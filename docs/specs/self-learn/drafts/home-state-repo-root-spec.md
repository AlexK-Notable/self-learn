# Spec — `home_state` strict repo-root classification (the read/write leak close)

Status: DRAFT rev 1 — for BLIND Opus spec gate (reviewer reads this spec +
the code only; no review notes).
Origin: Spec C1 §1.5a carved this out to "Spec C3" (a breaking change to
data-access classification deserved its own user ruling, not a
scope-growth footnote). The ruling is now made: **Option C — fold the
nested-non-root case into the existing `not-a-repo` state** (chosen over a
distinct `nested` state) by three independent reviewers + a
design-decision agent. This spec is that C3 resolution.
Scope: defect repair, one predicate correction + one message refinement +
subprocess bounding. No new state, no new public surface, no lock change.

Pin the code at commit `0a8b19d` (`git rev-parse HEAD`). NOTE: the task
brief named `74fcfc7`; the working tree's actual HEAD is `0a8b19d` and
every line anchor below is against that. All anchors are
`plugins/self-learn/cli/src/self_learn/` unless a full path is given.

---

## 1. Problem statement — the reproduced harm

`home_state` (ledger.py ~50-79) is the classifier every read and write
surface consults before touching the ledger. Today its "is this a git
repo?" leg (ledger.py **70-76**) runs the **coarse** predicate:

```python
proc = subprocess.run(
    ["git", "-C", str(home), "rev-parse", "--is-inside-work-tree"], ...)
if proc.returncode != 0 or proc.stdout.strip() != "true":
    return "not-a-repo"
```

`git rev-parse --is-inside-work-tree` answers **TRUE** for a home that is
*nested inside a PARENT repo's work tree but is not its own root*. So a
ledger home at e.g. `~/project/ledger`, where `~/project` is an unrelated
git repo and `ledger/` was never `git init`'d, classifies as a repo (then,
if it happens to hold the layout dirs, as `ok`). Every committing surface
then runs `git -C <home> …`, which **walks up to the parent repo** and
lands ledger writes — captures, telemetry flushes, miner commits — in that
unrelated repository. Telemetry flushes even on **read** commands, so a
mere `self-learn status` can dirty the user's project repo. This was
reproduced in a sandbox.

The `init` verb was already hardened against exactly this: init_home
(ledger.py 253-352) branches on `is_repo_root` (P-C1.20, ledger.py
281-285) precisely because "is-inside-work-tree answers TRUE for a path a
PARENT repo's work tree swallows." The read/write classifier
`home_state` was left on the coarse predicate — the same gap, on the
other door. This spec closes it.

`is_repo_root` (hosts.py **194-217**) is the exact predicate: it returns
True iff `git -C <path> rev-parse --show-toplevel` resolves to `<path>`
itself. It is already imported into ledger.py (ledger.py **26**:
`from .hosts import is_repo_root`).

### Why fold into `not-a-repo`, not a new `nested` state

`HOME_STATES = ("ok", "missing", "not-a-repo", "uninitialized")`
(ledger.py 33). The committing surfaces refuse on `not-a-repo` in one of
two shapes:

- **Literal-set refusers** (`missing`/`not-a-repo` only): teach.py
  `_home_gate` (teach.py **243**), ledger_ops.py `require_writable_home`
  (ledger_ops.py **306**), miner.py (miner.py **1611**), selfcheck.py
  (selfcheck.py **287**), and cli.py `_cmd_status_fast` returns
  `EXIT_NO_HOME` for any non-`ok`/non-`uninitialized` (cli.py 553).
- **Refuse-by-default** on any non-`ok` (except a warn-and-continue for
  `uninitialized`): cli.py `_home_gate` (cli.py **504-508**); the bash
  hook plugins/self-learn/hooks/self-learn-pending.sh **37** warns on any
  `home_state != "ok"`.

`not-a-repo` is therefore already in **every** committing gate's refusal
set. Folding the nested case into it is leak-proof by construction. A
distinct `nested` state would re-open the leak the moment any one of those
gates forgot to add it to its set — four independent refuse-sites, four
chances to re-leak. No consumer needs to change; that is the design
intent.

---

## 2. Obligations (the three changes)

### O-1 — `home_state` predicate correctness (ledger.py 70-76)

Replace the coarse subprocess block at ledger.py **70-76** with the strict
predicate:

```python
if not is_repo_root(home):
    return "not-a-repo"
```

- `home` at that point is already a `Path` (ledger.py 67) and already
  passed `home.is_dir()` (ledger.py 68). `is_repo_root` accepts `Path |
  str`, re-`expanduser`s (idempotent) and `resolve`s internally — no
  caller-side normalization needed.
- The `subprocess` import in ledger.py stays (still used by O-2's probe).
- Exact resulting behavior:
  - home is its **own** git repo root → `is_repo_root` True → fall
    through to the existing layout check (ledger.py 77) → `ok` or
    `uninitialized` exactly as before.
  - home is a directory that is **not** its own root — including nested
    inside a parent repo's work tree → `not-a-repo`. **This is the fix:**
    the coarse predicate returned "repo" here; the strict one refuses.
  - home is a directory in no work tree at all → `not-a-repo` (unchanged).

No new mutation is introduced; `home_state` only reads.

### O-2 — `home_state_message` precision for the nested sub-case (ledger.py 92-98)

On the `not-a-repo` branch of `home_state_message` (ledger.py 92-98),
before returning, **probe** the home for a parent work tree:

- Run `git -C <home> rev-parse --show-toplevel`, **bounded** (O-3), with
  `str(home)` (the parameter is typed `Path | str`, ledger.py 82).
- If the probe **succeeds** with a non-empty `--show-toplevel` **whose
  resolved value `!= home`** (this inequality is implied — `is_repo_root(home)`
  was False for us to be on this branch — but the branch MUST test it
  explicitly rather than assume it: a transient git-recovery window between
  the `home_state` classification and this probe, or a direct caller passing a
  mismatched `state`/`home` pair, could otherwise yield `toplevel == home` and
  emit a misleading "unrelated repo" line. Compare resolved paths, i.e.
  `Path(toplevel).resolve() != Path(home).expanduser().resolve()`), return a
  message that:
  1. **names the parent repo's toplevel** (the resolved `--show-toplevel`
     value);
  2. states that committing there would pollute an **unrelated** repo
     (cite doc 13 §2 — the ledger is its own git repo, every producer
     commits its own writes);
  3. points at **`self-learn init`** as the fix (nested init is
     supported: init_home step 5, ledger.py 270-272 / 340-348, `git
     init`s an empty nested dir in place and blesses nested init per doc
     13 §3).
- If the probe **fails** (nonzero rc, empty output, timeout, a nonexistent
  path — some tests pass `/nonexistent/wherever` — **or a resolved toplevel
  equal to `home`**), return the **current** true-"not a git repo" text
  unchanged (ledger.py 93-98).

**Substring invariant (both branches):** the returned string MUST contain
the literal substring `self-learn init`. The current text already does
(ledger.py 97); the new nested-branch text must too. This preserves
test_portability_docs.py::test_home_state_error_messages_name_init
(plugins/self-learn/cli/tests/test_portability_docs.py **120-128**), which
asserts `"self-learn init" in not_a_repo` — and note that test calls
`home_state_message("not-a-repo", "/nonexistent/wherever")`, whose probe
fails, so it exercises the unchanged-text branch.

The probe runs **only** on the already-failing `not-a-repo` path, so its
cost is nil on the healthy read path.

### O-3 — bound the now-hot coarse git calls

After O-1, `home_state` calls `is_repo_root` on **every** read and write,
making `is_repo_root` a hot-path predicate. A wedged local git (e.g. a
stranded `index.lock`, an NFS stall) must not be able to hang the read
path. gitops.py's `_git` (gitops.py 209-225) is the codebase's bounded
pattern: every git subprocess carries `timeout=GIT_LOCAL_TIMEOUT`
(`GIT_LOCAL_TIMEOUT = 30.0`, gitops.py 145). The three coarse callers here
predate/bypass that pattern and are unbounded.

Give each a bounded timeout consistent with `gitops._git`:

1. **`is_repo_root`** (hosts.py 209-213): add
   `timeout=gitops.GIT_LOCAL_TIMEOUT` to its `subprocess.run`, and wrap in
   `try/except subprocess.TimeoutExpired`. **On `TimeoutExpired` →
   `return False`.** (hosts.py already imports `subprocess` at hosts.py 43
   and `gitops` at hosts.py 50.)
2. **`_is_git_repo`** (hosts.py 178-184): same — bounded, and on
   `TimeoutExpired` → `return False`. (Used at hosts.py 295 for host-path
   validation.)
3. **`home_state_message`'s new probe** (O-2): bounded the same way; on
   `TimeoutExpired` → treat as **probe-failed** → the unchanged
   true-"not a git repo" text.

**Safe/refusing return, stated explicitly:** a timed-out probe MUST NOT
classify a home as a valid repo root. `False` is the safe answer for both
predicates — for `is_repo_root` it routes `home_state` to `not-a-repo`
(refuse, do not commit) rather than a false `ok`. Unlike `gitops._git`,
these predicates **catch** `TimeoutExpired` and return `False` rather than
raising: they are boolean classifiers on the read path (and `is_repo_root`
is imported by the ui server for its `needs_init` derivation, hosts.py
202-204), where a raised exception would be a regression, whereas a
bounded `False` degrades safely to "refuse and say so."

---

## 3. Invariants preserved (must be named and unbroken)

- **`commit_lock` invariant** (test_lock_invariant.py, structural: "no
  ledger/host mutation may precede its `commit_lock`"). This spec touches
  only **classification** (`home_state`), **messaging**
  (`home_state_message`), and **subprocess bounding** (two boolean
  predicates + one probe). It introduces **no new filesystem/git mutation
  path** and therefore needs **no** lock change. `home_state`,
  `home_state_message`, `is_repo_root`, and `_is_git_repo` are all
  read-only. Assert this in the DoD.
- **Idempotency / no regression of the healthy path:** a properly-init'd
  nested home is its **own** repo root → `is_repo_root` True →
  `home_state` still `ok`. A **zero-commit** repo root still counts as a
  root (`is_repo_root` already handles this — `--show-toplevel` resolves
  before the first commit, hosts.py 199-200) → still `ok`/`uninitialized`
  as today. The fix must not regress these.

---

## 4. Test obligations

New tests (place beside the existing `TestHomeState`,
plugins/self-learn/cli/tests/test_hosting_fixes.py 943-960, which already
has an `init_repo` helper from `tests/support.py`):

- **T-1 — nested un-rooted home → `not-a-repo`.** Create a parent dir,
  `git init` **the parent**, create an empty subdir `parent/ledger` that
  is **not** itself `git init`'d. Assert `home_state(parent/"ledger") ==
  "not-a-repo"`. (Under the pre-fix coarse predicate this returned a
  repo-classification; T-1 is the regression lock for O-1.)

- **T-2 — nested message names the parent.** For the same
  `parent/ledger`, assert `home_state_message("not-a-repo",
  parent/"ledger")` contains the parent repo's resolved toplevel path
  **and** the substring `self-learn init`. (O-2 nested branch.)

- **T-3 — plain (non-nested) not-a-repo message unchanged.** A plain
  empty dir in **no** work tree: assert the message still contains
  `"not a git repo"` and `self-learn init`. This locks the probe-failed
  branch and keeps
  test_hosting_fixes.py::test_not_a_repo_home_is_loud_and_non_zero
  (test_hosting_fixes.py 976-985, asserts `"not a git repo" in err`) and
  test_portability_docs.py::test_home_state_error_messages_name_init
  passing.

- **T-4 — timeout returns the refusing classification.** Force the git
  probe to exceed its bound (e.g. monkeypatch `subprocess.run` used by
  `is_repo_root` to raise `subprocess.TimeoutExpired`, or point at a git
  shim that sleeps past the timeout). Assert `is_repo_root(...) is False`
  and, consequently, that a home whose probe times out classifies as
  `not-a-repo` (never `ok`). Assert `_is_git_repo` returns `False` on the
  same forced timeout.

- **T-5 — regression: init'd nested home stays `ok`.** Create a parent
  repo, then a nested subdir that **is** `git init`'d as its own root and
  given the layout dirs (or `hosts.yaml`). Assert `home_state(...) ==
  "ok"`. (Names the Option-C guarantee: a properly-init'd nested home is
  its own root and is not swept into `not-a-repo`.) Also cover the
  zero-commit root staying a root.

- **T-6 — read-path-no-leak property.** With `SELF_LEARN_HOME` pointed at
  a nested un-rooted home inside a parent repo, run a **read** surface
  (`self-learn status --fast`, and/or `status`/`list`/`report` via
  `cli.main`). Assert (a) it exits `EXIT_NO_HOME` and says the home is not
  a usable repo on stderr, and (b) the **parent** repo's working tree /
  index is **unchanged** — no new commit, no staged/tracked ledger paths
  in the parent (`git -C <parent> status --porcelain` shows no
  ledger-authored change, `git -C <parent> rev-parse HEAD` unmoved). This
  is the direct regression lock for the reproduced harm: a read command
  must never write into the parent repo.

Existing tests that MUST remain green (do not edit):
test_hosting_fixes.py::TestHomeState::test_home_state_classifies (944-953),
test_initialized_empty_home_is_ok (955-960),
test_not_a_repo_home_is_loud_and_non_zero (976-985),
test_portability_docs.py::test_home_state_error_messages_name_init
(120-128). None of these use a nested layout, so O-1 does not perturb
them.

---

## 5. Explicitly out of scope

Stated so the gate does not demand them:

- **The init-lock error-mislabel `entered` flag** (a resource-exhaustion
  cosmetic) — dropped; not in this spec.
- **Any test-comment change in test_lock_invariant.py** — the prior
  finding there was refuted; no change.
- **OSError-guarding git-off-PATH.** Whether these subprocess calls should
  also catch `OSError` (git absent from `PATH`) is a separate,
  pre-existing, **systemic** question across the codebase — NOT this spec.
  **Bounding via `timeout=` IS in scope (O-3); OSError-guarding is NOT.**
- **Any new `HOME_STATES` value.** Option C is explicitly the no-new-state
  design; introducing `nested` is out of scope and contrary to the
  ruling.
- **Consumer/gate edits.** No `_home_gate`, `require_writable_home`,
  miner, selfcheck, hook, or `HOME_STATES` change — folding into the
  existing `not-a-repo` value is precisely what makes them unnecessary.

---

## 6. Definition of Done / acceptance criteria

A reviewer can check each against the code:

1. ledger.py 70-76's coarse `--is-inside-work-tree` block is gone,
   replaced by `if not is_repo_root(home): return "not-a-repo"`. No other
   branch of `home_state` changed; the layout check (ledger.py 77) and its
   `ok`/`uninitialized` outcomes are untouched.
2. `home_state_message`'s `not-a-repo` branch probes `--show-toplevel`
   (bounded) and, on a non-empty parent toplevel, returns a message
   naming that toplevel, citing doc 13 §2, and containing `self-learn
   init`; on probe failure/timeout it returns the current text unchanged.
   **Both** branches contain the substring `self-learn init`.
3. `is_repo_root` (hosts.py) and `_is_git_repo` (hosts.py) each pass
   `timeout=gitops.GIT_LOCAL_TIMEOUT` to `subprocess.run` and return
   `False` on `subprocess.TimeoutExpired`. The O-2 probe is likewise
   bounded and treats timeout as probe-failed. No predicate raises on
   timeout.
4. `HOME_STATES` is unchanged (still the four values); no consumer/gate
   file is modified.
5. No new mutation path; no `commit_lock` change; the four touched
   functions are read-only. test_lock_invariant.py passes unmodified.
6. New tests T-1…T-6 exist and pass; all existing home_state /
   portability tests listed in §4 pass unmodified.
7. The reproduced harm is locked out: T-6 proves a read command against a
   nested un-rooted home leaves the parent repo's index and HEAD
   untouched and refuses loudly.
8. The full test suite (`pytest` under plugins/self-learn/cli/) is green.
