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
- **User bucket** replaces the root bucket's user half; compile target
  unchanged (chezmoi flow).
- `hosts.yaml` is data, tracked in the ledger repo — one file to read
  to know where canon may land. Registration is a CLI verb
  (`self-learn host add <path>`), never a hand edit the compilers
  trust blindly (the verb validates the path and stamps the entry).

## 4. Routing across repos — the revision of record

02 §2's "route = one commit" was already false for user scope: the
chezmoi path has committed ledger-side and dotfiles-side separately
since M1 (E-17 extended). The honest invariant was never single-commit;
it is: **the ledger is the source of truth and canon is a compiled,
regenerable artifact** (correction = supersede + recompile, never
revert). Doc 13 promotes that to the general rule:

1. **Ledger-first two-phase.** A resolution verb commits the ledger
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

## 6. Cache namespacing

`~/.cache/claude-skills/self-learn/` → `~/.cache/self-learn/` in the
same migration (the old name embeds the host it no longer belongs to).
State keyed under a hash of the ledger-home path (H-4) so a future
second home (06's shared team ledger beside the personal one) is a
config away, not a redesign. One-time migration moves cursors, journal,
markers, spool; the sentinel path change is coordinated with
claude-skills-sync in the same commit pair.

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

## 8. Invariants

- **H-1** · One ledger home per machine, explicit (`~/.self-learn` or
  SELF_LEARN_HOME), never inferred from cwd.
- **H-2** · The ledger is truth; canon is compiled output; recompile is
  always safe and repairs any two-phase interruption.
- **H-3** · Compile targets come from hosts.yaml only — capture is
  open, canon is registered. No autonomous process ever writes to an
  unregistered repo.
- **H-4** · Cache state is namespaced by ledger home.
- **H-5** · No watcher on the ledger repo — producers commit their own
  writes with pinned subjects. Corollary: a write its producer could not
  commit is committed by nobody, so `self-learn reconcile` is the
  backstop (§5), and no mutation may precede its `commit_lock`.
- **H-6** · Migration preserves resolution-commit history (the
  analyst's negative exemplars are part of the system's memory).
