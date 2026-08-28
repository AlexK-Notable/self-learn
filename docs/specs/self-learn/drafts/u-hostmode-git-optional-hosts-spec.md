# U-hostmode — git-optional canon hosts

**r2 — amended 2026-08-27 per blind spec gate r1 (NOT SOUND: 3 blockers,
6 majors, 12 docs, 3 nits) and the orchestrator's rulings on every design
fork the gate opened.** The census is carried forward unchanged except for
six bounded number corrections, each marked in place; the gate reproduced
every other figure exactly. The **mechanism** is rebuilt: plain is a real
mode with its own lock and its own `TargetSpec` field, the
`host_repo is None` overload is retired at the root, user scope becomes a
first-class plain host, `chezmoi_adopt` and `user_scope_dirty_status` are
deleted, `reconcile.py` and `report.py` and `commit_drift` and the UI come
into scope, and the compile record moves inside the resolution's own
ledger commit. The unit is now two phases (§5.0).

*(r1, 2026-08-27, measured the census and recommended per-host modes. Its
option map, its census, and its recommendation stand. Its mechanism did
not: it specified plain mode two incompatible ways, reused a discriminator
that already means "chezmoi user scope" in five shipped sites, and opened
a second ledger commit whose failure path collides with the shipped exit-6
contract.)*

Authored at `50fa815` in the throwaway worktree
`.claude/worktrees/u-hostmode-spec` (branch `u-hostmode-spec`, based on
`master` = `50fa815`).

**Mandate.** User ruling 2026-08-26 16:20, verbatim:

> *"while the git system works for us, other users might find it
> cumbersome. there needs to be a clean way set the behavior once the
> unit is built."*

Earlier the same day, the user's own framing of the alternative, verbatim:

> *"remind me what the git operations are needed for again? why do we need
> to make sure there's a repo? is it just for claude.md backups? if so,
> why not just handle that in some kind of shared ~/.self-learn directory
> (which we probably already make)"*

That second question is not a stray remark; it is a design option, and
§3.2 steelmans it with its measured cost before §3.3 recommends anything.

**Every number below is a command output.** The command is printed beside
its output, or the instrument is named. Where something could not be
measured it is said so, in §14. Code is cited by SYMBOL first, line
second — line numbers are at `50fa815` and will move.

---

## 0. Reading order and precedence

1. `03-decisions.md` rows **S-6** (compilers own marker-bounded sections),
   **S-10** (policy that changes what the CLI may auto-commit lives in a
   committed `config.yaml`, never an env var — the precedent this unit's
   default-mode knob copies), **S-12** (append-only substance; git is
   history/blame), **S-17** (D1–D3 hosting/product separation; **D3:
   pushes are MANUAL**). Where this spec and a row disagree, **the row
   wins**.
2. `13-hosting-and-separation.md` **§3** (the registry and `--init`),
   **§4** (routing across repos — the text this unit amends), **§5** and
   **§8 H-5** (producers commit their own writes; no watcher on the
   ledger, ever; `reconcile` is the backstop and **no mutation may
   precede its `commit_lock`**), **§8 H-2** (the ledger is truth, canon is
   compiled output, recompile is always safe), **§8 H-3** (compile targets
   come from hosts.yaml only).
3. `09-surface-spec.md` **§11 Y-17** — the git-init-on-register decision,
   the sentence this unit revises (§2.4), and the **consent invariant**
   the UI half of this unit rewrites (§4.9).
4. `02-schema.md` §4 (managed sections) — unchanged by this unit.
5. `misc/verb-coverage-2026-08-26.md` (local-only) — the assessment that
   queued this unit; its "git-optional host ❌ / `U-hostmode` QUEUED" row
   and its measured user-scope finding. **The gate could not read it
   (out of bounds); the finding it is cited for was re-measured
   independently and confirmed (§2.6), the queueing claim was not.**
6. The code, in the order §2 measures it.

**Precedence inside this spec.** §5's acceptance criteria are the spec.
Prose is rationale. Where prose and a criterion conflict, the criterion
wins.

---

## 1. Objective, and the non-objectives

**Objective.** Make a canon host's *version-control posture* a property of
the host, set once at registration, with two values: **`git`** (today's
behaviour, byte-for-byte) and **`plain`** (no repo required, nothing
committed, nothing pushed). Give `plain` an integrity instrument that is
at least as strong as the one `git` provides for the region self-learn
actually owns, and put that instrument in the ledger — which is where the
user asked for it. **And retire, at the root, the shipped overload that
made "no host repo" mean "chezmoi user scope"** — because the moment a
second thing has no host repo, every site that reads that sentinel is
wrong (§2.5a).

**Non-objectives, each a thing a builder might reach for.**

1. **New verbs.** `host add` gains one flag; `recompile` gains one flag
   (`--adopt`, §4.5). Nothing else. The verb-coverage gaps
   (`host --retire`, `route --dry-run`, `show <id>`, bucket pruning, bulk
   apply) belong to **`U-verbs`**, queued separately — fenced out by name
   in §8.
2. **Retiring git mode.** `git` stays the default and stays
   byte-identical. This unit adds an option; it does not migrate anybody.
3. **Reviving chezmoi.** chezmoi was retired 2026-07-24. Phase 2 DELETES
   the two symbols the ruling names and collapses the third (§4.8); it
   does not repair or extend anything chezmoi-shaped.
4. **A general-purpose snapshot/undo system.** §3.4 R-d names the shape
   this refuses and the trigger that would revisit it.
5. **Changing the LEDGER's own git usage.** 54 of the 94 git call sites
   are ledger-side (§2.2). All 54 keep their behaviour. `reconcile.py`
   is edited (§4.6) but its git usage is not.
6. **Touching H-5.** Producers still commit their own ledger writes. A
   plain host changes what happens in the HOST, never in the ledger —
   and §4.6 is the work that keeps H-5's *corollary* true for the new
   ledger artifact rather than merely asserting it.

---

## 2. Census, measured at `50fa815`

*(The blind gate re-ran every figure in this section. All reproduced
except six, corrected in place below and marked **CORRECTED-r2**.)*

### 2.0 Instruments, named once

- **`git-call census`** — `ast.parse` over every `*.py` in
  `plugins/self-learn/cli/src/self_learn/`, every `ast.Call` whose func is
  `gitops.<name>` for `<name>` in the git-touching set
  {`commit_lock, stage, commit, paths_dirty, dirty_paths, check_ignore,
  push_if_remote, push_with_retry, push_pending, unpushed_commits, _git,
  _git_ok, _git_nolock, staged_diff, known_paths, has_remote, toplevel`},
  classified by the unparsed text of its FIRST positional argument
  (`home`/`resolved`/`target` → LEDGER; anything containing `host`, plus
  the two bare-`repo`/`root` host locals → HOST). Raw
  `subprocess.run(["git", …])` calls are counted separately because they
  bypass `gitops` entirely.
- **`managed-region census`** — for every `*.md` under the nine registered
  hosts and `~/.claude`, resolved and de-duplicated by `Path.resolve()`
  (three of the nine hosts nest, so a naive walk double-counts), the byte
  length of the substring from `compilers.BEGIN_MARKER` to
  `compilers.END_MARKER` inclusive, and the count of `*(lrn-` entry
  markers inside it.
- **`reference-target census`** — the same walk, files containing at least
  one `^## \d{4}-\d{2}-\d{2} — lrn-[0-9a-f]{8}$` block (the shape
  `compilers.compile_reference` writes).
- **Test counts** — `pytest --collect-only -q`, tail line, run from
  `plugins/self-learn/cli` and `plugins/self-learn/ui`, under
  `env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT
  uv run --no-sync`.

### 2.1 The nine registered hosts, measured

```
$ cat ~/.self-learn/hosts.yaml
skills_root: ~/repos/claude-skills
projects:
- path: ~/repos/claude-skills
- path: ~/repos/keyboards/zmk-config-offsetkey
- path: ~/repos/keyboards
- path: ~/.config
- path: ~/repos/nsys-marketplace
- path: ~/repos/3d-printing/k1c-manta-m5p
- path: ~/repos/nsys-marketplace-local
- path: ~/repos/ignomi
- path: ~/repos/3d-printing
```

`git -C <p> rev-parse --show-toplevel` / `git -C <p> remote` /
`git -C <p> rev-list --count HEAD` /
`git -C <p> log --oneline --grep='^self-learn: ' | wc -l` /
`git -C <p> status --porcelain | wc -l`:

| host | root | remotes | commits | of which `self-learn:` | dirty entries now |
|---|---|---|---|---|---|
| `repos/claude-skills` | yes | origin | 504 | 76 | 0 |
| `repos/keyboards/zmk-config-offsetkey` | yes | origin, upstream | 287 | 1 | 81 |
| `repos/keyboards` | yes | **none** | **4** | 2 | 10 |
| `.config` | yes | **none** | **24** | 8 | 0 |
| `repos/nsys-marketplace` | yes | origin | 341 | 1 | 2 |
| `repos/3d-printing/k1c-manta-m5p` | yes | origin | 84 | 5 | 0 |
| `repos/nsys-marketplace-local` | yes | upstream | 360 | 1 | 0 |
| `repos/ignomi` | yes | origin | 33 | 1 | 14 |
| `repos/3d-printing` | yes | **none** | **4** | 3 | 0 |

**Three of nine have no remote at all, so the push half of the git
machinery is already inert for 33% of registered hosts.** *(CORRECTED-r2,
gate D-1: r1 said four/44%. The table always bolded **none** on exactly
three rows; the prose contradicted it. `gitops.has_remote` is "True iff
the repo has any configured remote" — `upstream`-only counts, so
`nsys-marketplace-local` has one.)*

**Three of nine are repos ONLY because self-learn demands it.** This is
not inference; each says so in its own history or its own `.gitignore`:

```
$ git -C ~/repos/keyboards log --oneline --format='%h %ad %s' --date=short | tail -1
2085fe3 2026-07-18 init: repo root for keyboards umbrella project (self-learn registration target)

$ git -C ~/repos/3d-printing log --oneline --format='%h %ad %s' --date=short | tail -1
d4f7c17 2026-08-25 self-learn: init for host registration

$ git -C ~/.config log --oneline --format='%h %ad %s' --date=short | tail -1
fc5b7dc 2026-07-23 self-learn: init for host registration

$ head -6 ~/.config/.gitignore
# ~/.config is a self-learn CANON HOST — not a dotfiles repo.
#
# This git repo exists for exactly one reason: `self-learn` requires each
# registered project host to be a git repo ROOT so it can commit compiled
# lessons. See ~/.self-learn/hosts.yaml (`projects:` includes ~/.config)
# and hosts.py:195 INIT_COMMIT_SUBJECT, which is the subject of commit fc5b7dc.

$ cat ~/repos/3d-printing/.gitignore
# self-learn host: only the compiled canon surfaces are tracked
*
!.gitignore
!CLAUDE.md
!references/
!references/**
```

`repos/3d-printing` and `.config` each carry a hand-written deny-by-default
`.gitignore` whose only job is to stop the requirement from swallowing the
rest of the directory. **That is the cumbersomeness, in the repository's
own words.** It is 3 `git init`s, 2 hand-authored whitelist ignore files,
and 2 explanatory comment blocks, all to satisfy a check.

### 2.2 The git-operation census — 94 calls, 38 of them host-side

`git-call census` (§2.0):

```
TOTAL gitops git-touching calls in cli src: 94
  HOST-side: 38   LEDGER-side: 54   unclassified: 2
HOST-side by function: {paths_dirty: 7, commit_lock: 6, commit: 7,
                        stage: 5, push_if_remote: 8, _git: 2,
                        dirty_paths: 1, check_ignore: 1, unpushed_commits: 1}
LEDGER-side by file: {verbs: 11, worker: 7, hosts: 6, ledger: 5,
                      reconcile: 5, import_common: 4, miner: 4, teach: 4,
                      telemetry: 4, import_backlog: 1, import_memory: 1,
                      report: 1, selfcheck: 1}
```

- **All 38 host-side calls live in `verbs.py`.** No other module touches a
  host repo through `gitops`.
- **They are held by 11 functions** (AST owner-mapping):
  `_abort_if_dirty`, `_resolve_local_target`, `_remove_hook_script`,
  `_host_phase`, `route`, `route_direct`, **`commit_drift`**, `graduate`,
  `supersede`, `push_pending`, `recompile`. §8 IN now lists all eleven
  *(CORRECTED-r2, gate M-2: r1's IN list named seven)*.
- The 2 unclassified are `teach.py:268` and `import_memory.py:123`, both
  `gitops.toplevel(Path.cwd())` — a *read* that resolves the caller's cwd
  to a project path. Neither reads or writes a registered host. **They are
  the one place where a plain host is still discovered by git**, and §4.10
  says what happens to them.
- Four more host-side git calls bypass `gitops` and go straight to
  `subprocess.run(["git", …])`, all in `hosts.py`:
  `_is_git_repo` (`hosts.py:181`, `rev-parse --is-inside-work-tree`),
  `is_repo_root` (`:215`, `rev-parse --show-toplevel`),
  `_init_for_registration` (`:264`, `git init`; `:269`,
  `commit --allow-empty`).

**Host-side total: 42.** Ledger-side total: 54.

**Two sites the dispatch brief asked to be classified are LEDGER-side, not
host-side:** `report.py:140` (`_resolution_dates(home)`) and
`reconcile.py:112` (`_porcelain(home)`). Neither changes behaviour here.
*(Both files are nonetheless IN scope in r2 for other reasons — §4.6 and
§4.7 — which is why r1's blanket "OUT-10" is withdrawn.)*

### 2.3 What each host-side operation protects

Grouped by the thing it is there to guarantee. "Verb" names the callers.

| # | Operation | Symbol / site | Verbs | What it protects | Survives in plain mode? |
|---|---|---|---|---|---|
| **H-a** | `git rev-parse --is-inside-work-tree` | `hosts._is_git_repo` (`hosts.py:178`), via `hosts.host_path_problem` (`:283`) | `host add`, and **every canon-writing gate** through `verbs._gate_host` (`verbs.py:776`) | *Committability.* Registration and each route re-check that the host can hold a commit. Incidentally, it is also the only thing standing between a typo'd hosts.yaml **skills-root** entry and canon written outside any repo (§2.9) | **REPLACED** by the `.self-learn-host` marker (§4.4) |
| **H-b** | `git rev-parse --show-toplevel` | `hosts.is_repo_root` (`:198`) | `host add --init`; the UI's `_needs_init` (`ui routes.py:2419`) | The Y-17 predicate: is this exact path a repo ROOT (not merely inside one) | **KEPT** — still the `--init` predicate, now behind the UI's mode choice (§4.9) |
| **H-c** | `git init` + `commit --allow-empty` | `hosts._init_for_registration` (`:228`) | `host add --init` | The disclosed opt-IN to committability | **KEPT, unchanged.** `--init` is a git-mode convenience and stays exactly that |
| **H-d** | `git status --porcelain -- <target>` | `gitops.paths_dirty` (`gitops.py:544`) via `verbs._abort_if_dirty` (`verbs.py:458`) — 7 host-side sites | `route`, `route_direct`, `recompile`, **`commit_drift`** | *Attribution.* Refuse to regenerate a target that carries the human's uncommitted work, because the pathspec commit would file their edit under self-learn's pinned subject | **REPLACED by a narrower and stricter instrument** (§4.5) |
| **H-e** | `git check-ignore` | `gitops.check_ignore` (`gitops.py:559`) at `verbs.py:1068` | `route --dest claude-md:local` | *Privacy* (A2 §6 / P-A3): `CLAUDE.local.md` must be gitignored or the route publishes a personal lesson to the team | **N/A by construction** — a plain host tracks nothing, so nothing is published. §4.11 states the plain-mode ruling and its residual |
| **H-f** | `flock` on `<git-common-dir>/self-learn.commit.lock` | `gitops.commit_lock` / `commit_lock_path` (`gitops.py:369`) — 6 host-side sites | route / recompile / hook removal / commit-drift host phases | *Serialization* of self-learn's own writers against each other, and against `push_with_retry`'s `pull --rebase --autostash` | **REPLACED by a REAL plain-host lock** in the global cache dir (§4.3) — `commit_lock_path` raises `GitOpsError("<repo> is not a git repository")` for a non-repo, so plain hosts need a different lock HOME, not no lock |
| **H-g** | `git add` + `git commit -- <pathspec>` | `gitops.stage` / `gitops.commit` — 12 host-side sites | route / route_direct / recompile / graduate / supersede / hook removal / commit_drift | *History and blame* for the compiled canon; the record→commit link (S-6: the record id in the commit MESSAGE) | **SKIPPED.** Replaced ledger-side by the compile record (§4.5) |
| **H-h** | `git push` (+ pinned rebase retry) | `gitops.push_if_remote` (`gitops.py:668`) — 8 host-side sites | route / route_direct / graduate / supersede / recompile / `push` | *Off-machine backup* and multi-machine sync of compiled canon | **SKIPPED.** Already inert for 3 of 9 hosts (§2.1) |
| **H-i** | `git show --format= <sha>` | `gitops._git` at `verbs.py:3279` | `route_direct` only | Rendering the host diff back to the operator | **SKIPPED** — no sha to show; §4.12 says what renders instead |
| **H-j** | `git rm --ignore-unmatch` | `gitops._git` at `verbs.py:1839` | hook retirement (`_remove_hook_script`) | Removing a retired guard script from tracking | **DEGRADED to `Path.unlink`** — the function already has that branch for untracked scripts (`verbs.py:1842-1846`) |
| **H-k** | `git rev-list @{u}..` count | `gitops.unpushed_commits` (`gitops.py:679`) at `verbs.py:4599` | bare `self-learn push` | Deciding whether a host has anything to publish | **SKIPPED** — a plain host is never a push candidate |

**The sentinel is not in this table, deliberately.** `sentinel.hold` /
`heartbeat` / `release` write
`${XDG_CACHE_HOME:-~/.cache}/self-learn/autosync-pause` — a global file,
never inside a host, never inside a repo (`sentinel.py:52`; and
`test_lock_invariant.NOT_REPO_TRUTH` exempts all four entries on exactly
that ground). It pauses *a host's own autosync script* during a canon
apply. **It is orthogonal to whether the host is a git repo** and this
unit does not change it. §10 item 1 states the one thing that IS worth
saying about it.

### 2.4 What "dirty" means today, and the decision that made it so

**The rule, as decided.** `09-surface-spec.md` §11 Y-17, verbatim:

> *"The committability invariant stands — canon writes are commits;
> audit, rollback, and recompile all diff against git (13 §4) — and the
> flow absorbs the gap instead of refusing at the human."*

**The refusal message, as shipped** (`verbs.py:271`, `:458-465`):

```python
GITOPS_DIRTY_MARKER = "has unrelated uncommitted changes"

def _abort_if_dirty(repo: Path, target: Path) -> None:
    """(c) dirty-compile-target abort — against the HOST repo (doc 13 §4:
    the target lives in a host now, so the dirty check must too)."""
    if gitops.paths_dirty(repo, target):
        raise DirtyTargetError(
            f"compile target {target} {GITOPS_DIRTY_MARKER} — "
            "commit/stash first, then re-run"
        )
```

**Measured facts about that gate, each of which matters:**

1. **It is per-FILE, not per-region.** `gitops.paths_dirty` runs
   `git status --porcelain -- <target>` (`gitops.py:544-548`). Any
   uncommitted byte anywhere in `CLAUDE.md` refuses the route — including
   a hand edit far OUTSIDE the managed markers, which
   `compilers.compile_managed_text` provably preserves ("text outside the
   markers is preserved byte-exact", `compilers.py:9`).
2. **It is per-file, not per-repo.** A repo can be filthy and still
   accept a route: `zmk-config-offsetkey` has 81 dirty entries and
   `ignomi` has 14 right now, and neither would refuse unless the target
   itself is among them.
3. **It cannot see a COMMITTED hand edit inside the markers.** Once the
   human commits their in-marker edit, `git status` is clean and the next
   regeneration silently destroys it. Git is structurally blind to the one
   edit that actually loses data.
4. **`recompile` does NOT "diff against git".** Y-17's sentence is stale
   on that third clause. `verbs.recompile` recompiles from the ledger and
   branches on `compile_result.changed` — a content comparison inside
   `compilers` (`verbs.py:4829-4838`). Its git use is the dirty skip
   (`:4807`) and the commit (`:4834-4838`).
5. **The `--selftest` drift check does not diff a HOST against git
   either.** `selfcheck._check_drift` (`selfcheck.py:427`) looks for the
   record's `(lrn-…)` entry marker inside the target's managed section,
   and a reference record's id inside its references file. All nine rows
   are file/marker-based with respect to hosts:
   ```
   $ grep -n '("[a-z]*", \*_check' selfcheck.py | wc -l
   9
   ```
   `capture, compiler, markers, drift, reach, hooks, surface, sentinel,
   invocation` — **zero of nine touch a HOST's git.** *(CORRECTED-r2,
   gate D-3: r1 said "zero of nine touch git", which is false —
   `_check_drift` opens with `state = home_state(home)`
   (`selfcheck.py:452`; two more rows do the same at `:334` and `:838`),
   and `ledger.home_state` calls `hosts.is_repo_root(home)`
   (`ledger.py:70`), which runs one git subprocess **against the
   LEDGER**. The claim this unit needs is the host-scoped one, and it
   holds.)*

**So of Y-17's three named justifications — "audit, rollback, and
recompile all diff against git" — the third is false as written, and the
first two are the real ones.** Audit (`git log` / `git blame` over the
compiled canon) and rollback (`git revert`, though S-12 already forbids
per-lesson revert as a *correction* mechanism) genuinely need a repo.
Drift detection, recompile, and the whole selftest do not.

### 2.5 The shape plain mode reuses — and the discriminator it must NOT reuse

*(REWRITTEN-r2, gate B-1. r1's headline claim — "plain mode is not a new
code path, it IS the existing `host_repo is None` path" — is **withdrawn**.
It is false under the ruled mechanism, and it was the source of the
blocker.)*

`verbs.TargetSpec.host_repo` is `Path | None`, and `None` is a live,
shipped value. What it buys, read off `_host_phase`:

```
verbs.py:2596  lock = (
verbs.py:2597      gitops.commit_lock(spec.host_repo)
verbs.py:2598      if spec.host_repo is not None
verbs.py:2599      else contextlib.nullcontext()
verbs.py:2600  )
verbs.py:2613  if spec.host_repo is not None and host_paths:
```

For user scope, `_host_phase` today takes **no lock**, runs **no dirty
gate** (it runs `chezmoi.preflight_user_scope` instead, `verbs.py:1274`;
`:1183` is the rules variant and `:4779` recompile's — *CORRECTED-r2, gate
D-6*), **stages nothing**, **commits nothing**, and **pushes nothing**.
The resolution-evidence surface has a shipped state for exactly that
outcome:

```
$ grep -n 'wrote_uncommitted' src/self_learn/cli.py
1156:        return "wrote_uncommitted"
```

pinned by `tests/test_resolution_evidence.py:405::test_user_scope_route_is_wrote_uncommitted`
(asserting `host_commit_sha is None` and
`outcome_state == "wrote_uncommitted"`).

**What plain mode takes from this, and what it must not.** Plain mode
reuses the **SHAPE** of that write path — no host commit, no host push,
`host_commit_sha = None`, `outcome_state = "wrote_uncommitted"`. It must
**not** reuse the **DISCRIMINATOR**, because `host_repo is None` already
means something else. §2.5a is that measurement, and §4.1–§4.2 are the
mechanism the orchestrator ruled.

### 2.5a `host_repo is None` already means "chezmoi user scope", in 17 sites

*(NEW in r2, gate B-2.)* The docstring says it in terms
(`verbs.py:735`):

> *"``host_repo`` is None only for the chezmoi user flow (the dotfiles
> repo commits itself)."*

Every site that reads the sentinel, measured
(`grep -rn 'host_repo is None\|host_repo is not None' src/self_learn/`):

| site | what `None` selects there | hazard for a plain host |
|---|---|---|
| `verbs.commit_drift:3508` | the chezmoi branch: `user_scope_dirty_status`, `dotfiles_source_path`, `CHEZMOI_DRIFT_REFUSAL` | a plain PROJECT host would be treated as the user's dotfiles file |
| `verbs.recompile:4771` | comment *"The chezmoi-guarded user file (E-17)"* → `preflight_user_scope` | same misroute |
| `verbs.py:2152` | `rules_dir = None` (so `rules_topic_count` is silently 0) | a plain host's rules co-fire silently under-counts |
| `verbs.py:1952` (in **`_compile_set`**, def `:1907`) | `host = None`, and the loop below is `if project is None or host is None: continue` — **the multi-bucket union that decides WHICH records compile into this target** | *(CORRECTED-r3, gate r2-M3: r1/r2 called this `surface_fill`, which is a different function at `verbs.py:2042` with no `host_repo` site of its own.)* **The highest-consequence of the three**: a wrong `None` here silently BLANKS a compiled section, where the others only under-count a report field |
| `verbs.py:3408` | `_commit_drift_targets` early-return | as above |
| `report.py:973`, `report.py:1480` | `continue` — the row is dropped | **a plain host silently vanishes from two report surfaces** |
| `verbs.py:2598` | `nullcontext()` — no lock | B-1: the plain host would be unserialized |
| `verbs.py:2613` | stage/commit skipped | correct by accident, wrong by construction |
| `verbs.py:2999, 3276, 3324, 4069, 4178` | host push / `git show` skipped (each also guarded by `host_sha is not None`) | correct by accident |
| `verbs.py:3001, 3326` | the same, for `old_host_repo` (retirement) | correct by accident |
| `verbs.py:3440` | a docstring asserting the equivalence | stale the moment plain exists |

**15 sites in `verbs.py`, 2 in `report.py`. `.host_repo` is read in
exactly two modules and nowhere in the UI:**

```
$ grep -rn '\.host_repo' src/self_learn/ | sed 's/:.*//' | sort | uniq -c
     4 report.py
    32 verbs.py
$ grep -rn 'host_repo' ../../ui/src/            # (no output)
```

**`worker.py`'s five `host_repo` sites are a DIFFERENT local** — a prompt
sentinel built from `bucket_project_path(bucket_dir)`. `worker.py:504-505`
is `host_repo: Path | None = None` then
`host_repo_sentinel = "(no host repo at this scope)"`; the string
`"(user scope has no host repo)"` is the `elif scope == "user"` branch at
`:525` *(CORRECTED-r3, gate r2-D8: r2 quoted `:525`'s string as if it were
`:505`'s assignment)*. They have nothing to do with `TargetSpec` and are
**not** touched. Stated so a builder grepping the name does not "fix" them.

### 2.6 The user-scope canon — MEASURED, not assumed

```
$ ls -la ~/.claude/CLAUDE.md
-rw-r--r-- 1 user user 24329 Aug 24 19:20 ~/.claude/CLAUDE.md

$ realpath ~/.claude/CLAUDE.md
~/.claude/CLAUDE.md                      # not a symlink

$ git -C ~/.claude rev-parse --show-toplevel
fatal: not a git repository (or any parent up to mount point /)
Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).
rc=128

$ git -C ~/.config status --porcelain          # (empty)
rc=0
$ git -C ~/.config ls-files
.gitignore
CLAUDE.md
references/LEARNINGS.md
```

**Findings.**

- **The user-scope canon target is `~/.claude/CLAUDE.md`**
  (`verbs.DEFAULT_USER_CLAUDE_MD`, `verbs.py:185`), resolved in
  `_resolve_target`'s `scope == "user"` branch (`verbs.py:1267-1278`),
  which returns `TargetSpec(..., host_repo=None)`.
- **`~/.claude` is not a git repository and has no parent repository.**
  The verb assessment's claim — *"user-scope canon has NO VCS since
  chezmoi's retirement"* — is **CONFIRMED, measured** (and independently
  re-measured by the blind gate).
- **The global `CLAUDE.md`'s claim about `~/.config` is also true, and is
  about a different file.** `~/.config` is a registered **project** host,
  a repo root with 24 commits and no remote, tracking three files. Its
  `CLAUDE.md` is project-scope canon. Both claims are true; they are about
  different files (§12.4 lands that sentence in the runbook).

**Which mode is user scope in after this unit?** *(RULED, gate B-2 +
the orchestrator's ruling on r1's Q-3 — r1 recommended deferral and is
**overruled**.)* **User scope becomes a first-class `plain` host, by
construction, in Phase 2.** `~/.claude` (measured: no VCS) is the
user-scope canon host; its mode is `plain` and cannot be anything else;
its compile record is keyed by the synthetic slug `user` (§4.2), which
also resolves gate M-5 — r1's REC4 required a record for user scope while
§4.3 gave it no slug and no `host:` value. `~/.claude/CLAUDE.md` is the
largest managed section on this machine (19 279 B, 25 entries — §2.7),
and it is the loudest case of canon with no integrity instrument at all.

### 2.7 The managed-region census — what a ledger-side history would hold

`managed-region census` and `reference-target census` (§2.0), de-duplicated
by resolved path across all nine hosts plus `~/.claude`:

```
DEDUPED files with a managed section: 16
  total managed-section bytes: 44654
  total containing-file bytes:  283204
  managed share of those files: 15.8%
  min / mean / max section bytes: 98 / 2791 / 19279
  total entries: 55

self-learn REFERENCE target files (dated lrn- blocks): 9
  total bytes: 25099, total entries: 33
```

*(CORRECTED-r2, gate D-7: mean is 44 654 / 16 = 2 790.875 → **2 791**,
not 2 790.)*

*(CORRECTED-r2, gate D-8: the 16 files as the instrument walks them
include three `.claude/worktrees/` linked-worktree checkouts of a host
file that no route targets —
`repos/3d-printing/k1c-manta-m5p/.claude/worktrees/{agent-ac2c5b10111a9ac08,beacon-thermal-mitigation}/CLAUDE.md`
and `repos/keyboards/.claude/worktrees/qk-alice-duo-probe/CLAUDE.md`. They
survive `Path.resolve()` dedup because they are genuinely distinct paths.
**Excluding them: 13 files, 40 627 managed bytes of 220 842 file bytes =
18.4%.** Both figures support the same argument; 18.4% is the one to
quote where the argument is about routable targets, and it is used
alongside 15.8% at every site below.)*

The five largest managed sections:

| file | file bytes | section bytes | entries |
|---|---|---|---|
| `~/.claude/CLAUDE.md` | 24 329 | **19 279** | 25 |
| `claude-skills/plugins/testing-methodology/skills/testing-methodology/SKILL.md` | 10 038 | 9 257 | 11 |
| `.config/CLAUDE.md` | 72 467 | 2 166 | 3 |
| `claude-skills/plugins/hypr-doctor/skills/hypr-doctor/SKILL.md` | 13 917 | 2 158 | 4 |
| `3d-printing/k1c-manta-m5p/CLAUDE.md` | 25 499 | 1 590 | 1 |

**Total canon under management on this machine: 69 753 bytes across 25
files and 88 entries.**

And the ledger it would live in:

```
$ du -sh ~/.self-learn ~/.self-learn/.git
4.0M    ~/.self-learn
3.2M    ~/.self-learn/.git
$ git -C ~/.self-learn rev-list --count HEAD
382
$ git -C ~/.self-learn count-objects -vH | tail -6
in-pack: 1756
packs: 2
size-pack: 467.68 KiB
```

**Sizing the user's proposal.** 98 `self-learn:` commits have landed across
all nine hosts **in six weeks — 2026-07-13 to 2026-08-25** *(CORRECTED-r2,
gate D-2: r1 said "13 months". The 98 total is unaffected; the growth-RATE
reading is — this is six weeks of accrual, not thirteen months of it.)*
At the measured mean managed section of 2 791 B, snapshotting the whole
region on every write costs ≈ 273 KB *uncompressed* over the entire
history to date — against a ledger pack of 468 KiB. Git deltas
near-identical regenerations to almost nothing. **Storing full ledger-side
snapshots of every canon write to date would roughly double the ledger's
pack size in the worst case, and far less in practice.** Cost is not the
objection to the user's idea. §3.2 says what the real objection is, and it
is much smaller than it sounds.

### 2.8 The UI has a host-add path, and it carries a consent contract

```
$ grep -rn 'build_host_add_argv\|_needs_init\|init_disclosed' \
    plugins/self-learn/ui/src/self_learn_ui/routes.py
2411:def build_host_add_argv(path: str, *, init: bool = False) -> list[str]:
2419:def _needs_init(path: str) -> bool:
2424:    return not is_repo_root(path)
2485:        needs_init=_needs_init(path),
2526:    use_init = init_disclosed == "1" and _needs_init(path)
2529:    result = await runner.run(build_host_add_argv(path, init=use_init))
```

Three routes (`host-add/arm`, `/disarm`, `/confirm`), one template
(`ui/templates/partials/host_add_bar.html`), and the **Y-17 consent
invariant** (`routes.py:2378-2400`): `--init` executes only when the arm
rendering displayed the git-init disclosure AND the confirm-time
re-derivation of `is_repo_root` still says it is needed. The bit can only
ever WEAKEN execution. `self_learn.hosts.is_repo_root` is IMPORTED, never
reimplemented (`routes.py:33`).

**Consequence for this unit** *(RULED, gate M-3, overruling r1's Q-2
recommendation)*: the UI does not merely suppress a stale disclosure —
**it exposes the mode as the consent choice itself.** §4.9.

### 2.9 The mutable seam, and the one place today's code is already wrong

**`cli._outcome_state` (`cli.py:1115-1160`) cannot describe a plain host.**
Read the route branch as shipped:

```python
    # route: the full 4-state predicate.
    if result.host_commit_sha is not None:
        return "landed"
    if result.compile_result is None:
        return "drift"
    if _reports_no_change(result.compile_result):
        return "no_op"
    if isinstance(result.compile_result, UserScopeResult) or result.variant == "local":
        return "wrote_uncommitted"
    return "unknown"
```

A successful route into a plain project host yields `host_commit_sha=None`,
a non-`None` `SectionResult` with `changed=True`, and neither
`UserScopeResult` nor `variant == "local"`. **It falls through to
`"unknown"`.** That is the exact seam the build must widen, and `PLAIN3`
is its criterion. The blind gate re-ran the predicate and confirmed it.

**And the H-3 hole plain mode opens.**
`tests/test_hosting_fixes.py:772::test_typod_skills_root_never_writes_canon_outside_a_repo`
pins it, in its own words:

```python
"""`skills_root: /home/user/repos` (a plain dir) used to CREATE
/home/user/repos/CLAUDE.md and only then fail its git commit."""
...
with pytest.raises(verbs.VerbError, match="not a git repo"):
    verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)
assert not (typo / "CLAUDE.md").exists()   # canon never written
assert head(env.ledger) == before          # and no ledger commit either
```

**The `not a git repo` refusal is what makes that test pass** — and it is
the sole guard **on the skills-root legs** *(QUALIFIED-r2, gate N-2: for a
*projects* entry there IS an upstream check —
`verbs._project_host_or_refuse` (`verbs.py:812-822`) first requires
`hosts.is_project_host(load_hosts(home), host)` against the bucket's own
`meta.yaml` path, so a typo'd projects entry is refused with "host not
registered" before `_gate_host` runs. The test's own route is
`scope="skill:s"`, reaching `_gate_host(home, hosts.skills_root,
"skills-root")` with no registration cross-check.)*

Remove it for plain hosts and a hand-edited typo'd skills-root would sail
through `_gate_host`, the ledger commit would land, and the failure would
move to the host phase — where `_HOST_PHASE_ERRORS` (`verbs.py:2561`)
converts it into a warning and a routed-but-uncompiled record. **A clean
refusal degrades into drift.** §4.4 is the replacement guard.

### 2.10 Test census

```
$ cd plugins/self-learn/cli && … pytest --collect-only -q | tail -1
2417 tests collected in 2.47s
$ cd plugins/self-learn/ui  && … pytest --collect-only -q | tail -1
1268 tests collected in 2.05s
```

| file | collected |
|---|---|
| `tests/test_hosting.py` | 57 |
| `tests/test_hosting_fixes.py` | 72 |
| `tests/test_commit_drift.py` | 18 |
| `tests/test_resolution_evidence.py` | 18 |
| `tests/test_lock_invariant.py` | 35 |
| `tests/test_verbs.py` | 35 |
| `tests/test_m2_verbs.py` | 24 |
| `tests/test_gitops.py` | 12 |

Ten test files reference the host-git surface at all
(`paths_dirty | DirtyTargetError | GITOPS_DIRTY_MARKER | host_commit_sha |
"not a git repo" | is_repo_root | INIT_COMMIT_SUBJECT`):
`test_hosting.py` (20 hits), `test_resolution_evidence.py` (12),
`test_hosting_fixes.py` (10), `test_init.py` (9), `test_pointer.py` (4),
`test_gitops.py` (3), `test_verbs.py` (3), `test_commit_drift.py` (2),
`test_batch_fixes.py` (1), `test_m2_verbs.py` (1).

**The single test most at risk** *(CORRECTED-r2, gate D-10: r1 said "must
change" and then said it stays unedited, in the same paragraph)*:
`test_hosting.py:434::test_cli_without_flag_still_refuses_non_repo`. It
asserts `self-learn host add <plain-dir>` exits non-zero with
`"not a git repo"`. Under a `git` default that stays TRUE and the test
stays green **unedited**; `MODE5` requires exactly that.

### 2.10a THE CHEZMOI CENSUS — the deletion list, measured

*(REPLACED-r3, gate r2-B3: r2 carried a CLI-only "budget" and named the
deletion list from memory, which omitted the UI's entire adopt surface and
one module-level import whose deletion errors the whole UI suite. The
ruling is that the list is produced by a census. This is that census.)*

```
$ cd plugins/self-learn
$ for d in cli/src cli/tests ui/src ui/templates ui/tests; do
>   printf '%-16s %s\n' "$d" "$(grep -rn -i chezmoi $d | wc -l)"; done
cli/src          205
cli/tests        343
ui/src            12
ui/templates       7
ui/tests          43
$ grep -rn -i chezmoi ../../install.sh | wc -l
0
$ grep -rn -i chezmoi ../../docs/ | wc -l
497
$ grep -rn -i chezmoi commands skills | wc -l
1
```

**By file — `cli/src` (205):**

```
     91 cli/src/self_learn/chezmoi.py          # the module itself
     89 cli/src/self_learn/verbs.py            # incl. the 42 chezmoi_bin sites
     20 cli/src/self_learn/cli.py
      3 cli/src/self_learn/teach.py            # :75 import, :722-723 except tuple
      2 cli/src/self_learn/compilers.py        # :596, :605 — COMMENTS ONLY, kept
```

**By file — `cli/tests` (343), all 22 files:**

```
    122 test_a2_rules_local.py     43 test_commit_drift.py     38 test_chezmoi.py
     30 test_verbs.py              16 test_resolution_evidence.py
     14 test_hosting.py            12 test_route_hook.py       11 test_u_glob.py
     11 test_regime_fixes.py        8 test_xscope_enumeration.py
      8 test_retirement_cleanup.py  7 test_lock_invariant.py    5 test_m2_verbs.py
      5 test_compilers.py           3 test_pointer.py           2 test_records_lifecycle.py
      2 test_hook_compiler.py       2 test_buckets.py           1 test_surface_fill.py
      1 test_one_motion_config.py   1 test_invocation.py        1 test_composer.py
```

`test_chezmoi.py` is a dedicated file; `test_chezmoi.py` +
`test_a2_rules_local.py` collect **82 tests** together.

**`ui/src` (12) and `ui/templates` (7) — the complete list:**

```
ui/src/self_learn_ui/routes.py:32:from self_learn.chezmoi import ADOPT_COMMAND_PREFIX, CHEZMOI_DIRTY_MARKER
ui/src/self_learn_ui/routes.py:74:    "chezmoi-adopt": "Adopt into chezmoi",
ui/src/self_learn_ui/routes.py:167:    elif verb == "chezmoi-adopt":
ui/src/self_learn_ui/routes.py:169,172:  (comments)
ui/src/self_learn_ui/routes.py:174:        argv = ["chezmoi-adopt", target or ""]
ui/src/self_learn_ui/routes.py:1401,1906,1979,1984,2058:  (comments)
ui/src/self_learn_ui/routes.py:2062:COMMIT_DRIFT_MARKERS = (GITOPS_DIRTY_MARKER, CHEZMOI_DIRTY_MARKER)
ui/templates/partials/adopt_offer.html:2,12
ui/templates/partials/evidence.html:46
ui/templates/partials/action_bar.html:193,195,196,197
```

plus the non-`chezmoi`-named half of the same surface:
`routes.py:1886-1889` (the two call sites), `_extract_adopt_path`
(`:1989-2002`), `_adopt_offer_response` (`:2004`), the dismiss route
(`:2030`), `models.py:305` (`adopted: bool = True`) and `:334`
(`if scope == "user" and not adopted:`), `action_bar.html:188` / `:198-199`,
`detail.html:143-146`.

**`ui/tests` — TWO different censuses, and r3 printed one under the
other's label** *(CORRECTED-r4, gate r3-D1)*:

```
$ grep -rn -i chezmoi ui/tests | sed 's/:.*//' | sort | uniq -c
     17 test_routes.py   11 test_commit_drift.py    7 test_proposals.py
      5 test_resolution_evidence.py    3 test_js_dom.py          # = 43, FIVE files
$ grep -rn -i adopt   ui/tests | sed 's/:.*//' | sort | uniq -c
     26 test_routes.py   11 test_js_dom.py          6 test_resolution_evidence.py
      6 test_proposals.py    6 test_commit_drift.py    4 test_models_detail.py   # = 59, SIX files
```

**`chezmoi`: 43 across five files** — `test_models_detail.py` has **zero**.
**`adopt`: 59 across six files.** Both matter and they gate different
criteria: `CHEZ6` sweeps `chezmoi`, `UIC5` sweeps `adopt`. Two named
functions: `test_routes.py::test_chezmoi_adopt` (`:112`),
`::test_arm_then_confirm_runs_chezmoi_adopt` (`:2912`).

**The CLI adopt surface (8 test functions, ALL in
`test_a2_rules_local.py`** — *CORRECTED-r3, gate r2-D3):*
`cli.py:328-336` (parser), `:1553-1572` (`_cmd_chezmoi_adopt`),
`:2102-2103` (dispatch); `verbs.py:163` (`__all__`), `:3584-3611`
(`chezmoi_adopt`), `:2412-2415` + `:2646-2654` (the `offer_adopt` /
`adopt_hint` channel); `chezmoi.py:61`, `:257-265`, `:311` (inside
`compile_user_scope`), `:376`.

**What is NOT deleted:** `compilers.py:596` and `:605` are prose comments
mentioning chezmoi's historical refusal — `compilers.py` is untouchable
(§9), so a post-Phase-2 `cli/src` sweep returns **2**, not 0 (`CHEZ2`).
And `docs/` is **history and stays** — `CHEZ6`'s instrument is scoped to
`src/`, `templates/` and `tests/`, never to `docs/`.

**The `docs/` figure is self-referential and must be quoted stably**
*(CORRECTED-r4, gate r3-D2: r3 said 497; it is now 546, and the entire
delta is this draft's own growth — 497 − 76 = 421 and 546 − 125 = 421)*:
**`docs/` holds 421 chezmoi hits EXCLUDING this draft** (546 including it,
at r4), led by `c2-chezmoi-capability-spec.md` at 115 and
`a2-rules-local-spec.md` at 58. Quote 421; the other number moves on every
edit to this file.

### 2.10b THE PHASE-1 DISTURBANCE CENSUS

*(NEW in r4, gate r3-B1. r3 stated the Phase-1 disturbance as "the 36
chezmoi-shimming functions in `test_a2_rules_local.py`" and added *"the
rest of the 343 CLI-test hits are Phase 2's"*. **Both claims are
withdrawn.** Phase 1 drops the `chezmoi_bin` parameter from 42 `verbs.py`
signatures and deletes `commit_drift`'s user leg; the blast radius is
larger and spans six files. It is measured here the way §2.10a measures
chezmoi, so the builder budgets from a census rather than a sentence.)*

**Leg 1 — `chezmoi_bin` passed as a keyword argument.** Dropping the
parameter in Phase 1 makes every one of these a `TypeError`:

```
$ grep -rn 'chezmoi_bin' cli/tests/ | sed 's/:.*//' | sort | uniq -c
     19 test_a2_rules_local.py       11 test_u_glob.py
      7 test_xscope_enumeration.py    3 test_pointer.py       2 test_verbs.py
                                                              # 42 sites, FIVE files
```

**23 of the 42 are outside `test_a2_rules_local.py`** — e.g.
`test_a2_rules_local.py:298`,
`verbs.route(env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent")`.

**Leg 2 — test functions that mention chezmoi in their own body**
(AST census, `ast.get_source_segment`), the files Phase 1 actually
touches:

| file | chezmoi functions / total | Phase-1 disposition |
|---|---|---|
| `test_a2_rules_local.py` | **36** of 69 | EDIT — drop the shim + the `chezmoi_bin` kwarg; the user-scope route now takes the plain path |
| `test_u_glob.py` | **10** of 30 | EDIT — `chezmoi_bin` kwarg only (11 sites) |
| `test_chezmoi.py` | **8** of 13 | **UNTOUCHED in Phase 1** — it tests `chezmoi.py` directly, which Phase 1 does not change; deleted whole in Phase 2 |
| `test_commit_drift.py` | **6** of 18 | **REWRITE** to the plain-host refusal — see leg 3 |
| `test_verbs.py` | **4** of 35 | EDIT — 2 `chezmoi_bin` kwarg sites + 2 shims |
| `test_xscope_enumeration.py` | **3** of 27 | EDIT — 7 `chezmoi_bin` kwarg sites |
| `test_pointer.py` | **3** of 48 | EDIT — 3 `chezmoi_bin` kwarg sites |
| `test_resolution_evidence.py` | **2** of 18 | EDIT — `USER6`'s own concession |
| `test_retirement_cleanup.py` | **2** of 16 | EDIT |
| `test_m2_verbs.py` · `test_compilers.py` | 2 each | EDIT |
| `test_buckets.py` · `test_composer.py` · `test_hook_compiler.py` · `test_hosting.py` · `test_invocation.py` · `test_one_motion_config.py` · `test_records_lifecycle.py` · `test_regime_fixes.py` · `test_route_hook.py` | 1 each | EDIT or no-op — each to be confirmed by the builder and named in `S3` |

**Total: 87 chezmoi-mentioning test functions across 20 CLI test files.**
Phase 1 touches the subset whose behaviour it changes; Phase 2 removes the
rest with the module.

**Leg 3 — `test_commit_drift.py`'s user leg.** §4.7 deletes
`commit_drift`'s `:3508` chezmoi branch in Phase 1, so `commit-drift`
against user scope refuses at 64 instead of committing. AST census of that
file — **18 functions, 6 of which exercise the deleted leg**:

```
:191  test_dirty_dotfiles_goes_through_chezmoi_git      # asserts the user leg COMMITS
:210  test_drift_refused_no_commit
:226  test_clean_dotfiles_refused
:237  test_dry_run_reports_repo_and_files_writes_nothing
:274  test_chezmoi_dirty_message_carries_the_extracted_marker
:329  test_commit_drift_drift_exit_64
```

The other **12 are git-mode** and stay byte-unedited. `CD2` says exactly
that.

**The six files Phase 1 must be allowed to edit** —
`test_a2_rules_local.py`, `test_u_glob.py`, `test_xscope_enumeration.py`,
`test_pointer.py`, `test_verbs.py`, `test_commit_drift.py` — plus
`test_resolution_evidence.py` (`USER6`), **`test_m2_verbs.py`,
`test_compilers.py`, `test_retirement_cleanup.py`** (its own table marks
all three EDIT) and the **nine** one-hit files. §9's Phase-1 list names
them and `S3` reconciles them individually. *(CORRECTED-r5, gate r4-D3:
r4 said "the eight one-hit files" — the AST census gives exactly nine —
and this sentence omitted the three EDIT files its own table lists.)*

**Leg 4 — six files this census missed entirely** *(CARVED-r7, builder
disclosure 2026-08-28: none of these mention chezmoi, so leg 1/2's AST
census could not have found them — each is forced by an `[A]` behavior
change elsewhere in this unit breaking a literal assertion the census
never scoped. Discovered during the build, not predicted by the spec;
carved here rather than silently edited so `S3`'s own membership control
stays a true statement.)*:

| file | forcing criterion | assertion that broke |
|---|---|---|
| `test_provider.py` | `MODE3` — `config.effective_default_mode` is a new public export | `test_pr1_provider_setting_and_all`'s `__all__` membership list (missing the new name) |
| `test_round3_fixes.py` | `REC12`/§4.5b — the ledger lock is now held through the host write, not free during it | `TestLockScope.test_the_ledger_lock_is_free_during_the_host_phase`'s `probe_out.read_text() == "ACQUIRED"` (now `"BLOCKED"` — the test's own premise inverts, name kept, body rewritten to prove the new claim the same way: from inside a real host pre-commit hook) |
| `test_route_cli.py` | `REC9` — the compile record rides the SAME ledger commit as the routed record, never a second commit | `test_teach_route_dest_end_to_end`'s `env.committed_files() == [f"skills/s/resolved/{record.id}.md"]` (now two paths: the resolved record plus one `compiled/<slug>.yaml`) |
| `test_u_fake.py` | cross-unit fallout of the `test_route_cli.py` edit above — DS1's `REWRITTEN`/`_DS1_EXPECTED` census pins every function's post-`c2669a9` byte count and sha256, so an in-scope edit of a function it tracks forces a re-pin | `_DS1_EXPECTED["test_route_cli.py"]`'s pinned `(count, sha256)` tuple (added `("test_route_cli.py", "test_teach_route_dest_end_to_end")` to `REWRITTEN`, regenerated the tuple the same way the file's own discipline requires — over `git show c2669a9:...`, never the working tree) |
| `test_worker_contract.py` | cross-unit fallout of the `test_u_fake.py` edit above — `_ARMOR_SHAS` pins `test_u_fake.py`'s own whole-file sha256 | `_ARMOR_SHAS["plugins/self-learn/cli/tests/test_u_fake.py"]`'s pinned hash (re-pinned to the file's new sha256, one line, dated comment) |
| `ui/tests/test_routes.py` | `UIM1`/`UIM2` — the confirm route's argv now always carries `--mode <mode>`, and the arming/confirm text always shows it | every `runner.calls == [["host", "add", str(foreign)]]`-shaped assertion (now `[..., "--mode", "git", ...]`) and the rendered-command assertions (`self-learn host add {foreign}` → `self-learn host add --mode git {foreign}`); `_confirm_form_fields`'s regex also broke against `UIM1`'s new same-named `mode` radio pair — a naive `dict(re.findall(...))` let the LAST-rendered radio's `value` silently overwrite the CHECKED one's, so it was rewritten radio-aware (skips any `<input type="radio">` without `checked`) |

This file is **already** covered by §9's own `ui/tests/` "additions only"
clause for anything newly added (`TestUIM1DefaultModeConfig`), but the
edits table above are NOT additions — they are literal-assertion and
helper-function EDITS to pre-existing tests, which is why it is carved
here rather than left to that clause.

**Leg 5 — four more files, forced by two of this unit's OWN code-gate
folds rather than by anything in the census** *(CARVED-r9, gate r2-M2:
r1's own fold (`b652992`) already touched all four of these — §9's list
and `S3`'s whitelist were never widened to admit them, which is what
gate r2 caught)*:

| file | forcing criterion | what broke / what changed |
|---|---|---|
| `cli/tests/conftest.py` | D-1's litter guard (r1: widened to hard-fail on an in-process host-lock file; r2: docstring paragraph documenting the XDG_CACHE_HOME rule for ad-hoc scripts) | the litter-guard fixture's own docstring/body — no test bodies outside it |
| `ui/tests/conftest.py` | D-1, same shape, mirrored — this file has no armor pin so no re-pin follows from it | the matching litter-guard fixture's docstring |
| `cli/tests/test_u_sdka.py` | D-1, downstream — `test_hy5_numstat_bounds_hold`'s pinned `(added, deleted)` tuple for `cli/tests/conftest.py` is a byte-count observation of that file, so every D-1 edit to `conftest.py` forces a re-measured bound here (r1 and r2 both) | `bounds["plugins/self-learn/cli/tests/conftest.py"]`, re-measured via `git diff --numstat` against the file's actual pre-fold state, never guessed |
| `cli/tests/test_context_budget.py` | `B-1` (r1 only — untouched this r2 fold) — `compiled.refuses("unknown", "plain")` went `True`, and `_sync_user_claude_md`'s fixture hand-wrote the managed region into user scope with no matching compile-record entry, landing exactly in the state `B-1` now refuses | the fixture writes the matching record entry, mirroring what a real apply step leaves behind (same `write_entry` call `verbs._write_compile_record_entry` makes) |

None of the four mention chezmoi and none are in the 20-file leg-1/2
census or leg 4's six files — they were found only by running the full
suite after B-1/D-1 landed, which is why leg 4's method (an AST census
over an `[A]` behavior change) could not have found them either: leg 4's
forcing criteria are single, dated code changes; leg 5's are litter-guard
*maintenance* (D-1) and a fixture that assumed a state B-1 later closed.
§9's Phase-1 file list and `S3`'s positive-control whitelist are both
widened to admit these four, so `S3`'s own membership check (§5.12)
stays a true statement about what this unit has actually touched.


### 2.11 The lock-invariant walker, and why it cannot be this unit's instrument

`tests/test_lock_invariant.py` (848 lines, 35 tests) derives entrypoints,
mutations and lock coverage structurally. Its lock detector, verbatim
(`:278-284`):

```python
def _is_lock(expr: ast.expr) -> bool:
    """Does this expression subtree open the critical section? (Walks the
    whole subtree so ``lock = commit_lock(r) if r else nullcontext()`` —
    ``verbs._host_phase``'s real shape — counts.)"""
```

**The walker deliberately treats `_host_phase`'s nullcontext ternary as
guarded**, by name, without evaluating the condition. The blind gate
replicated `_is_lock` and `_Analysis._guarded_lines` against four
`_host_phase` shapes and measured the result:

| shape | walker |
|---|---|
| shipped ternary | GREEN |
| ternary kept, plain branch yields `nullcontext()` | **GREEN** |
| the assignment replaced by a bare `contextlib.nullcontext()` | **RED** (zero guarded lines) |
| the choice refactored into `lock = _host_lock(spec)` | **RED** (zero guarded lines) |

So:

- The walker stays green for the mutation that matters. It is a
  **regression guard** (`UN5`), never evidence that plain writes are
  locked.
- A separate, **process-level** instrument is required (`PLAIN5`), and
  §4.3 gives plain hosts a real lock so there is something for it to
  prove.
- **A builder who refactors the lock choice into a helper turns the
  walker RED** — a safe failure direction, but one that will look like a
  regression. Said here so it is not debugged as one.

`NOT_REPO_TRUTH` (`:106-206`) already exempts every XDG-cache writer,
including the sentinel's four entries and `serve`'s four. The plain-host
lock file needs no new exemption (it is an flock target, not a write the
walker classifies) — `PLAIN6` asserts the exemption list did not grow.

---

## 3. DECISION — the text this unit owes `03-decisions.md`

*§3.1–§3.4 are written to be lifted into `S-51` (§12.1).*

### 3.1 The option map

Six framings were considered. Each is stated as its own best case.

**Option 1 — Status quo: every canon host is a git repo.**
*Case for:* one posture, one code path, 42 host-side git operations all
meaningful; audit and rollback available on every host; `host add --init`
already lowers the cost to one flag; a repo is free.
*Case against, measured:* it is not free. Three of nine hosts exist as
repos only to satisfy the check, two of them needing hand-written
deny-by-default `.gitignore` files to stop the repo swallowing the
directory (§2.1). Three of nine have no remote, so the push half is inert
for 33% of them. And the check's central protection — the dirty gate —
is per-file rather than per-region, so it refuses over edits the compiler
provably preserves while being structurally blind to the one edit that
loses data (§2.4).

**Option 2 — Hosts need no VCS at all; history lives ledger-side.**
**This is the user's own framing** and it gets §3.2 to itself.

**Option 3 — Per-host mode `git | plain`, set once at registration, with
a ledger-side compile record as plain mode's integrity instrument.**
*Case for:* honours the ruling's "set the behavior once" literally; git
hosts stay byte-identical so nothing already working is put at risk;
and the compile record is **option 2's mechanism, adopted, scoped to what
it can actually do**.
*Case against:* two postures to reason about; one new ledger artifact
that needs an H-5 backstop (§4.6); the H-3 typo hole (§2.9) that §4.4
must close; and it forces the `host_repo is None` overload to be retired
(§2.5a) rather than reused.

**Option 4 — One global switch in `config.yaml`, no per-host granularity.**
*Case for:* smallest surface; exactly one thing to set; matches
`S-10`'s committed-`config.yaml` precedent.
*Case against, measured:* this machine would need both values at once.
`claude-skills` (504 commits, a live remote, 76 self-learn commits) is a
real repo whose canon genuinely wants history; `repos/3d-printing` (4
commits, no remote, a whitelist ignore file) is a directory pretending to
be one. A global switch forces one of them to be wrong. Rejected on that
measurement, not on principle.

**Option 5 — Auto-detect: if the path is a repo, use git; else plain.**
*Case for:* zero configuration; the user never sets anything.
*Case against:* it is the failure mode `S-10` was written against —
behaviour that changes without anyone deciding. Concretely: a user runs
`git init` in their notes directory for unrelated reasons and self-learn
silently starts committing to it; or a `.git` directory is removed and
self-learn silently stops. It also cannot be reconciled with the Y-17
consent contract, whose entire point is that becoming a repo is a
disclosed choice. And the user asked for a way to *set* the behaviour,
not for it to be inferred.

**Option 6 — Degrade gracefully at each of the 42 call sites: try git,
catch, continue.**
*Case for:* no new configuration at all; works everywhere.
*Case against:* 42 independent `try`/`except` sites is 42 places to get
the failure semantics wrong, and it destroys the property that makes the
current code auditable — that a `GitOpsError` reaching dispatch means
something definite (exit 6 = nothing written; exit 7 = half-written,
`cli.py:1389-1404`). A catch-and-continue at the host phase would turn a
wedged git into a silent no-write. Rejected.

### 3.2 The user's framing, steelmanned

> *"why do we need to make sure there's a repo? is it just for claude.md
> backups? if so, why not just handle that in some kind of shared
> ~/.self-learn directory (which we probably already make)"*

**The steelman, and it is strong.**

1. **The premise is mostly right.** Of the eleven host-side operation
   classes in §2.3, exactly two — `H-g` (commit) and `H-h` (push) — deliver
   history and off-machine backup. The other nine are *gates and
   plumbing that exist because those two exist.* Remove the commit and
   the push and `paths_dirty`'s attribution rationale, the host commit
   lock, the `git show` render, the `git rm`, and the unpushed-count all
   lose their reason for being. **Roughly three quarters of the host-side
   git surface is scaffolding around one commit.**
2. **The ledger already is the source of truth.** H-2 says it in the
   register: *"the ledger is truth; canon is compiled output; recompile is
   always safe and repairs any two-phase interruption."* The host commit is
   therefore a *copy* of information the ledger already holds, in a place
   the ledger does not control.
3. **The ledger already exists and is already versioned.** 382 commits,
   468 KiB packed. The user's "which we probably already make" is correct.
4. **The cost is small.** §2.7: the entire canon under management is
   69 753 B; a full snapshot of every canon write to date is ≈ 273 KB
   uncompressed, against a 468 KiB pack. Storage is not the objection.
5. **It would be strictly BETTER at the thing that actually loses data.**
   A ledger-side record of what self-learn last wrote catches a
   *committed* in-marker hand edit. `git status` cannot (§2.4 item 3).
6. **It is already the shipped posture for user scope**, which has no VCS
   at all (§2.6) and writes `~/.claude/CLAUDE.md` uncommitted today.

**What the framing cannot do, measured — and this is the whole limit.**

The ledger can only ever hold *self-learn's own region*. §2.7: across the
files carrying a managed section, that region is **15.8% of the bytes**
(44 654 of 283 204 across 16 walked files; **18.4%** — 40 627 of 220 842 —
across the 13 that are routable targets rather than worktree checkouts).
The rest is the human's own prose in their own `CLAUDE.md`. **A
ledger-side history is a backup of self-learn's writes, never a backup of
the host's file**, and the two are not the same promise. If a user's only
copy of `~/.config/CLAUDE.md` (72 467 B, of which 2 166 B is ours) is that
file, ledger-side history does nothing for them.

**The honest conclusion.** The user's framing is right about what the git
operations are FOR, right that the ledger is the better home for
self-learn's own integrity record, and right that this does not require a
repo per host. It is not a *replacement* for a host repo where the host
genuinely wants history for the human's own content — but self-learn was
never entitled to demand that on the human's behalf. **Adopt the framing;
scope its promise honestly; keep git available for hosts that want it.**

### 3.3 The recommendation

**Adopt Option 3, with Option 2 as its mechanism.**

Concretely:

1. A host's mode is `git` or `plain`, recorded **once**, in its
   `hosts.yaml` entry, written by `host add --mode`. Absent = `git`, so
   every existing entry and every existing test is byte-unchanged
   (§4.1, `MODE1`/`UN1`).
2. A `config.yaml` key sets the default for *newly registered* hosts,
   parsed with `one_motion_enabled`'s exact fail-closed discipline —
   anything but the literal string `plain` reads as `git` (§4.2,
   `MODE3`). `S-10`'s reasoning carries over verbatim.
3. **The mode rides `TargetSpec.mode`, never the absence of a repo path**
   (§4.1). `host_repo` is renamed `host_path`, and after Phase 2 it is
   never `None` — the sentinel that meant "chezmoi user scope" is retired
   at the root, not worked around.
4. Plain hosts skip `H-g`, `H-h`, `H-i`, `H-k`, degrade `H-j`, and get
   REPLACEMENTS — not omissions — for `H-a` (the `.self-learn-host`
   marker, §4.4), `H-d` (the compile record, §4.5) and `H-f` (a real
   cache-dir lock, §4.3).
5. The compile record is the user's `~/.self-learn` idea, built: for each
   host target, the sha256 of the region the ledger says must be there,
   plus the previous one so an unlanded apply is distinguishable from a
   hand edit (§4.5). It is written **inside the resolution's own ledger
   commit**, so it opens no new failure window (§4.5, B-3). A route against pre-existing marker-bounded content with
   no record yet self-adopts — writing the missing entry and
   proceeding, with one printed notice — only when that content is
   byte-identical to what the compiler would currently render from the
   ledger; anything else still refuses and names `recompile --adopt`
   (§4.5a's seventh row).
6. **User scope becomes a first-class plain host** (Phase 2), and
   `chezmoi_adopt` / `user_scope_dirty_status` are deleted (§4.8).
7. Git hosts stay **byte-identical**, proven by the `UN` group (§5.8).

**Three sentences, for the orchestrator.** The git operations exist for
two things — history and off-machine backup — and everything else in the
host-side surface is scaffolding around the one commit that delivers them;
so make version control a per-host property set once at registration
(`git` default, `plain` opt-in), keep git hosts byte-identical, and give
plain hosts a ledger-side compile record — the user's own
`~/.self-learn` idea — which is *stricter* than `git status` for the
region self-learn owns, because it sees a committed in-marker hand edit
that git cannot. The cost is honest and must be stated in the docs: a
ledger-side record backs up self-learn's 15.8–18.4% of those files and
never the human's remainder. **The two things r1 got wrong and r2 fixes
are mechanism, not measurement:** plain must be a real mode with a real
lock and its own `TargetSpec` field rather than a reuse of the
`host_repo is None` sentinel that already means chezmoi user scope in 17
sites, and the compile record must ride the resolution's own ledger commit
rather than open a second one whose failure would return exit 6 while
asserting, falsely, that nothing was written.

### 3.4 Designs rejected, with the measurement that rejected each

| # | Rejected | Why |
|---|---|---|
| **R-a** | Global-only switch (option 4) | §3.1 — this machine needs both values at once: `claude-skills` (504 commits, remote, 76 self-learn commits) vs `repos/3d-printing` (4 commits, no remote, whitelist `.gitignore`) |
| **R-b** | Auto-detect by `.git` presence (option 5) | §3.1 — behaviour changing without a decision is the exact failure `S-10` was written against; irreconcilable with Y-17's disclosed-consent contract |
| **R-c** | Try/except at each of the 42 call sites (option 6) | §2.2 / §3.1 — destroys the exit-6-vs-7 distinction `cli.py:1389-1404` depends on |
| **R-d** | N-deep ledger-side snapshot history / an undo verb | §3.2 — the ledger can only hold 15.8–18.4% of those files' bytes; a "history" that silently covers a sixth of the file is worse than an honestly-scoped record. Trigger to revisit: a user asks to restore a *previous* canon state, which today is `supersede + recompile` (S-12) |
| **R-e** | A whole-FILE hash as the plain-mode dirty instrument | §2.4 item 1 — reproduces git's own over-refusal (any out-of-marker edit blocks a write the compiler provably preserves) while adding nothing git does not already do. The region hash is strictly better on both sides |
| **R-f** | A `host set-mode` verb | Q-4, accepted as recommended. The ruling says *"set the behavior once"*. `host remove` explicitly keeps the bucket and its records (`cli.py:1489-1490`), so `remove` + `add --mode` is a lossless round trip. Fenced to `U-verbs` |
| **R-g** | Retiring `git` mode / migrating existing hosts | §1 non-objective 2 |
| **R-h** | Reusing `test_lock_invariant.py` as the plain-write serialization proof | §2.11 — the gate measured that the walker stays GREEN for the mutation that matters |
| **R-i** | **Reusing `host_repo is None` as the plain-mode discriminator** *(NEW in r2, gate B-1/B-2)* | §2.5a — it already means "chezmoi user scope" in 17 sites, five of which would actively misroute a plain project host into the chezmoi branch. Under that reading `_host_phase` also takes NO lock and `slug_for(repo)` has no path to key a lock by, so PLAIN5 would be unreachable |
| **R-j** | **A second ledger commit for the compile record** *(NEW in r2, gate B-3)* | §4.5 — its failure is post-mutation by construction (the record has moved AND host canon is on disk) yet `gitops.commit` raises a plain `GitOpsError`, which `cli._cmd_verb` maps to exit 6 whose documented meaning is *"nothing was written"*. `cli.py:1397-1403`'s own comment pins why 6 is safe: *"only because … every post-mutation git failure is re-raised as HalfWrittenError above"* |
| **R-k** | **Per-BUCKET placement of the compile record** *(NEW in r2, gate M-1 option (b))* | §4.6 — a host target can be written from MANY buckets: `_resolve_target`'s `claude-md` + `scope.startswith("skill:")` branch resolves EVERY skill bucket's route to the single `<skills_root>/CLAUDE.md`. Per-bucket records would give one file two rival records. Per-host keying is forced, so `reconcile` must learn the region instead |
| **R-l** | **Deferring user scope to another unit** *(NEW in r2 — r1's own Q-3 recommendation, OVERRULED)* | §2.6 — `~/.claude` has no VCS, holds the largest managed section on the machine, and is the ONE remaining consumer of the `host_repo is None` sentinel. Leaving it behind means the root cause survives the unit that exists to remove it |

---

## 4. Design

### 4.1 The mode carrier — `TargetSpec.mode`, and the rename

*(RULED, gate B-1/B-2.)*

**`TargetSpec` gains `mode: str`** ∈ `{"git", "plain"}`, and
**`host_repo` is renamed `host_path`.**

*Why the rename is not cosmetic.* `host_repo` on a plain host is not a
repo, and the name is what made `is None` readable as "no VCS" when it
actually means "chezmoi user scope" (§2.5a). Leaving the name in place
leaves the trap in place.

*Why the rename is affordable, measured:*

```
$ grep -rn '\.host_repo' src/self_learn/ | sed 's/:.*//' | sort | uniq -c
     4 report.py
    32 verbs.py
$ grep -rn 'host_repo' ../../ui/src/            # (no output)
```

36 sites, two modules, zero UI. `worker.py`'s five same-named sites are a
different local and are untouched (§2.5a).

**The single resolver, CLI-owned, imported never reimplemented** (the
`canon_read_roots` / `is_repo_root` posture, 09 §11 Y-17 decision 2):

```python
# hosts.py
def host_mode(home: Path | str, path: Path | str) -> str: ...      # "git" | "plain"
def effective_default_mode(home: Path | str) -> str: ...           # config.yaml, fail-closed
def host_slug(home: Path | str, path: Path | str) -> str: ...      # slug_for(), or "user"
```

`host_mode` is the ONLY place a posture is decided. **No site infers a
posture from repo presence, and no site infers user scope from a missing
path** (`MODE9` is the AST criterion that enforces both).

**The 17 sites, re-keyed** (§2.5a's table is the checklist):

- `verbs.py:2596-2600` — the lock ternary becomes a **mode dispatch** to
  `gitops.host_lock(spec.host_path, spec.mode)` (§4.3). It is a real lock
  in both branches.
- `verbs.py:2613` — `if spec.mode == "git" and host_paths:`
- `verbs.py:2999, 3324, 4069, 4178` (+ `3001, 3326` for `old_host_*`) —
  host push guarded on `mode == "git"`, keeping the existing
  `host_sha is not None` conjunct.
- `verbs.py:3276` — the `git show` render, on `mode == "git"`.
- `verbs.py:1952, 2152, 3408` — read `spec.host_path` unconditionally
  (never `None` after Phase 1), so **`_compile_set`'s multi-bucket union**
  (`verbs.py:1907`, the site whose wrong `None` blanks a section — gate
  r2-M3), the rules co-fire count and `_commit_drift_targets` all see a
  plain host.
- `verbs.py:3508` (`commit_drift`) and `verbs.py:4771` (`recompile`) —
  branch on `mode`, not on `None` (§4.7, §4.8).
- `report.py:973, 1480` — drop the `spec.host_path is None` `continue`
  (Phase 2), so a plain host stops vanishing from two report surfaces.
- `verbs.py:3440` — the stale docstring.

### 4.2 `host add --mode`, the config default, and the registry shape

**`hosts.yaml`.** Two shapes:

```yaml
skills_root:
  path: /home/user/repos/claude-skills
  mode: git                       # NEW: optional; absent == git
projects:
- path: /home/user/repos/claude-skills          # absent mode == git
- {path: /home/user/notes, mode: plain}         # NEW
```

**Measured migration facts:**

- `hosts.load_hosts` **already accepts** a project entry as either a bare
  string or a `{path: <str>}` mapping (`hosts.py:145-155`).
- `skills_root` is **scalar-only** today and raises on a mapping
  (`hosts.py:135-138`). It must be widened while still accepting the
  scalar (`MODE8`).
- **The shipped parser silently DROPS unknown project-entry keys**
  *(NEW in r2, gate D-5; the gate ran four fixtures)*: `{path, mode}` is
  ACCEPTED and `mode` is discarded; an arbitrary `banana: 3` is ACCEPTED;
  only a `skills_root` MAPPING raises. **That is a rollback hazard, not a
  crash** — §4.13 and `MODE10`.
- `hosts.save_hosts` (`hosts.py:158`) must emit `mode` **only when it is
  not the default**, so a registry of git-mode hosts round-trips
  byte-identically (`MODE2`; the gate confirmed this is achievable today).
- `hosts.Hosts` gains modes without changing `skills_root: Path | None`
  or `projects: list[Path]`. Builder's choice of representation, under
  `MODE7`: every existing importer must keep compiling and its tests pass
  unedited — including `hosts.canon_read_roots` (`hosts.py:570`),
  `ui/src/self_learn_ui/engine/charter.py:95`, and
  `ui/src/self_learn_ui/proposals.py:241`.

**The verb.**

- `self-learn host add <path> [--skills-root] [--init] [--mode git|plain]`.
- `--mode` absent → `effective_default_mode(home)`.
- `--mode plain --init` is a **usage refusal (64)**, before anything is
  initialized (the `F6` ordering `hosts.host_add` already follows).
- Re-adding an already-registered host with a DIFFERENT `--mode` is a
  **refusal (64)**, naming `host remove` + `host add --mode` (`MODE6`).

**The config key.**

```yaml
hosts:
  default_mode: plain     # ONLY the literal string "plain" enables
```

Parsed by a function shaped exactly like `config.one_motion_enabled`
(`config.py:247-286`): missing file → default, silent; unparseable →
`_warn` + default; non-mapping → `_warn` + default; wrong value →
`_warn` + default. **Fail-closed direction is `git`.**

**The synthetic user slug.** `host_slug(home, path)` returns
`hosts.slug_for(path)` for a registered host and the literal `"user"` for
the user-scope host, whose record is `<home>/compiled/user.yaml` with
`host: (user scope — ~/.claude)` and `mode: plain` *(gate M-5)*.

### 4.3 The plain-host lock — a real one

*(RULED, gate B-1. r1's `slug_for(repo)` cache-dir lock was correct; what
was wrong was pairing it with a design where `host_repo` is `None` and
there is no path to key it by.)*

Measured (`gitops.commit_lock_path`, `gitops.py:383-386`):

```python
    proc = _git(repo, "rev-parse", "--git-common-dir")
    if proc.returncode != 0:
        raise GitOpsError(f"{repo} is not a git repository")
```

A plain host cannot host its own lock file. It still needs one:
`route`'s host phase and `recompile` both do read-modify-write on the
same target file and can run concurrently.

**Design.** A new `gitops.host_lock(path, mode)` context manager and
`gitops.host_lock_path(path, mode)`:

- `mode == "git"` → today's `<git-common-dir>/self-learn.commit.lock`,
  **byte-identical** (`UN8`).
- `mode == "plain"` → `${XDG_CACHE_HOME:-~/.cache}/self-learn/host-<slug>.commit.lock`.

Both share `commit_lock`'s flock body. `commit_lock(home)` — the ledger's
— is unchanged.

*Why the global cache and not the per-home cache:* the sentinel's own
reasoning, `sentinel.py:8-12` — *"GLOBAL, deliberately NOT home-namespaced
(unlike the worker cache, H-4) … any host's sync script must be able to
find it without knowing which ledger home is applying."* A host can be
registered by more than one ledger home; the contended resource is the
host's file.

*Why not `<host>/.self-learn.lock`:* it puts a churning file in the user's
directory.

**`PLAIN5` is the runtime instrument, and it uses two OS PROCESSES, never
threads** *(CORRECTED-r2, gate M-6)*: `gitops.commit_lock` short-circuits
on a module-level `_held_locks: set[str]` (`gitops.py:365`, checked at
`:429-432`) BEFORE it ever calls `flock` — *"Re-entrant within one process
… so a verb may hold it across a helper that acquires it again."* A second
acquisition from another THREAD of the same process takes the
pass-through and never blocks, so a threaded test would pass vacuously.

### 4.4 The H-3 replacement guard — the `.self-learn-host` marker

*(RULED — r1's Q-1 answered: the marker file is adopted.)*

`host add --mode plain` writes `<path>/.self-learn-host`: one line naming
the ledger home that registered it and the ISO timestamp.
`hosts.host_path_problem` requires it for a plain entry, exactly as it
requires a git work tree for a git entry.

It is the structural analogue of `.git`: a marker at the exact registered
path, created by the registering verb, that a hand edit of `hosts.yaml`
cannot conjure. It closes the §2.9 hole rather than narrowing it, it is
destination-agnostic, and it is checked by the same one-predicate gate
everything already routes through. Cost: one dotfile — against the three
`git init`s and two whitelist `.gitignore`s the current requirement has
already cost on this machine (§2.1).

`host_path_problem` keeps its `(home, path, kind) -> str | None` signature
and its three existing refusal texts (`GATE3`); the git-repo clause
becomes mode-conditional and the marker clause joins it.

**The user-scope host is exempt and needs no marker** — it is a host by
construction, not by registration, so there is no hand-editable entry to
guard (`USER3`).

### 4.5 The compile record — inside the resolution's own commit

*(REBUILT-r2, gates B-3, M-4, M-5, D-9. **AMENDED-r3, gates r2-B4 and
r2-M2**: `prev_sha256` is redefined as the OBSERVED pre-flight hash, and
the whole read-compute-write span moves inside the per-host lock.)*

**Location.** `<home>/compiled/<slug>.yaml`, one file per host, slug from
`hosts.host_slug` (§4.2). A tracked, committed ledger file — the "shared
`~/.self-learn` directory" the user named.

**Shape.**

```yaml
host: /home/user/notes
mode: plain
targets:
  CLAUDE.md:
    region: managed          # managed | pointer | reference | script
    sha256: 9f2c…            # what the ledger says the region must be, after this resolution
    based_on_sha256: 41ab…   # the region hash OBSERVED on disk at pre-flight —
                             # the state THIS write is based on; null when the region was absent
    bytes: 1590
    at: 2026-08-27T04:11:52Z
    by: route lrn-4f911239
```

*(RENAMED-r3, gate r2-B4: r2 called the second field `prev_sha256` and
defined it as "what the record said before it" — the previous
**expectation**. §4.5a shows why that contradicts H-2. It is now the
**observed** hash, and the name says so.)*

**Where the four region kinds' bytes come from.** `managed` and `pointer`
are the marker-bounded substrings; `script` is a whole generated file;
`reference` is a whole file whose path is **not** `TargetSpec.target` —
that field is `None` for the reference destination by construction
(`cli._canon_path`'s docstring says so). The path is
**`compilers.reference_target_path(spec.refs_dir, spec.ref_name)`**, which
`_resolve_target`'s reference branch already computes at pre-flight
(`verbs.py:1376`), and both `refs_dir` and `ref_name` ride the spec.
*(ADDED-r3, gate r2-N1: a reader could otherwise conclude the reference
expectation is uncomputable at ledger time. It is not.)*

**When it is written — one commit, no second window.** The record is
written under `_ledger_write`, **before** `_commit_ledger`, and rides the
resolution's OWN pinned commit. There is no second ledger commit and no
`self-learn: compile record …` subject *(r1 had both; gate B-3 rejected
them)*.

*This is only possible because the record is an EXPECTATION, not a
receipt.* The compile is a deterministic function of (the routed record
set, the pre-write host bytes) — `compilers.compile_managed_text` emits
`"\n".join([BEGIN_MARKER, *entries, END_MARKER])` from `_eligible(records)`
alone, independent of the target's current text, and `compile_reference`
appends to bytes we can read before writing. So the region's post-write
hash is computable at ledger-commit time, before the host phase runs.

**Failure semantics.** Because the record write is a ledger mutation inside
`_ledger_write`, a failure of the enclosing `stage`/`commit` is already
`gitops.HalfWrittenError` via the shipped `_commit_ledger`
(`verbs.py:513-537`, gate-confirmed) → **exit 7**, with the printed repair.
**No new exit code, no new code path, and exit 6 keeps its true meaning**
(`REC10`, `M20`, §7).

**Which regions it covers** (`compilers.py:1-115`):

| write shape | bounded by | covered? |
|---|---|---|
| managed section (SKILL.md / CLAUDE.md) | `BEGIN_MARKER`…`END_MARKER` (`compilers.py:158-159`) | **YES** — `region: managed` |
| pointer block | `POINTER_BEGIN_MARKER`…`POINTER_END_MARKER` (`:164-167`) | **YES** — `region: pointer` |
| references append | **no markers at all** — whole file, path from `reference_target_path` | **YES** — `region: reference` |
| hook script | a whole generated file under `<skills_root>/hooks/self-learn/` | **YES** — `region: script` |
| `paths:` frontmatter key | `compilers.apply_paths_frontmatter` | **NO** — it already has its own agreement predicate, `compilers.paths_frontmatter_drift`. §8 OUT-6 |
| new-skill scaffold + `marketplace.json` | whole files, created once | **NO** — §8 OUT-7 |

### 4.5a THE PREDICATE — seven cases, and why `based_on_sha256` is the observed hash

*(AMENDED-r3, gate r2-B4.)*

**The defect r2 shipped.** `_host_phase` catches `_HOST_PHASE_ERRORS`
(`verbs.py:2561`) and returns `(None, None)` after printing *"HOST PHASE
FAILED after the ledger commit … canon is stale, never lost (H-2); run
`self-learn recompile` to repair"* at **exit 0** (`verbs.py:2656-2663`).
An unlanded apply is therefore an ordinary, repeatable outcome, and a
wedged host repeats it every run. Under r2's *previous-expectation*
definition, trace it with no human involved:

| step | disk | record written | verdict next run |
|---|---|---|---|
| clean | A | `{sha A}` | — |
| route r1 | still A (host phase failed) | `{sha B, prev A}` | A == prev → **stale** ✓ |
| route r2 | still A (host phase failed again) | `{sha C, prev B}` | A matches neither C nor B → **`edited`** ✗ |

At that point the route refuses **and `recompile` refuses** — while the
shipped warning text, which this unit does not change, names `recompile`
as the repair, and the offered `recompile --adopt` tells the operator to
"adopt" self-learn's own stale output while the refusal accuses them of a
hand edit. That contradicts doc 13 §8 **H-2** (*"recompile is always safe
and repairs any two-phase interruption"*) and doc 13 §4 item 2 (*drift "is
repaired by recompile, one command, idempotent"*).

**The fix.** `based_on_sha256` is **the region hash observed on disk at
pre-flight** — the state this write is based on — not the previous
expectation. Because pre-flight already REFUSES on `edited` and on
`unknown provenance`, **the observed hash is always self-learn-authored**,
so nothing is laundered by recording it. N consecutive unlanded applies
then keep observing A and keep recording `based_on = A`, so every run
verdicts **stale**, `recompile` alone always repairs, and H-2 holds.

**The table.**

| entry in record | region on disk | verdict | `route` / resolution verbs | `recompile` |
|---|---|---|---|---|
| absent | absent | **fresh** | proceed; record written with `based_on: null` | proceed |
| absent | **present**, bytes == the compiler's expected render from the ledger's current records | **unknown provenance — self-adopt** *(NEW in r9, gate r2-M3)* | **ADOPT automatically**: print one notice line naming the target, then proceed exactly as `fresh` — the record entry is written in the SAME ledger commit as the in-flight route/recompile, no separate step | same — adopt and proceed |
| absent | **present**, bytes differ from that expected render | **unknown provenance — foreign** | **REFUSE** — the H-3-class hazard | **REFUSE**; repair is `recompile --adopt`, named in the refusal text |
| present | hash == `sha256` | **clean** | proceed | no-op |
| present | region absent | **missing** | proceed (drift; this write lands it), recording `based_on: null` | proceed; repairs |
| present | hash == `based_on_sha256` | **stale** — our own apply did not land, N times running | proceed (drift) | proceed; repairs |
| present | hash matches neither | **edited** | **REFUSE** | **REFUSE**; repair is `recompile --adopt` |

**`based_on_sha256` is `null` whenever the pre-flight observation found no
region — the `fresh` and `missing` rows — and otherwise it is the observed
hash.** *(ADDED-r4, gate r3-N1: r3 gave `null` for `fresh` only, leaving
the field undefined on the write that repairs a `missing` region.)*

**The self-adopt row, and why it is safe** *(NEW in r9, gate r2-M3)*.
The "unknown provenance" verdict was previously ONE row that always
refused — correct for genuinely foreign content, wrong for the far more
common case: a host that carries self-learn's own prior output with no
ledger receipt for it, because it was written before this unit existed,
or because its compile record was lost. `_expected_managed_region(home,
spec)` renders what the CURRENT ledger records would produce for this
exact target — the same render the write path itself would produce — and
the comparison runs at PRE-FLIGHT, before the in-flight route's own
record is marked "routed", so it cannot compare a target against itself.
A byte-exact match is proof by construction that the on-disk content is
self-learn's own compiled output: nothing else in the codebase produces
that exact byte string. Only a mismatch is still treated as foreign, and
only a mismatch still refuses. This is what makes every pre-existing
host self-migrate on its first post-upgrade route with no separate
migration step (§4.13) while the H-3 protection against genuinely
foreign content is unchanged for the row that still refuses.

`recompile --adopt [<target>]` is a FLAG on the existing verb, not a new
verb — it re-records the on-disk region as authoritative, the one-command
human decision the `unknown provenance` and `edited` refusals name.
`--force` is deliberately NOT added.

**What it buys over `git status`, mechanically.** A human edits a line
*inside* the markers and commits it. `git status` now prints nothing, so
today's `_abort_if_dirty` passes and the next regeneration destroys the
edit with no warning. The record hashes that same region, gets a number
matching neither `sha256` nor `based_on_sha256`, refuses, and names the
file and the repair. Conversely a hand edit far *outside* the markers
changes `git status` (today: refusal) but not the region hash (plain mode:
no refusal) — safe, because the compiler preserves out-of-marker text
byte-exactly.

**The record is written for `git`-mode hosts and for user scope too**
(`REC4`). It is the only instrument that sees a committed in-marker edit,
which is a real hazard on a git host as well; and one write path is far
easier to keep correct than two. Git mode's *gates* are unchanged —
`paths_dirty` still decides refusals there (`UN2`).

### 4.5b The lock span — where the host lock lives, when it opens, and what the walker sees

*(NEW in r3, gate r2-M2. **AMENDED-r4, gates r3-M1, r3-M2 and r3-M3**: the
lock lives in the CALLEE, it opens before the first ledger mutation, and
the walker needs a detector constant — not the widening argument r3 gave.)*

**The defect r2 shipped.** r2 computed the expectation inside
`_ledger_write` (step d) and wrote the host later under the host lock
(step e), with `_compile_set` (`verbs.py:1907`) **re-reading `resolved/`
at compile time**. If another producer's ledger commit lands in that
window, the region actually written includes their record and hashes to
neither our `sha256` nor our `based_on_sha256` — and the next route reads
**`edited`** and blames a hand edit that never happened. `serve` schedules
producers alongside operator verbs, so this is not hypothetical.

#### The host lock is acquired in the CALLEE, at entry

*(RULED-r4, gate r3-M2. r3's pseudocode put the lock at the caller, which
covers three of five host-write paths.)*

Measured — `_host_phase` (def `verbs.py:2571`) has **six call sites**:

| caller | site |
|---|---|
| `route` | `verbs.py:2962` |
| `route_direct` | `verbs.py:3265` |
| `supersede` | `verbs.py:4154` |
| `recompile` | `verbs.py:4786` |
| `_retirement_host_phase` (def `:2281`) | `verbs.py:2302` |

and `_retirement_host_phase` is itself reached from **`route:2982`**,
**`route_direct:3295`** and **`graduate:4055`**.

**So the lock is taken by `_host_phase` and `_retirement_host_phase`
themselves, at entry — not by their callers.** Every path is then covered
by construction, including `supersede` and `graduate`, which a
caller-side lock would have left writing the host **unlocked**. `_held_locks`
re-entrancy (`gitops.py:365`) makes the retirement path's double
acquisition a pass-through, so `route` → `_retirement_host_phase` →
`_host_phase` is safe.

#### It opens BEFORE the first ledger mutation

*(RULED-r4, gate r3-M3.)* `_ledger_write`'s own docstring pins that the
ledger lock *"must open before the first mutation, not at `commit()`:
`resolve_record` `git mv`s…"*. The same rule now binds the host lock:
**both locks are held before `resolve_record` runs.** Otherwise a host-lock
timeout — `gitops` raises `GitOpsError` after a bounded wait
(`gitops.py:418-427`) — would return **exit 6 asserting "nothing was
written" over a record that has already moved**, which is r2-B3's lie
reintroduced at a new point. §7 row 6 stays true only because of this
ordering.

```
route(record_id):
    with _ledger_write(home):                       # commit_lock(home)   [1st]
        with gitops.host_lock(spec.host_path, spec.mode):   #             [2nd]
            #  ↑ both locks open BEFORE any mutation (r3-M3)
            observed = sha256(region on disk)       # pre-flight read
            expected = compile(...)                 # from the ledger we are about to commit
            resolve_record(...)                     # THE FIRST LEDGER MUTATION (git mv)
            write compile record                    # ledger mutation
            _commit_ledger(...)                     # the resolution's own pinned commit
            _host_phase(...)                        # the host write; re-enters host_lock
                                                    #   as a pass-through (_held_locks)
    push(...)                                       # step f — OUTSIDE both locks
```

**Acquisition order is unchanged — ledger first, host second** — the
pinned `_host_phase` rule (*"Always ledger→host, the one ordering, so
composing them cannot deadlock"*). Nothing is inverted.

**What DOES change is the ledger lock's SCOPE**, and this revises a
deliberate decision. `_ledger_write`'s docstring records that the lock
*"must CLOSE at the commit"*, because the previous whole-verb shape *"held
the ledger lock across the compile, the host phase and the push … so a
wedged remote therefore blocked every other producer for a full TCP
timeout."* The new span covers the compile and the host write but **still
excludes the push**, so the reason for that decision — a network operation
inside the lock — does not apply: every operation in the widened span is
local file I/O plus one local `git commit`. **The cost is real and
bounded:** a concurrent `teach` capture now waits for a local compile
instead of only for a local ledger commit.

#### The walker needs a detector constant, not a widening argument

*(CORRECTED-r4, gate r3-M1. r3 argued that widening a `with` cannot
un-guard anything. True, and beside the point.)*

Measured: `test_lock_invariant.py:94` is
`_LOCKS = ("commit_lock", "_ledger_write")`, and `_is_lock` returns True
only when a call **named** one of those appears in the subtree. §4.3
names the host lock **`gitops.host_lock`** — a name `_LOCKS` does not
contain. Inside `route`/`route_direct` the outer `_ledger_write` `with`
still covers everything, so those stay green; but **every host write not
lexically inside a `_ledger_write` block loses its recognised guard** —
`_host_phase`'s own `with`, `commit_drift` (`verbs.py:3550`),
`_remove_hook_script` (`:1838`), and the retirement leg. Those functions
then enter `requires_lock()`'s fixpoint and their roots — `cli._cmd_host`
among them — fail `test_no_entrypoint_reaches_a_mutation_without_a_lock`.
The spec already carried the measurement that says so (§2.11's fourth row,
§10 item 2) and then asserted green anyway.

**The fix is one name: `_LOCKS` gains `"host_lock"`.** That is a
**detector constant, not a `NOT_REPO_TRUTH` exemption** — it tells the
walker how to recognise a guard, it does not excuse a write from needing
one. `PLAIN6`'s "`NOT_REPO_TRUTH` unchanged" therefore still holds
verbatim. `PLAIN13` is the criterion and `M55` the mutation.

#### The residual, stated rather than left implicit

The host lock is partial by design — `commit_lock_path`'s own docstring
says so for git hosts (*"a human's `git add` in their own repo takes no
lock of ours"*), and the same is true of a human's editor on a plain host.
If a human writes the region during our span, the next run observes a hash
matching neither field and verdicts **`edited`** — a refusal naming
`recompile --adopt`, which is the conservative direction and the correct
one: it *was* a hand edit. **The concurrency this closes is self-learn's
own; the concurrency it cannot close is a human's, and that one fails
loudly rather than silently.**


### 4.6 `reconcile` learns the record — keeping H-5's corollary true

*(RULED, gate M-1. r1 asserted "H-5 unchanged, `reconcile` unchanged" and
put `reconcile.py` on the untouchable list — literally true and materially
false.)*

Measured: `reconcile._is_reconcilable` (`reconcile.py:130-138`) returns
True only for a path whose parent is a discovered BUCKET dir matching
`_RECONCILABLE` (`reconcile.py:78-83`:
`pending/lrn-*.md`, `resolved/lrn-*.md`, `proposals/*.yaml`, `meta.yaml`),
and `ledger.discover_buckets` (`ledger.py:142-160`) globs exactly
`skills/*`, `projects/*`, and `user`. `<home>/compiled/<slug>.yaml` is
inside none of them, so `find_orphans` can never return it — and doc 13 §5
states what that costs: *"a record whose producer wrote it and then failed
to commit it is committed by **nobody, ever** … It sits untracked until a
clone deletes it."*

**Ruling: `reconcile.py` is IN scope** — `_RECONCILABLE` gains the
home-relative shape `compiled/*.yaml` and `_is_reconcilable` learns to
match it against the home rather than only against a bucket.

**Why not put the record inside a bucket instead (gate M-1 option b):**
because a host target can be written from MANY buckets.
`_resolve_target`'s `claude-md` branch for `scope.startswith("skill:")`
resolves EVERY skill bucket's route to the single
`<skills_root>/CLAUDE.md`. Per-bucket records would give one file two
rival records with no arbiter. Per-host keying is forced (R-k), so the
sweep must move to meet it.

`ledger._LAYOUT` (`ledger.py:31`, `("skills","projects","user","telemetry")`)
gains `"compiled"` so a home with only a compiled dir still reads as
bootstrapped rather than `uninitialized`.

### 4.7 `commit_drift` is mode-branched

*(RULED, gate M-2. r1 named `commit_drift` in §2.3's rows and then left it
out of §8 IN with no criterion.)*

`verbs.commit_drift` (`verbs.py:3422`) holds four host-side git calls —
`commit_lock` (`:3550`), `paths_dirty` (`:3552`), `dirty_paths` (`:3559`),
`commit` (`:3569`) — all unguarded by any mode check, plus the
`host_repo is None` chezmoi branch at `:3508`.

**On a plain host, `commit-drift` refuses**, in the verb's own words: there
is no commit to make, because self-learn commits nothing there and the
human's own file is their own to manage. Exit **64**, matching every other
`host`-family refusal (`_cmd_host`'s mapping, **`cli.py:1515-1522`** —
*CORRECTED-r3, gate r2-D5*; the gate confirmed the substantive claim: that
`except` block already maps every `VerbError` from `verbs.commit_drift` to
`EXIT_USAGE`, so `CD1` needs no new dispatch code).
`CD1`/`CD2` are the criteria; §7 gains the row.

The `:3508` chezmoi branch is **deleted in Phase 1**, not rewritten
*(CORRECTED-r3, gate r2-B1: r2 kept it as `if spec.mode == "plain" and
spec.scope_kind == "user":` and justified that with "user scope is the
only plain thing that exists yet", which is false of Phase 1 — Phase 1
ships plain project and skills-root hosts, `PLAIN1`/`PLAIN2` are `[A]`)*.
`commit-drift` on ANY plain host, user scope included, refuses at 64;
there is no chezmoi leg left to take.

### 4.8 User scope is a plain host (Phase 1); chezmoi is deleted wholesale (Phase 2)

*(RULED, gate B-2 + the overruling of r1's Q-3. **REBUILT-r3, gates r2-B1,
r2-B2 and r2-M4**: the mechanism moves to Phase 1, and `chezmoi.py` is
deleted WHOLESALE rather than half-kept.)*

#### 4.8.1 Phase 1 — the mechanism

**User scope becomes a host by construction.** `_resolve_target`'s
`scope == "user"` branch returns
`TargetSpec(..., host_path=<user_claude_md>.parent, mode="plain",
scope_kind="user")` — `~/.claude`, or the parent of whatever
`user_claude_md` override is threaded. It is never registered in
`hosts.yaml`, needs no `.self-learn-host` marker (§4.4), and its mode
cannot be anything but `plain`. Its compile record is
`<home>/compiled/user.yaml` with `host: (user scope — ~/.claude)`.

**`host_path is None` becomes unreachable in Phase 1** (`USER4`) — the
root-cause fix B-2 asked for. No site can infer user scope from a missing
path, because there are no missing paths.

**And the user-scope WRITE moves to the ordinary plain path in Phase 1,
not Phase 2** *(gate r2-B2's root cause)*. `_apply_target`'s user leg
(`verbs.py:2406`) stops calling `chezmoi.compile_user_scope` and calls the
same `compilers.compile_managed_file` path every other plain host uses —
which is what *"user scope becomes a first-class plain host"* means. The
three `preflight_user_scope` call sites (`verbs.py:1183`, `:1274`,
`:4779`) are replaced by the §4.5a predicate, and the `chezmoi_bin`
parameter is dropped from the 42 `verbs.py` signatures that thread it.

**Why this is Phase 1 and not Phase 2, stated because it goes one step
beyond the letter of the r2-B1 ruling** (which moved `USER1` alone):
leaving the write on `compile_user_scope` would give Phase 1 a user scope
carrying `mode == "plain"` whose gate and whose write are both still
chezmoi's — a mode that does not control behaviour, which is the hybrid
the gate would flag next. `USER1`–`USER6` therefore all become `[A]`.

**Three consequences that must be specified, not discovered:**

1. **The user route now yields a `SectionResult`, not a
   `UserScopeResult`.** `cli._reports_no_change` (`cli.py:1105`) and
   `cli._outcome_state` (`:1156`) both branch on
   `isinstance(..., UserScopeResult)`; those branches become dead. They
   still compile (the class exists until Phase 2), and `SectionResult`
   carries `.changed`, which `_reports_no_change`'s generic `getattr` leg
   already handles. `USER7` pins that the user envelope is unchanged, and
   `PLAIN3`'s mode-keyed `wrote_uncommitted` is what keeps `USER6` true.
2. **`chezmoi.compile_user_scope` loses its only caller in Phase 1** and
   becomes dead module surface until Phase 2 deletes it. That is stated,
   not hidden: `CHEZ0` `[A]` asserts zero callers at the end of Phase 1.
3. **The Phase-1 test disturbance is measured, not estimated — and it is
   larger than one file.** §2.10b is the census: **42 `chezmoi_bin` kwarg
   sites across five test files (23 of them outside
   `test_a2_rules_local.py`)**, **87 chezmoi-mentioning test functions
   across 20 files**, and **6 of `test_commit_drift.py`'s 18 functions
   exercising the user leg §4.7 deletes**. Phase 1 edits or rewrites the
   subset whose behaviour it changes; `S3` requires each to be named
   individually. This is the largest single cost of putting the write move
   in Phase 1, and it is still the reason to do it once rather than twice.
   *(CORRECTED-r4, gate r3-B1: r3 added "the rest of the 343 CLI-test hits
   are Phase 2's", which the `chezmoi_bin` census falsifies. That sentence
   is withdrawn.)*

#### 4.8.2 Phase 2 — `chezmoi.py` is deleted wholesale

*(RULED, gate r2-B2. r2 kept `compile_user_scope` and the capability
probes "because they still serve the user-scope write"; §4.8.1 removes
that caller, so the stated reason is gone, and gate r2-M4 measured that
the kept function would have been left calling a deleted symbol —
`compile_user_scope`'s `offer_adopt` branch calls `adopt_command(target)`
at `chezmoi.py:311`, and r2 deleted `adopt_command` at `:260`. Half-keeping
a module whose retirement is already decided produces exactly that.)*

**`plugins/self-learn/cli/src/self_learn/chezmoi.py` is deleted.** Its
basis: chezmoi was retired 2026-07-24; `chezmoi managed` is empty and
`chezmoi apply` is a verified no-op; `~/.claude` is not a git repo (§2.6);
and the verb assessment measured **0 uses of `chezmoi-adopt` in 380 ledger
commits**.

**The deletion list is a CENSUS, not a memory** — §2.10a carries it in
full. Everything it names goes, including the four sites r2 never
mentioned and that gate r2-B3 found:

- `ui/src/self_learn_ui/routes.py:32` —
  `from self_learn.chezmoi import ADOPT_COMMAND_PREFIX, CHEZMOI_DIRTY_MARKER`,
  a **module-level** import. **Deleting `ADOPT_COMMAND_PREFIX` without
  this is an `ImportError` at UI module load, which errors the whole
  1268-test UI suite and makes `S4` unpassable.**
- `COMMIT_DRIFT_MARKERS` (`routes.py:2062`) becomes
  `(GITOPS_DIRTY_MARKER,)` — it currently unions the chezmoi marker.
- `cli.py:38` (`from .chezmoi import ChezmoiAbort, ChezmoiError,
  UserScopeResult`), `verbs.py:84`, and **`teach.py:75`** (`ChezmoiAbort,
  ChezmoiError`, used in its `:722-723` except tuple). The two exception
  types also sit in `verbs._HOST_PHASE_ERRORS` (`verbs.py:2561`) and in
  `cli._cmd_verb`'s and `_cmd_host`'s except tuples — **four except
  tuples shrink**, which is a behaviour-preserving edit only because
  nothing raises those types once the module is gone (`CHEZ5`).

#### 4.8.3 The UI adopt surface — deleted, replaced by nothing

*(NEW in r3, gate r2-B3. There is no chezmoi to adopt from, so the flow
has no replacement.)*

`ui/src/self_learn_ui/routes.py`: the import (`:32`), the verb label
`"chezmoi-adopt": "Adopt into chezmoi"` (`:74`), the argv branch
(`:167-174`, `argv = ["chezmoi-adopt", target or ""]` — a UI route that
invokes the very CLI verb `CHEZ1` deletes), `_extract_adopt_path`
(`:1989-2002`, which greps stderr for `ADOPT_COMMAND_PREFIX`),
`_adopt_offer_response` (`:2004-2028`), the
`/record/{record_id}/adopt-offer/dismiss` route (`:2030`), the two call
sites at `:1886-1889`, and the comment blocks at `:1401`, `:1906`,
`:1979-1984`, `:2058`.
`ui/templates/`: `partials/adopt_offer.html` (whole file),
`partials/action_bar.html:188-199` (the `kind == "adopt"` branch and its
two buttons, `data-key-action="chezmoi_adopt"` /
`"chezmoi_adopt_decline"`), `partials/evidence.html:46`, and
`detail.html:143-146`.
`ui/src/self_learn_ui/models.py`: the `adopted: bool = True` parameter
(`:305`) and the `if scope == "user" and not adopted:` branch (`:334`).
**Six UI test files** reference the surface — `test_routes.py` (26 hits),
`test_js_dom.py` (11), `test_commit_drift.py` (6),
`test_resolution_evidence.py` (6), `test_proposals.py` (6),
`test_models_detail.py` (4) — including
`test_routes.py::test_chezmoi_adopt` (`:112`) and
`::test_arm_then_confirm_runs_chezmoi_adopt` (`:2912`).

Group **UIC** (§5.11) is the criteria; `S5` reconciles the deletions.


### 4.9 The UI exposes the mode as the consent choice

*(RULED, gate M-3, overruling r1's Q-2 recommendation.)*

The arm rendering's git-init disclosure is **replaced** by a two-option
consent, server-rendered, defaulting to `effective_default_mode(home)`:

- **"Track with git"** — *"initialize a git repository here so self-learn
  can commit each compiled lesson"* (shown with the real `--init` argv
  when `_needs_init(path)`).
- **"Plain"** — *"no repository; self-learn writes canon here and commits
  nothing"*.

`build_host_add_argv(path, *, init: bool, mode: str)` always passes
`--mode` explicitly, so the executed argv is unambiguous.

**Y-17's consent invariant is preserved, not weakened.** `--init`
executes only when the posted choice is `git` AND the confirm-time
re-derivation `_needs_init(path)` still holds. Every mismatch runs the
plain-`add` shape:

- choice `git`, path became a repo root → `--init` dropped, `--mode git`
  registers;
- choice `git`, still not a root → `--init` runs, as disclosed;
- choice `plain` → never inits, whatever the path is;
- a forged `mode=git` on a repo-root path → re-derivation drops `--init`.

The bit still only ever WEAKENS execution relative to what was read.
`_needs_init` keeps its CLI-owned import (`routes.py:33`) and its meaning
(`not is_repo_root(path)`); what changes is which choice consumes it.

`UIM1`–`UIM4` are the criteria, `M20`–`M22` the mutations, and
`HOST_ADD_ERROR_LEAD` and the Y-16 error leg are untouched.

### 4.10 The two cwd probes

`teach.py:268` and `import_memory.py:123` call
`gitops.toplevel(Path.cwd()) or Path.cwd()` to derive the project path
for a capture. On a plain directory `toplevel` returns `None` and the
fallback takes cwd itself. **That already works.** No change, but `UN6`
pins it, because a builder tidying `toplevel`'s callers could easily
break the one thing that already handles a repo-less host.

### 4.11 `claude-md:local` on a plain host

`H-e` (`gitops.check_ignore`, `verbs.py:1068`) exists so a personal
`CLAUDE.local.md` is not published by being tracked. **On a plain host
nothing is tracked and nothing is pushed**, so the hazard cannot occur.
**Ruling: skip the check for plain hosts** (`PLAIN9`).

**The residual, stated rather than buried:** a plain host that a human
*later* `git init`s and pushes would publish an already-written
`CLAUDE.local.md`. That is a user action after the fact, and the honest
response is a one-line note at registration time, not a gate (`PLAIN7`).

### 4.12 Step-by-step, both modes

| step | git mode | plain mode |
|---|---|---|
| (c) pre-flight gate | `_gate_host` → `host_path_problem` → git work tree | `_gate_host` → `host_path_problem` → **`.self-learn-host` marker** (§4.4) |
| (c) dirty check | `_abort_if_dirty` → `paths_dirty` (whole file) | **the §4.5 predicate** against the compile record |
| (c′) host lock OPENS | `host_lock(path, "git")` → `<git-common-dir>/self-learn.commit.lock`, taken INSIDE `_ledger_write` (§4.5b) | `host_lock(path, "plain")` → `…/self-learn/host-<slug>.commit.lock`, same nesting |
| (c″) observe + compute | region hash read off disk; expectation compiled | identical |
| (d) ledger commit | resolution | resolution **+ the compile record, same commit, same lock** |
| (e) compile | identical | identical — same `compilers` code, byte for byte |
| (e) stage + commit | `gitops.stage` + `gitops.commit` | **skipped**; `host_commit_sha = None` |
| (f) host push | `push_if_remote(host_path)` | **skipped**; `host_push = None` |
| (f) host diff render | `git show --format=` | **skipped**; the compile result's own change report renders instead |
| (g) sentinel release | identical | identical |

### 4.13 Migration and rollback

**Migration: none required, and none by hand.** Absent `mode` reads as
`git` (`MODE1`), `save_hosts` omits the default (`MODE2`), the nine
registered hosts keep behaving byte-for-byte (`UN1`). Nothing in
`~/.self-learn` is rewritten by the build itself. A user who wants an
existing host to become plain does `host remove` + `host add --mode
plain` (R-f). **For every host that already carries self-learn's own
compiled output with no compile-record entry — the state every
pre-existing install is in the moment this unit lands, since compile
records did not exist before it — §4.5a's self-adopt row (*NEW in r9,
gate r2-M3*) means the FIRST route or `recompile` against that target
writes the missing record entry automatically, with one printed notice,
and proceeds; there is no separate migration step to run.** `self-learn
doctor`'s drift summary (`selfcheck._check_drift`) names the count of
targets still missing a record so an operator can see it without waiting
for a route to touch every one.

**Rollback, corrected** *(CORRECTED-r2, gate D-5; the gate ran the shipped
parser against four fixtures)*: reverting this unit does **not** make a
`mode: plain` projects entry unreadable. The shipped parser accepts
`{path, mode}` and **silently drops** the `mode` key
(`hosts.py:150-155` checks only
`isinstance(entry, dict) and isinstance(entry.get("path"), str)`); only a
`skills_root` MAPPING raises `HostsError`. **The hazard is therefore a
silent resumption of host commits into a directory the user chose to keep
repo-less — not a crash.** The advice is unchanged and now has a reason:
**remove plain entries with `host remove` FIRST, then revert.**

**`MODE10` does NOT close this hole, and r2's claim that it did is
withdrawn** *(CORRECTED-r3, gate r2-M1)*. The hazard belongs to the
**reverted** parser; hardening the **new** one changes nothing after a
revert — the gate re-ran the four fixtures against the shipped parser and
confirmed `{path, mode}` is still ACCEPTED with `mode` dropped. `MODE10`'s
real value is forward-compatibility, which §11's sibling row already
states correctly, and it is kept for that.

**The only mitigation is procedural, so the runbook carries it as a
numbered procedure** (§12.4): **step 1 is `self-learn host list`** —
which `MODE11` requires to show each host's mode — to enumerate the plain
hosts; **step 2**, for each one, either `git init` it (making the reverted
code's git-mode assumption true) or `self-learn host remove` it; **step
**3**, commit or delete the `<home>/compiled/*.yaml` files, then revert.
They are **inert** to the reverted code — nothing in it reads them — **but
also UNSWEPT** by it: the revert takes `compiled/*.yaml` out of
`_RECONCILABLE`, so an uncommitted one becomes exactly the H-5-corollary
orphan §4.6 exists to prevent. *(CORRECTED-r4, gate r3-D6: r3 said "need
no cleanup", here and in §12.4.)*

---

## 5. Criteria

### 5.0 The two phases, and the proof Phase 1 lands alone

*(REBUILT-r3, gate r2-B1: r2's boundary did not hold — the
`host_repo`→`host_path` rename broke `report.py`'s four reads while §9
excluded `report.py` from Phase 1, and `host_lock(None, mode)` would have
called `slug_for(None)` for a user-scope route because `USER1`/`USER4`
were `[B]`.)*

- **Phase 1 [A] — the whole mechanism.** The mode, the compile record, the
  marker, the lock span, plain project/skills-root hosts, **and user scope
  as a plain host end to end** (§4.8.1). Groups: MODE, REC, GATE, PLAIN,
  RCN, CD, UIM, UN, **USER**, **RPT**, DOC, S1–S3.
- **Phase 2 [B] — the chezmoi deletions only.** `chezmoi.py` wholesale,
  the CLI adopt surface, the UI adopt surface. Groups: CHEZ1–CHEZ6, UIC,
  S4–S5. (**`CHEZ0` is `[A]`** — it asserts the Phase-1 precondition that
  makes the Phase-2 deletion a removal of dead code, so it is filed with
  its group but gated with Phase 1.)

**94 criteria — 82 [A], 12 [B] — across 14 groups. 60 mutations. *(r9: MODE6a added, gate r2-M4; r10: M25 split into M25a/M25b, gate r3-N5.)***

#### Can Phase 1 land alone? — re-run over every [A] criterion

The gate's leg-(a) and leg-(b) defects are closed by moving three things
into Phase 1. Checked criterion by criterion:

| what Phase 1 needs | is it in Phase 1 now? |
|---|---|
| `report.py`'s four `.host_repo` reads (`:973, 975, 1480, 1482`) survive the rename | **YES** — `report.py` joins §9's Phase-1 list, and `RPT1`/`RPT2` are `[A]`. Without this `S1` (suite rc 0) reddens on a Phase-1-only build |
| `host_lock(spec.host_path, spec.mode)` never receives `None` | **YES** — `USER1`/`USER4` are `[A]`, so `host_path` is never `None` after Phase 1. `slug_for(None)` cannot be reached |
| `MODE9` `[A]` forbids retaining a `host_path is None` user-scope guard | **YES, and consistently** — `USER4` `[A]` is what makes `MODE9` satisfiable rather than contradictory. In r2 the forbidding criterion was `[A]` and the enabling one `[B]` |
| the `commit_drift` `:3508` chezmoi branch has a Phase-1 answer | **YES** — deleted, not rewritten (§4.7). r2's rewrite leaned on "user scope is the only plain thing that exists yet", false of a phase that ships `PLAIN1`/`PLAIN2` |
| `_outcome_state` / `_reports_no_change` still compile | **YES** — `UserScopeResult` still exists in Phase 1; its branches merely go dead (§4.8.1 item 1) |
| every module Phase 1 imports still resolves | **YES** — Phase 1 deletes nothing from `chezmoi.py`, so `teach.py:75`, `cli.py:38`, `verbs.py:84` and `ui/routes.py:32` all still import |
| both suites can RUN at the end of Phase 1 | **YES** — `S1`/`S2` are `[A]`. The edits to existing tests span **six CLI files plus `test_resolution_evidence.py`, `test_m2_verbs.py`, `test_compilers.py`, `test_retirement_cleanup.py` and the NINE one-hit files** *(CORRECTED-r5, gate r4-D3: r4 said eight)*, censused in §2.10b *(CORRECTED-r4, gate r3-B1: r3 claimed "the only edits … are the 36 … in `test_a2_rules_local.py`", which the `chezmoi_bin` kwarg census (23 sites outside that file) and `test_commit_drift.py`'s six user-leg tests both falsify)*. `S3` reconciles every one by name |

**Phase 2 is then a pure deletion** with no mechanism left to invent —
which is what makes it a phase boundary rather than a deferral.

**DONE WHEN (builder-visible).** *Phase 1:* `host add --mode plain`
registers a non-repo directory and writes `.self-learn-host`; a `route`
into it writes canon, writes a compile record in the SAME ledger commit,
commits nothing in the host, and reports `wrote_uncommitted`; a user-scope
route does the same with zero chezmoi calls; a hand edit inside the
managed markers refuses that route even after the human commits it, while
two consecutive failed host phases keep verdicting `stale` and
`recompile` repairs them; a `route` into any of the nine existing hosts
produces a byte-identical commit to what `50fa815` produces.
*Phase 2:* `import self_learn.chezmoi` raises `ModuleNotFoundError`;
`self-learn chezmoi-adopt` no longer exists; the UI has no adopt offer;
both suites green.


### 5.1 MODE — the setting (Phase 1)

- **MODE1** **[A]** A `hosts.yaml` with **no** `mode` key anywhere loads
  with every host in `git` mode. **Check:** the real registry's text,
  copied into a fixture, through `load_hosts` + `host_mode`; all nine
  report `git`. **Mutation M1.**
- **MODE2** **[A]** `save_hosts(load_hosts(h))` on a mode-free registry is
  **byte-identical** to the input. **Check:** round-trip the real
  registry's text (fixture copy). *(The gate confirmed this round-trip is
  byte-identical today, so the criterion is achievable.)* **Mutation M2.**
- **MODE3** **[A]** `effective_default_mode` returns `plain` **only** for
  the literal YAML string `plain` under `hosts.default_mode`. Every other
  input — missing file, unparseable, non-mapping top level, non-mapping
  section, `"Plain"`, `"PLAIN"`, `true`, `null`, `1`, a list — returns
  `git`; a present-but-wrong value WARNs on stderr. **Mutation M3.**
- **MODE4** **[A]** `host add --mode plain --init` exits **64** naming
  both flags, leaves the path **not** a repo, **not** marked, and **not**
  registered. **Mutation M4.**
- **MODE5** **[A]** `test_hosting.py::test_cli_without_flag_still_refuses_non_repo`
  and `::test_without_init_behavior_byte_unchanged` pass **unedited**.
  **Mutation M5** (make `plain` the built-in default) → both red.
- **MODE6** **[A]** `host add` on an already-registered host with a
  *different* `--mode` exits **64**, names the repair, and does **not**
  rewrite `hosts.yaml` (file sha256 unchanged) or add a ledger commit
  (`HEAD` unchanged). **Mutation M6.**
- **MODE6a** **[A]** *(NEW in r9, gate r2-M4.)* `host add` on an
  already-registered **plain**-mode host with the **SAME** `--mode`
  re-asserts the `.self-learn-host` marker when it is missing -- printing
  "marker restored" -- instead of returning early with the marker still
  absent. The named repair in `GATE2`'s and `MODE6`'s refusal text
  (`host remove` + `host add --mode`) must actually repair when run in
  the already-registered state; before this it silently no-op'd.
  **Check:** delete the marker file on an already-registered plain host,
  run `host add --mode plain` again, assert the marker file exists and rc
  is 0; a control run with the marker already present asserts the repair
  line is NOT printed (a true no-op, not a rewrite every time).
- **MODE7** **[A]** Every existing consumer of `Hosts.skills_root` /
  `Hosts.projects` compiles and passes unedited — including
  `hosts.canon_read_roots`, `ui/…/engine/charter.py:95`, and
  `ui/…/proposals.py:241`. **Check:** an AST test enumerating every
  attribute access on a `Hosts` instance across BOTH `src` trees,
  asserted against the pre-existing set; **positive control in the same
  test** — the same enumeration for a name known absent returns zero.
- **MODE8** **[A]** `skills_root` accepts BOTH the scalar form and
  `{path, mode}`, rejecting every other shape with the existing
  `HostsError` wording pattern. **Mutation M7.**
- **MODE9** **[A]** **No site decides a posture except `hosts.host_mode`,
  and no site infers user scope from a missing path.** **Instrument:** an
  AST sweep over `cli/src/self_learn/` for (a) any comparison of a
  `TargetSpec` attribute to `None` used to select a chezmoi/user branch,
  and (b) any call to `hosts._is_git_repo` / `is_repo_root` outside
  `hosts.py` and the `--init` path. **Positive control:** the same sweep
  run against `50fa815`'s tree must report the **five branch-selecting
  sites** — `verbs.py:1952, 2152, 3408, 3508, 4771` — plus
  `report.py:973, 1480`, so an empty result cannot be an empty search.
  *(CORRECTED-r3, gate r2-D1: r2's control said "the 17 sites", which this
  sweep cannot return — the push/show guards at `2999, 3001, 3276, 3324,
  3326, 4069, 4178`, the stage guard at `2613` and the docstring at `3440`
  select no user/chezmoi branch. A control that cannot reproduce fails on
  correct code and invites weakening.)* **Mutation M8.**
- **MODE10** **[A]** `load_hosts` **REFUSES** an unknown key in a project
  entry or a `skills_root` mapping, with the existing `HostsError`
  pattern. **Check:** the gate's own four fixtures —
  `{path, mode}` accepted, `{path, banana}` refused, a bare string
  accepted, a `skills_root` mapping with an unknown key refused.
  **Mutation M9.** *(CORRECTED-r3, gate r2-M1: r2 claimed this "turns
  gate D-5's silent-drop hazard into a closed hole". It does not — that
  hazard is the REVERTED parser's, and this hardens the new one. Kept for
  forward-compatibility; §4.13 carries the real, procedural mitigation.)*

- **MODE11** **[A]** `self-learn host list` shows each host's **mode**.
  **Check:** a registry with one git and one plain project host renders
  both modes; and for a registry with **no** plain entries the output is
  byte-identical to `50fa815`'s (`UN4`). This is the surface §12.4's
  rollback procedure step 1 depends on, so it is a criterion, not a
  courtesy. **Mutation M46.** *(NEW in r3, gate r2-M1.)*

### 5.2 REC — the compile record (Phase 1)

- **REC1** **[A]** After a route, `<home>/compiled/<slug>.yaml` carries an
  entry for the target whose `sha256` equals
  `hashlib.sha256(<region bytes read back off disk>).hexdigest()`.
  **Mutation M10.**
- **REC2** **[A]** The predicate returns `edited` for a hand edit INSIDE
  the markers that has been **committed** in the host — i.e. where
  `gitops.paths_dirty` returns `False`. **Check:** one test that edits
  in-marker, `git add`+`git commit`s in the host, asserts
  `paths_dirty is False` **and** the verdict is `edited`, in the same
  body. **This is the criterion that justifies the whole record.**
  **Mutation M11.**
- **REC3** **[A]** The predicate returns `clean` for a hand edit OUTSIDE
  the markers, and a subsequent regeneration preserves that edit
  byte-exactly. **Mutation M12** (hash the whole file) → red.
- **REC4** **[A]** The record is written for **git**-mode hosts as well as
  plain. **Check:** two routes (git host, plain host) each leave an entry.
  *(User scope joins this in Phase 2 — `USER5`.)* **Mutation M13.**
- **REC5** **[A]** **The seven-case predicate of §4.5a is implemented
  exactly.** **Check:** seven fixtures, one per row, asserting the verdict
  string and, for the two refusing rows, exit 1 plus a byte-unchanged
  region on disk. Named explicitly: `entry absent + region absent` →
  proceeds (**this is `PLAIN2`'s first route into a fresh host, and r1's
  REC5 wrongly refused it**); `entry absent + region present, bytes ==
  the compiler's expected render` → **self-adopts and proceeds** (*NEW in
  r9, gate r2-M3* — one printed notice, the record entry written in the
  same ledger commit); `entry absent + region present, bytes differ` →
  still refuses. **Mutations M14, M15, M16.** **Self-adopt mutation:**
  disabling the byte-match branch turns the self-adopt fixture RED while
  leaving the still-refuses fixture GREEN, proving the two sub-cases are
  independently reddenable (gate r2-M3's own probe).
- **REC6** **[A]** `based_on_sha256` distinguishes **stale** from
  **edited**. **Check:** write, then restore the region to the bytes the
  write was based on, assert `stale` and that `recompile` proceeds; then
  set the region to third-party bytes, assert `edited` and that
  `recompile` REFUSES. **Mutation M17** (drop the field) → red, and
  `recompile` can no longer repair an unlanded apply.
- **REC13** **[A]** **Two consecutive host-phase failures still verdict
  `stale`, and `recompile` (without `--adopt`) repairs.** **Check:** force
  `_apply_target` to raise a member of `_HOST_PHASE_ERRORS` twice in a
  row; after each run assert exit **0** with the shipped "HOST PHASE
  FAILED … run `self-learn recompile` to repair" warning; after the second,
  assert the verdict is `stale` (not `edited`) and that a plain
  `recompile` lands the region. **Mutation M47:** define the second hash
  as the previous *expectation* instead of the observed pre-flight hash →
  the second run verdicts `edited` and `recompile` refuses → red.
  *(NEW in r3, gate r2-B4. This is the H-2 contradiction r2 shipped; the
  mutation is r2's own definition, kept so it cannot come back.)*
- **REC12** **[A]** *(EXTENDED-r4, gates r3-M2 and r3-M3.)* The host lock
  is acquired **in the callee, at entry**, and **before the first ledger
  mutation**. **Check:** an AST test asserting (a) `_host_phase`
  (`verbs.py:2571`) opens a `gitops.host_lock(spec.host_path, spec.mode)`
  `with` as its **first statement**; **`_retirement_host_phase`
  (`:2281`) takes NO lock of its own** — its first statement is
  `if retirement.spec is not None:` and it holds no host path, so both of
  its branches delegate to a callee that locks (`_host_phase` at `:2302`,
  `_remove_hook_script` at `:2317`, whose own lock at `verbs.py:1838`
  becomes `host_lock`) and its third path writes nothing (the
  bulk-acknowledge door) *(CORRECTED-r5, gate r4-M1: r4 required a lock at
  a function that has no host to lock at entry — an AST check written
  literally would fail a correct implementation)*; (b) **all six
  `_host_phase` call sites plus `_remove_hook_script` are covered** —
  `route:2962`,
  `route_direct:3265`, `supersede:4154`, `recompile:4786`, and
  `_retirement_host_phase:2302` reached from `route:2982`,
  `route_direct:3295` and **`graduate:4055`**; (c) the `host_lock` `with`
  **precedes the first mutating call** (`resolve_record` / `Record.write`)
  in the enclosing `_ledger_write` block; (d) the push call is lexically
  OUTSIDE both; **(e) the ledger lock is acquired BEFORE the host lock, on
  every host-writing verb** (*NEW in r9, gate r2-M1* — `supersede` and
  `graduate` open `with _ledger_write(home), <host lock>:` as ONE combined
  statement, ledger item first, matching `route`'s and `route_direct`'s
  shape; a fifth check instruments the acquisition ORDER itself, not just
  presence, by patching both lock context managers to append to a shared
  list and asserting ledger-before-host for every leg). **Mutation M48:**
  compute the expectation before taking the host lock → red. **Mutation
  M57:** move the lock from `_host_phase` to its callers →
  `supersede`'s and `graduate`'s host-write tests redden. **Mutation
  M58:** acquire the host lock AFTER `resolve_record` → a host-lock
  timeout leaves the record moved while dispatch returns exit 6 → red.
  **Mutation, leg (e):** swap `with _ledger_write(home), <host lock>:` to
  `with <host lock>, _ledger_write(home):` in one verb → red, that verb
  only. **Runtime probe:** two verbs writing the same host and ledger
  concurrently (a holder subprocess plus the foreground call, with
  `gitops.COMMIT_LOCK_TIMEOUT` patched low) complete without either
  hitting `COMMIT_LOCK_TIMEOUT` — proof the fixed order does not
  deadlock two real OS processes against each other.
- **REC7** **[A]** The record covers exactly the four region kinds
  `managed`, `pointer`, `reference`, `script`. **Check:** **three routes
  covering the four region kinds** *(CORRECTED-r2, gate D-11)* —
  `claude-md` (managed), `reference` (which also writes a pointer), `hook`
  (script). **Positive control:** a `rules` route leaves **no** `paths`
  region. **Mutation M18.**
- **REC8** **[A]** The record round-trips foreign keys (`ruamel`
  `typ="rt"`, the discipline `records.py` and `hosts._yaml()` already use).
- **REC9** **[A]** **The record rides the resolution's OWN ledger commit.**
  **Check:** after a route, `git -C <home> log --format=%s` contains
  exactly the resolution subject and **no** `compile record` subject, and
  `git -C <home> show --stat HEAD` names both the record file and the
  `<home>/compiled/…` path. **Mutation M19** (write it as a second commit)
  → red.
- **REC10** **[A]** A failure of the enclosing `stage`/`commit` after the
  record file is written returns **exit 7** with the half-written repair
  text, never exit 6. **Check:** monkeypatch `gitops.commit` to raise
  `GitOpsError` on the ledger; assert rc == 7 and that
  `cli._report_half_written`'s text was printed. **Mutation M20.**
- **REC11** **[A]** `recompile --adopt` re-records the on-disk region and
  clears an `edited`/`unknown provenance` refusal; **`--force` does not
  exist.** **Check:** rc 0, the entry's `sha256` now equals the on-disk
  region, and `argparse` rejects `--force`. **Mutation M21.**

### 5.3 GATE — the H-3 replacement (Phase 1)

- **GATE1** **[A]** `test_hosting_fixes.py::test_typod_skills_root_never_writes_canon_outside_a_repo`
  passes **unedited**.
- **GATE2** **[A]** The same property for a plain host: a hand-edited
  `hosts.yaml` naming a plain path **without** `.self-learn-host` is
  refused in PRE-FLIGHT — no canon file created, ledger `HEAD` unchanged.
  **Mutation M22.**
- **GATE3** **[A]** `host_path_problem` keeps its three existing
  refusal TEXTS byte-identical; `test_host_add_refuses_the_ledger_home`,
  `test_host_pointing_at_the_ledger_itself_is_refused`,
  `test_refusal_names_rebind` pass unedited, plus plain-mode
  parametrizations of the first two. *(NARROWED in r9, gate r2-N2: r1's
  claim that the signature itself — `(home, path, kind) -> str | None` —
  stays fixed is withdrawn. `host_path_problem` gains keyword-only
  `mode: str | None = None` and `check_marker: bool = True` so `host_add`
  can finally reuse it for the git-repo and ledger-home checks instead of
  duplicating their refusal text — the "cannot be reused" justification
  r1 gave for the duplication no longer holds. Every existing caller,
  keyword-free, is unaffected by construction; only the TEXTS were ever
  the load-bearing claim.)*
- **GATE4** **[A]** `host list` shows a broken PLAIN entry marked broken
  (the lenient-list contract
  `test_host_list_shows_a_broken_entry_marked_broken` pins for git).
- **GATE5** **[A]** `.self-learn-host` names the registering ledger home
  and an ISO timestamp, and `host remove` **leaves it in place** (removing
  it would silently invalidate a re-add and is not what `remove`
  documents: *"the bucket and its records are untouched — only the compile
  gate closed"*). **Mutation M23.**

### 5.4 PLAIN — plain mode end to end (Phase 1)

- **PLAIN1** **[A]** `host add --mode plain <plain-dir>` succeeds against a
  non-repo directory with no parent repo, runs no `git init`, and writes
  `.self-learn-host`.
- **PLAIN2** **[A]** A `route` into a plain host writes the managed
  section; `host_commit_sha is None`; the host contains no `.git`; the
  ledger has exactly the resolution commit and no others.
- **PLAIN3** **[A]** That route's envelope reports
  `outcome_state == "wrote_uncommitted"`, **not** `"unknown"`.
  **Mutation M24** — *the current code; the gate confirmed the predicate
  falls through.*
- **PLAIN4** **[A]** No git subprocess runs against a plain host during a
  route. **Check:** monkeypatch `subprocess.run` and `gitops._git` to
  record `(repo_arg, argv)`; assert **zero** entries resolving inside the
  plain host. **Positive control in the same test:** the identical
  instrument over a git-mode route records a non-zero count. **Mutation
  M25a** (drop the control) → the control leg fails, but this is a
  META-ROW — deleting the test's own positive control is not
  independently reddenable (§6, r10, gate r3-N5). **Mutation M25b**
  (a stray `subprocess.run(["git", "status"], cwd=...)` inserted into
  `_host_phase`'s plain branch) → RED, and is the actual proof that this
  criterion's instrument catches a real hole.
- **PLAIN5** **[A]** Two **OS processes** entering the plain-host lock are
  serialized: the second observably blocks until the first releases, and
  the file contains exactly one complete regeneration. **Never threads** —
  `gitops._held_locks` (`gitops.py:365`, checked `:429-432`) makes a
  same-process re-acquire a pass-through. **Mutation M26.**
- **PLAIN6** **[A]** `test_lock_invariant.py` green and `NOT_REPO_TRUTH`
  **not grown**. **Check, cwd-pinned** *(CORRECTED-r5, gate r4-D1's audit
  — see §5.13)*: run from `plugins/self-learn`,
  `git diff 50fa815 -- cli/tests/test_lock_invariant.py` must be
  **NON-EMPTY** (`PLAIN13` edits `_LOCKS`, so an empty diff means the
  pathspec did not resolve). **Permitted hunks, r11 (gate r1):** the
  one-name `_LOCKS` change at `:94` (`PLAIN13`); Phase 2's
  `NOT_REPO_TRUTH` **shrink by three** dead exemptions for symbols
  `chezmoi.py`'s deletion removes — `chezmoi._run`,
  `chezmoi.compile_user_scope`, `chezmoi.preflight_user_scope` — kept
  out by `test_lock_invariant.py`'s own
  `test_the_exemption_list_cannot_rot` (a dict entry naming a function
  that no longer exists fails it); and `_ARGV_FOR`
  losing its `_cmd_chezmoi_adopt` entry (the verb itself is `CHEZ1`'s
  own deletion). **No other hunk is permitted** — the rule stays "not
  grown", never "unchanged": a shrink that removes only symbols this
  same unit deleted is compliant; any other edit to either dict is not.
- **PLAIN7** **[A]** `host add --mode plain` prints a consent line naming
  what plain mode does NOT do (no commits, no push, no off-machine backup
  of the host's own file) **and** the `claude-md:local` residual of §4.11,
  alongside the existing consent line (`cli.py:1462-1465`), which is
  preserved.
- **PLAIN8** **[A]** `--selftest`'s `drift` row reports on plain hosts:
  the entry-marker check unchanged, plus the region verdict; a host with
  no compile record yet SKIPs with a distinguishable reason. **Check:**
  four fixtures (no record; clean; stale; edited) asserting four distinct
  rendered strings. **Mutation M27.**
- **PLAIN9** **[A]** `claude-md:local` on a plain host does not call
  `gitops.check_ignore`. **Positive control:** the same route on a git host
  still calls it and still refuses. **Mutation M28.**
- **PLAIN10** **[A]** `self-learn push` skips plain hosts silently and
  without calling `unpushed_commits` on them — no `skipping <path>` line
  (that LOUD skip is for *broken* hosts, `verbs.py:4594`). **Mutation M29.**
- **PLAIN11** **[A]** Hook retirement on a plain host removes the script by
  `Path.unlink`, with no `git rm` and no commit. **Check:** the `PLAIN4`
  instrument plus `script.exists() is False` — the outcome alone is not
  enough, because `_remove_hook_script` swallows a `GitOpsError` into a
  warning (`verbs.py:1853-1860`). **Mutation M30.**
- **PLAIN13** **[A]** **`test_lock_invariant.py`'s `_LOCKS` gains exactly
  one name, `"host_lock"`** (`test_lock_invariant.py:94`), and the walker
  then recognises `with gitops.host_lock(...)` as a guard. **Check:** the
  tuple's members are `("commit_lock", "_ledger_write", "host_lock")` — no
  other change; and `test_no_entrypoint_reaches_a_mutation_without_a_lock`
  is green with `commit_drift`, `_remove_hook_script` and the retirement
  leg reachable from their roots. **`NOT_REPO_TRUTH` is NOT touched** —
  this is a detector constant, so `PLAIN6` still holds verbatim.
  **Mutation M55:** revert the constant → those roots redden.
  *(NEW in r4, gate r3-M1.)*
- **PLAIN12** **[A]** The plain-host lock path is
  `${XDG_CACHE_HOME}/self-learn/host-<slug>.commit.lock` and the git-host
  lock path is byte-identical to `50fa815`'s. **Mutation M31.**

### 5.5 RCN — reconcile (Phase 1)

- **RCN1** **[A]** An uncommitted `<home>/compiled/<slug>.yaml` is found by
  `reconcile.find_orphans` and committed under the pinned reconcile
  subject. **Mutation M32** (leave `_RECONCILABLE` unchanged) → red.
  *(The gate measured that this is impossible today.)*
- **RCN2** **[A]** `reconcile` still refuses to guess at a staged deletion
  or rename (`_BLOCKING_CODES`) for a compiled record, exactly as for a
  bucket record.
- **RCN3** **[A]** A home containing only `compiled/` reads as
  bootstrapped, not `uninitialized` (`ledger._LAYOUT`). **Mutation M33.**
- **RCN4** **[A]** `reconcile`'s existing tests pass unedited.

### 5.6 CD — commit-drift (Phase 1)

- **CD1** **[A]** `host commit-drift <id>` against a plain host refuses in
  the verb's own words at exit **64**, calling no git in the host.
  **Mutation M34.**
- **CD2** **[A]** *(r6, gate r5-N2: the six rewritten tests KEEP their original names deliberately — `UN3`(i)'s name-set diff is what proves nothing was dropped; a name such as `test_dirty_dotfiles_goes_through_chezmoi_git` now asserts the 64 refusal, and its docstring says so.)* *(RESTATED-r4, gate r3-B1: r3 required all 18 tests
  unedited while §4.7 deletes the leg 6 of them exercise.)*
  `host commit-drift` against a **git** host is byte-unchanged: its four
  host-side git calls still run and **`test_commit_drift.py`'s 12
  git-mode tests pass byte-unedited**. Its **6 user/chezmoi-leg tests are
  REWRITTEN** to assert the plain-host refusal (`CD1`, exit 64) and are
  named individually in the build report:
  `test_dirty_dotfiles_goes_through_chezmoi_git` (`:191`),
  `test_drift_refused_no_commit` (`:210`),
  `test_clean_dotfiles_refused` (`:226`),
  `test_dry_run_reports_repo_and_files_writes_nothing` (`:237`),
  `test_chezmoi_dirty_message_carries_the_extracted_marker` (`:274`),
  `test_commit_drift_drift_exit_64` (`:329`). **Mutation M56:** leave any
  of the six asserting a chezmoi commit → red.

### 5.7 UIM — the UI consent (Phase 1)

- **UIM1** **[A]** *(RESTATED-r8, gate r1 fold N-7: "byte-identical to
  `50fa815`'s rendering" is unachievable once §4.9's two-option consent
  — new radio buttons `50fa815` never had — replaces the git-init
  disclosure outright. The property actually held, and actually tested,
  is restated below; no test changed.)* With `hosts.default_mode:
  plain`, the arm rendering for a non-repo path pre-selects the
  **Plain** radio and shows **no git-init disclosure**; with the key
  absent (`MODE1`'s own default, `git`) it pre-selects the **Track with
  git** radio and shows the disclosure text — carrying the real
  `--init` argv — exactly when `_needs_init(path)` holds. **Mutation
  M35.**
- **UIM2** **[A]** `build_host_add_argv` always emits `--mode`, and emits
  `--init` **only** when the posted choice is `git` AND `_needs_init(path)`
  holds at confirm time. **Check:** the four Y-17 mismatch cases of §4.9,
  each asserting the exact argv. **Mutation M36.**
- **UIM3** **[A]** A forged `mode=git` posted for a path that IS a repo
  root runs `["host","add","--mode","git",path]` — no `--init`. The
  weaken-only property is preserved. **Mutation M37.**
- **UIM4** **[A]** The Y-16 error leg is untouched: `HOST_ADD_ERROR_LEAD`,
  the `[data-verb-error]` marker and the dismiss-via-disarm route are
  byte-unchanged, and the existing registration tests
  (`ui/tests/test_registration_wipe.py`, `ui/tests/test_routes.py`) pass
  with additions only.

### 5.8 UN — git-mode hosts are byte-identical (Phase 1)

- **UN1** **[A]** A route into a **git** host produces a commit whose
  subject, body, author, pathspec and resulting tree are byte-identical to
  `50fa815`'s. **Instrument:** the same scripted route against two
  throwaway ledger+host pairs (one built from `50fa815`, one from the
  build), comparing `git -C <host> show --format=%s%n%b%n --stat HEAD` and
  `git -C <host> rev-parse HEAD^{tree}`.
- **UN2** **[A]** Git-mode **gates** are unchanged: `_abort_if_dirty` still
  decides refusals on a git host and `GITOPS_DIRTY_MARKER` is
  byte-unchanged. **Mutation M38.**
- **UN3** **[A]** *(CARVED-r4→r5, gate r4-B1: r4 carved §9's blanket rule
  for the §2.10b census and then re-asserted UN3 over ten files, **six of
  which the census requires editing** — two `[A]` criteria with no
  precedence rule between them. `CD2` and `UN3` now compose.)*
  The ten test files that pin host-git behaviour (§2.10) pass with **no
  edits to any existing test function except the §2.10b census edits `S3`
  reconciles.** Of the ten, **six carry a census disposition** —
  `test_commit_drift.py` (REWRITE ×6, `CD2`/`M56`), `test_verbs.py`,
  `test_pointer.py`, `test_resolution_evidence.py` (`USER6`),
  `test_m2_verbs.py`, `test_hosting.py` (EDIT).
  **Instrument, split into two halves with different scopes:**
  **(i)** the per-file `--collect-only -q` **name-set** diff against
  `50fa815` binds **unconditionally over all ten** — the collected-name set
  may only GAIN names, so a census rewrite must keep its function name and
  **no test may be renamed or deleted in Phase 1**; **(ii)** the
  additions-only diff binds only the **four non-census files** —
  `test_hosting_fixes.py`, `test_init.py`, `test_gitops.py`,
  `test_batch_fixes.py`. Run from `plugins/self-learn`:
  `git diff --name-only 50fa815 -- cli/tests/test_hosting_fixes.py cli/tests/test_init.py cli/tests/test_gitops.py cli/tests/test_batch_fixes.py`
  must be **EMPTY**, and the same command with
  `cli/tests/test_commit_drift.py` appended must be **NON-EMPTY** — that
  second run is the positive control proving the pathspec resolves
  (§5.13).
- **UN4** **[A]** `host list` output for a registry with no plain entries
  is byte-identical to `50fa815`'s. *(SCOPED-r8, gate r1 fold N-7: named
  alongside `UIM1` for sharing its phrase, not its defect — this is the
  CLI's `host list` text, an entirely different surface from §4.9's arm
  HTML, and MODE11's own byte-identity claim here is unaffected by that
  section and stays achievable; still `50fa815`-byte-identical, unedited
  by this fix.)*
- **UN5** **[A]** `test_lock_invariant.py` green — **as a regression guard
  only.** The build report must state in one sentence that this is not
  evidence about plain-write serialization and that `PLAIN5` is (§2.11).
- **UN6** **[A]** `teach` and `import --memory` still derive a project path
  in a non-repo cwd via `gitops.toplevel(...) or Path.cwd()`.
- **UN7** **[A]** *(RESTATED-r2 — r1's UN7 pinned `build_host_add_argv`
  unchanged, which the M-3 ruling supersedes.)* The UI's **runner
  contract** is unchanged: the confirm route still calls
  `runner.run(<argv>)` exactly once and still renders through
  `partials/host_add_bar.html`; only the argv content and the consent copy
  change.
- **UN8** **[A]** `gitops.host_lock_path(p, "git")` returns exactly what
  `commit_lock_path(p)` returns today, and `commit_lock(home)` — the
  ledger's — is byte-unchanged. **Mutation M39.**
- **UN9** **[A]** `worker.py`'s five `host_repo` sites are **unedited**
  (they are a prompt sentinel, not `TargetSpec`; §2.5a).

### 5.9 USER — user scope as a plain host (**Phase 1**)

*(MOVED-r3, gate r2-B1: every one of these was `[B]` in r2, which is why
Phase 1 could not run. §5.0's table shows what each one unblocks.)*

- **USER1** **[A]** `_resolve_target`'s `scope == "user"` branch returns
  `mode == "plain"` and `host_path == <user_claude_md>.parent`.
  **Mutation M41'.**
- **USER2** **[A]** A user-scope route calls **no chezmoi function at
  all**. **Check:** the `PLAIN4` subprocess/attribute instrument extended
  to every `chezmoi.*` symbol; assert zero. **Positive control:** the same
  instrument at `50fa815` records a non-zero count. **Mutation M40.**
  *(No longer contradicts `CHEZ4` — §4.8.1 moves the write off
  `compile_user_scope`, and `CHEZ4` is inverted below. Gate r2-B2.)*
- **USER3** **[A]** The user-scope host needs no `.self-learn-host` marker
  and no `hosts.yaml` entry; `host_path_problem` is never consulted for
  it. **Mutation M41.**
- **USER4** **[A]** **`TargetSpec.host_path is None` is unreachable.**
  **Instrument:** an AST sweep asserting zero `host_path is None` /
  `is not None` comparisons remain in `verbs.py` and `report.py`, plus a
  runtime assertion in `TargetSpec.__post_init__`. **Positive control:**
  the same sweep **run with the pre-rename field name `host_repo`**
  reports the 17 sites of §2.5a — a `host_path` sweep at `50fa815` returns
  zero, because the field does not exist there yet. *(CORRECTED-r3, gate
  r2-D2.)* **Mutation M42.**
- **USER5** **[A]** A user-scope route leaves a compile record at
  `<home>/compiled/user.yaml` with `host: (user scope — ~/.claude)` and
  `mode: plain`. **Mutation M43.**
- **USER6** **[A]** `test_resolution_evidence.py::test_user_scope_route_is_wrote_uncommitted`
  still passes — edited only where its chezmoi shim is removed, with all
  four asserted envelope fields (`destination`, `variant`,
  `host_commit_sha`, `outcome_state`) unchanged.
- **USER7** **[A]** The user route's compile result is a `SectionResult`,
  and `cli._reports_no_change` (`cli.py:1105`) and `cli._outcome_state`
  (`:1156`) still classify it correctly with their `UserScopeResult`
  branches now dead: a no-change user route reports `no_op`, a changed one
  `wrote_uncommitted`. **Mutation M49:** delete `_reports_no_change`'s
  generic `getattr(..., "changed")` leg → the no-change user route
  misreports → red. *(NEW in r3, gate r2-B2's stated coupling.)*

### 5.10 RPT — report (**Phase 1**)

*(MOVED-r3, gate r2-B1 leg (a): `report.py` must take the rename in Phase
1 or Phase 1's `S1` reddens.)*

- **RPT1** **[A]** A plain host appears in both report surfaces that
  dropped it (`report.py:973`, `:1480`). **Check:** register a plain host,
  route a `rules` record into it, assert the row is present in
  `report --json`. **Mutation M45** (restore the `continue`) → red.
- **RPT2** **[A]** `report.py:140`'s ledger-side `git log` is unchanged
  and `report`'s existing tests pass unedited.
- **RPT3** **[A]** `report.py`'s four `.host_repo` reads (`:973, 975,
  1480, 1482`) are renamed and the module imports cleanly. **Check:**
  `uv run python -c "import self_learn.report"` rc 0, captured **unpiped**.
  **Mutation M50:** leave one `.host_repo` read → `AttributeError` at the
  first plain route → red. *(NEW in r3 — this is gate r2-B1 leg (a) made
  falsifiable.)*

### 5.11 CHEZ — chezmoi deleted wholesale (Phase 2)

*(REBUILT-r3, gates r2-B2, r2-M4, r2-B3.)*

- **CHEZ0** **[A]** *(Phase 1)* At the end of Phase 1,
  `chezmoi.compile_user_scope` and `chezmoi.preflight_user_scope` have
  **zero callers** in `cli/src`. **Instrument:** an AST call-graph sweep;
  **positive control** at `50fa815` reports `verbs.py:2406` and
  `verbs.py:1183, 1274, 4779`. *(This is what makes §4.8.2's deletion a
  removal of dead code rather than a behaviour change.)*
- **CHEZ1** **[B]** `self-learn chezmoi-adopt` no longer exists:
  `cli.main(["chezmoi-adopt", "/x"])` exits through argparse's
  unknown-command path, and `verbs.chezmoi_adopt` is absent.
- **CHEZ2** **[B]** **No module `self_learn.chezmoi` exists.**
  `import self_learn.chezmoi` raises `ModuleNotFoundError`, and
  `verbs.py` contains **zero** `chezmoi_bin` parameters. **Check:** the
  §2.10a grep returns **2** for `cli/src` — exactly the two `compilers.py`
  prose comments at `:596`/`:605` that `CHEZ6` exempts and §9 makes
  untouchable — and **0** for `chezmoi_bin`. Positive control at
  `50fa815`: 205 and 42. *(CORRECTED-r4, gate r3-D4: r3 said "return 0 for
  `cli/src`", contradicting CHEZ6's own exemption.)* **Mutation M44.**
  *(INVERTED-r3 from r2's CHEZ4, which asserted the module still imports —
  gate r2-B2 measured that keeping it is incoherent once the write moves,
  and gate r2-M4 measured that the kept `compile_user_scope` would call
  the deleted `adopt_command` at `chezmoi.py:311`.)*
- **CHEZ3** **[B]** *(CORRECTED-r11, gate r1-M2b: the deletion set is
  five files, not "8 [tests], all in `test_a2_rules_local.py`" —
  measured by AST test/class name-set diff against `50fa815`; this
  ALSO discharges `S5`'s "named individually" requirement, `D-1`.)*
  The `offer_adopt` / `adopt_hint` channel is gone, `UserScopeResult`
  is gone, and no route prints an adopt hint. **Deleted/renamed, by
  file:**

  - `test_a2_rules_local.py` — **20 names** (4 classes, 16 functions):
    classes `TestObligation11OfferFiringMatrix`,
    `TestObligation12AdoptAcceptPath`, `TestObligation13SingleCommandString`
    deleted whole (14 functions between them); `TestObligation26Chezmoi
    ManagedRefusal` renamed to `TestObligation26FormerManagedRefusalNow
    Succeeds` (its 6 functions carried over, 5 byte-identical names, 1
    renamed `test_pathed_route_refuses_dead_glob_before_chezmoi_on_managed`
    → `…_before_the_old_managed_refusal`); plus 2 standalone functions,
    `TestObligation1VariantAbsentByteIdentical::test_managed_carries_no_
    variant_key` and `…test_unmanaged_carries_no_variant_key` (both
    asserted `"variant" not in routed.routing` byte-identically, differing
    only in chezmoi shim state — the surviving sibling
    `test_absent_carries_no_variant_key` still carries the obligation).
  - `test_chezmoi.py` — **13 tests, whole file** (8 classes:
    `TestAbsentDegradesToSilentWrite`, `TestBrokenSourceWarns`,
    `TestChezmoiCapability`, `TestCleanPath`, `TestDirtyRepoAbort`,
    `TestDriftAbort`, `TestInvocationFailures`,
    `TestUnmanagedDegradesToSilentWrite`) — sanctioned by §4.8.2, the
    module's own wholesale deletion.
  - `test_compilers.py` — 1: `TestCapRetirementIrreversible::
    test_t1_4_chezmoi_wrapper_has_no_override_params` (imported the
    deleted `compile_user_scope`).
  - `test_regime_fixes.py` — 1: `test_real_chezmoi_round_trip`.
  - `test_retirement_cleanup.py` — 1 renamed (UN3 does not protect this
    file): `TestRecompileCompleteness::test_user_file_regenerated_via_
    chezmoi_flow` → `…_via_the_plain_host_path`.

  **None of the 22 UN3-protected names in `test_commit_drift.py`,
  `test_hosting.py`, `test_verbs.py` were touched** (`CHEZ6`'s
  accounting, §5.11) — those are retained-not-deleted, a different
  disposition entirely.
*(**CHEZ4 is retired**, not missing — r2's "the module still imports" was
inverted into `CHEZ2` and its number was not reused. The group is CHEZ0,
1, 2, 3, 5, 6; the mutation table references CHEZ5/CHEZ6 by name, so they
are not renumbered. CORRECTED-r4, gate r3-D5.)*

- **CHEZ5** **[B]** The four except tuples that name `ChezmoiAbort` /
  `ChezmoiError` shrink and nothing else changes:
  `verbs._HOST_PHASE_ERRORS` (`verbs.py:2561`), `cli._cmd_verb`,
  `cli._cmd_host`, `teach.py:722-723`. **Check:** each tuple's remaining
  members are byte-unchanged, and `teach.py:75`'s import is gone.
  **Mutation M51:** leave one import → `ImportError` at CLI load → the
  whole CLI suite errors → red. *(NEW in r3, gate r2-B2's measurement.)*
- **CHEZ6** **[B]** *(CORRECTED-r11, gate r1-M2a: the shipped
  accounting is 37 `cli/tests` hits, not "one migration note" — every
  one is legitimate, and this criterion now says so instead of leaving
  the shipped state to look like an overrun. `ui/static` joins the
  swept trees, gate r1-N2.)* **Zero `chezmoi` literals remain in
  `cli/src`, `ui/src`, `ui/templates`, `ui/tests`, `ui/static`** —
  except the two prose comments at `compilers.py:596`/`:605`
  (`ui/static` carries zero: its two `app.js:517,519` retirement
  comments say "adopt", not `chezmoi` — see `UIC5`) — and `cli/tests`
  carries exactly 37, in six categories, MEASURED at `b7e4189`:

  | category | count | files |
  |---|---|---|
  | `UN3`-protected pre-existing test/class names (name-set freeze forbids renaming) | 22 | `test_commit_drift.py` 11, `test_hosting.py` 1, `test_verbs.py` 10 |
  | unrelated real-world guard against the externally-installed `chezmoi` CLI's `cd` subcommand (`lrn-98d42215`) | 14 | `test_route_hook.py` 12, `test_hook_compiler.py` 2 |
  | absence assertion (`assert "chezmoi" not in text`) | 1 | `test_composer.py` 1 |

  **Instrument:** `grep -rn -i chezmoi` over exactly those six trees
  (`ui/static` added at r11); **positive control** at `50fa815` returns
  205 / 12 / 7 / 343 / 43 for the original five — `ui/static` was not
  separately measured before r11, since no instrument swept it.
  **`docs/` is explicitly NOT swept** — its **421 hits excluding this
  draft** (546 including it, at r4) are history and stay (§2.10a).
  *(CORRECTED-r4, gate r3-D2.)* *(NEW in r3, gate r2-B3's "census, not memory" ruling.)*

### 5.11a UIC — the UI adopt surface (Phase 2)

*(NEW in r3, gate r2-B3. r2 named none of this, and one omission —
`ui/routes.py:32`'s module-level import — would have errored the entire
1268-test UI suite the moment `ADOPT_COMMAND_PREFIX` was deleted.)*

- **UIC1** **[B]** `ui/src/self_learn_ui/routes.py` has **no import from
  `self_learn.chezmoi`**, and the UI package imports cleanly:
  `cd plugins/self-learn/ui && uv run python -c "import
  self_learn_ui.routes"` rc **0**, captured **unpiped**. **Mutation M52:**
  delete `ADOPT_COMMAND_PREFIX` from `chezmoi.py` while leaving
  `routes.py:32` → `ImportError` → the whole UI suite errors → red.
  **This mutation is the gate's own finding, kept so it cannot recur.**
- **UIC2** **[B]** `COMMIT_DRIFT_MARKERS` (`routes.py:2062`) is
  `(GITOPS_DIRTY_MARKER,)` and the git-mode commit-drift banner still
  fires. **Check:** `ui/tests/test_commit_drift.py`'s git-mode legs pass;
  its chezmoi legs are deleted, named individually.
- **UIC3** **[B]** The adopt flow is **gone, replaced by nothing**: no
  `"chezmoi-adopt"` verb label (`:74`), no argv branch (`:167-174`), no
  `_extract_adopt_path`, no `_adopt_offer_response`, no
  `/record/{id}/adopt-offer/dismiss` route, no
  `partials/adopt_offer.html`, and no `kind == "adopt"` branch in
  `action_bar.html`. **Check:** a POST to the dismiss route returns 404;
  a rendered detail page for a user-scope routed record contains no
  `data-adopt-offer` attribute. **Mutation M53:** leave the dismiss route
  → the 404 assertion reddens.
- **UIC4** **[B]** `models.py`'s `adopted` parameter (`:305`) and its
  `if scope == "user" and not adopted:` branch (`:334`) are gone, and
  `ui/tests/test_models_detail.py`'s remaining assertions pass.
  **Mutation M54.**
- **UIC5** **[B]** *(CORRECTED-r11, gate r1-N2: `ui/static` joins the
  swept trees — it carries the UI's whole client-side behaviour and no
  criterion looked at it before r11.)* Zero `adopt` references remain
  in `ui/src`, `ui/templates`, and `ui/static` — except two dated
  retirement comments in `ui/static/app.js:517,519` (`reloadDeferred`'s
  docblock, marking leg (e) a permanent gap after the offer it deferred
  for was deleted; retained-history, not live behaviour). **Positive
  control** at `50fa815`: the §2.10a listing (`ui/src` 37, `ui/templates`
  13; `ui/static` was not separately measured before r11). The six UI
  test files are reconciled individually by `S5`.


### 5.12 DOC (Phase 1) and SUITE (both)

- **DOC1** **[A]** *(CORRECTED-r11, gate r1: Phase 2 landed under the
  SAME unit, so the interim parentheticals this criterion pinned are
  gone by design, not by omission.)* `03-decisions.md` carries `S-51`
  = §3 of this spec — **with the row's two Phase-2 clauses no longer
  carrying the `(landed by Phase 2 of the same unit)` parenthetical**,
  replaced by one closing sentence once both phases exist under this
  unit: *"Both phases (Phase 1: the mode carrier, the compile record,
  plain-mode user scope; Phase 2: `chezmoi.py` deletion, UI adopt
  surface) landed under this unit — see `FW-122`."* **Check:**
  `grep -o '(landed by Phase 2 of the same unit)' docs/specs/self-learn/03-decisions.md
  | wc -l` → **0**, and the row's final sentence is the replacement
  text above (positive control: the same grep at Phase 1's own tip,
  `fa02a4c`/master `3b8e037`, returns **2**, proving the instrument
  would have caught an un-updated row). *(CORRECTED-r3, gate r2-D7.)*
- **DOC2** **[A]** *(CORRECTED-r11, gate r1: §12.2's FW-122 cell pinned
  the Phase-1-only interim wording; Phase 2 landing under this unit makes
  that wording stale, not the live doc.)* `14-forward-work-map.md`
  carries FW-122, FW-123, FW-124 (§12.2), verbatim — where §12.2's own
  FW-122 disposition cell now reads *"Landed by `U-hostmode` (Phase 1 +
  Phase 2)"*, replacing r8's interim *"Landed by `U-hostmode` Phase 1
  (this build); Phase 2 … not yet landed — N-6"*. **Check:** the spec
  text and the live `14-forward-work-map.md` row agree byte-for-byte on
  that cell.
- **DOC3** **[A]** `13-hosting-and-separation.md` §4 carries §12.3's
  amendment — as **item 5** of a list that has **four** items today
  *(CORRECTED-r2, gate D-4)* — and §8 `H-3` gains its clause.
- **DOC4** **[A]** `17-invocation-runbook.md` gains the §12.4 lines,
  including the CORRECTED rollback text.
- **DOC5** **[A]** No doc or docstring asserts that a canon host must be a
  git repo after this unit. **Instrument:** grep
  `docs/specs/self-learn/*.md` **and `cli/src/self_learn/hosts.py`**
  *(EXTENDED-r2, gate N-3: `hosts.py:16` and `hosts.py:331` both say
  "must exist, must be a git repo" and were outside r1's instrument)* for
  `must be committable|must be a git repo|canon hosts must be`; every hit
  must be mode-qualified or quoted-as-history. **Positive control:** the
  same grep at `50fa815` returns the known hits
  (`09-surface-spec.md:1917`, `hosts.py:16`, `hosts.py:331`,
  `host_path_problem`'s message).
- **DOC6** **[A]** The UI test assertions on the git-repo refusal string
  still pass — they assert a *git-mode* refusal, which survives:
  `ui/tests/test_routes.py:513, 517, 669, 713-714, 733` and
  `ui/tests/test_registration_wipe.py:60, 156`. *(CORRECTED-r3, gate
  r2-D4: r2 cited `test_registration_wipe.py:74`, which is a docstring,
  and omitted `test_routes.py:733`'s
  `r.text.index("canon hosts must be committable")`.)*
- **S1** **[A]** `plugins/self-learn/cli/scripts/suite` rc **0**,
  collected ≥ **2417**, 0 failures. rc captured **unpiped**.
- **S2** **[A]** UI suite from **inside** `plugins/self-learn/ui`:
  collected ≥ **1268**, with
  `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
  the ONLY failure.
- **S3** **[A]** *(RESTATED-r4, gate r3-B1: r3 forbade deletions while
  §4.8.1 permitted them and `USER6` conceded an edit outside the named
  file.)* Phase 1 reconciliation: **no test outside §2.10b's census
  and the `_LOCKS` constant `PLAIN13` changes is edited, renamed or
  deleted** *(CARVED-r5, gate r4-D2: `test_lock_invariant.py` is not in
  the 20-file census — it carries chezmoi literals in comments but has
  zero chezmoi-mentioning test functions — so S3 as written forbade the
  edit `PLAIN13` requires)*; every census test that IS touched is
  listed in the build report with its disposition (EDIT / REWRITE /
  DELETE) and its reason; and the collected-count delta equals
  `(new − deleted)` and is reconciled line by line.
  **Positive control, cwd-pinned** *(CORRECTED-r5, gate r4-D1 — see
  §5.13)*: run from `plugins/self-learn`,
  `git diff --name-only 50fa815 -- cli/tests/ ui/tests/` must
  **(i) be NON-EMPTY**, naming at least `cli/tests/test_hostmode.py` and
  `cli/tests/test_a2_rules_local.py` — an empty result means the pathspec
  did not resolve, not that nothing was touched — and **(ii)** name no
  file absent from the §2.10b census, the two new files,
  `test_lock_invariant.py` (`PLAIN13`), **the six §2.10b leg 4 files**
  (`CARVED-r7`: `test_provider.py`, `test_round3_fixes.py`,
  `test_route_cli.py`, `test_u_fake.py`, `test_worker_contract.py`,
  `ui/tests/test_routes.py`), **and the four §2.10b leg 5 files**
  (`CARVED-r9`, gate r2-M2: `cli/tests/conftest.py`,
  `ui/tests/conftest.py`, `cli/tests/test_u_sdka.py`,
  `cli/tests/test_context_budget.py`). **Order matters: (i) gates (ii).**
- **S4** **[B]** Phase 2: **both** suites green — CLI collected
  ≥ `2417 + (new − deleted)` and UI collected ≥ `1268 + (new − deleted)`,
  each delta reconciled by `S5`; the only failure is the known
  pre-existing `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`.
  *(CORRECTED-r3, gate r2-D6: r2 said "the same standard" as `S1`'s
  `≥ 2417`, which Phase 2 cannot meet — it deletes at least 8 CLI test
  functions and the UI adopt tests. The UI suite is named explicitly
  because the UI deletions of §4.8.3 are Phase 2's largest surface.)*
- **S5** **[B]** Phase 2 reconciliation: every deleted test named
  individually with the deleted symbol it covered; the collected-count
  delta equals (new − deleted) and is reconciled in the build report.


### 5.13 THE DIFF-INSTRUMENT AUDIT — every `git diff` check in this spec

*(NEW in r5, gate r4-D1. The gate found `S3`'s positive control fails
open; the ruling required auditing **every** diff-based instrument for the
same shape. This is that audit.)*

**The failure mode, reproduced by me at `50fa815`, not merely quoted.**
Git resolves a pathspec against the **cwd**, and prints nothing at rc 0
when it matches nothing. Every diff instrument in this spec was written
with pathspecs relative to `plugins/self-learn`, but a gate or a builder
runs from the repo root by default:

```
$ cd ~/repos/self-learn
$ git diff --name-only 50fa815~1 50fa815 -- cli/tests/ ui/tests/
                                                    # (nothing)
rc=0
$ git diff --name-only 50fa815~1 50fa815 -- plugins/self-learn/cli/tests/
plugins/self-learn/cli/tests/test_lock_invariant.py
plugins/self-learn/cli/tests/test_serve.py
plugins/self-learn/cli/tests/test_u_sdka.py
rc=0
```

**Same commits, same range: three real files, or silence.** "The control
could not see the target" and "no file outside the census was touched"
are byte-identical outputs — the `lrn-ea833a5b` shape, and the most
dangerous form a check can take.

**All three diff-based instruments, audited and fixed:**

| # | criterion | shape at r4 | fix |
|---|---|---|---|
| 1 | **`S3`** positive control | `git diff 50fa815 -- cli/tests/ ui/tests/`, cwd unpinned, empty result reads as PASS | cwd pinned to `plugins/self-learn`; **must be NON-EMPTY** naming `test_hostmode.py` and `test_a2_rules_local.py` **before** the membership check runs |
| 2 | **`UN3`** additions-only half | `git diff 50fa815 -- tests/` — same shape, and the wrong scope besides (r4-B1) | split: the name-set half binds all ten unconditionally; the diff half binds the four non-census files, cwd pinned, **with a paired NON-EMPTY control run** that appends `test_commit_drift.py` |
| 3 | **`PLAIN6`** `NOT_REPO_TRUTH` check | `git diff 50fa815 -- tests/test_lock_invariant.py` — same shape; and since `PLAIN13` *edits* that file, an empty diff is doubly ambiguous | cwd pinned; **must be NON-EMPTY**, with the only permitted hunk the one-name `_LOCKS` change |

**The rule this spec now applies to every diff check, stated once:** pin
the cwd, use pathspecs relative to it, and **assert the direction that
distinguishes "clean" from "could not see it"** — a check whose PASS
output is identical to its blind output is not a check. Every other `git`
instrument here is already cwd-explicit (`git -C <p>`, `git -C <home>`,
`git -C <host>` — §2.1, `REC9`, `UN1`) or names its directory in the
transcript (§2.0, §2.10), and the collected-name diffs are computed from
pytest output rather than from pathspecs, so none of them carries this
shape.

---

## 6. Mutation plan

Every cell is `predicted` — **no code for this unit exists at `50fa815`**.
**Ten rows carry a measured anchor** verified by a blind gate: M9, M11,
M20, M24, M26, M32, M50, M52 (all confirmed at gate r3) plus M55 and M56
(added in r4 from gate r3's own measurements). *(CORRECTED-r4, gate r3-D3:
r3's preamble said "three".)*

| # | Mutation | Must fail | Basis |
|---|---|---|---|
| **M1** | `host_mode` defaults to `plain` when `mode` is absent | MODE1, MODE5 | *predicted* |
| **M2** | `save_hosts` always emits `mode:` | MODE2 | *predicted* — the gate ran the round-trip and it is byte-identical today |
| **M3** | `effective_default_mode` accepts any truthy value | MODE3 | *predicted* — the shape `config.one_motion_enabled` already refuses |
| **M4** | drop the `--mode plain --init` refusal | MODE4 | *predicted* |
| **M5** | make `plain` the built-in default | MODE1, MODE5 | *predicted* |
| **M6** | `host_add` silently flips an existing host's mode | MODE6 | *predicted* |
| **M7** | drop the `skills_root` scalar branch | MODE8, MODE1 on the real registry's text | *predicted* |
| **M8** | restore one `host_path is None` user-scope inference (e.g. `commit_drift:3508`) | MODE9, and CD1 | *predicted* |
| **M9** | `load_hosts` silently drops an unknown project-entry key | MODE10 | *predicted* — **measured anchor:** the gate ran four fixtures against the shipped parser; `{path, banana: 3}` is ACCEPTED today. This mutation IS the current behaviour, so the row is guaranteed to fire |
| **M10** | hash the region EXCLUDING `END_MARKER` | REC1 | *predicted* *(REPLACED-r2, gate N-1: r1's M7 — "hash the in-memory string rather than the bytes on disk" — cannot fire on POSIX, because `Path.write_text` performs no newline translation and the compilers write UTF-8 with no other normalization, so both implementations produce the same digest. This substitution discriminates.)* |
| **M11** | implement the predicate as a call to `gitops.paths_dirty` | **REC2** | *predicted* — **measured anchor:** `paths_dirty` runs `git status --porcelain -- <target>`, which by construction reports nothing for a committed edit; REC2 asserts `paths_dirty is False` in the same body, so this cannot pass |
| **M12** | hash the whole file instead of the region | REC3 | *predicted* — R-e made falsifiable |
| **M13** | write the record only when `mode == "plain"` | REC4 | *predicted* |
| **M14** | treat `entry absent + region present` as fresh | REC5, GATE2 | *predicted* |
| **M15** | treat `entry absent + region absent` as a refusal | REC5, PLAIN2 | *predicted* — **this is r1's own REC5 bug, kept as a mutation so it cannot come back** |
| **M16** | treat `entry present + region absent` as `edited` | REC5 | *predicted* |
| **M17** | drop `based_on_sha256` | REC6 | *predicted* — and `recompile` loses the ability to repair an unlanded apply, which REC6's second leg asserts |
| **M18** | add a `paths` region to the record | REC7's positive control | *predicted* |
| **M19** | write the record as a second ledger commit | REC9 | *predicted* — this is r1's design, kept as a mutation (gate B-3) |
| **M20** | let the post-record `GitOpsError` leak (exit 6) instead of `HalfWrittenError` | REC10 | *predicted* — **measured anchor:** `cli.py:1397-1403`'s own comment pins that 6's "nothing was written" claim is safe *"only because … every post-mutation git failure is re-raised as HalfWrittenError above"* |
| **M21** | add `recompile --force` | REC11 | *predicted* |
| **M22** | skip the `.self-learn-host` check in `host_path_problem` | **GATE2** | *predicted* |
| **M23** | `host remove` deletes `.self-learn-host` | GATE5 | *predicted* |
| **M24** | leave `cli._outcome_state` unedited | **PLAIN3** | *predicted* — **measured anchor, CONFIRMED by the gate:** the shipped predicate at `cli.py:1146-1160` falls through to `"unknown"` for a `SectionResult` with `changed=True`, `host_commit_sha=None`, not `UserScopeResult`, `variant != "local"`. The mutation is the current code |
| **M25a** | drop `PLAIN4`'s git-mode positive control | PLAIN4's control leg | *META-ROW (r10, gate r3-N5): not independently reddenable.* Deleting a test's own POSITIVE CONTROL removes evidence, it does not redden an assertion — there is nothing left in the test for the deletion itself to fail. Kept in the table as the `lrn-ea833a5b` shape this mutation illustrates (a gate whose pass output is identical to "could not see the target"), not as a runnable row; `M25b` is the row that actually reddens |
| **M25b** | insert a stray `subprocess.run(["git", "status"], cwd=str(spec.host_path))` into `_host_phase`'s PLAIN branch | PLAIN4 | *predicted — this is the mutation `M25a`'s control exists to catch, and the one gate r2 M-6 found invisible to the pre-fold instrument (`gitops._git` was patched; a raw `subprocess.run` bypassing that wrapper was not). `test_plain4_no_git_subprocess_against_plain_host` now patches BOTH `gitops._git` and raw `subprocess.run`; this mutation reddens the widened instrument. `M25b` RED is the proof that `M25a`'s control is doing real work — `M25a` alone cannot demonstrate that, by construction* |
| **M26** | **keep `_host_phase`'s lock ternary but make its plain branch yield `contextlib.nullcontext()`** | **PLAIN5 only** | *predicted* — **measured anchor, gate-replicated:** the gate copied `_is_lock` and `_guarded_lines` verbatim and ran them over four shapes; this one leaves the mutation lines guarded and `test_lock_invariant.py` **GREEN**. *(SHAPE-PINNED-r2, gate D-12: replacing the ASSIGNMENT outright with a bare `nullcontext()` leaves zero guarded lines and turns the walker RED — a different result, and not this mutation.)* A gate that sees only PLAIN5 die has confirmed §2.11's blind spot, not found a hole |
| **M27** | `--selftest` treats "no compile record" as clean | PLAIN8 | *predicted* — assert the rendered string, not the boolean |
| **M28** | call `check_ignore` on a plain host | PLAIN9 | *predicted* |
| **M29** | emit a LOUD skip line for plain hosts in `push_pending` | PLAIN10 | *predicted* |
| **M30** | keep `git rm` in hook retirement for plain hosts | PLAIN11 | *predicted* — silent without PLAIN11's subprocess assertion, because `verbs.py:1853-1860` swallows the `GitOpsError` |
| **M31** | key the plain lock by the ledger home instead of the host slug | PLAIN12, PLAIN5 (two homes, one host) | *predicted* |
| **M32** | leave `_RECONCILABLE` unchanged | **RCN1** | *predicted* — **measured anchor:** the gate confirmed `<home>/compiled/` is outside `discover_buckets`' three globs, so `find_orphans` can never return it today |
| **M33** | leave `ledger._LAYOUT` unchanged | RCN3 | *predicted* |
| **M34** | let `commit_drift` run its git path on a plain host | CD1 | *predicted* — `paths_dirty` → `_git_ok` → `GitOpsError` → exit 6 with a message about a repo that is not one |
| **M35** | `_needs_init` / the arm rendering ignores the mode | **UIM1** | *predicted* — *(r1's M20 killed nothing; this one has a criterion)* |
| **M36** | omit `--mode` from `build_host_add_argv` | UIM2 | *predicted* |
| **M37** | let a posted `mode=git` force `--init` without re-derivation | UIM3 | *predicted* — the Y-17 F1 invariant |
| **M38** | route git-mode refusals through the record predicate | UN2, plus the shipped dirty tests | *predicted* |
| **M39** | change the git-mode lock path | UN8 | *predicted* |
| **M40** | keep one chezmoi call on the user-scope route | USER2 | *predicted* |
| **M41** | require `.self-learn-host` in `~/.claude` | USER3 | *predicted* |
| **M42** | leave one `host_path is None` comparison | USER4 | *predicted* |
| **M43** | slug user scope with `slug_for("~/.claude")` instead of `"user"` | USER5 | *predicted* — gate M-5's gap made falsifiable |
| **M44** | keep `chezmoi_bin` on one verb signature | CHEZ2 | *predicted*. D-5 (code gate r1 fold, 2026-08-28): not runnable at Phase 1's own gate — this mutation targets a Phase-2-only deletion that has not happened yet. |
| **M45** | restore `report.py`'s `continue` | RPT1 | *predicted* |
| **M46** | `host list` omits the mode | MODE11 | *predicted* — §12.4's rollback procedure step 1 has no other source |
| **M47** | define the second record hash as the previous **expectation** rather than the observed pre-flight hash | **REC13** | *predicted* — **this is r2's own definition**, and the gate traced it: two consecutive host-phase failures then verdict `edited`, so `route` AND `recompile` refuse, contradicting H-2 and the shipped "run `self-learn recompile` to repair" warning. Kept as a mutation so it cannot come back |
| **M48** | compute the expectation before taking the host lock (r2's shape) | **REC12** | *predicted* — a concurrent producer's ledger commit then lands between our commit and our host phase, `_compile_set` (`verbs.py:1907`) re-reads `resolved/`, and the written region hashes to neither field |
| **M49** | delete `_reports_no_change`'s generic `getattr(..., "changed")` leg | USER7 | *predicted* — with `UserScopeResult` no longer produced by the user route, that leg is the only thing classifying it |
| **M50** | leave one `.host_repo` read in `report.py` | **RPT3** | *predicted* — **measured anchor:** the gate measured four reads at `report.py:973, 975, 1480, 1482`; each raises `AttributeError` on the first plain route after the rename. This is gate r2-B1 leg (a) |
| **M51** | leave `teach.py:75`'s `from .chezmoi import ChezmoiAbort, ChezmoiError` after deleting the module | CHEZ5 | *predicted* — `ImportError` at CLI load; the whole CLI suite errors. D-5 (code gate r1 fold, 2026-08-28): not runnable at Phase 1's own gate — this mutation targets a Phase-2-only deletion that has not happened yet. |
| **M52** | delete `ADOPT_COMMAND_PREFIX` while leaving `ui/routes.py:32`'s module-level import | **UIC1** | *predicted* — **measured anchor:** the gate found this import; the deletion errors the entire 1268-test UI suite, so `S4` becomes unpassable. This is the gate's own r2-B3 finding, kept as a mutation. D-5 (code gate r1 fold, 2026-08-28): not runnable at Phase 1's own gate — this mutation targets a Phase-2-only deletion that has not happened yet. |
| **M53** | leave the `/record/{id}/adopt-offer/dismiss` route | UIC3 | *predicted*. D-5 (code gate r1 fold, 2026-08-28): not runnable at Phase 1's own gate — this mutation targets a Phase-2-only deletion that has not happened yet. |
| **M54** | leave `models.py`'s `adopted` parameter | UIC4 | *predicted*. D-5 (code gate r1 fold, 2026-08-28): not runnable at Phase 1's own gate — this mutation targets a Phase-2-only deletion that has not happened yet. |
| **M41'** | user scope keeps `mode == None` / no mode | USER1, and `host_lock(None, …)` → `slug_for(None)` `TypeError` | *predicted* — gate r2-B1 leg (b) |
| **M55** | leave `_LOCKS` as `("commit_lock", "_ledger_write")` | **PLAIN13** | *predicted* — **measured anchor:** `_LOCKS` is at `test_lock_invariant.py:94` and `_is_lock` matches by NAME; `gitops.host_lock` is not in it, so `commit_drift`, `_remove_hook_script` and the retirement leg lose their recognised guard and their roots fail `test_no_entrypoint_reaches_a_mutation_without_a_lock`. This mutation IS r3's shipped design |
| **M56** | leave one of `test_commit_drift.py`'s six user-leg tests asserting a chezmoi commit | CD2 | *predicted* — **measured anchor:** `test_dirty_dotfiles_goes_through_chezmoi_git` (`:191`) asserts the user leg COMMITS; after Phase 1 it refuses at 64 |
| **M57** | move the host lock from `_host_phase` to its callers (r3's shape) | **REC12** | *predicted* — `supersede:4154` and `graduate:4055` (via `_retirement_host_phase:2302`) then write the host with no host lock at all: two paths that WERE locked at `50fa815` |
| **M58** | acquire the host lock AFTER `resolve_record` | **REC12**, and §7 row 6 | *predicted* — a host-lock timeout then returns exit 6 ("nothing was written") over a record that has already `git mv`-ed; r2-B3's lie at a new point |

**A gate must run each of these and record the actual red set, replacing
`predicted` with `measured` per row. A row that stays `predicted` after
the build is an unverified claim, not a passing criterion.**

**Unmutated criteria, with reasons.** MODE7 and USER4's sweep half (AST
censuses whose only mutation is deleting the census); UN1/UN3/UN4
(byte-identity comparisons against `50fa815` — the mutation is any
behaviour change, and every other row is one); UN5 (a regression guard by
construction, §2.11); UN6 and UN9 and RPT2 and RCN2/RCN4 and CD2
(each pins the *absence* of a change); REC8 (round-trip fidelity, which
`ruamel typ="rt"` already provides and whose mutation is caught first by
`records.py`'s tests); DOC1–DOC6 and S1–S5 (presence and suite checks with
their own positive controls); USER1/USER6/CHEZ1/CHEZ3/CHEZ0/UIC2/UIC5 (each is killed by
M40/M41'/M42/M44/M52 or by the deletion itself).

---

## 7. Exit codes

Verified against `cli.py:66-76`, `cli._cmd_verb` (`cli.py:1380-1408`),
`cli._finish_verb` (`cli.py:1246-1249`), `_cmd_host`
(`cli.py:1410-1428`), `gitops.EXIT_*`, `ledger.EXIT_NO_HOME`.

| Code | Constant | git-mode host | **plain-mode host** |
|---|---|---|---|
| **0** | `EXIT_OK` | Routed; host committed; pushed or skipped | Routed; canon written; compile record in the same ledger commit. **Unchanged** |
| **1** | `VerbError.exit_code` | Every pre-flight refusal: unregistered host · host not sound (incl. `not a git repo`) · **dirty compile target** · secret hit · glob/ALWAYS-gate · `CompileError` · `ChezmoiAbort` | **Reachable, changed trigger set.** `not a git repo` → the missing-`.self-learn-host` refusal; the dirty leg → the §4.5 predicate's `edited` and `unknown provenance` rows |
| **2** | *(argparse)* | Missing/invalid flag | **Unchanged.** `--mode` outside `choices` lands here |
| **3** | `EXIT_PUSH_FAILED` | Ledger push failed, **or host push failed** (`_finish_verb`, MAJOR 4) | **HOST leg IMPOSSIBLE.** Ledger leg unchanged; entirely impossible when the ledger is also remoteless |
| **4** | `EXIT_REBASE_CONFLICT` | A push's `pull --rebase` conflicted, ledger or host | **HOST leg IMPOSSIBLE.** Ledger leg unchanged |
| **5** | `EXIT_NO_HOME` | LEDGER home missing or not a git repo | **Unchanged.** The LEDGER is still always a git repo |
| **6** | `EXIT_GIT_FAILED` | A `GitOpsError` raised BEFORE the first mutation | **Reachable via the LEDGER only**, and via a plain-host **lock timeout** (`host_lock` still raises `GitOpsError` on timeout — nothing written, so 6 stays true). **Never returned for a compile-record failure** — see row 7 |
| **7** | `EXIT_HALF_WRITTEN` | `HalfWrittenError`: the LEDGER record moved and the LEDGER commit failed | **Unchanged in meaning, WIDENED in trigger** *(NEW-r2, gate B-3)*: because the compile record is written inside `_ledger_write` before `_commit_ledger`, a failure of that commit is already half-written and already returns 7 through the shipped path. **`REC10` pins it. A builder must not invent an eighth code, and must not let it leak as 6** |
| **64** | `EXIT_USAGE` | Unknown/malformed record id; every `host` sub-verb refusal | **Reachable, plus four new triggers:** `--mode plain --init`; a mode-flip re-add; an unknown key in a hosts.yaml entry (`MODE10`); **`host commit-drift` against a plain host** (`CD1`) |

**Two codes become impossible on the host leg: 3 and 4.** The row a builder
is most likely to get wrong is **7 vs 6**: a plain-mode *host* write that
fails is still a warning at exit 0 (the ledger is committed and canon is
stale-not-lost, H-2), while a *ledger* commit that fails after the record
is on disk is 7.

---

## 8. Scope

### IN

1. `hosts.py` — the mode on the entry; `host_mode`,
   `effective_default_mode`, `host_slug`; the `.self-learn-host` marker;
   `host_path_problem`'s mode branch; `save_hosts` round-trip;
   `load_hosts`' unknown-key refusal; the `:16` / `:331` docstrings.
2. `config.py` — one new fail-closed reader.
3. `cli.py` — `--mode` on `host add`; `recompile --adopt`; `_host_line`;
   the consent lines; `_outcome_state`'s plain branch; (Phase 2) the
   `chezmoi-adopt` parser, `_cmd_chezmoi_adopt`, dispatch.
4. `verbs.py` — **all eleven functions that hold the 38 host-side git
   calls** (§2.2): `_abort_if_dirty`, `_resolve_local_target`,
   `_remove_hook_script`, `_host_phase`, `route`, `route_direct`,
   **`commit_drift`**, `graduate`, `supersede`, `push_pending`,
   `recompile` — plus `_gate_host`, `_resolve_target`, `TargetSpec`, and
   (Phase 2) `chezmoi_adopt` and the `chezmoi_bin` thread.
5. `gitops.py` — `host_lock` / `host_lock_path` **only**;
   `commit_lock`/`commit_lock_path` for the ledger unchanged.
6. `selfcheck.py` — `_check_drift` reads the compile record.
7. **`reconcile.py`** — `_RECONCILABLE` and `_is_reconcilable` (§4.6).
8. **`ledger.py`** — `_LAYOUT` gains `"compiled"` (§4.6).
9. **`report.py`** — the rename of its four `.host_repo` reads (`:973,
   975, 1480, 1482`) and the two dead `is None` guards. **Phase 1**
   *(MOVED-r3, gate r2-B1 leg (a): the rename is Phase 1's, so the file
   must be too, or Phase 1 does not import)*.
10. **`chezmoi.py`** — **deleted wholesale** in Phase 2 (§4.8.2).
11. **`teach.py`** — `:75`'s import and `:722-723`'s except tuple
    (Phase 2). *(ADDED-r3: r2 never named it, and it is a third
    module-level importer of the deleted module.)*
12. A new module for the compile record (`compiled.py` or equivalent).
13. `ui/routes.py` + `templates/partials/host_add_bar.html` — the consent
    choice (§4.9), Phase 1.
14. **The UI adopt surface (Phase 2, §4.8.3)** — `ui/routes.py`'s import,
    verb label, argv branch, `_extract_adopt_path`,
    `_adopt_offer_response`, the dismiss route and `COMMIT_DRIFT_MARKERS`;
    `ui/templates/partials/{adopt_offer,action_bar,evidence}.html` and
    `detail.html`; `ui/src/self_learn_ui/models.py:305, 334`; the six UI
    test files.
13. Docs: `03` S-51, `14` FW-122..124, `13` §4 + §8, `17` runbook lines.

### OUT — each is a real thing a builder might reach for

- **OUT-1 — Any new verb, and any mode-changing verb.** No
  `host set-mode`, no `host --retire`, no `route --dry-run`, no
  `show <id>`, no bucket pruning, no bulk apply. **All belong to
  `U-verbs`.** This unit adds one flag to `host add` and one to
  `recompile`.
- **OUT-2 — A UI surface beyond the consent choice.** No mode display in
  the bucket list, no re-mode control, no `host list` page.
- **OUT-3 — Migrating any of the nine registered hosts.** The build ships
  a capability; `~/.self-learn` is not written by it.
- **OUT-4** *(INVERTED-r3, gate r2-B2 — r2 fenced OUT the wholesale
  deletion and kept `compile_user_scope`; that is now the RULING's
  opposite.)* **What remains out is `docs/`.** The 497 chezmoi mentions
  across the spec corpus are history and are not swept; `CHEZ6`'s
  instrument is scoped to `src/`, `templates/` and `tests/`. Also out:
  `compilers.py:596`/`:605`, two prose comments that mention chezmoi's
  historical refusal and describe no live behaviour.
- **OUT-5 — Registering user scope in `hosts.yaml`.** It is a host by
  construction, not by registration (`USER3`) — no entry, no marker, no
  `host_path_problem` consultation. What is NOT out any more is the
  user-scope *mechanism*: `USER1`–`USER7` are Phase-1 criteria (gate
  r2-B1).
- **OUT-6 — `paths:` frontmatter in the compile record.**
  `compilers.paths_frontmatter_drift` is already the one agreement
  predicate for that key. `REC7`'s positive control enforces the omission.
- **OUT-7 — new-skill scaffolds in the compile record.**
- **OUT-8 — `doctor invocation`.** It is the invocation-seam doctor.
- **OUT-9 — The sentinel's contract.** Unchanged in every particular.
- **OUT-10** *(REVISED-r2 — r1 declared `report.py` and `reconcile.py`
  permanently out; both are now IN, per gates M-1 and B-2.)* **What
  remains out is the LEDGER's git behaviour:** the 54 ledger-side git
  calls keep their semantics, `reconcile`'s git usage is untouched (only
  its path predicate changes), and `report.py:140`'s `git log` is
  unchanged (`RPT2`).
- **OUT-11 — Fixing `09 §11 Y-17`'s stale "recompile … diff against git"
  clause in place.** §2.4 item 4 measured it false; correcting a ratified
  surface-spec row is a human-ratified motion. It rides **FW-124**.
- **OUT-12 — `worker.py`'s five `host_repo` sites.** A different local
  (§2.5a); `UN9` pins them unedited.

---

## 9. Files this unit may touch

**Phase 1 [A]:** `cli/src/self_learn/{hosts,config,gitops,cli,verbs,selfcheck,reconcile,ledger,`**`report`**`}.py`
*(`report.py` ADDED-r3, gate r2-B1 leg (a) — it holds four `.host_repo`
reads and cannot survive the rename otherwise)* · the new compile-record
module · `ui/src/self_learn_ui/routes.py` ·
`ui/templates/partials/host_add_bar.html` ·
`cli/tests/test_hostmode.py` (new — CORRECTED-r9, gate r2 N-5: r7 also
named `test_compile_record.py` as a second new file; it was never
created, every test lives in `test_hostmode.py`, now 4000+ lines) ·
**the §2.10b
census files** — `test_a2_rules_local.py`, `test_u_glob.py`,
`test_xscope_enumeration.py`, `test_pointer.py`, `test_verbs.py`,
`test_commit_drift.py`, `test_resolution_evidence.py`, plus the nine
one-hit files (`test_buckets.py`, `test_composer.py`,
`test_hook_compiler.py`, `test_hosting.py`, `test_invocation.py`,
`test_one_motion_config.py`, `test_records_lifecycle.py`,
`test_regime_fixes.py`, `test_route_hook.py`;
CORRECTED-r5, gate r4-D3) and
`test_m2_verbs.py`/`test_compilers.py`/`test_retirement_cleanup.py`
*(EXTENDED-r4, gate r3-B1 — r3 named one test file and then forbade
touching any existing test body)* · `cli/tests/test_lock_invariant.py`
(the one-name `_LOCKS` change, `PLAIN13`) ·
**`test_provider.py`, `test_round3_fixes.py`, `test_route_cli.py`,
`test_u_fake.py`, `test_worker_contract.py`** (`CARVED-r7`, §2.10b leg 4 —
each forced by an `[A]` behavior change outside the chezmoi census) ·
**`cli/tests/conftest.py`, `ui/tests/conftest.py`, `test_u_sdka.py`,
`test_context_budget.py`** (`CARVED-r9`, gate r2-M2, §2.10b leg 5 —
forced by this unit's own D-1/B-1 code-gate folds, not by anything in
the census) ·
`ui/tests/` (additions only, **plus `test_routes.py`'s `CARVED-r7`
edits**, §2.10b leg 4) · `docs/specs/self-learn/{03,13,14,17,09-surface-spec}`
*(`09-surface-spec.md` ADDED-r7 — `DOC5`'s stale-quote fix, one line)* ·
this spec draft.

**Phase 2 [B]:** `cli/src/self_learn/{chezmoi,teach,cli,verbs}.py` ·
`ui/src/self_learn_ui/{routes,models}.py` ·
`ui/templates/{detail.html,partials/*.html}` · the named CLI and UI test
deletions.

**Explicitly NOT touchable, either phase:** `compilers.py` (the marker
contract and the byte-exact preservation rule are what make the region
hash meaningful — changing them invalidates `REC3`) · `records.py` ·
`ledger_ops.py` · `miner.py` · `worker.py` · `analyst.py` ·
`sentinel.py` · `serve.py` · any existing test function body — **except
the §2.10b census edits `S3` reconciles, the `_LOCKS` constant `PLAIN13`
changes, and the Phase-2 deletions `S5` reconciles** *(CARVED-r4, gate
r3-B1 leg 3: r3's blanket rule forbade the edits r3's own design
required)*. `UN3`'s stricter **name-set** rule still binds all ten host-git files —
nothing renamed, nothing deleted — while its **additions-only** rule binds
only the four of them absent from the census (`test_hosting_fixes.py`,
`test_init.py`, `test_gitops.py`, `test_batch_fixes.py`).
*(CORRECTED-r5, gate r4-B1.)*

*(r1 listed `reconcile.py` and `report.py` here; gates M-1 and B-2 removed
both. r2 listed `report.py` as Phase 2 only; gate r2-B1 moved it to Phase
1. `teach.py` and `ui/models.py` join the touchable set in r3 per gates
r2-B2 and r2-B3.)*

---

## 10. Interactions named, not solved

1. **The sentinel.** Unchanged. One runbook sentence: the sentinel pauses
   *a host's own autosync script*, and a host with no repo may still have
   one. Its semantics do not depend on git and are not mode-branched.
2. **`test_lock_invariant.py`.** §2.11 in full: green either way, a
   regression guard, never evidence (`UN5`, `PLAIN6`, `M26`). **And a
   builder who refactors the lock choice into a helper turns it RED** —
   safe, but it will look like a regression.
3. **`selftest` / `recompile` drift.** Already host-git-free (§2.4 item 5).
   The record ADDS a signal; `PLAIN8` pins the four-way rendering.
4. **The parked `_check_drift` / `_check_reach` real-home resolution
   discussion.** This unit changes what `_check_drift` *reads* for a
   plain host, never how either resolves a home. A builder editing home
   resolution has left this unit. *(Note the one thing r1 got wrong here:
   `_check_drift` DOES run one git call against the ledger, through
   `home_state` → `is_repo_root` — §2.4 item 5. That call is unchanged.)*
5. **`reconcile`.** Now IN scope, for the compile record only (§4.6). Its
   git usage, its `_BLOCKING_CODES` refusal and its pinned subject are
   unchanged (`RCN2`, `RCN4`).
6. **chezmoi and user scope.** Phase 2 (§4.8). Phase 1 must not touch
   `chezmoi.py` at all — that is a Phase 1 gate condition.
7. **`U-ancestry`.** See §11.

---

## 11. Parallel units

*(RE-STATED-r3, **AMENDED-r4/r5** — three phase attributions corrected
and the `_ledger_write` SPAN row added at r4 (gate r3-M4), preamble
relabelled at r5 (gate r4-N1). r2 added `reconcile.py`,
`report.py`, `ledger.py` and the UI consent; **r3 adds `teach.py`,
`ui/models.py`, `ui/templates/`, the six UI test files, and the wholesale
deletion of `chezmoi.py`** — and moves `report.py` and the whole user-scope
mechanism into Phase 1.)*

Three specs are being authored at the same base (`50fa815`):
**U-hostmode** (this one, `S-51`, `FW-122..124`), **U-ancestry**
(`S-52`, `FW-125..127`), **U-corrob** (`S-53`, `FW-128..130`).

| Surface | This unit | U-ancestry | U-corrob | My interface assumption |
|---|---|---|---|---|
| `hosts.py` — `Hosts` shape | Adds a per-entry mode; `skills_root` widened; `load_hosts` refuses unknown keys | Likely READS `hosts.projects` to find ancestors | — | **U-ancestry reads `Hosts.projects` / `Hosts.skills_root` through their existing accessors and does not construct `Hosts` positionally.** `MODE7` enforces that from my side. **New:** `MODE10` makes `load_hosts` REFUSE unknown entry keys — a sibling adding a hosts.yaml key must add it to the parser, not rely on the silent drop |
| `hosts.host_path_problem` | Mode branch; three existing refusals unchanged | May call it on an ancestor path | — | Signature `(home, path, kind) -> str \| None` and the three texts are pinned by `GATE3` |
| **`TargetSpec`** | **`host_repo` → `host_path`; new `mode` field; `None` unreachable after PHASE 1** *(CORRECTED-r4, gate r3-M4)* | May construct or read a spec for an ancestor | — | **THE settled answer to the gate's open question:** the mode rides a NEW field, not the repo path. A sibling constructing a `TargetSpec` must pass `mode`, and must obtain it from `hosts.host_mode` — never from `.git` presence (option 5, rejected R-b) |
| `verbs._resolve_target` | Mode-branches the existing branches' gate/dirty calls; **user branch rewritten in Phase 1** *(CORRECTED-r4, gate r3-M4)* | **Almost certainly adds a NEW branch** | — | **U-ancestry owns any NEW branch; I own the mode-branching of the existing ones.** Textual merge, not semantic |
| **Ancestor hosts and git** | `~/repos/3d-printing` is the most likely plain host on this machine (4 commits, no remote, whitelist `.gitignore`, git-inited 2026-08-25 solely to register) | Would inherit canon from it | — | **U-ancestry must NOT assume an ancestor is a git repo, must not call `gitops.paths_dirty`/`commit`/`push_if_remote` on one directly, and must route every ancestor host-phase decision through `spec.mode`.** This is now statable precisely, which it was not in r1 |
| `verbs._host_phase` | The ternary becomes a mode dispatch to `gitops.host_lock` | May add an ancestor host phase | — | Any new host phase takes `host_lock(path, mode)`, never `commit_lock(path)` |
| **`reconcile.py` / `ledger._LAYOUT`** | `_RECONCILABLE` gains `compiled/*.yaml`; `_LAYOUT` gains `"compiled"` | — | Tool-events may add a ledger artifact | **Any sibling adding a ledger artifact must ALSO extend `_RECONCILABLE`, or it has no H-5 backstop** — that is exactly the hole gate M-1 found in r1. Say so in their spec |
| **`report.py`** | **Phase 1** takes the rename of its four `.host_repo` reads and removes the two dead `is None` guards *(CORRECTED-r4, gate r3-M4)* | — | May add report rows | Additive; no conflict expected — but a sibling reading `spec.host_repo` will not compile after Phase 1 |
| **`chezmoi.py`** | **Phase 2 DELETES THE MODULE.** Its three module-level importers (`cli.py:38`, `verbs.py:84`, **`teach.py:75`**) and the UI's (`ui/routes.py:32`) all lose their import; four except tuples shrink | — | — | **No sibling may import `self_learn.chezmoi` at all**, and none may add a `ChezmoiAbort`/`ChezmoiError` catch. A sibling that does is a merge conflict to resolve, not a reason to keep the module. `CHEZ6`'s zero-literal sweep will find it |
| **`ui/models.py`, `ui/templates/`, the six UI test files** | Phase 2 deletes the adopt offer (§4.8.3): `models.py:305, 334`, `partials/adopt_offer.html`, `action_bar.html`'s `kind == "adopt"` branch, `evidence.html:46`, `detail.html:143-146` | — | — | No sibling is expected in the adopt surface. `UIC5` asserts zero `adopt` references remain in `ui/src` and `ui/templates`, so a sibling adding one reddens it |
| **The UI** | Phase 1: `build_host_add_argv` signature changes, `host_add_bar.html` consent copy replaced. Phase 2: the whole adopt surface goes | — | — | No sibling is expected in `ui/routes.py`'s registration triple or its adopt surface; if one is, this unit merges first. *(The gate correctly notes this is a scheduling assumption, not a checkable interface — it is the one row here that cannot be verified from the spec alone.)* |
| `cli._outcome_state` | Widens the `wrote_uncommitted` branch | May add a state | — | I widen an existing branch, add no state name; a sibling adding one must keep `wrote_uncommitted` reachable for plain hosts |
| **`_ledger_write`'s SPAN** *(NEW row in r4, gate r3-M4 — the r3 change with the broadest cross-unit effect)* | **Widened** to cover the pre-flight read, the compile, the compile record, the resolution commit and the host write; the push stays outside (§4.5b) | U-ancestry's analyst path takes no ledger lock and is unaffected; **any ancestor host phase it adds must nest `host_lock` inside `_ledger_write`, not beside it** (`REC12`) | U-corrob's worker/miner producers take `commit_lock(home)` for their own H-5 commits and **now contend across a local compile** — bounded, no network in the span, but measurably longer than a bare ledger commit | A sibling holding the ledger lock waits longer; a sibling adding a host write must take `gitops.host_lock(path, mode)` **in the callee, at entry, before its first ledger mutation** |
| `test_lock_invariant.py` | Green; **`_LOCKS` gains exactly one name, `"host_lock"`** (`PLAIN13`); `NOT_REPO_TRUTH` **unchanged** (`PLAIN6`) | Must also not grow `NOT_REPO_TRUTH` | Cache-dir writes likely already exempt | **No unit grows `NOT_REPO_TRUTH` this round.** A sibling adding a differently-named lock helper must add it to `_LOCKS` too, or its writes redden |
| `13-hosting-and-separation.md` §4 | Adds **item 5** to a four-item list | Likely amends §4 or §2 | — | Textual conflict expected; semantic not. My amendment scopes committability to git mode; a sibling's must not re-assert it unscoped |
| `03` / `14` | `S-51` / FW-122..124 | `S-52` / FW-125..127 | `S-53` / FW-128..130 | Reserved, disjoint. Ceilings `S-50` / `FW-121` re-confirmed by the gate |

**I design none of their features.** Where a row says what a sibling
"must" do, it is a constraint this design imposes on a shared surface.

---

## 12. Docs owed at merge

### 12.1 `03-decisions.md` — one new row after `S-50`

**`S-51` — the text is §3 of this spec, in full.** Provenance cell: this
spec; user ruling 2026-08-26 16:20 and the same day's framing question;
the concrete instance is `~/repos/3d-printing`, git-inited
`d4f7c17` 2026-08-25 solely to satisfy the requirement.

**One-paragraph form, for the row itself:**

> **S-51 — A canon host's version-control posture is a PROPERTY OF THE
> HOST, set once at registration: `git` (default; today's behaviour,
> byte-for-byte) or `plain` (no repo, no commit, no push).** Measured at
> `50fa815`: of 94 git call sites in the CLI, **38 are host-side, all in
> `verbs.py`, held by 11 functions**; of the eleven host-side operation
> classes, exactly two — the host commit and the host push — deliver
> anything, and the other nine are gates and plumbing that exist because
> those two do. Three of nine registered hosts are git repos ONLY because
> self-learn requires it, two of them carrying hand-written
> deny-by-default `.gitignore` files, and **three of nine have no remote
> at all**. **The user's own framing is adopted as the mechanism:**
> integrity moves to a ledger-side **compile record** — per target, the
> sha256 of the region the ledger says must be there, plus the previous
> one so an unlanded apply is distinguishable from a hand edit — written
> **inside the resolution's own ledger commit**, so it opens no new
> failure window. It is *stricter* than `git status` for the region
> self-learn owns, because it sees a **committed** in-marker hand edit
> that git is structurally blind to, while not refusing over out-of-marker
> edits the compiler provably preserves. Its promise is scoped honestly:
> the ledger holds self-learn's region, **15.8%** of the bytes of the 16
> files carrying one (44 654 of 283 204; **18.4%** across the 13 that are
> routable targets rather than worktree checkouts), and never the human's
> remainder — so `git` stays available and stays the default. **The
> overload this retires at the root:** `TargetSpec.host_repo is None`
> already meant "chezmoi user scope" in 17 shipped sites, five of which
> would have misrouted a plain project host into the chezmoi branch — so
> the field is renamed `host_path`, a `mode` field carries the posture,
> and **user scope becomes a first-class plain host** (`~/.claude`,
> measured: no VCS, and the largest managed section on the machine) whose
> write goes through the same plain path as every other plain host —
> **and, `(landed by Phase 2 of the same unit)`, `chezmoi.py` is deleted
> wholesale**, CLI and UI adopt surfaces included, chezmoi having been
> retired 2026-07-24 with zero `chezmoi-adopt` uses in 380 ledger
> commits. **Refused, so
> they are not rediscovered:** a global-only switch (this machine needs
> both values at once); auto-detection by `.git` presence (behaviour
> changing without a decision is what `S-10` was written against, and it
> is irreconcilable with Y-17's disclosed-consent contract); try/except at
> each of the 42 host-side sites (it destroys the exit-6-vs-7 distinction
> dispatch depends on); a second ledger commit for the record (its failure
> is post-mutation and would return exit 6 asserting, falsely, that
> nothing was written). **The one thing plain mode must not lose:** the
> `not a git repo` refusal is currently the only guard **on the
> skills-root legs** stopping a hand-edited hosts.yaml typo from getting
> canon written into it (a typo'd *projects* entry is caught first by
> `_project_host_or_refuse`'s registration match), so plain mode ships a
> replacement predicate — a `.self-learn-host` marker written by
> `host add --mode plain` — not an omission.

**No amendment to any existing row is owed.** `S-6`, `S-10`, `S-12`,
`S-17`, `S-23`, `S-50` all survive verbatim. `S-17`'s D3 (*"pushes are
MANUAL"*) is reinforced: a plain host has nothing to push.

### 12.2 `14-forward-work-map.md` — three new rows

Highest existing row at `50fa815`: **FW-121** (gate-confirmed). Header:
`| # | Item | Type | Trigger / when |`.

| # | Item | Type | Trigger / when |
|---|---|---|---|
| **FW-122** | **Canon hosts are git-optional: `mode: git \| plain` on the hosts.yaml entry, set once at `host add --mode`, defaulting to `git`; a ledger-side compile record is plain mode's integrity instrument; user scope becomes a first-class plain host and the chezmoi adopt surface is deleted.** Measured before the build: 38 of 94 git call sites are host-side, all in `verbs.py`, held by 11 functions; 3 of 9 registered hosts are repos only to satisfy the requirement (`keyboards` `2085fe3`, `.config` `fc5b7dc`, `3d-printing` `d4f7c17`), 2 of those needing whitelist `.gitignore`s; **3 of 9 have no remote**; `~/.claude` has no VCS and holds the largest managed section on the machine (19 279 B). The record is **stricter than `git status`** for the region self-learn owns and rides the resolution's own ledger commit. `TargetSpec.host_repo is None` — which meant "chezmoi user scope" in 17 sites — is retired at the root. Git hosts stay byte-identical, proven by the `UN` group. | BUILD | Landed by `U-hostmode` (Phase 1 + Phase 2) |
| **FW-123** | **The lock-invariant walker cannot see whether a `host_repo is None` write is actually serialized, by design, and plain mode widens that blind spot.** `test_lock_invariant.py`'s `_is_lock` walks the whole expression subtree specifically so `lock = commit_lock(r) if r else nullcontext()` — `verbs._host_phase`'s real shape — counts as guarded, without evaluating the condition (its own docstring says so). **Gate-replicated 2026-08-27:** the ternary with a `nullcontext()` plain branch leaves the walker GREEN; replacing the assignment outright leaves zero guarded lines and turns it RED. **Mitigated, not closed:** plain hosts get a real cache-dir lock (`${XDG_CACHE_HOME:-~/.cache}/self-learn/host-<slug>.commit.lock`, keyed by host path for the sentinel's own reason) and a **two-process** runtime serialization test — never threads, because `gitops._held_locks` makes a same-process re-acquire a pass-through. **The residual is the walker's approximation itself**, a deliberate trade. | WATCH | Trigger: a third `nullcontext`-shaped host phase appears, or a real concurrent-write corruption is observed on a plain host |
| **FW-124** | **`09-surface-spec.md` §11 Y-17's committability sentence is stale on one of its three clauses, and the row is a ratified decision, so it is not corrected in passing.** It reads: *"canon writes are commits; audit, rollback, and recompile all diff against git (13 §4)"*. Measured 2026-08-27: **recompile does not diff against git** — `verbs.recompile` branches on `compile_result.changed`, a content comparison inside `compilers` (`verbs.py:4829-4838`); its git use is the dirty skip and the commit. Nor does drift detection: `selfcheck._check_drift` looks for the `(lrn-…)` entry marker in the target's managed section, and **zero of the nine `--selftest` rows diff a HOST against git** (three consult `ledger.home_state`, whose `is_repo_root(home)` runs one git call against the LEDGER — `ledger.py:70`). Audit and rollback are genuine, and are why `git` mode stays the default. **The real cost:** a reader following Y-17's wording concludes that removing git removes drift repair, which is false, and would over-scope any future git-optional work. `U-hostmode` scopes the *requirement* to git mode in `13 §4` and leaves Y-17's text alone. | BUILD | Not scheduled. One-line docs correction: restate as "audit and rollback diff against git; drift detection and recompile do not". Belongs with whoever next touches Y-17 |

### 12.3 `13-hosting-and-separation.md` — the §4 amendment

*(CORRECTED-r2, gate D-4: §4's numbered list has **four** items at lines
131–149 — ledger-first two-phase; crash-between-phases drift check;
rejected-proposal digest; sentinel contract shrinks. The new item is
**5**, and it refers to items **1–4**.)*

> **5. Hosts are git-optional (added by `U-hostmode`).** A registered host
> carries a **mode** on its `hosts.yaml` entry: **`git`** (the default,
> and what every entry written before this unit means) or **`plain`**. A
> `git` host behaves exactly as items 1–4 describe. A **`plain`** host
> requires no repository: nothing is staged, committed, or pushed there,
> and the two-phase rule of item 1 collapses to its ledger half. The mode
> is set ONCE, by `self-learn host add --mode git|plain`;
> `config.yaml`'s `hosts.default_mode` sets the default for new
> registrations, fail-closed to `git` (the `S-10` discipline). `host add
> --init` is unchanged and remains a **git**-mode convenience — `--mode
> plain --init` is a usage refusal, not a silent preference. A plain host
> is gated at registration and at every route by a `.self-learn-host`
> marker file the registering verb writes — the structural analogue of
> `.git`, and the replacement for the committability check, not its
> omission. **User scope (`~/.claude`) is a plain host by construction**:
> it is never registered, carries no marker, and its mode cannot be
> anything else.
>
> **What replaces git for a plain host, and what does not.** Item 2's
> drift check is unaffected: it was never a git check — it compares the
> ledger's routed records against `(lrn-…)` entry markers in the target,
> and `self-learn recompile` remains the one-command repair (H-2). What IS
> replaced is the **dirty gate**. A plain host is gated by a
> **ledger-side compile record** — `<home>/compiled/<host-slug>.yaml`, one
> entry per target, carrying the sha256 of the region the ledger says must
> be there and the sha256 of **the state that write was based on** — the
> region as it was observed on disk at pre-flight. A region matching the
> current hash is clean; matching the based-on hash means our own apply
> did not land (drift — `recompile` repairs it, however many times in a
> row it fails); matching neither was hand-edited and the route refuses,
> naming `recompile --adopt`. **This is
> stricter than `git status` for the region self-learn owns** — it catches
> an in-marker hand edit the human has already COMMITTED, which
> `git status` reports as clean — and narrower where narrowness is
> correct: an edit outside the markers no longer refuses a write the
> compiler preserves byte-exactly. The record is written for **git** hosts
> too; only the *gate* differs by mode. It is written **inside the
> resolution's own ledger commit**, under the ledger `commit_lock`, before
> that commit — so it opens no second failure window, and a failure of
> that commit is already `HalfWrittenError` (exit 7), never a false exit 6.
> It is swept by `self-learn reconcile` like every other ledger artifact
> (§5's corollary applies to it, and `_RECONCILABLE` was extended so that
> is true and not merely asserted).
>
> **What a plain host gives up, stated plainly.** No `git log` or
> `git blame` over the compiled canon, no `git revert` of a canon commit
> (already not a correction mechanism — `S-12`), and **no off-machine
> backup of the host's file**. A ledger-side record is a record of
> self-learn's own region, not a backup of the user's file: measured
> 2026-08-27, self-learn's region is **15.8%** of the bytes of the sixteen
> files carrying a managed section (44 654 of 283 204; **18.4%** across
> the thirteen that are routable targets rather than `.claude/worktrees/`
> checkouts). A user whose host content wants history should use `git`
> mode, which is why it is the default.

**And item 1 gains a leading clause:**

> 1. **Ledger-first two-phase** *(for a `git`-mode host; a `plain` host
>    runs the ledger phase and then applies canon without a host commit —
>    item 5)*. A resolution verb commits the ledger change …

**The clause for §8's `H-3` bullet** — append: *"A registered host need
not be a git repository: `U-hostmode` makes version control a per-host
mode (`git` default, `plain` opt-in). H-3 itself is unchanged — compile
targets still come from hosts.yaml only, and a plain host is gated by a
`.self-learn-host` marker the registering verb writes, never by being
writable."*

### 12.4 `17-invocation-runbook.md`

- **A new section, `host modes`** — what `--mode plain` does and does not
  do; the consent lines `host add --mode plain` prints; how to change a
  mode (`host remove` + `host add --mode`); the `.self-learn-host` marker
  and that `host remove` leaves it; `recompile --adopt` and when to reach
  for it; and the explicit note that **`--selftest` and `recompile` work
  identically on both modes**, because that is the first thing an operator
  will assume they do not.
- **A rollback PROCEDURE in §6** *(CORRECTED-r2 at gate D-5;
  STRENGTHENED-r3 at gate r2-M1, which measured that no forward code
  change can close this — `MODE10` hardens the new parser, and after a
  revert the new parser is gone.)* Reverting this unit leaves any
  `mode: plain` **projects** entry silently re-read as a **git** host: the
  reverted parser accepts `{path, mode}` and drops the `mode` key
  (`hosts.py:150-155`); only a `skills_root` MAPPING raises `HostsError`.
  **The hazard is a silent resumption of host commits into a directory the
  user chose to keep repo-less, not a crash** — so the revert is not safe
  to perform blind, and the runbook carries three numbered steps:
  **(1) `self-learn host list`** and note every host whose mode reads
  `plain` (`MODE11` is why that column exists);
  **(2)** for each, either `git init` it — making the reverted code's
  git-mode assumption true — or `self-learn host remove` it;
  **(3)** commit or delete the `<home>/compiled/*.yaml` files, then revert,
  Phase 2 before Phase 1. *(CORRECTED-r4, gate r3-D6: r3 said they "need
  no cleanup". They are inert to the reverted code — nothing reads them —
  **but they are also UNSWEPT by it**: the revert takes `compiled/*.yaml`
  out of `_RECONCILABLE`, so any uncommitted record file becomes exactly
  the H-5-corollary orphan §4.6 exists to prevent — "committed by nobody,
  ever … until a clone deletes it".)*
- **One sentence in the user-scope section:** *"`~/.claude/CLAUDE.md` —
  the user-scope canon target — is not in any git repository and has not
  been since chezmoi's retirement (measured 2026-08-27:
  `git -C ~/.claude rev-parse` exits 128). The local git repo in
  `~/.config` is a different thing: `~/.config` is a registered
  **project** host, and its `CLAUDE.md` is project-scope canon. Both
  statements are true; they are about different files."*

---

## 13. Questions — all RULED

*(r1 opened four. All four are now ruled; none is left open for the
build.)*

| # | Question | Ruling |
|---|---|---|
| **Q-1** | The H-3 replacement guard: marker file, pre-flight existence check, or the weaker gate? | **RULED: the `.self-learn-host` marker file** (§4.4), the structural analogue of `.git`. r1's recommendation, accepted |
| **Q-2** | Should the UI expose the mode? | **RULED, OVERRULING r1: yes — the mode IS the consent choice**, replacing the init disclosure rather than sitting beside it (§4.9). r1 recommended suppress-only; the ruling is that a consent moment should present the actual choice |
| **Q-3** | Should user scope become a first-class plain host? | **RULED, OVERRULING r1: yes, in this unit — and, after gate r2-B1, in PHASE 1.** r1 recommended deferral on footprint grounds; the ruling is that deferring leaves the root cause — the `host_repo is None` overload — alive inside the unit that exists to remove it. r2 put it in Phase 2, which made Phase 1 unbuildable (`host_lock(None, …)`); r3 puts the whole mechanism in Phase 1 and leaves Phase 2 as pure deletion |
| **Q-4** | How hard is "set once"? | **RULED as r1 recommended: no new verb.** Settable at registration; a mode-flipping re-add refuses 64; change is `host remove` + `host add --mode` (R-f) |

**Open for the BUILDER to measure, not for the orchestrator to rule:**

1. The representation of modes inside `Hosts` (parallel mapping vs a
   `HostEntry` type). Constrained by `MODE7`, not by this spec.
2. Whether `region_dirty` lives in the new compile-record module or in
   `compilers.py`. `compilers.py` is untouchable (§9), so the default is
   the new module; a builder who finds a reason to disagree must say so
   in the build report.
3. The exact wording of the two UI consent options. `UIM1` pins the
   behaviour, not the copy.

---

## 14. What could NOT be measured

1. **Whether plain mode is actually less cumbersome for a real new user.**
   Everything in §2.1 measures *this* machine's cost of the current rule.
   It is direct evidence of friction, not of another user's experience.
2. **Whether the compile record's refusal would fire in practice.** The
   committed-in-marker-hand-edit hazard (§2.4 item 3) is a *structural*
   property of `git status`, read out of the code. **No instance of it
   occurring has been observed in the 98 host-side self-learn commits** —
   not evidence it never happened, since nothing was watching.
3. **The compile record's own footprint.** It stores two 64-char hashes
   plus four small fields per target, not the bytes — far smaller than
   §2.7's ≈273 KB figure, which prices the *rejected* snapshot option
   (R-d) to answer the user's question honestly.
4. **How many of the 22 CLI and 6 UI chezmoi-referencing test files need
   EDITS rather than DELETIONS.** §2.10a now measures the whole surface
   (205 / 343 / 12 / 7 / 43 hits, per-file), and §4.8.1 item 3 measures
   the Phase-1 slice exactly (36 of 69 functions in
   `test_a2_rules_local.py`). What is still unmeasured is the edit/delete
   split across the remaining files; `S3` and `S5` force the builder to
   reconcile each one by name rather than estimate.
5. **Whether `U-ancestry` will in fact touch `_resolve_target`.** §11's
   sibling assumptions are constraints stated from this side; their specs
   were not read.
6. **`git status` behaviour on a host whose `.gitignore` excludes the
   canon target.** `repos/3d-printing`'s whitelist tracks `CLAUDE.md`
   explicitly so the case does not arise there, but a plain-turned-git
   host whose ignore rules exclude the target would make `paths_dirty`
   silently always-clean. Not measured; not this unit's.
7. **Any live CLI verb run against the real ledger.** `~/.self-learn` was
   read-only throughout: `cat`, `ls`, `git log`, `git status`, `du`,
   `count-objects`. No verb was executed against it; the daemon was not
   touched. *(The blind gate noted this self-report is unfalsifiable from
   outside; it is restated, not strengthened.)*
8. **`misc/verb-coverage-2026-08-26.md`'s queueing claim.** The gate could
   not read the file (local-only, out of bounds). The finding this spec
   cites it for — user-scope has no VCS — was re-measured independently
   and confirmed (§2.6); the queueing claim and the `U-verbs` row remain
   **unverified by any second party**.
9. **Whether the widened ledger-lock span (§4.5b) measurably delays a
   concurrent capture.** The reasoning is structural — the span gains a
   local compile and a local `git commit` and still excludes the push, so
   the network-timeout case that motivated the round-3 narrowing cannot
   occur. **No timing was measured**, and none is claimed. If a burn-in
   shows `teach` latency moving, that is the row to reopen.
10. **Whether any of the 497 `docs/` chezmoi mentions become misleading
   once the module is gone.** `CHEZ6` deliberately does not sweep `docs/`
   (they are history), and no audit of them was performed. The two specs
   most affected — `c2-chezmoi-capability-spec.md` (115 hits) and
   `a2-rules-local-spec.md` (58) — describe shipped behaviour that Phase 2
   removes; whether they need dated "superseded by U-hostmode" banners is
   a docs-sweep question this unit does not answer.

---

## R. Revision history

- **r1** — 2026-08-27, authored at `50fa815`. Census measured; six-option
  map with the user's framing steelmanned and priced; recommendation
  Option 3; 46 criteria in seven groups; 25 mutations; four open
  questions. **Blind spec gate r1: NOT SOUND** — 3 blockers, 6 majors, 12
  docs, 3 nits. The census reproduced exactly except six numbers.
- **r2** — 2026-08-27, folded in place. Plain became a real mode with
  `TargetSpec.mode` and the `host_repo`→`host_path` rename (`B-1`); the
  17-site overload was re-keyed and user scope made a first-class plain
  host (`B-2`); the compile record moved inside the resolution's own
  ledger commit (`B-3`); `reconcile.py`, `ledger._LAYOUT`, `commit_drift`,
  `report.py` and the UI consent came into scope (`M-1`–`M-3`); the
  predicate became a six-case table (`M-4`); `PLAIN5` became two
  processes (`M-6`). 80 criteria, 45 mutations, six numbers corrected.
  **Blind spec gate r2: NOT SOUND** — 4 blockers, 4 majors, 8 docs, 1 nit.
  **Every r1 finding verified closed**: the 17-site re-key independently
  re-derived and complete, the `_commit_ledger` anchor confirmed at
  `verbs.py:513-537`, `R-k` confirmed, `CD1`'s exit 64 confirmed, and
  every corrected number re-measured as right. The new findings were all
  in the surface the fold opened.
- **r3** — 2026-08-27, folded in place. Phase 1 made independently
  buildable (`report.py` + the whole user-scope mechanism moved into it);
  `chezmoi.py` deleted wholesale in Phase 2 with the deletion list turned
  into a pasted census and the UI adopt surface given group `UIC`;
  `prev_sha256` → `based_on_sha256` (the pre-flight observation), closing
  the H-2 contradiction; the lock span widened. 92 criteria, 55 mutations.
  **Blind spec gate r3: NOT SOUND** — 1 blocker, 4 majors, 6 docs, 1 nit.
  **Every r2 finding disposed**, and the four hardest ones upheld by
  re-derivation: the gate re-walked `based_on_sha256` through three
  consecutive failures, failure-then-hand-edit and failure-then-revert;
  re-ran all eight chezmoi counts (seven exact); and ruled the
  USER1–USER7-in-Phase-1 call **correct on the merits** — *"the decision
  is correct; only its budget is wrong."*
- **r4** — 2026-08-27, folded in place. **No design change; a re-census
  and three wiring pins.** **§2.10b is new** — the Phase-1 disturbance
  census r3 stated as one sentence: 42 `chezmoi_bin` kwarg sites across
  five test files (**23 outside `test_a2_rules_local.py`**), 87
  chezmoi-mentioning test functions across 20 files, and 6 of
  `test_commit_drift.py`'s 18 functions exercising the user leg §4.7
  deletes. Four statements that contradicted it are struck or restated:
  §5.0 row 7, §4.8.1 item 3, **`CD2`** (now "12 git-mode byte-unedited / 6
  user-leg REWRITTEN", the six named, `M56`) and **`S3`** (now "no test
  outside the census is touched", with a positive control); §9's Phase-1
  list gains every census file and its "no existing test body" rule is
  carved for them (`r3-B1`). **Three lock pins** (§4.5b rebuilt): the host
  lock lives in the CALLEE — `_host_phase` and `_retirement_host_phase`,
  at entry — so all six `_host_phase` call sites are covered and
  `supersede`/`graduate` do not write the host unlocked (`r3-M2`,
  `REC12`, `M57`); it opens **before `resolve_record`**, so a lock timeout
  cannot return exit 6 over a moved record (`r3-M3`, `M58`); and
  `test_lock_invariant.py`'s **`_LOCKS` gains `"host_lock"`** — a detector
  constant, not a `NOT_REPO_TRUTH` exemption — replacing r3's irrelevant
  widening argument (`r3-M1`, `PLAIN13`, `M55`). **§11** corrected on
  three stale Phase-2 attributions and given a new row for the widened
  `_ledger_write` span, naming what U-ancestry and U-corrob may observe
  (`r3-M4`). **Also folded:** `ui/tests`'s chezmoi census (43/five files)
  separated from the adopt census (59/six) that r3 printed under its label
  (`r3-D1`); `docs/` quoted as **421 excluding this draft** (`r3-D2`);
  §6's preamble "three anchors" → **ten** (`r3-D3`); `CHEZ2` reconciled
  with `CHEZ6`'s exemption (**returns 2, not 0**) (`r3-D4`); `CHEZ4`
  recorded as retired rather than missing (`r3-D5`); §12.4 step 3 now says
  the record files are inert **and unswept**, so commit or delete them
  before reverting (`r3-D6`); `based_on_sha256` stated `null` for the
  `missing` row as well as `fresh` (`r3-N1`).
  **Two phases, 93 criteria (81 [A], 12 [B]) across 14 groups, 59
  mutations.**
- **r6** — 2026-08-28, folded in place by the orchestrator: three post-SOUND gate nits (r5-D1 `git -C <home>`; r5-N1 nine; r5-N2 CD2 names kept deliberately) and absolute home paths scrubbed to `~`. No re-gate (repricing rule 2026-07-26).
- **r5** — 2026-08-27, folded in place. **No design change, no new
  criterion, no new mutation: one criterion carve, one AST-check
  correction, and an instrument audit.** **`UN3` and `CD2` now compose**
  (`r4-B1`) — r4 carved §9's blanket "no existing test body" rule for the
  §2.10b census and then re-asserted `UN3` over ten files, **six of which
  the census requires editing** (`test_commit_drift.py` REWRITE ×6,
  `test_verbs.py`, `test_pointer.py`, `test_resolution_evidence.py`,
  `test_m2_verbs.py`, `test_hosting.py`), leaving two `[A]` criteria with
  no precedence between them. `UN3`'s instrument is now split: the
  collected-**name**-set diff binds unconditionally over all ten (nothing
  renamed, nothing deleted — a rewrite keeps its name), the
  additions-only diff binds only the four non-census files
  (`test_hosting_fixes.py`, `test_init.py`, `test_gitops.py`,
  `test_batch_fixes.py`), and §9's clause matches.
  **`REC12(a)` no longer demands a lock at a function with nothing to
  lock** (`r4-M1`): `_retirement_host_phase` (`:2281`) holds no host path
  — its first statement is `if retirement.spec is not None:` and both
  branches delegate to a callee that locks (`_host_phase:2302`,
  `_remove_hook_script:2317`), its third path writing nothing — so it is
  dropped from (a), kept under (b)'s coverage, and `_remove_hook_script`
  joins (b). (b)/(c)/(d), `M57` and `M58` are unchanged.
  **§5.13 is new — the diff-instrument audit** (`r4-D1`): all three
  `git diff` checks were cwd-relative and failed OPEN, which I reproduced
  at `50fa815` rather than quoting — the same commit range prints three
  real files with a root-relative pathspec and **nothing, rc 0** with the
  spec's. `S3`, `UN3`'s diff half and `PLAIN6` are now cwd-pinned and each
  must be **NON-EMPTY before** its membership check runs; the audit states
  the rule once and records that every other `git` instrument here is
  already `git -C`-explicit or names its directory. **Also folded:**
  `S3`'s carve now admits the `_LOCKS` edit `PLAIN13` requires
  (`r4-D2`); "the eight one-hit files" → **nine** at both live sites, and
  §2.10b's closing sentence now names `test_m2_verbs.py`,
  `test_compilers.py` and `test_retirement_cleanup.py`, which its own
  table marks EDIT (`r4-D3`); §11's preamble relabelled (`r4-N1`).
  **Counts unchanged: two phases, 93 criteria (81 [A], 12 [B]) across 14
  groups, 59 mutations, 10 measured anchors.**
- **r7** — 2026-08-28, folded in place during the Phase 1 build itself
  (builder disclosure per the coordinator's ruling that "satisfied by
  construction" claims must be verified, not a re-gate; repricing rule
  2026-07-26 — no design change, no new criterion, no new mutation).
  **§2.10b gains leg 4**: six files the chezmoi-mention census could
  not have found (none mention chezmoi) but that Phase 1's OWN `[A]`
  behavior changes force — `test_provider.py` (`MODE3`'s new export),
  `test_round3_fixes.py` (`REC12`/§4.5b's widened lock span inverts
  `TestLockScope`'s premise), `test_route_cli.py` (`REC9`'s compile
  record riding the route's own ledger commit), `test_u_fake.py` and
  `test_worker_contract.py` (cascading DS1/armor re-pins forced by the
  `test_route_cli.py` edit), and `ui/tests/test_routes.py` (`UIM1`/
  `UIM2`'s always-present `--mode` argv breaking literal `runner.calls`
  assertions, plus a radio-aware fix to `_confirm_form_fields`). Each
  carries its forcing criterion and the assertion that broke, one line
  per file. `§9`'s Phase-1 file list and `S3`'s positive-control
  membership rule are both widened to admit them, so `S3`'s own control
  command is a true statement rather than a false negative against work
  the spec's census structurally could not anticipate.
  **`DOC5`**: `09-surface-spec.md:1917`'s stale quote — "canon hosts
  must be committable" stated as an unqualified rule inside an
  ONBOARDING-copy illustration — is mode-qualified in place ("a
  git-mode canon host must be committable"), matching the `hosts.py`
  hits' own existing "when `mode == \"git\"`" phrasing; `09-surface-
  spec.md` is added to §9's touchable file list for this one line.
  **A real UN8 defect found and fixed during the build, no criterion
  or number change**: refactoring `commit_lock`'s flock body into the
  new shared `_flock_lock` (feeding both `commit_lock` and `host_lock`)
  left the timeout error's suffix hardcoded to `"wedged mid-write"`
  instead of parametrized on `wedged_by`, silently changing the
  LEDGER's own `commit_lock` timeout text from 50fa815's
  `"...wedged mid-commit"` to `"...wedged mid-write"` — a byte-identity
  break `UN8` names explicitly, with no prior test pinning the string.
  Fixed in `gitops.py` (one line, `wedged_by` used in both places the
  message already had it once); a new dedicated test asserts the
  ledger's timeout text ends `"wedged mid-commit"`, RED-then-restored
  with sha256 verification during the build.
  **Counts unchanged: two phases, 93 criteria (81 [A], 12 [B]) across 14
  groups, 59 mutations, 10 measured anchors.**
- **r8** — 2026-08-28, folded in place during the Phase 1 code gate r1
  fold (2 blockers, 12 majors, 9 nits, 5 defers — z-note
  `4M9w4buPr9FC80nmjeect`; no design change, no new criterion, no new
  mutation — three wording corrections this document itself owed).
  **N-6**: `FW-122`'s Trigger column (here and in
  `14-forward-work-map.md`, kept verbatim per `DOC2`) claimed "Landed
  by `U-hostmode` (Phase 1 + Phase 2)" while Phase 2 (`chezmoi.py`'s
  deletion, the UI adopt surface) had not landed — corrected in both
  files, identically, to name Phase 1 landed and Phase 2 pending.
  **D-5**: the §6 mutation table's `M44`, `M51`–`M54` rows (Phase-2-only
  `[B]` criteria `CHEZ2`, `CHEZ5`, `UIC1`, `UIC3`, `UIC4`) gain an
  explicit "not runnable at Phase 1's own gate" note — the deletions
  they mutate have not happened yet, which the table did not previously
  say. **N-7**: `UIM1`/`UN4` both claimed rendering "byte-identical to
  `50fa815`'s" — true and unaffected for `UN4` (`host list`'s CLI text,
  scoped in place with a note explaining why it was named alongside
  `UIM1` without sharing its defect), but unachievable by construction
  for `UIM1` once §4.9's two-option consent radios — new in this build,
  `50fa815` had none — replace the git-init disclosure outright.
  `UIM1` restated to the SEMANTIC property its own test
  (`ui/tests/test_routes.py::TestUIM1DefaultModeConfig`) actually
  asserts: correct radio pre-selection plus the disclosure text
  rendering exactly when `_needs_init(path)` holds. Test docstrings
  updated to match (assertions unchanged).
  **Counts unchanged: two phases, 93 criteria (81 [A], 12 [B]) across 14
  groups, 59 mutations, 10 measured anchors.**
- **r9** — 2026-08-28, folded in place during the Phase 1 code gate r2
  fold (0 blockers, 4 majors, 8 nits, 3 defers — z-note
  `DdsHWMKAs3rCSwQ9knYnM`; both r1 blockers and 11 of r1's 12 majors
  verified fixed).
  **M-1**: `supersede` and `graduate` now open
  `with _ledger_write(home), <host lock>:` as ONE combined statement,
  ledger item first — matching `route`'s and `route_direct`'s shape --
  instead of nesting the host lock inside a separate ledger-write block
  in the opposite order. `REC12` gains leg (e), instrumenting the
  acquisition ORDER itself (not just presence) across all five
  host-writing verbs, plus a real two-process runtime probe proving the
  fixed order does not deadlock (`gitops.COMMIT_LOCK_TIMEOUT` patched low
  for the probe only). **§4.5a and `REC5` gain a seventh
  case** (`M-3`): `entry absent + region present` splits on whether the
  on-disk bytes match `_expected_managed_region`'s current render --
  a match self-adopts automatically (one printed notice, record entry
  written in the same commit as the in-flight route); a mismatch still
  refuses, naming `recompile --adopt`. This is what makes every
  pre-existing host migrate itself on its first post-upgrade route with
  no separate migration step — §4.13 and runbook 17 both gain the
  paragraph saying so, and `selfcheck`'s drift summary gains a count of
  targets still missing a record. **`MODE6a` is new** (`M-4`): the named
  repair (`host remove` + `host add --mode`) must actually repair --
  `host add --mode plain` on an already-registered plain host now
  re-asserts a missing `.self-learn-host` marker instead of returning
  early with it still absent. **`GATE3` narrowed** (`N-2`): only the
  three refusal TEXTS are pinned byte-identical now, not the function
  signature — `host_path_problem` gains keyword-only `mode` and
  `check_marker` params so `host_add` can finally reuse it for the
  git-repo and ledger-home checks instead of duplicating their text.
  **`compiled.refuses`'s docstring rewritten** as one statement of the
  now-seven-row table (`N-1`). **§2.10b gains leg 5** (`M-2`, this fold's
  own finding): `cli/tests/conftest.py`, `ui/tests/conftest.py`,
  `cli/tests/test_u_sdka.py` and `cli/tests/test_context_budget.py` --
  all four touched by r1's own D-1/B-1 folds, none admitted by section 9's
  file list or `S3`'s positive-control whitelist until now. Section 9 and `S3`
  are both widened to admit them, so `S3`'s own membership check is a
  true statement again. Also folded: `recompile` batches every automatic
  resync write into ONE commit per invocation instead of one commit per
  changed target (`N-6`); `_resync_region_entry` gains an explicit
  `delete: bool = False` param so an unknown expectation is never
  conflated with a deliberate removal (`D-2`); the two
  `assert old_record is not None` invariant guards become explicit
  `raise VerbError(...)` so they survive `python -O` (`D-3`); the
  §2.10b/`test_kind_coverage_table` walker's `expected_kinds` now derives
  from `compiled.REGION_KINDS` itself, with a union-check control
  (`N-7`); standalone resync commit subjects name the host by
  `hosts.host_subject_name()` (basename + short digest, `user` for user
  scope) rather than a path-derived slug shape — though after `N-6`'s
  batching a subject can no longer name a single host, so the function
  is unit-tested in `hosts.py` but not called from `verbs.py` (`N-8`);
  five stray lock files an earlier ad-hoc probe left under the real
  `~/.cache/self-learn` are deleted, and every ad-hoc script from now on
  sets `XDG_CACHE_HOME` to a temp dir (`D-1`); `N-3` through `N-5`
  are wording-only (the spec header's stale "Uncommitted" sentence, a
  stale comment naming a symbol that never existed, and §9 naming the
  one real new test file instead of a second file never created).
  **`REC5` and `REC12`'s criterion text (§5.2), §4.5a's own table and
  `GATE3` (§5.3) are updated to describe the shipped seven-case predicate,
  the fifth lock-order leg and the narrowed signature claim** — none of
  this was asked verbatim by the gate ruling, but leaving them describing
  the six-case predicate and the four-leg lock check after landing the
  code that supersedes both would have been a stale spec shipped
  alongside working code, the exact class of defect this gate exists to
  catch.
  **Counts: two phases, 94 criteria (82 [A], 12 [B]) across 14 groups
  (`MODE6a` added), 59 mutations, 10 measured anchors.**
- **r10** — 2026-08-28, folded in place during the Phase 1 code gate r3
  fold (CLEAN — 0 Blockers, 0 Majors, 5 Nits, 2 Defers; z-note
  `fFcid-IaulaB12061FOCD`; no re-gate, all five bounded). N-1:
  `hosts.host_subject_name` deleted — its `__all__` entry and its three
  direct unit tests (`TestN8HostSubjectNameNeverTheFullPath`) — dead
  code after N-6's batching already meant nothing called it. N-2: one
  sentence added to `03-decisions.md`'s `S-51` row, to
  `13-hosting-and-separation.md` §4 item 5, and to this spec's own §3.3
  item 5, each stating REC5's seventh row in one line: a route
  self-adopts pre-existing marker-bounded content only when it is
  byte-identical to the compiler's render, and still refuses (naming
  `recompile --adopt`) otherwise. N-3: the marker-repair `print()` moved
  OUT of `hosts.py` — `host_add` now returns a new `HostAddResult`
  dataclass (`.hosts`, `.marker_restored: bool`) instead of a bare
  `Hosts`, and `cli.py::_cmd_host_inner` prints "marker restored" from
  the returned signal. The one production caller and the seven
  `test_hosting.py` call sites that captured the return value as a
  bare `Hosts` gained a trailing `.hosts`; the two
  `TestM4NamedRepairActuallyRepairs` call sites that already captured
  it as `result` needed no such change — that class gained a new
  CLI-driving test plus a `result.marker_restored` assertion on the
  existing library-level ones. N-4: `_resolve_local_target` built two
  byte-identical `TargetSpec` calls, one per branch of its
  `if check_dirty:` — now builds it once, before the branch, and returns
  the same `spec` either way. N-5: the mutation table's `M25` row is
  split — `M25a` (drop `PLAIN4`'s positive control) is marked a
  META-ROW, not independently reddenable by construction (deleting a
  test's own control removes evidence, it does not redden an
  assertion); `M25b` (the stray `subprocess.run(["git", "status"], ...)`
  actually inserted into `_host_phase`'s plain branch, gate r2 M-6's
  find) is the row that reddens and is `M25a`'s proof. `PLAIN4`'s own
  criterion text (§5.4) updated to match. D-1/D-2 left exactly as r9
  documented them — no action, per the gate's own ruling.
  **Counts: two phases, 94 criteria (82 [A], 12 [B]) across 14 groups,
  60 mutations (`M25` split into `M25a`/`M25b`), 10 measured anchors.**
- **r11** — 2026-08-28, folded in place during the Phase 2 code gate r1
  fold (NOT CLEAN — 0 Blockers, 3 Majors, 2 Nits, 2 Defers; z-note
  `ayhM7pjRlJKgqwEGhSKMi`; no re-gate, every finding text/census scope).
  **The deletion itself was already clean and complete** — all 12 `[B]`
  criteria discriminate, all 10 mutations run RED, the census reproduces
  exactly, UN3 held — what the gate found is that the SPEC never
  described Phase 2 landing, and one ratified doc still asserted retired
  behaviour in the present tense. M-1: three criteria amended to
  describe the shipped docs instead of the interim wording they still
  pinned — `DOC1` no longer requires `03-decisions.md`'s two Phase-2
  parentheticals (they are correctly gone once both phases exist under
  one unit; positive control is the replacement sentence, and the same
  grep at Phase 1's own tip returns 2, proving the instrument would
  have caught an un-updated row); `DOC2`'s §12.2 FW-122 cell is updated
  to the LANDED text ("Landed by `U-hostmode` (Phase 1 + Phase 2)"),
  replacing r8's interim wording, in both the spec and the live
  `14-forward-work-map.md` row; `PLAIN6` now explicitly permits the
  `NOT_REPO_TRUTH` shrink by three dead exemptions this unit's own
  deletion causes (`chezmoi._run`, `chezmoi.compile_user_scope`,
  `chezmoi.preflight_user_scope`) and `_ARGV_FOR` losing
  `_cmd_chezmoi_adopt`, alongside the one-name `_LOCKS` change — the
  "not grown" rule holds; "unchanged" was never the rule. M-2: `CHEZ6`
  and `CHEZ3`'s criterion texts now state the MEASURED shipped
  accounting instead of stale predictions — `CHEZ6`: 37 `cli/tests`
  hits in six categories (22 UN3-protected names, 14 documenting the
  unrelated real `chezmoi cd` hook guard, 1 absence assertion), not
  "one migration note"; `CHEZ3`: the deletion set is five files (the 20
  in `test_a2_rules_local.py`, the 13 in `test_chezmoi.py`, one each in
  `test_compilers.py`/`test_regime_fixes.py`, one rename in
  `test_retirement_cleanup.py`), not "8, all in one file" — this
  by-file listing also discharges `S5`'s "named individually"
  requirement (`D-1`). M-3: `13-hosting-and-separation.md` §2 (`:62`),
  §3 (`:91`), §7 (`:318`) rewritten from present-tense "routes via the
  chezmoi/dotfiles flow" claims to the shipped truth — user scope is a
  first-class plain host by construction since Phase 1/2 (landed
  2026-08-28); §7 no longer contradicts its own §4 item 5. `D-2`: doc
  13 `:129`'s "the chezmoi path has committed … since M1" clause is now
  dated ("UNTIL 2026-08-28 … — history now"). N-1: `test_hostmode.py`
  is excluded from `CHEZ6`'s `cli/tests` sweep BY PATH instead of
  building `_RETIRED_MODULE` from `"chez" + "moi"` to dodge its own
  grep — the file now spells the retired module's name as a plain
  literal, greppable like any other file, and simply is not counted.
  N-2: `ui/static` joins both `CHEZ6`'s and `UIC5`'s swept trees; its
  only content is `app.js:517,519`'s two dated retirement comments
  (leg (e) of `reloadDeferred`, kept as a permanent gap) — zero
  `chezmoi` literals there (`CHEZ6`), two `adopt` literals, both
  accounted retained-history (`UIC5`). No code change; six criteria
  amended (`DOC1`, `DOC2`, `PLAIN6`, `CHEZ3`, `CHEZ6`, `UIC5`), one doc
  (13-hosting-and-separation.md) gets four dated clauses, and
  `test_hostmode.py`'s census instrument is rewritten to exclude itself
  by path rather than by evasion.
  **Counts: two phases, 94 criteria (82 [A], 12 [B]) across 14 groups,
  60 mutations, 10 measured anchors — unchanged; this fold amends
  criterion TEXT only.**
