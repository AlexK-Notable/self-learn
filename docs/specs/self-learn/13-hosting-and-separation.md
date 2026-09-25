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
  *(2026-09-11 — Sprint 3 lane A, the placement amendment, Q2/Q-A1
  rulings; forward work, not built this sprint — see
  `14-forward-work-map.md`.)* The **target model**, once built: an
  authorized placement into a resolvable, non-denylisted root
  **registers that root as a consequence of routing** — by the human's
  own tap or an authorized automated reviewer's — rather than needing a
  separate `host add` step first. H-3's core promise is unchanged (no
  compile target is ever guessed, and none is ever written before
  registration); what changes is that registration becomes a **step of
  the placement action** instead of a human-only standalone
  prerequisite. **Today** the CLI still refuses an unregistered host
  exactly as this paragraph describes above; nothing in this note is
  live until the forward-work rows land.
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
          CLAUDE.md, and ~/.claude/CLAUDE.md — a first-class PLAIN
          host by construction (U-hostmode §4.8.1, landed 2026-08-28):
          no repo, self-learn writes canon but commits nothing. UNTIL
          2026-08-28 this host routed via the chezmoi/dotfiles flow
          (history — see §4 item 5). Registered in hosts.yaml, never
          inferred, except the user host, which is never registered.
```

## 3. Ledger home layout

```
~/.self-learn/
  hosts.yaml                    # the registry (H-3): skill roots + project paths
  skills/<name>/{pending,resolved,proposals}/
  projects/<slug>/{pending,resolved,proposals}/   # per-project (NEW)
  user/{pending,resolved,proposals}/
  telemetry/<month>.<actor>.jsonl
  cases/<yyyy-mm>/case-<8hex>.md      # decision cases (02 §3a; S-65)
  cases/runs/<run_id>.json             # committed delegated-run recipe,
                                       # evidence and unfinished obligations
  user-statements.jsonl               # append-only, the user's own words
  user-model.md                       # CURRENT/LAPSED readings (02 §3a)
  overseer/{<date>-report.md, latest-report.md, coverage.yaml,
    open-questions.yaml, evaluation-<date>.md}   # the overseer's own subtree
```

`cases/runs/<run_id>.json` is ledger truth, not runner cache. Its schema and
continuation rules are in 02 §3a. A compound intent may register that one
manifest path alongside its existing mutation paths so a `ledger_effect`
proof lands in the same commit as the compound mutation. This uses the
existing `intents.add_step` path list and recovery algorithm; it adds no
intent field, phase, or second executor.

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
  unchanged — `~/.claude/CLAUDE.md`, written as a first-class PLAIN host
  since U-hostmode Phase 1/2 (landed 2026-08-28; UNTIL then, chezmoi
  flow — history, see §4 item 5).
- **Persisted placement intent and the never-register blocklist**
  *(2026-09-11 — Q2; forward work, not built this sprint)*. A lesson
  whose destination root does not yet resolve to a registered host
  will, once built, keep its intended host recorded against the
  pending proposal rather than discarding it — so that when the root
  becomes registered (by the auto-registration mechanism above or by
  hand), the proposal regenerates automatically instead of the human
  re-discovering and re-typing the scope (policy
  `d4-general-policy-codex.md` §3, step 4). The **never-register
  blocklist** lives as a new `hosts.yaml` key, seeded with this
  repository (this repo's own `CLAUDE.md` already forbids registering
  it as a canon host) — **user-populated, agent-maintained**: an agent
  may propose adding an entry, never remove one, and never registers a
  denylisted root under any circumstance, human-tapped or
  automated-reviewer-tapped alike. A **worktree or nested scratch
  directory resolves to its enclosing main checkout** before any of
  this runs — the registered host is always the checkout, never a
  throwaway `.claude/worktrees/*` path. A **personal-literal scan**
  (extending `plugins/self-learn/cli/tests/test_personal_literals.py`'s
  existing check over the tracked product tree to run against any body
  about to be written into a *git-mode* host) runs before any such
  write, refusing or redacting exactly as the existing secret scan does
  today (`02-schema.md`, evidence-quote rule).
- **Cases, statements, and the user model** *(Added 2026-09-13, S-65 — the
  steward and overseer build)*: three ledger-truth files at the home root
  and one subtree, `overseer/`, owned by the overseer's own runner. Full
  content contract: `02-schema.md` §3a.
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

02 §2's "route = one commit" was already false for user scope: UNTIL
2026-08-28, the chezmoi path had committed ledger-side and dotfiles-side
separately since M1 (E-17 extended) — history now (`U-hostmode` §4.8.1
made user scope a plain host, no dotfiles-side commit at all). The
honest invariant was never single-commit;
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
   naming `recompile --adopt`. **No entry at all, region present, is not
   automatically foreign:** if the on-disk bytes are byte-identical to
   what the ledger's current records would render for that target, the
   route self-adopts — writing the missing entry and proceeding, with one
   printed notice — since nothing else in the codebase produces that
   exact byte string; only a genuine mismatch still refuses. **This is
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

**Recovery runs first; a STOP refuses the batch; `batch` checks once
before item 1 (added 2026-09-11, Sprint 3 spec lane B — §7.2a, `S-62`).**
`reconcile`'s orphan scan is preceded, inside the same lock span, by
intent recovery (§7.2a.3): an interrupted multi-file transaction leaves
a staged rename the scan would otherwise report `blocked` forever, so
recovery goes first and the scan only ever sees a clean-or-ordinary
tree. When recovery leaves any intent `stopped`, `reconcile` refuses
its WHOLE orphan batch — the same all-or-nothing contract `blocked` and
`invalid` already carry — because the scan can see, and would stage,
the very files the stuck transaction half-wrote; the process exit is 6
with the offender named, and every ordinary orphan under that home,
the miner's own carried-over records included, stays uncommitted until
the STOP is cleared (§7.2a.4). **The `batch` verb runs the same check
once, before item 1**, so a pre-existing STOP refuses the sheet before
anything lands; each item's verb still runs its own check at its own
lock. **A mid-sheet 6 after an earlier item has committed reports 8
(`EXIT_BATCH_PARTIAL`), never 6** — this amends
`u-verbs` §3.3a's rule 3, under which a mid-sheet 6 promoted to the
sheet's exit code over commits that had already landed, contradicting
6's ratified meaning ("nothing was written"); 7 (half-written, repair
named) and the push codes 3/4 are unchanged.

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

**Two more jobs join the tick** *(Added 2026-09-13, U10 + O-4)*. `serve`'s
one-job-at-a-time tick (§5's own rule, unchanged) gains a steward job,
nightly, after the worker job in the same tick — never before it, since the
steward reads the worker's brief — and an overseer job, weekly, after the
steward job. Both are ordinary `serve` jobs in exactly this section's sense:
each takes its own lock, commits under its own pinned subject, and `serve`
itself never stages, commits, or pushes on their behalf (H-5 unchanged).
*(Amended 2026-09-24.)* So each publishes its own writes: every write inside
a steward or overseer run is `no_push`, and the run pushes once when it ends,
however it ends (complete, partial, a failed attempt, or an exception), if
the ledger `HEAD` moved during the run and something is still unpushed — the
bare `self-learn push` verb, so hosts the run committed into go too. A dry
run and a `no_push` request publish nothing.
`_steward_is_due`/`_overseer_is_due` follow the existing
`_mine_is_due`/schedule-state-parity shape; both run inside the same
`_worker_autokick_disabled()` span the mine and worker jobs already share,
for the same reason given there: no producer's follow-on tail may spawn a
detached child while `serve` is mid-tick. `doctor serve` and `status
--fast` gain `steward_last_run_at` only, read from the cached marker;
`steward_cases_since_overseer` walks the case store and stays on full
`status`, while `overseer_last_run`/`overseer_next`/`overseer_open_questions`
remain additive JSON fields *(Amended 2026-09-14, U10 fold r1a S6)*,
following the precedent §7.2a.7 already set for the intent-recovery status
line (full field list: §7.2a.7 as amended).
`systemd/self-learn-overseer.service`/`.timer` (weekly `OnCalendar`,
`Persistent=true`) join the miner/host unit pair; `install.sh` links but
never enables them, unchanged from every other unit this repo ships
(`CLAUDE.md` § Layout).

**The overseer's catch-up rule and the same-week guard** *(Added 2026-09-19,
`03-decisions.md` S-68)*. The weekly job is due on the first tick at or after
**Sunday 04:15 local for which that week is not done — whatever the weekday**.
A machine that was off all Sunday therefore runs the missed week on Monday
instead of skipping it in silence, and the product does not depend on
`Persistent=true` on a timer that is linked but never enabled to do it. **Only
the most recent Sunday boundary defines the current week**: after a longer
outage, older undone weeks are subsumed by that one catch-up run rather than
replayed one per week — the overseer's population is everything since its
last run, so the single run covers them, and nothing is run retroactively.
"Not done" is S-68's own test: a run for that week completed, or its attempts
reached `runs.attempt_cap` — read from committed run records, never from the
cache marker alone. **The catch-up applies only once a previous run exists**
(coverage's `last_run_at` is not null; orchestrator ruling 2026-09-19): an
overseer that has NEVER run stays on the plain calendar rule, due at the next
Sunday 04:15 local, so turning `overseer.enabled` on midweek cannot trigger an
immediate unattended first run. `self-learn overseer run` remains the way to
start the first one by hand, watched. The same test is the **same-week guard, and it lives in
the runner, not in the scheduler**: whoever starts an overseer run — the
`serve` job, a hand-typed `self-learn overseer run`, or the systemd timer if
a human ever enables it — re-checks it inside the run and holds without
writing when the week is already done, so two entry points cannot double-run
one week even with both enabled. A held run is a held outcome under the
unattended-run contract (`FW-85`), not a failure. Committed unfinished work
stays due regardless of the calendar, unchanged from O-4: a failed attempt is
retried after the existing two-hour attempt cooldown
(`miner.ATTEMPT_COOLDOWN_SECS`), on any day, until the week is done or the
cap closes it. *(Amended 2026-09-24, S-68: a hand-typed `self-learn overseer
run` is a manual run and is exempt from this guard — the user's words, "user
initiated runs don't count toward the weekly limit" — and, by the user's choice
of "No, Sunday still runs", its completion does not make the week done, so the
scheduled run still happens.)*

**A raise inside either due-check is a HOLD, not an attempt** *(Added
2026-09-19, S-68)*. It is logged, it increments no attempt count, and the job
is not due this tick. It arms that job's cache-side cooldown so the tick loop
cannot spin on it; while the cause persists it is shown in the `doctor` serve
row and the heartbeat as the reason that job is not running, and the user is
notified once per distinct cause, never once per tick. It never escapes into
`_run_tick`, where one exception ends the whole `serve` process — miner,
worker, steward and overseer together — and ends it again on every restart
while the cause persists. **Ordering, for both jobs: the cooldown test reads
only the cache attempt journal, and is evaluated BEFORE any git read.** Today
`_steward_is_due` reads committed manifests before it looks at a cooldown at
all (`serve.py:481-488`), so a wedged git would be re-entered on every 60-second
tick; with the order above it cannot be retried faster than the cooldown.
Counting a due-check failure as an attempt is explicitly NOT the rule: a check
that could not even read the state took ownership of nothing, and three ticks
against a broken git would otherwise exhaust a cap of 3 and park lessons
nobody examined. The case that motivated counting — an exception that recurs
identically on every resume — needs no help from the due-check: that attempt
is counted at its start, inside the run (`02-schema.md` §3a), so it reaches
the cap and closes out on its own.

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
  skills_root: ~/repos/claude-skills   # covers all 3 skills (glob)
  projects:
    - path: ~/repos/claude-skills
  ```
  **There is no dotfiles/user host entry in `hosts.yaml`** (audit
  correction 2026-07-16, M-2, still true today): `host add --kind
  dotfiles` is refused by design, and `~/.claude/CLAUDE.md` is
  deliberately NOT hosts-gated — it is a first-class PLAIN host by
  construction (`U-hostmode` §4.8.1, landed 2026-08-28, §4 item 5),
  never registered, never carrying a `.self-learn-host` marker. UNTIL
  2026-08-28 the SAME never-hosts-gated invariant held for a different
  reason: it routed through the chezmoi flow, which §2 already called
  "a host that was ALWAYS external" — history now, not the live
  mechanism. An earlier draft of this line said otherwise (before the
  2026-07-16 correction); the implementation (`HOST_KINDS =
  skills-root | project`) is correct and this doc was wrong.
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
     print(slug_for("~/repos/claude-skills"))')
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
  **Second clause (added 2026-09-11, Sprint 3 spec lane B — the intent
  bracket, `S-61`):** the four D7-covered transactions — `hosts.host_add`,
  `hosts.host_rebind`, `hosts.host_remove`, and the collapse leg of
  `verbs._execute_route` — open an *intent* (§7.2a) inside their lock
  span, BEFORE the first mutation, covering every ledger path the span
  touches, and close it AFTER the commit — so the lock and the intent
  bracket nest as `acquire → begin → mutate… → complete → commit →
  finish → release`, never in any other order (with `S-63`'s host-phase
  record the close moves past the last recorded host step, which for
  the retirement leg sits outside the ledger span; the lifetime and
  lock arrangement for that case are `FW-157`'s pre-build decision,
  §7.2a.9 — no other reordering is permitted). Any other multi-path
  transaction is outside D7 until a ruling widens it (`FW-157`(a)).
  The lock is what makes an intent found at acquisition a *leftover*
  (its writer crashed) rather than a live peer's; the intent is what
  makes the multi-file span recoverable, which the lock alone never was.
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
  **Second check (added 2026-09-11, Sprint 3 spec lane B, `S-62`):** the
  recover-or-refuse contract of §7.2a is pinned by a SEPARATE
  fail-closed census test, not by bending the walker: every call to
  `commit_lock` under `src/self_learn/` — the attribute form
  `gitops.commit_lock(` in other modules AND the bare `commit_lock(`
  inside `gitops.py` itself (`push_with_retry`'s take is bare; the
  census matches the resolved name, not one spelling) — is one of (a)
  the ledger-write wrapper itself, (b) a ledger site on §7.2a's exempt
  list, named by qualified function name, or (c) a host-repo
  acquisition, likewise named — and an unlisted site turns the test
  red; the census's positive control is the bare `commit_lock(repo)`
  in `gitops.py`. The walker's own lock set (`_LOCKS` in
  `tests/test_lock_invariant.py`) gains the wrapper's name if the
  promotion renames it (`_ledger_write` is already in the tuple),
  because a callee's lock never discharges a caller's obligation. The walker
  cannot express call ORDERING ("recovery ran before the first
  mutation"); that property is proven by the mutations §7.2a's test
  plan names, not by a structural test.
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

## 7.2a The intent transaction (D7) and the recover-or-refuse contract (added 2026-09-11, Sprint 3 spec lane B)

Sprint 2 lane M-W shipped a crash-safe multi-file ledger transaction
under decision D7 (`decisions-2026-09-04.md`, ruled 2026-09-04; three
gate rounds against real `SIGKILL`s, 2026-09-05). It was never written
into this corpus: until this section, the mechanism lived only in
`intents.py`'s module docstring. This section is the NORMATIVE text —
`03-decisions.md` rows `S-61` (the transaction), `S-62` (the
generalised contract) and `S-63` (the host-phase record) carry the
decisions and their rationale and point here. Code of record: `intents.py`,
`reconcile.py`, `gitops.py`, `batch.py` at master `a41ddb3`.

### 7.2a.1 The intent file

An intent is ONE JSON file at `<home>/.intents/<id>.json`, `id` twelve
hex characters, written under the ledger `commit_lock` before the
transaction's first mutation, rewritten by recovery when an attempt
fails (§7.2a.3), and removed after its commit. It lives in
the ledger home, not the XDG cache: the cache is not guaranteed to
survive a reboot and is namespaced by a hash of the home, while an
intent's only durability requirement is "outlives the crash it
recovers from", which the ledger's own directory satisfies by
construction. No `.gitignore` entry: an untracked `.intents/*.json`
matches no reconcilable path shape, so nothing in the tree ever stages
it, and a stray directory after a crash is a visible diagnostic. The
`a41ddb3` schema plus the `S-62` extension (`stopped`):

```
{"op": "collapse" | "host_add" | "host_rebind" | "host_remove",
 "id": "<12 hex>",
 "started": "<iso timestamp>",
 "steps": [{"path": "<HOME-RELATIVE path>",
            "old_sha": "<sha256 hex>" | null,
            "new_sha": "<sha256 hex>" | "-" | null,
            "old_inline": "<base64>"}, ...],     # key present only when captured
 "commit_subject": "<the pinned subject the transaction's one commit carries>",
 "stopped": {"reason": "<text>", "at": "<iso timestamp>"}}   # added 2026-09-11 (S-62):
                                   # present only after a failed recovery attempt, §7.2a.3
```

- **One step per PATH the transaction touches**, not per mutation of
  that path: only a path's state at the two endpoints matters for
  recovery. The step list covers EVERY ledger path the span touches —
  record moves, compile-record entries, retirement and resync paths —
  each registered before its first write (M-W gate r1 MAJOR-1).
- **`path` is home-relative**, so an intent is read back against
  whatever `home` recovery is given; a ledger restored from backup or
  moved recovers exactly like one that never moved.
- **`old_sha`** is the path's sha256 before the transaction; `null`
  means "did not exist" (restore = delete). **`old_inline`** is present
  only when the pre-transaction bytes are NOT recoverable from `HEAD`
  (untracked, or locally modified ahead of `HEAD`) AND are at most
  64 KiB (`_INLINE_CAP`); a larger untracked file has no inline copy,
  which is the one shape that makes a restore unresolvable.
- **`new_sha`** starts `null` ("unrecorded"); `complete` fills every
  step in one pass — a real sha256 if the path exists, the sentinel
  `"-"` if it does not (the vanished half of a rename). A `null` at
  recovery time is proof the crash landed before `complete`, i.e.
  mid-mutation; it is never confused with "expected absent".
- **`stopped`** is absent until a recovery attempt fails; recovery
  itself writes it (§7.2a.3) so a read-only reader can tell a recorded
  failed attempt from an intent with no such record. Not persisted
  at `a41ddb3`; the field is `S-62`'s, built with the guard lane.
- **Durability class:** the file has ONE writer (`intents._write_intent`)
  and it is `fsops.atomic_write(…, fsync=True)` — the records class of
  the D6 write policy, so an intent that a crash left on disk is either
  the last complete state written or absent, never torn.

### 7.2a.2 The bracket discipline

The bracket nests inside the lock span (H-7, second clause), in this
order and no other:

1. **`begin` — before the first mutation.** Captures every known path's
   pre-state and writes the file. A mutation that precedes `begin` is
   outside the transaction and unrecoverable by it.
2. **`add_step` — before a later path's first mutation.** For a path not
   knowable at `begin` time (a collapse's compile-record target resolves
   its host slug mid-transaction). Same before-the-mutation discipline;
   a path already present is a no-op, so a retry never duplicates it.
3. **`complete` — once, after the last mutation and before the commit.**
   Records every step's ACTUAL final state. A crash before this call
   restores; a crash after it rolls forward, even if the commit itself
   never ran.
4. **`finish` — after the commit landed.** Unlinks the file.

Four writers bracket today: `hosts.host_add`, `hosts.host_rebind`,
`hosts.host_remove`, and the COLLAPSE leg of `verbs._execute_route`. A
plain (non-collapse) route opens no intent — D7's own exclusion, which
`S-63` keeps (widening it is a decision nobody has made; `FW-157`(a)).

### 7.2a.3 The three outcomes

`intents.recover(home)` reads every `.intents/*.json` under the ledger
lock and resolves each intent to exactly one of:

- **`rolled_forward`** — every step's `new_sha` is present and verifies
  against the path on disk (hash match, or confirmed absent for `"-"`):
  stage every step path that still exists and commit with the recorded
  subject. The commit is `allow_empty`: a crash between the commit
  landing and `finish` leaves every step verified with nothing to
  stage, and that reads as success — `gitops.stage_and_commit` skips
  the commit when staging produced no diff, so a roll-forward NEVER
  creates a second commit (M-W gate r1 held "no duplicate roll-forward
  commit").
- **`restored`** — otherwise, when every step's pre-transaction bytes
  resolve BY CONTENT, tried in order: the current on-disk bytes already
  match `old_sha` (a step never actually mutated); `HEAD`'s blob at that
  path matches `old_sha` (whichever commit `HEAD` now names); the
  inline copy matches. Then every step is written back (a `null`
  `old_sha` deletes the path and prunes directories the deletion left
  empty), every step path is `git reset --` so the index matches the
  worktree (a staged rename's vanished old half included), and the
  intent is removed. Because resolution is by content and not by
  `HEAD`'s position, an unrelated commit landing while an intent sits
  unresolved cannot stale it — which is why a `base_head` field was
  rejected (M-W gate r1 BLOCKER-1 ruling).
- **`stopped`** — any of: the file cannot be read or parsed (an
  `OSError` or any `ValueError`, non-UTF-8 included — a different repair
  from an unresolvable step and reported as "unreadable intent file");
  one step's prior bytes resolve from none of the three sources; the
  roll-forward commit failed; a restore failed partway. For a STOP
  detected BEFORE anything was applied (an unreadable file, an
  unresolvable pre-image) no step path is changed — only the outcome
  metadata below is written; for an operational STOP (a commit or a
  restore write failed) what recovery had already written stays on
  disk and the STOP line says so, naming the path it failed at. Either
  way the file stays in place, the offender is named, and recovery
  PERSISTS the outcome: it rewrites the intent (same single writer,
  same durability class) with a `stopped` field carrying the reason
  and a timestamp (§7.2a.1), so a read-only view (§7.2a.7) can tell a
  recorded failed attempt from an intent with no such record. An
  unreadable file cannot carry the field; unreadability is itself the
  STOP any reader can see. **Marker publication can itself fail**, and
  two cases are distinct. *Caught failure, the caller survives:* the
  rewrite raises (`ENOSPC` creating the replacement file; or the
  directory fsync AFTER `os.replace`, at which point the new marker is
  already visible — atomic replacement guarantees complete bytes, old
  or new, not which). The caller knows both failures and reports both:
  its demonstrated recovery failure, plus "failure outcome could not
  be durably confirmed"; it retains the intent, refuses its requested
  work exactly as for a marked STOP, and assumes NOTHING about which
  bytes are on disk — the file may be unmarked, carry the new marker,
  or carry an earlier retry's. *Process death before the rewrite:* no
  process survives to know the reason, and the file carries whatever
  was last durably written. A later process reports only what it can
  read and the outcome of its OWN retry, which may succeed if the
  fault was transient; it never asserts an earlier, unrecorded
  failure. So an unmarked file means "no durable record of a failed
  attempt", never "never attempted". Within one protected span a
  demonstrated failure is never discarded because its marker cannot
  be written: the wrapper and the clear leg (§7.2a.4) act on the
  attempt they just made, not only on the marker. A later recovery
  run re-attempts a persisted STOP (a transient fault may have
  cleared) and rewrites the field on failure: the field records the
  last attempt, never a decision to stop trying; the attempts are
  idempotent (a restore rewrites the same pre-images) and no
  suppression cache is added. A STOP is permanent by construction once
  `HEAD` has moved past a step's `old_sha` with no inline copy: only
  clearing (§7.2a.4) ends it. Recovery processes every leftover intent
  in order, so one run can roll forward or restore some and STOP on
  another; the completed outcomes are reported beside the STOP, never
  hidden by it.

**What recovery never does — M-W gate r1 MAJOR-2, preserved verbatim:**
*"recovery NAMES the host repair (`self-learn recompile`) on all three surfaces; it does NOT run the host phase (unattended host-repo writes from the miner's/worker's start would be a new mutation surface; the ledger→host two-phase seam predates M-W and has `recompile` as its documented repair)."*
Every surface that reports a `rolled_forward`
outcome prints the repair by name: `recovered <id> (rolled forward: its
commit landed — the host phase did not run; run 'self-learn recompile')`.

### 7.2a.4 Clearing a STOP

Clearing a STOP means: a person or the recovery verb (§7.2a.6) has
inspected the offending path, accepted the intent's step paths AS THEY
ARE ON DISK, and removed `<home>/.intents/<id>.json` under the ledger
lock. The half-written files then re-enter the ordinary contract — the
next `reconcile` commits them as orphans if they validate, or reports
them `blocked`/`invalid`. Only an intent that classifies STOPPED may be
cleared — its file is unreadable, it carries the `stopped` field a
failed recovery attempt persisted (§7.2a.3), or the clear leg's own
recovery attempt, made in this span on an unmarked file, has just
failed on it (a marker that could not be written does not
un-demonstrate the failure) — and the classification that authorises
the deletion is made under the lock, in the same protected span as the
deletion, from the file's bytes and the attempt made at that moment;
a `status` snapshot taken earlier authorises nothing. An unmarked
leftover is attempted first, as every recovery does: one that recovers
is recovered and reported, not cleared; one whose writer is live is
never touched. By hand, the
contract is unchanged from M-W: read the offender named in the STOP
line, decide, delete the file, re-run `reconcile`.

### 7.2a.5 The recover-or-refuse contract (every lock-holding ledger commit path)

At `a41ddb3` recovery runs on four surfaces and on none of the other
ledger lock sites (readiness review §A). The contract below closes
that with ONE seam; its five answers are the user's rulings of
2026-09-11 14:31 (`GO-NO-GO-2026-09-11.md`) and the readiness review's
settled findings (`assess-live-intent-commit-paths.md` §B, §D.2).

**(1) The seam is a ledger-level lock wrapper, NOT `gitops.commit_lock`.**
`verbs._ledger_write(home)` is promoted to a shared, importable
ledger-write wrapper — call it `ledger_write(home)`; the module it lives
in is the builder's choice provided every converted module can import
it without a cycle — and every direct `gitops.commit_lock(<ledger
home>)` site is converted to it, nested takes included (a nested take is
a pass-through, §7.2a.5(2)). The check runs in the wrapper. A builder
MUST NOT place the check inside `gitops.commit_lock` or `_flock_lock`,
for two independent reasons: (a) `commit_lock` is taken on HOST repos
too (`verbs.commit_drift`, `verbs.recompile`'s host commits) and shares
its body with `host_lock`, while intents are ledger-scoped — a guard
there would fire on a host acquire and look for `.intents/` in a user's
repository; (b) it recurses — `intents.recover` itself takes
`commit_lock(home)`, so a guard inside `commit_lock` that calls
`recover` re-enters `commit_lock` and fires again. **Exempt ledger
sites** (each a named entry of H-8's census, each with its reason):
`intents.recover` — it IS the recovery, and its own `commit_lock(home)`
becomes a pass-through when reached through the wrapper;
`intents.clear_stopped` — the §7.2a.6 clear leg, exempt for the same
reason (it is part of recovery, and it must run before the check would
refuse on the very intent it removes); `ledger.init_home`'s fresh/empty
non-repo initialisation takes only (its steps 3 and 5: a directory
self-learn just created, or an existing EMPTY non-repo directory) — no
intent can exist there, and each site is pinned to a literal `with
gitops.commit_lock(…)` form the walker can see (`ledger.py`, the
manual-`__enter__` note). `init_home`'s step-6 take is NOT exempt: that
step mutates an EXISTING home — layout top-up, and an initial
`--allow-empty` commit of whatever is staged when `HEAD` is absent,
which under a STOP could be the stuck intent's own staged rename — so
that one take converts to the wrapper, keeping its guard widened to the
refusal type so `init` still refuses cleanly instead of leaking a
traceback (the site's own comment names that signature) (re-read
against `ledger.py` 2026-09-11; the readiness review's blanket reason,
"a fresh ledger has no `.intents/`", is true of steps 3 and 5 and false
of step 6). **Not exempt:** `gitops.push_with_retry`'s
rebase leg, when the repo being pushed is the LEDGER, converts: it
checks at its own acquisition and refuses the rebase on a STOP (the
refusal is printed; the push surface's exit stays 0, §7.2a.5(5)). No
prior recovery covers that acquisition — `teach` pushes through
`push_if_remote` with no `reconcile` on the path, `batch` pushes at
sheet end likewise, and even the `push` verb's own `reconcile` ran
under an earlier, released span, so a writer can crash in between.
The leg's bare `with commit_lock(repo)` stays for HOST repos, outside
this contract; how the leg learns which lock to take (a parameter from
the push surface is the obvious form) is the builder's, and H-8's
census classifies the surviving bare site as a host-repo acquisition,
with a test proving the ledger push path takes the wrapper.
`reconcile.reconcile` converts to the wrapper and reads the outcome it yields (§7.2a.5(3)),
which also closes the two-acquisition gap its docstring records
(recovery used to run under its own lock, then the orphan scan under a
second); `verbs._stage_and_commit`'s nested take converts;
`worker.run`'s start-of-run `intents.recover` call is not a lock site
and stays where it is (it sits on an armor-pinned path); the only
change there is what the run does with a `stopped` outcome, §7.2a.5(4).
Host-repo
acquisitions are named in the census and are outside this contract.

**(2) Ordering: outermost acquisition, inside the lock, pre-mutation —
and the transaction's own intent is exempt BY ORDERING.** The check
runs exactly once per lock span: on the OUTERMOST acquisition of the
ledger lock in this process, AFTER the lock is held, BEFORE any
requested mutation IN THAT LOCK SPAN (recovery's writes are the
check's, and an earlier span's commits are that span's, §7.2a.5(4)),
and BEFORE the verb's own `intents.begin`. Because the
verb's intent does not yet exist when the check runs, it is exempt by
construction; a builder MUST NOT thread an intent id through call
chains or keep a lock-holder registry to identify "own" — there is
nothing to identify. Mechanically: the wrapper's body runs on EVERY
nested `with`, pass-through or not, so the wrapper tests whether this
process already holds the ledger lock BEFORE acquiring (today: the
`_held_locks` bookkeeping behind `gitops._flock_lock`, keyed by
`commit_lock_path(home)`) and skips the check when it does. This is not
a nicety: a guard that re-ran on a nested acquire after `begin` would
see the transaction's OWN intent with every `new_sha` still `null`,
classify it restorable, and undo the live transaction's writes
mid-flight — silent corruption produced by the safety guard. A
concurrent process is excluded by `flock`, so any intent visible at
acquisition belongs to a crashed writer or one that finished and failed
to clean up, never to a live peer.

**(3) What "recover" means, per path — FINISH AND TELL.** An intent
that recovery can finish (roll forward or restore) is finished at the
check, whoever the caller is; the wrapper hands the outcome (the three
id lists, with each STOP's offending path and reason) back to its
caller, and the caller's surface reports it BEFORE its own output: an
attended verb prints the same three-line shape `reconcile` prints
today, a batch item's outcome rides the `--json` envelope, the miner
and worker log each recovered id on its own line. Unattended callers
(the miner's landing commit, the worker's commit and harvest locks,
`telemetry.flush` when the miner or worker calls it, and all of these
again under `serve`'s tick, the steward's own run
(`13-hosting-and-separation.md` §5, added
2026-09-13), and the overseer's own run (same section)) recover the LEDGER half of a recoverable
intent exactly as their run-start recovery already does, log it, and
never act on a host step; an attended caller does not act on a host
step either — the attended host repair is `self-learn recompile`, named
in the printed line (§7.2a.3, MAJOR-2). The hand-edit refusal does
not trip after a roll-forward: the compile record's `sha256` is
the predicted post-write region and its `based_on_sha256` the region
observed before the write, so a host file the interrupted verb never
touched reads `stale` under `compiled.verdict_for`, and `stale` is not
in `REFUSING_VERDICTS` — the verb's own host write then proceeds and
repairs the drift as a side effect (readiness review §B(i), verified
against `compiled.py`).

**(4) STOP scope — OPTION 1, refuse everything.** When the check finds
an intent it cannot finish (a `stopped` outcome), EVERY ledger-write
verb refuses at lock acquisition, exit 6, nothing written — one generic
seam, no per-verb path prediction. For the four unattended runs the
refusal point is the RUN START, not the landing lock: the miner's
run-start `reconcile` and the worker's run-start `intents.recover`, the
steward's run-start `intents.recover` (`steward.py`, mirroring the
worker's), and the overseer's run-start `intents.recover` (`overseer.py`,
same shape)
already report a `stopped` outcome, and a run that sees one ends
there — exit 6, or the job record under `serve` — before enumeration
and before any model session is spent. Today both log the STOP and
proceed (readiness review A-1), and the miner's "never fatal" healing
wrapper is what carries it on; that wrapper gets this one exception,
because a run that cannot land has nothing to mine for. The landing
lock's check (the miner's landing commit, the worker's commit and
harvest locks) is the backstop for a STOP that appears mid-run, not
the first line. The cost, stated plainly: **one
stuck intent file freezes `teach`, the 03:30 nightly mine, the worker,
`telemetry.flush`, `config set`/`unset`, every import, every
resolution verb and every batch, until recovery clears it** — and
under `serve` the mine and worker jobs fail every tick, recorded in the
job record, with no other alarm unless §7.2a.7 is built. Each refused
write re-attempts the STOP first; the attempts are idempotent and the
field records only the last one (§7.2a.3). The user
chose this outage over the alternatives with the cost in front of them
(14:31). Rejected: overlap-only refusal checked at commit time
(unsound — by then the verb has `git mv`'d and staged, so the refusal
manufactures the staged-rename shape `reconcile` cannot repair: exit-7
semantics under an exit-6 label); the hybrid `ledger_write(home,
paths=…)` is deferred, not rejected (readiness review §B(iii), Option
2). `reconcile` keeps its whole-batch refusal on STOP unchanged.

**What a STOP promises — three separate facts, never one.** (a) The
requested verb's OWN mutations IN THE REFUSED LOCK SPAN: none. The
check refused before that span's first requested write, and that is
the whole content of exit 6. (b) Recovery actions that completed in the
same check before the STOP (other intents rolled forward or restored —
a commit landed, bytes restored): reported, never hidden behind the
refusal. (c) A recovery attempt that partially mutated (a restore write
or a roll-forward commit failed midway, §7.2a.3), or whose failure
could not be durably recorded: reported as such, naming the path it
failed at, the intent left in place. **Multi-span verbs, stated
explicitly.** A verb with several outer lock spans (`recompile --adopt`
commits under one span and takes another later) is refused at the span
where the STOP appears. The commits of its earlier spans are the verb's
own work: they stand — a later STOP does not un-write them — and the
refusal carries them beside the recovery outcomes, printed as `no
further requested writes; earlier commits: <subjects>`. The process
code for that case: **6** only when no span of the invocation
committed; when an earlier span committed, **8** (`EXIT_BATCH_PARTIAL`,
whose ratified meaning is "some of the requested work landed and the
rest was refused; read the output" — `batch` in §5 is the model), with
the earlier commits named — never a code that claims the invocation
wrote nothing.

**(5) Exit codes and the refusal message.** A STOP refusal is a
DISTINCT exception type (a `GitOpsError` subclass; the name is the
builder's, the distinction is not) raised before the refused span's
first requested mutation, carrying the recovery outcome — the three id
lists with each STOP's offending path and reason, any completed or
partial recovery action of §7.2a.5(4)(b)/(c), and the verb's own
earlier-span commits, if any — whose message names the intent id, the
offending path and reason, what recovery did, what this verb wrote
before the refused span (nothing, or the earlier commits), and the
clearing verb — e.g., for a first-span refusal: `self-learn:
transaction intent <id> is STOPPED (cannot restore <path>: <reason>);
this verb wrote nothing — every ledger write refuses until it is
cleared. Inspect the path, then run 'self-learn reconcile
--clear-intent <id>' to accept its current on-disk state, or delete
<home>/.intents/<id>.json by hand.` After an earlier span committed
the second clause reads `no further requested writes; earlier commits:
<subjects>` and the exit is 8 (§7.2a.5(4)). For a first-span refusal
the process exit is **6** (`EXIT_GIT_FAILED`, whose "nothing was
written" is fact (a) of §7.2a.5(4) — the requested verb's own writes in
the refused span — and says nothing about recovery's, which the
message reports separately), on every surface,
including the 22 `_cmd_*` handlers and `teach` that reach `main()`'s
generic `GitOpsError` catch: that catch gains one dedicated arm for
this type that prints the message above and NOT the generic hedge
("this surface did not say whether anything was written"), which
would be false here. **`batch`:** the sheet-level check, the per-item
checks and the 8-not-6 rule are §5's; a refusal's carried outcome
rides the item's `--json` envelope. **`push`:** stays **0** on STOP.
`push` runs `reconcile` first; a refused reconcile is informational on
push (M-C's contract, ruled NO CHANGE 2026-09-05 02:45): the refused
batch means nothing corrupt can publish, what IS committed
republishes, and the stderr line names the intent; a STOP met at the
ledger rebase leg (§7.2a.5(1)) is printed the same way and the exit
stays 0. This asymmetry with the verbs is deliberate and recorded
here so a builder does not "fix" it. **`reconcile`:** exit 6 on STOP
as today, converted to the wrapper: it catches the refusal type and
renders the carried outcome as its own refused result (offenders
named), so `push` sees a result, not an exception. Any other surface
with an envelope of its own (a batch item, a `--json` caller) may
catch the type the same way to fill it; what is required is the
carried outcome and the truthful message, not a catch topology.

### 7.2a.6 The recovery verb — callable, machine-readable, and able to clear a STOP (the adjudicator rider)

The user's rider on option 1 (14:31): the attendant agent to be built
after this sprint (S-29 / FW-82) must be able to clear a stuck intent
itself. Consequences, each new surface (`FW-158`): **`self-learn
reconcile` is THE recovery verb** — it already runs recovery first and
is what every refusal names. It gains **`--json`**: one envelope
carrying the three outcome lists (each STOP with its intent id,
offending path and reason), the orphan-scan lists (`committed`,
`blocked`, `invalid`), the `refused` flag, and what was cleared — the
exact field spelling is the build's, the content is not. It gains
**`--clear-intent <id>`**: under the ledger lock, remove
`<home>/.intents/<id>.json` ONLY if that intent classifies STOPPED
under §7.2a.4's rule — unreadable, carrying the persisted `stopped`
field, or failing the clear leg's own recovery attempt made in this
span on an unmarked file — decided in the same protected span as the
deletion from the file's bytes and that attempt (an unmarked intent
that recovers is recovered and reported, not cleared; a live writer's
intent is refused with a named reason; a `status` snapshot is not
authorisation), record the clearing in the
envelope, then proceed with the ordinary scan (§7.2a.4). The clear leg belongs to the recovery module —
`intents.clear_stopped(home, id)`, a named entry of §7.2a.5(1)'s exempt
list and of H-8's census: it takes the lock the way `intents.recover`
does and is exempt from the wrapper's check for the same reason — and
it runs BEFORE that check would refuse
on the very intent being cleared; a clear placed after the wrapper's
check can never run, since the STOP it exists to remove refuses it
first. Under the S-29 autonomy policy this verb is listed as a
**candidate auto-action, NOT auto-applied by default**; S-29's hard
floors (hook routes never auto-applied, secret-scan blocks always
escalate) are unchanged, and the policy's supervised-first sequencing
still governs when an agent may run it unattended.

*Amended 2026-09-13:* "hook routes never auto-applied" now has one named
exception, the overseer (`S-29` as amended, `S-66`); the secret-scan floor
is unchanged and, per the amended S-29, is now the *only* unconditional
floor. `reconcile --clear-intent` itself is unaffected by either clause —
it was never a hook route.

### 7.2a.7 Visibility — a STOP must be seen where the operator looks

Two measured gaps at `a41ddb3` make option 1's outage silent, and the
contract requires both closed in the same lane: (a) `status`'s
live-intent line does not distinguish a STOP from a transaction in
flight, and (b) the SessionStart hook (`hooks/self-learn-pending.sh`)
runs `status --fast 2>/dev/null`, discarding the stderr line the
function's own docstring calls the human's one notice. Requirements:
**`status`** (full and `--fast`) classifies every intent READ-ONLY —
no recovery, no ledger mutation — from ONE coherent snapshot: it probes
the ledger commit lock non-blockingly and, on success, lists and reads
every intent file WHILE holding the probe, then releases it; on
contention it reads no file as current state. The probe is a SEPARATE
read-only primitive, not `gitops._flock_lock` — that helper opens the
lock file for writing (truncating the holder's pid), writes its own
pid, and retries; it is the mutating house pattern. The probe opens
the lock file `O_RDONLY|O_CREAT` (an empty lock file created when
absent is the only byte it can cause and is not a ledger write; it
never truncates, so a live holder's pid survives being probed) and
takes `LOCK_EX|LOCK_NB` exactly once; that is the only lock interaction
`status` performs. Classes, in this precedence: *busy* (the probe
found the lock held: a transaction in flight or a recovery running;
the intents on disk are somebody's, `status` says so without calling
any one of them harmless or leftover, and any marker it can see is
labelled a historical failed attempt, not current state); *stopped*
(lock free, and the file read under the probe is unreadable or carries
the persisted `stopped` field, §7.2a.3: an outage — "every ledger
write refuses until …", naming the clearing verb); *pending* (lock
free, no marker: a leftover with no durable record of a failed
attempt, which the next ledger write attempts — `status` does not
promise that attempt will succeed, because matching hashes cannot
promise I/O). A file that vanishes between listing and reading under
the probe is reported as absent — an observed absence, classified as
neither pending nor stopped. A probe that fails for any reason other than
contention (`EACCES`, an unreadable lock directory) is reported as
*unknown — could not probe the ledger lock: <reason>*, never as free;
the pid the lock file carries is a diagnostic, not the classifier.
This is a status classification, not a fourth D7 outcome.
**`status --fast`'s JSON payload** (08 §7.1's pinned, machine-parsed
contract) gains ADDITIVE fields carrying the stopped ids and the
counts, so the fact survives `2>/dev/null` by the route the hook
already reads. **The pending hook** prints a session-start line
whenever a stopped intent is reported, naming the verb that clears it —
it must not discard the warning, by whichever route. **`serve`'s
tick** must surface a refusal: a job refused by the guard logs the
refusal on its own line naming the intent id (REQUIRED), and
**`doctor`** carries a row that reads the ledger's `.intents/` and
reports "N stopped intent(s) — last recovery failure at <at, or
'unknown' for an unreadable file>; ledger writes refuse; run …"
(REQUIRED). Recording the last failed job and its reason in the
heartbeat is RECOMMENDED — `serve.write_heartbeat` carries only
`next_job` today, so that is a new field on its contract, not a
restatement — and the `doctor` row reads it when present. A refusal
that reaches only the job record and the journal does not satisfy this
section.

**The overseer's status/doctor row** *(Added 2026-09-13, O-4/O-5)*: the
same visibility discipline this section states for a STOP applies to the
overseer's own cadence — `status --fast` and `doctor serve` gain
`overseer_last_run`, `overseer_next` (the next due weekly tick), and
`overseer_open_questions`. The open-question count comes only from the
committed `overseer/open-questions.yaml` machine index (one entry per
question — its id, kind and affected case ids, plus an ask's text and why;
no count limit since 2026-09-24), never by parsing the report's
prose or walking the case store. These are additive JSON fields on an existing read-only surface,
not a new command; a `status`/`doctor` run that omits them is not this
section's fault, but a build that never wires them through is.

### 7.2a.8 Test plan the blind code gate verifies

- The wrapper's name joins `_LOCKS` in `tests/test_lock_invariant.py`
  if the promotion renames it (H-8; `_ledger_write` is already in the
  tuple), or every converted site reads as unlocked; the wrapper is
  used as a literal `with` statement everywhere (the walker recognises
  only that form).
- The census of §7.2a.5(1) is a SEPARATE fail-closed test, in the
  walker's file or beside it — not a bend of the walker; it sees both
  spellings of `commit_lock`, and the bare site in `gitops.py` is its
  positive control.
- Behavioural tests plant an intent in each of the three states
  (`begin` → mutate → `complete` → crash before commit; `begin` →
  mutate → crash before `complete`; an oversize untracked step above
  `_INLINE_CAP`) against each path family — an attended resolution
  verb, a batch item, `teach`, `telemetry flush`, `config set`, the
  miner's landing lock, the worker's commit lock, the three
  `hosts.host_*` writers (which must now check before opening their
  own intent) — plus regressions for `reconcile` (6, HEAD unchanged,
  intent left on disk, `stopped` field written), `push` (0, line
  printed; the ledger rebase leg refuses under a planted STOP and the
  host rebase leg does not check), `--clear-intent` (per §7.2a.4's
  rule, three outcomes exercised: already stopped or unreadable →
  cleared; unmarked and failing the clear leg's own attempt in this
  span → cleared after that demonstrated failure; unmarked and
  recovering → recovered and reported, NOT cleared; and a live
  writer's intent → deletion refused), and `status`
  (stopped / busy / pending read-only). The plant helper
  goes in a NEW, non-pinned module; `support.py` is byte-pinned and
  must not change. Planting replaces re-driving a `SIGKILL` per path;
  the subprocess-kill harness in `test_intents.py` already proves the
  crash shapes.
- Mutation verification, per `CLAUDE.md`: delete the check → red;
  invert the `stopped` branch → red; move the check outside the `with`
  → red. **Mandatory, named here because it is the only proof of
  §7.2a.5(2):** disable the outermost-acquisition check so recovery
  runs on a nested acquire, and confirm `test_intents.py`'s
  `TestCollapseCrashWindows` and `TestCollapseWithOldIdCrashWindow`
  redden — a guard that restores the live transaction's own intent
  mid-flight would otherwise ship green.
- Every "nothing was written" absence assertion has its positive
  control first: the same verb succeeds and commits with no intent
  planted.
- Marker-publication failure (§7.2a.3), three cases, each stating
  its injection boundary and the marker state before the attempt.
  (i) Caught failure BEFORE replacement (the intent writer raising
  `OSError` ahead of `os.replace`), starting unmarked and again
  starting with an earlier retry's marker: the surviving caller's
  report carries both facts (its recovery failure; "could not be
  durably confirmed"), the intent is retained, the requested work
  refused; the file's bytes are whatever they were before (the test
  asserts the pre-attempt bytes for THIS boundary only). (ii) Caught
  failure AFTER replacement (the directory fsync raising): same
  two-fact report and refusal; the file now carries the new marker,
  and the test asserts that, not old bytes. (iii) Process death after
  a failed attempt and before the rewrite (the `SIGKILL` harness):
  the file is readable and unmarked; the NEXT ledger write reports
  only what it reads plus its own retry's outcome — with the fault
  still active it refuses and marks; with the fault cleared it
  finishes the intent and proceeds. The two-fact report is required
  from the surviving caller in (i)/(ii), never from the next process
  in (iii).
- Status interleaving witness (§7.2a.7): a second process holding the
  ledger lock with an unmarked intent on disk → `status` reports
  *busy*, never *pending*; the same with a marked intent → *busy* with
  the marker labelled historical; after the probe the holder's pid is
  intact in the lock file; a probe error other than contention →
  *unknown*.
- The change touches `worker.run`'s path, so the armor-pinned
  end-to-end files (`test_attrib.py`, `test_worker.py`,
  `test_repair.py`, `test_invocation*.py`) run before merge. The
  start-of-run recovery call is unmoved (no dated armor exemption);
  the new "a `stopped` outcome ends the run" branch (§7.2a.5(4)) gets
  its own test in each of the miner and the worker — plant a STOPPED
  intent, run, assert exit 6 (or the job record under `serve`) with
  no model session started — with the positive control first: a
  RECOVERABLE intent is finished and the run proceeds
  (`TestWorkerRunFindsAnIntent` already is that control for the
  worker).

### 7.2a.9 The host-phase record (option B) — what the intent says about the host, and what it never does

`S-63` chooses option B of the robustness review's four
(`assess-robustness-followups.md` ITEM 3): **the intent RECORDS the
host-phase steps; recovery turns the repair line into a precise one; no
unattended caller ever acts on a host step; the attended completion of
a host step is `self-learn recompile`, H-2's existing repair.** Design
facts a builder needs, fixed here; the build itself is deferred
(`FW-157`):

- **Host steps live under their own key, never in `steps`.** The intent
  is single-repo by construction (creation records home-relative
  ledger paths and rejects targets outside the home), and D7's two-outcome
  classification runs over `steps` alone. A separate `host_steps` list
  keeps that classification byte-for-byte: `[{"host": "<host path as
  registered in hosts.yaml>", "target": "<target path relative to the
  host>", "record": "<lrn-id>", "based_on_sha256": "<region hash
  observed before the write>", "sha256": "<region hash the write was to
  produce>"}]` — the same two hashes the compile record already stores
  for this target, over the managed REGION, not the file. No new
  hashing vocabulary is introduced. The pair describes a target that is
  a contained managed region of a file inside the host — the shape the
  compile record hashes; a destination the compile record addresses
  differently (a reference target outside the host, a hook, a new skill
  file) is not representable by it and is `FW-157`(d), a pre-build
  question — until answered, such a step is not recorded and §7.2a.3's
  generic line stands for it. `based_on_sha256` is nullable: a fresh
  host has no prior region.
- **The record covers both host phases** (the successor's `_host_phase`
  and the retirement's `_retirement_host_phase`) under two invariants
  fixed here and not negotiable at build time. (i) **Pending host work
  is durably discoverable at the ledger-commit boundary:** by the time
  the ledger commit lands, the intent already names every host step
  that commit obliges — a step added only when its phase starts would
  leave a crash between the commit and that phase unrecorded, and a
  crash after the successor phase but before a retirement step is
  added would read as wholly complete. (ii) **No other acquisition may
  classify a still-running transaction as leftover:** an intent kept
  alive past the ledger commit must not be visible as a leftover to a
  writer that takes the ledger lock while a host phase is still
  running — `_retirement_host_phase` runs outside the ledger span today
  (`verbs.py:4322`), so merely moving `finish` past it would let a peer
  recover and delete a live transaction's intent, breaking
  §7.2a.5(2)'s own-intent-by-ordering. The intent's lifetime and the
  lock arrangement that satisfies both (the host phases inside the
  ledger span, a liveness marker on the intent, or another form) are
  `FW-157`'s pre-build decision (b); the design is incomplete until
  that decision is folded and gated. A crash inside a recorded host
  phase leaves an intent whose ledger steps all verify (the roll-forward
  leg, no second commit, §7.2a.3) and whose `host_steps` say what was
  pending. Pushes are not steps (idempotent, outside every lock).
- **Recovery reads host steps only to speak — on the roll-forward leg
  only.** A restored intent's host steps describe work that never
  became truth and are not reported. For each host step it reads the
  target's current managed region, read-only, and reports the
  observation actually made, in this precedence: *unavailable* (a
  read or parse failure OTHER than confirmed absence of the file or
  region — an unreadable file, or malformed managed markers, on which
  `compiled.region_bytes` raises; confirmed absence is evaluated under
  the prior/missing rules below) → `host <host>
  target <target> for <record>: could not read the managed region
  (<path>: <read/parse reason>); run 'self-learn recompile'` — a host
  observation that fails NEVER becomes a ledger-recovery failure: the
  ledger outcome was decided before any host step was read, and this
  line is diagnostic only; *matches expected* (`sha256`) → `… region
  matches the expected content; its host commit is not verified from
  here — run 'self-learn recompile' to confirm`; *matches prior*
  (`based_on_sha256`; or the region is absent and `based_on_sha256` is
  `null`) → `… matches the prior state for <record>: the ledger
  committed; the host phase still needs checking — run 'self-learn
  recompile'` (an observation of current bytes, not a claim that the
  phase never ran); *missing* (the file or its managed region is absent
  and a prior region was recorded) → `… is MISSING for <record>: the
  file or its region is gone; run 'self-learn recompile'`; *differs* (a
  successfully read region matching neither hash) → `… DIFFERS from
  both recorded states for <record>; 'self-learn recompile' will
  refuse it as a hand edit (REC5) — inspect it`. A worktree hash never
  proves a commit landed (`_host_phase` writes the bytes and only then
  commits), so no line claims completion. A host phase that
  legitimately produces no host commit (a no-op write; a `plain`-mode
  host) is complete when its step's expected region is observed, which
  is the completion the intent's close uses for those cases. It writes
  nothing to any host, from any caller. The lines replace the generic
  "the host phase did not run; run 'self-learn recompile'" of §7.2a.3
  wherever a host step is recorded.
- **Scope stays collapse-only** (D7's exclusion, §7.2a.2). Whether a
  plain route should open an intent so its host phase is recorded too
  is a decision owed before `FW-157` builds, not made here.
- **Build precondition:** in `FW-157`'s trigger (M-I wave 3), not here.

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

## 7.4 The overseer's hook-activation path (O-2)

*Added 2026-09-13, S-66 — the overseer build.* Today a hook route
generates a guard script and prints two manual steps that a human runs by
hand; the batch executor refuses hook routes outright ("a hook route is
refused inside a batch (S-29) — route it by hand"); `install.sh`
deliberately never touches guard scripts or `settings.json`. `S-29` as
amended gives the overseer the authority to approve *and install* a hook on
the user's behalf. This section makes that authority one verb, not a
relaxation of the batch refusal above.

**The gate.** `overseer.hook_activation` is a committed-config key (the
S-10 opt-in pattern), **default `false`, fail-closed on anything but YAML
`true`.** It governs only the overseer's own automatic path, never a
human's: with it `false`, the overseer applies an approved hook route only
as far as step 1 below (placed) and then parks it, with a receipt saying
activation is delegated but switched off — the same two-manual-steps state
this file already describes for a human. With it `true`, the overseer's
own call proceeds through all three steps. `misc/audit-2026-09-02/steward-design/seam-reconciliation-2026-09-12.md`'s
standing recommendation — switch this OFF until one hook has been
activated by hand — governs the setting's initial value, not this
section's mechanics.

**The path.** Two callers, one set of steps, resolved against
`<claude_dir>` — `$SELF_LEARN_CLAUDE_DIR` if set, else `~/.claude` — so a
test run never touches the real directory:

- **The human path**: `self-learn hook activate <record-id> [--json]`, a
  CLI verb outside `batch`, writes its own receipt directly.
- **The overseer's path**: a sheet item for the hook route, applied
  through `batch.run(..., actor="overseer", hook_activation=True)` — two
  keyword-only parameters only the overseer's own runner call sets, never
  sheet text. `batch` keeps refusing a hook route on every ordinary sheet,
  unchanged (the default is `actor="human", hook_activation=False`); this
  is the one caller that lifts the refusal, and only for its own call.

Both paths perform the same three steps; the gate above conditions only
the overseer's path — each step produces its own receipt line:

1. **Placed:** a symlink `<claude_dir>/hooks/<script_name>` → the host's
   guard script, created atomically (write to a temp name, then rename
   into place); refuses if a *different* target already occupies that
   name.
2. **Registered** (on the overseer's path, skipped with a receipt saying
   so when `overseer.hook_activation` is `false`; the human's `hook
   activate` always performs this step): renders the exact bytes the
   guard script and the `settings.json` snippet would be — the same diff
   a human reviewing this route would see today, no shortcut on what gets
   shown — then merges the snippet into the correct event array in
   `settings.json`, under a backup of the prior file (same discipline
   this file's other host-file writers already follow — a hand-edit is
   reversible).
3. **Activation-checked** (same skip condition as step 2 — on the
   overseer's path only): replays the
   hook's own preview examples against the *symlink path* (so a dangling
   or wrong-target link fails here, not silently later), then runs the
   same detection the doctor's hook check performs and requires it to
   report the registration as live. The receipt states explicitly that
   Claude Code's own reload of `settings.json` was **not observed** —
   `FW-154`'s rule that delivery is never inferred from a file existing
   applies here exactly as it does to the delivery-instrumentation work
   that row names.

**The receipt.** One mechanism for either caller: the verb's own ledger
write records a `hook-activated`/`hook-deactivated` history entry on the
record (`02-schema.md` §2 as amended), the same entries this build adds
for either actor. The overseer's own activation additionally lands, as an
ordinary executor receipt, in the Application section of the overseer's
decision case for that parked item — the same path that appends any
other verb's receipt there (`02-schema.md` §3a.2 §5); the human path opens
no case, so no Application section exists to write to. `batch`'s flush
epilogue remains the Application section's one writer.

**What stays true regardless of actor.** The two manual steps this file's
existing hook-compile path already requires — the exact-bytes preview and a
diff-approved step — are the human's `hook activate` unconditionally, and
the overseer's step 2 (registered) whenever the gate allows it: neither
caller's activation removes them. `install.sh` is untouched — it never
enables a hook, same as it never
enables a systemd unit. `hook deactivate <record-id>` reverses the symlink
and the `settings.json` merge from the recorded backup and is
unattended-callable under the same §7.2a.5 contract as every other
ledger-write verb.

**What this section does not do.** It does not widen the hook *destination
grammar* itself (advisory PreToolUse, PostToolUse, bounded-command hooks) —
that is `FW-161`'s own scope, sequenced independently of this section; O-2
only decides *who* may approve and install a hook already compiled under
whatever destination grammar exists at build time.

## 8. Invariants

- **H-1** · One ledger home per machine, explicit (`~/.self-learn` or
  SELF_LEARN_HOME), never inferred from cwd.
- **H-2** · The ledger is truth; canon is compiled output; recompile is
  always safe and repairs any two-phase interruption. *Amended
  2026-09-11 (Sprint 3 spec lane B, `S-63`, §7.2a.9):* a route's intent
  RECORDS the host-phase steps it was about to apply, so that recovery
  after a crash between the two phases NAMES the interruption precisely
  — which host, which target, which record, and whether the region
  matches the prior state, matches the expected state, is missing,
  differs, or could not be read — and names `self-learn recompile` as the
  repair. The record adds no second repair and no second writer:
  `recompile` remains the only thing that repairs a two-phase
  interruption, no unattended caller ever applies a host step from an
  intent, and an attended caller completes a host step only by running
  `recompile`. M-W gate r1 MAJOR-2 stands verbatim (§7.2a.3).
- **H-3** · Compile targets come from hosts.yaml only — capture is
  open, canon is registered. No autonomous process ever writes to an
  unregistered repo. A registered host need not be a git repository:
  `U-hostmode` makes version control a per-host mode (`git` default,
  `plain` opt-in). H-3 itself is unchanged — compile targets still come
  from hosts.yaml only, and a plain host is gated by a
  `.self-learn-host` marker the registering verb writes, never by being
  writable. *2026-09-11 (Q-A1, forward work — FW-152):* registration may
  follow from an authorized placement, including an authorized
  automated reviewer's, subject to the `hosts.yaml` never-register
  blocklist. H-3 itself is unchanged — nothing is ever written to a
  repo that is not registered at the moment of the write, and no target
  is ever guessed.
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
