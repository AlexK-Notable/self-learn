# `~/.cache/self-learn` detritus — diagnosis

**Date:** 2026-07-26
**Measured:** 31,033 `home-<8hex>` dirs, 1.1 GB, 310,651 inodes.
**Verdict:** test pollution from the **UI** suite. Reproduced live. **Ongoing** — 7,254 dirs created today.

---

## 1. How the path is derived

`plugins/self-learn/cli/src/self_learn/worker.py:112-127`

```python
def cache_dir() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    digest = hashlib.sha256(str(resolve_home()).encode("utf-8")).hexdigest()[:8]
    new = base / "self-learn" / f"home-{digest}"
    new.mkdir(parents=True, exist_ok=True)          # <-- line 125, side effect
    _migrate_cache(base / "claude-skills" / "self-learn", new)
    return new
```

Two properties combine into the leak:

1. **The name varies with the ledger home.** `resolve_home()`
   (`ledger.py:44-47`) is `$SELF_LEARN_HOME or "~/.self-learn"`, expanded.
   The dir name is `sha256(str(home))[:8]`. A unique home string ⇒ a unique
   directory. Under pytest, `tmp_path` is unique **per test**, so a per-test
   ledger home mints a new namespace every single test.
2. **Resolving the path CREATES it** (line 125). `cache_dir()` is not a pure
   path computation — `mkdir(parents=True, exist_ok=True)` runs
   unconditionally. Any call at all, including a read-only `status` query,
   materialises a directory on disk. This is what turns "ask a question"
   into "leave a directory behind".

Verified: `sha256("/home/komi/.self-learn")[:8] == "0f24de4d"` — matches the one
live dir, `home-0f24de4d`.

### Why each junk dir holds exactly 2 entries

* **`.migrated-from-claude-skills`** — `_migrate_cache()`
  (`worker.py:139-196`). `~/.cache/claude-skills/self-learn` **exists on this
  host but is empty**. So the guard at line 158 passes (`old.is_dir()` is
  true), `sorted(old.iterdir())` yields nothing, `moved`/`failed` stay empty,
  and control falls through to line 189 which writes the marker. Every newly
  created namespace therefore gets a 78-byte marker recording a migration that
  moved nothing. Confirmed by reading the empty source dir and a sample marker.
* **`miner/`** — `plugins/self-learn/cli/src/self_learn/miner.py:137-139`:
  ```python
  def miner_dir() -> Path:
      d = worker.cache_dir() / "miner"
      d.mkdir(parents=True, exist_ok=True)
      return d
  ```

Full census of the 31,033 dirs by entry count: 31,028 have ≤3 entries; the
outliers are `home-0f24de4d` (13, live), `home-d528468b` (10), `home-d49121ac`
(9), and `home-76945814` / `home-52c8a9dc` / `home-3fe33585` (7 each). The
five outliers are stale *worker* residue from throwaway homes dated 17-20 Jul
(`worker.log` shows "window opened … run: idle"), not live state.

---

## 2. The actual bug — where the redirect is lost

**`plugins/self-learn/ui/src/self_learn_ui/ledger.py:115-116`**

```python
full_env = dict(env if env is not None else os.environ)
full_env["SELF_LEARN_HOME"] = str(home)
```

When the caller omits `env=`, this **inherits the real process environment and
pins only `SELF_LEARN_HOME`**. Every other isolation variable —
`XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`, `SELF_LEARN_TRANSCRIPTS_DIR`,
`SELF_LEARN_CLAUDE_DIR` — is whatever the developer's shell had.

Call sites that omit `env=`:

| file | lines |
|---|---|
| `ui/src/self_learn_ui/routes.py` | 238, 301, 409, 410, 411, 412, 444, 464, 863, 891, 892 |
| `ui/src/self_learn_ui/pane.py` | 504 |

### Why the tests don't catch it — the three-link chain

**Link 1 — the UI conftest has no autouse isolation.**
`plugins/self-learn/ui/tests/conftest.py` defines `redirected_xdg`, which does
redirect correctly — but it is **opt-in, not autouse**. Only 3 of 46 UI test
files request it. The single autouse fixture is `_client_contexts`, which
touches no environment variables. So `os.environ` inside a UI test **is the
developer's real environment**: no `XDG_CACHE_HOME`, no
`SELF_LEARN_TRANSCRIPTS_DIR`.

Contrast `plugins/self-learn/cli/tests/conftest.py:13-35`, which *is*
`autouse=True` and sets all six. The CLI suite is consequently clean (measured
below).

**Link 2 — the sandbox env is built correctly, then narrowed away.**
`ui/tests/support.py:69-111` (`make_env`) builds a correct env mapping with
`XDG_CACHE_HOME`, `XDG_RUNTIME_DIR` and `SELF_LEARN_HOME` all under `tmp_path`,
and deliberately never mutates `os.environ`. Tests then do:

```python
env = load_env(sb.env)                       # test_routes.py:47
app = create_app(env=env, token=TOKEN, ...)  # test_routes.py:48
```

`load_env` (`ui/src/self_learn_ui/env.py:98-158`) parses that mapping into an
`EnvConfig` that models **only `self_learn_home`** (plus UI port/model/budget
knobs). `XDG_CACHE_HOME` and `XDG_RUNTIME_DIR` are read from `sb.env` by
nobody and dropped on the floor. The sandbox env dict never reaches a
subprocess.

**Link 3 — routes call the CLI with no env.**
`create_app` serves routes that call `ledger.status(home)`,
`ledger.list_items(home)`, `ledger.report(home)`, `ledger.mine_status(home)` —
no `env=` — so `_invoke_json` takes the `os.environ` branch and spawns
`self-learn` with **real `XDG_CACHE_HOME` (unset ⇒ `~/.cache`) + per-test
`SELF_LEARN_HOME`**.

Result, exactly as observed:
`~/.cache/self-learn/home-<sha256(tmp_path/"ledger-home")[:8]>/`

This is the "path resolved before the fixture can patch the environment"
failure the brief anticipated, but the mechanism is not module-scope import —
it is an env mapping **narrowed through a typed config object**, losing every
field the object does not model. A per-test fixture cannot defend against
that, because the fixture was never the thing carrying the value.

### Secondary harm — the suite has been running the real miner

Every junk dir's `miner/miner.log` reads:

```
watchdog: last run >24h — spawned run (pid 1043079)
run 9e97a760: initialized forward-only (152 files seeded)
```

Because each namespace is brand new, `miner.last-run` is absent, so the
watchdog concludes the miner has never run and **spawns a real mining run**.
`cursors.json` in these dirs indexes the user's **real** transcripts
(`/home/komi/.claude/projects/...`) — 135 files in July 18 dirs, 152 today,
tracking the real transcript count. So the UI suite has been spawning genuine
transcript-miner processes against live Claude transcripts, ~176 per run.

Mitigating: every one of these journal entries has `"status":"initialized"`
with `duration_secs` 0.6-0.8 and `landed:0`. A forward-only initialisation
seeds cursors and stops; it does **not** invoke the model. So there is no API
cost and nothing was written to the ledger. The cost is disk, inodes, process
churn, and reads of the real transcripts directory.

---

## 3. Reproduction — with positive controls

Harness: `scratchpad/probe.sh`. It exports all six variables to a scratch tree,
then counts `home-*` dirs in **four** distinct sinks so a null result is
distinguishable from a blind check:

| sink | path | meaning |
|---|---|---|
| A | `$SCRATCH/xdg/self-learn/` | `XDG_CACHE_HOME` honoured — **stands in for the real `~/.cache`** |
| B | `$SCRATCH/fakehome/.cache/self-learn/` | fell back to `$HOME` |
| D | `$SCRATCH/pytmp/**/home-*` | pytest basetemp — correctly isolated (**per-run positive control**) |
| C | `/home/komi/.cache/self-learn/` | the real cache — must never move |

`HOME` and `XDG_CACHE_HOME` are pointed at *different* paths deliberately, so
"honoured XDG" and "fell back to HOME" are separable. Sink A absorbs the leak
that would otherwise land in the real `~/.cache` — which is why the real count
never moves in any run below. That is by design, not evidence of absence.

### Positive control (method validation) — PASSED

```
$ probe.sh $S/pc control ./.venv/bin/python -c "from self_learn import worker; print(worker.cache_dir())"
sink A  XDG_CACHE_HOME honoured : 1
sink C  REAL ~/.cache           : 31033 -> 31033  (delta 0)
cache_dir -> .../pc/xdg/self-learn/home-9946e58d
```

The counter demonstrably detects a newly created dir. Additionally every test
run below reports a non-zero sink D, so each individual run carries its own
proof that the check was not blind.

### Results

| target | sink A (leak) | sink D (control) | real cache |
|---|---|---|---|
| CLI `tests/test_miner.py` | 0 | 63 | 31033 → 31033 |
| UI suspects (6 files) | 0 | 14 | 31033 → 31033 |
| **UI `tests/test_routes.py`** | **101** | 11 | 31033 → 31033 |
| **UI full suite** (`-m 'not js'`, 1005 passed, 74s) | **176** | 26 | 31033 → 31033 |
| CLI full suite (1131 passed, 101s) | **0** | 621 | 31033 → 31033 |

**Live reproduction confirmed.** One run of `test_routes.py` produced 101
leaked namespaces. Attribution, by hashing every directory under the pytest
basetemp and matching against the leaked names:

```
leaked dirs: 101   attributed to pytest tmp homes: 100
  matched: .../p4/pytmp/test_content_landmark_is_progr0/ledger-home
  matched: .../p4/pytmp/test_bucket_clear_next_id_none0/ledger-home
  ...
```

(The 101st is the digest of the harness's own outer `SELF_LEARN_HOME`, from a
test that does not use `make_env`.) Shape of a leaked dir: `miner/` containing
`cursors.json journal.jsonl miner.last-run miner.lock miner.log …` — identical
to the 31,033 in the real cache.

The full CLI suite leaked **zero** while its control sink registered 621 — a
validated negative. The CLI conftest's autouse fixture is correct and
sufficient; the UI suite is the sole source.

### Independent attribution against the real cache

Hashing every surviving path under `/tmp/pytest-of-komi` against the 31,033
real dir names, before running anything:

```
real cache dirs: 31033
paths checked:   47478
MATCHES:         360
  home-b9d8d840  <-  /tmp/pytest-of-komi/pytest-361/test_clean_bucket_shows_no_cou0/ledger-home
  home-a6258500  <-  /tmp/pytest-of-komi/pytest-361/test_bucket_shows_its_own_unre0/ledger-home
  ...
```

360 dirs in the **real** cache are provably named after leftover pytest tmp
`ledger-home` paths. Mapping the 180 unique test names to source files:

```
 91 test_routes.py          12 test_degradation_walk.py    2 test_runner_real.py
 26 test_resolution_evidence.py  9 test_iterate_routes.py  2 test_app.py
 16 test_proposals.py        6 test_commit_drift.py        1 test_static_assets.py
                             3 test_unreadable_record.py
```

Exactly the files that define a local `make_client(sb)` calling
`create_app(env=load_env(sb.env))`. This is direct evidence against the real
1.1 GB, independent of my own test runs.

---

## 4. Ongoing or historical? — ONGOING

Newest dir: **2026-07-26 19:44 PDT** (`02:44Z` on 07-27), roughly 3 hours
before this investigation. Not residue.

Per-day counts:

```
2026-07-15     8      2026-07-21  1234
2026-07-17  4559      2026-07-22  1869
2026-07-18  6542      2026-07-24  1978
2026-07-19  6441      2026-07-25  1144
2026-07-20     4      2026-07-26  7254   <-- today
```

Repo's first commit is 2026-07-11; first leaked dir is 2026-07-15 19:34.
31,033 / 176 ≈ **176 full-UI-suite-equivalent runs** in 11 days.

The per-minute histogram corroborates the mechanism precisely: bursts of
~148 dirs in one minute with a 25-50 dir tail in the adjacent minute
(`02:06`=112, `02:10`=115, `02:42`=110, `02:47`=120, `03:43`=137, `03:50`=137).
The full UI suite takes **74 seconds** and emits **176** dirs — a run straddles
a minute boundary and splits into exactly that large-burst-plus-tail shape.

**Production is not affected.** The systemd unit pins
`Environment=SELF_LEARN_HOME=%h/.self-learn` (asserted by
`ui/tests/test_service_unit.py:106-107`), so the real UI and the nightly miner
resolve the single stable namespace `home-0f24de4d`. Its `miner.log` shows a
healthy daily cadence with real landings. `self-learn-miner.timer` next fires
2026-07-27 03:36 PDT; no self-learn process was running during this
investigation.

---

## 5. Proposed fix

Two layers. Ship both — they fix different things.

### (a) Stop the bleeding — add the missing autouse fixture (test-only, low risk)

`plugins/self-learn/ui/tests/conftest.py` — mirror the CLI suite's existing
guard, which the UI suite simply never grew:

```python
@pytest.fixture(autouse=True)
def _ui_test_isolation(monkeypatch, tmp_path):
    """Rule 7/8 for EVERY UI test, not just the three that opt into
    `redirected_xdg`: no test may resolve the real cache, runtime dir,
    ledger, ~/.claude, or the real transcript root."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache-default"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg-runtime-default"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-default"))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir-default"))
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(tmp_path / "_no_transcripts"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
```

This alone would have prevented all 31,033: it closes the `os.environ` fallback
for every present and future call site at once. `redirected_xdg` continues to
work — it just overrides these defaults.

### (b) Fix the underlying defect — don't silently inherit ambient env

(a) is a test-side guard; the production-shaped bug is that a UI process whose
env has been narrowed loses cache isolation entirely. Carry the invocation env
on the config object:

`ui/src/self_learn_ui/env.py` — add a field to `EnvConfig` and populate it in
`load_env` from the *same* mapping it parsed:

```python
@dataclass(frozen=True)
class EnvConfig:
    ...
    subprocess_env: dict[str, str] = field(default_factory=dict)

# at the end of load_env():
return EnvConfig(..., subprocess_env=dict(env))
```

Then have the 12 call sites in `routes.py` / `pane.py` pass
`env=cfg.subprocess_env`. `sb.env` from `make_env` then actually reaches the
subprocess, and `support.py`'s documented contract ("ready to pass as `env=` to
any `ledger.py` call") becomes true end-to-end instead of terminating at
`load_env`.

A cheaper variant, if touching 12 call sites is unwelcome: make the default
explicit rather than ambient — change `_invoke_json`'s signature so `env` is
**required**, and let the type checker enumerate the call sites. Silent
inheritance of the real environment is the defect; either change removes it.

### (c) Optional, design-level — flagging, not recommending

`cache_dir()` creating a directory as a side effect of resolving a path
(`worker.py:125`) is what makes this class of bug destructive rather than
harmless. A pure `cache_path()` for read-only surfaces, with `mkdir` reserved
for surfaces that actually write, would mean a mis-scoped read leaves nothing
behind. This is a real design change with blast radius across both packages —
the user's call, not mine.

Also cosmetic: once `~/.cache/claude-skills/self-learn` (empty) is removed,
`_migrate_cache` short-circuits at line 158 and stops writing a marker into
every new namespace. Not worth doing on its own.

### Not established

* I did not bisect *which individual test* within `test_routes.py` leaks — the
  file-level reproduction plus the sha256 attribution of 360 real dirs to named
  tests makes this unnecessary for the fix, but it means I cannot say "N of 172
  tests leak" beyond the observed 101 dirs.
* I did not verify the proposed fix by applying it — the brief forbids
  modifying the tree. The diff above is reasoned from the traced call chain,
  not executed. The (a) fixture is directly analogous to the CLI one that
  measurably yields a zero-leak suite, which is the strongest evidence
  available without applying it.
* Two pre-existing test failures surfaced and are **not** related to this bug:
  * `ui/tests/test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
    — fails identically with no redirects at all (asserts `"ln -sf" in header`).
  * `cli/tests/test_hosting.py::TestCacheAndSentinel::test_sentinel_path_is_global`
    — passes normally; fails only under my harness because line 768 asserts
    `"home-" not in str(path)` and my scratchpad path literally contains the
    substring `home-`. A harness artifact, not a defect.

---

## 6. Cleanup — the user's decision, NOT run

Nothing was deleted. `home-0f24de4d` is live production state (1.5 MB) and must
be kept; it is the namespace for the real ledger home `~/.self-learn`
(`sha256("/home/komi/.self-learn")[:8] == "0f24de4d"`, verified).

Reclaims ~1.1 GB and ~310,000 inodes. **Do the fix first** — otherwise the next
UI suite run starts refilling it at ~176 dirs a run.

```bash
# 1. derive the live namespace rather than trusting a hardcoded hash
LIVE=home-$(python3 -c 'import hashlib,os;print(hashlib.sha256(os.path.expanduser("~/.self-learn").encode()).hexdigest()[:8])')
echo "keeping $LIVE"          # expect: home-0f24de4d

# 2. DRY RUN — what would be removed (expect 31032)
find ~/.cache/self-learn -maxdepth 1 -type d -name 'home-*' ! -name "$LIVE" | wc -l

# 3. delete
find ~/.cache/self-learn -maxdepth 1 -type d -name 'home-*' ! -name "$LIVE" -exec rm -rf {} +
```

Note step 3 removes the five stale-worker outliers listed in §1
(`home-d528468b`, `home-d49121ac`, `home-76945814`, `home-52c8a9dc`,
`home-3fe33585`). They are throwaway-home worker residue from 17-20 Jul, dead
for six days. To keep them, add `-mtime +2` to the `find` in steps 2 and 3 —
that also protects anything recent by construction.
