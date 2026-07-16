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
  hosts.yaml seeded (claude-skills as skills root + project host;
  dotfiles/user host), layout dirs.
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
  writes with pinned subjects.
- **H-6** · Migration preserves resolution-commit history (the
  analyst's negative exemplars are part of the system's memory).
