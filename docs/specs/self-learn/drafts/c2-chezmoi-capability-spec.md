# Spec C2 — chezmoi: HARD dependency → DETECTED capability (user-scope compile)

Status: DRAFT rev 1 — for BLIND Opus spec gate (reviewer reads this spec +
the code only; no review notes).
Scope: make the ONE existing user-scope compile target capability-aware.
No new targets, no new scopes. One new probe, one branch inside the
already-split write/sync seam, gated messaging. No lock change; no change
to project- or skill-scope routing.

Pin the code at commit `0f5c679` (`git rev-parse HEAD` →
`0f5c679c207c6326763904c9b71383701bc8bdda`, "fix(cli): home_state repo-root
predicate …"). Every line anchor below is against that commit. Paths are
`plugins/self-learn/cli/src/self_learn/` unless a full path is given.

---

## 1. Problem statement — hard dep, plus a reproduced bug

### 1.1 The dependency today

`chezmoi` is a **hard runtime dependency** of the user-scope compile path,
and of nothing else. It is executed ONLY from `chezmoi.py`, always through
two wrappers:

- `_run(argv)` (chezmoi.py **97-101**): `subprocess.run`; wraps
  `FileNotFoundError` (binary absent) → `ChezmoiError` (chezmoi.py 100-101).
- `_check(proc)` (chezmoi.py **104-110**): nonzero rc → `ChezmoiError`.

The binary name is the hardcoded literal `"chezmoi"` — the default of every
`chezmoi: str = "chezmoi"` keyword param (chezmoi.py 124, 139, 148, 160,
186). No `shutil.which` probe, no env override; `cli.py` never overrides it,
so `chezmoi_bin` is `"chezmoi"` end to end.

The single reach into chezmoi for a user-scope route is:

```
verbs.route / verbs.route_direct
  → _resolve_target(scope="user", destination="claude-md")   verbs.py 575-584
      → preflight_user_scope(target, chezmoi=chezmoi_bin)     verbs.py 583  (PRE-ledger-commit)
  → _host_phase(...)                                          verbs.py 1693 / 1943
      → _apply_target(... scope_kind=="user" ...)             verbs.py 1296-1304
          → compile_user_scope(target, records, chezmoi=…)    chezmoi.py 180-216
```

`recompile` reaches the same compile via its own preflight guard
(verbs.py **3068-3103**, `preflight_user_scope` at **3076**,
`compile_user_scope` via `_host_phase` at **3083**).

Because both the preflight and every sync step raise `ChezmoiError` when the
binary is missing, a machine **without chezmoi** cannot route ANY user-scope
lesson: the route fails, and the record is diverted to `pending/` by the
catch sites (teach.py **710-724**, cli.py **1001**/**1131**). chezmoi is,
by contrast to git (a genuine hard dep), an **optional** dotfiles tool; the
codebase's prevailing pattern for optional tools is `shutil.which(...)`
(worker.py **43** import, **1054** `notify-send`, **1089**
`self-learn-notify`; ui `runner.py` **176** `self-learn`). C2 brings
user-scope compile onto that pattern.

### 1.2 The reproduced bug (verified in a /tmp chezmoi sandbox)

Even **with** chezmoi installed, the flow is wrong when the target file is
present but **not chezmoi-managed** (e.g. `~/.claude/CLAUDE.md` exists as a
plain file the user never `chezmoi add`ed):

- `preflight_user_scope` runs `chezmoi diff <target>` (chezmoi.py 168). On
  an unmanaged path this exits **nonzero** ("not managed") → `_check` →
  `ChezmoiError` **before** any edit; OR, on chezmoi versions where `diff`
  tolerates it, the compiler writes the file and then step 4
  `chezmoi re-add <target>` (chezmoi.py 207) exits nonzero **after** the
  file was already written — a confusing route-failure that leaves the
  record pending despite the file having changed.

The fix must PROBE managed-ness first and never call `re-add` on an
unmanaged (or absent-chezmoi) target.

### 1.3 Empirically verified probes (chezmoi v2.71.0, isolated
`--source`/`--destination`/`--config` sandbox; never touched real
`~/.claude` or the real source)

- **Capability (absent vs present):** `shutil.which(chezmoi) is not None`.
- **Managed vs unmanaged (present):** `chezmoi source-path <target>` →
  **rc 0 = managed** (stdout = the source path); **nonzero = unmanaged**
  (stderr "…: not managed"). The code already trusts this exact probe:
  `dotfiles_source_path` (chezmoi.py 139-145) calls `source-path`.
  `chezmoi managed <path>` is NOT a discriminator — it returned **rc 0 for
  an unmanaged path** in the sandbox; do not use it.
- **Broken-source is a SYNC-time failure, not a pre-probe state.**
  Sandbox result when the chezmoi source tree was wiped while the target
  stayed on disk: `source-path`, `diff`, and `re-add` **all** returned
  nonzero "not managed". So a *fully-gone* source reads as **unmanaged**
  (→ silent degraded write, §3 row 2). The "managed-but-broken-source"
  WARN case (§3 row 4) is therefore precisely: `source-path` **rc 0** and
  the drift/dirty preflight passes, but a later step-4/5 command
  (`re-add` / `git add` / `commit` / `push`) raises `ChezmoiError` — e.g.
  a partially-corrupt source, a `git push` to an unreachable remote, a
  permission error. It is detected at sync time by CATCHING `ChezmoiError`,
  after the managed file is already written.

---

## 2. The write/sync seam this pivots on

`compile_user_scope` (chezmoi.py **180-216**) already splits into a
chezmoi-free WRITE and a chezmoi-only SYNC:

- **WRITE** — step 3, `compile_managed_file(target, records, …)`
  (chezmoi.py 200-202; the real file write, compilers.py **261-288**).
  Uses no chezmoi.
- **SYNC** — step 4 `chezmoi re-add` (chezmoi.py 207) + step 5
  `chezmoi git -- add -A` / `commit -m` / `push` (chezmoi.py 211-214). The
  same-machine-plus-publish bolt-on.

The preflight (steps 1-2, `preflight_user_scope`, chezmoi.py 160-177,
called internally at 197) is the drift/dirty gate that must ABORT
(`ChezmoiAbort`) **before** the WRITE. **This split is the seam.** C2 makes
the SYNC (and the preflight guarding it) conditional on the detected
capability, and always performs the WRITE.

---

## 3. The capability model (USER-RULED — implement exactly this)

Three detection states, plus one sync-time degradation, for user-scope
compile:

| # | chezmoi state | `source-path <target>` | behavior | verbosity |
|---|---|---|---|---|
| 1 | **absent** (`which` fails) | — (not run) | WRITE only (`compile_managed_file`); SKIP preflight; SKIP sync | **silent** |
| 2 | **present, unmanaged** | nonzero | WRITE only; SKIP preflight; SKIP sync | **silent** |
| 3 | **present, managed** | rc 0 | preflight (drift/dirty `ChezmoiAbort` — **unchanged**) → WRITE → re-add → commit → push | silent on success |
| 4 | **present, managed, broken source** | rc 0, preflight passes, but a step-4/5 command raises `ChezmoiError` | WRITE already done → **abandon sync, do not re-raise** → **WARN** | **noisy (the one message)** |

Verbosity ruling: rows 1-2 are the routine degraded cases and are
**silent** (matching the `shutil.which("notify-send")` precedent — absence
is silent, not an error). Row 4 is the ONLY user-facing message. Row 3 on
success is silent as today.

Preserved exactly (row 3): when the target is managed and the source is
healthy, the current happy path is byte-for-byte unchanged — including
`ChezmoiAbort` on pre-existing drift or a dirty dotfiles repo, raised
BEFORE any edit (chezmoi.py 169-172, 176-177). **The capability check runs
BEFORE the preflight**, so an absent/unmanaged target (rows 1-2) never
reaches the drift/dirty gate.

---

## 4. Obligations

All in `chezmoi.py` except O-4/O-5 (verbs.py) and O-7 (tests).

### O-1 — capability probe (new function in chezmoi.py)

Add a probe that returns the detection state (rows 1-3; row 4 is decided at
sync time, O-3):

```python
import shutil            # new import (chezmoi.py currently imports only subprocess, dataclass, Path)

USER_SCOPE_ABSENT = "absent"
USER_SCOPE_UNMANAGED = "unmanaged"
USER_SCOPE_MANAGED = "managed"

def user_scope_capability(target: Path | str, *, chezmoi: str = "chezmoi") -> str:
    """Which of the three detection states applies to ``target`` (§3 rows 1-3)."""
    if shutil.which(chezmoi) is None:
        return USER_SCOPE_ABSENT
    proc = _run([chezmoi, "source-path", str(target)])   # rc 0 = managed, nonzero = unmanaged
    return USER_SCOPE_MANAGED if proc.returncode == 0 else USER_SCOPE_UNMANAGED
```

- Use `_run` (not `_check`): a nonzero `source-path` is the **unmanaged
  signal**, not an error — it must NOT raise. (`_run` still wraps a genuine
  `FileNotFoundError`, but `which` already proved the binary present on
  this branch, so that path is dead here.)
- Add `user_scope_capability` and the three `USER_SCOPE_*` constants to
  `__all__` (chezmoi.py 48-59).
- Export the constants so tests and verbs import the SAME literals this
  function returns (no hand-copied strings) — the established discipline for
  `CHEZMOI_DIRTY_MARKER` (chezmoi.py 74).

### O-2 — `preflight_user_scope` becomes capability-gated (chezmoi.py 160-177)

At the top of `preflight_user_scope`, before the `chezmoi diff` probe:

```python
if user_scope_capability(target, chezmoi=chezmoi) != USER_SCOPE_MANAGED:
    return   # absent/unmanaged: nothing to sync, so nothing to drift-check (§3 rows 1-2)
```

- For `USER_SCOPE_MANAGED`, the rest of the function (chezmoi.py 168-177)
  runs **unchanged**: `chezmoi diff` → `ChezmoiAbort` on drift; `chezmoi git
  -- status --porcelain` → `ChezmoiAbort` on a dirty repo.
- Exact effect on the standalone call sites:
  - verbs.py **583** (`_resolve_target`, PRE-ledger-commit): absent/unmanaged
    → returns cleanly → the route proceeds to the ledger commit and then to
    `_host_phase`, where O-3 writes the file. Today it raised `ChezmoiError`
    → pending. **This is the primary bug close.**
  - verbs.py **3076** (`recompile`): absent/unmanaged → no abort → falls
    through to `_host_phase` (O-3) which does the degraded write.

### O-3 — `compile_user_scope` branches on capability (chezmoi.py 180-216)

Restructure `compile_user_scope` to the §3 table. Pseudocode (preserve the
existing docstring intent, param list, and `max_entries`/`max_words`
threading):

```python
target = Path(target)
cap = user_scope_capability(target, chezmoi=chezmoi)

if cap != USER_SCOPE_MANAGED:
    # §3 rows 1-2: WRITE only, silent, no sync.
    section = compile_managed_file(target, records, max_entries=…, max_words=…)
    return UserScopeResult(section=section, committed=False, commit_message=None,
                           synced=False, sync_warning=None)

# §3 row 3/4: managed.
preflight_user_scope(target, chezmoi=chezmoi)        # ChezmoiAbort on drift/dirty — UNCHANGED
section = compile_managed_file(target, records, max_entries=…, max_words=…)   # step 3, WRITE
if not section.changed:
    return UserScopeResult(section=section, committed=False, commit_message=None,
                           synced=False, sync_warning=None)   # no-op, as today
message = commit_message or f"self-learn: update managed section in {target.name}"
try:
    _check(_run([chezmoi, "re-add", str(target)]))            # step 4
    _check(_run([chezmoi, "git", "--", "add", "-A"]))         # step 5
    _check(_run([chezmoi, "git", "--", "commit", "-m", message]))
    if push:
        _check(_run([chezmoi, "git", "--", "push"]))
except ChezmoiError as exc:                                   # §3 row 4: broken source
    warning = (
        f"self-learn: wrote {target} but chezmoi sync did not complete "
        f"({exc}) — your edit is on disk but may not be captured in the "
        f"dotfiles source, so a later `chezmoi apply` could overwrite it. "
        f"Fix the dotfiles source/remote, then `self-learn recompile`."
    )   # accurate across re-add/commit AND push failure (no false "CLOBBER"
        # claim for a push-only failure, where the commit did land locally)
    return UserScopeResult(section=section, committed=False, commit_message=message,
                           synced=False, sync_warning=warning)
return UserScopeResult(section=section, committed=True, commit_message=message,
                       synced=True, sync_warning=None)
```

- **Catch `ChezmoiError` ONLY** in the sync block, NOT `ChezmoiAbort`. A
  genuine drift/dirty `ChezmoiAbort` is raised by `preflight_user_scope`
  (outside the try) and must still propagate (row 3 preserved).
- The `except` block must **not** re-raise and must **not** roll back the
  file — the WRITE already happened; H-2 "loud warning, never a rollback".
- `compile_managed_file` on a MISSING target still raises `CompileError`
  (compilers.py 275-279) in every row — unchanged; the compiler owns the
  section, never the file's existence. (For user scope the target is
  `~/.claude/CLAUDE.md`, which exists in practice; a missing one is a real
  error, not a degraded state.)

### O-4 — `UserScopeResult` gains two fields (chezmoi.py 88-94)

Extend the frozen dataclass:

```python
@dataclass(frozen=True)
class UserScopeResult:
    section: SectionResult
    committed: bool                 # True ⇔ the dotfiles repo was committed (row 3 success only)
    commit_message: str | None
    synced: bool = False            # True ⇔ full re-add+commit(+push) ran (row 3 success)
    sync_warning: str | None = None # row 4 only: the single WARN string; None otherwise
```

- `committed` keeps its exact current meaning (dotfiles repo committed):
  **True only on row 3 success**. Rows 1, 2, 4 and the no-op compile all
  return `committed=False`. This preserves every existing reader of
  `committed` (recompile reports `changed=bool(committed)`, verbs.py 3100;
  the teach/route push renderer keys "(pushed)" off the commit, so a
  degraded/broken write correctly does NOT print "(pushed)").
- `synced` / `sync_warning` default so no other constructor changes.

### O-5 — surface the row-4 warning to the user (verbs.py `_host_phase`)

`_host_phase` (verbs.py 1414-1475) already owns the user-facing `warnings:
list[str]` the CLI prints (cli.py **886**, **1184** iterate
`result.warnings`). In the success path, after `_apply_target` returns
(verbs.py 1446-1453) and before returning at 1467, add:

```python
sync_warning = getattr(compile_result, "sync_warning", None)
if sync_warning:
    print(f"self-learn: {sync_warning}", file=sys.stderr)   # mirrors the H-2 warn at 1473
    warnings.append(sync_warning)
```

- This is the ONE message (§3 row 4). Rows 1-2 return `sync_warning=None` →
  nothing printed → **silent**, satisfying the verbosity ruling.
- It flows to both entry points that pass `warnings`: `route`/`route_direct`
  (verbs.py 1693/1943, `warnings=warnings` into `VerbResult`, 1701/1951) and
  `recompile` (verbs.py 3083, `warnings=result.warnings`). No new plumbing.
- Guard with `getattr(..., None)` because `_apply_target` returns different
  result types per destination (NewSkillApplyResult, SectionResult, etc.);
  only `UserScopeResult` carries `sync_warning`.

### O-6 — no binary-name / env changes

Out of scope to add an env override or rename the binary. `chezmoi_bin`
stays the threaded `"chezmoi"` literal. C2 changes DETECTION, not
configuration. (Named so the gate does not demand a `SELF_LEARN_CHEZMOI`
env var.)

---

## 5. Invariants to preserve (named, and why each holds)

- **`commit_lock` (no ledger/host mutation before `gitops.commit_lock`).**
  The user-scope compile writes to `~/.claude/CLAUDE.md`, which is neither
  the ledger repo nor any host repo of ours: for user scope
  `TargetSpec.host_repo is None` (verbs.py 584), so `_host_phase` takes
  `contextlib.nullcontext()` (verbs.py 1439-1443) — there is no host
  `commit_lock` here, and chezmoi commits its OWN dotfiles repo inside
  `compile_user_scope`. The **ledger** commit (the `resolved/` record) runs
  under `gitops.commit_lock(home)` in the LEDGER phase (`_routed_to`,
  verbs.py 365; `_commit_ledger`, called at verbs.py 1680) **before**
  `_host_phase` (verbs.py 1693). C2 adds **no** mutation before that lock:
  O-1/O-2 are read-only probes (`which`, `source-path`, `diff`, `git
  status`); the only new WRITE is `compile_managed_file` inside
  `_host_phase`, strictly AFTER the ledger commit — exactly where the file
  write already was. `test_lock_invariant.py` needs no change and must pass
  unmodified.
- **Two separate writes, not conflated.** (a) The ledger-side record write
  + commit (`resolved/<id>.md`, under `commit_lock(home)`, LEDGER phase) is
  untouched by C2. (b) The user-file write (`~/.claude/CLAUDE.md`, HOST
  phase) is the only thing C2 makes capability-aware. In rows 1/2/4 (a) still
  commits normally (the record routes); only (b)'s **sync** degrades. A
  degraded/broken user-file sync must NOT fail the route — the ledger is
  truth (H-2), and the file is written regardless.
- **Idempotency + existing catches hold for GENUINE errors.** A missing
  target (`CompileError`), a real `ChezmoiAbort` (drift/dirty on a managed
  target), and a `ChezmoiError` that is NOT a user-scope sync failure are
  all handled by their existing paths, unchanged by C2: a route-phase error
  → `pending` via the teach.py (710-724) / cli.py (1001, 1131) catches; a
  host-phase compile/sync error → the existing host-phase warning path, with
  the record left `resolved`. C2 changes neither routing; it only stops (i)
  absent/unmanaged from being treated as errors
  and (ii) a managed-but-broken **sync** from failing the route. Re-running
  a degraded route is idempotent: `compile_managed_file` rewrites only on
  `changed`, and a later route once chezmoi/source is healthy performs the
  sync.

---

## 6. Test obligations

Existing isolation pattern (follow it — `tests/test_chezmoi.py`): a
**PATH-shimmed fake `chezmoi`** bash script (`SHIM`, test_chezmoi.py 18-31)
installed first on `PATH` by the `shim` fixture (53-72); it appends each
invocation's `$*` to `$CHEZMOI_SHIM_LOG` and simulates outcomes via env
vars `CHEZMOI_SHIM_DIFF`, `CHEZMOI_SHIM_STATUS`, `CHEZMOI_SHIM_EXIT`. Tests
assert on the argv log and the target file. **No real chezmoi is required
in CI** — extend the same shim; do not add a real-binary dependency.

Two shim extensions are needed:

1. Handle `source-path`: add a `source-path)` case to the `SHIM` `case`
   block that prints a source path and honors a new env var, e.g.
   `CHEZMOI_SHIM_SOURCE_RC` (default 0 = managed; set nonzero = unmanaged).
   Keep `diff`/`git` cases as-is.
2. Absent-chezmoi = a `PATH` with no `chezmoi` on it (the existing
   `test_missing_binary` fixture pattern at test_chezmoi.py 151-156 already
   does this with an empty bin dir).

Required tests (all four §3 rows + regressions):

- **T-1 — absent → silent WRITE, no sync, no raise (§3 row 1).** Point
  `PATH` at a dir with no `chezmoi` (empty-bin pattern). Assert
  `compile_user_scope(target, [record])` returns without raising,
  `result.committed is False`, `result.synced is False`,
  `result.sync_warning is None`; the target file now contains the managed
  section (`BEGIN_MARKER`/`END_MARKER`, the record's rendered line — reuse
  the assertions at test_chezmoi.py 96-104); and **no** `re-add`/`git`
  invocation was logged. **This REPLACES `TestInvocationFailures::
  test_missing_binary_raises_chezmoi_error` (test_chezmoi.py 151-156)**,
  whose old expectation (absent ⇒ `ChezmoiError`) is exactly the behavior
  C2 removes — update it to the T-1 expectation.
- **T-2 — present + unmanaged → silent WRITE, no sync (§3 row 2).** Shim on
  `PATH`; set `CHEZMOI_SHIM_SOURCE_RC=1` (source-path nonzero). Assert: file
  written with the section; `committed is False`, `synced is False`,
  `sync_warning is None`; the logged calls contain `source-path <target>`
  and **no** `diff`, `re-add`, or `git` — i.e. the drift gate was skipped
  and never called `re-add` on an unmanaged target (the §1.2 bug lock).
- **T-3 — present + managed, healthy → full happy path (§3 row 3
  regression).** Default shim (source-path rc 0, clean diff/status). Assert
  the argv sequence still matches the pinned order (test_chezmoi.py 84-94),
  now prefixed by the `source-path` probe(s), and that `committed is True`,
  `synced is True`, `sync_warning is None`. Keep
  `test_target_edited_with_managed_section` (96-104),
  `test_custom_commit_message` (106-110), and
  `test_noop_compile_skips_readd_and_commit` (112-117) green (update their
  expected call logs to include the leading `source-path` probe).
- **T-4 — present + managed + broken source → WRITE then WARN, no raise
  (§3 row 4).** Shim: source-path rc 0, clean `diff`/`status` (preflight
  passes), but make **`re-add` (or `push`) exit nonzero** — e.g. extend the
  shim to honor `CHEZMOI_SHIM_READD_RC=1` in the `re-add)` case, or set
  `CHEZMOI_SHIM_EXIT` conditionally. Assert: `compile_user_scope` does NOT
  raise; the file IS written (section present); `committed is False`,
  `synced is False`; `result.sync_warning` is non-None and contains
  "clobber" and "recompile"; the argv log shows the write path reached
  `re-add` (proving the failure was at sync, not preflight).
- **T-5 — drift/dirty ABORT unchanged on a managed target (§3 row 3
  regression).** With source-path rc 0: set `CHEZMOI_SHIM_DIFF` non-empty →
  assert `ChezmoiAbort` raised, target untouched, calls stopped after
  `source-path` + `diff` (adapt `TestDriftAbort`, test_chezmoi.py 120-129);
  and set `CHEZMOI_SHIM_STATUS` non-empty → assert `ChezmoiAbort`, stopped
  after `source-path` + `diff` + `git … status` (adapt
  `TestDirtyRepoAbort`, 132-141). Genuine drift/dirty on a MANAGED target
  must still abort before any edit.
- **T-6 — capability probe unit (§3 rows 1-3).** Directly test
  `user_scope_capability`: absent `PATH` → `USER_SCOPE_ABSENT`; shim with
  `CHEZMOI_SHIM_SOURCE_RC=1` → `USER_SCOPE_UNMANAGED`; default shim →
  `USER_SCOPE_MANAGED`. Asserts the probe never raises on the unmanaged
  (nonzero source-path) branch.
- **T-7 (integration, optional but recommended) — route with absent chezmoi
  succeeds.** Through `verbs.route`/`route_direct` (as `test_route_hook.py`
  / `test_verbs.py` drive routes), with `PATH` lacking `chezmoi` and a
  user-scoped record: assert the verb returns success (record moves to
  `resolved/`, not `pending/`), the user CLAUDE.md is written, and
  `result.warnings` is empty (silent). This locks O-2's PRE-ledger-commit
  effect at verbs.py 583 and O-5's silence for row 1.

---

## 7. Explicitly OUT OF SCOPE

Stated so the gate does not demand them:

- **Spec A (claude-md parameterization / variant targets).** C2 makes the
  EXISTING single user-scope target capability-aware; it adds NO new
  targets. C2 **creates the seam** (the capability branch inside
  `compile_user_scope`) that Spec A will build variant targets on; it does
  not build them.
- **The `DEFAULT_MEMORY_DIR` / all-projects memory sweep (Spec D).**
- **Project-scope and skill-scope routing.** They never touch chezmoi
  (verbs.py 585-603, 650-671 route to real host repos under
  `gitops.commit_lock`); C2 does not alter them.
- **An env override or rename of the `chezmoi` binary (O-6).**
- **`commit_drift`'s user leg** (verbs.py 2179-2206) and the read-only
  `user_scope_dirty_status` / `dotfiles_source_path` (chezmoi.py 123-157).
  Those are already reached only via UI flows that presuppose a managed,
  present chezmoi; C2 does not re-gate them. (An OPTIONAL follow-up could
  make `commit_drift` capability-aware, but it is not required here.)
- **selfcheck drift check** (selfcheck.py 205-206) — already reads
  `DEFAULT_USER_CLAUDE_MD` directly, chezmoi-free; untouched.

### OPTIONAL obligation (clearly marked, NOT core)

O-OPT — surface the absent-vs-unmanaged distinction at low cost in a status
surface (e.g. `self-learn selftest`/`status`): report "chezmoi not installed
— user-scope lessons write locally, no dotfiles sync" when
`shutil.which("chezmoi") is None`. This is a diagnostic nicety, not part of
the routing behavior, and must remain silent on the hot route path. Only
build it if a status surface already enumerates optional-tool health;
otherwise defer.

---

## 8. Definition of Done (checkable against the code)

1. `chezmoi.py` defines `user_scope_capability` (O-1) returning one of
   `USER_SCOPE_ABSENT`/`USER_SCOPE_UNMANAGED`/`USER_SCOPE_MANAGED`, using
   `shutil.which` then `chezmoi source-path` via `_run` (never `_check`);
   the three constants and the function are in `__all__`.
2. `preflight_user_scope` returns early (no drift/dirty probe, no raise) for
   absent/unmanaged, and for managed is unchanged except for the single
   leading `source-path` capability probe (O-2) — the drift/dirty behavior
   itself is byte-identical, and the managed call log gains exactly one
   leading `source-path` entry (consistent with DoD-8).
3. `compile_user_scope` writes the file in ALL four rows, skips
   preflight+sync for rows 1-2, runs the unchanged preflight+sync for row 3,
   and CATCHES `ChezmoiError` from steps 4-5 (only) to WARN without
   re-raising or rolling back for row 4 (O-3). `ChezmoiAbort` still
   propagates.
4. `UserScopeResult` has `synced: bool` and `sync_warning: str | None` with
   safe defaults; `committed` is True only on row-3 success (O-4).
5. `_host_phase` prints and appends `sync_warning` to `warnings` when the
   user-scope compile carries one, and nothing otherwise — the ONLY new
   message (O-5). Rows 1-2 are silent.
6. No env override / binary rename; `chezmoi_bin` remains the `"chezmoi"`
   default (O-6).
7. No new mutation before any `commit_lock`; `TargetSpec.host_repo is None`
   for user scope is unchanged; `test_lock_invariant.py` passes unmodified
   (§5).
8. Tests T-1…T-6 exist and pass; the pre-existing `test_missing_binary…`
   expectation is updated to T-1 (absent ⇒ silent write, not
   `ChezmoiError`); `TestCleanPath`/`TestDriftAbort`/`TestDirtyRepoAbort`
   pass with their call logs updated for the leading `source-path` probe.
9. The §1.2 bug is locked: routing a user-scope record with the target
   present-but-unmanaged writes the file, skips sync, never calls `re-add`
   on the unmanaged target, and does not fail the route (T-2, and T-7 if
   built).
10. `pytest` under `plugins/self-learn/cli/` is green.
