# UI test-cache isolation — stop the suite writing into the real `~/.cache`

*2026-07-27. Status: **SHIPPED** — spec gate SOUND after folds, blind code
gate **CLEAN** (no blockers, 9 mutations incl. 4 unsuggested). Source:
`research/2026-07-27-routing-monoculture-and-pin-audit.md` §10.*

**Revision history**

- **r1** 2026-07-27 — first draft. Blind Opus spec gate: **NOT SOUND** —
  3 BLOCKER, 2 MAJOR, 1 MINOR. The gate independently verified every
  factual claim in r1 (all correct, and it re-measured the leak at exactly
  **176/run**); the findings were entirely about criteria that could not
  fail. Per the verdict-repricing rule each was a bounded text
  substitution, so all six folded here rather than opening a fresh round.
- **r2** 2026-07-27 — folds: criterion 2 gains a positive control and an
  mtime check (B1); the guard and criterion 3 now cover all five redirected
  variables independently (B2); pyright scope widened to include the files
  this unit actually changes (B3); the `redirected_xdg` consumer count
  corrected from "3" to **one**, with the tmp-subdirectory-collision trap
  named (M1); §5 gains the module-scoped `server` fixtures and the
  skip-composition requirement (M2); criterion 3's mutation step redirected
  so proving discrimination no longer adds to the real cache (MINOR).
- **r3** 2026-07-27 — built (Sonnet), blind code gate **CLEAN**. Post-gate
  corrections folded here: criterion 1's expected count (the r2 number was
  arithmetically unreachable post-change); **§5's "Chromium absent" premise
  was false** — see §7; F-4 recorded from the gate's MAJOR-1; the uv-cache
  note added to §4.

## 7. Correction — a premise this spec got wrong, and how

r1/r2 §5 asserted "Chromium absent on this host". **Chromium is installed**
(`~/.cache/ms-playwright/chromium-1194/1200/1228`). The 77 skips are an
**artifact of the measurement**: redirecting `XDG_CACHE_HOME` moves
Playwright's browser path, so the browser suite skips *because* of the
redirect the spec mandates.

It propagated because the baseline was measured through the redirect, the
artifact was written down as a property of the host, and the spec gate —
instructed by this spec to redirect — reproduced the same number
independently. Two agreeing measurements of the same instrument error.

**Consequence, confirmed live by the builder:** on a bare unredirected run
the browser suite executes, and the five module-scoped `server` fixtures
are set up before any function-scoped fixture applies. A detached miner
spawned during that bring-up wrote real state into
`~/.cache/self-learn/home-3f8991fa`. So the residual §5 called "not a live
leak today" **is live on this host** — bounded to ~1 directory per bare run
against 176 before the fix. Carried as **F-5**.

**Standing instruction for anyone running this suite: export
`XDG_CACHE_HOME` to a scratch dir at the shell level.** `monkeypatch`
cannot protect module-scoped bring-up; only the process environment can.

## 1. The defect

Running the UI test suite creates directories in the user's **real**
`~/.cache/self-learn`. Measured: **31,033 `home-*` directories, 1.1 GB,
7,254 of them dated 2026-07-26**, newest at 19:44. One directory
(`home-0f24de4d`) is live production state; the rest are test residue.
Leak rate measured independently twice: **exactly 176 per full UI suite
run**.

Two facts compose:

1. `cli/src/self_learn/worker.py:112-127` — `cache_dir()` computes
   `${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolve_home())[:8]>`
   and **`mkdir`s it at line 125, as a side effect of resolving the path**.
   A read-only query is enough to create one. The name varies with
   `SELF_LEARN_HOME`, so a unique ledger home per test mints a unique
   namespace.
2. `ui/tests/conftest.py` has **no autouse environment redirect**. Its
   `redirected_xdg` fixture is opt-in with **exactly one consumer**,
   `tests/test_cache_path.py` (6 references). `tests/test_launcher.py`
   mentions it only in a docstring, and says explicitly that it is
   *independent* of it — that suite drives the launcher as a subprocess
   with its own explicit `env` dict. Every other UI test runs with the
   developer's ambient `XDG_CACHE_HOME`, which the subprocess inherits via
   `ui/src/self_learn_ui/ledger.py:115-116`
   (`dict(env if env is not None else os.environ)`).

`cli/tests/conftest.py:13-35` already has the autouse fixture this package
never grew — which is why the **CLI suite leaks zero** (verified across
1133 passing tests) while the UI suite leaks 176.

## 2. Scope — and what is deliberately NOT in it

**In scope:** make every UI test resolve its cache, runtime dir, ledger
home, `~/.claude` dir, and transcripts dir to throwaway paths, so no test
can write to real user state; plus a guard that fails if any one of those
five protections is removed.

**Explicitly NOT in scope — do not add it to this unit:**

- **Making `env=` a required parameter** on `_invoke_json` and threading an
  explicit env through `routes.py` / `pane.py` and `EnvConfig`. Hardening
  with **no production symptom**: the systemd unit pins `SELF_LEARN_HOME`,
  and a server subprocess inheriting `os.environ` (PATH, etc.) is correct.
  It bites only under test, which §3.1 closes — `monkeypatch.setenv`
  mutates `os.environ`, and `ledger.py:115` copies `os.environ`. Follow-up
  **F-1**.
- **Making `cache_dir()` non-mutating** (a pure `cache_path()` for
  read-only surfaces). Real design change, cross-package blast radius.
  Follow-up **F-2**.
- **Deleting the existing 1.1 GB.** The user's action, not the builder's,
  and it must follow this fix or it refills at 176 per run. **F-3**.

The unit is one fixture plus one guard file. If it grows past that, stop
and say so rather than absorbing F-1.

## 3. The change

### 3.1 `ui/tests/conftest.py` — add an autouse redirect fixture

Mirror `cli/tests/conftest.py:13-35` in intent, adapted to this package.
Autouse, function-scoped, `monkeypatch` + `tmp_path`. It must set:

| var | why |
|---|---|
| `XDG_CACHE_HOME` | the leak itself |
| `XDG_RUNTIME_DIR` | the UI token dir must never be the real one |
| `SELF_LEARN_HOME` | the cache-namespace key; also stops tests touching the real ledger |
| `SELF_LEARN_CLAUDE_DIR` | tests must never see the real `~/.claude` |
| `SELF_LEARN_TRANSCRIPTS_DIR` | must never default to real `~/.claude/projects` |
| `SELF_LEARN_WORKER_AUTOKICK=0`, `SELF_LEARN_MINER_AUTOKICK=0` | no detached spawns from the suite |

Carry a comment naming this document and the measured cause, in the style
of the CLI fixture's own comments — a future reader deleting it should see
what it costs.

**Two constraints on the directory names it chooses:**

- **It must not break `redirected_xdg`.** That fixture stays and keeps
  working: an explicitly-requested fixture is instantiated after the
  autouse default, so its `setenv` wins. This is the CLI package's working
  precedent, and the gate confirmed it empirically. Verify, do not assume.
- **Its tmp subdirectory names must differ from `redirected_xdg`'s**
  (`cache`, `runtime`, `ledger-home`). Both fixtures receive the *same*
  `tmp_path`, so identical names would make criterion 4 tautological — it
  would pass whether or not the override actually happened.

### 3.2 A guard that reproduces the defect, per variable

Add a guard test file asserting the **mechanism**, not the fixture's own
`setenv` calls. Asserting `os.environ["XDG_CACHE_HOME"]` starts with tmp is
near-tautological and would pass against a fixture that redirects the wrong
variable.

§2 puts five variables in scope, so the guard must assert **one resolved
path per variable**, each obtained from the real production resolver and
each required to be under `tmp_path`:

| variable | resolver to call |
|---|---|
| `XDG_CACHE_HOME` | `self_learn.worker.cache_dir()` — `worker.py:112` |
| `XDG_RUNTIME_DIR` | `self_learn_ui.middleware.resolve_token_path()` — `middleware.py:77`. **Assert with the var set**: its unset-fallback is `cache_dir()`, which would mask a missing redirect. |
| `SELF_LEARN_HOME` | `self_learn.ledger.resolve_home()` — `cli/.../ledger.py:44` |
| `SELF_LEARN_CLAUDE_DIR` | `self_learn.selfcheck.claude_runtime_dir()` — `selfcheck.py:471` |
| `SELF_LEARN_TRANSCRIPTS_DIR` | `self_learn.miner.transcripts_root()` — `miner.py:182` |

All five verified to exist at those sites. A fixture that redirects only
`XDG_CACHE_HOME` must fail four of these five — that is the point.

**Verify the guard by reproducing the defect** (`lrn-fe16fceb`): see
criterion 3. A guard that passes in both states is theatre and must be
replaced, not explained.

## 4. Acceptance criteria

Ordered; each is a command with a stated expected result. **Record actual
output for each — a criterion whose result is only asserted in prose has
not been run.**

1. **The suite is still green.** `uv run --project . pytest` from
   `plugins/self-learn/ui`, with `XDG_CACHE_HOME` exported to a scratch dir
   (see §7) → **1010 passed, 77 skipped**, and exactly one failure: the
   pre-existing, unrelated
   `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
   (an `ln -sf`-in-docstring assertion). Any *other* failure is a
   regression caused by this unit.

   **1010 = the 1005 pre-change baseline + this unit's 5 guard tests.** Do
   not read 1010 as a regression against 1005; that number is only
   reachable with the guard absent or the fixture disabled — which is
   exactly what criterion 2a produces, and is a useful cross-check.

   Note: `uv` also honours `XDG_CACHE_HOME`, so the first scratch-redirected
   run re-materialises ~34 MB of package cache and is noticeably slower.
   That is uv, not a test side effect.

2. **The leak is closed. Three measurements, not one** — the naked
   before/after count prints "identical" in at least three states (fix
   works / an outer redirect is still exported / the directory does not
   exist), and is blind to a test that writes *into* the existing live
   `home-0f24de4d` namespace.

   a. **Positive control — prove the instrument sees the leak.** Autouse
      fixture disabled, `XDG_CACHE_HOME=<scratch>`, full UI suite →
      `find <scratch>/self-learn -maxdepth 1 -type d -name 'home-*' | wc -l`
      must be **176**. Not "nonzero" — 176.
   b. **The fix.** Same command, fixture enabled → must be **0**, and
      `<scratch>/self-learn` must not exist.
   c. **Production namespace untouched.** Note the wall-clock time before
      the run; afterwards
      `find ~/.cache/self-learn -mindepth 1 -newermt '<run start>' | head`
      must be **empty**. An mtime check, not a count — a count cannot see
      writes into an existing directory.

3. **The guard discriminates, per variable.** For each of the five
   redirects, remove that one variable from the fixture and confirm its
   corresponding §3.2 assertion FAILS while the others still pass. Five
   independent mutations, not one blanket disable. **Run every mutation
   with `XDG_CACHE_HOME=<scratch>` exported** — otherwise proving
   discrimination writes into the real cache this unit exists to protect.
   Revert each mutation by inverse edit, never `git checkout`.

4. **`redirected_xdg` still governs its one consumer.**
   `tests/test_cache_path.py` passes and its
   `startswith(redirected_xdg["cache_home"])` assertions still hold — i.e.
   they see `redirected_xdg`'s paths, not the autouse defaults. (Requires
   §3.1's distinct-directory-names constraint, or this is tautological.)
   `test_launcher.py` is subprocess-driven with its own explicit env and is
   unaffected; it is not evidence about this fixture either way.

5. **Pyright clean at a scope that can see this unit's files**:
   `PYRIGHT_PYTHON_FORCE_VERSION=latest pyright --pythonpath .venv/bin/python src tests/conftest.py tests/<new_guard_file>.py`
   → 0 errors. The `src`-only scope returns 0 on the *unmodified* tree and
   is identical for a correct fix, a broken fix, and no fix — worthless
   here. Baseline for the widened scope verified today: `src
   tests/conftest.py` → **0 errors, rc=0**, captured unpiped. The bare
   `pyright` invocation's ~98 errors are pre-existing across test modules
   and are NOT this baseline; its trailing version notice also reads like a
   tool that failed to run.

## 5. Risks the builder must check, not assume

- **Fixture ordering.** If the autouse fixture ran *after* `redirected_xdg`
  it would clobber it. Criterion 4 catches this.
- **Directory-name collision.** Both fixtures get the same `tmp_path`;
  identical subdirectory names make criterion 4 vacuous. See §3.1.
- **Function scope cannot protect module-scoped fixtures.** pytest
  instantiates module scope first, and `monkeypatch`/`tmp_path` are
  function-scoped, so a module-scoped fixture cannot request them. There
  are **five module-scoped `server` fixtures** that build the real app and
  run uvicorn in a thread: `test_js_dom.py:280, :343, :400, :460` and
  `test_js_dom_pane_persistence.py:80`. They are set up even when their
  tests skip, because `browser` depends on `server`. The gate confirmed
  this bring-up does not currently resolve `cache_dir()`, so it is not a
  live leak today — but it is the one structural reason this fix could
  silently fail on a machine where Chromium *is* installed.
- **Criterion 1's "77 skipped" is not full coverage, and not a property of
  this host.** All 77 skips are the browser suite (66 + 6 + 5 across
  `test_js_dom.py` and `test_js_dom_pane_persistence.py`). They skip
  *because* the mandated `XDG_CACHE_HOME` redirect moves Playwright's
  browser path — **Chromium is installed here**; see §7. Criterion 2 is
  therefore measured with the browser test bodies never executed. **Record
  the skip composition alongside the counts** so a future reader does not
  read 1010/77 as complete. (One positive datum from the code gate: the
  five module-scoped `server` fixtures *were* set up and contributed zero
  cache dirs, so bring-up itself does not resolve `cache_dir()` — the leak
  in §7 comes from the miner autokick, not the fixture.)
- **Tests that assert on absence.** Some test may assert a var is unset or
  a path shape a tmp redirect changes. Criterion 1 catches it; if one
  fails, fix the test only if the fixture is right — never weaken the
  fixture to make a test pass without saying so.
- **`test_sentinel_path_is_global`** (`cli/tests/test_hosting.py:763`)
  asserts `"home-" not in str(path)`. It is in the **CLI** package, out of
  this unit's reach. Noted only because an earlier investigation saw it
  fail under a harness whose own scratch path contained `home-`. Do not
  "fix" it here, and do not choose a scratch path containing that
  substring.
- **`_client_contexts`** is the existing autouse fixture. Two autouse
  fixtures coexist fine; do not merge them.

## 6. Out-of-scope follow-ups (record, do not build)

- **F-1** — `_invoke_json`'s `env=` required; explicit subprocess env
  through `EnvConfig` and the call sites that omit it (`pane.py:504`,
  `routes.py:238`, `:301`, `:409`, `:412`, `:444`, `:863`).
- **F-2** — non-mutating `cache_path()` for read-only surfaces.
- **F-3** — the user's cleanup of the existing stale dirs / 1.1 GB, after
  this ships. **The count is now 31,214, not 31,033**: the builder's first
  exploratory command was a bare unredirected run, which added ~181 —
  including `home-3f8991fa`, a real miner namespace that scanned 155 real
  transcript files. Disclosed by the builder unprompted; nothing deleted,
  since deletion is the user's call.
- **F-4** *(code gate MAJOR-1)* — `~/.claude/CLAUDE.md` is **hardcoded** at
  `ui/.../pane.py:288`, `cli/.../worker.py:565`, and
  `cli/.../verbs.py:160` (`DEFAULT_USER_CLAUDE_MD`, the default *write*
  target of `route()`), and consults `SELF_LEARN_CLAUDE_DIR` at none of
  them. Only a `HOME` redirect reaches those. So §2's "no test *can* write
  to real user state" is **overbroad as written** — not a regression, and
  criterion 2c confirms nothing was written, but the guard cannot see this
  gap because its row asserts a *different* resolver
  (`selfcheck.claude_runtime_dir()`). Either add `HOME` to the redirect set
  with a guard row on `pane`'s canon-target resolver, or narrow §2's claim.
- **F-5** *(§7)* — close the module-scoped residual. A session-scoped
  redirect would do it, but naively it also hides Chromium and silently
  skips 77 browser tests — trading a leak for invisible coverage loss.
  Pair it with `PLAYWRIGHT_BROWSERS_PATH` pointed at the real location.
