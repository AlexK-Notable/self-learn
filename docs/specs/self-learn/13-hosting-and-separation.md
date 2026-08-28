# 13 — Hosting: the independent ledger home and the product / ledger / host split

**Status: RATIFIED 2026-07-16 (user-directed: "we need an independent
home for the ledger" following the separation discussion; the four
material calls were answered live and are recorded in §1 — any answer
is user-vetoable by dated register edit). Build proceeds ledger-first
per §7, worktree + pre-migration audit. This document REVISES 02 §2's
single-repo route-atomicity language — see §4, the revision of record.**

## 0. Origin

Three converging facts, all surfaced 2026-07-16:

1. **Separation intent.** self-learn outgrew the personal-skills
   monorepo (540-test CLI, 13-doc corpus, systemd units, autonomous
   nightly miner, a team-scale horizon in 06) — the user directed an
   official split.
2. **Project scope was quietly host-specific.** `resolve_home()` is
   env-or-fixed-default; every capture on the machine lands in one
   global home, and `project` scope compiles into *that repo's*
   CLAUDE.md. Fine while captures were conscious; the doc-12 miner
   reads EVERY project's transcripts, so a project-scoped lesson about
   `~/repos/foo` would mis-home into claude-skills' CLAUDE.md. The
   review gate contains the damage; the architecture invited it.
3. **The cache plane is a per-machine singleton** (locks, cursors,
   journal, markers share one un-namespaced path) — "multiple ledgers
   via SELF_LEARN_HOME" was never actually supported, just unclaimed.

An independent ledger home resolves all three at once: the ledger stops
being a tenant of one host, project scope becomes per-project, and
"one ledger per machine" becomes an explicit registered fact instead of
an accident.

## 1. The ratified calls (2026-07-16, user present)

- **Q1 · Home = `~/.self-learn`** — product-named; the in-repo
  `.self-learn` bucket dirs disappear in migration, so no collision.
- **Q2 · Project buckets auto-create; routing gates on host
  registration.** Any session or mining run may open a project's bucket
  (capture is cheap and human-gated downstream), but compiling into a
  project's CLAUDE.md requires that host to be registered in
  `hosts.yaml` at route time — the CLI refuses otherwise and the card
  says why. No compile target is ever guessed (invariant H-3).
- **Q3 · Migration preserves history** via `git-filter-repo` extraction
  — load-bearing, not cosmetic: the M2 analyst's rejected-proposal
  digest greps resolution COMMIT MESSAGES, which must survive the move.
- **Q4 · Ledger first, product repo second.** The ledger migration
  fixes the live cross-project mis-homing exposure; extracting
  code+specs to the product repo is step 2 (§8).

## 2. The three layers

```
PRODUCT   the self-learn repo (step 2): CLI + plugin + spec corpus.
          Normal git workflow, NO autosync — the worktree-vs-autosync
          dance for self-learn development ends.
LEDGER    ~/.self-learn — a git repo with its own private remote.
          Records, proposals, telemetry, hosts.yaml. THE per-machine
          singleton; source of truth for every lesson.
HOSTS     repos holding COMPILED canon: claude-skills (SKILL.md managed
          sections + its own CLAUDE.md), any registered project's
          CLAUDE.md, and ~/.claude/CLAUDE.md via the chezmoi/dotfiles
          flow (a host that was ALWAYS external — the precedent §4
          leans on). Registered in hosts.yaml, never inferred.
```

## 3. Ledger home layout

```
~/.self-learn/
  hosts.yaml                    # the registry (H-3): skill roots + project paths
  skills/<name>/{pending,resolved,proposals}/
  projects/<slug>/{pending,resolved,proposals}/   # per-project (NEW)
  user/{pending,resolved,proposals}/
  telemetry/<month>.<actor>.jsonl
```

- **Skill buckets** are host-global as before; `hosts.yaml` names the
  skills root (claude-skills) so compilers find SKILL.md targets.
- **Project buckets are per-project** — the scope-semantics upgrade.
  A bucket records its project's absolute path at creation (`meta.yaml`
  beside the bucket; the slug alone is lossy). Producers know the path:
  teach uses cwd; the miner reads the transcript's own `cwd` field.
  *(Added 2026-07-18 — feedback round 3 item 3, 02 §2's `rehome` pin:)*
  a bucket can also be created by `self-learn rehome` moving a pending
  record into a registered project that has no bucket yet — dirs +
  `meta.yaml` stamped from the hosts.yaml entry, same shape as a
  capture-created bucket; hosts.yaml remains the only registration
  authority either way.
- **User bucket** replaces the root bucket's user half; compile target
  unchanged (chezmoi flow).
- `hosts.yaml` is data, tracked in the ledger repo — one file to read
  to know where canon may land. Registration is a CLI verb
  (`self-learn host add <path>`), never a hand edit the compilers
  trust blindly (the verb validates the path and stamps the entry).
  *(Amended 2026-07-18 — feedback round 3 item 2; normative text at
  09 §11 Y-17, this bullet is its CLI-side mirror. Reworked the
  same day at the amendment's blind review — F6/F7/F8 folded.)*
  `host add`
  gains `--init`: `git init` + an empty root commit (pinned subject
  `self-learn: init for host registration`) at the EXACT path,
  performed before the path validation, which then runs
  unchanged — the pure-argument refusals (kind validity,
  ledger-home existence) stay AHEAD of the init leg as they run
  today, so an invalid invocation never leaves an initialized repo
  behind (F6). Semantics per the Y-17 matrix: no-op when the path
  is
  already a repo root — a zero-commit repo counts as a root, and
  the root commit is best-effort-once: a failed empty commit is
  not retried, the retry skips the init leg (F7);
  init-at-the-exact-path when it is not a root —
  including when a parent repo's work tree swallows it (nested
  repos are acceptable and intended); clean refusal on a missing
  dir OR a regular file, never a fall-through to raw git stderr
  (F8 — `--init` initializes existing directories only, it
  creates nothing); all other refusals and the
  idempotent re-add unchanged; without `--init`, behavior
  byte-unchanged. The deciding predicate — "the exact resolved path
  is itself a git repo root" — is one CLI-owned helper (the
  is-inside-work-tree check cannot carry this: it passes for paths
  inside a parent work tree); the UI imports it for its
  disclosure banner. The committability invariant is untouched —
  `--init` is how a not-yet-repo project opts INTO it, disclosed,
  never a bypass.

## 4. Routing across repos — the revision of record

02 §2's "route = one commit" was already false for user scope: the
chezmoi path has committed ledger-side and dotfiles-side separately
since M1 (E-17 extended). The honest invariant was never single-commit;
it is: **the ledger is the source of truth and canon is a compiled,
regenerable artifact** (correction = supersede + recompile, never
revert). Doc 13 promotes that to the general rule:

1. **Ledger-first two-phase** *(for a `git`-mode host; a `plain` host
   runs the ledger phase and then applies canon without a host commit —
   item 5)*. A resolution verb commits the ledger
   change (pinned subject, in `~/.self-learn`) FIRST, then applies the
   recompiled managed section in the target host and commits there
   (pinned subject referencing the record id), then pushes both.
2. **Crash between phases = stale canon, never lost truth.** The
   `--selftest` gains a drift check: managed-section entry markers
   (`*(lrn-…)*`) vs the ledger's routed records; drift is repaired by
   recompile, one command, idempotent.
3. **The rejected-proposal digest moves its grep to the ledger repo**
   (resolution commits live there now).
4. **The sentinel contract SHRINKS.** The ledger repo has no watcher
   (§5), so the sentinel exists only to pause a HOST's autosync during
   the seconds of a canon apply+commit. Same file contract, same TTL,
   per-host documentation; claude-skills-sync keeps its check.
5. **Hosts are git-optional (added by `U-hostmode`).** A registered host
   carries a **mode** on its `hosts.yaml` entry: **`git`** (the default,
   and what every entry written before this unit means) or **`plain`**. A
   `git` host behaves exactly as items 1–4 describe. A **`plain`** host
   requires no repository: nothing is staged, committed, or pushed there,
   and the two-phase rule of item 1 collapses to its ledger half. The mode
   is set ONCE, by `self-learn host add --mode git|plain`;
   `config.yaml`'s `hosts.default_mode` sets the default for new
   registrations, fail-closed to `git` (the `S-10` discipline). `host add
   --init` is unchanged and remains a **git**-mode convenience — `--mode
   plain --init` is a usage refusal, not a silent preference. A plain host
   is gated at registration and at every route by a `.self-learn-host`
   marker file the registering verb writes — the structural analogue of
   `.git`, and the replacement for the committability check, not its
   omission. **User scope (`~/.claude`) is a plain host by construction**:
   it is never registered, carries no marker, and its mode cannot be
   anything else.

   **What replaces git for a plain host, and what does not.** Item 2's
   drift check is unaffected: it was never a git check — it compares the
   ledger's routed records against `(lrn-…)` entry markers in the target,
   and `self-learn recompile` remains the one-command repair (H-2). What IS
   replaced is the **dirty gate**. A plain host is gated by a
   **ledger-side compile record** — `<home>/compiled/<host-slug>.yaml`, one
   entry per target, carrying the sha256 of the region the ledger says must
   be there and the sha256 of **the state that write was based on** — the
   region as it was observed on disk at pre-flight. A region matching the
   current hash is clean; matching the based-on hash means our own apply
   did not land (drift — `recompile` repairs it, however many times in a
   row it fails); matching neither was hand-edited and the route refuses,
   naming `recompile --adopt`. **This is
   stricter than `git status` for the region self-learn owns** — it catches
   an in-marker hand edit the human has already COMMITTED, which
   `git status` reports as clean — and narrower where narrowness is
   correct: an edit outside the markers no longer refuses a write the
   compiler preserves byte-exactly. The record is written for **git** hosts
   too; only the *gate* differs by mode. It is written **inside the
   resolution's own ledger commit**, under the ledger `commit_lock`, before
   that commit — so it opens no second failure window, and a failure of
   that commit is already `HalfWrittenError` (exit 7), never a false exit 6.
   It is swept by `self-learn reconcile` like every other ledger artifact
   (§5's corollary applies to it, and `_RECONCILABLE` was extended so that
   is true and not merely asserted).

   **What a plain host gives up, stated plainly.** No `git log` or
   `git blame` over the compiled canon, no `git revert` of a canon commit
   (already not a correction mechanism — `S-12`), and **no off-machine
   backup of the host's file**. A ledger-side record is a record of
   self-learn's own region, not a backup of the user's file: measured
   2026-08-27, self-learn's region is **15.8%** of the bytes of the sixteen
   files carrying a managed section (44 654 of 283 204; **18.4%** across
   the thirteen that are routable targets rather than `.claude/worktrees/`
   checkouts). A user whose host content wants history should use `git`
   mode, which is why it is the default.

## 5. Producers commit their own writes

Every ledger mutation already flows through the CLI (teach, import,
mine, the resolution verbs). Therefore the ledger repo needs **no
autosync watcher, ever** (H-5): producers commit (pinned subjects) and
push their own writes; the review-session self-push rule carries over.
This closes a v1 wrinkle — pending captures used to ride anonymous
autosync commits; now every capture has an attributable commit.

**The corollary, and its backstop** (added 2026-07-16 after the audit
found the hole open). H-5 composes with the pathspec rule ("every
producer commits ONLY its own paths") into a failure mode neither rule
implies alone: a record whose producer wrote it and then *failed* to
commit it is committed by **nobody, ever**. There is no watcher to sweep
it up and no other producer will name its path. It sits untracked until a
clone deletes it. The miner made this concrete — its landing commit could
fail while `_advance_cursors` ran regardless, so the records were both
uncommitted and never re-mined.

`self-learn reconcile` is the backstop: it finds ledger records/proposals
that no producer committed and commits them under the lock, by pathspec,
with the pinned subject `self-learn: reconcile <n> uncommitted
record(s)`. It runs on demand, at the start of every `mine` run, and
before every `push` — so the window closes without a human being told.

It commits only what exists and is untracked-or-modified: it never
commits a deletion and never completes half a staged `git mv` (that shape
is a broken *resolution*, and guessing at it produces the record-in-two-
places corruption `gitops.known_paths` exists to prevent). Those it
reports and leaves for the verb's own printed repair.

Its correctness rests on the lock invariant: **no ledger/host mutation
may precede its `commit_lock`.** Because every producer holds the lock
from before its first mutation through its commit, anything reconcile
sees uncommitted *while holding that lock* is orphaned by definition
rather than merely in flight. The invariant is enforced mechanically
(`cli/tests/test_lock_invariant.py` walks the package call graph and
fails when any entrypoint can reach a mutation without passing through a
lock), because three separate review rounds established the rule and
three separate files still missed it.

**`serve` is a scheduler, not a watcher (added by `U-engine` Phase 2;
corrected 2026-08-27, gate r1 D-2/M-1).**
H-5 says the ledger repo needs no autosync watcher, ever. The
`self-learn serve` host process does not change that and is not one: it
STARTS producers (`miner.run`, `worker.run`) on a schedule, and each
producer still takes its own `commit_lock`, commits only its own
pathspec, and uses its own pinned subject — exactly as when a verb or a
timer started it. `serve` never stages, never commits, never pushes,
and writes into `cache_dir()` only — three files (`serve.heartbeat`,
`serve.poke`, `serve.schedule`), all already `NOT_REPO_TRUTH` by the
same rule as every other cache write. The `reconcile` backstop is
unchanged and still runs at the start of every `mine` and before every
`push`. The mechanical consequence is in `test_lock_invariant.py`:
`miner.run` and `worker.run` were never roots (`cli._cmd_mine` and
`cli._cmd_worker` already called them, before `serve` existed) and stay
not-roots — `serve` gives every mutation already reachable from them a
SECOND path into the lock-obligation walk, through `cli.entrypoint ->
... -> cli._cmd_serve -> serve.run_forever -> serve._run_tick`, which the
walker checks structurally, without anyone declaring it.

## 6. Cache namespacing

`~/.cache/claude-skills/self-learn/` → `~/.cache/self-learn/` in the
same migration (the old name embeds the host it no longer belongs to).
State keyed under a hash of the ledger-home path (H-4) so a future
second home (06's shared team ledger beside the personal one) is a
config away, not a redesign. One-time migration moves cursors, journal,
markers, spool; the sentinel path change is coordinated with
claude-skills-sync in the same commit pair.

**Hermetic guarantee (`U-cachelit`, 2026-08-28, FW-130):** every test
suite in this repo (CLI, UI) redirects `XDG_CACHE_HOME` for the whole
test session — a session-scoped floor UNDERNEATH each package's own
per-test redirect, never merely per-test alone — so a namespace under
this scheme is written to the REAL `~/.cache/self-learn` iff a real
`self-learn` invocation resolved it, never as a side effect of running
either suite; both suites' `conftest.py` also carry a session-scoped
guard that fails the suite's own session, by name, if that guarantee
is ever broken again.

**Running the two suites (pre-existing, unrelated to the guarantee
above):** a bare `pytest` invoked from the worktree root, given both
packages' `tests/` directories, collides — neither package's `tests/`
is an importable package (no `__init__.py`), so pytest's default
rootdir-based import mode binds each same-named module (`conftest.py`,
`support.py`, `test_serve.py`, …) to ONE entry in `sys.modules`; the
second package's copy then either fails to import (`support.py`'s
UI-only names missing from the CLI's own `support.py`, already bound
first) or errors outright (`import file mismatch`). Measured: `uv run
--project plugins/self-learn/ui pytest plugins/self-learn/cli/tests
plugins/self-learn/ui/tests` — 18 collection errors, all this shape.
Each suite has its own sanctioned entry point instead (CLI: `plugins/
self-learn/cli/scripts/suite`; UI: `cd plugins/self-learn/ui && uv run
pytest`, explicit `tests/` path) — this has always been true and is not
something this unit changed.

## 7. Migration plan (ledger-first; worktree + pre-migration audit)

- **T-H1 · Home bootstrap** — `~/.self-learn` git init, private remote,
  layout dirs, hosts.yaml seeded with EXACTLY two entries:
  ```yaml
  skills_root: /home/komi/repos/claude-skills   # covers all 3 skills (glob)
  projects:
    - path: /home/komi/repos/claude-skills
  ```
  **There is no dotfiles/user host** (audit correction 2026-07-16, M-2):
  `~/.claude/CLAUDE.md` routes through the chezmoi flow, which §2 already
  calls "a host that was ALWAYS external" — it is deliberately NOT
  hosts-gated, and `host add --kind dotfiles` is refused by design. An
  earlier draft of this line said otherwise; the implementation
  (`HOST_KINDS = skills-root | project`) is correct and this doc was
  wrong.
- **T-H2 · History extraction** — `git-filter-repo` over a claude-skills
  clone: every `**/.self-learn/**` path (root + per-skill buckets +
  telemetry) rewritten into the §3 layout, grafted into the home repo;
  verify the digest's `git log --grep '^self-learn: reject '` still
  answers there. Buckets then deleted from claude-skills (one commit,
  after verification).
- **T-H3 · Code refactor** — ledger.py (home resolve = `~/.self-learn`
  or SELF_LEARN_HOME; discover_buckets on the new layout), hosts.yaml
  reader + `host add` verb, bucket_dir_for_scope (+ project-path
  binding), compilers (targets via registry; route-time host gate),
  two-phase route + drift selftest, digest relocation, worker + miner
  path updates, cache move, **doctrine/rubric resolve relative to the
  CLI package** (they ship with the product beside the skill — never
  via any home; this also pre-clears the step-2 extraction). Test
  fixtures (`make_home`) rebuilt around home+host sandboxes.
- **T-H4 · Deploy cutover** — env/unit updates, cache migration shim,
  the dangling-symlink sweep across ~/.claude/skills, ~/.claude/hooks,
  ~/bin, systemd (the hypr-doctor-drift lesson), claude-skills
  CLAUDE.md rewritten to "ledger HOST" framing, plugin README updated.
- **T-H5 · Acceptance (user-present)** — a real capture lands in
  `~/.self-learn` with its own commit; a route compiles into
  claude-skills SKILL.md two-phase with both pinned commits; a mined
  candidate from a FOREIGN project lands in that project's bucket and
  its card shows the route-time host gate; drift selftest catches a
  hand-broken marker; miner overnight run green under the new cache.

### 7.1 Cutover runbook (audit-corrected 2026-07-16)

Two reviewers audited this migration before it ran. The design and the
extraction survived; **every blocker lived in an unguarded window of the
sequence**, and all are dissolved by stopping the daemons first plus two
hard gates. The corrected order (see the README revision log for the
findings):

0. **Snapshot** (nothing destructive yet): `cp -a` the old cache dir,
   record the master SHA, tar all four bucket dirs, count records (39).
1. **Stop the daemons FIRST** — miner timer + autosync watcher; confirm
   no run in flight. Nothing in the migration depends on them being up,
   and their liveness is what makes B-2/M-1 possible.
2. **Flush + commit** — `telemetry flush` (old code, old paths) then
   commit; `git clone` sees committed state only (m-3), and the watcher
   that used to guarantee a clean tree is now down.
3. **Doc/unit fixes land in the branch BEFORE the merge** (M-3): the
   runtime instruction files (SKILL.md, commands/review.md, README) are
   what the agent operates from — stale bucket paths there silently
   mislead. Miner unit gains `Environment=SELF_LEARN_HOME=%h/.self-learn`
   (B-1: the systemd user manager does not inherit the shell's env).
4. **Extract, then RECONCILE as a hard gate** — record count in the
   extracted repo must equal the snapshot's 39, else ABORT (B-2).
5. **Bootstrap the home before ANY new-code CLI call** — `test ! -e
   ~/.self-learn` first (B-3: `teach` auto-creates the home and would
   collide with the move), then move, seed hosts.yaml + project
   meta.yaml, commit, create the private remote, push.
   **The project bucket dir must be named by the CURRENT code's slug, and
   the script must DERIVE it, never type it** (audit correction
   2026-07-16, MINOR H). `hosts.slug_for` gained a
   `-<sha256(resolved)[:8]>` suffix — the readable `/`→`-` shape alone was
   many-to-one (`/w/a-b` and `/w/a/b` both render `-w-a-b`), so two
   projects shared one bucket and B's records compiled into A's CLAUDE.md.
   An earlier draft of this runbook still showed the old, suffix-less
   bucket name; a hand-typed name would create a bucket the code then
   cannot find, silently opening a SECOND one beside it. So:
   ```bash
   slug=$(python -c 'from self_learn.hosts import slug_for; \
     print(slug_for("/home/komi/repos/claude-skills"))')
   mkdir -p ~/.self-learn/projects/"$slug"/{pending,resolved,proposals}
   ```
   (Verified no live impact at the time of writing: no `projects/<slug>`
   dir exists yet, so nothing needs renaming — the correction is to the
   runbook, before it runs.)
6. **Merge the code**, then `git rm` the old buckets (recoverable from
   history — this is NOT the point of no return).
7. **First new-code CLI call migrates the cache** — daemons still down.
   THIS is the actual point of no return (the shim moves, not copies).
   Gate on it: buckets ≥ 5 and cursors present (B-1's silent-all-clear
   is why the gate is a script assertion, not an eyeball).
8. **Redeploy + sweep** — `./install.sh` (which also deploys the
   SessionStart hook that was never symlinked — audit PC-1), then sweep
   `~/.claude/skills`, `~/.claude/hooks`, `~/bin` for dangling symlinks.
9. **Restart daemons**, then run T-H5 acceptance.

Standing corrections from the same audit: **PC-1** — the SessionStart
hook has never been deployed or registered (install.sh symlinks it;
`settings.json` registration stays manual by design), so the miner's
36 h staleness line does not exist on this machine until step 8 + a
manual settings edit. **PC-2** — H-6's rejected-proposal history is
currently *vacuous* (zero rejections ever); the invariant holds and
costs nothing, but it protects a memory that does not yet exist.
- **Step 2 (after T-H5 settles): product-repo extraction** — code +
  corpus to the self-learn repo via filter-repo, own install.sh,
  claude-skills marketplace entry dropped. Its details stay §8-thin
  until step 1 is live; nothing in T-H1..5 blocks or presupposes it
  beyond the package-relative doctrine/rubric pin.

## 7.2 The concurrency invariant (added 2026-07-16, after 7 review rounds)

H-5 made concurrent producers the norm (teach, import, the kicked
worker, the nightly miner, and the verbs all commit into ONE ledger
repo, several from detached processes). That promoted a dormant git
wart into a live corruption path, and hardening it consumed four fix
rounds. The durable outcomes:

- **H-7 · No ledger/host mutation may precede its `commit_lock`.** The
  lock opens BEFORE the first mutation of a repo and is held through
  that repo's commit. Scope is `[first mutation → commit]` — NOT the
  whole verb (that held the lock across network pushes, blocking every
  other producer) and NOT `[stage → commit]` (verbs mutate before they
  stage, e.g. `resolve_record`'s `git mv`). Push runs OUTSIDE the lock;
  `push_with_retry` takes the lock itself around `pull --rebase
  --autostash + re-push`, in the repo being rebased, so no caller can
  forget it. Every git call is timeout-bounded.
- **Why the lock exists (measured, not argued):** without it, a racing
  `pull --rebase --autostash` commits git CONFLICT MARKERS into a
  record file and reports success — an unparseable record, exit 0,
  clean `git status`. The pathspec-commit layer survives a pure rename
  and a non-colliding edit; it cannot survive this.
- **H-8 · The rule is machine-checked, not review-checked.**
  `tests/test_lock_invariant.py` states H-7 as a call-graph property:
  every function parsed from source, mutating leaves propagated by
  fixpoint, entrypoints derived (a root = no in-package caller), a
  violation = an obligation reaching a root. Exemptions are
  fail-closed. This exists because four rounds of patching the
  *reported* sites simply relocated the bug to the file nobody listed.
- **A layer must not assert state it cannot know.** `HalfWrittenError`
  (exit 7) vs a clean refusal (exit 6) are different facts; the
  constructor *requires* `repair=`, so no surface can report
  half-written state without naming the fix. `reconcile` (verb +
  miner-run-start + `push`) makes an uncommitted record self-healing
  rather than narrated data loss.

**Recorded as narrower-than-claimed** (final verifier, 2026-07-16 —
none reachable by current code; fix when touched): exemptions are
function-scoped, so a ledger write added inside an already-exempt
function escapes the check; 11 of 19 runtime lock-contention cases bail
on validation before reaching the lock (notably `host add`, whose
fixture pre-registers the host); nine checker-evasion spellings exist
(aliased writes, `getattr`, dynamically-built git argv, absolute
imports) — the checker pins today's house style, not the rule itself.
The model's own writes (the worker's `claude -p`, `cwd=home`) can never
be lock-guarded and are unfixable by AST — `reconcile` is the answer
there. *Amended 2026-08-19 (U-docs):* still true of the model's own
writes on either backend — but since `U-attrib` (`S-32`) those writes
land in an exclusive **stage**, and the **install** from stage into the
ledger runs inside the worker under the commit lock. The unguardable
window is now the stage, which no other producer reads, rather than the
ledger itself; `reconcile` remains the answer for anything that escapes.

## 7.3 Step-2 runbook — product-repo extraction (drafted + ratified + **EXECUTED 2026-07-17**, user: "execute")

*Step 1 is live and T-H5 is fully discharged (2026-07-17: first real
mine green; the organic foreign-project card landed from the zmk-config
repo), so the §8-thin veil comes off. This section is the §7.1-grade
runbook. It moves CODE and CORPUS only — the ledger (step 1's product)
and every compiled canon target stay exactly where they are.*

### What moves, what stays (the boundary, stated once)

| Moves to the product repo | Stays in claude-skills |
|---|---|
| `plugins/self-learn/cli/` (uv project, tests) | every compiled canon target: SKILL.md sections, `CLAUDE.md`, references |
| `plugins/self-learn/skills/self-learn/` (SKILL.md + references — doctrine/registry ride the package, T-H3 already pinned) | skill-scope guard scripts (canon in their OWNING plugin: `plugins/chezmoi/hooks/…`) |
| `plugins/self-learn/commands/` (review/teach) | **project/user-scope guard scripts → relocated to `hooks/self-learn/` (D1)** |
| `plugins/self-learn/hooks/self-learn-pending.sh` (a PRODUCT hook, not canon) | `hosts.yaml` semantics: skills_root remains this repo — unchanged |
| `plugins/self-learn/scripts/self-learn` (~/bin shim; `readlink -f` makes it repo-agnostic) | the claude-skills autosync watcher |
| `docs/specs/self-learn/` corpus (+ fixtures, research, reviews) via filter-repo (H-6: history preserved) | `~/.self-learn` (untouched — that was step 1) |
| `systemd/self-learn-miner.{service,timer}` | |

### Decisions requiring ratification before execution

- **D1 — M3-7 amendment (the one real design question).** Guard
  scripts are CANON (compiled from records), and canon lives in
  registered HOSTS — but M3-7 currently lands project/user-scope
  guards under `plugins/self-learn/hooks/`, i.e. inside the PRODUCT's
  plugin dir. That conflation was invisible while product and host
  shared a repo; extraction forces the split. **Recommendation:**
  amend M3-7 so project/user-scope guards land at
  `<skills_root>/hooks/self-learn/` (a canon directory of the host,
  swept by the host's install.sh), and migrate the two live records
  (`lrn-dd9489b2`, `lrn-4f5971c8`): `git mv` the scripts, update each
  record's `routing.hook.script_path` (one pinned ledger commit — the
  only hand-edit of a resolved record this runbook permits), re-run
  install.sh. Script FILENAMES never change, so `~/.claude/hooks/`
  symlink names and the user's settings.json entries survive
  untouched. *Rejected alternative:* leaving a stub
  `plugins/self-learn/hooks/` in claude-skills — two repos owning
  pieces of one plugin is exactly the ambiguity doc 13 exists to kill.
  **RATIFIED 2026-07-17 (user, stating the governing principle):**
  *"stays in claude-skills. the goal would be to treat the learning
  system as a tool unto itself that anyone could install and use for
  their own skills. nothing should get committed to its repo other
  than work that's specific to its development."* This is the
  product-boundary rule for ALL future routing surfaces: compiled
  output of any kind lands in the USER'S hosts, never in the product
  repo — the product repo receives only its own development work.
  M3-7 is amended accordingly (08 §8.1 note).
- **D2 — product repo identity.** **RATIFIED 2026-07-17:**
  `github.com/AlexK-Notable/self-learn`, private, same posture as
  `self-learn-ledger`.
  *(Amended 2026-07-24 — user ruling, publication: the product repo is
  **PUBLIC**, licensed FSL-1.1-MIT (see the root `LICENSE`; 03 S-19).
  This reverses the `private` half of the ratification above and, with
  it, the derived pin P-C1.4 in `drafts/c1-portability-defects-spec.md`
  §1.3 — the `plugin.json` `homepage`/`repository` links that P-C1.4
  accepted as knowingly unreachable are now publicly correct, exactly as
  that pin anticipated. **The "same posture as `self-learn-ledger`"
  clause no longer holds and is severed: the LEDGER remains private.**
  D1 (product-boundary) and D3 (no autosync) are unaffected.)*
- **D3 — product-repo autosync.** **RATIFIED 2026-07-17: NO watcher
  — manual pushes only** (recommendation to mirror was declined).
  Consistent with D1's boundary: the product repo changes only when
  someone is deliberately developing it; ambient sync is a
  skills-repo affordance, not a product-repo one.

### The runbook

0. **Snapshot + preconditions.** Tree clean, suite green, selftest
   6/6, no code work in flight. Snapshot dir
   `~/.local/state/self-learn-extraction-<date>/` records: master sha,
   `ls -l` of `~/.claude/{skills,commands,hooks}` and `~/bin` (the
   symlink surfaces this migration re-points).
1. **D1 first, in claude-skills, as its own commit** (so the
   extraction filter never carries the guards out): `git mv` the two
   guards → `hooks/self-learn/`; extend install.sh's per-plugin hooks
   sweep to also walk `hooks/self-learn/*.sh`; pinned ledger commit
   updating the two `script_path` fields; `./install.sh`;
   `self-learn --selftest` hooks check green. **install.sh restarts
   autosync (lrn-316a5411)** — no window needs to stay closed here,
   but step 2 stops daemons AFTER this, not before.
2. **Stop the claude-skills autosync watcher** for the surgery
   window; leave the miner timer (it touches only the ledger) but do
   not run it mid-swap.
3. **Extract with history:** fresh clone → `git filter-repo` keeping
   `plugins/self-learn/`, `docs/specs/self-learn/`,
   `systemd/self-learn-miner.*` — layout PRESERVED (the shim's
   `../cli` relative path, package-relative doctrine loading, and the
   test suite all keep working with zero path edits; restructuring is
   a later, separate decision).
4. **Product repo bring-up:** own thin install.sh (five surfaces:
   skill symlink, commands dir symlink, `~/bin/self-learn` shim,
   `self-learn-pending.sh` hook symlink, `uv sync` + miner units) —
   same idempotent link-with-backup idiom; README; `gh repo create`
   per D2; push; run install.sh; full suite; selftest.
5. **Removal commit in claude-skills:** `git rm -r
   plugins/self-learn docs/specs/self-learn
   systemd/self-learn-miner.*`; drop the marketplace entry; update
   CLAUDE.md (skills table, autosync notes). `hooks/self-learn/` and
   its sweep REMAIN — they are host canon now (D1).
6. **Re-link + dangling sweep:** re-run claude-skills install.sh;
   then sweep `~/.claude/skills`, `~/.claude/commands`,
   `~/.claude/hooks`, `~/bin` for symlinks pointing into deleted
   paths (the hypr-doctor-drift dead-hook precedent — a dangling hook
   symlink no-ops SILENTLY; this sweep is the step most tempting to
   skip and the one that has already bitten once).
7. **Verify, fresh session:** `~/bin/self-learn status` resolves via
   the product repo; selftest 6/6 (hosts.yaml untouched — drift check
   proves canon compilation still lands in claude-skills);
   `systemctl --user start self-learn-miner.service` green;
   SessionStart pending hook prints; `/self-learn:review` loads; the
   three guards still registered + resolvable; restart both
   autosync watchers (claude-skills + D3's, if ratified).
8. **Bookkeeping:** doc 13 revision note (step 2 executed), README
   revision log, project memory, handoff. Retain the snapshot until
   the first product-repo dev cycle completes.

**Rollback at any point before step 5's push:** delete the product
repo clone. After step 5: the pre-removal master sha is tagged in the
snapshot; `git revert` the removal commit + re-run install.sh restores
every symlink — no ledger or canon state is touched at any step, so
rollback is purely a code-repo affair.

## 8. Invariants

- **H-1** · One ledger home per machine, explicit (`~/.self-learn` or
  SELF_LEARN_HOME), never inferred from cwd.
- **H-2** · The ledger is truth; canon is compiled output; recompile is
  always safe and repairs any two-phase interruption.
- **H-3** · Compile targets come from hosts.yaml only — capture is
  open, canon is registered. No autonomous process ever writes to an
  unregistered repo. A registered host need not be a git repository:
  `U-hostmode` makes version control a per-host mode (`git` default,
  `plain` opt-in). H-3 itself is unchanged — compile targets still come
  from hosts.yaml only, and a plain host is gated by a
  `.self-learn-host` marker the registering verb writes, never by being
  writable.
- **H-4** · Cache state is namespaced by ledger home.
- **H-5** · No watcher on the ledger repo — producers commit their own
  writes with pinned subjects. Corollary: a write its producer could not
  commit is committed by nobody, so `self-learn reconcile` is the
  backstop (§5), and no mutation may precede its `commit_lock`.
  `self-learn serve` (U-engine Phase 2) does not change this: it starts
  producers on a schedule; it does not itself mutate the ledger. (Owed
  by spec §12.3 since r5; landed 2026-08-27 — gate r1 D-1 first flagged
  it missing, gate r2 D-1 found it STILL missing after a first attempt
  whose inline parenthetical apparently broke a plain-text match; this
  is the clean, unwrapped form.)
- **H-6** · Migration preserves resolution-commit history (the
  analyst's negative exemplars are part of the system's memory).
