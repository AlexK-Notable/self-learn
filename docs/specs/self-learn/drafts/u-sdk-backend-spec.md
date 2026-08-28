# Spec — U-sdk: the SDK backend

**Superseded in part 2026-08-28 by `U-fw117`** (FW-117 CLOSED,
`14-forward-work-map.md`): this spec quotes `write_repair_settings_file`'s
live-CLI-verified docstring at length as evidence for the sdk backend's
`settings=None` design -- the function itself is now DELETED (a dead
write nothing under the sdk backend ever read back). The evidence and
verification this spec records stay true as a historical measurement;
they are not undone by the function's deletion, they are simply no
longer readable from a function that no longer exists. The rest of this
document is left as written below -- it is the historical build record
for this unit's own contract at the time it shipped.

Status: **r4 — SOUND. Cleared for build; no further spec gate.** Unit
`U-sdk`, **Wave 1** of the approved Agent-SDK migration. Wave 0
(`U-seam`) is merged; this is the first unit in the repo that imports
`claude_agent_sdk` from the CLI package.

r1 draft → r2 (four operator rulings folded) → r3 (blind gate: NOT
SOUND — 2 BLOCKER / 4 MAJOR / 7 NOTE, all folded) → **r4 (delta gate:
SOUND — 0 BLOCKER / 0 MAJOR / 3 NOTE, folded under the repricing rule;
the code gate verifies downstream).** §11 maps every finding to its
change. The security core survived independent re-verification: the
gate read the installed transport source, re-probed the shared process
group, confirmed `F-A`/`F-B` verbatim, and traced the charter's
asymmetric resolve. **Both BLOCKERs are consequences of `Dep-1`** — the
dev dependency that makes this unit testable also makes nine shipped
tests, and two lockfiles, this unit's business. §3.13 and the may-touch
table are where that lands.

**The gate strengthened one argument rather than weakening it.** `K-1a`
claimed the third kill rung was needed because `asyncio.run` closes the
loop and strands the background `disconnect()`. The real reason is
sharper, and is now recorded in `K-1b`: the SDK's `close()` waits
**5 s gracefully before it sends any signal at all**, so a 2.5 s shielded
wait is abandoned *inside the first graceful window* — at that moment not
one signal has been sent to the child.

**Base commit:** `c2669a9` (master — *"chore: sync ui/uv.lock metadata for
the CLI's new [sdk] extra (U-seam follow-through)"*). Every symbol quoted
in this document was read at that commit. `worker.py`, `miner.py`,
`analyst.py`, `config.py` and every existing test file are **uncontended
and untouched by this unit**.

**The unit in one sentence.** Make `SELF_LEARN_BACKEND=sdk` work — ship
the `SdkBackend` that satisfies `U-seam`'s two-operation `Backend`
protocol by running a `ClaudeSDKClient` session instead of a `claude`
subprocess, reproducing each surface's containment as SDK objects rather
than as a settings file plus argv flags.

**This unit is a PORT, not a design.** Every load-bearing mechanism —
the session lifecycle, the interrupt/kill ladder, the shielded
`disconnect()`, the path-scoped `can_use_tool` callback with its
asymmetric resolve, the stream-json fake CLI — already ships and is
already green in `plugins/self-learn/ui`. §2 names the port sources line
for line. A builder who finds themselves inventing a mechanism the UI
already has has left this unit's mandate and must stop and report. The
things this unit genuinely *decides* are enumerated in §6 and nowhere
else.

**What is new, and therefore where the risk is.** Three things have no UI
precedent and are the parts a gate should read hardest: (i) the CLI's
containment is *write-glob shaped*, not *record-file shaped*, so the
charter's matcher is new code on a security boundary (§3.6); (ii) the CLI
call sites are **synchronous**, so an async SDK session has to be driven
from a sync frame and torn down before the event loop closes (§3.4, §3.7);
(iii) the CLI backend never had a budget, and this one does (§3.5, §7.3
`V-2`).

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/__init__.py` | **NEW.** Re-exports only: `SdkBackend`, `SdkOutcome`. |
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/backend.py` | **NEW.** `SdkBackend`, `run_sync`, the options builder, the message drain, the outcome mapping, the analyst text extraction. |
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/charter.py` | **NEW.** `build_can_use_tool`, `CharterPaths`, the glob matcher, `CharterPatternUnsupported`. |
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/lifecycle.py` | **NEW.** The kill ladder, the child-pid resolver, the pid sidecar, the start-of-run orphan sweep. The **only** module in this unit that sends a signal. |
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/events.py` | **NEW.** Tool-event / denial capture, the JSONL sink, retention. The **only** module in this unit that writes a file. |
| `plugins/self-learn/cli/src/self_learn/invocation_sdk/provider_env.py` | **NEW.** `provider_env(spec) -> dict[str, str]`. The single provider extension point (`PS-1`, §3.9). Ships returning `{}`. **`U-bedrock` owns this file's body**; nothing else in this unit may grow provider logic. |
| `plugins/self-learn/cli/src/self_learn/invocation/registry.py` | **The one edit to an existing file.** `_resolve`'s `sdk` branch only (§3.2) — the lazy-import target, which must resolve to this unit's sibling package. Quoted hunk; nothing else in the module changes. **Numstat-bounded**: `git diff --numstat c2669a9..HEAD -- …/registry.py` reports at most **6 insertions and 2 deletions**, in one hunk, all inside the `if value == "sdk":` block (`RS5`). |
| `plugins/self-learn/cli/tests/fixtures/fake_claude.py` | **NEW.** The stream-json fake CLI, ported from the UI's fixture of the same name (§3.10). |
| `plugins/self-learn/cli/tests/test_invocation_sdk.py` | **NEW.** Every criterion in §4 lands here. |
| `plugins/self-learn/cli/pyproject.toml` | `[dependency-groups] dev` gains `claude-agent-sdk` **only** (§3.11 `Dep-1`). `[project.optional-dependencies]` and `[project] dependencies` are **NOT** touched — `Dep-2`, `RS7`. |
| `plugins/self-learn/cli/tests/test_invocation.py` | **BLOCKER-1.** The **nine** tests enumerated in §3.13 `Sim-2` each gain a request for the absence fixture, plus **one** module-level import/fixture line. Nothing else. **Numstat-bounded**: ≤ **21 insertions / ≤ 9 deletions** — nine modified signature lines are 9 deletions **by construction**, plus the import line. Every changed line must fall inside a `def test_…` signature of the nine, or be the single import line; `SU4`'s structural AST bound governs (§0.1). No assertion, no body, no other test is touched. |
| `plugins/self-learn/cli/tests/conftest.py` | **Code-gate fold (2026-08-18), `BLOCKER-1`'s fix-proof.** Gains exactly ONE new `pytest.fixture(scope="session", autouse=True)` — `_no_real_sdk_spawn_tripwire`. Hard-blocks `claude_agent_sdk`'s `_find_cli()` for the whole suite (patches `SubprocessCLITransport._find_cli` to raise, restored in a `finally`); lives HERE rather than in `test_invocation_sdk.py` precisely because `Sim-1a` forbids an `autouse` fixture there. **Additive only** — the pre-existing `_worker_test_defaults` fixture is untouched. |
| `plugins/self-learn/cli/uv.lock` | **BLOCKER-2.** Re-locked by `Dep-1`. Bounded: `[package.dev-dependencies] dev` and `[package.metadata.requires-dev] dev` for the `self-learn-cli` member gain one entry each. **No `[[package]]` stanza is added or removed and no locked version changes** — measured: the lock already carries `claude-agent-sdk 0.2.134` and its transitive `anyio` / `mcp` / `sniffio` for the `[sdk]` extra (`RS8`). |
| `plugins/self-learn/ui/uv.lock` | **BLOCKER-2.** The `self-learn-cli` workspace member's `[package.metadata.requires-dev]` block **only** — today the single line `dev = [{ name = "pytest", specifier = ">=8.0" }]`. Nothing else in the file. Precedent: base commit `c2669a9` is exactly this class of sync (`+5 −1`, metadata only) (`RS8`). |
| `docs/specs/self-learn/03-decisions.md` | New row `S-36` (§7.5), landing in the same commit as the build. |
| `docs/specs/self-learn/14-forward-work-map.md` | New rows for §7.3's residuals, landing in the same commit. |

**`test_lock_invariant.py` and `test_attrib.py` may NOT be edited** —
they stay sha-pinned (`SU5`), and that constraint is what forced this
unit's package **placement** (§3.1), for which three shipped guards are
the reason (`G-1`, `G-2`, `G-3`). `test_invocation.py` is the **one**
exception, granted by the BLOCKER-1 ruling and bounded to the enumerated
nine-test fixture edit above; the placement argument is unaffected,
because `HY2`/`HY4`/`WR7` — the three guards that forced the placement —
are **not** among the nine and stay byte-identical.
`plugins/self-learn/ui/**` is otherwise untouched: it is the port
**source** (§2), and `U-seam` §7.2's no-touch ruling still stands.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced
   by name thereafter. A second definition anywhere is a bug in this
   document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number.
4. Read before this document: `docs/specs/self-learn/drafts/u-seam-invocation-seam-spec.md`
   §§3.1–3.8 (the seam contract this unit implements), and the three
   probe memos named in §2.2. This spec quotes them but does not
   reproduce them.
5. **Verify-at-build (§8) is not optional.** Every fact in §8 was
   measured on **SDK 0.2.121 / CLI 2.1.226** while writing this spec, and
   every one of them must be **re-confirmed against the resolved SDK at
   build time**, from the installed source or a live probe — never from
   memory and never from this document alone. A §8 row that fails
   re-confirmation is a spec defect to report, not a thing to work
   around.

---

## 1. Why this unit exists

`U-seam` shipped the seam and the refusal. Today, selecting `sdk` at any
precedence rung raises `BackendUnavailable` from `backend_for`, the two
entry points catch it, and every surface degrades exactly as it does for
a missing CLI. The extra `self-learn-cli[sdk]` is declared, so the error
message's install command is true — but installing it changes nothing.

This unit makes the extra load-bearing. After it merges,
`SELF_LEARN_BACKEND_ANALYST=sdk` runs the analyst through a
`ClaudeSDKClient` session, and `pip install 'self-learn-cli[sdk]'` is the
difference between that working and the same byte-pinned refusal.

**What the seam gives a backend, and what it does not.** `SessionSpec`
carries `surface`, `prompt`, `cwd`, `timeout`, `containment`, `log`,
`label`, `timeout_display`, and two closures (`cli_argv_builder`,
`cli_settings_writer`). It does **not** carry a model name, a system
prompt, or an SDK option of any kind — `U-seam` §3.4 froze that shape and
this unit may not widen it (**`G-0`**). §3.3 is where that gap is closed, and
it is closed by reading the surface's own argv, which `U-seam` already
blessed as an independent witness (`CN10`).

---

## 2. What this unit ports, and from where

### 2.1 In-house sources (READ ALL FOUR BEFORE BUILDING)

| Source | What ports | What does **not** |
|---|---|---|
| `plugins/self-learn/ui/src/self_learn_ui/engine/sdk.py` | `SdkPaneEngine.interrupt`/`close`'s ladder, `_ABANDONED_DISCONNECTS` + `_log_abandoned_disconnect`, the option-set shape, `_map_result`'s defensive `getattr`s, the "tolerate unknown message types" drain | Streaming (`include_partial_messages`, `StreamEvent` mapping, `PaneEvent`), the in-process MCP proposal server, `session_store`/`resume`, `fallback_model`, the `uilog` sink |
| `.../engine/charter.py` | The deny-by-default structure, `_PATH_KEYS`, `_under_any`, the deny-reason discipline, and — **verbatim, including its comment** — the asymmetric resolve | The three read roots (`self_learn.hosts.canon_read_roots`, `plugin_references_dir`), `zero_write`, `extra_allowed_tools`, the record/proposal path triple. **No CLI surface scopes reads by path** (`C-2`), so that whole apparatus has no counterpart here |
| `.../engine/base.py` | Nothing directly — it is the UI's own seam, and `U-seam`'s `Backend` protocol is this unit's seam | The `PaneEngine` ABC, `PaneEvent`, `PaneContext`, `FakeEngine` |
| `plugins/self-learn/ui/tests/fixtures/fake_claude.py` | The whole control-protocol skeleton: initialize handshake, one-user-message-selects-a-scenario, generic control_request success, the NDJSON message shapes | The pane-specific scenarios; §3.10 lists this unit's own |

**`P-a` (NORMATIVE).** Where a mechanism exists in the UI source, the
port reproduces it. A deliberate divergence is legal only if it is listed
in §6 with its reason. An *undocumented* divergence is a defect.

**`P-b` — the asymmetric resolve ports verbatim, comment included.**
`charter.py` carries this, and it is the single most important sentence
in the port source:

> *Deliberately NOT `.resolve()`d past the (trusted) bucket root: the
> write-target paths below are the CANONICAL reference point a request is
> judged against, and resolving them would follow any symlink an attacker
> planted AT that exact filename, silently rebasing the "expected" path
> onto wherever the symlink points — defeating the check for the one case
> it exists to catch. Only the REQUESTED path (the model-supplied,
> untrusted `tool_input`) gets the full symlink-following `.resolve()`.*

§3.6 states the CLI-shaped form of that rule; criteria `CH4`/`CH5` are its
positive and negative controls.

### 2.2 Probe memos — the settled footguns (NORMATIVE)

All three live under `docs/specs/self-learn/research/`. Their findings are
normative in this spec; §8 requires each to be re-confirmed on the
resolved SDK.

- `2026-07-12-sdk-pane-probes.md` — footguns **A**, **B**, **C** below,
  plus the 48,866 / 3,027-token `setting_sources` measurement.
- `2026-07-12-sdk-auth-empirical-test.md` — subscription OAuth works; the
  SDK reads the same credential chain as `claude -p`, so no auth work is
  in scope. Its second finding (the SDK loads `~/.claude` by default) is
  footgun C's measurement.
- `2026-07-18-sdk-bundle-exclusion.md` — `_find_cli()` prefers the
  package-relative `_bundled/` CLI, then falls back to
  `shutil.which("claude")`.

**`F-A` — `ClaudeSDKClient` ONLY, never string-prompt `query()`.**
`query(prompt="...", can_use_tool=...)` raises
`ValueError: can_use_tool callback requires streaming mode`. A finite
`AsyncIterable` does not rescue it either — the probe measured every
gated call failing with *"Tool permission request failed: Error: Stream
closed"*, the callback never firing, and the agent burning turns. Only
`ClaudeSDKClient` keeps the bidirectional control stream open.
Criterion `OP1`; mutation `M1`.

**`F-B` — `allowed_tools=[]` everywhere; any entry SHADOWS the callback.**
The SDK itself warns `CanUseToolShadowedWarning: can_use_tool will not be
invoked for: …`. An entry that allows a whole tool auto-approves it
*before* the callback is consulted. Criterion `OP2`; mutation `M2`.

**`F-C` — `setting_sources=[]` explicitly on every surface.** Leaving it
unset does **not** mean "no settings" on this host: the probe measured
the unset variant byte-identical to `["user","project","local"]` — 48,866
cached prefix tokens, 139 slash commands, 13 plugins, **13 hooks fired**,
and `permissionMode: dontAsk` inherited from the user's own
`~/.claude/settings.json`. `[]` measured 3,027 tokens and zero hooks.
The inherited permission mode is the part that matters most: it would
neuter the callback. Criterion `OP3`; mutation `M3`.

**`F-D` — NEW, found while writing this spec, not in any memo.**
`ClaudeAgentOptions.system_prompt` defaults to `None`, and
`SubprocessCLITransport._build_command` renders `None` as
`cmd.extend(["--system-prompt", ""])` — an **empty** system prompt, not
an absent flag. The four CLI surfaces emit no system-prompt flag at all
and therefore get Claude Code's default system prompt. A build that
leaves `system_prompt` at its default silently strips the system prompt
from every worker, miner and analyst session — a large, invisible
capability regression that no failure leg would report. §3.3 `A-3` is the
fix; criterion `OP10`; mutation `M11`. **§8 row 1 re-confirms it.**

---

## 3. The change

### 3.1 `Loc-1` — where this package lives, and why it is not inside `invocation/` (NORMATIVE)

`plugins/self-learn/cli/src/self_learn/invocation_sdk/`, **six modules**,
a sibling of `invocation/` and not a member of it:

| Module | Contains | May import |
|---|---|---|
| `backend.py` | `SdkBackend`, `SdkOutcome`, `run_sync`, `_build_options`, `_drive`, `_map_outcome`, `_extract_text` | stdlib, `claude_agent_sdk`, `..invocation` (contract only), `.charter`, `.lifecycle`, `.events`, `.provider_env` |
| `charter.py` | `build_can_use_tool`, `CharterPaths`, `CharterPatternUnsupported`, the matcher | stdlib, `claude_agent_sdk` (permission types), `..invocation` (contract only) |
| `lifecycle.py` | the kill ladder, `child_pid_of`, the pid sidecar, `sweep_orphans` | stdlib, `.. import worker` (module object) |
| `events.py` | `EventLog`, the JSONL sink, `prune_event_logs` | stdlib, `.. import worker` (module object) |
| `provider_env.py` | `provider_env` | stdlib **only** |
| `__init__.py` | re-exports only | the five above |

**`L-a` — this placement is FORCED, and the three forcing guards are
measured.** The obvious home for an `SdkBackend` is `invocation/sdk.py`,
next to `invocation/cli.py`. It is not available:

- **`G-1` — `HY2` forbids it.** `test_invocation.py::test_hy2_no_module_in_invocation_imports_the_forbidden_modules`
  AST-walks `invocation_dir.glob("*.py")` and rejects any `import`/
  `ImportFrom` naming `worker`, `miner`, `analyst`, `verbs`, `teach` or
  `ledger_ops` — **including a function-local one** (`ast.walk`, not a
  module-header scan). This unit needs `worker.cache_dir()` and
  `worker._pid_alive` (§3.7, §3.8). Inside `invocation/`, it cannot have
  them.
- **`G-2` — `HY4` forbids it.** `test_invocation.py::test_hy4_no_filesystem_writes_in_invocation_except_fakebackend_writes`
  scans the same glob for `open` / `write_text` / `mkdir` / `unlink` /
  `touch` calls, allows exactly `{("fake.py","mkdir"), ("fake.py","write_text")}`,
  and **asserts `len(violations) == 2`**. The pid sidecar and the
  tool-events JSONL are writes. Inside `invocation/`, they redden a test
  this unit may not edit.
- **`G-3` — the root level forbids it too.**
  `test_lock_invariant.py`'s `NOT_REPO_TRUTH` census parses
  `SRC.glob("*.py")` — root-level `self_learn/*.py` — fail-closed: every
  function reaching a filesystem-mutating leaf from a root must either
  hold a lock or carry an explicit exemption entry. A root-level
  `self_learn/sdk_backend.py` writing the sidecar would need a
  `NOT_REPO_TRUTH` entry, i.e. an edit to `test_lock_invariant.py`.

A **subpackage** is outside all three globs. `HY2`'s scope rule (`I-a`:
*"No module in this package…"*) genuinely does not reach a sibling
package, so this is correct scoping rather than evasion — `invocation/`
stays pure, and the module that needs `worker` is not in it.

**`L-b` — the invisibility is DECLARED and re-covered in-package, not
exploited.** `U-seam` `B-6` recorded that the lock census is root-level
blind and built `HY4` because of it; repeating that hole one level down
would be a fresh instance of **`U-seam`'s `M30`** — the
witness-collapse-by-deduplication mutation that unit named as the one it
most feared. *(Qualified deliberately: this document has its own `M30`,
an unrelated pid-sidecar row.)* So `U-sdk` ships the two guards for its
own package, in its own new test file:

- `PL3` — every filesystem write in `invocation_sdk/` is enumerated
  against a written-down allow-list **with an exact count**, the same
  shape `HY4` uses.
- `PL4` — every path this package writes resolves under
  `worker.cache_dir()`, never inside a git repository and never under the
  resolved ledger home. That is the *property* `NOT_REPO_TRUTH` entries
  claim, asserted directly instead of declared.

**`L-c` — a nested `invocation/sdk/` subpackage is REFUSED.** It would
have identical test-visibility to `invocation_sdk/` while violating
`I-a`'s stated design rule in spirit — a module inside the package that
imports `worker`. Placement outside is the honest form of the same
mechanical outcome.

**`L-d` — no module under `src/self_learn/` may CALL `write_session(...)`
or `text_session(...)`.** `test_invocation.py::test_wr7_seam_is_only_called_from_the_three_call_sites`
`rglob`s the whole source tree and asserts the *call* sites are exactly
`{"worker.py", "miner.py", "analyst.py"}`. `invocation_sdk/` **is** inside
that rglob. `SdkBackend.write_session` / `.text_session` are **definitions**
(not counted) and must delegate to a differently-named private method —
`self._run(spec)`. A build in which `text_session` calls
`self.write_session(spec)` adds `invocation_sdk/backend.py` to `WR7`'s
site set and reddens a test this unit may not edit. Criterion `PL5`;
mutation `M6`.

**`I-c`** No module in `invocation_sdk/` may import `miner`, `analyst`,
`verbs`, `teach` or `ledger_ops`. `worker` is permitted, and only for
`cache_dir` and `_pid_alive`. Criterion `PL2`.

**`I-d`** The `worker` import is `from .. import worker` (the module
object) at module scope in `lifecycle.py` and `events.py`, and every use
is `worker.cache_dir()` / `worker._pid_alive(...)` at call time —
`U-seam` `B-3a`'s rule, so a test's `monkeypatch.setattr(worker, …)` is
observed. No cycle is created: `worker` imports `invocation`, and
`invocation/registry.py` imports `invocation_sdk` **lazily, inside
`_resolve`** (§3.2). Criterion `PL6` proves it in a fresh interpreter, in
both import orders.

### 3.2 `Reg-2` — the registry's lazy branch, the one edit (NORMATIVE)

`invocation/registry.py`'s `_resolve` currently reads:

```python
    if value == "sdk":
        raise BackendUnavailable(_SDK_UNAVAILABLE_MESSAGE)
```

It becomes:

```python
    if value == "sdk":
        try:
            from ..invocation_sdk import SdkBackend
        except ImportError as exc:
            raise BackendUnavailable(_SDK_UNAVAILABLE_MESSAGE) from exc
        return SdkBackend()
```

**`R-d`** `_SDK_UNAVAILABLE_MESSAGE` is **not** re-spelled, re-worded or
moved. It stays the byte-pinned two-line string `U-seam` §3.7.4 froze,
and `RG4`/`RG5` in `test_invocation.py` keep passing unchanged when
`claude_agent_sdk` is absent. Criterion `RS2`; mutation `M28`.

**`R-e`** The import is **lazy** (inside `_resolve`), for two independent
reasons, both binding: it keeps `invocation/` importable on a machine
without the extra, and it is what makes `I-d`'s cycle-freedom hold.
Criterion `RS3`.

**`R-f`** `except ImportError` — not a bare `except`. A `claude_agent_sdk`
that imports but raises something else must not be silently reported as
"not installed"; it propagates. Criterion `RS4`; mutation `M29`.

**`R-g`** Nothing else in `registry.py` changes. The five-rung chain, the
two warning spellings, `config._warn`, `KNOWN_BACKENDS`, `_dispatch`'s
`SURFACES` validation and both entry points are untouched. Criterion `RS5`
is a `git diff` instrument criterion over that file, **numstat-bounded**
per the may-touch table.

**`R-h` — the import target must RESOLVE to this unit's sibling package,
and that is asserted by identity, not by spelling (§10 `V-1`).**
`from ..invocation_sdk import SdkBackend` is the only legal target: not
`..invocation.sdk` (which `L-a` forbids from existing at all), not a
top-level `self_learn.sdk_backend` (`G-3`), not a re-export through some
other module. `RS6` asserts that the **type of** the object `backend_for` returns is
identical to the independently-imported class —
`type(backend) is self_learn.invocation_sdk.SdkBackend` — so a same-named
class reached by any other route fails. *(The r2 prose said the returned
object "is" the class; `backend_for` returns an **instance**, and the
identity is on its type. NOTE-5.)* A wrong target degrades *quietly* into the
`BackendUnavailable` path (the `except ImportError` swallows it and the
operator is told to install an extra that is already installed), which is
exactly the shape that would survive a green suite without `RS6`.
Mutation `M58`.

### 3.3 `Argv-1` — the two facts read from argv, and nothing else (NORMATIVE)

`SessionSpec` carries no model and no system prompt (`G-0`). The surface's
own argv does. `SdkBackend` therefore builds the argv exactly as
`CliBackend` does — **settings writer first, then argv builder** —
and reads **exactly two** values out of it:

| Read | Source in argv | Lands on |
|---|---|---|
| model | the element after `--model` | `options.model` |
| doctrine | the element after `--append-system-prompt` | `options.system_prompt`'s `append` |

**`A-1`** The argv is obtained as
`argv = spec.cli_argv_builder(spec.cli_settings_writer() if spec.cli_settings_writer is not None else None)`
— identical to `CliBackend._run`'s first two statements, and pinned in
that **order** (`U-seam` `AV3`). It is not optional: `miner._reader_cli_argv_builder`
asserts its argument is not `None`, so a backend that skipped the writer
would raise `AssertionError` on the miner surface. Criterion `OP12`;
mutation `M13`.

**`A-2`** The settings file **is written** (side effect preserved) and
`options.settings` **is `None`** (the file is not handed to the SDK). This
pair is one criterion because it is one decision: a settings file's
`permissions.allow` rules **shadow `can_use_tool`** exactly as
`allowed_tools` entries do (`F-B`'s warning text names settings files
explicitly), so handing the CLI's own allow rules to the SDK would
auto-approve precisely the writes the charter exists to gate. Under
`setting_sources=[]` the charter is the **only** permission authority, by
construction. Criterion `OP4`; mutation `M4`.

**`A-3`** `options.system_prompt` is:

| Condition | Value |
|---|---|
| argv contains `--append-system-prompt V` | `{"type": "preset", "preset": "claude_code", "append": V}` |
| otherwise | `{"type": "preset", "preset": "claude_code"}` |

**never `None`, never a bare `str`.** `None` renders `--system-prompt ""`
(`F-D`); a bare `str` renders `--system-prompt V`, replacing Claude
Code's system prompt instead of appending to it. Only the analyst emits
`--append-system-prompt` today; the other three take the second row.
Criterion `OP10`; mutations `M11`, `M12`.

**`A-4`** A missing `--model` is not an error: `options.model = None` and
the CLI's own default applies. A flag present as the argv's **last**
element with no value after it is treated as absent, never as an
`IndexError`. Criterion `OP11`.

**`A-5` — the read set is CLOSED.** `backend.py` reads exactly the two
flags of `A-1`'s table out of argv. It may not read `--allowedTools`,
`--disallowedTools`, `--settings`, `--strict-mcp-config` or anything else
— those are the `Containment`'s job, and reading them from argv would
re-collapse the two witnesses `U-seam` spent a whole unit separating.
Criterion `OP13` enumerates the read set from source; mutation `M14`.

### 3.4 `Sync-1` — `run_sync` (NORMATIVE)

All three call sites are synchronous functions. The SDK session is a
coroutine. `run_sync` is the only bridge, and it lives in `backend.py`.

```python
def run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T
```

**`Y-a`** It takes a **factory**, not a coroutine object. A coroutine
created in one thread's frame and awaited inside a different loop is a
`RuntimeError` waiting to happen; the factory is called *inside* the
target loop's thread. Criterion `SY4`; mutation `M17`.

**`Y-b`** Two branches, selected by `asyncio.get_running_loop()`:

| Condition | Behavior |
|---|---|
| no running loop in this thread (`RuntimeError`) | `return asyncio.run(factory())` |
| a loop is already running | run `asyncio.run(factory())` on a **dedicated non-daemon thread**, `join()` it, and re-raise anything it raised |

Criteria `SY1`, `SY2`.

**`Y-c`** Exceptions propagate **with their original type and their
`__traceback__`**, from *both* branches. This is not cosmetic: `U-seam`
`T-c`/`TR4` requires a bare `OSError` to escape `analyst.analyze`
uncaught, and a wrapper that converted it to a generic error would
silently repair a defect this project deliberately preserves (`R-1`).
Criterion `SY3`; mutation `M18`.

**`Y-d`** The `join()` is unbounded. It is safe because the coroutine is
itself bounded: `asyncio.wait_for(…, timeout=spec.timeout)` plus the kill
ladder (§3.7) means the coroutine cannot outlive the surface's own
timeout by more than the ladder's fixed window. A `join(timeout=…)` would
add a second, weaker bound whose expiry has no remedy — a Python thread
cannot be killed — and would return control while a live session
continued in the background. Criterion `SY5`.

**`Y-e` — measured: no shipped in-process caller runs inside a loop
today.** The UI drives resolution verbs through `VerbRunner`, which
spawns a subprocess; it imports `self_learn.worker` for `cache_dir`,
`package_skill_refs` and `STALE_AFTER_SECS`, and calls neither
`worker.run` nor `analyst.analyze` in-process. The second branch of `Y-b`
is therefore a **forward guarantee** for the UI/SDK convergence, not a
fix for a live bug. It is specified, tested and mutated anyway — an
untested fallback is a fallback that does not work when it is finally
needed. §7.3 `R-4` records the honest status.

### 3.5 `Opt-1` — the option set, per surface (NORMATIVE)

`_build_options(spec) -> ClaudeAgentOptions`. Every field this unit sets,
and nothing else:

| Field | Value | Why |
|---|---|---|
| `cwd` | `str(spec.cwd)` | `U-seam` `T-a` — all four surfaces run in the ledger home |
| `system_prompt` | `A-3`'s table | `F-D` |
| `model` | `A-1`'s table, or `None` | `A-4` |
| `allowed_tools` | `[]` — **always, every surface** | `F-B` |
| `disallowed_tools` | `D` (§3.6) | the containment, transcribed |
| `can_use_tool` | the charter callback (§3.6) | the containment, enforced |
| `permission_mode` | `"default"` — **always, every surface** | `O-2` below |
| `setting_sources` | `[]` — **always** | `F-C` |
| `settings` | `None` — **always** | `A-2` |
| `strict_mcp_config` | `True` — **always** | `O-3` below |
| `mcp_servers` | `{}` | no surface has an MCP server |
| `include_partial_messages` | `False` | no CLI surface has a streaming consumer (`U-seam` §7.4) |
| `env` | `provider_env(spec)` (§3.9) | the one provider extension point |
| `cli_path` | `os.environ.get("SELF_LEARN_SDK_CLI_PATH") or None` | `O-4` below |
| `max_turns` | `O-1`'s table | budget guard 2 |
| `max_budget_usd` | `O-1`'s table | budget guard 3 |

**`O-0` — the option set is assembled as a MAPPING, and that mapping is
the observation point (MAJOR-1).** `_build_options` is split in two:

```python
def options_kwargs(spec: SessionSpec) -> dict[str, object]: ...
def _build_options(spec: SessionSpec) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(**options_kwargs(spec))
```

The r2 draft asserted the field set by **AST-scanning the
`ClaudeAgentOptions(...)` call for keywords**, which contradicts `O-1a`:
a `**kwargs` construction has **zero** AST keywords, so the scan would
report an empty set for the very build the spec requires. The mapping
returned by `options_kwargs` is the seam where the set is both *complete*
and *observable*, and it is where `OP14` looks. **No AST scan of the
construction call is written.**

**`O-0a` — every `options.*` assertion in §4 observes the object actually
passed to `ClaudeSDKClient`**, captured by a **constructor spy**
(`monkeypatch.setattr(backend_module, "ClaudeSDKClient", spy)`), not the
return value of `_build_options` called separately by the test. A build
that assembles correct options and then passes a different object would
otherwise be invisible. `OP14` ties the two together: the spy-captured
object's fields equal `options_kwargs`'s mapping.

**No other field is set.** `fallback_model`, `session_store`, `resume`,
`session_id`, `hooks`, `agents`, `skills`, `plugins`, `add_dirs`,
`sandbox`, `betas`, `thinking`, `effort`, `output_format`,
`enable_file_checkpointing`, `extra_args`, `include_hook_events`,
`max_thinking_tokens`, `task_budget`, `user`, `stderr`, `tools` are all
left at their defaults. Criterion `OP14`; mutation `M15`.

**`tools` staying at its default is load-bearing, not incidental.**
`tools=None` is what keeps `--tools` **out of argv entirely**; setting it
to the `claude_code` preset would emit `--tools default` and change the
CLI's base tool set on every surface.

**`O-1` — the three budget guards.**

| Guard | Value | Env override | Default |
|---|---|---|---|
| wall clock | `asyncio.wait_for(…, timeout=spec.timeout)` | — (the surface's own) | **mandatory, never absent** |
| turns | `options.max_turns` | `SELF_LEARN_SDK_MAX_TURNS_<SELECTOR>` | `worker`/`worker-repair` **120**, `miner-reader` **60**, `analyst` **30** |
| spend | `options.max_budget_usd` | `SELF_LEARN_SDK_MAX_BUDGET_USD` | **`None`** — wired, unset |

`<SELECTOR>` is `SELECTOR_FOR_SURFACE[spec.surface]` (`U-seam` §3.2), so
the repair round is never independently configurable — the same rule
that governs backend selection.

**`O-1b` — why spend is UNSET and turns are GENEROUS (ruled, §10 `V-2`).**
The wall clock is the real bound; the other two are second-line ceilings
behind it.

- **Spend unset is not an exposure regression.** The CLI path today has
  **no dollar cap at all** and carries the identical unattended exposure
  — the nightly worker and miner already run uncapped. Shipping the sdk
  backend uncapped-by-default therefore changes nothing about the risk
  the operator already carries, while shipping it capped-by-default would
  introduce a truncation failure mode no shipped run has ever had. The
  knob exists (`SELF_LEARN_SDK_MAX_BUDGET_USD`) for anyone who wants one
  today.
- **The numbers are guesses, and the unit says so rather than dressing
  them up.** No shipped run has ever been counted in turns or dollars.
  `SdkOutcome` records `cost_usd` and `turns` and the JSONL sink persists
  them (`E-2`, `E-3`), so **burn-in produces the actual distribution** and
  a post-burn-in unit sets informed defaults from measured data instead
  of from this table. §7.3 `R-7` carries that as a residual with an
  owner.

Criteria `OP7`, `OP8`, `OP9`; mutations `M8`, `M9`, `M10`.

**`O-1a` — an unappliable cap DEGRADES LOUDLY, never silently.**
`max_turns` and `max_budget_usd` are applied only if the field is present
on the resolved `ClaudeAgentOptions` (checked via
`{f.name for f in dataclasses.fields(ClaudeAgentOptions)}`, not
`hasattr` on an instance). When a requested cap cannot be applied,
`SdkBackend` emits **one** line through `spec.log`:

```
run: sdk backend could not apply {field} on this claude-agent-sdk version
```

Feature detection that silently drops a guard is a fail-open shape; the
log line is what makes it fail *visible*. The wall-clock guard is never
feature-detected — it is ours. Criterion `OP9`; mutation `M10`.

**`O-2` — `permission_mode="default"` unconditionally, and NOT derived
from `containment.default_mode`.** On the CLI, `default_mode is None`
means the settings file omits `permissions.defaultMode` and the host's
own `~/.claude/settings.json` wins — on this host, `bypassPermissions`
(measured; it is why `U-attrib`'s `GR-a` hotfix exists). Under
`setting_sources=[]` there is no host settings file loaded at all, so
there is nothing to inherit and nothing to reproduce. Deriving the mode
from the containment would, on `SELF_LEARN_ENFORCE_SCOPE=0`, hand the SDK
a mode that shadows the callback and make the entire containment
decorative. **The rule is narrowing-only: where the SDK backend cannot
reproduce a CLI boundary exactly, it reproduces the narrower one.**
Criterion `OP5`; mutation `M5`.

**This does NOT mean `SELF_LEARN_ENFORCE_SCOPE=0` stops working** — the
r1 draft proposed exactly that and it was **overruled** (§10 `V-2`…`V-4`;
silently ignoring an incident-window escape hatch is the fail shape this
campaign hunts). The variable keeps its meaning, honored **in the charter
callback** rather than in the option set: `C-10`. The fencing is the
point — the hatch changes what the callback *approves*, and changes
`permission_mode`, `setting_sources` and `strict_mcp_config` **not at
all**, so the shadowing hazard this paragraph identifies stays closed.
Criterion `CH12` is that fence, asserted directly.

**`O-3` — `strict_mcp_config=True` unconditionally, and NOT derived from
`containment.strict_mcp`.** The containment says `True` on the two worker
surfaces and `False` on the miner and analyst. With `mcp_servers={}` and
`setting_sources=[]` there is no MCP config to load on any surface, so
`True` is belt on "nothing to connect to" and is the strictly narrower
value everywhere. This is `O-2`'s narrowing-only rule applied a second
time, and it is a **documented divergence** from the containment record
(§6 `D-6`). Criterion `OP6`; mutation `M7`.

**`O-4` — `cli_path`.** `SELF_LEARN_SDK_CLI_PATH`, when set, is passed
verbatim; unset yields `None` and the SDK resolves the CLI itself
(`_bundled/` first, then `shutil.which("claude")` — the bundle-exclusion
memo). Tests point it at §3.10's fake. Criterion `OP15`.

### 3.6 `Charter-1` — the permission callback (NORMATIVE)

This is the security surface and the only genuinely new code in the unit.

**`C-1` — the three sets, defined once.**

```
W  = {"Write", "Edit", "NotebookEdit"}                       # the write family
D  = [t for t in (containment.disallowed_tools or "").split(",") if t]
A  = [t for t in (containment.allowed_tools   or "").split(",") if t]
P  = ("file_path", "path", "notebook_path")                  # ported verbatim from charter.py
```

`D` also lands on `options.disallowed_tools`; `A` never reaches
`options.allowed_tools` (`F-B`) and is consulted **only** inside the
callback.

**`C-2` — no CLI surface scopes reads by path, and that is why the UI's
read-root apparatus does not port.** Measured on master:

| Surface | `allowed_tools` | `disallowed_tools` |
|---|---|---|
| `worker`, `worker-repair` | `worker.ALLOWED_TOOLS` = `"Read,Grep,Glob"` | `worker.DISALLOWED_TOOLS` = `"Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"` |
| `miner-reader` | `None` | `miner.READER_DISALLOWED_TOOLS` = `worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"` |
| `analyst` | `analyst.ANALYST_ALLOWED_TOOLS` = `"Read,Grep,Glob"` | `None` |

Reads are allowed **at any path** on the worker and analyst, and
**structurally denied** on the miner. So the probe-2 open question — do
reads outside `cwd` reach `can_use_tool`? — **does not bind this unit at
all**: on the two surfaces where reads are permitted the callback would
allow them anywhere, and on the surface where they are not, `D` denies
them before any callback runs. §8 row 6 still asks the question, because
`U-bedrock` and later units may care; U-sdk's correctness does not.

**`C-3` — the write family is the ONLY path decision, and `Edit` is
DENIED while `Write` is GATED.** This inverts the naive reading and is
quoted from `worker.write_permission_rules`'s own docstring, verified
against the live CLI on 2026-07-15:

> *file-write scoping rides the `Edit(...)` rule FAMILY (**it governs
> Write too**); `Write(path)` rules match nothing. The Edit TOOL itself
> stays in DISALLOWED_TOOLS.*

So on the CLI the model writes with **`Write`**, permitted by
`Edit(/…)`-family rules; the **`Edit` tool** is structurally denied by
`DISALLOWED_TOOLS`. A charter that allowed `Edit` on matching paths and
denied `Write` would invert the shipped boundary while looking correct.
Criterion `CH1`; mutation `M19`.

**`C-4` — the decision order, deny-by-default.** In this order, first hit
wins:

1. `tool_name in D` → **DENY** (belt; `options.disallowed_tools` is the
   braces and normally fires first).
2. **the enforcement hatch (`C-10`) is open** → **ALLOW**.
3. `tool_name in W` → path decision (`C-5`). Allow only if the resolved
   requested path matches; else DENY.
4. `tool_name in A` → **ALLOW** (unscoped — `C-2`).
5. → **DENY**, always, with a reason naming the tool.

There is no path that grants by omission, and the hatch at step 2 sits
**below** the structural deny at step 1 — deliberately, because that is
where it sits on the CLI (`C-10`). Criterion `CH2`; mutation `M20`
(step 5 flipped to allow).

**`C-10` — the enforcement hatch: `SELF_LEARN_ENFORCE_SCOPE=0` keeps its
meaning, and the mirror is SOURCED (NORMATIVE).**

What the variable does on the CLI, read from master rather than assumed:

- `worker._enforce_scope()` is `os.environ.get("SELF_LEARN_ENFORCE_SCOPE") != "0"`.
- Its only consumers are `worker.write_settings_file`,
  `worker.write_repair_settings_file`, and the two
  `containment_for(..., enforce=_enforce_scope())` call sites in `run()`.
  When false, `permissions.defaultMode` is **omitted** from the settings
  file and `Containment.default_mode` is `None`.
- The consequence is quoted from `write_repair_settings_file`'s own
  docstring, verified there against the live CLI 2.1.226: this host's
  `~/.claude/settings.json` sets `permissions.defaultMode:
  bypassPermissions`, *"which … voids any settings-file scope that omits
  the key."* The **write scope stops enforcing**. `--disallowedTools` is
  a CLI flag rather than a permission rule and is **unaffected**.
- **`miner.write_reader_settings` hardcodes `"defaultMode": "default"`**
  and the analyst passes no `--settings` at all, so neither surface is
  reachable by the variable today.
- **The CLI path emits NO log line** when the switch is off — measured:
  no `log(` accompanies any `_enforce_scope()` call site. Per the parity
  rule, the hatch is therefore **silent** here too.

The mirror, stated as a property of the containment **data** rather than
as an environment read — so the variable reaches the charter through
`_enforce_scope()` → `containment_for(enforce=…)` → `default_mode`, the
chain `U-seam` already built, and `charter.py` never touches
`os.environ`:

> **The hatch is OPEN iff `containment.default_mode is None` AND
> (`containment.write_globs` or `containment.write_exact`) is non-empty.**

Both conjuncts are load-bearing, and the second is what makes the first
safe:

| Containment | `default_mode` | write sets | Hatch | Matches the CLI because |
|---|---|---|---|---|
| `worker`, `ENFORCE_SCOPE=0` | `None` | non-empty | **OPEN** | the settings scope is voided |
| `worker`, default | `"default"` | non-empty | closed | the scope enforces |
| `worker-repair`, `ENFORCE_SCOPE=0` | `None` | non-empty (the repair set `E`) | **OPEN** | same |
| `miner-reader`, any | `"default"` | non-empty | closed | the miner hardcodes the key |
| `analyst`, any | `None` | **empty** | closed | there is no write scope to un-enforce; the analyst is read-only by construction (`ANALYST_ALLOWED_TOOLS = "Read,Grep,Glob"`) |
| `DEGRADED_WORKER_CONTAINMENT` | `None` | **empty** | closed | it describes nothing and may grant nothing |

Without the second conjunct, `default_mode is None` alone would open the
hatch on the **analyst** — whose `D` is empty, so step 1 catches nothing
and the charter would approve every tool including `Write` and `Bash`.
That is mutation `M53`, and `CH11` is the criterion that catches it.

**A repair round with an empty `E` leaves the hatch closed.** `run()`
never reaches the repair invocation with an empty set, and closed is the
narrower direction, so the edge is stated rather than special-cased.

Criteria `CH10` (open), `CH11` (closed, four legs), `CH12` (the option-set
fence), `CH13` (silence parity). Mutations `M53`–`M57`.

**`C-5` — the match rule, and the asymmetric resolve (`P-b`) in CLI
shape.** Computed **once**, at callback-build time:

- For each pattern `g` in `containment.write_globs`: split `g` on `/`.
  The **trusted prefix** is the longest leading run of segments
  containing none of `*`, `?`. The prefix is resolved exactly once with
  `Path(prefix).resolve()`; the remaining segments are re-joined
  **verbatim, unresolved**.
- For each path `e` in `containment.write_exact`: the trusted prefix is
  `Path(e).parent`, resolved once; the **final segment is appended
  verbatim and never resolved** — that leaf is exactly where a planted
  symlink would rebase the expectation.

Per call, the requested path is `Path(raw).resolve()` — full symlink
following — where `raw` is the first non-empty string value among `P`.
A `W`-family call with no resolvable target path is **DENIED**, never
allowed (ported verbatim from `charter.py`'s `_extract_target_path`
branch). Criteria `CH3` (no target → deny), `CH4` (leaf symlink →
deny: proves the expected side was **not** resolved), `CH5` (**negative
control** — a symlink in the *directory chain above* the trusted prefix
→ **allow**: proves the prefix **is** resolved, so a build that "fixes"
`CH4` by resolving nothing at all breaks every deployment whose `/home`
is a symlink and is caught here). Mutations `M21`, `M22`.

**`C-6` — the glob semantics, stated because they are re-implemented.**
The CLI's rules use gitignore-flavored `**`. Python's `fnmatch` does not:
its `*` crosses `/`, which would **widen** the boundary. The matcher
translates the wildcard tail to a regex with exactly these rules:

| Token | Regex | Meaning |
|---|---|---|
| `**` as a whole segment | `(?:.*/)?` | zero or more segments |
| `**` inside a segment | `.*` | crosses separators |
| `*` | `[^/]*` | within one segment |
| `?` | `[^/]` | one character, within one segment |

Anchored at both ends. A pattern ending in `/**` matches paths **inside**
the directory and **not** the directory itself. Criterion `CH6` pins
five positive and five negative cases, including
`<home>/skills/**/proposals/**` matching `<home>/skills/a/b/proposals/c/d.yaml`
and **not** matching `<home>/skills/proposals-evil.yaml`. Mutation `M23`
(`fnmatch.fnmatch` substituted) must redden it.

**`C-7` — an unsupported metacharacter FAILS CLOSED.** If any pattern
contains `[`, `]`, `{`, `}` or a leading `!`, `build_can_use_tool` raises
`CharterPatternUnsupported` **before returning a callback**, and the
session never starts. Guessing at a character class the matcher does not
implement risks widening; refusing to start is the only safe direction,
and it mirrors `charter.py`'s `CanonReadRootsUnavailable` fail-closed
discipline. `SdkBackend` maps that raise to
`Outcome(failure="os-error")` with the exception's text as `detail` —
the session did not run, and the surface degrades exactly as it does for
any other pre-spawn failure. Criterion `CH7`; mutation `M24`.

**`C-8` — deny reasons are model-facing text and are pinned.** Each of
the four deny branches carries a distinct message beginning
`self-learn invocation charter: `, naming the tool and (for `W`) the
resolved path. The probe measured the deny reason surfacing verbatim as
an error tool result and the model correctly declining to retry — which
only works if the reason says what was refused. Criterion `CH8` asserts
the four are distinct and each names its tool.

**`C-9` — every DENY is recorded.** The callback appends to the session's
`EventLog` (§3.8) before returning. Criterion `CH9`.

### 3.7 `Life-1` — the kill ladder, the child pid, the sidecar (NORMATIVE)

**`K-1` — the ladder, in order.** On timeout, and again unconditionally in
`finally`:

1. **Bounded `interrupt()`** — `await asyncio.wait_for(client.interrupt(),
   timeout=INTERRUPT_GRACE_SECS)`. Any exception, including the timeout,
   is swallowed and escalates to step 2. Cancel-on-timeout is safe *here*:
   the abandoned control request is moot once the transport disconnects.
2. **SHIELDED `disconnect()`** —
   `task = asyncio.ensure_future(client.disconnect())`, then
   `await asyncio.wait_for(asyncio.shield(task), timeout=KILL_SECS)`. On
   expiry the task is **abandoned, never cancelled**, held by a strong
   module-level reference, and given both done-callbacks (discard +
   log) — ported verbatim from `sdk.py`'s `_ABANDONED_DISCONNECTS` /
   `_log_abandoned_disconnect`. **A raw cancel pierces the SDK
   transport's own shielded SIGTERM/SIGKILL escalation** — its
   `close()` carries that caveat in its own docstring — and would return
   "bounded" while a wedged CLI child lived on with no further
   escalation.
3. **Explicit child kill, BEFORE the coroutine returns** — `K-2`.

Defaults: `INTERRUPT_GRACE_SECS = 1.0`, `KILL_SECS = 2.5`, the values
`sdk.py` tuned on 2026-07-18. Criteria `KL1`, `KL2`, `KL3`; mutations
`M25`, `M26`.

**`K-1a` — why step 3 exists here and not in the UI.** The UI's loop
outlives the engine, so an abandoned `disconnect()` finishes in the
background. Here, `run_sync` calls `asyncio.run`, which **closes the
loop** on return: any background task dies unfinished and the SDK's own
escalation never completes. The explicit kill is what makes the ladder
terminate in a sync frame. Criterion `KL4`.

**`K-1b` — the real reason is sharper than `K-1a`, and it was measured.**
Read from the installed transport's `close()`: the whole body runs inside
`anyio.CancelScope(shield=True)`, and the child-process teardown is

```
fail_after(5): await process.wait()          # graceful — NO signal sent
  → on timeout: process.terminate()          # SIGTERM
    fail_after(5): await process.wait()
      → on timeout: process.kill()           # SIGKILL
```

with a further 5 s wait-lock acquisition ahead of it. **`KILL_SECS` is
2.5 s.** The shielded wait therefore expires *inside the first graceful
window* — at the moment `SdkBackend` abandons the task, **not one signal
has been sent to the child**, and the first one is still ≥ 2.5 s away.
So step 3 is not a belt on a mostly-finished teardown; on the timeout
path it is, in practice, **the only thing that signals the child before
the loop closes.** `KL4`'s `hang_sigterm_ignored` leg is what proves it,
and this paragraph is why that leg is an integration test rather than a
recorder test.

**`K-2` — the kill, with the `getpgid` guard. MEASURED, and load-bearing.**

```
if child is not None and worker._pid_alive(child):
    if os.getpgid(child) != os.getpgid(0):
        os.killpg(child, signal.SIGKILL)
    else:
        os.kill(child, signal.SIGKILL)
```
guarded by `except (ProcessLookupError, PermissionError): pass`.

**The SDK's child shares the caller's process group.**
`SubprocessCLITransport.connect` calls `anyio.open_process(cmd, stdin=…,
stdout=…, stderr=…, cwd=…, env=…, user=…)` — **no `start_new_session`,
no `preexec_fn`, no process-group argument**. Measured on the resolved
SDK while writing this spec: parent pgid `1026799`, child pgid
`1026799`, `os.getpgid(child) == os.getpgid(0)` → **True**. Criterion
`KL5`; mutation `M27`.

**Corrected by the code gate (NOTE-14) — the unguarded call's OBSERVED
failure mode on this host is "the child is never killed", not "kills the
worker itself".** `os.killpg(child, SIGKILL)` passes the CHILD's raw
pid as the process-GROUP id argument, not `os.getpgid(0)` — and since the
child never became a process-group leader (no `setpgid`, it merely
inherited the caller's group), no process group numbered `child`
ordinarily exists. Live under `M27`: the unguarded call raised
`ProcessLookupError` (ESRCH), the child was **never actually killed**,
and it survived as an orphan that contaminated five subsequent test runs
(`hang_sigterm_ignored`, still alive). The theoretical "kills the worker"
hazard this paragraph originally described would require `child`'s pid
number to itself COLLIDE with a live, distinct process group id — an
edge case, not the typical failure. **The guard is still load-bearing**:
without it, `K-2` degrades from "reliably kills the child" to "usually
does nothing, occasionally (on a pid collision) kills something it
shouldn't" — neither acceptable, which is why `KL5`'s recorder-based
positive/negative legs (`K-2a`, below) remain the test, not a real
signal.

**`K-2a` — the guard is tested through RECORDERS, not through real
signals, and that is deliberate.** `KL5` monkeypatches `os.kill`,
`os.killpg` and `os.getpgid` and asserts: same-pgid → `os.kill` called,
`os.killpg` **never** called; different-pgid → `os.killpg` called. A test
that let the unguarded mutant actually fire would kill the pytest process
— a redden that destroys the run reporting it, which is not a usable
signal. One integration leg (`KL4`) does send a real `SIGKILL`, and only
ever down the `os.kill` path.

**`K-2b` — the killed child becomes a ZOMBIE, and that is accepted
(NOTE-7).** Two measured facts combine. (i) The SDK registers an
`atexit` reaper over a module-level `_ACTIVE_CHILDREN` set, and it sends
**`SIGTERM` only**. (ii) `close()`'s `finally` discards a child from that
set **only when `returncode is not None`** — i.e. only one it actually
reaped — so a child `SdkBackend` kills out from under an abandoned
`disconnect()` stays in the set. `K-2` sends `SIGKILL` and does **not**
`waitpid`, so the child is reaped by nobody and remains a **zombie** for
the lifetime of the CLI process.

**Bounded and accepted, not fixed.** At most **two** per run (the worker's
batch and repair invocations; the miner and analyst run one session
each), and the CLI process exits minutes later, at which point `init`
reaps them. Adding a `waitpid` would race the SDK's own `process.wait()`
inside the shielded scope for the same child — two reapers on one pid is
a worse failure than a short-lived zombie. Recorded here so a future
reader who sees `<defunct>` in `ps` during a run knows it is specified
behavior. §7.3 `R-8`.

**`K-3` — the child pid resolver is DEFENSIVE.** `child_pid_of(client)`
walks private attributes (`client._transport._process.pid` on the
resolved SDK) inside `try/except (AttributeError, TypeError)` and returns
`None` on any failure. A `None` child is **not** an error: the ladder's
steps 1 and 2 still run, step 3 is skipped, and one line is logged
(`run: sdk backend could not resolve the child pid`). The alternative —
raising — would turn an SDK-internal rename into a total outage of the
backend. Criterion `KL6`; §8 row 3 re-confirms the attribute path.

**`K-4` — the pid sidecar.** `worker.cache_dir() / f"{spec.surface}.sdk-child.pid"`,
written as JSON as soon as the child pid is known, and **unlinked in
`finally`** whether the session succeeded, failed or timed out:

```json
{"pid": 12345, "started_at": 1754700000.0, "cli": "/home/…/claude"}
```

It carries more than a pid **because a bare pid is a pid-reuse foot-gun**:
a sweep that trusts one can `SIGKILL` an unrelated process that inherited
the number. Criterion `KL7`.

**`K-5` — the start-of-run orphan sweep.** Before connecting, `SdkBackend`
reads the sidecar for its own surface, if present, and kills the recorded
pid **only when all three hold**: `worker._pid_alive(pid)` is true; the
process's `/proc/<pid>/cmdline` first element basename is `claude` or
equals the sidecar's `cli` basename; and the sidecar's `started_at` is
older than the current process's start. It then unlinks the sidecar. Any
check that cannot be performed (no `/proc`, unreadable cmdline) means
**do not kill** — unlink the sidecar and log one line. The sweep uses
`K-2`'s guarded kill, never a bare `killpg`. Criterion `KL8`; mutation
`M31` (the cmdline check dropped) is the negative control that a sweep
which kills on pid alone is caught.

### 3.8 `Ev-1` — capture (NORMATIVE)

**`E-1` — `SdkOutcome`, a frozen subclass of `Outcome`.**

```python
@dataclass(frozen=True)
class SdkOutcome(Outcome):
    tool_events: tuple[dict, ...] = ()
    denials: tuple[dict, ...] = ()
    cost_usd: float | None = None
    turns: int | None = None
    session_id: str | None = None
```

**A subclass, not five new fields on `Outcome`.** Three reasons, all
binding: `contract.py` is byte-frozen by this unit's file surface;
`U-bedrock` and `U-fake` rebase over this unit and must not have to
rebase over a contract change; and four of the five facts are ones no
CLI-shaped backend can ever populate, so on `Outcome` they would be
permanently-`None` fields inviting a consumer to read a silent wrong
answer. `isinstance(SdkOutcome(...), Outcome)` holds, `Outcome`'s
`__post_init__` invariant still fires, and every existing consumer path
(`worker._invoke_claude` discarding it, `miner._invoke_reader` branching
on `.failure`, `analyst.analyze` reading `.stdout`) is unchanged.
Criterion `EV1`; mutation `M32`.

**`E-2` — what is captured.**

| Field | Source |
|---|---|
| `tool_events` | one dict per `ToolUseBlock` in every `AssistantMessage`, and one per `ToolResultBlock` in every `UserMessage` |
| `denials` | every DENY the charter returned (`C-9`), **plus** `ResultMessage.permission_denials` when non-empty |
| `cost_usd` | `ResultMessage.total_cost_usd` |
| `turns` | `ResultMessage.num_turns`, via `getattr(..., None)` + `isinstance(int)` — `sdk.py`'s defensive form, ported |
| `session_id` | `ResultMessage.session_id`, same defensive form |

Both denial sources are kept because they differ: a structurally
disallowed tool appears in neither, a charter DENY appears in both, and a
denial the SDK recorded but the callback never saw appears only in the
second. Criterion `EV2`.

**`E-3` — the JSONL sink.**
`worker.cache_dir() / f"{spec.surface}.tool-events.{run_id}.jsonl"`,
where `run_id` is assigned at session **start** as
`f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"`.

The run id is **not** the session id: the session id arrives only with
the `ResultMessage`, which a timed-out or crashed session never produces,
and a naming scheme that works only on the happy path is a naming scheme
that loses exactly the runs worth reading. The session id is written
*inside* the file instead. One JSON object per line: a `meta` line first
(surface, run_id, session_id, cost_usd, turns, failure), then one line
per tool event, then one per denial. Written **once**, at the end of the
session, inside the same `finally` that clears the sidecar — so a
timed-out session still leaves its file. Criterion `EV3`; mutation `M33`
(the write moved out of `finally`).

**`E-4` — capture only.** Nothing in this unit reads these files back.
The consumer is a post-burn-in unit; §7.4 names it. A build that grows a
reader has left the mandate.

**`E-5` — retention, with a negative control.** At session start,
`prune_event_logs(surface)` keeps the newest `SELF_LEARN_SDK_EVENT_LOGS`
(default **20**) files matching **exactly**
`f"{surface}.tool-events.*.jsonl"` in `cache_dir()`, by mtime, and
unlinks the rest. It matches nothing else — not another surface's files,
not `worker.log`, not `worker.window`. Criterion `EV5` is the retention
leg; `EV6` is the **negative control**: a decoy file in `cache_dir()`
that does not match the pattern survives a prune that deletes twenty
that do. Mutation `M34` (the pattern widened to `*.jsonl`) must redden
`EV6` and only `EV6`.

**`E-6` — the only two writes in this package.** `events.py` writes the
JSONL; `lifecycle.py` writes and unlinks the pid sidecar. `PL3` pins the
count.

### 3.9 `PS-1` — the provider extension point (NORMATIVE)

`provider_env.py` contains exactly one public symbol:

```python
def provider_env(spec: SessionSpec) -> dict[str, str]:
    """The ONE point where provider environment variables enter an SDK
    session. The anthropic leg contributes nothing. U-bedrock owns this
    function's body; no other module in invocation_sdk/ may grow
    provider logic."""
    return {}
```

**`PS-a`** `backend.py` calls `provider_env(spec)` **exactly once**, and
its return value is assigned to `options.env` **without merging anything
else in**. Criterion `OP16` enumerates the call sites from source and
requires exactly one; mutation `M16`.

**`PS-b` — the leak test.** With the shipped anthropic leg,
`options.env == {}` — not a copy of `os.environ`, not a filtered subset,
not `{"ANTHROPIC_API_KEY": …}`.

**The merge direction `OP17` relies on is correct; the r2 draft's
"precisely what `subprocess.run` does" was not (NOTE-3).** Measured, the
SDK builds the child environment as:

```python
inherited_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
process_env = {
    **inherited_env,
    "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
    **self._options.env,
    "CLAUDE_AGENT_SDK_VERSION": __version__,
}
```
plus `process_env["PWD"] = cwd`. So an SDK child sees the parent
environment **minus `CLAUDECODE`, plus `CLAUDE_CODE_ENTRYPOINT=sdk-py`
and `CLAUDE_AGENT_SDK_VERSION`** — three differences from what
`subprocess.run` gives the CLI backend. What matters for this unit
survives intact: `**self._options.env` merges **over** the inherited
environment, so `env={}` contributes nothing and `provider_env`'s future
entries will win over an inherited value of the same name. One edge
recorded rather than discovered later: `CLAUDE_AGENT_SDK_VERSION` is set
**after** the merge and is the one key `options.env` cannot override.
Criterion `OP17`; mutation `M35`.

**`PS-c` — merge discipline for `U-bedrock`.** `U-sdk` touches
`provider_env.py` and `backend.py`'s single call site. `U-bedrock`'s diff
is expected to be confined to `provider_env.py` plus its own new modules
and its doctor. This is stated so the Wave-1 merge order
(`U-sdk` → `U-bedrock` → `U-fake`) has a mechanical, not a social,
disjointness. **No Bedrock or AWS logic appears anywhere in this unit.**

### 3.10 `Fake-2` — the stream-json fake CLI (NORMATIVE)

`plugins/self-learn/cli/tests/fixtures/fake_claude.py`, ported from the
UI fixture of the same name (§2.1). The control protocol ports verbatim:
argv accepted and ignored; the first stdin `control_request` with
`subtype == "initialize"` answered immediately (skipping it hangs the SDK
on a 60 s timeout); any other `control_request` answered with a generic
success so `interrupt()` never hangs; a `{"type":"user"}` message's
content string selects a scenario; EOF exits 0.

Scenarios — this unit's own set, not the UI's:

| Scenario | Drives |
|---|---|
| `ok_text` | happy path with a non-empty `ResultMessage.result` — analyst extraction branch 1 |
| `ok_blocks_only` | `ResultMessage.result` absent/empty, text only in the final `AssistantMessage` — extraction branch 2 |
| `ok_write` | a `Write` `ToolUseBlock` + its `ToolResultBlock` — tool-event capture, `FileChanged`-shaped flow |
| `error_result` | `is_error=True` with `errors: ["boom"]` |
| `no_result` | messages then EOF, never a `ResultMessage` |
| `hard_exit` | `os._exit(1)` mid-stream — a `ProcessError` on the message stream |
| `hang` | sleeps past any test timeout — drives `wait_for` + the ladder |
| `hang_sigterm_ignored` | installs `SIG_IGN` for `SIGTERM`, then sleeps — drives `K-2`'s explicit `SIGKILL` (`KL4`) |
| `malformed_line` | a non-JSON stdout line the SDK transport skips |

**`FK-a`** No test in this unit reaches the network or a real model.
Every session runs against this fake via `SELF_LEARN_SDK_CLI_PATH`, with
`CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1` set (the SDK's version check
shells out to `<cli_path> -v`, which the fake does not implement).
Criterion `HG5`.

**`FK-b`** `U-seam` `B-1`'s suite-wide guard
(`test_attrib.py::test_hy1_…`) globs `tests/*.py` and rejects any line
matching `\[\s*"claude"\s*\]` that does not also call
`worker._invoke_claude(`. `tests/fixtures/` is outside that glob, but
`test_invocation_sdk.py` is **inside** it and must comply. Criterion
`HG1`.

### 3.11 `Dep-1` / `Dep-2` — the dependency, and the pin that must NOT move

**`Dep-1`** `claude-agent-sdk` is added to the CLI's
`[dependency-groups] dev` so the ordinary `uv run pytest` in
`plugins/self-learn/cli` has it. Measured: it is **not** currently
importable there. Without this, every criterion in §4 would `skipif` its
way to green and the mutation plan would be unrunnable — an untestable
unit, which is worse than a missing dependency. **Sanctioned** (§10
`V-3`), and bounded three ways:

- **The dev group ONLY.** `[project] dependencies` does not gain the SDK,
  now or as a side effect — a runtime dependency would make the `[sdk]`
  extra meaningless and would install an SDK for every user of the CLI.
  Criterion `RS7`; mutation `M59`.
- **The dev-group presence must not MASK the missing-extra path.** The
  whole point of `BackendUnavailable` is what happens on a machine
  *without* the extra, and after `Dep-1` the test machine always has it.
  So the absent case is exercised by **simulating absence** — an
  import-block shim (a `sys.meta_path` finder, or
  `monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)`, that
  raises `ImportError` for that name and that name only) — and
  **never** by uninstalling anything. Criterion `RS2`.
- **The shim is scoped to the test that uses it** and is torn down by
  `monkeypatch`, so no other criterion runs under a poisoned import
  table.

**`Dep-2` — `[project.optional-dependencies]` must NOT change.**
`test_invocation.py::test_rg8_pyproject_sdk_extra_matches_ui_pin` reads
the **UI**'s pin with `re.search(r'"claude-agent-sdk[^"]*"', ui_text)`
and asserts `f'sdk = ["{ui_pin}"]' in cli_text`. Raising the CLI floor to
`>=0.2.121` **alone reddens `RG8`**, a test this unit may not edit; and
raising both would mean editing `plugins/self-learn/ui/pyproject.toml`,
which is the port source and out of this unit's surface.

So **the floor stays `>=0.2.116,<0.3`**, and the version question is
answered by `O-1a`'s runtime feature detection instead — which the
mandate already anticipated (*"max_budget_usd if present on the resolved
SDK version"*). Criterion `RS1` asserts the pin is byte-unchanged;
§7.3 `R-3` owns the residual.

### 3.12 `Map-1` — SDK conditions to `Outcome` (NORMATIVE)

`FAILURE_KINDS` is `U-seam`'s and is not extended:
`("exit", "timeout", "not-found", "os-error", "unavailable")`.

| SDK condition | `ok` | `rc` | `stdout` | `detail` | `failure` |
|---|---|---|---|---|---|
| `ResultMessage`, `is_error=False` | `True` | `0` | extracted text (`E-7`) | `""` | `None` |
| `ResultMessage`, `is_error=True` | `False` | `1` | extracted text | `"; ".join(errors)` else `result` else `subtype` | `"exit"` |
| `ProcessError` (nonzero CLI exit) | `False` | `exc.exit_code` if an `int`, else `1` | `""` | `str(exc)` | `"exit"` |
| stream ended with **no** `ResultMessage` | `False` | `1` | `""` | `"sdk session ended without a result"` | `"exit"` |
| `CLINotFoundError` | `False` | `None` | `""` | `""` | `"not-found"` |
| `asyncio.TimeoutError` from the wall-clock guard | `False` | `None` | `""` | `""` | `"timeout"` |
| `CharterPatternUnsupported` (`C-7`) | `False` | `None` | `""` | `str(exc)` | `"os-error"` |
| any other `ClaudeSDKError` (JSON decode, connection, protocol) | `False` | `None` | `""` | `str(exc)` | `"os-error"` |
| bare `OSError` from the transport | worker/miner: as `"os-error"` | `None` | `""` | `str(exc)` | `"os-error"` — **analyst: RE-RAISED, not caught** |

**`MAJOR-3` (code gate, 2026-08-18) — the "`ProcessError` (nonzero CLI
exit)" row's bare-`Exception` catch is NARROWED, not unconditional.**
The catch only maps to `failure="exit"` when `str(exc)` carries the
SDK's own wrapped-`ProcessError` shape (a message containing `"exit code
N"` — `ProcessError.__str__` always appends `f"(exit code: {exit_code})"`
when one is known). Anything else caught there — an `AttributeError`,
`TypeError`, `KeyError`, or any other programming bug raised inside
`_run_session`, the drain, or the outcome mapping — **re-raises**,
deliberately NOT added as a new `Map-1` row: this is the absence of a
mapping, not a new one. `_drive`'s `finally` (the kill ladder, the
sidecar clear, the event-log write) still runs regardless, since a bare
`raise` inside an `except` block does not skip the enclosing `finally`.

**`O-rc`** `rc` is a synthetic `1` on every `failure="exit"` the SDK
cannot attach a real exit code to, and `None` on all four other failure
kinds — matching `CliBackend`, where `not-found`, `timeout`, `os-error`
and `unavailable` all produce `rc=None`. Rendering `rc=None` through the
`exited` template would emit `"analyst exited None: …"`, an operator-
visible byte that no shipped run has ever produced. Criterion `OU2`;
mutation `M36`.

**`O-log`** Every failure leg is rendered through
`LOG_TEMPLATES[spec.surface]` via `spec.log`, **byte-identically to
`CliBackend`**. The SDK backend carries no copies of those f-strings.
`unavailable` is never produced by this backend (the registry owns it).
Criterion `OU3`; mutation `M37` (own literals) must redden it even though
the default bytes match — asserted by `monkeypatch.setitem` on
`LOG_TEMPLATES`, `U-seam` `B-3a`'s third site.

**`O-quiet`** A clean session (`ok=True`) writes **nothing** through
`spec.log`, matching `U-seam` `LG6`. The permitted set beyond the
templates is **five** lines, each emitted **only** when the thing it
names actually happened (MAJOR-2 — the r2 draft's list of three omitted
the two ported kill-path lines, which `K-1`'s verbatim port from `sdk.py`
requires and `KL2`/`KL3` assert):

| # | Line | Emitted when |
|---|---|---|
| 1 | the `O-1a` cap line | a requested budget cap is absent on the resolved SDK |
| 2 | the `K-3` line | the child pid could not be resolved |
| 3 | the `K-5` line | the orphan sweep declined or acted |
| 4 | *"disconnect() still running at the kill bound…"* | the shielded wait expired (`K-1` step 2) — **ported** |
| 5 | *"abandoned disconnect() completed / finished with / was cancelled"* | the abandoned task's done-callback fired — **ported** |

Lines 4 and 5 are `sdk.py`'s own, and `P-a` requires the port to
reproduce them. Criterion `OU4`; mutation `M38`.

**`O-analyst-oserror`** The analyst's missing `OSError` leg is preserved
here exactly as `U-seam` `T-c` preserves it in `CliBackend`: a bare
`OSError` escapes `SdkBackend.text_session`, escapes `analyst.analyze`,
and escapes `teach.py`'s `except analyst.AnalystError`. This unit
**reproduces the shipped defect `R-1`** rather than quietly fixing it on
one backend and not the other — a divergence would mean the defect's
eventual fix had to be discovered twice. The criterion carries an inline
comment saying so. Criterion `OU5`; mutation `M39`.

**`E-7` — the analyst's text extraction, both branches contract-tested.**

1. `ResultMessage.result` when it is a `str` and non-empty after
   `.strip()` → use it verbatim (unstripped).
2. otherwise → `"".join(block.text for block in <final AssistantMessage>.content
   if isinstance(block, TextBlock))`.
3. otherwise → `""`.

Branch 1 is what the resolved SDK populates on a normal turn; branch 2 is
what a build that never sets `result` leaves behind, and it is the branch
that keeps the analyst working if that changes. Both are driven by their
own fake scenario (`ok_text`, `ok_blocks_only`). Criterion `OU6`;
mutations `M40`, `M41`.

**`O-stdout`** `Outcome.stdout` follows `U-seam` `T-e`: the extracted
text on the analyst, `""` on both worker surfaces, and the extracted text
on the miner (whose caller treats it as diagnostic only and never parses
it). Criterion `OU7`.

**`O-drain`** The message drain **tolerates unknown message types by
skipping them, and never raises** — `RateLimitEvent` was observed
mid-stream on every Max-OAuth probe run. Criterion `OU8`; mutation `M42`.

---

### 3.13 `Sim-1` / `Sim-2` — simulated absence, and the nine shipped tests (NORMATIVE)

**`Sim-0` — the problem, stated exactly.** `Dep-1` makes
`claude_agent_sdk` importable in the CLI venv. §3.2's branch therefore
**succeeds** and returns an `SdkBackend` where nine shipped tests demand
`BackendUnavailable`. This is not a defect introduced by this unit — it
is a **latent venv dependency** the shipped tests already carried:

> Installing the `[sdk]` extra into the CLI venv **for any reason at all**
> — a developer running `uv sync --extra sdk` to try the backend, CI
> adding the extra, a future unit needing it — breaks all nine, today, at
> `c2669a9`, with no code change whatsoever. The tests assert a refusal
> that is really an *absence*, and they read the absence off the
> environment instead of establishing it.

**`Sim-1` — the ruling: simulate, don't rely.** The nine are amended in
this unit to establish the absence they assert, under a **single**
`sys.meta_path` import-block fixture defined **once** and requested by
each. Recorded verbatim as the rationale: *the shipped tests were
latently venv-dependent, so simulation makes them truthful on every host
— strictly more robust than the absence-reliance `U-seam` shipped.* The
amendment makes the suite **less** environment-coupled than it is today;
it is a repair of the tests' oracle, not a relaxation of it.

**The fixture is defined in `tests/test_invocation_sdk.py`** — the same
one `RS2` specifies (§3.11 `Dep-1`) — and reached from
`test_invocation.py` by the house import-for-fixtures pattern, whose
precedent is `test_attrib.py:48`:

```python
from test_invocation_sdk import (  # noqa: F401 -- fixture resolved by name
    sdk_absent,
)
```

The location is **forced, not chosen**: `SU2` bounds the test-directory
diff to three paths, and the may-touch cell allows `test_invocation.py`
exactly **one** import line — so a new `conftest.py`, or a fourth
fixture module, would break one bound or the other. It blocks
`claude_agent_sdk` **and that name only**, and is torn down by
`monkeypatch`.

**`Sim-1a` — the import line is a CHANNEL, and it is fenced.** Importing
`test_invocation_sdk` executes that module at collection time in the same
session as all 61 shipped tests. **An `autouse` fixture defined there
would therefore apply to every one of them** — reaching the whole shipped
suite through a single line that `SU4`'s diff bound permits and its AST
check would not flag, because the line itself is legal. So, normatively:
**`test_invocation_sdk.py` defines no `autouse` fixture.** Anything this
unit's own tests need, they request by name. Criterion `SU6`'s fourth
leg; mutation `M64`.

**`Sim-2` — the nine, by name, with what each demands.** Located by
symbol; the counts are measured at `c2669a9`.

| # | Test | What breaks without the shim |
|---|---|---|
| 1 | `test_rg1_five_rung_precedence_resolves_in_isolation` | **16** `pytest.raises(BackendUnavailable)` — 4 rungs × 4 surfaces |
| 2 | `test_rg2_each_rung_shadows_the_ones_below` | **5** `pytest.raises(BackendUnavailable)` |
| 3 | `test_rg4_sdk_raises_backend_unavailable_with_install_command` | 1 raise + the `pip install` substring |
| 4 | `test_rg5_write_session_returns_unavailable_without_raising` | `failure == "unavailable"` |
| 5 | `test_rg5_text_session_returns_unavailable_without_raising` | `failure == "unavailable"` |
| 6 | `test_rg5_analyst_analyze_converts_unavailable_to_analyst_error` | the `AnalystError` text |
| 7 | `test_rg5_shimmed_worker_run_completes_under_sdk_selection` | **the live-session hazard — see `Sim-3`** |
| 8 | `test_wr2_miner_early_returns_precede_the_stray_sweep` | its `unavailable` leg (`SELF_LEARN_BACKEND=sdk`) |
| 9 | `test_wr6_analyst_failure_mappings_are_byte_exact_…` | its `unavailable` byte-literal leg |

`test_rg5_unknown_surface_returns_outcome_never_keyerror` is **not** in
the set and is **not** amended: it sets no backend env var and is
unaffected. Amending it would be an unbounded edit.

**`Sim-3` — the live-session hazard, as a HARD PROPERTY.** Test 7 calls
`worker.run(env.home)` under `SELF_LEARN_BACKEND=sdk`. With the SDK
importable and no shim, that constructs a real `SdkBackend` and drives a
**real session**. Its existing guard — `assert claude_shim["count"]() == 0`
— would **not** catch it: `claude_shim` shims `claude` on PATH, and the
SDK's `_find_cli()` prefers the package-relative `_bundled/` CLI *before*
`shutil.which("claude")` (the bundle-exclusion memo), so a real bundled
binary can run while the PATH shim's counter stays at zero. Therefore,
normatively:

> **No test in the CLI suite may start a real SDK session, under any
> mutation of this unit.** The property is established two ways, so
> neither alone is load-bearing: (a) the absence shim makes
> `ClaudeSDKClient` unconstructible in the nine; (b) every test in this
> unit that *does* construct one sets `SELF_LEARN_SDK_CLI_PATH` to the
> fake (`HG2`), and `M50` is deliberately shaped so that even the
> `cli_path` mutation fails **closed** (`CLINotFoundError`) rather than
> falling through to the SDK's own resolution.

Criteria `SU6` (the nine), `SU4` (nothing else moved), `HG2` (this
unit's own sessions). Mutation `M60` proves the shim is **live** rather
than decorative.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`plugins/self-learn/cli/tests/test_invocation_sdk.py` unless it says
otherwise. **82 criteria**, in ten groups: `SU` 6, `PL` 6, `OP` 17,
`CH` 13, `KL` 8, `SY` 5, `OU` 8, `EV` 6, `RS` 8, `HG` 5. `SU2`, `SU3`,
`RS5` and one `HG` criterion are **instrument criteria** — satisfied by a
command's recorded output in the build report, not by a test function.

### SU — the suite (the headline)

- **`SU1`** The CLI suite at `plugins/self-learn/cli` collects **1716**
  tests and reports **1711 passed, 5 skipped, 0 failed** — the `c2669a9`
  baseline, measured for this spec (§9) — *plus* the new tests in
  `test_invocation_sdk.py`. A collected count below 1716, or any failure,
  or a **sixth skip**, fails this criterion. The five skips are the four
  `test_lock_invariant.py` *"not a ledger-mutating surface"* skips and
  `test_regime_fixes.py`'s *"repo-root suite absent"*.
- **`SU2` — restated for the code-gate fold (2026-08-18).** `git diff
  --name-only c2669a9..HEAD -- plugins/self-learn/cli/tests/` names
  **exactly four** paths: `tests/test_invocation_sdk.py`,
  `tests/fixtures/fake_claude.py`, `tests/test_invocation.py` (the third
  bounded by `SU4`), and `tests/conftest.py` (new — `BLOCKER-1`'s
  `_no_real_sdk_spawn_tripwire`, the fix-proof the fold's own text
  required; a **session-scoped autouse fixture belongs in `conftest.py`,
  never in `test_invocation_sdk.py`, precisely because `Sim-1a` forbids
  an `autouse` fixture there**). *Instrument criterion.*
- **`SU3` — restated for the code-gate fold.** `git diff --name-only
  c2669a9..HEAD` names, under `plugins/self-learn/`, **exactly** these
  paths and no others:

  | Path | Content bound |
  |---|---|
  | `cli/src/self_learn/invocation_sdk/**` | new files only |
  | `cli/src/self_learn/invocation/registry.py` | `RS5`'s numstat bound |
  | `cli/tests/test_invocation_sdk.py`, `cli/tests/fixtures/fake_claude.py` | new files |
  | `cli/tests/test_invocation.py` | `SU4`'s enumerated-hunk bound |
  | `cli/tests/conftest.py` | additive only — exactly one new `pytest.fixture(scope="session", autouse=True)` (`_no_real_sdk_spawn_tripwire`), no edit to the pre-existing `_worker_test_defaults` fixture |
  | `cli/pyproject.toml` | `[dependency-groups] dev` only (`RS7`) |
  | `cli/uv.lock` | dev-dependency + `requires-dev` entries only; **no `[[package]]` added or removed, no locked version changed** (`RS8`) |
  | `ui/uv.lock` | the `self-learn-cli` member's `[package.metadata.requires-dev]` block only (`RS8`) |

  **`ui/uv.lock` is the only path under `plugins/self-learn/ui/` this
  unit may touch**, and it is metadata, not source — `U-seam`'s own
  lockfile adjudication (CONFORMANT-in-substance) plus base commit
  `c2669a9`, which is precisely this class of sync, are the precedent.
  No file under `ui/src/` or `ui/tests/` appears. *Instrument criterion.*
- **`SU4` — restated for BLOCKER-1: the pin is FILE-MINUS-ENUMERATED-HUNKS.**
  `test_invocation.py`'s 61 tests all pass. The anti-tamper pin is **not**
  a whole-file sha (the fixture edit changes the file) and **not** a
  post-edit sha alone (a post-edit sha pins whatever the builder wrote,
  including smuggled edits). Instead, both of:

  1. **A structural bound on the diff.** Every line in
    `git diff c2669a9..HEAD -- tests/test_invocation.py` that is added or
    removed is either (a) the single module-level import of the absence
    fixture, or (b) inside the `def test_…(…):` **signature line** of one
    of `Sim-2`'s nine tests. **No line inside any test body, no
    assertion, and no other test function may appear in the diff** —
    asserted by parsing the diff hunks against the nine functions' AST
    ranges, so "it's only a small fix" cannot smuggle through.
  2. **A post-edit sha, recorded in the build report**, so a *second*
    edit after the gate is still caught.

  `HY2`, `HY4`, `WR7`, `RG8` and `RG3` are **not** among the nine and are
  asserted byte-identical to `c2669a9` individually — they are the guards
  this unit's placement and pin decisions rest on, and the allowance must
  not reach them.
- **`SU5`** `test_lock_invariant.py` and `test_attrib.py` are
  sha-unchanged from `c2669a9` — **whole-file**, no allowance.
- **`SU6`** Four legs. (i) Each of `Sim-2`'s nine tests requests the
  absence fixture and passes **with the SDK installed** — asserted by
  running the nine explicitly and by an AST check that each names the
  fixture in its parameter list. (ii) The fixture is defined **once**,
  and that site is **`tests/test_invocation_sdk.py`** (asserted: exactly
  one definition site in the suite, in that file). (iii) It blocks
  `claude_agent_sdk` **and no other module** — importing an unrelated
  module under the fixture still succeeds. (iv) **`test_invocation_sdk.py`
  defines NO `autouse` fixture** — AST scan for
  `@pytest.fixture(autouse=True)` in any form, asserting zero. This is
  the fence on the one channel by which the new module's state could
  reach all 61 shipped tests without appearing in `SU4`'s diff
  (`Sim-1a`).

### PL — placement, imports, and the re-covered guards

- **`PL1`** `invocation_sdk` is a package directory under
  `src/self_learn/`, is **not** inside `invocation/`, and contains
  exactly the six modules of §3.1's table — asserted by listing the
  directory, so an extra module is a failure rather than a surprise.
- **`PL2`** AST scan of `invocation_sdk/*.py`: no module imports `miner`,
  `analyst`, `verbs`, `teach` or `ledger_ops`, in any form (`import X`,
  `from X import Y`, `from .. import X`), at module level **or** inside a
  function. `worker` is permitted, and the only names taken from it are
  `cache_dir` and `_pid_alive` — asserted by collecting every
  `worker.<attr>` attribute access in the package and comparing the set.
- **`PL3`** AST scan for `open` / `write_text` / `mkdir` / `unlink` /
  `touch` calls across `invocation_sdk/*.py`. The allow-list is exactly
  `{("events.py","write_text"), ("events.py","unlink"), ("events.py","mkdir"),
  ("lifecycle.py","write_text"), ("lifecycle.py","unlink")}`, and the
  **total count is asserted exactly** — `HY4`'s shape, applied to this
  package (`L-b`).
- **`PL4`** Every path written by this package resolves under
  `worker.cache_dir()`; none resolves inside a git repository; none
  resolves under the resolved ledger home. Driven by running a full fake
  session with `XDG_CACHE_HOME` and `SELF_LEARN_HOME` pointed at separate
  scratch dirs and asserting on the set of files that appeared.
- **`PL5`** No module under `src/self_learn/` **calls** `write_session(`
  or `text_session(` other than `worker.py`, `miner.py` and `analyst.py`
  — the same AST scan `WR7` performs, asserted here as well so the
  constraint is visible in the file it constrains (`L-d`).
- **`PL6`** In a **fresh interpreter**, `import self_learn.invocation_sdk`
  succeeds, and so does the reverse order (`import self_learn.worker`
  then the package, and `import self_learn.invocation` then the package).
  Three subprocess launches, three exit codes. Proves `I-d`'s
  cycle-freedom rather than asserting it.

### OP — the option set

- **`OP1`** The session is driven by `ClaudeSDKClient`. `claude_agent_sdk.query`
  is **never called**: asserted by monkeypatching it to raise, driving a
  full fake session, and requiring success (`F-A`).
- **`OP2`** `options.allowed_tools == []` on all four surfaces, even
  though `containment.allowed_tools` is a non-empty string on three of
  them (`F-B`).
- **`OP3`** `options.setting_sources == []` on all four surfaces —
  asserted as `== []`, explicitly **not** `is None` and not falsy, so a
  build that drops the field fails (`F-C`).
- **`OP4`** `options.settings is None` on all four surfaces, **and** the
  miner's `cli_settings_writer` was nonetheless called and its file
  exists on disk. Both halves in one criterion (`A-2`).
- **`OP5`** `options.permission_mode == "default"` on all four surfaces
  and under both values of `SELF_LEARN_ENFORCE_SCOPE` (`O-2`).
- **`OP6`** `options.strict_mcp_config is True` and `options.mcp_servers == {}`
  on all four surfaces, including the two whose `containment.strict_mcp`
  is `False` (`O-3`).
- **`OP7`** `options.disallowed_tools` equals set `D` for each surface:
  the worker's six, the miner's nine, and `[]` for the analyst. Asserted
  against `worker.DISALLOWED_TOOLS` / `miner.READER_DISALLOWED_TOOLS`
  **split at test time**, never against a literal list copied into the
  test.
- **`OP8`** `options.max_turns` takes `O-1`'s per-surface default, and
  `SELF_LEARN_SDK_MAX_TURNS_WORKER` overrides it for **both**
  `worker` and `worker-repair` while `SELF_LEARN_SDK_MAX_TURNS_MINER`
  overrides neither — the `SELECTOR_FOR_SURFACE` mapping, checked where
  it can fail.
- **`OP9`** `options.max_budget_usd is None` by default;
  `SELF_LEARN_SDK_MAX_BUDGET_USD=2.5` puts `2.5` on the options. With a
  stub `ClaudeAgentOptions` whose `dataclasses.fields` lack
  `max_budget_usd`, the session **still runs** and the byte-exact
  `O-1a` line is logged once (`O-1a`).
- **`OP10`** `options.system_prompt` is
  `{"type":"preset","preset":"claude_code","append": doctrine}` on the
  analyst and `{"type":"preset","preset":"claude_code"}` on the other
  three. **Never `None`** — asserted as an explicit `is not None` before
  the shape comparison, because `None` is the field's own default and is
  the `F-D` failure (`A-3`).
- **`OP11`** `--model`'s value lands on `options.model`; an argv with no
  `--model` yields `options.model is None`; an argv whose **last**
  element is `--model` yields `None` and no `IndexError` (`A-4`).
- **`OP12`** `cli_settings_writer` is called **before** `cli_argv_builder`
  and its return value is the argument `cli_argv_builder` receives —
  order-recording closures on the miner surface, the same observation
  `U-seam` `AV3` makes of `CliBackend` (`A-1`).
- **`OP13`** The argv read set is closed: a source scan of `backend.py`
  finds the string literals `"--model"` and `"--append-system-prompt"`
  and **no other** `"--"`-prefixed literal (`A-5`).
- **`OP14` — restated for MAJOR-1: observed at the kwargs seam, tied to
  the spy.** Two legs. (i) `set(options_kwargs(spec))` equals §3.5's
  table **minus** whichever of `max_turns` / `max_budget_usd` the
  resolved SDK does not carry (`O-1a`) — so an added or dropped field
  fails either way, and feature-gating does not read as a defect. (ii)
  For each key in that mapping, the value equals the corresponding
  attribute on the `ClaudeAgentOptions` object the **constructor spy**
  captured (`O-0a`), which is what ties the assembled mapping to the
  object the session actually ran on. **No AST scan of the
  `ClaudeAgentOptions(...)` call is performed** — a `**kwargs`
  construction has no AST keywords to find.
- **`OP15`** `SELF_LEARN_SDK_CLI_PATH` lands on `options.cli_path`;
  unset yields `None` (`O-4`).
- **`OP16`** `provider_env` is called **exactly once** in the package —
  AST scan across `invocation_sdk/*.py` — and its return value is
  assigned to `options.env` with no merge (`PS-a`).
- **`OP17`** `options.env == {}` on all four surfaces with the shipped
  anthropic leg, with `ANTHROPIC_API_KEY`, `AWS_PROFILE` and
  `AWS_REGION` all set in the test's environment beforehand — the leak
  test (`PS-b`).

### CH — the charter

- **`CH1`** `Write` on a path matching a `write_glob` is **allowed**;
  `Edit` on that same path is **denied**. Both directions, on the worker
  surface, because the inverse is the plausible mistake (`C-3`).
- **`CH2`** Deny-by-default: `Bash`, `Task`, `WebFetch`, `WebSearch`,
  `NotebookEdit` and an invented `FutureTool` are each denied on every
  surface, and the analyst — whose `D` is empty — denies them too, from
  step 4 rather than step 1 (`C-4`).
- **`CH3`** A `W`-family call whose `tool_input` carries no non-empty
  string under any key in `P` is **denied**, with a reason naming the
  tool (`C-5`).
- **`CH4`** A symlink planted **at the leaf** of a `write_exact` target,
  pointing outside every permitted root, is **denied** — the resolved
  request lands outside and the expectation was not rebased onto it
  (`P-b`, `C-5`).
- **`CH5` — the negative control for `CH4`.** With the whole ledger home
  reached through a symlinked parent directory (`tmp/link -> tmp/real`),
  a legitimate write **is allowed**. A build that "fixes" `CH4` by
  resolving nothing at all passes `CH4` and fails here.
- **`CH6`** The matcher, five positive and five negative cases, including:
  `<home>/skills/**/proposals/**` matches
  `<home>/skills/a/b/proposals/c/d.yaml`; does **not** match
  `<home>/skills/proposals-evil.yaml`; `<stage>/**` matches
  `<stage>/x.yaml` and does **not** match `<stage>` itself or
  `<stage>-evil/x.yaml` (`C-6`).
- **`CH7`** A `write_glob` containing `[` makes `build_can_use_tool`
  raise `CharterPatternUnsupported` **before returning a callback**, and
  `SdkBackend` turns that into `Outcome(ok=False, failure="os-error")`
  with the exception text as `detail` and **no session started** —
  asserted by a `connect` spy that must never have fired (`C-7`).
- **`CH8`** The four deny branches produce four **distinct** messages,
  each beginning `self-learn invocation charter: ` and each naming its
  tool; the `W` branch also names the **resolved** path, not the raw one
  (`C-8`).
- **`CH9`** Every DENY appears in the session's `denials`, and a session
  with no denial has `denials == ()` (`C-9`).
- **`CH10` — the hatch OPEN, driven END-TO-END from the real variable.**
  With `SELF_LEARN_ENFORCE_SCOPE=0` set in the environment, a shimmed
  `worker.run` reaching the sdk backend produces a charter that
  **approves** a `Write` to a path outside every `write_glob` — the write
  the same run **denies** with the variable unset. Driven from the env
  var, not from a hand-built `Containment`, so the whole chain
  (`_enforce_scope()` → `containment_for(enforce=…)` → `default_mode` →
  the hatch) is observed rather than assumed. Second leg, same run: a
  tool in `D` (`Bash`) is **still denied** — the hatch sits below step 1
  (`C-4`, `C-10`).

  **Third leg — `worker-repair` OPENS too (MAJOR-3).** The same run is
  driven to a **repair round**, and the repair invocation's charter
  approves a write outside its exact-path set. This leg exists because
  `containment_for("worker-repair")` returns **`write_globs=()`** with
  the paths in **`write_exact`** — so a builder who writes `C-10`'s
  second conjunct as `containment.write_globs` alone, rather than the
  union, passes every other criterion in this document while the hatch
  **never opens on the repair round**. Mutation `M62`.
- **`CH11` — the hatch CLOSED, four legs, the negative-control set.**
  (i) variable unset → the out-of-glob write is denied, byte-identical
  reason to the pre-hatch build. (ii) With the variable **set**, the
  **analyst** containment (empty write sets) still denies the whole write
  family. (iii) With it set, the **miner** containment
  (`default_mode == "default"`) still denies a write outside the spool.
  (iv) With it set, `DEGRADED_WORKER_CONTAINMENT` grants nothing. Legs
  (ii)–(iv) are what make the second conjunct of `C-10` falsifiable.
- **`CH12` — the fence: the hatch changes the CHARTER and nothing else.**
  With `SELF_LEARN_ENFORCE_SCOPE=0` set, on every surface:
  `options.permission_mode == "default"`, `options.setting_sources == []`,
  `options.strict_mcp_config is True`, `options.settings is None`, and
  `options.disallowed_tools` is byte-identical to the variable-unset run.
  Five assertions. This is the fence around the shadowing hazard `O-2`
  identifies, and it is asserted directly rather than argued.
- **`CH13` — silence parity.** The hatch emits **nothing** through
  `spec.log`, on the open and closed paths alike, because the CLI path
  emits nothing — asserted twice over: behaviorally (`spec.log` receives
  no line attributable to the hatch on a `SELF_LEARN_ENFORCE_SCOPE=0`
  run) and at the source (a scan of `worker.py` confirms no `log(` call
  accompanies any `_enforce_scope()` call site, so the parity claim is
  re-derived at test time rather than trusted from this document).

### KL — the kill ladder and the child

- **`KL1`** On a `hang` scenario, `client.interrupt()` is awaited with a
  bound of `INTERRUPT_GRACE_SECS` and an `interrupt()` that never returns
  does not extend the ladder past `KILL_SECS` — measured with a monotonic
  clock around `run_sync`, asserted as an upper bound with margin.
- **`KL2`** `disconnect()` is **shielded**: a `disconnect` that outlives
  `KILL_SECS` leaves `run_sync` returning on time **and** the task alive
  and not cancelled — asserted on the task object, and on the strong
  reference set being non-empty at that moment (`K-1` step 2).
- **`KL3`** The abandoned task's done-callbacks fire: the strong
  reference is discarded and one line is logged naming the outcome —
  ported from `_log_abandoned_disconnect` (`K-1` step 2).
- **`KL4`** Integration leg, real signal: against `hang_sigterm_ignored`,
  `run_sync` returns a `timeout` outcome **and** the child pid is gone
  after it returns — polled, with a bound. This is the criterion that
  proves the explicit kill happens **before** the loop closes (`K-1a`).
- **`KL5`** The `getpgid` guard, through recorders. With
  `os.getpgid` stubbed so `getpgid(child) == getpgid(0)`: `os.kill` is
  called with `SIGKILL` and `os.killpg` is **never** called. With it
  stubbed to differ: `os.killpg` is called. `ProcessLookupError` and
  `PermissionError` from either are swallowed. Four assertions; no real
  signal is sent (`K-2`, `K-2a`).
- **`KL6`** `child_pid_of` returns an `int` for a live client and `None`
  for a client whose private attributes are missing or of the wrong type;
  a `None` child skips step 3, still runs steps 1–2, and logs the
  byte-exact `K-3` line once.
- **`KL7`** The pid sidecar exists at
  `cache_dir()/<surface>.sdk-child.pid` **during** the session, carries
  `pid`, `started_at` and `cli`, and is **absent** after `run_sync`
  returns — on the success path, the failure path and the timeout path.
  Three legs (`K-4`).
- **`KL8`** The orphan sweep kills a sidecar-recorded pid whose
  `/proc/<pid>/cmdline` basename matches, and **does not kill** one whose
  cmdline does not match — the second leg driven by a live sleeper the
  test owns, asserted still alive afterwards. Both legs go through
  `K-2`'s guarded kill (`K-5`).

### SY — the sync bridge

- **`SY1`** `run_sync` returns the coroutine's value when no loop is
  running.
- **`SY2`** `run_sync` returns the same value when called from inside a
  running loop — driven by `asyncio.run(async_caller())` where
  `async_caller` calls `run_sync` directly — and the coroutine executed
  on a **different** thread id than the caller's.
- **`SY3`** An exception raised inside the coroutine propagates out of
  `run_sync` with its **original type**, from **both** branches. Driven
  with `OSError` specifically, because that is `T-c`'s case (`Y-c`).
- **`SY4`** `run_sync` accepts a **factory** and calls it exactly once,
  inside the target thread — asserted by recording the thread id at
  factory-call time (`Y-a`).
- **`SY5`** The thread is non-daemon and is joined without a timeout —
  asserted from the source AST, plus a behavioral leg proving `run_sync`
  does not return while the coroutine is still running (`Y-d`).

### OU — the outcome mapping

- **`OU1`** Every row of §3.12's table, one leg each, driven through the
  fake CLI or a monkeypatched client. Nine legs, each asserting all five
  `Outcome` fields.
- **`OU2`** `rc` is `1` on every `failure="exit"` with no real exit code,
  the real code when a `ProcessError` carries an `int`, and `None` on
  `timeout` / `not-found` / `os-error` (`O-rc`).
- **`OU3`** Every failure leg's log line is byte-identical to the one
  `CliBackend` produces for the same surface and failure — asserted by
  driving both backends with the same `SessionSpec` and comparing the
  captured text, **and** by `monkeypatch.setitem` on `LOG_TEMPLATES`
  requiring the emitted line to change (`O-log`, `U-seam` `B-3a`).
- **`OU4`** A clean session writes **nothing** through `spec.log`; each of
  the three degradation lines appears **only** when its condition is
  forced (`O-quiet`).
- **`OU5`** A bare `OSError` from the transport escapes
  `SdkBackend.text_session` **and** `analyst.analyze` as an `OSError`, and
  is caught and rendered on the worker and miner surfaces. The analyst
  leg carries an inline comment naming preserved defect `R-1`
  (`O-analyst-oserror`).
- **`OU6`** Analyst text extraction, both branches: `ok_text` yields
  `ResultMessage.result` verbatim; `ok_blocks_only` yields the joined
  `TextBlock`s of the final `AssistantMessage`; a session with neither
  yields `""` (`E-7`).
- **`OU7`** `Outcome.stdout` is `""` on both worker surfaces even when the
  session produced text, and is the extracted text on the miner and the
  analyst (`O-stdout`).
- **`OU8`** An unknown message type mid-stream is skipped, not raised: a
  fake scenario emitting a `{"type":"stream_event", …}` the mapper does
  not know still reaches a clean `ResultMessage` and `ok=True`
  (`O-drain`).

### EV — capture

- **`EV1`** `SdkOutcome` is a frozen dataclass, `isinstance(…, Outcome)`
  is true, `Outcome`'s `ok`/`failure` invariant still raises on
  violation, and every field defaults so `SdkOutcome(ok=True, rc=0,
  stdout="", detail="", failure=None)` constructs (`E-1`).
- **`EV2`** `tool_events` carries one entry per `ToolUseBlock` and one per
  `ToolResultBlock`; `denials` carries the charter's DENYs **and**
  `ResultMessage.permission_denials`; `cost_usd`, `turns` and
  `session_id` come off the `ResultMessage` and are `None` when it
  reports none (`E-2`).
- **`EV3`** The JSONL file is written at
  `cache_dir()/<surface>.tool-events.<run_id>.jsonl` with `run_id`
  matching `^\d{8}T\d{6}Z-\d+$`, a `meta` first line carrying
  `session_id`, and one line per event. It exists **after a timed-out
  session too** — the leg that proves the write is in `finally` (`E-3`).
- **`EV4`** Nothing in `invocation_sdk/` reads a `.tool-events.` file:
  source scan (`E-4`).
- **`EV5`** Retention keeps the newest `SELF_LEARN_SDK_EVENT_LOGS` files
  and unlinks the rest, per surface — a second surface's files are
  untouched by the first's prune (`E-5`).
- **`EV6` — the negative control for `EV5`.** A decoy file in
  `cache_dir()` that does not match `<surface>.tool-events.*.jsonl`
  survives a prune that deletes twenty that do. Named files:
  `worker.log`, `worker.window`, `miner.tool-events.X.jsonl` while
  pruning `worker` (`E-5`).

### RS — the registry

- **`RS1`** `pyproject.toml`'s `[project.optional-dependencies]` block is
  **byte-unchanged** from `c2669a9`, and
  `test_invocation.py::test_rg8_…` passes (`Dep-2`).
- **`RS2`** With `claude_agent_sdk` importable,
  `SELF_LEARN_BACKEND=sdk` makes `backend_for` return an `SdkBackend` for
  every surface. With the import blocked **by an import-block shim** — a
  `sys.meta_path` finder (or a `monkeypatch.setitem` on `sys.modules`)
  that raises `ImportError` for `claude_agent_sdk` and for nothing else,
  **never by uninstalling** — it raises `BackendUnavailable` whose
  `str()` is **byte-identical** to `_SDK_UNAVAILABLE_MESSAGE` and whose
  `__cause__` is the `ImportError` (`R-d`, `Dep-1`). The shim is what
  keeps the dev-group dependency from masking the missing-extra path.
- **`RS3`** `import self_learn.invocation` does **not** import
  `claude_agent_sdk` — asserted by checking `sys.modules` in a fresh
  interpreter after importing the seam (`R-e`).
- **`RS4`** A `claude_agent_sdk` that raises something other than
  `ImportError` on import **propagates** — it is not reported as "not
  installed" (`R-f`).
- **`RS5`** `git diff c2669a9..HEAD -- .../invocation/registry.py` touches
  exactly the `if value == "sdk":` hunk of §3.2 and nothing else, and
  `git diff --numstat` over that path reports **at most `6` insertions
  and `2` deletions in one hunk** (`R-g`). *Instrument criterion.*
- **`RS6`** The lazy-import target resolves to this unit's sibling
  package, asserted by **identity**: the object `backend_for` returns
  under `SELF_LEARN_BACKEND=sdk` satisfies
  `type(backend) is self_learn.invocation_sdk.SdkBackend`, where the
  right-hand side is imported independently in the test. A same-named
  class reached by any other route fails (`R-h`).
- **`RS7`** The CLI `pyproject.toml`'s `[project] dependencies` array is
  **byte-unchanged** from `c2669a9` — `claude-agent-sdk` appears in
  `[dependency-groups] dev` and in `[project.optional-dependencies]`, and
  in **neither** the runtime dependency list nor anywhere else (`Dep-1`).
- **`RS8` — the lockfile content class (BLOCKER-2).** Parsed, not
  grepped, over both lockfiles at `c2669a9` and at `HEAD`:
  - **`cli/uv.lock`**: the set of `[[package]]` `(name, version)` pairs
    is **identical** — no package added, none removed, no version
    changed. The only differences are the `self-learn-cli` member's
    `[package.dev-dependencies] dev` and
    `[package.metadata.requires-dev] dev` lists, each gaining
    `claude-agent-sdk` and nothing else. *(This bound is tight because
    the SDK and its transitive `anyio` / `mcp` / `sniffio` are **already
    locked** for the `[sdk]` extra — measured at `c2669a9`, where
    `claude-agent-sdk` resolves to **0.2.134**.)*
  - **`ui/uv.lock`**: the `(name, version)` pair set is identical, and
    the **only** changed block is the `self-learn-cli` member's
    `[package.metadata.requires-dev]`.
  - Neither file's `[project] dependencies`-derived `requires-dist`
    entries change on either member.

### HG — hygiene

- **`HG1`** `test_invocation_sdk.py` contains no line matching
  `\[\s*"claude"\s*\]` that does not also contain
  `worker._invoke_claude(` — `U-seam` `B-1` restated where it binds
  (`FK-b`).
- **`HG2`** No test in this unit reaches the network: every session sets
  `SELF_LEARN_SDK_CLI_PATH` to the fake, and a source scan asserts no
  test constructs `ClaudeAgentOptions` or `SdkBackend` without it
  (`FK-a`).
- **`HG3`** The fake CLI never spawns a model: source scan of
  `tests/fixtures/fake_claude.py` for `subprocess`, `socket`, `urllib`,
  `http` — none present.
- **`HG4`** Every test in this unit that resolves `cache_dir()` runs
  under a redirected `XDG_CACHE_HOME` — inherited from `conftest.py`'s
  autouse fixture; asserted once, positively, by writing a sidecar and
  checking it landed under `tmp_path`.
- **`HG5`** pyright is clean over the new package. From
  `plugins/self-learn/cli/`:

  ```
  pyright --pythonpath .venv/bin/python src/self_learn/invocation_sdk
  ```

  "Clean" means **0 errors** over that path. The build report also
  records the whole-`src` count and its **delta against the `c2669a9`
  baseline, which must be 0** — scoped-zero alone cannot distinguish this
  unit's errors from the tree's pre-existing ones.
  *Instrument criterion.*

---

## 5. Mutation plan

**64 mutations** (`M1`–`M64`). Every mutation is applied to the **built**
code, the suite is run, and the named criteria must **redden**. A
mutation that leaves the suite green is a hole in §4 and must be closed
before the gate, not explained away.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | `ClaudeSDKClient` replaced by string-prompt `query()` | `OP1`, plus every **session-driven** `CH` criterion (`CH9`) and everything downstream of a real drive (`KL*`, `OU*`, `EV*`) — **corrected by the code gate (NOTE-5): NOT "every `CH` criterion" as originally stated.** `CH1`–`CH8` and `CH10`–`CH13` unit-test `build_can_use_tool` directly against a hand-built `Containment`; they never construct a `ClaudeSDKClient` at all, so this mutation cannot reach them. Only `CH9` (denial recording, session-driven) is actually exercised |
| `M2` | `allowed_tools=[]` → `["Read","Grep","Glob"]` | `OP2`. **`CH1`/`CH2` are NOT credited** — the shadowing affects reads, which the charter allows anyway (`C-2`); gate-measured |
| `M3` | `setting_sources=[]` dropped (field not passed) | `OP3` |
| `M4` | `options.settings` set to the containment's settings path | `OP4` |
| `M5` | `permission_mode` derived from `containment.default_mode` (`None` → field unset) | `OP5` |
| `M6` | `SdkBackend.text_session` delegates via `self.write_session(spec)` | `PL5`, and `test_invocation.py::test_wr7_…` (shipped, un-editable) |
| `M7` | `strict_mcp_config` derived from `containment.strict_mcp` | `OP6` |
| `M8` | `disallowed_tools` hardcoded to the UI's `["Bash","Task","WebSearch","WebFetch"]` | `OP7`, `CH2`'s miner leg (Read/Grep/Glob no longer structurally denied) |
| `M9` | `max_turns` read from the `MINER` selector for `worker-repair` | `OP8` |
| `M10` | Feature detection made silent: an unappliable cap is dropped with no log line | `OP9` |
| `M11` | `system_prompt` left at its default (`None`) | `OP10`. **This is `F-D`, and it is the mutation this document is most afraid of** — see the note below the table |
| `M12` | `system_prompt` passed as a bare `str` (the doctrine text) instead of the append-preset | `OP10` |
| `M13` | `cli_settings_writer` skipped; `cli_argv_builder(None)` called directly | `OP12`, and the miner leg of `OU1` (`AssertionError` from `_reader_cli_argv_builder`) |
| `M14` | `disallowed_tools` read from argv's `--disallowedTools` instead of from the containment | `OP13`. **`OP7` is NOT credited** — the two agree today, which is exactly why the witnesses must stay separate (`A-5`) |
| `M15` | `fallback_model="claude-haiku-4-5"` added (copied from the UI engine) | `OP14` |
| `M16` | `provider_env` called a second time and the two dicts merged | `OP16` |
| `M17` | `run_sync` takes a coroutine object instead of a factory | `SY4`, `SY2` |
| `M18` | `run_sync`'s thread branch wraps the exception in `RuntimeError` | `SY3`, `OU5` |
| `M19` | Charter allows `Edit` and denies `Write` on matching paths | `CH1` |
| `M20` | Charter's final fall-through returns `PermissionResultAllow()` | `CH2`, `CH3` |
| `M21` | The expected side is `.resolve()`d in full (leaf included) | `CH4`. **`CH5` stays GREEN** — recorded, because `CH5` is the control for the *opposite* over-correction and must not be credited here |
| `M22` | Nothing is resolved on the expected side (the trusted prefix left raw) | `CH5`. **`CH4` stays GREEN** — the negative-control pair, both directions covered |
| `M23` | The matcher replaced by `fnmatch.fnmatch` | `CH6` (the `*`-crosses-`/` widening: `<home>/skills/proposals-evil.yaml` starts matching) |
| `M24` | `CharterPatternUnsupported` swallowed and the pattern skipped | `CH7` |
| `M25` | `disconnect()` awaited with a plain `wait_for` (no `shield`) | `KL2`, `KL3` |
| `M26` | The abandoned task's strong reference dropped | `KL3` |
| `M27` | The `getpgid` guard removed — `os.killpg` unconditionally | `KL5`. **The recorder form is what makes this survivable**: the real-signal form would kill pytest (`K-2a`) |
| `M28` | `_SDK_UNAVAILABLE_MESSAGE` re-spelled in `registry.py` | `RS2`, and `test_invocation.py::test_rg4_…`/`test_rg5_…` (shipped) |
| `M29` | `except ImportError` widened to bare `except Exception` | `RS4` |
| `M30` | The sidecar unlink moved out of `finally` | `KL7`'s timeout leg |
| `M31` | The orphan sweep's `/proc` cmdline check dropped (kills on pid liveness alone) | `KL8`'s second leg |
| `M32` | `SdkOutcome` made a plain dataclass, not an `Outcome` subclass | `EV1`, and every `OU` criterion that asserts on `Outcome` fields |
| `M33` | The JSONL write moved out of `finally` (success path only) | `EV3`'s timeout leg |
| `M34` | Retention's pattern widened to `*.jsonl` | `EV6`. **`EV5` stays GREEN** — the negative control earns its row here |
| `M35` | `options.env` populated from `os.environ` | `OP17` |
| `M36` | `rc=None` on `failure="exit"` | `OU2`, `OU3` (the `exited` template renders `None`) |
| `M37` | `SdkBackend` carries its own copies of the four failure f-strings | `OU3`'s `setitem` leg. **The emitted bytes are identical**, so no byte-comparing leg can catch it — `U-seam` `B-3a`'s third site, restated |
| `M38` | A per-session summary line logged unconditionally through `spec.log` | `OU4` |
| `M39` | An `OSError` leg added on the analyst surface, converting to `AnalystError` | `OU5` |
| `M40` | Extraction branch 2 removed (only `ResultMessage.result` read) | `OU6`'s `ok_blocks_only` leg |
| `M41` | Extraction prefers branch 2 over branch 1 | `OU6`'s `ok_text` leg |
| `M42` | The drain raises on an unrecognized message type | `OU8` |
| `M43` | The four deny branches collapsed to one shared message | `CH8` |
| `M44` | The charter's DENY not appended to the `EventLog` | `CH9`, `EV2`'s denial leg |
| `M45` | `tool_events` records `ToolUseBlock`s only, never `ToolResultBlock`s | `EV2` |
| `M46` | `client.interrupt()` awaited **unbounded** (no `wait_for`) | `KL1`, and `KL4` (the ladder never reaches step 3 against `hang_sigterm_ignored`) |
| `M47` | The explicit child kill moved out of the coroutine into a module-level `atexit` handler | `KL4`. **`KL5` is NOT credited** — the recorders still see the same calls, just too late; only the integration leg observes the ordering |
| `M48` | `child_pid_of` lets `AttributeError` escape instead of returning `None` | `KL6` |
| `M49` | `--model`'s value read as `argv[argv.index("--model") + 1]` with no bounds check | `OP11`'s last-element leg (`IndexError`) |
| `M50` | `cli_path` read from a differently-named env var | `OP15`, and every session-driving criterion (`CLINotFoundError` — the fake is never found). **Deliberately this shape rather than "hardcode `None`"**: a mutant that falls through to the SDK's own PATH resolution would invoke the REAL `claude` from inside the suite, which `HG2` exists to prevent and which no mutation may cause |
| `M51` | `Outcome.stdout` carries the extracted text on the worker surfaces too | `OU7` |
| `M52` | `run_sync`'s thread created `daemon=True` and joined with `timeout=0.1` | `SY5` |
| `M53` | The hatch keyed on `default_mode is None` **alone**, dropping `C-10`'s write-set conjunct | `CH11` legs (ii) and (iv) — the analyst's charter goes fully permissive and `DEGRADED_WORKER_CONTAINMENT` starts granting. **`CH10` stays GREEN**: the worker case is unaffected, which is precisely why the conjunct needs its own control |
| `M54` | The hatch **also** sets `permission_mode="bypassPermissions"` | `CH12`. **`CH10` stays GREEN** — the write is approved either way; only the fence sees it. This is the `O-2` shadowing hazard, re-entering through the hatch |
| `M55` | The hatch placed **above** step 1, so it bypasses `D` too | `CH10`'s second leg (`Bash` approved on the worker). Records that `--disallowedTools` survives `bypassPermissions` on the CLI, so a hatch that bypassed it would be wider than the thing it mirrors |
| `M56` | The hatch removed entirely — the charter denies regardless of `default_mode` | `CH10` |
| `M57` | The hatch logs a line through `spec.log` when it opens | `CH13`, `OU4`. The CLI path is silent; a new operator-visible line on an incident-window path is a divergence, not a courtesy |
| `M58` | `registry.py`'s lazy import points at `..invocation.sdk` (a module that does not exist) | `RS6`, and `RS2`'s positive leg. **`RS5` is NOT credited** — the numstat and the hunk location are unchanged by a one-word target edit, which is exactly why identity is asserted separately |
| `M59` | `claude-agent-sdk` added to `[project] dependencies` as well | `RS7`. **`RS1` is NOT credited** — it pins the `[project.optional-dependencies]` block, which this mutation leaves alone |
| `M60` | **The absence fixture is removed from ONE of `Sim-2`'s nine** (the SDK stays installed) | `SU6`, **and that test itself**. This is the row that proves the shim is **load-bearing, not decorative**: without it the amendment could be a no-op comment and every criterion would stay green. Run it against `test_rg4_…` (a one-raise test — the smallest unambiguous signal) and separately against `test_rg5_shimmed_worker_run_completes_under_sdk_selection`, where the failure mode is the `Sim-3` live-session hazard rather than a clean assertion error |
| `M61` | A locked version bumped in `cli/uv.lock` (e.g. `pytest`), or a `[[package]]` stanza added | `RS8`. **`SU3` is NOT credited** — the path is already allowed by the restated table; only the *content* bound sees this, which is why `RS8` parses the lock rather than diffing its name |
| `M62` | `C-10`'s second conjunct written as `containment.write_globs` alone, not the union with `write_exact` | `CH10`'s **third leg** (`worker-repair` never opens). **`CH10`'s first two legs and all four `CH11` legs stay GREEN** — the batch surface has non-empty `write_globs`, so every other hatch criterion is blind to this. Negative control for the union (MAJOR-3) |
| `M63` | `prune_event_logs` retains everything (or off-by-one on `SELF_LEARN_SDK_EVENT_LOGS`) | `EV5`. **`EV6` is NOT credited** — a no-op prune deletes nothing, including the decoy, so the negative control passes vacuously. This row is what stops `EV5`+`EV6` from being satisfiable by a function that does nothing (MAJOR-4) |
| `M64` | An `autouse` fixture added to `test_invocation_sdk.py` (e.g. one setting an env var) | `SU6` leg (iv). The row exists because the damage this fixture class does lands in the **61 shipped tests**, not in this unit's own — so the mutant's *visible* symptom may be a shipped test failing for a reason nothing in §4 would otherwise explain (`Sim-1a`) |

**`M11` is the mutation this document is most afraid of.** It is not a
deliberate act — it is the **default**. A builder who simply does not
pass `system_prompt` gets `--system-prompt ""`, every model session runs
with no system prompt, every criterion about permissions and transports
stays green, and the only symptom is that the worker's judgement quietly
gets worse. `OP10` is the guard, and it asserts `is not None` explicitly
before comparing shapes so that "field absent" and "field wrong" fail the
same way.

**`M21`/`M22` and `M34` are the negative-control rows.** Each names a
criterion that must stay **green** as well as one that must redden. A
guard that reddens for both over-correction and under-correction is
specific; one that reddens for everything is a tripwire, and a gate
cannot tell the difference without these rows.

### 5.1 Criteria with NO mutation row, declared

**A criterion no mutation exercises is a criterion nobody has shown can
fail.** Twenty of §4's eighty-two have no row, and each falls into one of
four declared classes. Anything not in this list has a row; a gate that
finds a fifth class has found a hole. **Every criterion added by the r2
and r3 folds (`CH10`–`CH13`, `RS6`, `RS7`, `RS8`, `SU6`) carries a row** —
a ruling or finding that arrives without a mutation is one nobody can
show was implemented. `EV5` was the r2 draft's **fifth class** — no row
and no declaration, and satisfiable by a `prune_event_logs` that does
nothing — and `M63` closes it, which is what restores this section's
completeness claim (MAJOR-4).

**Reading the "NOT credited" notes.** Three rows (`M21`/`M22`, `M34`,
`M53`/`M54`, `M58`, `M59`) name a criterion that must stay **GREEN**.
Those mentions are not coverage — `RS1`, `RS5` and `CH10` appear in this
document's mutation table *only* in that role, and each is still declared
below or covered by its own separate row.

| Class | Criteria | Why no row |
|---|---|---|
| **Instrument** — satisfied by a recorded command's output, not by a test function | `SU2`, `SU3`, `RS5`, `HG5` | There is no code to mutate. The evidence is the command output in the build report; a gate re-runs the command instead of mutating |
| **Baseline / anti-tamper** — the criterion's subject is the *absence* of a change | `SU1`, `SU4`, `SU5`, `RS1` | Their "mutation" is editing the file they pin, which is exactly the act they detect; `M6`, `M28` and `M34` already demonstrate that detection working through the shipped tests |
| **Structural guards whose mutation is the guard's own subject** | `PL1`, `PL2`, `PL3`, `PL4`, `PL6`, `EV4`, `RS3`, `HG1`, `HG2`, `HG3`, `HG4` | Each asserts a property of the source tree (an import, a write, a call, an import order). "Mutating" one means writing the forbidden construct, which is the criterion's definition rather than an independent probe. The build report records one such demonstration per criterion — *add the import, watch it redden, remove it* — instead of a numbered row |
| **Happy path already covered transitively** | `SY1`, `OU1`'s success row | A `run_sync` that does not return the coroutine's value fails every session-driving criterion in `OP`, `CH`, `KL`, `OU` and `EV` at once. A dedicated row would add no information |

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** The package lives **outside** `invocation/`, as
  `invocation_sdk/`, because `HY2`, `HY4` and the root-level lock census
  each independently forbid the alternatives, and no existing test file
  may be edited (`L-a`). The nested `invocation/sdk/` form is refused as
  evasion (`L-c`).
- **`D-2`** The invisibility that placement buys is **re-covered
  in-package** by `PL3` and `PL4`, rather than left as a second instance
  of the census hole `U-seam` `B-6` documented (`L-b`).
- **`D-3`** `registry.py` is the **one** existing file edited, and only
  its `sdk` branch. The byte-pinned unavailable message does not move
  (`R-d`).
- **`D-4`** Model and doctrine are read from the surface's **argv** —
  the only other statement of the invocation the seam provides — and the
  read set is **closed at two flags** (`A-5`). `SessionSpec` is not
  widened.
- **`D-5`** `permission_mode="default"` unconditionally; not derived from
  `containment.default_mode`. Narrowing-only (`O-2`).
- **`D-6`** `strict_mcp_config=True` unconditionally; not derived from
  `containment.strict_mcp`. Narrowing-only, and a **documented
  divergence** from the containment record (`O-3`).
- **`D-7`** `options.settings is None`, while the settings **file is
  still written** — because a settings allow-rule shadows the callback,
  and the charter must be the only permission authority (`A-2`).
- **`D-8`** `system_prompt` is always the `claude_code` preset, with
  `append` only on the analyst. Never `None`, never a bare `str`
  (`A-3`, `F-D`).
- **`D-9`** Three budget guards: wall-clock mandatory, turns defaulted
  per surface, spend **wired but unset** (`O-1`). An unappliable cap logs
  (`O-1a`).
- **`D-10`** `run_sync` takes a factory, uses a dedicated non-daemon
  thread when a loop is running, joins unbounded, and re-raises with the
  original type (`Y-a`…`Y-d`). Specified and tested even though no
  shipped caller needs the second branch today (`Y-e`).
- **`D-11`** The charter gates the **write family by path** and nothing
  else; the UI's read-root apparatus does not port, because no CLI
  surface scopes reads by path (`C-2`).
- **`D-12`** `Write` is gated and `Edit` is denied — the shipped CLI
  boundary, quoted from `write_permission_rules` (`C-3`).
- **`D-13`** The glob matcher is written out rather than delegated to
  `fnmatch`, whose `*` crosses `/` and would widen the boundary; an
  unsupported metacharacter **fails closed** (`C-6`, `C-7`).
- **`D-14`** The kill ladder gains a third rung the UI does not have — an
  explicit child kill before the coroutine returns — because
  `asyncio.run` closes the loop and would otherwise strand the SDK's own
  escalation (`K-1a`).
- **`D-15`** The `killpg` is guarded by `getpgid`, and the guard is tested
  through **recorders** rather than real signals (`K-2`, `K-2a`).
- **`D-16`** The pid sidecar carries `pid`, `started_at` and `cli`, and
  the sweep refuses to kill when it cannot corroborate the identity —
  pid reuse is the failure mode a bare pid invites (`K-4`, `K-5`).
- **`D-17`** `SdkOutcome` is a **subclass**, so `contract.py` stays frozen
  and the parallel Wave-1 units do not rebase over a contract change
  (`E-1`).
- **`D-18`** The tool-events file is named by a **start-of-session** run
  id, not by the session id, so a timed-out run still produces a
  readable, uniquely-named file (`E-3`).
- **`D-19`** Retention prunes only the exact per-surface pattern, and a
  negative control proves it (`E-5`, `EV6`).
- **`D-20`** The provider extension point is **one function in one file**,
  called once, assigned without merging — so `U-bedrock`'s merge is
  mechanically disjoint from this unit (`PS-a`, `PS-c`).
- **`D-21`** The `[sdk]` extra's pin **does not move**; the version
  question is answered by runtime feature detection instead (`Dep-2`,
  `O-1a`).
- **`D-22`** `claude-agent-sdk` joins the CLI's **dev** group, because an
  `importorskip`-shaped unit is an untestable unit and its mutation plan
  cannot be run (`Dep-1`).
- **`D-23`** No module under `src/self_learn/` may **call**
  `write_session(`/`text_session(`; `SdkBackend`'s two methods delegate
  to `self._run` (`L-d`).
- **`D-24`** *(ruling `V-4`)* **`SELF_LEARN_ENFORCE_SCOPE=0` keeps its
  meaning on the sdk backend**, honored in the **charter callback**
  (`C-10`) rather than in the option set. The r1 draft's proposal to let
  it silently stop working is struck: an incident-window escape hatch
  that quietly does nothing is the fail shape this campaign exists to
  hunt. The mirror is sourced from `worker.py`, including its **silence**
  (`CH13`), and fenced by `CH12`.
- **`D-25`** *(ruling `V-4`)* The hatch is a property of the containment
  **data** — `default_mode is None` **and** a non-empty write scope — not
  an `os.environ` read inside `charter.py`. The second conjunct is what
  keeps the analyst and `DEGRADED_WORKER_CONTAINMENT` closed; without it
  the hatch opens on a surface the variable never reached (`M53`).
- **`D-26`** *(ruling `V-1`)* The registry's lazy-import target is
  asserted **by identity** against the sibling package, not by spelling,
  because a wrong target degrades quietly into the `BackendUnavailable`
  path and would survive a green suite (`R-h`, `RS6`). The one-file edit
  is numstat-bounded (`RS5`).
- **`D-27`** *(ruling `V-3`)* The SDK enters the **dev group only**, and
  the missing-extra path is exercised by an **import-block shim** rather
  than by uninstalling — so the dependency that makes the unit testable
  cannot mask the behavior the unit is testing (`Dep-1`, `RS2`, `RS7`).
- **`D-29`** *(gate BLOCKER-1)* `test_invocation.py`'s nine
  refusal-asserting tests are **amended in this unit** to simulate the
  SDK's absence rather than rely on it. The tests were **latently
  venv-dependent** — installing the `[sdk]` extra for any reason breaks
  them today — so this is a repair of their oracle, and the suite comes
  out *less* environment-coupled (`Sim-0`, `Sim-1`). The allowance is
  enumerated by test name, structurally bounded (`SU4`), and does not
  reach `HY2`/`HY4`/`WR7`.
- **`D-30`** *(gate BLOCKER-1)* **No test in the CLI suite may start a
  real SDK session under any mutation of this unit**, established two
  independent ways (`Sim-3`) — the PATH-shim counter that guards test 7
  today cannot see a `_bundled/` CLI, so it is not one of the two.
- **`D-31`** *(gate BLOCKER-2)* Both lockfiles are **disclosed** in the
  may-touch table with parsed content bounds (`RS8`) rather than left as
  an undeclared side effect. The bound is tighter than expected because
  the SDK is already locked for the `[sdk]` extra: **no `[[package]]`
  stanza and no version changes at all**.
- **`D-32`** *(gate MAJOR-1)* The option set is observed at an
  **assembled-kwargs seam** (`options_kwargs`) and tied to a
  **constructor spy**, not by AST-scanning the construction call — a
  `**kwargs` call has no AST keywords, so the r2 form contradicted
  `O-1a`'s feature gating (`O-0`, `O-0a`).
- **`D-28`** *(ruling `V-2`)* Budget defaults stand as drafted, with the
  rationale recorded rather than assumed: the CLI path is already
  uncapped in dollars under identical unattended exposure, so
  unset-on-sdk is no regression, and `cost_usd`/`turns` capture means
  burn-in — not this spec — sets the informed numbers (`O-1b`, `R-7`).

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Out-of-scope look-alikes

Every site `U-seam` §7.1 excluded stays excluded, unchanged and
unexamined: `worker._spawn_window`, `worker._digest`, `worker._notify`,
`worker._notify_with_ids`, `miner._spawn_run`, and every `subprocess`
site in `gitops.py`, `hosts.py`, `ledger.py`, `ledger_ops.py`,
`chezmoi.py`, `hook_compiler.py`. None spawns a model; none acquires an
SDK path. `PL5` is where that stays honest.

### 7.2 The UI package is still the port source and is still not touched

`U-seam` §7.2's ruling stands verbatim, and this unit strengthens the
reason: the UI engine is now the **reference implementation** for the
ladder and the charter, and a shared abstraction extracted before the CLI
side has burned in would freeze the wrong seam. The naming echo
(`SdkBackend` ↔ `SdkPaneEngine`, `build_can_use_tool` ↔
`build_can_use_tool`) is a reading aid, not a contract. `SU3` enforces
the no-touch.

### 7.3 Residuals this unit accepts, with owners

- **`R-1` — the analyst's missing `OSError` leg is preserved on the SDK
  backend too.** Deliberately: `U-seam` `T-c` preserved it on
  `CliBackend`, and fixing it on one backend only would mean the defect's
  eventual fix has to be found twice. Pinned by `OU5`. Owner: the
  existing `FW` row `U-seam` opened for `R-1`; this unit adds a note that
  the fix must now land on **both** backends.
- **`R-2` — the hatch's mirror is exact on THIS host and slightly WIDER
  on a host whose global settings do not set `bypassPermissions`.**
  *(r1 recorded "the variable stops working" as the residual; ruling
  `V-4` struck that and `C-10` makes the variable work. What remains is
  narrower and is stated honestly rather than dropped.)* On the CLI,
  `ENFORCE_SCOPE=0` omits `permissions.defaultMode` and the **host's
  own** `~/.claude/settings.json` decides what happens next — on this
  machine that is `bypassPermissions` (measured), so the scope is fully
  voided and `C-10`'s unconditional approve is an exact mirror. On a host
  whose global settings set something stricter, the CLI would still
  refuse some of what `C-10` approves. The sdk hatch is therefore the
  **one place in this unit where the SDK path can be wider than the CLI
  path** — and only when the operator has deliberately opened an
  incident-window hatch. Reading the host settings to narrow it back
  would mean loading the settings source `F-C` exists to keep out.
  Owner: a new `FW` row — *"decide whether the hatch should consult the
  host's `permissions.defaultMode` without loading the host's settings
  into the session."*
- **`R-8` — a SIGKILLed child is left as a zombie for the CLI process's
  lifetime.** `K-2b`, measured: the SDK's `close()` discards from
  `_ACTIVE_CHILDREN` only a child it reaped, its `atexit` reaper sends
  `SIGTERM` only, and `K-2` kills without `waitpid`. Bounded at **≤ 2 per
  run** and reaped by `init` when the CLI exits. **Accepted, not fixed**:
  adding a `waitpid` would put two reapers on one pid, racing the SDK's
  own shielded `process.wait()`. Owner: a new `FW` row, to be revisited
  only if a long-lived caller (the UI, in-process) ever hosts these
  sessions — that is the shape where "process lifetime" stops being
  minutes.
- **`R-9` — the nine amended shipped tests are a shared surface with
  every later unit.** `Sim-1` fixes a latent venv dependency, but it also
  means `test_invocation.py` now carries a fixture this unit owns. A
  later Wave-1 unit that also needs to amend those tests will collide.
  Owner: a new `FW` row — *"the absence fixture is `U-sdk`'s; a unit
  needing to change it should promote it to `conftest.py` rather than
  fork it."*
- **`R-7` — the budget defaults are unmeasured guesses.** `max_turns`
  120/60/30 and `max_budget_usd` unset (`O-1`, `O-1b`) rest on no data:
  no shipped run has ever been counted in turns or dollars. The capture
  this unit ships (`cost_usd`, `turns`, the JSONL sink) is what produces
  the distribution. Owner: the **post-burn-in recalibration unit** —
  same owner as `R-6`'s tool-events consumer, and it should set both
  numbers from the measured distribution rather than re-guessing.
- **`R-3` — the `[sdk]` extra's floor (`>=0.2.116`) is lower than the
  version this unit was written against (`0.2.121`), and `RG8` forbids
  moving it alone.** Runtime feature detection (`O-1a`) covers the two
  fields whose presence is version-dependent, but a 0.2.116 environment
  is genuinely untested by this unit. Owner: a new `FW` row —
  *"raise both pins in one commit, or drop `RG8`'s cross-package
  coupling."*
- **`R-4` — `run_sync`'s in-loop branch has no shipped caller.**
  Measured: the UI drives verbs through `VerbRunner` subprocesses and
  calls no seam function in-process (`Y-e`). The branch is specified,
  tested and mutated as a forward guarantee. Recorded so a future reader
  does not mistake test coverage for production exercise. Owner: a new
  `FW` row, to be closed when the UI first calls a seam surface in-loop.
- **`R-5` — the glob matcher is a re-implementation of the CLI's rule
  semantics and could disagree with it.** `C-6` pins ten cases and `C-7`
  fails closed on anything it does not implement, so every known
  divergence direction is *narrowing*. An unknown divergence in the
  widening direction is the residual risk. Owner: a new `FW` row —
  *"differential-test the matcher against the live CLI's own rule
  evaluation."* §8 row 7 is the build-time down-payment.
- **`R-6` — no burn-in evidence exists for any surface.** This unit ships
  the capability; it does not switch any surface to it. The default at
  every rung is still `cli` (`U-seam` §3.7.1 rung 5). Owner: the
  post-merge burn-in unit, which also owns the tool-events consumer
  (`E-4`).

- **`R-10` — `_extract_target_path`'s key precedence lets the charter
  judge `file_path` while a `NotebookEdit` call actually acts on
  `notebook_path`.** Code-gate NOTE-2 (2026-08-18). A ported property
  (`P` == the UI charter's `_PATH_KEYS`, in the same order) — unreachable
  today (no shipped `Containment` distinguishes the two keys), but the
  ambiguity belongs in the port source's own residuals too, not just
  here. Owner: `U-seam`'s port source, if `NotebookEdit` scoping ever
  needs to distinguish the two paths.
- **`R-11` — `_compile_glob`'s anchorless-pattern fallback roots at `/`
  (widening) instead of failing closed.** Code-gate NOTE-4. `_compile_glob`'s
  `else str(Path("/").resolve())` branch fires when `_split_trusted_prefix`
  finds no leading non-wildcard segment (e.g. a bare `*.yaml`), compiling
  to `^/[^/]*\.yaml$` — `/anything.yaml` would `ALLOW`. Unreachable from
  `containment_for` today (every shipped pattern is absolute), so this is
  a defense-in-depth gap, not a live one. Owner: a new `FW` row — *"either
  reject an anchorless pattern in `_check_supported` (fail closed, `C-7`'s
  own discipline) or document why `/` is an acceptable default root."*
- **`R-12` — five mutation-table rows name a second criterion that
  cannot structurally redden, given this unit's actual test/containment
  shape (not a behavioral defect — a scope over-claim in the table).**
  Code-gate NOTEs 6–12, folded into one residual since they share the
  same shape: `M8`'s "`CH2`'s miner leg" (`CH2` has no miner leg to
  redden); `M13`'s "`OU1`'s miner leg" (`OU1` drives no miner
  `cli_settings_writer`); `M18`'s `OU5` (the analyst path uses
  `run_sync`'s no-running-loop branch, untouched by that mutation);
  `M20`'s `CH3` (its deny lives in decision step 3, not the step-5
  fall-through `M20` edits); `M32`'s "every `OU` criterion asserting on
  `Outcome` fields" (those reads survive on a plain dataclass, and `_run`'s
  own `isinstance(outcome, SdkOutcome)` still holds); `M36`'s `OU3` (`OU3`
  compares `CliBackend`'s not-found line and a `LOG_TEMPLATES` `setitem`,
  never the rendered `exited` rc); `M44`'s "`EV2`'s denial leg" (`EV2`
  asserts `tool_events`/`turns`/`session_id`/`cost_usd`, never `denials`).
  Every row's FIRST-named criterion still reddens correctly; only the
  table's over-claimed second name is wrong. Owner: none — this is a
  documentation-only correction, folded here rather than in the mutation
  table itself to avoid re-litigating all five rows individually.
- **`R-13` — `M60b` (the absence fixture dropped from
  `test_rg5_shimmed_worker_run_completes_under_sdk_selection`) reddens
  only via `SU6`; the test itself still passes.** Code-gate NOTE-13. Under
  the code gate's own containment (`SELF_LEARN_SDK_CLI_PATH` forced to a
  fake) the mutant drove a fake session and the assertions were satisfied
  regardless; with the CLI path genuinely unset, this is the SAME code
  shape `BLOCKER-1` found — the test's assertions cannot detect that an
  SDK session ran AT ALL, only that `worker.run` returned. The
  `_no_real_sdk_spawn_tripwire` fixture (`conftest.py`, added in this
  gate fold) now makes that shape fail LOUDLY the instant it recurs
  anywhere in the suite, which substantially mitigates the live hazard;
  the residual is narrower than before but not closed — `test_rg5_…`
  itself still cannot distinguish "the SDK path ran cleanly" from "no
  session ran at all". Owner: a new `FW` row — *"give
  `test_rg5_shimmed_worker_run_completes_under_sdk_selection` its own
  assertion that a session was actually attempted, not just that
  `worker.run` returned."*
- **`R-14` — `SU4` leg 1's fixture-import hunk is 4 lines, not the 3
  §3.13 itself quotes.** Code-gate NOTE-15. The literal wording of leg 1
  admits only "the single module-level import … or a signature line";
  the actual hunk is the 3-line import form plus one blank line. Inside
  the `test_invocation.py` ≤21/≤9 numstat bound throughout — cosmetic,
  no owner needed.

### 7.4 Not built, with reasons

- **No provider/Bedrock/AWS logic.** `U-bedrock` owns it; this unit ships
  the one extension point and a leak test (`PS-1`).
- **No consumer for the tool-events capture.** Capture only, by mandate
  (`E-4`).
- **No streaming, no partial output, no cost surfacing to the operator.**
  `include_partial_messages=False`; `cost_usd` rides on `SdkOutcome` and
  the JSONL and is rendered nowhere. Adding a cost footer is an
  operator-facing change with its own unit.
- **No `session_store`, `resume`, `fork_session` or `fallback_model`.**
  All four exist on the resolved SDK and all four are pane concepts. The
  CLI surfaces are one-shot.
- **No retry, no backoff.** Not shipped on any surface today.
- **No change to any surface's default backend.** `R-6`.
- **No `FakeBackend` change.** `U-seam`'s fake already satisfies §4's
  needs where a fake is wanted; the SDK criteria use the fake **CLI**
  (§3.10) instead, because the thing under test is the SDK translation.

### 7.5 Handed to `03-decisions.md`

- **`S-36`** — the SDK backend exists; its containment is enforced by a
  `can_use_tool` charter rather than a settings file; three option values
  (`permission_mode`, `strict_mcp_config`, `settings`) are deliberately
  **not** derived from the `Containment` and are fixed at their narrower
  values (`O-2`, `O-3`, `A-2`); the `[sdk]` extra becomes load-bearing;
  no surface's default backend changes.

---

## 8. Verify-at-build ledger

**Every row was measured for this spec on `claude-agent-sdk 0.2.121` /
`claude 2.1.226`, and every row must be RE-CONFIRMED at build time
against the SDK the builder actually resolves** — from the installed
source or a live probe, never from this document and never from memory.
A row that fails re-confirmation is reported, not worked around.

> **THE RESOLVED VERSION IS 0.2.134, AND THE GAP HAS BEEN CLOSED.**
> Measured at `c2669a9`: `cli/uv.lock` pins `claude-agent-sdk` at
> **0.2.134**, while the source reading below was done against the UI
> venv's **0.2.121**. The pin `>=0.2.116,<0.3` permits both. The delta
> gate re-verified this ledger on **0.2.134**, obtained two independent
> ways (uv-cache wheel, and a scratch sdist whose sha256 matches
> `cli/uv.lock:158`): **11 of the 12 rows hold unchanged; row 10 gains
> one additive field.** The three load-bearing facts moved only in line
> number — the `system_prompt` branch to L567, `open_process` (still no
> `start_new_session`) to L835, and the `close()` ladder (same shape) to
> L994. Re-confirmation at build time remains mandatory, but it is now a
> check against a measured baseline rather than an open question.

| # | Question | Measured (0.2.121) | How to re-confirm |
|---|---|---|---|
| 1 | Does `system_prompt=None` emit an **empty** system prompt? | **YES.** `_build_command`: `if self._options.system_prompt is None: cmd.extend(["--system-prompt", ""])` | Read `_build_command` in the resolved `_internal/transport/subprocess_cli.py` |
| 2 | Does the append-preset map to `--append-system-prompt`? | **YES, and ONLY that.** *(NOTE-1: the r2 draft additionally claimed the branch emits `--tools default`. That is **FALSE** on 0.2.121 — `--tools` is a **separate** branch keyed on `options.tools is not None`, and `tools` defaults to `None`. The claim and the "divergence judged harmless" sentence are **struck**. With `tools` left at its default, no `--tools` flag is emitted at all, which is exactly the CLI parity this unit wants — see `O-0`'s closing note.)* | Read the `system_prompt` branch **and** the separate `if self._options.tools is not None:` branch; confirm they are independent |
| 3 | Does the transport set `start_new_session`, and where is the child pid? | **NO** `start_new_session`, no `preexec_fn`. `anyio.open_process(cmd, stdin=…, stdout=…, stderr=…, cwd=…, env=…, user=…)`. Child pid at `client._transport._process.pid`. **Measured: `os.getpgid(child) == os.getpgid(0)` → True** | Re-read `connect()`; re-run the two-line `anyio.open_process` pgid probe. **`K-2`'s guard depends on this row** |
| 4 | Is `--settings` honored under `setting_sources=[]`? | The two flags are emitted **independently** — `--settings` from `_build_settings_value()`, `--setting-sources=` from `effective_setting_sources`. So a settings file WOULD be loaded, which is why `A-2` passes `settings=None` | Read both emission sites; if unsure, probe with a settings file granting a rule and check whether the callback still fires for it |
| 5 | Are `max_turns`, `max_budget_usd`, `fallback_model`, `env` present? | **All four present** on `ClaudeAgentOptions` | `{f.name for f in dataclasses.fields(ClaudeAgentOptions)}` — the same check `O-1a` performs at runtime |
| 6 | Do reads **outside `cwd`** reach `can_use_tool`? | **UNKNOWN.** Probe 2 observed reads inside `cwd` auto-approving. **Does not bind this unit** (`C-2`) | A live probe if a later unit needs path-scoped reads; record the answer in the memo, not here |
| 7 | Does the matcher agree with the CLI's own rule evaluation? | **NOT MEASURED.** `R-5` | Down-payment: run one live `claude -p` with a settings file granting `Edit(/<tmp>/a/**)` and confirm a write to `<tmp>/a/b/c.txt` is permitted and one to `<tmp>/ab/c.txt` is not; compare against `CH6`'s matcher on the same inputs |
| 8 | Is `_bundled/` self-contained, or does it need system Node? | The bundle is an **existence check**, not a hard dependency: `_find_cli()` prefers `_bundled/`, then `shutil.which("claude")` (bundle-exclusion memo, verified in source and empirically) | Re-read `_find_cli()`; confirm `SELF_LEARN_SDK_CLI_PATH` still overrides it |
| 9 | Bundled CLI version vs host `claude` | Host `claude --version` = **2.1.226**. Skew between the SDK's bundled CLI and the host CLI is expected and tolerated (the engine speaks the SDK protocol) | `claude --version`; the doctor that WARNs on skew is **`U-bedrock`'s**, not this unit's |
| 10 | `ResultMessage`'s shape | **0.2.134 (the resolved version), 18 fields**: `subtype, duration_ms, duration_api_ms, is_error, num_turns, session_id, stop_reason, total_cost_usd, usage, result, structured_output, model_usage, permission_denials, deferred_tool_use, errors, api_error_status, terminal_reason, uuid` — `result: str \| None`, `permission_denials: list[Any] \| None`. **The only §8 row that moved between 0.2.121 and 0.2.134**: `terminal_reason` is **additive** (17 → 18), and **nothing this unit reads is affected** — `E-7` reads `result`, `E-2` reads `total_cost_usd` / `num_turns` / `session_id` / `permission_denials`, and `O-log` reads `errors` / `subtype`, all unchanged | `dataclasses.fields(ResultMessage)`; `E-7` and `E-2` depend on it |
| 11 | The three probe footguns (`F-A`, `F-B`, `F-C`) | Measured on 0.2.116 in the memos; the option shapes they depend on are unchanged on 0.2.121 | `F-B`: construct with `allowed_tools=["Read"]` and confirm `CanUseToolShadowedWarning`. `F-A`: call `query(prompt="…", can_use_tool=…)` and confirm the `ValueError`. `F-C`: no live probe needed — `setting_sources=[]` is passed unconditionally either way |
| 12 | Does `skills` promotion still leave an explicit `[]` alone? | **YES.** `_apply_skills_defaults` promotes `setting_sources` to `["user","project"]` **only when it is `None`**; an explicit `[]` survives. This unit sets `skills` never | Read `_apply_skills_defaults` |

---

## 9. What was executed, and against what oracle

Measured on this worktree at base `c2669a9`:

- **CLI suite baseline:** `uv run pytest -q` from `plugins/self-learn/cli`
  — **1716 collected, 1711 passed, 5 skipped, 0 failed, 178.61 s, rc 0**
  (rc read unpiped). This is `SU1`'s figure.
- **`claude_agent_sdk` in the CLI venv:** **absent**
  (`ModuleNotFoundError`). This is `Dep-1`'s figure.
- **Resolved SDK (UI venv):** `claude_agent_sdk` **0.2.121** at
  `plugins/self-learn/ui/.venv/lib/python3.13/site-packages/claude_agent_sdk`.
- **Host CLI:** `claude --version` → **2.1.226**.
- **Process-group probe:** `anyio.open_process(["sleep","5"], …)` — parent
  pid 1026802 / pgid 1026799, child pid 1026809 / pgid 1026799,
  `os.getpgid(child) == os.getpgid(0)` → **True**. This is `K-2`'s
  evidence.
- **Option/message shapes:** `dataclasses.fields(ClaudeAgentOptions)` and
  `dataclasses.fields(ResultMessage)` enumerated; §8 rows 5 and 10 quote
  them.
- **Transport source:** `_build_command`, `_build_settings_value`,
  `_apply_skills_defaults`, `connect()` and `close()` read in the
  installed 0.2.121 tree; §8 rows 1, 2, 3, 4 and 12 quote them.
- **Guards read at `c2669a9`:** `test_invocation.py`'s `HY2`, `HY4`,
  `WR7`, `RG8`; `test_lock_invariant.py`'s census globs;
  `test_attrib.py`'s `HY1`. §3.1's placement argument and §3.11's pin
  argument rest on these four reads.

Nothing in this document was inferred from an unexecuted claim. Where a
fact was not measured, §8 says so (rows 6, 7) and §7.3 owns the residual.

---

## 10. Operator rulings, folded

All four questions the r1 draft routed out were **ruled**. Each ruling is
folded into the normative register above; this section records the
decision and where it landed, so the register stays single and this
section stays a pointer rather than a second statement.

- **`V-1` — placement: the sibling package STANDS.** Ruling: the three
  guards exist precisely to keep the seam package pure (no `worker`
  imports, no filesystem writes); relaxing them to admit a transport that
  needs *both* would spend the guards' whole value to buy a directory
  name. The sibling plus in-package re-coverage (`PL3`/`PL4`) is
  architecture, not evasion, and the explicit refusal of nested
  `invocation/sdk/` (`L-c`) is kept. **Added by the ruling:** the
  lazy-import target must be verified to resolve to the sibling package —
  `R-h`, criterion `RS6` (identity, not spelling), mutation `M58` — and
  the one-line registry edit is numstat-bounded in the may-touch table
  and `RS5`.
- **`V-2` — budget defaults: as drafted.** `max_budget_usd` unset with
  the knob available; `max_turns` 120/60/30 as generous second-line
  ceilings behind `wait_for`, which is the real bound. **Rationale now
  recorded** in `O-1b`: the CLI path today has **no** dollar cap under
  identical unattended exposure, so unset-on-sdk is no regression;
  `Outcome` records `cost_usd` and `turns`; burn-in produces the actual
  distribution and a post-burn-in unit sets informed defaults from data.
  Residual `R-7` carries it with that owner.
- **`V-3` — dev group: SANCTIONED, bounded.** Without the SDK importable
  in the CLI venv every criterion skips and the mutation plan is
  unrunnable, which would make this spec unfalsifiable. **Bounds added**
  to `Dep-1`: dev group only, never `[project] dependencies`
  (criterion `RS7`, mutation `M59`); and the missing-extra path is
  exercised by **simulating absence** with an import-block shim, never by
  uninstalling, so the dev dependency cannot mask the
  `BackendUnavailable` path (criterion `RS2`).
- **`V-4` — `SELF_LEARN_ENFORCE_SCOPE=0` KEEPS its meaning.** Ruling:
  silently ignoring an incident-window escape hatch is the exact fail
  shape this campaign hunts; the r1 draft's assumption is **overruled**.
  **Mechanism added** as `C-10`, consistent with the narrowing-only rule:
  `permission_mode` stays `"default"`, `setting_sources` stays `[]`,
  `strict_mcp_config` stays on, and the **charter callback** honors the
  variable by approving what it would otherwise deny — sourced from
  `worker.py`'s actual behavior, including the fact that the CLI path
  emits **no log line**, so the hatch is silent here too (`CH13`).
  Criteria `CH10` (open, driven end-to-end from the real variable),
  `CH11` (closed, four legs), `CH12` (the fence: the variable must not
  move `permission_mode`, `setting_sources` or `strict_mcp_config`),
  `CH13` (silence parity); mutations `M53`–`M57`. Residual `R-2` is
  rewritten to what actually survives: the mirror is exact on this host
  and marginally wider on a host whose global settings are stricter than
  `bypassPermissions`.

**Nothing in §4 or §5 is open.** A gate reading this section should treat
every ruling as settled input, not as a question still in flight.

---

## 11. Revision history

### r1 — first draft

Written against base `c2669a9` after reading the `U-seam` spec in full,
the four in-house port sources, the three probe memos, and the shipped
guards named in §9. Facts measured rather than assumed: the suite
baseline, the absent CLI-venv dependency, the resolved SDK and host CLI
versions, the process-group identity, the option and message shapes, and
the four transport source sites. Four decisions the plan left open are
recorded in §6 (`D-1`, `D-4`, `D-17`, `D-21`); four questions that bind
the work are routed to the operator in §10 rather than decided.

### r2 — operator rulings folded

All four §10 questions ruled and folded; §10 rewritten from *questions*
to *rulings, folded*, and nothing in §4/§5 is left open. Criteria
**74 → 80**, mutations **52 → 59**.

| Ruling | Outcome | Landed in |
|---|---|---|
| `V-1` | Sibling placement **stands**; import target must be *verified* | `R-h` (new, §3.2); may-touch numstat bound; `RS5` strengthened; `RS6` (new); `M58` (new) |
| `V-2` | Defaults **as drafted**, rationale recorded | `O-1b` (new, §3.5); residual `R-7` (new) |
| `V-3` | Dev group **sanctioned**, bounded three ways | `Dep-1` (§3.11, expanded); `RS2` strengthened (import-block shim named); `RS7` (new); `M59` (new) |
| `V-4` | The variable **keeps its meaning**, via the charter | `C-10` (new, §3.6); `C-4` step 2 (new); `O-2` amended; `CH10`–`CH13` (new); `M53`–`M57` (new); `R-2` rewritten |

Facts newly sourced for the fold, read from master rather than assumed:
`worker._enforce_scope()`'s definition and its four consumers; that the
CLI path emits **no log line** when the switch is off (so the mirror is
silent — `CH13`); that `miner.write_reader_settings` hardcodes
`"defaultMode": "default"` and the analyst passes no `--settings`, which
is why `C-10`'s reach is worker and worker-repair alone; and
`write_repair_settings_file`'s live-CLI-verified docstring for what
omitting `defaultMode` actually costs.

One new residual surfaced *by* the fold rather than papered over: the
hatch's mirror is exact on this host and marginally **wider** on a host
whose global `permissions.defaultMode` is stricter than
`bypassPermissions` — the single place in this unit where the SDK path
can be wider than the CLI path (`R-2`).

### r3 — blind gate folded (NOT SOUND: 2 BLOCKER / 4 MAJOR / 7 NOTE)

Criteria **80 → 82**, mutations **59 → 63**. Every finding folded; each
load-bearing claim independently re-verified against master and the
installed SDK before the fold, not taken on the gate's word.

| Finding | Landed in |
|---|---|
| **BLOCKER-1** — `Dep-1` flips nine shipped tests | §3.13 `Sim-0`…`Sim-3` (new); `test_invocation.py` enters the may-touch table; `SU2`, `SU3`, `SU4` restated; `SU6` (new); `M60` (new); `D-29`, `D-30`; `R-9` |
| **BLOCKER-2** — `Dep-1` re-locks two lockfiles | both lockfiles enter the may-touch table with parsed content bounds; `SU3` restated; `RS8` (new); `M61` (new); `D-31` |
| **MAJOR-1** — `OP14`'s AST scan contradicts `O-1a` | `O-0`, `O-0a` (new); `OP14` restated; `D-32` |
| **MAJOR-2** — `O-quiet`'s list of 3 omits the ported kill-path lines | `O-quiet` list 3 → **5** |
| **MAJOR-3** — no `worker-repair` OPEN leg | `CH10` third leg (new); `M62` (new) |
| **MAJOR-4** — `EV5` was a fifth, undeclared class | `M63` (new); §5.1's completeness sentence restored |
| **NOTE-1** — `--tools default` claim false | §8 row 2 struck and rewritten; `O-0`'s closing note added |
| **NOTE-2** — status header | r1 → **r3** |
| **NOTE-3** — env parity phrasing | `PS-b` rewritten with the measured `process_env` construction |
| **NOTE-4** — `M30` cross-namespace collision | `L-b` qualified as `U-seam`'s `M30` |
| **NOTE-5** — `R-h` prose vs `RS6` | `R-h` aligned to `type(...) is ...` |
| **NOTE-6** — observation point unstated | `O-0a` (new) |
| **NOTE-7** — atexit reaper / zombie | `K-2b` (new); `R-8` |

**Two of the gate's findings came back stronger than reported.**
(i) `K-1a`'s argument was *understated*: the SDK's `close()` waits 5 s
gracefully **before sending any signal**, so a 2.5 s shielded wait is
abandoned before the child has been signalled at all — recorded as
`K-1b`, which upgrades the third kill rung from "belt" to "the only
thing that signals the child on the timeout path". (ii) BLOCKER-2's
bound is *tighter* than stated: `cli/uv.lock` already locks
`claude-agent-sdk` **0.2.134** plus `anyio`/`mcp`/`sniffio` for the
`[sdk]` extra, so the dev-group edit adds **no `[[package]]` stanza and
changes no version** — `RS8` pins that as the bound.

**One fact the fold surfaced that no finding named:** the CLI lock
resolves **0.2.134**, while every source reading in this document was
done against the UI venv's **0.2.121**. Both satisfy the pin. §8 now
opens with that gap stated — and r4 closed it.

### r4 — delta gate: SOUND (0 BLOCKER / 0 MAJOR / 3 NOTE, folded)

All 13 r3 folds verified correct, "none cosmetically"; both strengthened
claims independently confirmed (`K-1b` on **both** versions — the first
`close()` window sends no signal; `RS8`'s lock bound parsed — 40 stanzas,
the extra's closure already locked); and `Sim-3`'s bundled-CLI hazard
verified **real on the 0.2.134 wheel** (`_bundled/` ships in it).
Criteria unchanged at **82**; mutations **63 → 64**.

| NOTE | Finding | Landed in |
|---|---|---|
| **A** | The `test_invocation.py` may-touch cell stated two mutually exclusive numstat bounds, and the first ("12 insertions, 0 deletions") is **unsatisfiable** — nine modified signature lines are nine deletions by construction | the clause is **struck**; the ≤21/≤9 bound and `SU4`'s structural AST bound (governing per §0.1) remain |
| **B** | §8 row 10 stale on 0.2.134 — `ResultMessage` gains `terminal_reason` (17 → 18, additive) | row 10 rewritten to the 0.2.134 list with the affected-reads check; the §8 banner **downgraded** from "most likely source of a stale fact" to the measured statement (11 of 12 rows unchanged, row 10 additive) |
| **C** | The absence fixture's definition site was unnamed, and the permitted import line is an unfenced channel | `Sim-1` names **`tests/test_invocation_sdk.py`** and shows the import, citing house precedent `test_attrib.py:48`'s `# noqa: F401 -- fixtures resolved by name`; **`Sim-1a`** (new) forbids any `autouse` fixture there; `SU6` gains legs (ii) and (iv); `M64` (new) |

**Why NOTE-C's hardening is not paranoia.** The import line is legal, so
`SU4`'s AST bound cannot flag it, and the module it pulls in is executed
at collection time in the same session as all 61 shipped tests. An
`autouse` fixture defined there would reach every one of them through a
diff this spec explicitly permits. `Sim-1a` closes the one channel the
BLOCKER-1 allowance opened, and `M64` is what shows the fence is real.

**`M64` is added rather than the NOTE being folded prose-only**, because
this document's own standing rule is that a finding arriving without a
mutation is one nobody can show was implemented — and legs (ii) and (iii)
of `SU6` were already covered by `M60`, leaving (iv) uncovered.
