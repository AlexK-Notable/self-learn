# self-learn — instructions for Claude Code

This file is committed and applies to anyone, human or agent, working in this
repository. Machine-specific rules (worker counts, exported environment, the live
ledger on a given host) belong in `CLAUDE.local.md`, which is git-ignored.

## What this repo is

- The PRODUCT: the `self-learn` CLI, the G-3 web UI, the plugin (skill, commands,
  hooks), the systemd units, and the spec corpus. Lessons live in the user's ledger
  (`$SELF_LEARN_HOME`, default `~/.self-learn`), never here.
- Never register this repo as a self-learn canon host (`self-learn host add …`):
  the compiler would write into the product. See README.md and CONTRIBUTING.md.
- `docs/specs/self-learn/` is the design authority; code follows it. A substantive
  change lands with a revision-log entry in that directory's README.
- This is a PUBLIC repository. Nothing committed may contain ledger content,
  tokens, or absolute home paths. `plugins/self-learn/cli/tests/test_personal_literals.py`
  scans the tracked tree for personal literals.

## Layout (README.md has the full map)

- `plugins/self-learn/cli/` — the Python CLI (uv project; package `src/self_learn/`).
- `plugins/self-learn/ui/` — the web UI (uv project; package `src/self_learn_ui/`).
- `plugins/self-learn/{skills,commands,hooks,scripts}/` — the plugin surfaces.
- `systemd/` — the host, UI, and legacy miner units. `install.sh` deploys everything
  as live symlinks and deliberately never enables a unit; that is the human's step.
- Scratch (audit reports, handoffs, one-off scripts) goes in an untracked `misc/`
  directory rather than a temp directory, and stays out of commits.

## Running things

- Sync once per package: `uv sync --project plugins/self-learn/cli` (and `…/ui`).
  Then run with `uv run --no-sync --project <pkg> …` so nothing re-syncs mid-run.
- CLI suite: `plugins/self-learn/cli/scripts/suite` is the sanctioned runner — one
  pytest-xdist run over the whole tree. `SUITE_WORKERS=N` caps the workers,
  `SUITE_OUT=<dir>` keeps the log, `SUITE_SERIAL=1` runs single-process for
  bisection. Read its own `suite rc=` line; an exit status read downstream of a
  pipe is the pipe's, not the runner's.
- One file: `uv run --no-sync --project plugins/self-learn/cli pytest tests/<file>.py -p no:cacheprovider -q`.
- UI suite: run FROM INSIDE the package — `cd plugins/self-learn/ui && uv run pytest -q`.
  (`uv run --project plugins/self-learn/ui pytest` from the repo root collects the
  CLI tree instead: `--project` sets the venv, not the collection root.) The browser
  tests need Playwright's Chromium and fail loudly without it;
  `SELF_LEARN_UI_NO_BROWSER=1` is the explicit opt-out. One known pre-existing
  failure, `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`,
  does not block; any new failure does.
- Type check per package: `uv run --no-sync --project <pkg> pyright src`. The error
  count must not grow; compare before and after on the same machine.
- `self-learn --selftest`, `self-learn doctor invocation`, and `self-learn doctor
  settings` are the read-only health views.
- Every ad-hoc run of the CLI or its tests points at a scratch ledger: set
  `SELF_LEARN_HOME` and `XDG_CACHE_HOME` to temporary directories. The default
  ledger is the user's real data.
- Do not run the suite, or the armor-pinned worker tests, with any
  `SELF_LEARN_OVERRIDE_*` variable exported: `test_worker.py` fails 10 tests under
  them (measured 2026-09-03). The override channel outranks `config.yaml` and exists
  for read verbs against a live ledger.

## Safety rules inherent to the product

- **An installed checkout's working tree is production.** `install.sh` symlinks
  the `~/bin` shims, the hooks, and the units into this tree, so the host service's
  nightly mine, the worker, and the UI execute whatever is sitting here, committed
  or not. Never leave a probe or a half-finished edit in an installed checkout
  across a session boundary. Do mutation testing in a git worktree, and prove the
  venv resolves there with `realpath(self_learn.__file__)` — a worktree venv can
  resolve back to the original tree.
- Agents never enable, start, stop, or restart systemd units, never run
  `daemon-reload`, and never signal the host process. Unit-file edits are inert
  until the human reloads; say so in the commit body.
- Revert probes by inverse edit and verify with `sha256sum` against
  `git show HEAD:<path>`. Never `git checkout --`, `git restore`, `git stash`, or
  `git reset --hard` to undo a probe; they have destroyed uncommitted work here.
- Never `git add -A` from the repo root; untracked scratch lands in the commit.

## Change discipline

- The review bar is mutation verification: for every test a change adds or relies
  on, break the behaviour and see the test fail; a test that stays green is a
  defect, not a pass. An absence assertion ("X not in page") needs a positive
  control asserting the region rendered, checked first.
- Armor (`plugins/self-learn/cli/tests/test_armor.py`): the fixtures `support.py`,
  `conftest.py`, and `backends.py` are byte-pinned and eight behaviour files are
  AST-pinned to `ANCHOR`. Adding top-level nodes is free; editing or deleting one
  needs a dated exemption entry (`Behaviour.edited` / `.missing`) naming a spec
  section. `--remeasure --anchor <sha>` is run only by the landing step on master's
  tip, never on a feature branch, and never rewrites a `MEASURED` literal for you.
- Lock invariant (`plugins/self-learn/cli/tests/test_lock_invariant.py`): every
  ledger-mutating surface must be reachable under the commit lock. A deliberate
  exception is one `NOT_REPO_TRUTH` entry with its disposition, never a walker
  edit. A nested closure inside a verb becomes its own unlocked node.
- Hermetic harnesses (`_REQUIRED_REAL_BINS` in the UI tests) carry every binary a
  script invokes; adding a dependency to a script means updating its harness.
- UI tests: `FakeRunner` carries verb invocations only; page reads
  (`ledger.list_items`, `ledger.status`, …) are monkeypatched directly. A bucket is
  identified by `(scope, name)`, never by name alone.
- A change that touches `worker.run`'s path runs the armor-pinned end-to-end files
  (`test_attrib.py`, `test_worker.py`, `test_repair.py`, `test_invocation*.py`)
  before merging; a review that ran only `test_worker.py` has missed real breakage.

## Git

- Direct commits to `master` are the norm; branches merge with `--no-ff` and a
  message that carries the unit's narrative and review result. Prefixes in use:
  `fix(<area>):`, `feat(<area>):`, `spec(<area>):`, `docs(<area>):`, `merge:`.
- A change is landable when it is committed on a clean tree, the CLI suite is green
  (plus the UI suite when UI files changed), pyright has not grown, and, for
  product code, its blind code gate returned CLEAN. Never `--force` or
  `--force-with-lease` on a published branch, never push a dirty tree, never push
  someone else's branch or a detached HEAD.
- Before pushing paths the remote has not seen, scan the outgoing diff's added
  lines for tokens, secrets, and absolute home paths, and test the count rather
  than printing it.
