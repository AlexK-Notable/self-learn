# U-verbs — completing the ledger's verb surface

Status: **r6 — 2026-08-28.** Four blind spec gates, each verifying the
previous fold and finding only defects that fold itself introduced — a
strictly converging series: r1 **0 B / 9 M / 10 N / 6 D**
(`AosifSV6kYD2d4jyur1OF`), r2 **0/4/6/0** (`xC0jWpAeV2NkyZymJ9phy`),
r3 **0/3/3/0** (`pwQtXZt7aHOa0FEl6DRXE`), r4 **0/1/3/0**
(`we6w98VwqYC8aIYfzsWus`). **All 45 findings across the four rounds are
folded** — §12.1-§12.4 are the finding-by-finding tables. Five needed a
decision and were ruled by the orchestrator: `M-5` (idempotence, §3.3b),
`M-6` (the batch exit code, §3.3a), `M-4r2` (the flush epilogue, §3.3c),
`M-1r3` (fold all six flush sites; FW-139 withdrawn) and `M-2r3` (write
`scope:` unconditionally). **r4's four findings folded without a further
round** (repricing rule — all bounded text substitutions), and its named
*class* — a correction landing in a new place while the original sentence
survives, three rounds running — is closed by **§13.1's whole-spec
stale-statement sweep**, run and pasted.
Unit `U-verbs` (T2, full two-gate).
Written in the throwaway worktree `.claude/worktrees/u-verbs-spec`
(branch `u-verbs-spec`, base `ba90ef9` = `origin/master`). **Uncommitted.**

Reserved numbering: **S-54**; **FW-133 … FW-138**.
*(r5: FW-139 is WITHDRAWN — gate M-1r3 measured its stated obstacle false, so
§3.3c folds all six flush call sites and there is no residual to register.
The ceiling returns to **FW-138**; no numbered hole is left behind.)*
(Measured: `03-decisions.md`'s highest row on master is `S-53` with `S-51`
reserved by U-hostmode; `14-forward-work-map.md`'s highest is `FW-132`
with `FW-122`-`FW-124` reserved by U-hostmode — see §2.0.)

---

## 0. Reading order and precedence

**THE CODE BASE FOR EVERY NUMBER IN THIS SPEC IS `b206800`** — the
U-hostmode Phase 1 branch (worktree `.claude/worktrees/u-hostmode`,
`83e9f37` + the `ba90ef9` merge), **not master**. U-hostmode lands
before this unit and renames `TargetSpec.host_repo` → `host_path`, adds
`mode: git | plain`, adds the ledger-side compile record
(`compiled/*.yaml`), and makes user scope a first-class plain host. Every
code line number, symbol name and count below is read off `b206800`;
every *ledger* number is read off the live ledger at
`4444be7` (2026-08-27, porcelain clean). A gate re-measuring on master
**after U-hostmode lands** should get the same answers; a gate measuring
on master *before* it lands will see `host_repo`, no `mode`, and no
`compiled/`, and should treat those three as the only expected
divergence.

**Every number below is a command output**, and the command is quoted
beside it. Where something could not be measured, §13 says so.

**Path convention.** Every pasted command output has had the operator's
literal home prefix replaced by `~`, and nothing else altered (the drafts
convention, `scrub-personal-literals-spec.md` §"Group C"). Bucket
**slugs**, which encode the resolved path with slashes as dashes, get the
same treatment: `-home-<user>-…`. The ledger home is written
`~/.self-learn` or `$SELF_LEARN_HOME` throughout.

**Every number is reproducible from a command QUOTED IN THIS FILE.**
`misc/u-verbs-measurements/{uverbs_census,uverbs_usage}.py` exist as
convenience wrappers, but `misc/` is git-excluded and never reaches the
public repo, so **no number here depends on them**: §2.1's usage table is
one `git log | awk`, §2.2's guard census is one `awk` over `verbs.py`,
§2.3's and §2.5's ledger figures are `ls`/`grep`/`sed` one-liners, and
every one is pasted with its own output. A gate re-measures by copying
the command out of the fence.

**Absence is never asserted by a bare zero.** Where a number is a *count
of something missing* (§2.2's past-date check, §2.3's slug shape, §2.9's
armor collisions), a **positive control** is quoted beside it showing the
same command finding the thing when it IS there. §2.1 carries a live
instance of why: `git log --pretty=format:'%s'` emits no trailing
newline, so `grep -vc` silently under-counts by one.

**No verb was run against the live ledger** — every ledger figure is a
frontmatter read or a `git log` read.

Precedence, highest first:

1. **`03-decisions.md`** rows **S-8/S-12** (substance freezes at
   routing), **S-23** (user scope has no references dir), **S-29** (the
   tiered-autonomy floor that forbids an unattended hook route),
   **S-10** (behaviour never changes without a decision) and **S-17 D3**
   (pushes are manual). Where this spec and a row disagree, **the row
   wins**.
2. **`02-schema.md` §2** — the record-state pin. Four clauses are
   load-bearing here and are quoted where they bind: *"refusals … on
   status, never mere existence"*; *"Substance freezes at routing:
   `created_at`, `type`, `source`, and the body never change
   afterward"*; *"Lifecycle metadata may mutate: `status`, `routing`,
   `sightings`, `scope`/`kind` (triage may re-classify — the filing is
   never frozen)"*; and *"`resolution_note` … written **exactly
   once**"*. §4.10 amends §2 with exactly one new key and says so.
3. **`13-hosting-and-separation.md`** §4 (ledger-first two-phase; drift
   is repaired by recompile), §8 invariants **H-3** (compile targets come
   from `hosts.yaml` only), **H-5** (producers commit their own writes)
   and **H-4** (the per-home cache namespace).
4. **`u-hostmode-git-optional-hosts-spec.md`** §4.1 (`host_path`/`mode`),
   §4.3 (`gitops.host_lock`), §4.5/§4.5b (the compile record and the
   widened `_ledger_write` span), §4.8 (user scope as a plain host) and
   its **Phase 2** (`chezmoi.py` deleted wholesale, the UI adopt surface
   deleted). **This unit re-specifies none of that** — §10 records the
   interface it assumes instead.
5. **`u-rescope-user-to-skill-spec.md`** §3 (the four rationales for a
   separate `rescope` verb), §4 (the excluded directions), §5
   (sweep-and-disclose). This unit **widens** that verb's reach and must
   answer §3 rationale 1 by measurement, not by assertion — §3.2.
6. **`11-telemetry-and-lifecycle.md`** §2.1/§2.2/§2.5 (the post-routing
   lifecycle verbs and their pinned commit subjects).
7. **`misc/verb-coverage-2026-08-26.md`** (znote `IbSQPLO0i3vxFCgd96NYu`)
   — the assessment whose ranked gaps G2…G10 are this unit's scope. Its
   G1 (terminal-state guards) is **CLOSED** by `u-verbguards` (`b62af3e`,
   FW-51) and is this unit's *vocabulary*, not its work.
8. The code, in the order §2 measures it.

**Precedence inside this spec.** §5's criteria ARE the spec. Prose is
rationale. Where a criterion and a paragraph disagree, the criterion wins.

---

## 1. Objective, and the non-objectives

**Objective.** Make every workflow the last two review batches had to
hand-build a first-class, guarded verb — so that the ledger's verb
surface covers its own state machine, and no correct operation requires
a bash script, a hand `git mv`, or an accident (`defer --until <past>`).

Eight gap classes, all from `misc/verb-coverage-2026-08-26.md` §4, plus
one producer defect the batch runner needs:

| Gap | What is missing today | Phase |
|---|---|---|
| **G2** | user↔project / project↔skill filing moves (FW-115), skill↔skill (FW-114) | **1 [A]** |
| **G3** | a batch verb that applies a decision sheet in one locked run | **1 [A]** |
| **G5** | reopen a rejected record, un-defer early, amend a note; `defer --until <past>` accepted silently | **1 [A]** |
| **G6** | `route --dry-run`, `show <id>` | **1 [A]** |
| **G9** | FW-85: `worker kick` / `mine run` outcomes are invisible to a caller | **1 [A]** |
| **G4** | reroute a routed record; `reference` retirement is a silent no-op | **2 [B]** |
| **G7** | `host remove` orphans routed canon; no bucket prune | **2 [B]** |
| **G8** | `followup add` after routing; `reclassify` kind/type | **2 [B]** |
| **G10** | UI verb parity (dismiss-suspect, rescope, supersede, confirm-held) | **2 [B]** |

**Why that phase split, measured.** Phase 1 is every gap with a *live
waiter*: two `defer` commits name the missing move verb by name (§2.3),
two hand-written batch scripts exist on disk (§2.4), and `route
--dry-run` is the engine `batch --dry-run` is a loop over (§4.4). Phase 2
is every gap whose live-instance count is **zero** — 0 reference-routed
records have ever been graduated or superseded (§2.5), `host remove` has
0 uses in 382 ledger commits (§2.6), 2 follow-ups have ever been cleared
(§2.1). Phase 1 is also the half that writes **nothing to a host**: every
Phase-1 verb is ledger-only, and `route --dry-run` writes nothing at all.
Phase 2 is the host-touching half. §5.0 proves Phase 1 lands alone.

### Non-objectives

1. **A new *third* filing-move verb.** §3.2 refuses `refile` by name and
   by measurement: `rehome` and `rescope` widen instead, and the
   collision hazard u-rescope §3 rationale 1 raised is measured away
   (§2.3), not waved away.
2. **Retract / un-route (routed → pending).** A retraction must both
   un-write canon *and* restore a draft, and 02 §2's freeze-at-routing
   pin says the substance never returns to editable. `reroute` covers the
   half that has a live motivation (a wrong destination). **FW-133.**
3. **Anything U-hostmode owns.** `chezmoi.py`'s deletion, the UI adopt
   surface's deletion, `mode`, the compile record, `host_path` — all
   Phase 2 of *that* unit. This unit inherits them and must not
   re-specify them.
4. **Widening what an agent may PROPOSE.** `PROPOSABLE_VERBS`
   (`ui/src/self_learn_ui/proposals.py:67`) is unchanged by this unit;
   every new verb starts outside it (u-rescope §3 rationale 2, adopted
   verbatim). The analyst/worker may propose a move or a reroute in
   `rationale` prose; only a human-run verb writes.
5. **New exit-code integers.** §3.7: producers get the `--json` outcome
   envelope the resolution verbs already have (07 §4 contract 2), not new
   integers whose blast radius is the systemd units and the miner's
   callers (FW-85's own stated radius).
6. **A journal-backed batch resume.** §3.3: resumability is derived from
   ledger state, which is the only thing that survives a cleared cache.
7. **Bulk retirement on `host remove`.** §3.6: neither `graduate` nor
   `supersede` is an honest bulk answer, so neither is offered.

---

## 2. Census, measured at `b206800` (code) and `4444be7` (ledger)

### 2.0 The numbering ceilings

```
$ python3 - <<'PY'   # over docs/specs/self-learn/ on master (ba90ef9)
import re
t=open('docs/specs/self-learn/14-forward-work-map.md').read()
ns=sorted(set(int(m) for m in re.findall(r'^\| FW-(\d+) ', t, re.M)))
print('FW count',len(ns),'max',max(ns),'missing:',[i for i in range(1,max(ns)+1) if i not in ns])
t=open('docs/specs/self-learn/03-decisions.md').read()
ns=sorted(set(int(m) for m in re.findall(r'^\| S-(\d+) ', t, re.M)))
print('S  count',len(ns),'max',max(ns),'missing:',[i for i in range(1,max(ns)+1) if i not in ns])
PY
FW count 129 max 132 missing: [122, 123, 124]
S  count 52 max 53 missing: [51]
```

`FW-122`-`124` and `S-51` are U-hostmode's, unlanded. **This unit takes
`S-54` and `FW-133`-`FW-137`** — above every allocated number, colliding
with no sibling.

### 2.1 The verb surface and its usage, measured

**Instrument, quoted in full** — one `git log` + `awk`, no script:

```
$ git -C ~/.self-learn log --pretty=format:'%ad%x09%s' --date=short \
| awk -F'\t' '$2~/^self-learn: /{
    s=substr($2,13); split(s,w," "); v=w[1]
    if(v=="telemetry"||v=="host"||v=="follow-up") v=v" "w[2]
    if(v=="recurrence") v="confirm-recurrence"
    if(v=="suspect")    v="dismiss-suspect"
    if(v=="capture")    v="teach (capture)"
    a[v]++; if($1>="2026-07-29") d[v]++ }
  END{ for(v in a) printf "%-20s %4d %4d\n", v, a[v], d[v] }' | sort -k2 -rn
telemetry flush       126   87
route                  92   60
teach (capture)        30   15
graduate               24    5
worker                 21   10
reject                 21   20
mine                   18   10
defer                  13   10
host add                8    5
rehome                  3    3
confirm-recurrence      3    3
supersede               2    2
reconcile               2    1
follow-up done          2    0
rescope                 1    1
link                    1    1
dismiss-suspect         1    1
migration               1    0
migrate                 1    0
backfill                1    0
```

*(The subject-word mapping above is not cosmetic: the pinned subjects are
`self-learn: recurrence confirmed on lrn-…`, `self-learn: suspect
dismissed on lrn-…`, `self-learn: follow-up done on lrn-…` and
`self-learn: capture lrn-… (<scope>)` — verified with `git -C
~/.self-learn log --pretty=format:'%s%n' | grep -E 'recurrence|suspect|follow-up|capture' | sort -u | head`.)*

```
$ git -C ~/.self-learn rev-list --count HEAD
382
$ git -C ~/.self-learn log --pretty=format:'%s%n' | grep -v '^$' | grep -c    '^self-learn: '
371
$ git -C ~/.self-learn log --pretty=format:'%s%n' | grep -v '^$' | grep -vc   '^self-learn: '
11
```

371 + 11 = 382. **Use the `%s%n` form, not bare `%s`**: `git log
--pretty=format:'%s'` emits no trailing newline, and `grep -vc` then
under-counts by one (10, not 11) — the fail-quiet shape lrn-ea833a5b
names, met while writing this very section. The eleven are the
`bootstrap:` commit and ten pre-split `autosync` commits — the ten
autosyncs are all ≤ 2026-07-15, and the bootstrap commit is
**2026-07-16**, the split itself *(CORRECTED-r3, gate N-5: r2 put all
eleven at ≤ 07-15, which would have placed the bootstrap before the split
it performed)*:

```
$ git -C ~/.self-learn log --pretty=format:'%ad %s%n' --date=short | grep -i '^....-..-.. bootstrap'
2026-07-16 bootstrap: independent ledger home — hosts.yaml, project meta, derived slug bucket (doc 13 §3)
```

**Zero all-time uses:** `host remove`, `host rebind`, `confirm-held`,
`import`, `prune-memory`, `canary plant`, `chezmoi-adopt`, ledger-side
`recompile`, `init`. Since the 2026-07-16 split there are **zero**
anonymous ledger commits — the "no unowned mutations" pin holds, which is
exactly why a missing verb becomes a deferred record rather than a hand
edit.

**The exit-code contract this unit must extend and must not fork**
(`cli.py`'s module docstring, `:13-22`; rendered for humans in
`commands/review.md:230-264`):

| Code | Meaning | Ledger changed? |
|---|---|---|
| 0 | success | yes (or nothing to do) |
| 1 | the verb REFUSED (`VerbError`, `SecretRefusal`, `CompileError`) | **no** |
| 3 | committed, push failed | **yes** |
| 4 | committed, push hit a rebase conflict | **yes** |
| 5 | ledger home missing / not a repo | **no** |
| 6 | git failed BEFORE the first mutation (commonly a held lock) | **no** |
| 7 | written, commit failed — half-written | **yes** |
| 64 | usage (bad flag; unknown/malformed id) | **no** |

*(That is the contract as it stands at `b206800`. §3.3a adds **one**
integer to it — `EXIT_BATCH_PARTIAL = 8`, for the one surface that
performs many mutations in one invocation — and changes no existing
meaning. `2` is absent above on purpose: it is `proposal validate`'s
scan hit, which `cli.py:71` pins as never aliasable.)*

### 2.2 The guard vocabulary, and its two holdouts — MEASURED

`u-verbguards` (`b62af3e`, FW-51) landed **one** precondition helper,
`ledger_ops.require_status(home, id, allowed, *, verb, reason=None)`
(`ledger_ops.py:474`), which resolves across `pending/` AND `resolved/`
and refuses naming the record's actual status, **before any lock or
mutation**. Its status sets:

```
$ sed -n '95,118p' cli/src/self_learn/ledger_ops.py | grep -E '^[A-Z_]+ ='
RESOLUTION_STATUSES = frozenset({"routed", "rejected", "superseded"})
LIVE_STATUSES = frozenset({"pending", "deferred"})
RESOLVABLE_STATUSES = LIVE_STATUSES | frozenset({"routed"})
ROUTED_ONLY = frozenset({"routed"})
```

plus `supersede_cycle_check` (`ledger_ops.py:2479`).

**Who consults it, and who does not** — one `awk`, quoted in full:

```
$ awk '/^def /{f=$2; sub(/\(.*/,"",f)}
       /require_status\(/        {printf "verbs.py:%-5d %-20s require_status\n", NR, f}
       /is not pending \(status/ {printf "verbs.py:%-5d %-20s HAND-ROLLED\n",  NR, f}' \
      cli/src/self_learn/verbs.py
verbs.py:3124  route                require_status
verbs.py:3133  route                require_status
verbs.py:3635  route_direct         require_status
verbs.py:4149  reject               require_status
verbs.py:4194  defer                require_status
verbs.py:4281  rehome               HAND-ROLLED
verbs.py:4467  rescope              HAND-ROLLED
verbs.py:4574  graduate             require_status
verbs.py:4681  supersede            require_status
verbs.py:4684  supersede            require_status
verbs.py:4811  followup_done        require_status
verbs.py:4890  confirm_recurrence   require_status
verbs.py:4952  confirm_held         require_status
verbs.py:5043  dismiss_suspect      require_status
```

**Finding V-1 (measured).** Ten of the twelve record-verbs route their
status precondition through `require_status`. **`rehome` and `rescope`
are the two that still hand-roll it** — `if path.parent.name != "pending"
or record.status not in ("pending", "deferred")` — and their message says
*"is not pending (status 'rejected')"* rather than naming the status set
the verb needs. That is FW-51's exact shape surviving in the two verbs
the FW-51 unit did not touch, and it is the root cause this unit's move
half closes: **the new legs must not add a third hand-rolled check.**

Exactly **one** shipped test pins the hand-rolled wording:

```
$ grep -rn "is not pending" cli/tests/ ui/ commands/ skills/
cli/tests/test_rehome.py:200:            f"record {rec.id} is not pending (status 'rejected') — a "
```

Also measured — the past-date hole is an *absence*, so it needs a
positive control (the grep must be able to find a date check that IS
there):

```
$ sed -n '2582,2604p' cli/src/self_learn/ledger_ops.py | grep -c 'until'
8
$ sed -n '2582,2604p' cli/src/self_learn/ledger_ops.py | grep -cE 'until *[<>]|[<>] *until'
0
$ grep -cE '[a-z_]+ *[<>]=? ' cli/src/self_learn/ledger_ops.py   # control: comparisons DO exist here
28
```

`ledger_ops.defer_record` (`:2582`, routed through `require_status` at
`:2590`) normalises `until` to a string and writes it — **no comparison
of any kind**. The `defer --until <past>` workaround the assessment names
(G5) is therefore real, and it is an accident of a missing validation,
not a designed door.

### 2.3 The move matrix, and the two records waiting on it

```
$ ls ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md 2>/dev/null | wc -l
152
$ ls -d ~/.self-learn/{user,skills/*,projects/*} | wc -l
18
$ grep -h '^status: ' ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md \
    2>/dev/null | sort | uniq -c | sort -rn
     83 status: routed
     35 status: superseded
     21 status: rejected
     10 status: deferred
      3 status: pending
$ grep -h '^scope: ' ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md \
    2>/dev/null | sort | uniq -c | sort -rn
     75 scope: user
     33 scope: skill:home-assistant
     27 scope: project
      7 scope: skill:testing-methodology
      5 scope: skill:hypr-doctor
      2 scope: skill:chezmoi
      2 scope: skill:bitwarden-cli
      1 scope: skill:cron-claude
$ grep -c '^- path: ' ~/.self-learn/hosts.yaml
9
```

**All ten deferred records are user-scope:**

```
$ grep -l '^status: deferred' ~/.self-learn/{user,skills/*,projects/*}/pending/lrn-*.md \
    2>/dev/null | sed "s|$HOME/.self-learn/||; s|/pending/.*||" | sort | uniq -c
     10 user
```

and two of them are deferred *on this verb*, in their own commit bodies:

```
$ git -C ~/.self-learn log --pretty=format:'%h %s%n    %b%n' | grep -B1 'move verb'
e6b349a self-learn: defer lrn-b21d1969 until 2026-09-25
    no user-scope reference shelf (S-23) and no user->project move verb; the design implication (ancestor CLAUDE.md inheritance) is filed as a doctrine follow-up unit
--
59807c2 self-learn: defer lrn-1129a784 until 2026-09-24
    belongs at project (~/.config) scope; deferred until a user->project move verb exists
```

**The two file-op halves, and why the matrix has holes**
(`ledger_ops.py:2387` and `:2427`):

| | rewrites `scope:` | stamps target `meta.yaml` | sweeps proposal | discloses the sweep |
|---|---|---|---|---|
| `rehome_record` (project→project) | **no** | **yes** (`ensure_project_meta`) | yes | **no** |
| `rescope_record` (user↔skill) | **yes** (`set_scope`) | **no** | yes | **yes** (R-DISCLOSE-1/2) |

**Finding V-2.** The file-op half was written twice, each half-complete.
The missing cells need **both** behaviours, conditionally — which is why
neither existing function can be reused as-is, and why FW-115 says the
move "needs a `project_path` that a scope literal cannot carry".

**Finding V-3 (measured) — u-rescope §3 rationale 1's collision hazard
does not exist.** The rationale is *"a slug that happens to equal a skill
name becomes a silent mis-file"*. Measured against `hosts.slug_for`
(`hosts.py`, whose docstring reads *"Slug = `<readable>-<sha256(resolved)[:8]>`"*):
every slug **starts with `-`** (the root slash) and **ends with `-` + 8
hex**:

```
$ ls ~/.self-learn/projects/ | wc -l
12
$ ls ~/.self-learn/projects/ | grep -cE '^-.+-[0-9a-f]{8}$'      # positive control
12
$ ls ~/.self-learn/projects/ | grep -cvE '^-.+-[0-9a-f]{8}$'     # the assertion
0
$ ls ~/.self-learn/projects/ | grep -cE '^(user|skill:)'
0
```

Twelve of twelve live slugs match; **no slug can ever be the literal
`user` or start with `skill:`**. The residual collision is a *relative
path* literally named `user` or `skill:x`, which §4.1 closes by matching
the reserved literals first and pinning the escapes (`./user`,
`project:user`) with a test. Rationale 1 is therefore answerable by
measurement, and §3.2 answers it.

### 2.4 The two batches, measured

```
$ grep -c '^run ' misc/review-batch-2026-08-24.sh ; \
  grep '^run ' misc/review-batch-2026-08-24.sh | grep -vcE '^run (sentinel|push)'
37
34
$ grep -c '^run ' misc/review-batch-2026-08-25.sh ; \
  grep '^run ' misc/review-batch-2026-08-25.sh | grep -vcE '^run (sentinel|push)'
11
8
$ wc -l misc/review-decisions-2026-08-2{4,5}.md
  313 misc/review-decisions-2026-08-24.md
  143 misc/review-decisions-2026-08-25.md
$ grep -c '^rc=' misc/review-batch-2026-08-2{4,5}.log ; \
  grep -h '^rc=' misc/review-batch-2026-08-2{4,5}.log | grep -vc 'rc=0'
review-batch-2026-08-24.log:37
review-batch-2026-08-25.log:11
0
```

**42 verb calls across two hand-written scripts** (34 + 8), transcribed
by hand from a 456-line checkbox sheet, every one `rc=0`. Both scripts
re-derive the identical scaffolding, quoted from
`review-batch-2026-08-24.sh`:

- a `run()` wrapper printing `rc=$?` **unpiped** (the lrn-ea833a5b
  discipline, hand-applied);
- `sentinel hold` … `sentinel release` bracketing;
- every verb `--no-push`, one `push` at the end;
- and — only in the 08-24 script — a **retry-without-`--no-push`
  branch**, because the author could not tell from the sheet which verbs
  carry the flag.

Nothing preflights the sheet: the 08-25 script's `host add
~/repos/3d-printing --init` had to be sequenced by hand ahead of the
routes that needed it, and an ALWAYS-gate refusal or an over-cap signal
would only have surfaced at apply time. Nothing resumes a sheet after an
exit 5/6/7.

### 2.5 The `reference` retirement no-op — exposure and live instances

```
$ for f in ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md; do
    d=$(sed -n 's/^  destination: //p' "$f" | head -1)
    [ -n "$d" ] && printf '%-12s %s\n' "$d" "$(sed -n 's/^status: //p' "$f" | head -1)"
  done 2>/dev/null | sort | uniq -c
     37 claude-md    routed
      7 claude-md    superseded
      4 hook         routed
      4 new-skill    routed
     27 reference    routed
     11 skill-md     routed
      2 skill-md     superseded
```

92 records carry a routing block; **the `reference` row has one status
only — `routed`.**

```
$ for f in $(sed -n 's/^- path: //p' ~/.self-learn/hosts.yaml | sed 's|$|/references/LEARNINGS.md|') \
           $(sed -n 's/^skills_root: //p' ~/.self-learn/hosts.yaml)/plugins/*/skills/*/references/LEARNINGS.md; do
    [ -f "$f" ] && printf '%6s B  %2s entries  %s\n' \
        "$(wc -c <"$f")" "$(grep -c '^## ' "$f")" "${f/#$HOME/\~}"
  done
  1046 B   1 entries  ~/repos/keyboards/references/LEARNINGS.md
  1816 B   3 entries  ~/.config/references/LEARNINGS.md
  1356 B   4 entries  ~/repos/3d-printing/k1c-manta-m5p/references/LEARNINGS.md
   570 B   1 entries  ~/repos/ignomi/references/LEARNINGS.md
  1232 B   2 entries  ~/repos/3d-printing/references/LEARNINGS.md
   988 B   1 entries  ~/repos/claude-skills/plugins/cron-claude/skills/cron-claude/references/LEARNINGS.md
 15907 B  15 entries  ~/repos/claude-skills/plugins/home-assistant/skills/home-assistant/references/LEARNINGS.md
```

27 reference entries across **7 files** (1+3+4+1+2+1+15), matching the 27
reference-routed records exactly. **Finding V-4:** not one
reference-routed record has ever been graduated or superseded, so the
silent no-op (`verbs._retirement_preflight`, `verbs.py:2604`, whose bare
`_Retirement()` is returned for `reference` — *"references are
append-only"*) has **0 live instances and 27 records of exposure**. It is
latent, not bleeding. That is precisely why it is **Phase 2**, and
precisely why it must still be fixed: the exposure is 27 of 92 routings.

The removal is mechanically feasible: `compilers._reference_block`
(`compilers.py:1101`) writes `## <YYYY-MM-DD> — <lrn-id>` as the block
head, and `compile_reference` already scans the file for `record.id` for
idempotency. A block runs from its `## ` heading to the next `^## ` or
EOF.

### 2.6 Host lifecycle, measured

`hosts.host_remove` (`hosts.py:819`) drops the entry from `hosts.yaml`
and nothing else — its own docstring says *"The bucket and its records
are NEVER touched — deregistering a host closes the compile gate (H-3),
it does not delete truth."* It takes no `--force`, offers no `--retire`,
and never asks whether a record still targets the host. Uses: **0**
(§2.1). U-hostmode GATE5 adds one clause to it (a plain host's
`.self-learn-host` marker is left in place) and changes nothing else.

Two record-less bucket dirs exist live:

```
$ for d in ~/.self-learn/projects/*/; do \
    n=$(ls "$d"pending/lrn-*.md "$d"resolved/lrn-*.md 2>/dev/null | wc -l); \
    [ "$n" = 0 ] && echo "EMPTY $(basename $d)"; done
EMPTY -home-<user>-.claude-reports-77244b56
EMPTY -home-<user>-repos-nsys-marketplace-local-.claude-worktrees-bench-accuracy-eb48c377
```

### 2.7 Producer exit codes — FW-85, measured

`worker.kick` returns one of **five** outcomes — `spawned |
absorbed-window | absorbed-race | disabled | depth-limited` — and
`cli._cmd_worker` returns `EXIT_OK` for all five. `miner.run` returns one
of **eight** statuses — `ok | idle | busy | disabled | held-gate |
initialized | failed | landed-uncommitted` — and `cli._cmd_mine` maps
`landed-uncommitted` → 7, `failed` → 1, and **the other six → 0**.

Meanings, read off the code: `busy` = the miner's own `flock` on
`miner.lock` is held (`miner.py:1833`); `held-gate` = the flood gate,
`total_pending >= pending_gate()` (`miner.py:1963`); `disabled` =
`SELF_LEARN_MINER=0`; `initialized` = first-run cursor seeding.

**Finding V-5.** None of the six zero-mapped statuses is a *failure* — a
no-op is not an error, and giving `absorbed-window` a non-zero code would
make every `teach`/`import` kick look failed. What a caller cannot do is
**tell them apart**, which is exactly what FW-85's own trigger row asks
for: *"new codes, or a `--json` envelope carrying the outcome rather than
just ok/fail"*, under the ratified constraint *"never parse
human-formatted stdout"* (`ui/runner.py`'s docstring, 07 §4).

### 2.8 The UI verb surface, measured

```
$ grep -n "_VERB_LABELS\|_KNOWN_VERBS\|PROPOSABLE_VERBS" ui/src/self_learn_ui/{routes,proposals}.py
routes.py:61     _VERB_LABELS = {route, reject, defer, graduate, rehome,
                   confirm-recurrence, link-contradicts, followup-done, chezmoi-adopt}
routes.py:81     _KNOWN_VERBS = frozenset(_VERB_LABELS) - {"rehome"}
proposals.py:67  PROPOSABLE_VERBS = {route, reject, defer, graduate, rehome}
```

Absent from `_KNOWN_VERBS`: **dismiss-suspect, rescope, supersede,
confirm-held** (`chezmoi-adopt` leaves with U-hostmode Phase 2).

The keymap is a hard constraint, and it is nearly full:

```
$ (cd ui && uv run --project . python -c "
import sys; sys.path.insert(0,'src')
from self_learn_ui.keymap import KEYMAP
letters=set('abcdefghijklmnopqrstuvwxyz')
used={k for e in KEYMAP for k in e.keys}
print('used letters:', ''.join(sorted(l for l in used if l in letters)))
print('FREE letters:', ''.join(sorted(letters-used)))
print('entries:', len(KEYMAP))")
used letters: abcdefgijnopqrstuvwxy
FREE letters: hklmz
entries: 22
```

**Four** genuinely free letters (`h` is printed on the header back-link
and bound to nothing — `fixtures/ui-walks.md` W2-F1 — and claiming it would encode
that defect into a uniqueness test). §4.9 therefore separates **POST-
surface parity** (unbounded) from **keyboard parity** (four letters), and
spends two of the four.

The `holding` card (`templates/partials/action_bar.html:121-139`) already
renders three buttons — `tolerate (t)`, `confirm_recurrence (c)`,
`graduate (g)` — so a fourth is a one-line addition to an existing card.
The `resolved` card (`:155-186`) renders one, `graduate (g)`.

### 2.9 Armor and lock-invariant collision — MEASURED ZERO

```
$ for f in conftest.py backends.py test_invocation.py test_invocation_sdk.py \
           test_u_fake.py test_worker.py test_repair.py ; do
    printf '%s: ' "$f"
    grep -cE '\brehome\b|\brescope\b|\breroute\b|\breopen\b|\bundefer\b|\breclassify\b' cli/tests/$f
  done
conftest.py: 1        test_u_fake.py: 0
backends.py: 0        test_worker.py: 0
test_invocation.py: 0 test_repair.py: 0
test_invocation_sdk.py: 0
$ grep -nE '\brehome\b|\brescope\b|\breopen\b' cli/tests/conftest.py
156:# persistence.py`, or a future CLI file that grows one) cannot reopen
```

The seven `_ARMOR_SHAS` files (`cli/tests/test_worker_contract.py`) name
none of this unit's verbs; the single `conftest.py` hit is the English
word "reopen" in a comment. **No armor sha moves in this unit**, and §7
puts every new test in two NEW files so none can.

`test_lock_invariant.py`'s `_LOCKS = ("commit_lock", "_ledger_write",
"host_lock")` is unchanged: every new mutating verb takes
`_ledger_write(home)`, which the walker already recognises, and no new
lock helper is introduced. `NOT_REPO_TRUTH` does **not** grow.

### 2.10 Test baselines

*(CORRECTED at Phase 2 code gate r1 landing: the two totals below were
the PRE-BUILD baseline at `b206800` -- badly stale once Phase 1 AND
Phase 2 landed in the same tree. Re-measured LIVE, after the gate r1
Blocker/Major/Minor fix round (PH1's deletion + the six tests M-1/M-2/
M-3/the three Minors added):)*

```
$ (cd plugins/self-learn/cli && uv run --project . pytest --collect-only -q | tail -1)
2823 tests collected in 0.54s
$ (cd plugins/self-learn/ui  && uv run --project . pytest --collect-only -q | tail -1)
1282 tests collected in 0.54s
```

Per-file, for every file this unit reads or extends:

| file | tests | this unit |
|---|---|---|
| `test_verbs.py` | 48 | read-only reference |
| `test_route_cli.py` | 36 | read-only reference |
| `test_rehome.py` | 19 | **1 test rewritten** (the `:200` message pin, §7) |
| `test_rescope.py` | 34 | unchanged |
| `test_hosting.py` / `test_hosting_fixes.py` | 57 / 72 | unchanged |
| `test_lifecycle_cli.py` | 20 | unchanged |
| `test_m2_verbs.py` | 24 | unchanged |
| `test_dismiss_suspect.py` | 27 | unchanged |
| `test_ledger_ops.py` | 56 | unchanged |
| `test_miner.py` / `test_worker.py` | 100 / 52 | unchanged |
| `test_u_verbs.py` (this unit's own) | **94** (was 95) | PH1's skip-marked tombstone deleted outright at gate r1 landing (see `TestPhaseBoundary`'s own docstring); `phase2_verbs`'s `"followup add"` entry corrected to `"followup-add"` (Minor, gate r1: spelling unification) |

---

## 3. DECISIONS — the text `S-54` owes

*§3.1–§3.7 are written to be lifted into `S-54` (§11.1).*

### 3.1 One guard vocabulary, extended — never a per-verb check

**Decision.** Every new verb, and every widened leg of an existing one,
takes its status precondition from `ledger_ops.require_status` and
nothing else. No verb in this unit writes `if record.status != …`.
`rehome` and `rescope`'s two hand-rolled checks (§2.2, Finding V-1) are
**replaced** by `require_status(home, id, LIVE_STATUSES, verb=…)` in the
same edit that widens them — so the unit that adds four new move legs
also removes the last two places FW-51's root cause survives.

Two new status sets join the four that exist, in the same module and the
same closed-set style:

```python
#: `reopen`: only a rejected record returns to the draft plane. A
#: SUPERSEDED one has a live successor (or is a merge-collapse loser
#: whose evidence was merged into a survivor) — reopening it would
#: orphan that link; a ROUTED one is `reroute`/`supersede` territory.
REOPENABLE_STATUSES = frozenset({"rejected"})
#: `undefer`: the exact inverse of `defer`'s own write.
DEFERRED_ONLY = frozenset({"deferred"})
```

`ROUTED_ONLY` (existing) covers `reroute` and `followup add`.
`LIVE_STATUSES` covers the move legs and `reclassify --type`.
`reclassify --kind` takes **every** status, because 02 §2 says so in
words: *"`scope`/`kind` (triage may re-classify — the filing is never
frozen)"*, while the same paragraph freezes `type` at routing. That
asymmetry is not an oversight to smooth over; it is the pin, and §4.7
implements it exactly.

### 3.2 One filing-move operation — `rehome` and `rescope` widened, no third verb

**Decision.** There is **one** filing-move operation with **one** file-op
implementation, **one** target resolver, and **one** refusal set. It is
reachable through the two verb names that already exist. **No `refile`
verb is added.**

- **`rehome <id> --to <TARGET>`** — the general spelling. `TARGET` ∈
  `user` | `skill:<name>` | `project:<path-or-slug>` | `<path-or-slug>`
  (bare = project, byte-compatible with every existing call).
- **`rescope <id> --to <TARGET>`** — the same grammar, retained
  unchanged in argv and in commit subject. Its narrow vocabulary (`user`,
  `skill:<name>`) still works exactly as shipped; it additionally accepts
  the project forms.
- Both delegate to `verbs._move(home, id, to, …)`; both refuse
  identically; both **disclose the proposal sweep** (u-rescope's
  R-DISCLOSE-1/2, which `rehome` never did — §4.1).
- Every direction in the 3×3 scope matrix is supported except the
  identity diagonal, **including `skill:<a> → skill:<b>`** (FW-114 —
  §3.2c).

**Why not a third verb.** u-rescope §3 gave four rationales for a
separate verb. Measured against them:

| u-rescope §3 rationale | Status now |
|---|---|
| **1. "the target argument is a different kind of thing" — a slug that equals a skill name silently mis-files** | **Measured false** (§2.3, Finding V-3): 12/12 live slugs match `^-.+-[0-9a-f]{8}$`; `user` and `skill:` are unreachable as slugs. One prefix-tagged grammar with the reserved literals matched **first** has no ambiguity, and the only residual (a *relative* path literally named `user`) has a pinned escape and a test |
| **2. "`rehome` is agent-proposable; `rescope` should not be, yet"** | **Honoured unchanged.** `PROPOSABLE_VERBS` is untouched (§1 non-objective 4). Widening `rehome`'s `--to` does widen what an agent could ask for through the pane, so §4.1 adds the intake gate: `proposals._resolve_rehome_to` accepts **only** the project forms for an agent-authored proposal, and refuses `user`/`skill:` with the reason. A model may still say it in prose |
| **3. "the commit subject is pinned to the project shape"** | **Honoured by construction.** `rehome`'s subject stays `self-learn: rehome lrn-… → projects/<slug>` for every project target — byte-identical, so `test_rehome.py:106`, `09 §11 Y-18` and `10-surface-build-plan.md:511` stay true — and takes `→ skills/<name>` / `→ user` only on the new legs. `rescope`'s subject is untouched. Neither reuses `cli._routed_destination`'s split-on-`→` parse (u-rescope already dodged it with `_rescope_dest_label`) |
| **4. "a separate verb is the dated-future-work shape"** | **This spec IS the dated work.** FW-114/FW-115 asked for an ownership ruling before the build; §3.2 is it |

**Why not rename one into the other.** Retiring `rescope` into `rehome`
would give the ledger one verb word for one operation, which is the
tidier end state — at a measured cost of **3 test re-pins**
(`test_rehome.py:106`, `test_rescope.py:144`, `:159`) and **4 doc-site
amendments**, two of them inside ratified surface rows
(`09-surface-spec.md:2069`, `10-surface-build-plan.md:511`) plus
`02-schema.md:398` and `:453`. Retention costs zero of those. **RULED
2026-08-28 (§3.8 R1): keep both names** — and the ruling tightens rather
than softens this section, because "two names" is only safe if it is not
also "two implementations". `MOVE10` is the criterion that holds that
line; `M71` is the mutation that would otherwise slip past every
behavioural test.

#### 3.2a The file-op, unified

`ledger_ops.rehome_record` and `ledger_ops.rescope_record` are replaced
by **one** function, `ledger_ops.move_record(home, record_id, *,
target_scope, target_bucket, project_path=None)`, which:

1. resolves the record with `find_record_path(..., statuses=("pending",))`;
2. refuses a destination collision in `pending/` OR `resolved/` (the F4
   `create_record` precedent, unchanged);
3. creates `{pending,resolved,proposals}/` under the target;
4. stamps `meta.yaml` via `ensure_project_meta` **iff** `project_path is
   not None` (i.e. the target is a project bucket);
5. **writes `scope:` unconditionally** — `record.set_scope(target_scope)`
   on every leg, where `target_scope` is the identity of the bucket the
   record lands in. **One rule, no predicate**
   *(SIMPLIFIED-r5, gate M-2r3)*.

   *r3 conditioned this on the BUCKET-derived source scope and thereby
   made its own project→project repair unreachable (gate M-1r2). r4
   conditioned it on `record.scope` instead, which is correct but
   needless: the gate measured that `Record.write` is a **byte-perfect
   round-trip** — `set_scope(record.scope)` followed by `write()` leaves
   the file byte-identical on four real ledger records — so the
   conditional and the unconditional forms are behaviourally
   **equivalent**, and the conditional buys a predicate that no test can
   observe. The simpler rule is the one that ships.*

   Two consequences, stated rather than left implicit:
   **(a)** `09-surface-spec.md:2069`'s byte-untouched pin is satisfied by
   the round-trip, **not** by a conditional — step 6 calls
   `record.write(dest_path)` on every leg regardless;
   **(b)** the only observable fork is `M78`'s — *adding* a
   bucket-equality condition, which skips the write exactly when source
   and target buckets share a scope, and so silently keeps a wrong
   literal on the project→project leg. **`MOVE1` leg 9 is the criterion**
   (§5.2) and the only thing that catches it.

   **§4.1 step 6's same-place refusal keeps reading the BUCKET** — a
   different question with a different source, and u-rescope §6.2 step 5's
   point: a record whose frontmatter disagrees with its bucket is what
   this verb repairs, so the field cannot be trusted to answer *"is this
   a move at all?"*


   **Measured — the disagreement is real, not hypothetical (Finding V-6).**
   The walker, written out in full *(gate N-4r2: r3 elided the body, against
   §0's own rule)*:

   ```
   $ python3 - <<'PY'
   import re
   from pathlib import Path
   H = Path.home() / '.self-learn'
   buckets  = [('user', H / 'user')]
   buckets += [(f'skill:{d.name}', d) for d in sorted((H / 'skills').iterdir())   if d.is_dir()]
   buckets += [('project',         d) for d in sorted((H / 'projects').iterdir()) if d.is_dir()]
   bad, n = [], 0
   for expected, bdir in buckets:
       for sub in ('pending', 'resolved'):
           if not (bdir / sub).is_dir():
               continue
           for f in sorted((bdir / sub).glob('lrn-*.md')):
               n += 1
               m = re.search(r'^scope: (.+)$', f.read_text(encoding='utf-8', errors='replace'), re.M)
               got = m.group(1).strip() if m else '<none>'
               if got != expected:
                   bad.append((f.relative_to(H), got, expected))
   print('buckets scanned:', len(buckets))
   print('records scanned:', n)
   print('scope/bucket MISMATCHES:', len(bad))
   for r in bad:
       print('  ', r[0], ' scope=', r[1], ' bucket expects=', r[2])
   PY
   buckets scanned: 18
   records scanned: 152
   scope/bucket MISMATCHES: 1
      user/resolved/lrn-c826137f.md  scope= skill:cron-claude  bucket expects= user
   ```

   One of 152 live records disagrees with its bucket. It is **`resolved`**,
   so `require_status(..., LIVE_STATUSES, ...)` refuses it and no move verb
   can repair it — the honest scope of this clause: it governs the drafts a
   move CAN touch, and it does not silently rewrite frozen substance
   (02 §2). That record is **FW-138**; `MOVE1` leg 9 covers the *pending*
   record with the same defect, which is the one this verb must repair;
6. `git mv`s the file, then `record.write(dest_path)` — **mv-first**,
   u-rescope §6.4's ordering, which is the stricter of the two and is
   therefore adopted for the project legs too;
7. sweeps the source-bucket proposal siblings and returns `(touched,
   swept)` — the **pair**, u-rescope's shape, because only the pair makes
   the disclosure implementable.

`rehome_record` and `rescope_record` are **deleted**, not kept as
wrappers: two half-complete implementations of one operation is the
defect (Finding V-2), and leaving one as a shim would leave the drift
path open.

#### 3.2b `scope: project` carries no name — the asymmetry that made the matrix look hard

Measured (§2.3's `grep -h '^scope: '` census): a project record's `scope` literal is exactly
`"project"` — the *bucket slug* carries the project identity, and it is
not in the record. A skill record's is `skill:<name>`; a user record's is
`user`. So:

- **project → project** rewrites no `scope:` (both are `"project"`) — why
  `rehome` could be byte-untouched;
- **project → user/skill** and **user/skill → project** rewrite it;
- **only project targets** need `meta.yaml`.

`move_record` reads both conditions off the resolved target, so no leg is
special-cased.

#### 3.2c `skill:<a> → skill:<b>` is ruled IN, and FW-114 closes

FW-114's stated blocker is *"the direction where the proposal-sweep
hazard (u-rescope §5.3) has its sharpest form: a trace whose destination
judgment was owned by skill `a`, re-derived under skill `b`"*, and its
trigger asks for *"the third leg of §5.3's evidence gathering — does a
**carried** skill→skill proposal degrade gracefully?"*

**That question is moot for the shipped design.** u-rescope §5 decided
SWEEP, not carry: `remove_proposal_siblings` deletes the proposal on
every leg, so no proposal is ever carried across any bucket boundary and
there is no "carried skill→skill proposal" to characterise. Refusing the
leg now would make the move's refusal matrix a special-cased predicate
instead of a uniform one, which is the shape this unit exists to remove.
It is ruled **IN**, and `S-54` records FW-114 as closed with that
reasoning.

### 3.3 One batch executor — one new exit integer, and idempotence defined

**Decision.** `self-learn batch <SHEET.yaml> [--dry-run] [--json]
[--no-push]` is a first-class verb in a new module
`cli/src/self_learn/batch.py`. The review skill calls it; no review ever
writes another bash script. It:

- holds the sentinel **once** for the whole run (one **owning** hold —
  §4.4), heartbeats, releases in a `finally`;
- calls the same `verbs.*` functions the CLI calls, each with
  `no_push=True`, each inside its **own** `_ledger_write` span (§10);
- pushes **once** at the end (skipped under `--no-push` and `--dry-run`);
- reports **per-item exit codes** on a `--json` envelope and returns the
  process code §3.3a defines;
- **stops** on the first `5`/`6`/`7` (the ledger is unsafe to keep
  writing into) and **continues** past a `1` (a refusal is that item's
  business, and one bad route must not block thirty good ones);
- **refuses `hook` routes** — S-29's hard floor: a hook route replays
  examples and writes an executable, and that is never an unattended bulk
  action;
- **refuses `host add` / `host rebind` / `host remove`** for the same
  reason in the registration dialect: `09 §11 Y-17` makes registration a
  *disclosed-consent* event, and consent does not ride a bulk apply. The
  08-25 sheet's hand-sequenced `host add` (§2.4) stays hand-sequenced, and
  `--dry-run` **names it as a prerequisite** instead of silently failing
  at apply time.

**`--continue` is DROPPED** *(r3, gate D-2 + ruling)*. r2's signature
carried it, but §3.3b's classification makes a plain re-run identical to
a resume: per-item refusals never stop a batch, and ledger-level failures
always do. A flag whose behaviour is indistinguishable from its absence
is a flag that will one day be documented as meaning something it does
not.

#### 3.3a The process exit code — the contract gains ONE integer

*(r3 — gate M-6, ruled by the orchestrator. r2 returned "the
highest-severity item code" under `7 > 4 > 3 > 6 > 1 > 0`, which meant a
sheet with 30 applied items and 1 refusal exited **1** — the integer whose
ratified meaning is "the verb REFUSED, **nothing was written**"
(`cli.py:13-22`, `commands/review.md:264`: *"Only 3, 4 and 7 mean 'the
ledger changed'"*). That is a fork of the contract in its designed-normal
case, and §11.4's "never under-reports" claim asserted the opposite of
what the design did.)*

**The eight-integer contract describes ONE mutation. A batch is many.**
So the contract is **extended in its one table**, not forked:

> **`EXIT_BATCH_PARTIAL = 8`** — *batch completed; N items applied, M
> refused. The ledger DID change. Read the `--json` envelope for which.*

`8` is the next free integer: `0`-`7` and `64` are taken, and `2` is
`proposal validate`'s scan hit (`cli.py:71`'s comment pins it as
un-aliasable). Measured free at `b206800`:

```
$ grep -rnE 'return 8\b|EXIT_[A-Z_]+ = 8' plugins/self-learn/cli/src/self_learn/*.py
(no output)
$ grep -n 'EXIT_' plugins/self-learn/cli/src/self_learn/gitops.py | grep '='
117:EXIT_PUSH_FAILED = 3
118:EXIT_REBASE_CONFLICT = 4
133:EXIT_GIT_FAILED = 6
143:EXIT_HALF_WRITTEN = 7
```

**The decision procedure** (a procedure, not a `max()` — that is what
`BAT2` tests, and what `M30` breaks):

1. Sheet validation fails → **64**, nothing runs.
2. Home gate fails → **5**, nothing runs.
3. A **ledger-level** failure occurred (an item returned 3, 4, 6 or 7) →
   the **worst of those four** under `7 > 4 > 3 > 6`, and the envelope
   names every item that landed before it.
4. Else every item `applied` or `already-applied` → **0**.
5. Else ≥1 refusal **and ≥1 commit landed** → **8**.
6. Else (≥1 refusal, **zero** commits) → **1** — which keeps `1`'s
   ratified meaning exactly: refused, nothing written.

Steps 5 and 6 are separated by *"did anything land"*, so **`1` is never
emitted after a write**, which is the whole point. `0` means everything
applied; `8` means read the envelope; `3`/`4`/`7` mean a git step failed
after the ledger changed; `6`/`1`/`5`/`64` mean it did not.

**Where this row is owed is a MEASURED list, and it lives in §8** —
three surfaces render this contract and all three take the `8` row;
`11-telemetry-and-lifecycle.md` is **not** one of them, and neither is
`commands/teach.md`. `DOC8` counts all five, positively and negatively.
*(REPLACED-r6, gate M-1r4: r5 corrected this claim in §8 and left the
original sentence standing here — the third round running in which a
correction landed in a new place while the false original survived. §13
now carries the sweep that catches the class.)*

#### 3.3b Idempotence, defined — and true for every permitted verb

*(r3 — gate M-5, ruled. r2 classified 9 of the 15 permitted verbs and let
the rest "fall through to the verb's own idempotency refusal", which is
false for four of them: `note --append` appends a SECOND entry (rc 0, but
the ledger hash changes, failing `BAT8`'s own leg);
`link-contradicts` raises `already contradicts` at `records.py:621` → rc
1, not `already-applied`; `followup-done` and `confirm-held` are the same
shape.)*

**Definition.** An item is **`already-applied`** when its *effect is
already present* — the record's state, the link, the follow-up, the
confirmation, or the note already exists. An `already-applied` item is
**SKIPPED**: the verb is never called, nothing is written, the item's rc
is `0`, and the classification is a **state read**, never a parse of a
refusal message.

**Consequence, and the criterion (`BAT8`): the second run of an applied
sheet applies 0 items and exits 0**, with the ledger's `HEAD` unchanged.

Every one of the 15 Phase-1 permitted verbs, and the 3 Phase-2 ones:

| # | verb | `already-applied` when | ph |
|---|---|---|---|
| 1 | `route` | `status == routed` **and** `routing.destination` + qualifier equals the item's resolved destination | 1 |
| 2 | `reject` | `status == rejected` | 1 |
| 3 | `defer` | `status == deferred` **and** (`--until` given ⇒ `deferred_until` equals it; else `deferred_until` is in the future) | 1 |
| 4 | `undefer` | `status == pending` **and** `deferred_count >= 1` — the same guard shape row 5 uses *(tightened r4, gate N-6r2: `status == pending` alone silently SKIPS an item aimed at a record that was **never deferred**, where the verb alone would refuse naming the status. `undefer` never clears `deferred_count` (§4.2), so it is the durable witness that a defer happened; a never-deferred pending record has `deferred_count: 0`, the item reaches the verb, and the verb refuses)* | 1 |
| 5 | `reopen` | `status == pending` **and** `history` carries an `event: resolution` entry — so a never-rejected pending record is NOT "already reopened" and still refuses on status | 1 |
| 6 | `graduate` | `status == superseded` **and** `superseded_by == "canon"` | 1 |
| 7 | `supersede` | `status == superseded` **and** `superseded_by == item.new_id` | 1 |
| 8 | `rehome` | the record already lives in the item's resolved target bucket | 1 |
| 9 | `rescope` | same as `rehome` — one resolver, one condition | 1 |
| 10 | `note` | **an `notes[]` entry already carries this item's idempotency key** — §4.2: `key = sha256(<canonical sheet line>)[:16]`, stamped on the entry when `batch` writes it. This is the ONE verb whose effect is not derivable from record state (a second identical note is a legal thing to want), so it is the ONE verb that carries a key | 1 |
| 11 | `confirm-recurrence` | the item's `--event` nonce is already in `recurrences[].ref` | 1 |
| 12 | `dismiss-suspect` | the nonce is already in `dismissed_suspects[].ref` | 1 |
| 13 | `confirm-held` | `last_confirmed` is **set at all**. A *repeat* confirmation is a new fact and is deliberately **out of a sheet's reach** — run the verb directly. Rationale: `last_confirmed` is a bare timestamp, so it cannot distinguish "this sheet already did it" from "someone did it last month", and a sheet that re-confirms on every re-run is not re-runnable | 1 |
| 14 | `link-contradicts` | the target is already in `links.contradicts` — **exactly** the condition `Record.append_contradicts` raises on (`records.py:618-621`), read instead of triggered | 1 |
| 15 | `followup-done` | `routing.follow_up` is absent **and** `follow_up_done` is present | 1 |
| 16 | `reroute` | `status == routed` **and** `routing.destination` + qualifier equals the item's new destination | 2 |
| 17 | `followup add` | `routing.follow_up` is present **and** its `action` equals the item's | 2 |
| 18 | `reclassify` | `kind` (and `type`, when given) already equal the item's values | 2 |

#### 3.3c The flush rule moves to ONE place — the mutating-verb epilogue

*(NEW r4 — gate M-4r2, ruled. **REWRITTEN r5** — gate M-1r3: r4 folded
only the `VERB_COMMANDS` branch and deferred the rest behind an obstacle
the gate measured and found **false**. There is no residual and no FW row;
all of it folds here.)*

r4's problem was real: r4 put `batch` outside `VERB_COMMANDS` (correctly,
for `SHOW3`'s reason) and thereby dropped the 11 §4.2 flush for the entire
review path — a session that used to flush once per verb dispatch, 34
times on the 08-24 sheet, would have flushed **zero** times, leaving the
events in `~/.cache/self-learn/home-<sha>/`, the directory §3.3b's own
journal argument calls a place an operator clears.

**The root cause is not `batch`. The flush rule is written once per
dispatch branch — SIX times.** Measured at `b206800`:

```
$ grep -c '_flush_spool_best_effort(' plugins/self-learn/cli/src/self_learn/cli.py
7
$ awk '/^def /{f=$2; sub(/\(.*/,"",f)} /_flush_spool_best_effort\(/{printf "cli.py:%-5d  in %s\n", NR, f}' \
      plugins/self-learn/cli/src/self_learn/cli.py
cli.py:1949   in _cmd_report                 # flush_state = _flush_spool_best_effort(home)
cli.py:1955   in _flush_spool_best_effort    # the def
cli.py:2135   in _main                       # teach
cli.py:2145   in _main                       # VERB_COMMANDS
cli.py:2150   in _main                       # followup
cli.py:2155   in _main                       # link
cli.py:2189   in _main                       # import
```

**Seven occurrences = one def + SIX call sites.** *(CORRECTED-r5: r4 said
five, counting only `_main`. `_cmd_report:1949` is a sixth, and it is not
an outlier — the shipped comment at `:1945`, **four** lines above the
call, reads verbatim *(distance corrected r6, gate N-2r4; the quoted text
was already exact)*
`# report is a flushing verb (11 §4.2) — its numbers include the spool.`
It is the same rule, hand-copied a sixth time.)* A seventh surface has to
remember it a seventh time, and this spec's r3 did not. That is the shape
of Finding V-1 (`require_status` hand-rolled in two verbs) and Finding V-2
(the file-op written twice), and it takes the same answer.

**Decision — fold ALL of them.** One epilogue,
`cli._mutating_epilogue(home=None, *, no_push: bool = False) -> str`,
carrying `_flush_spool_best_effort`'s **exact signature and return** so
every substitution is a one-line, in-place edit. Its docstring states the
rule once: *11 §4.2's flush — the ONE place that rule is written; every
dispatch that may commit ends here, so a new surface cannot miss it by
forgetting to copy a line.*

**The fold is order-preserving, measured.** The gate re-measured the two
branches r4 claimed as obstacles and both have the identical shape:

```
    code = run_teach(args)            |     code = _cmd_import(args)
    _flush_spool_best_effort(…)       |     _flush_spool_best_effort(…)
    if (code == EXIT_OK and not args.route) or code == 4:  |  if code == EXIT_OK:
        _kick_after_capture(…)        |         _kick_after_capture(…)
    return code                       |     return code
```

Substituting the one flush line moves nothing: `code` is captured before
it, the kick still runs after it, the `if` conditions are untouched, and
`return code` is unchanged. **r4's stated obstacle — "reorders `teach`'s
worker kick and `import`'s exit-code branch" — was false**, and it
described a *different* fold (one that also absorbed the kick, where the
two conditions genuinely differ). Nothing is deferred, so **there is no
FW-139**, and the FW ceiling stays at **FW-138** with no numbered hole.

**The enumerated caller set — SEVEN call sites, normative and listed:**

| # | call site | surface |
|---|---|---|
| 1 | `cli._cmd_report` (was `:1949`) | `report` — flushes so its numbers include the spool |
| 2 | `cli._main`, teach branch (was `:2135`) | `teach` |
| 3 | `cli._main`, `VERB_COMMANDS` branch (was `:2145`) | the ten resolution verbs |
| 4 | `cli._main`, followup branch (was `:2150`) | `followup done` |
| 5 | `cli._main`, link branch (was `:2155`) | `link contradicts` |
| 6 | `cli._main`, import branch (was `:2189`) | `import` |
| 7 | `batch.run`, after the item loop | `batch` |

`BAT11` pins this list **parameterised over the table above**, not as a
hardcoded count, so an eighth caller reddens until the list is edited —
a deliberate spec change, never a silent one.

**Where `batch` calls it:** after the item loop, **before**
`push_pending`, **inside** the sentinel hold, always with
`no_push=True` — the same reason the items run `no_push=True`: the batch
owns the single push, and the flush's own commit must ride it rather than
publish itself. Order: items → `_mutating_epilogue(no_push=True)` →
`push_pending` (unless `--no-push`) → `hold.release()`.

**The flush COMMITS** (`cli.py:1955-1969`: *"the flush commits (H-5 —
telemetry is a producer)"*), so it is a ledger commit the criteria must
count: **`BAT10` leg (a) seeds the spool and asserts `HEAD` moved by
`N+1`** — N item commits plus one flush commit. An empty-spool fixture
would move by N either way and could not see `M79`, so the seeded form is
the one tested (§5.5). `BAT8`'s "HEAD identical on re-run" survives for
the complementary reason: `telemetry._commit_flush` (`telemetry.py:346`)
returns early when nothing was flushed, so an epilogue call on an empty
spool commits nothing.

`11 §4.2`'s doctrine bullet — today *"**Only human-triggered CLI verbs
flush** the spool into the tracked plane"* — gains one sentence:
**"every mutating dispatch — single verb or batch — flushes exactly
once, through `cli._mutating_epilogue`"** (`DOC5` third leg).

**Resumability is derived from ledger state, not from a journal.** The
assessment proposed a `<home>/.batch/<sheet-sha>.jsonl`. Refused: a
journal in the ledger is an uncommitted tracked-tree artifact that
`reconcile` would trip over, and a journal in the cache
(`~/.cache/self-learn/home-<sha>/`, H-4) sits in exactly the directory
FW-130 measured at **31,291 stray namespaces / 1.1 GB** — a place an
operator clears. **The durable record of what a batch did is the ledger's
own git history: one commit per item.**

### 3.4 One new frontmatter key — `history`, append-only

**Decision.** `reopen` must clear the write-once `resolution_note`, and
`reroute` must replace a `routing` block. Both would otherwise destroy
the only in-record copy of a fact the analyst reads (the M2
rejected-proposal digest reads `resolution_note`; `report`'s
`superseded_after_routing` reads `routing.routed_at`). Git keeps the old
bytes, but nothing in the product reads git for them.

So **one** key is added, not two:

```yaml
history:                       # append-only; never rewritten, never removed
- at: 2026-08-28T09:41:00Z
  event: resolution            # what `reopen` displaced
  status: rejected
  note: "not serious enough to warrant a rule"
- at: 2026-08-28T09:42:11Z
  event: routing               # what `reroute` displaced
  routing: {destination: reference, routed_at: 2026-08-24T…, by: human}
```

Same metadata class as `recurrences` / `dismissed_suspects` (02 §2's
2026-07-15 and 2026-08-24 amendments): optional, verb-written, mutable in
every status, and it never touches the substance freeze. `event` is a
closed set — `{"resolution", "routing"}` — so a future third displacement
is a decision, not a silent widening.

### 3.5 `reference` retirement is a real removal

**Decision.** `graduate`, `supersede` and `reroute` on a
reference-routed record **remove that record's entry block** from its
references file, in the retirement host phase, exactly as the doc-target
legs already drop a managed-section entry. The
*"references are append-only"* clause in `verbs._Retirement`'s docstring
and in `compilers._LEARNINGS_HEADER` describes the **compiler's write
mode**, and it stops being true of the file's lifetime; both are
corrected, and `08 §1`'s References-compiler pin gains one sentence.

The alternative — marking the block retired in place — was considered and
refused: the whole cost G4 measures is that a wrong `--dest reference`
leaves *permanent readable canon text*, and a reader who reaches the
block through the pointer reads the stale advice above the retirement
line before reaching the line.

**Named residual (FW-135):** the seven live `LEARNINGS.md` files carry a
header saying *"this file is append-only"* that becomes one word stale.

*(CORRECTED-r3, gate N-3: r2 called that header "hand-owned" and "the
human's bytes". It is not — **self-learn wrote it.**
`compilers._LEARNINGS_HEADER` (`compilers.py:173`) is applied at
`compilers.py:1174` on first creation, and is byte-identical to the live
files' headers:*

```
$ sed -n '173,180p' plugins/self-learn/cli/src/self_learn/compilers.py
_LEARNINGS_HEADER = (
    "# Learnings\n"
    "\n"
    "Reference-routed lessons, appended by self-learn (newest last). Each\n"
    "entry carries its record id for provenance; regenerate nothing here —\n"
    "this file is append-only.\n"
)
$ head -5 ~/repos/ignomi/references/LEARNINGS.md
# Learnings

Reference-routed lessons, appended by self-learn (newest last). Each
entry carries its record id for provenance; regenerate nothing here —
this file is append-only.
```

*The refusal stands, on its OTHER ground only:* a references file has
**no managed marker region**, so there is no bounded span the compiler
owns and no idempotent way to rewrite a header a human may since have
edited — a blind overwrite would be exactly the hand-edit-clobbering the
marker contract exists to prevent. The constant is corrected for newly
created files only, and the seven live files keep a one-word-stale
sentence self-learn itself wrote.

### 3.6 `host remove` refuses — there is no honest bulk retirement

**Decision.** `host remove <path>` **refuses (exit 1)** when ≥1 record
whose `routing.destination` resolves into that host is still `routed`,
naming the count and the first five ids, and naming the two repairs. The
override is **`--gate-only`**, which is today's behaviour made explicit
and loud (a post-note stating that the host's managed section is now
unmanaged and `recompile` will WARN-and-skip it).

**No `--retire` is offered**, and this is the ruling the mandate asks
for. `graduate` means *"authored canon already covers this"* and
`supersede` means *"another record replaces this"*. For a host being
deregistered, **both are false statements about every record in the
set**, and writing 27 false resolutions in one commit to make a
deregistration convenient is precisely the inversion FW-51 was opened
about (a machine turning a human's non-decision into a resolution). The
two honest repairs are: **move the records to another registered host
first** (`rehome`, now that it reaches every scope), or **`--gate-only`
and accept the stated consequence.** `S-54` records the refusal so it is
not rediscovered as an omission.

### 3.7 Producer outcomes ride `--json`, not new integers

**Decision.** `worker kick`, `worker run` and `mine run` gain `--json`,
emitting one object on stdout and nothing else:

```json
{"command": "worker kick", "outcome": "absorbed-window", "ok": true}
{"command": "mine run", "outcome": "held-gate", "ok": true,
 "landed": 0, "folded": 0, "recurrences": 0, "fires": 0, "run_id": "a1b2c3d4"}
```

**No exit-code integer changes.** The exit status keeps meaning exactly
what it means for every other surface — *did this fail* — which is 07 §4
contract 2 ("success/failure is still the exit status, never this JSON")
extended from the resolution verbs to the producers rather than forked.
Considered and refused: mapping `busy` → 6. It is defensible in
isolation (`busy` genuinely is "refused before the first mutation, safe
to retry"), but it would make a benign concurrent timer tick report
failure to systemd, and FW-85 names the systemd units as its own blast
radius. The residual — that the *integer* stays uninformative — is
**FW-134**, with the `--json` envelope as the sanctioned reading.

### 3.8 Rulings folded — orchestrator, 2026-08-28

The five questions §12 raised were ruled before the build. Each ruling is
recorded here as a decision, with the reasoning that decided it and the
criterion or mutation it moved.

**R1 (was Q1) — KEEP BOTH NAMES, but only as two entry points over ONE
implementation and ONE grammar.** Retiring a ratified surface name buys
nothing a user can feel; a *second implementation* is what the standing
root-cause preference forbids, and Finding V-2 says the codebase already
has one. So the ruling tightens §3.2 rather than softening it:
`rehome` and `rescope` keep their argv and their commit subjects, and
neither verb body may contain a file-op of its own — both parse the same
union `--to` grammar through `_resolve_move_target` and both write
through `ledger_ops.move_record`. **New criterion `MOVE10`** asserts that
structurally (a source/AST check that neither body renames, writes or
`git mv`s a record itself), and **new mutation `M71`** reintroduces a
divergent write inside `rescope` and must redden it. Without `MOVE10`,
"one implementation" is prose a builder can quietly violate while every
behavioural test stays green — which is exactly how the two half-complete
file-ops got here.

**R2 (was Q2) — SHIP `skill:<a> → skill:<b>`; FW-114 closes.** The row's
blocker was a *carried* proposal's judgment drift, and u-rescope §5's
SWEEP decision means nothing is carried on any leg, so the failure mode
it names cannot occur. §3.2c already builds it; the FW-114 disposition
note in §11.2 is the closure. No criterion moves — `MOVE1`'s eight legs
already include it.

**R3 (was Q3) — `batch` lives in the CLI.** Sentinel hold/release, the
single push, the severity ordering and already-applied idempotence are
*ledger* semantics; a skill that re-derives them will re-derive them
differently, which is the measured failure (§2.4: two scripts, two
different `--no-push` strategies). The review skill becomes a thin
caller. **New criterion `DOC7`** names the exact `commands/review.md`
sections that change and checks each one *within its own heading range*
(the `DOC3` pattern), so three edits in one section cannot satisfy it;
**new mutation `M73`** collapses them into one section.

**R4 (was Q4) — FOLD the reference-retirement change into `S-54`.** It
is a behaviour change to two shipped verbs (`graduate`, `supersede` now
edit a file they used to leave alone), and S-10 would normally want its
own row. It is folded because the measured live-instance count is
**zero** — no reference-routed record has ever been graduated or
superseded (§2.5) — so no human relies on the old behaviour, and the old
behaviour is documented nowhere but a docstring. §11.1's row states the
change and keeps the **27-of-92** exposure figure as its evidence. No
criterion moves; `RER5`/`RER6` already carry it.

**R5 (was Q5) — SHIP `note --append` AND render it on `show`, same
phase.** A field nothing reads is the `FW-80` shape (a display vocabulary
nobody validates). Shipping the writer and its one reader together means
the key is never write-only for even one release. `STATE8` gains a second
leg — the appended note must come back out of `show --json` **and** the
human render — and `SHOW1` gains `notes` to its required key set; **new
mutation `M72`** drops the rendering and must redden `STATE8`.

---

## 4. Design (field-exact)

### 4.1 The move: `rehome` / `rescope`, one mechanism

**Target grammar** — `verbs._resolve_move_target(home, to) -> (target_scope, target_bucket, project_path | None)`,
the ONE resolver, matched in this order, first match wins:

| `--to` | resolves to | registry consulted |
|---|---|---|
| exactly `user` | `("user", home/"user", None)` | none |
| `skill:<name>`, `<name>` non-empty | `(f"skill:{name}", home/"skills"/name, None)` | `hosts.skill_dir_for` (validity gate only) |
| `project:<rest>` | as the bare form below, over `<rest>` | `hosts.projects` |
| anything else | `("project", home/"projects"/slug, resolved_path)` | `hosts.projects` |

Refusal strings are the shipped ones, unchanged: an unregistered project
target names `self-learn host add <path>`; an unknown/ambiguous skill
names `self-learn host add <path> --skills-root`; an unparseable `--to`
names the whole grammar.

**The reserved-literal escape, pinned.** `user` and `skill:…` are matched
as *literals* before any path resolution, so a project host whose
directory is literally named `user` is unreachable by the bare form. The
escapes are `project:user`, `./user`, or the absolute path — all three
work, and `MOVE4` tests the first two against a host registered at a
directory named `user`.

**Verb procedure** (`verbs._move`, called by both `rehome` and `rescope`;
step order is `rescope`'s, which is the stricter of the two):

1. `path = find_record_path(home, record_id)` — pending OR resolved.
2. `_scan_or_refuse([path], note)` — before trusting the bytes.
3. `require_status(home, record_id, LIVE_STATUSES, verb=<invoked name>)`
   — **replacing** the two hand-rolled checks at `verbs.py:4281`/`:4467`.
4. `target_scope, target_bucket, project_path = _resolve_move_target(...)`.
5. Source scope from the **BUCKET**, never the record's `scope:` field
   (u-rescope §6.2 step 5 — a record whose frontmatter disagrees with its
   bucket is what this verb repairs).
6. Refuse `source_scope == target_scope` **and** `target_bucket ==
   source_bucket` (the same-place refusal; both checks, because two
   project buckets share the scope literal `"project"`).
7. Refuse a destination collision in `pending/` or `resolved/`.
8. `sentinel.hold()` + heartbeat; `with _ledger_write(home):`
   `move_record(...)` → `(touched, swept)`; body =
   `_move_commit_body(note, swept)`; `_commit_ledger(...)`.
9. Push unless `--no-push`; `post_notes` = `[_move_sweep_note(...)]` when
   `swept` — **on both verbs**, closing `rehome`'s silent sweep.

**Commit subjects.** `self-learn: rehome lrn-… → <dest-label>` /
`self-learn: rescope lrn-… → <dest-label>`, with `dest-label` from the
existing `_rescope_dest_label` widened by one arm:
`projects/<slug>` | `skills/<name>` | `user`. The project arm is
byte-identical to today's.

**Agent-proposal intake: narrowed on the TARGET, opened on the SOURCE.**

*(CORRECTED-r3, gate M-4. r2 named `ui/proposals._resolve_rehome_to`,
which **does not exist** — `grep -c '_resolve_rehome_to' ui/src` → 0. The
real gate is `proposals.validate_proposal`'s `rehome` branch,
`ui/src/self_learn_ui/proposals.py:348-372`, resolving the target through
`_registered_project_for` (`:232`). r2 also missed that the branch
refuses on the record's **own scope**, which makes §11.5's doctrine
amendment impossible to obey.)*

The shipped refusal, verbatim (`proposals.py:354-358`, re-read from
`git show b206800:…/proposals.py` — the branch itself runs `:348-372`):

```python
        if location.scope != "project":
            return _refuse(
                f"rehome is project→project only (M1) — {record_id} is "
                f"{location.scope}-scoped and cannot move"
            )
```

That source-scope refusal is **DELETED**. It is a second, hand-rolled
status/scope guard living in the UI — the same shape §3.1 removes from
`verbs.rehome` and `verbs.rescope` — and with it in place a user-scoped
record can never be proposed to a project target, which is *precisely*
FW-115's user→project case and precisely what §11.5's doctrine amendment
tells the analyst to propose. **One guard vocabulary:** the verb's
`require_status(..., LIVE_STATUSES, ...)` plus `_resolve_move_target`
decide, and the intake gate decides only what an *agent* may ask for.

What the intake gate keeps, and what it gains:

- **KEEPS** the target narrowing: `to` must resolve through
  `_registered_project_for` to a **registered project**. `user` and
  `skill:<name>` are refused with *"a scope change is a human verb — say
  it in `rationale` and let the human type it"* (u-rescope §3
  rationale 2, preserved deliberately: widening `--to` must not widen
  what a model may propose).
- **KEEPS** the unregistered-target refusal and the same-bucket refusal,
  byte-unchanged.
- **LOSES** the source-scope refusal. A `user`- or `skill:`-scoped
  pending record may now be *proposed* for a project target; the human
  arms it and the verb decides.

### 4.2 `undefer`, `reopen`, `note`, and the past-date refusal

**`defer --until <past>` refuses.** In `ledger_ops.defer_record`, after
the date is normalised: if the parsed date is **strictly before today**
(the **UTC** date — the one clock `DEFAULT_DEFER_DAYS` counts from, every ledger timestamp is written in, and `list`'s eligibility compares against; *amended 2026-08-28 17:10 PDT: r6 read "the caller's local date", which the product never implemented and which STATE1/STATE2 measured with `date.today()` — both went red at 00:00 UTC on the landed build; fixed forward on master with `defer_record(..., now=)` injectable*),
raise `LedgerOpsError` naming today and pointing at the real verb:

> `defer lrn-…: --until 2026-08-01 is in the past (today is 2026-08-28 UTC)
> — a defer must name a future date; `self-learn undefer lrn-…` is the
> verb for bringing a deferred record back now`

`--until <today>` is **accepted** (a same-day re-queue is meaningful and
`list`'s eligibility is `deferred_until <= now`). Exit **1** (a refusal,
nothing written) — not 64, because the flag parsed fine and the *record
state* is what makes it illegal, which is 02 §2's own distinction.

**`self-learn undefer <id> [--note] [--no-push]`** —
`require_status(..., DEFERRED_ONLY, verb="undefer")`; sets `status:
pending`, clears `deferred_until`, **keeps `deferred_count`** (the
"at 2 the card suggests reject" signal is history, not state); ledger-only,
one commit `self-learn: undefer lrn-…`; `--note` rides the commit body
only (`resolution_note` untouched — an un-defer is not a resolution).
Re-running it refuses naming `'pending'`.

**`self-learn reopen <id> [--note] [--no-push]`** —
`require_status(..., REOPENABLE_STATUSES, verb="reopen")`. Under
`_ledger_write`:

1. append `{at, event: "resolution", status: "rejected", note:
   <the old resolution_note or null>}` to `history`;
2. `record.clear_resolution_note()` (a **new** setter — the only writer
   permitted to clear it, and it refuses unless a `history` entry
   carrying that exact note already exists, so the note can never be
   silently lost);
3. `status: pending`;
4. `git mv resolved/ → pending/`, then `record.write(dest)` (mv-first);
5. sweep any stale proposal siblings and **disclose** them, same shape as
   the move.

Commit `self-learn: reopen lrn-…`. `post_notes` says plainly that the
record re-enters the queue and **will be re-analyzed**.

Refused, with the reason in the message: `superseded` (a live successor
or a merge-collapse evidence merge would be orphaned) and `routed`
(un-writing canon is FW-133).

**`self-learn note <id> --append TEXT [--no-push] [--key KEY]`** — any
status; `_scan_or_refuse` on the text; appends `{at, by, text}` — plus
`key` when given — to a **`notes`** list.

**`--key` is the idempotency key (§3.3b row 10, ruling M-5)**, and it is
**not** a general-purpose flag: `batch` passes
`key = sha256(<the item's canonical YAML line, keys sorted>)[:16]`, and
`note` appends **nothing** (rc 0, no commit, no ledger change) when a
`notes[]` entry already carries that key. A human at a terminal omits it
and every `note` call appends, which is the right default — two identical
observations on two days are two facts. This is the one verb whose effect
cannot be derived from record state, which is why it is the one verb that
carries a key rather than a state rule.

`notes` is a **separate key from `history`**: `history` records
*displaced* values, `notes` records *added* commentary, and merging them
would make both unreadable. `resolution_note` is never touched. Commit
`self-learn: note lrn-…`.

### 4.3 `route --dry-run` and `show`

**`self-learn route <id> [--dest T] --dry-run [--json]`.** Runs every
preflight the real route runs, in the same order, and then **computes the
bytes the compiler would write and throws them away**:

- `find_record_path` → `_scan_or_refuse` → `require_status` →
  `_resolve_destination` → `_resolve_target` (which carries the host
  gate, the registration gate, the dirty check and, after U-hostmode, the
  mode) → the ALWAYS gate → the rules-glob probe → the budget line;
- then `_expected_managed_region(home, spec)` /
  `_expected_reference_region(...)` / `_expected_pointer_region(...)` —
  **U-hostmode's own primitives, reused verbatim.** Those three functions
  exist precisely to answer "what does the ledger say must be there", and
  a dry run is that question asked one step earlier. Nothing new computes
  canon bytes.

**It writes nothing, commits nothing, takes no lock, and holds no
sentinel** — those are the discriminators `DRY3` tests. It exits **0**
when the route would succeed and **1** when a preflight refuses, with the
refusal text identical to the real run's.

`--json` payload:

```json
{"id":"lrn-…","verb":"route","dry_run":true,
 "destination":"claude-md","variant":null,"scope":"project",
 "host":"~/repos/…","mode":"git","target":"~/repos/…/CLAUDE.md",
 "region":"managed","already_present":false,
 "diff":{"added_lines":1,"removed_lines":0,"unified":"@@ …"},
 "budget":{"managed_share":0.07,"flagged":false},
 "would_refuse":[]}
```

`would_refuse` is a **list**, not a first-failure string: a dry run's
whole value is telling the human everything wrong with the sheet at once,
and a preflight that stops at the first problem re-creates the batch's
apply-time surprise.

**`self-learn show <id> [--json]`** — read-only. `--json` emits exactly
these keys *(listed here because `SHOW1` asserts "every key §4.3 lists"
and r2's §4.3 gave only prose — gate N-7)*:

```json
{"id":"lrn-…","status":"routed","scope":"project","kind":"surface-rule",
 "type":"knowledge","bucket":"projects/<slug>","created_at":"…",
 "sightings":3,"deferred_until":null,"deferred_count":0,
 "superseded_by":null,"resolution_note":null,
 "routing":{"destination":"claude-md","routed_at":"…","by":"human",
            "variant":null,"follow_up":null},
 "canon":{"destination":"claude-md","target":"~/repos/…/CLAUDE.md",
          "host":"~/repos/…","mode":"git","present":true},
 "proposal":{"present":false,"fresh":null,"destination":null,
             "already_canon":null},
 "recurrences":[],"dismissed_suspects":[],"last_confirmed":null,
 "history":[],"notes":[],
 "lifecycle":[{"sha":"abc1234","date":"2026-08-24","subject":"self-learn: route lrn-… → …"}]}
```

**`canon.present` is computed from the target file's actual content**, not
from `routing` — that is `SHOW1`'s discriminator. The human render carries
the same facts, `notes` included (`STATE8` leg 2). The lifecycle rows come
from `git -C <home> log --grep=<id> --oneline`.

**`show` takes no lock, mutates nothing, and MUST NOT join
`cli.VERB_COMMANDS`** *(r3, gate M-2)*. Measured at `b206800`:
`cli.main` runs `_flush_spool_best_effort(...)` for every command in
`VERB_COMMANDS` (`cli.py:2142-2146`), and that flush **commits** — its own
docstring says so (`cli.py:1955-1969`: *"the flush commits (H-5 —
telemetry is a producer…)"*). A read-only verb wired through that set
would move the ledger's `HEAD` whenever a spool happened to be non-empty,
contradicting `SHOW2` in a way no fixture with an empty spool could ever
see. `show` is wired like `list`/`status`/`report` — its own `_cmd_show`,
outside `VERB_COMMANDS` — and `SHOW3` pins it with a **non-empty spool**.

Like every command except `mine`/`init`, `show` ticks the miner watchdog
— **stated here because a read-only verb that can spawn a nightly run is
exactly the surprise `SHOW2` pins** (`SELF_LEARN_MINER_AUTOKICK=0`
suppresses it, same as `list`).

### 4.4 `batch`

**Sheet** (`batch.load_sheet`, YAML, schema-versioned):

```yaml
version: 1
items:
  - {id: lrn-1129a784, verb: rehome,  to: "project:~/.config", note: "…"}
  - {id: lrn-19d64bf3, verb: reject,  note: "not serious enough…"}
  - {id: lrn-d60c3365, verb: route,   dest: claude-md, by: human, note: "…"}
  - {id: lrn-b21d1969, verb: undefer}
  - {id: lrn-4e95b3a6, verb: route,   collapse: merge-1a2b3c4d}
```

Item keys are a **closed set per verb**: `id`, `verb`, and then **exactly
the keys that verb's CLI accepts** *(completed r3, gate N-9 — r2's list
omitted four `route` flags while claiming to be that rule, so a
merge-collapse route could not be expressed in a sheet at all)*:

| verb | permitted item keys beyond `id` / `verb` |
|---|---|
| `route` | `dest`, `collapse`, `by`, `follow_up`, `unblocks_on`, `follow_up_note`, `allow_empty_glob`, `note` |
| `reroute` (ph 2) | `dest`, `by`, `note` |
| `reject`, `graduate`, `undefer`, `reopen`, `confirm-held`, `followup-done` | `note` |
| `defer` | `until`, `note` |
| `supersede` | `new_id`, `note` |
| `rehome`, `rescope` | `to`, `note` |
| `note` | `append`, `key` |
| `confirm-recurrence` | `event`, `tolerate`, `note` |
| `dismiss-suspect` | `event`, `why`, `note` |
| `link-contradicts` | `target`, `note` |
| `followup add` (ph 2) | `action`, `unblocks_on`, `note` |
| `reclassify` (ph 2) | `kind`, `type`, `note` |

`no_push` is **not** an item key — the batch owns the push (one, at the
end). An unknown key, a key on the wrong verb, an unknown verb, a
malformed id, or a `version` other than `1` is **exit 64** and **nothing
runs**: a sheet is validated whole or not at all.

**Verbs permitted inside a sheet** — 15 in Phase 1: `route`, `reject`,
`defer`, `undefer`, `reopen`, `graduate`, `supersede`, `rehome`,
`rescope`, `note`, `confirm-recurrence`, `dismiss-suspect`,
`confirm-held`, `link-contradicts`, `followup-done`; **3 more in
Phase 2**: `reroute`, `followup add`, `reclassify`. **Every one of the 18
has an `already-applied` rule — §3.3b's table, which is normative.**
**Refused inside a sheet, each with its reason in the message:** any
route whose resolved destination is `hook` (S-29);
`host add|rebind|remove` (Y-17 disclosed consent); `teach`, `import`,
`mine`, `worker`, `push`, `sentinel`, `recompile`, `init`,
`proposal validate` (not record resolutions).

**Run procedure.** `sentinel.hold()` **once** → heartbeat → for each
item: classify against §3.3b, and if `already-applied` **skip without
calling the verb**; else dispatch to the same `verbs.*` function the CLI
dispatches to, with `no_push=True`, inside that verb's own
`_ledger_write` span, catching the same exception set `cli._cmd_verb`
catches and mapping it to the same integer → record `{n, id, verb, rc,
sha, state}` → on rc ∈ {5, 6, 7} **stop** → after the loop,
**`cli._mutating_epilogue(no_push=True)`** (§3.3c — the 11 §4.2 flush,
which itself commits) → one `verbs.push_pending(home)` unless
`--no-push` → `hold.release()` in a `finally`. The flush sits **inside**
the hold and **before** the push, so its own commit rides the batch's
single push instead of publishing itself.

**The sentinel count, stated precisely** *(r3, gate N-1)*: `batch` takes
**one OWNING hold** (`SentinelHold.owned is True`). Every verb it calls
then self-holds and gets `owned=False`, because `sentinel.hold()` returns
a non-owning handle when the sentinel is already live
(`sentinel.py:98-111`, verbatim: *"A LIVE sentinel already exists …
leave it untouched → `owned=False`"*). So a **correct** run makes
`N+1` calls to `sentinel.hold()` and exactly **1** of them owns. `BAT4`
asserts both numbers — the owning count is the property, the `N+1` total
is its positive control.

**`--dry-run`** runs each item's preflight only. For `route` items that
is exactly `route --dry-run` (§4.3), called as a function; for every
other verb it is the verb's own precondition set (status, target
resolution, registration) with nothing written. It additionally reports
**sheet-level** prerequisites the two hand scripts had to sequence by
hand: any target host not in `hosts.yaml`, and any item whose resolved
destination is `hook`.

**Human output** (non-`--json`) is one line per item plus a summary, and
it prints `rc=` **unpiped from the verb's own return**, never from a
shell pipeline — the discipline the hand scripts applied manually
(lrn-ea833a5b), now structural.

**Process exit code: §3.3a's decision procedure**, not a `max()`. The
envelope carries the per-item codes and, on a `3`/`4`/`7`, the list of
items that landed before the failure.

### 4.5 `reroute`, and real reference retirement (Phase 2)

**`self-learn reroute <id> --dest <TARGET> [--note] [--no-push] [--json]`**

- `require_status(..., ROUTED_ONLY, verb="reroute")`.
- Refuse when the new destination (with qualifier) equals the current one
  — *"already routed to `reference:LEARNINGS.md` — nothing to change"*.
  That is the idempotency refusal, and it names the state.
- Refuse `--dest hook` and `--dest new-skill`: both are
  `ONE_MOTION_UNROUTABLE`-class one-way motions (a hook writes an
  executable and needs a validated hook proposal with a fresh
  `record_sha`; `new-skill` creates a directory). Rerouting *into* them
  is a fresh `route` decision on a fresh record. Rerouting *away from*
  them is supported — the retirement half already exists for both.
- **Both** preflights run before the lock: `_resolve_target` for the new
  destination and `_retirement_preflight` for the old.
- Under `_ledger_write`: append the old `routing` block to `history` as
  `event: routing`; write the new `routing` (`routed_at` = now,
  `destination`, `by` = `human` unless `--by`); commit
  `self-learn: reroute lrn-… → <new-target>`.
- Host phase, inside the same span (U-hostmode §4.5b): retire the old
  target via `_retirement_host_phase`, compile the new via `_host_phase`,
  with `skip_target` short-circuiting when both resolve to the same file.
- `--json` envelope, same shape as `route`'s.

**Reference retirement, made real.** `compilers.retire_reference(
references_dir, record_id, *, dest=None) -> ReferenceResult` removes the
block whose heading matches `^## \S+ — <record_id>\s*$` through the line
before the next `^## ` (or EOF), collapses the resulting blank run to one
blank line, and returns `applied=False` when no such block exists
(idempotent). **`_Retirement` gains a THIRD field and `_retirement_host_phase` a THIRD
arm** *(specified r3, gate D-4 — r2 said only "carrying the references
path", but the shipped dataclass has exactly two fields and a docstring
pinning "At most one of the two is set", `verbs.py:2592-2601`)*:

```python
@dataclass(frozen=True)
class _Retirement:
    """… At most one of the THREE is set; all None means the record has
    no host presence to clean (pending, or a destination this build does
    not track)."""
    spec: TargetSpec | None = None
    removal: tuple[Path, Path, str, str] | None = None
    #: U-verbs: the resolved references FILE whose `## <day> — <id>` block
    #: must be removed, plus the spec that resolved it (the host phase
    #: needs `host_path`/`mode` for `gitops.host_lock` and the compile
    #: record). Set ONLY for `destination == "reference"`.
    reference: tuple[Path, TargetSpec] | None = None
```

`_retirement_preflight`'s `reference` branch resolves the file through
`compilers.reference_target_path(refs_dir, ref_name)` — the one mapping,
already used by the write leg, `recompile` and the drift check — and
returns `_Retirement(reference=(path, spec))`.
`_retirement_host_phase` gains the matching third arm, after the existing
`spec` and `removal` arms and in the same shape (take
`gitops.host_lock(spec.host_path, spec.mode)`, call
`compilers.retire_reference`, write the compile-record entry, return
`(host_sha, spec.host_path)`). The docstring's "at most one of the two"
becomes "at most one of the three". So **`graduate`, `supersede` and
`reroute` all clean up together**, through the one shared retirement
path, with no per-verb branch.

The retirement also writes a `region: reference` compile-record entry via
U-hostmode's `_write_generic_region_entry`, exactly as the reference
*write* leg already does at `verbs.py:3380-3400`.

### 4.6 `host remove` and `bucket prune` (Phase 2)

**`host remove <path> [--gate-only]`.** Before the lock,
`hosts.records_targeting(home, path) -> list[str]` walks
`discover_buckets`, keeps `status == "routed"` records whose bucket
resolves to that host (project legs) or whose scope resolves into that
skills root (skills-root leg), and returns their ids. Non-empty and no
`--gate-only` → `VerbError` (exit 1):

> `host remove ~/repos/foo: 4 routed record(s) still compile into this
> host (lrn-…, lrn-…, lrn-…, lrn-… and 0 more). Deregistering it would
> leave that canon unmanaged — `recompile` will WARN and skip it.
> Repairs: move them first (`self-learn rehome <id> --to <target>`), or
> pass --gate-only to close the compile gate anyway.`

With `--gate-only`: today's behaviour, plus a `post_notes` line naming
the count and the consequence. The `.self-learn-host` marker is left in
place (U-hostmode GATE5, unchanged).

**`self-learn bucket prune [--dry-run] [--no-push]`.** Removes every
bucket directory under `projects/`, `skills/` and `user/` that contains
**no** `lrn-*.md` in `pending/` or `resolved/`, **no** file in
`proposals/`, and nothing but `meta.yaml` and empty dirs otherwise. One
ledger commit `self-learn: bucket prune <n> empty bucket(s)`; `--dry-run`
prints the list and writes nothing. Refuses to prune the `user/` bucket
at all (it is the one bucket that must always exist).

### 4.7 `followup add` and `reclassify` (Phase 2)

**`self-learn followup add <id> --action TEXT [--unblocks-on GATE]
[--note TEXT] [--no-push]`** — `require_status(..., ROUTED_ONLY,
verb="followup add")`; refuses when `routing.follow_up` is already open
(*"lrn-… already has an open follow-up: <action> — `followup done` clears
it first"*); validates through the shipped `records._validate_follow_up`;
writes `routing.follow_up`; commit `self-learn: follow-up add lrn-…`
(matching the existing `self-learn: follow-up done lrn-…` subject
family). This is the verb that `daad648`'s hand commit (2026-07-14) did
by hand.

**`self-learn reclassify <id> [--kind K] [--type T] [--note]`** — at
least one of the two required (else 64).

- `--kind` ∈ `records.KINDS` = `{anti-pattern, surface-rule,
  reasoning-pattern}`: **every status**, because 02 §2 says *"`scope`/
  `kind` (triage may re-classify — the filing is never frozen)"*.
- `--type` ∈ `records.TYPES` = `{behavior, knowledge}`:
  `require_status(..., LIVE_STATUSES, verb="reclassify --type")`,
  because the same paragraph freezes `type` at routing. A `--type` change
  **re-validates the required body sections** through the shipped
  `records.REQUIRED_SECTIONS` map (`behavior` → `Trigger`+`Instruction`,
  `knowledge` → `Fact`) and refuses (exit 1) naming the missing headings
  — the record is not rewritten to fit.
- One commit `self-learn: reclassify lrn-…`; a `--kind`-only change on a
  routed record touches no host (kind is not compiled).

### 4.8 The producer `--json` envelopes

`worker kick|run --json` and `mine run --json` each print exactly one
JSON object and nothing else, in `cli._cmd_worker` / `cli._cmd_mine`.
Keys: `command`, `outcome` (the library's own status/outcome string,
never a re-derived label), `ok` (bool — `outcome not in {"failed",
"landed-uncommitted"}`), plus the counts the human line already prints.
**Exit codes are byte-unchanged**, which `PROD3` pins as a negative
criterion.

### 4.9 UI parity (Phase 2)

**POST-surface parity, unbounded.** `_VERB_LABELS` gains
`dismiss-suspect` ("Dismiss suspect"), `rescope` ("Change scope"),
`supersede` ("Supersede"), `confirm-held` ("Still holding"), and (Phase 2
of this unit) `reroute` ("Re-route"), `reopen` ("Reopen"), `undefer`
("Un-defer"). `_KNOWN_VERBS` = `frozenset(_VERB_LABELS) - {"rehome"}`
picks them up automatically, and `build_argv` gains one branch each,
matching `cli.py`'s parser verbatim.

**Keyboard parity, bounded to four free letters** (§2.8). Two are spent,
both on cards that already exist so no new page is introduced:

| key | action | card | why this card |
|---|---|---|---|
| `k` | `dismiss_suspect` | `holding` (`action_bar.html:121`) | the card already offers Tolerate/Confirm/Graduate; Dismiss is the fourth resolution `commands/review.md:219` already documents, and the UI is the only surface that lacks it |
| `m` | `confirm_held` | `resolved` (`action_bar.html:156`, `status == "routed"` only) | the verb with **0 uses ever** (§2.1) and `last_confirmed` present on **0** records — the staleness metric is unfed because the surface a human actually reviews on has no way to feed it |

The `last_confirmed` zero, with its command and a positive control
*(added r3, gate M-8 — §0 requires both and r2 gave neither)*:

```
$ grep -l 'last_confirmed' ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md 2>/dev/null | wc -l
0
$ grep -l '^status: '      ~/.self-learn/{user,skills/*,projects/*}/{pending,resolved}/lrn-*.md 2>/dev/null | wc -l
152
```

The control proves the glob reaches all 152 records, so the `0` is an
absence and not a mis-typed path.

The card line numbers, re-measured at `b206800`
(`grep -n 'elif kind ==' ui/templates/partials/action_bar.html`):
`holding` **:121**, `followup` :141, `contradicts` :150, `resolved`
**:156**, `adopt` :188 *(r2 wrote `:155`; one line off)*.

`l` and `z` stay free, deliberately: `reroute`, `reopen`, `undefer`,
`rescope` and `supersede` are **corrections**, reached through the
generic arm-then-confirm POST path from a form, not from a hot key on a
page the human is skimming. **FW-136** records that the keymap is now
four letters from full and that the next verb needing a key forces a
context-scoped dispatch (which `keymap.py`'s own docstring says app.js
does not do today: *"app.js dispatches on the FIRST key match with no
context filter"*).

**The staleness notice already covers the new move legs.**
`routes.NOTICE_PROPOSAL_MOVED` fires when a CLI-side move changes a
record's bucket while a proposal is waiting or armed. It keys on *the
bucket changed*, not on which direction, so every new leg inherits it
with no code change — `UIP5` asserts that positively rather than assuming
it.

### 4.10 The `history` / `notes` schema keys

`records.py` gains:

- `Record.history` / `Record.notes` properties (default `[]`);
- `Record.append_history(event, payload)` — `event` in the closed set
  `{"resolution", "routing"}`, stamps `at` in UTC ISO, **appends only**;
- `Record.append_note(text, *, by="human", key=None)` — stamps `at`,
  appends; `key` is the optional idempotency key (§4.2), stored on the
  entry and **never** generated by the record layer *(r4, gate N-1r2: r3
  specified `--key` in §4.2/§3.3b but left it out of both the signature
  and the schema, so `batch` would write verb-written frontmatter that no
  schema sentence describes)*;
- `Record.note_has_key(key) -> bool` — the read `batch` classifies on
  (§3.3b row 10);
- `Record.clear_resolution_note()` — sets `resolution_note` to `None`,
  and **raises unless** the current note already appears in a `history`
  entry with `event: "resolution"`. That precondition is what makes the
  write-once field safe to clear: the note cannot be destroyed, only
  displaced;
- validator clauses in `_validate_frontmatter`: both keys are `null` or a
  list of mappings; every entry has an ISO `at`; every `history` entry
  has an `event` in the closed set; nothing else is enforced (same
  posture as `recurrences`).

02 §2 gains one amendment paragraph (§11.3).

---

## 5. Criteria

Each criterion: **ID · phase · statement · check command · mutation.**
**[A]** = Phase 1, **[B]** = Phase 2. No code exists yet, so every
mutation cell is `predicted` unless marked **MEASURED** (those were read
off, or applied to, shipped code during this spec's census).

Every new test lives in `cli/tests/test_u_verbs.py` or
`ui/tests/test_u_verbs.py` — **two new files**, so that no
`_ARMOR_SHAS`-pinned file moves (§2.9). The single exception is the one
declared rewrite in `test_rehome.py` (§7).

### 5.0 The two phases, and the proof Phase 1 lands alone

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **PH1** | [A] | Phase 1 references **no** Phase-2 symbol: `reroute`, `retire_reference`, `records_targeting`, `bucket prune`, `followup add`, `reclassify` and the new UI labels appear nowhere in the Phase-1 tree | `grep -rnE '\breroute\b\|retire_reference\|records_targeting\|bucket_prune\|followup_add\|reclassify' plugins/self-learn/cli/src plugins/self-learn/ui/src` returns **0**, `rc` captured **unpiped**. Positive control: the same grep for `require_status` returns ≥ 12 | add any Phase-2 symbol to a Phase-1 module ⇒ PH1 red · `predicted` |
| **PH2** | [A] | Phase 1 writes to **no host**, and the snapshot names the verbs it drives *(r3, gate D-1)*: `undefer`, `reopen`, `note`, `rehome`, `rescope`, `show`, `route --dry-run`, and **`batch` with a one-line sheet whose single item is `undefer`**. `route` (real) and `batch` sheets containing a `route` item are **excluded by construction** — they write a host by design, which is the boundary, not an exception | `pytest -k test_phase1_touches_no_host` — a fixture with a registered host runs those eight, then asserts the HOST tree's `sha256 + mtime` snapshot is unchanged. Positive control **first**: the same fixture running a real `route` DOES change it. The `batch` leg is the discriminating one — a `batch` that reached `_host_phase` for a non-route item would redden here and nowhere else | make `undefer` call `_host_phase` ⇒ PH2 red on both the direct and the `batch` leg · `predicted` |

### 5.1 GUARD — one vocabulary, extended

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **GUARD1** | [A] | `verbs.py` contains **zero** hand-rolled status refusals: every record-verb's precondition is a `require_status` call | AST check, `pytest -k test_no_handrolled_status_check`: walk `verbs.py`, find every `raise VerbError` whose message contains the literal `status`, assert each is inside a function that also calls `require_status`. **Positive control, asserted first**: the same walk against `b206800`'s bytes (a fixture copy) reports exactly **2** violations, at `rehome` and `rescope` | re-introduce either hand-rolled check ⇒ GUARD1 red · **MEASURED** pre-state (§2.2: `verbs.py:4281`, `:4467`) |
| **GUARD2** | [A] | `REOPENABLE_STATUSES` and `DEFERRED_ONLY` are exported frozensets in `ledger_ops`, and `reopen`/`undefer` pass **those** constants, not literals | `pytest -k test_new_status_sets_are_constants` + `grep -n 'frozenset({"rejected"})\|frozenset({"deferred"})' cli/src/self_learn/verbs.py` returns 0 | inline `frozenset({"rejected"})` at the `reopen` call site ⇒ GUARD2 red · `predicted` |
| **GUARD3** | [A] | Every new verb refuses **on status, never mere existence**: given an id that exists in the wrong status, each returns **1** with a message naming the record AND its actual status — never 64 "not found" | `pytest -k test_new_verbs_refuse_on_status` — parametrised over `{undefer, reopen, note, rehome, rescope}` × the statuses each rejects; asserts `rc == 1` and `f"is {status!r}"` in stderr. Positive control: an id that does **not** exist returns 64 | swap any `require_status` for `find_record_path(..., statuses=("pending",))` ⇒ GUARD3 red (64, "not found") · `predicted` |
| **GUARD4** | [A] | Every new mutating verb is **safe to re-run**: a second invocation either is a no-op with rc 0 or refuses with rc 1 naming the state — never a partial write, never a traceback | `pytest -k test_new_verbs_rerun_safe` — parametrised over every new verb; runs it twice, asserts the second rc ∈ {0, 1}, asserts the ledger tree hash after run 2 equals after run 1 when rc == 1 | make `undefer` skip its `require_status` ⇒ the second run rewrites `status` and re-commits ⇒ GUARD4 red on the tree-hash leg · `predicted` |

### 5.2 MOVE — one filing-move operation, all nine cells

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **MOVE1** | [A] | All eight non-identity cells of the (user, skill, project) matrix move a pending record, in one commit, with the record's `scope:` correct at the destination and its bucket matching `bucket_dir_for_scope(scope)` — **plus a ninth leg: the mismatch repair** *(added r4, gate M-1r2)*. Leg 9: a pending record sitting in a **project** bucket whose frontmatter wrongly says `scope: user` is moved **project→project**, and ends with `scope: project`. This is the only leg on which §3.2a step 5's **unconditional** write and `M78`'s added bucket-equality condition give different answers *(reworded r6, gate N-2r4: r5 still called it "the leg step 5's condition decides" though step 5 no longer has a condition; the check and mutation cells were already correct)* | `pytest -k test_move_matrix` — 9 parametrised legs (the 8 cells plus `project→project (mismatch repair)`), each asserting the destination path, the `scope:` literal, and `git log -1 --format=%s`. *(r5, gate M-2r3: r4 attached a byte-identity control here claiming it would kill "rewrite unconditionally". It cannot — `Record.write` is a byte-perfect round-trip, measured by the gate on four real ledger records: `set_scope(record.scope)` then `write()` leaves the file byte-identical. Unconditional and field-conditioned are behaviourally **equivalent**, so §3.2a now specifies the simpler of the two — write unconditionally — and the control is deleted rather than left as a check that can never fire.)* | drop the `set_scope` call from `move_record` ⇒ MOVE1 red on the six cross-family legs **and leg 9** · `predicted`. `M78` (make the write conditional on **bucket** equality, so it is skipped whenever source and target buckets share a scope) ⇒ **MOVE1 leg 9 only** — all eight cell legs stay green, which is exactly why the leg is owed · `predicted`. **MEASURED context**: 1 of 152 live records has this defect (§3.2a, FW-138) |
| **MOVE2** | [A] | `meta.yaml` is stamped **iff** the target is a project bucket, and the SOURCE bucket's `meta.yaml` is never removed | `pytest -k test_move_meta_yaml_iff_project` — the 8 legs again; asserts `(target/"meta.yaml").exists() == (target_scope == "project")` and that the source's survives | stamp unconditionally ⇒ MOVE2 red on the four non-project targets (a `user/meta.yaml` appears) · `predicted` |
| **MOVE3** | [A] | `ledger_ops.rehome_record` and `ledger_ops.rescope_record` **no longer exist**; `move_record` is the only file-op | `grep -c 'def rehome_record\|def rescope_record' cli/src/self_learn/ledger_ops.py` = 0, `rc` unpiped; `pytest -k test_move_record_is_the_only_fileop` | keep `rescope_record` as a shim ⇒ MOVE3 red · `predicted` |
| **MOVE4** | [A] | The reserved literals win over paths: with a project host registered at a directory literally named `user`, `--to user` moves to the USER bucket, while `--to project:user` and `--to ./user` both move to that project bucket | `pytest -k test_move_reserved_literals_beat_paths` — three assertions on one fixture | resolve paths before literals ⇒ MOVE4 red on leg 1 (the record lands in the project bucket) · `predicted`. **MEASURED anchor**: 12/12 live slugs match `^-.+-[0-9a-f]{8}$`, so no *registered* project can collide (§2.3) |
| **MOVE5** | [A] | `rehome`'s commit subject for a **project** target is byte-identical to today's, `self-learn: rehome lrn-… → projects/<slug>` | `pytest cli/tests/test_rehome.py -k pinned_subject` (the **shipped** test at `:106`, unchanged) + `pytest -k test_move_subjects` for the three dest-label arms | make the subject `→ <slug>` (drop `projects/`) ⇒ the shipped test reddens · **MEASURED** as a live pin (`test_rehome.py:106`) |
| **MOVE6** | [A] | The proposal sweep is **disclosed on both verbs**: a `rehome` that swept a proposal emits the `swept … will be re-analyzed in <dest>` post-note and the `swept: <relpath>` commit-body lines | `pytest -k test_rehome_discloses_the_sweep`. Positive control **first**: the same assertion against `b206800`'s `rehome` (fixture copy) shows **no** post-note | drop the `post_notes` from the `rehome` path ⇒ MOVE6 red · **MEASURED** pre-state (`verbs.rehome` at `b206800` returns `VerbResult` with no `post_notes`) |
| **MOVE7** | [A] | Both verbs refuse identically, each refusal on status or on the target, never on existence: unknown id → 64; resolved record → **1** naming the status; unregistered project target → 1 naming `host add`; unknown skill → 1 naming `--skills-root`; same bucket → 1; id already in the target bucket → 1 | `pytest -k test_move_refusals` — 6 legs × 2 verbs | replace the collision check with an overwrite ⇒ MOVE7 red on the collision leg (and the target record's bytes change) · `predicted` |
| **MOVE8** | [A] | A **deferred** record moves and stays deferred, with `deferred_until` and `deferred_count` intact, on every leg | `pytest -k test_move_preserves_deferral` | reset `deferred_count` on move ⇒ MOVE8 red · `predicted` |
| **MOVE9** | [A] | The agent-proposal intake is narrow on the **target** and open on the **source** *(rewritten r3, gate M-4)*. Leg (a): `proposals.validate_proposal`'s `rehome` branch still refuses `to: user` / `to: skill:<name>` with a message naming `rationale`. Leg (b): **a `user`-scoped (and a `skill:`-scoped) pending record CAN be proposed to a registered project target** — the source-scope refusal at `proposals.py:354-358` is gone, and the verb's `require_status` is the one guard. Leg (c): the unregistered-target and same-bucket refusals are byte-unchanged | `pytest -k test_proposal_to_refuses_scope_literals` and `test_proposal_accepts_user_scoped_record_for_project_target` (ui). **Positive control, asserted first**: the same leg-(b) call against `b206800`'s branch text is REFUSED — that is the shipped behaviour this criterion changes | restore the `location.scope != "project"` refusal ⇒ MOVE9 leg (b) red — and §11.5's doctrine amendment becomes unobeyable, which is the finding · **MEASURED** pre-state (`proposals.py:354-358`, quoted in §4.1) |
| **MOVE10** | [A] | **Two entry points, ONE implementation (ruling R1).** Neither `verbs.rehome` nor `verbs.rescope` contains a file-op of its own: within each function body there is **no** `git mv`, no `Path.rename`, no `record.write(`, no `set_scope(`, no `ensure_project_meta(` and no `remove_proposal_siblings(` — every one of those reaches the disk only from `ledger_ops.move_record`. Both bodies must call `_move`, and `_move` must call `move_record` | AST check, `pytest -k test_move_has_one_implementation`: parse `verbs.py`, take the `rehome` and `rescope` function nodes, assert the forbidden call/attribute set is **empty** in each and that each contains a call to `_move`; then assert `move_record` is the only name `_move` calls from `ledger_ops` for the file move. **Positive control, asserted first**: the same walk against the `b206800` fixture copy reports the forbidden set **non-empty in both** (`rehome_record` / `rescope_record` call sites) | reintroduce a divergent write in one verb — e.g. give `rescope` back its own `record.set_scope(...)` + `git mv` and leave `rehome` on `move_record` ⇒ MOVE10 red **while every behavioural MOVE test stays green**, which is the point · `predicted` (pre-state **MEASURED**: two file-ops, §2.3 Finding V-2) |

### 5.3 STATE — reopen, undefer, note, and the past-date refusal

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **STATE1** | [A] | `defer --until <yesterday>` exits **1**, names today's date, and names `undefer`; nothing is written | `pytest -k test_defer_past_date_refuses`; asserts rc 1, both substrings, and an unchanged ledger tree hash | keep the shipped behaviour (no date check) ⇒ STATE1 red · **MEASURED** pre-state: `ledger_ops.defer_record` (`:2590`) has no date comparison at `b206800` |
| **STATE2** | [A] | `defer --until <today>` is **accepted** (rc 0) and the record is immediately eligible in `list --json` without `--include-deferred` | `pytest -k test_defer_today_is_accepted` | make the refusal `<= today` ⇒ STATE2 red · `predicted` |
| **STATE3** | [A] | `undefer` moves `deferred → pending`, clears `deferred_until`, **keeps `deferred_count`**, commits `self-learn: undefer lrn-…`, and writes no `resolution_note` | `pytest -k test_undefer` | clear `deferred_count` too ⇒ STATE3 red · `predicted` |
| **STATE4** | [A] | `reopen` moves `rejected → pending` with a `git mv` out of `resolved/`, and the old `resolution_note` survives verbatim in `history[0]` with `event: "resolution"` | `pytest -k test_reopen_preserves_the_note` — asserts the file's new path, `status`, `resolution_note is None`, and `history[0]["note"]` equal to the original string | drop the `append_history` call ⇒ **`clear_resolution_note` raises** and reopen fails loudly; assert that too — a silent loss must be impossible · `predicted` |
| **STATE5** | [A] | `Record.clear_resolution_note()` **refuses** unless the note is already in `history`; it is the only writer that may clear the field | `pytest -k test_clear_resolution_note_needs_history` + `grep -c 'resolution_note.*= None' cli/src/self_learn/*.py` limited to that one method | drop the precondition ⇒ STATE5 red · `predicted` |
| **STATE6** | [A] | `reopen` refuses `superseded` and `routed`, each naming the status AND the reason (a live successor / FW-133) | `pytest -k test_reopen_refuses_terminal` | widen `REOPENABLE_STATUSES` to `RESOLUTION_STATUSES` ⇒ STATE6 red · `predicted` |
| **STATE7** | [A] | `reopen` sweeps a stale proposal sibling and **discloses** it, same shape as the move | `pytest -k test_reopen_sweeps_and_discloses` | carry the proposal instead ⇒ STATE7 red · `predicted` |
| **STATE8** | [A] | `note <id> --append TEXT` appends to `notes[]` in **any** status, never touches `resolution_note`, and is secret-scanned. **Second leg (ruling R5): the note comes back out.** The same appended text appears in `show <id> --json` under `notes[]` **and** in `show <id>`'s human render — the key has exactly one reader from the day it has a writer | `pytest -k test_note_append` — 5 statuses × 1 assertion, plus a leg whose text trips `scan.scan()` and asserts rc 1 with nothing written; then `pytest -k test_note_round_trips_through_show` — append a distinctive string, assert it in both `show` outputs | write into `resolution_note` when it is empty ⇒ STATE8 red (leg 1) · `predicted`. Drop the `notes` rendering from `show` ⇒ STATE8 red (leg 2) · `predicted` |

### 5.4 DRY — the preview surfaces

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **DRY1** | [A] | `route --dry-run` renders the exact bytes the real route would write: for a fixture record, the dry run's `diff.unified` applied to the target's current content equals the content after the same route runs for real | `pytest -k test_dry_run_matches_the_real_write` — dry-run first, real route second, byte comparison. **This is the unit's isolator**: a preview that is not the real bytes is worse than no preview | compute the diff from the *proposal* instead of from `_expected_managed_region` ⇒ DRY1 red · `predicted` |
| **DRY2** | [A] | `route --dry-run` reuses U-hostmode's `_expected_*_region` helpers — no second canon-byte computation exists | `grep -c '^def _expected_' cli/src/self_learn/verbs.py` = **3** — `_expected_managed_region` (`:587`), `_expected_reference_region` (`:721`), `_expected_pointer_region` (`:750`), unchanged from `b206800`; `pytest -k test_dry_run_delegates_to_expected_region` (monkeypatches `_expected_managed_region` to a sentinel and asserts it appears in the output) | hand-roll a second compile in the dry-run path ⇒ DRY2 red · `predicted` |
| **DRY3** | [A] | `route --dry-run` **writes nothing, commits nothing, takes no ledger lock and holds no sentinel** | `pytest -k test_dry_run_writes_nothing` — snapshots `sha256 + mtime` of every file under the ledger home AND the host, asserts unchanged; asserts `sentinel.is_live()` is False throughout (`sentinel.py:68` — there is no `state` symbol; *CORRECTED-r3, gate N-2*); monkeypatches `_ledger_write` to raise. **Positive control first**: the same fixture without `--dry-run` changes both trees | let the dry run take the lock "for consistency" ⇒ DRY3 red on the monkeypatch leg · `predicted` |
| **DRY4** | [A] | `would_refuse` is a **list of every** failed preflight, not the first — a record failing both the ALWAYS gate and the host-registration gate reports two entries | `pytest -k test_dry_run_reports_every_refusal` | `return` at the first refusal ⇒ DRY4 red (1 entry, not 2) · `predicted` |
| **SHOW1** | [A] | `show <id> --json` carries every key §4.3 lists — **`history` and `notes` included** (ruling R5) — with `canon.present` computed from the target file's actual content (not from `routing`) for a routed record | `pytest -k test_show_json_shape` + a leg that hand-deletes the entry from the target and asserts `canon.present == false` while `routing.destination` is unchanged | read `present` off `routing` ⇒ SHOW1 red on the hand-delete leg · `predicted` |
| **SHOW2** | [A] | `show` mutates nothing and takes no lock; its miner-watchdog tick is **documented in `--help`** and suppressed by `SELF_LEARN_MINER_AUTOKICK=0` | `pytest -k test_show_is_read_only`; `self-learn show --help` contains `SELF_LEARN_MINER_AUTOKICK` | drop the help sentence ⇒ SHOW2 red · `predicted` |
| **SHOW3** | [A] | **`show` on a ledger with a NON-EMPTY telemetry spool leaves `HEAD` unchanged** *(new r3, gate M-2)*. `show` is not in `cli.VERB_COMMANDS`, so `cli.main` never runs `_flush_spool_best_effort` for it — and that flush **commits** (`cli.py:1955-1969`'s own docstring: *"the flush commits (H-5 — telemetry is a producer…)"*), dispatched at `cli.py:2142-2146` for every member of that set | `pytest -k test_show_does_not_flush_the_spool`: spool ≥1 telemetry event (`telemetry note offer-declined`), record `git rev-parse HEAD`, run `self-learn show <id>`, assert `HEAD` **identical** and the spool file still non-empty. **Positive control, asserted first**: the same fixture running `self-learn reject <id>` (a `VERB_COMMANDS` member) DOES move `HEAD` and DOES drain the spool — so the test can see a flush when one happens. Plus a static leg: `"show" not in cli.VERB_COMMANDS` | `M75` (add `show` to `VERB_COMMANDS`) ⇒ SHOW3 red on both legs — **and an empty-spool fixture would never have seen it**, which is why the spool is seeded · `predicted`. **MEASURED**: `VERB_COMMANDS` is a 10-name closed set at `cli.py:1997-2010`; `show` joining it is a one-line edit |

### 5.5 BATCH — one executor

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **BAT1** | [A] | A whole sheet is validated **before anything runs**: an unknown verb, an unknown item key, a malformed id, or `version != 1` exits **64** with nothing written | `pytest -k test_batch_validates_whole_sheet` — 4 legs, each asserting rc 64 and an unchanged ledger tree hash, with a VALID item ahead of the bad one so "nothing ran" is observable | validate lazily, per item ⇒ BAT1 red (the valid leading item committed) · `predicted` |
| **BAT2** | [A] | The process exit code is **§3.3a's decision procedure**, and the two legs that discriminate it from a raw `max()` are tested *(rewritten r3, gate M-1: r2's two legs — `{0,1,3}`→3 and `{0,7,1}`→7 — give the **identical** answer under raw `max()`, so `test_batch_exit_severity` stayed GREEN on `M30`; the mutation's own cell named the discriminating case and the criterion omitted it)* | `pytest -k test_batch_exit_severity`, five legs: **`{3,6}` ⇒ 3** and **`{4,6}` ⇒ 4** (raw max gives 6 for both — the inversion, a ledger that changed reported as one that did not); `{6,1}` ⇒ 6 (both rules agree; the leg pins that a pre-mutation failure outranks a refusal); `{0,1,3}` ⇒ 3; `{0,7,1}` ⇒ 7. **`{3,6}` and `{4,6}` are the only pairs where the two rules disagree** *(CORRECTED-r4, gate N-3r2: r3 named `{6,1}`, which **agrees** — both rules give 6, as that leg's own cell says — and missed `{4,6}`, which disagrees (procedure 4, raw `max()` 6) and is now a fourth leg. The `{6,1}` leg stays, as a non-discriminating pin that a pre-mutation failure outranks a refusal.)* | `M30` (raw `max()`) ⇒ BAT2 red on the `{3,6}` **and `{4,6}`** legs · `predicted` |
| **BAT11** | [A] | **The 11 §4.2 flush rule is written in exactly ONE place, and every dispatch that may commit is on it** *(rewritten r5, gate M-1r3 + N-1r3)*. Three legs. **(a)** `_flush_spool_best_effort` has **exactly one caller** in `cli.py`, and it is `cli._mutating_epilogue`. **(b)** `_mutating_epilogue`'s **call SITES** — not enclosing functions — are exactly §3.3c's seven-row table, read from the spec as data. **(c)** The two shipped tests that guard the rewiring stay green | **(a)** AST check, `pytest -k test_flush_has_one_caller`: parse `cli.py`, count `Call` nodes naming `_flush_spool_best_effort`, assert **1** and that its enclosing function is `_mutating_epilogue`. **Positive control, MEASURED at `b206800`: SIX** (`:1949` `_cmd_report`, `:2135` teach, `:2145` VERB_COMMANDS, `:2150` followup, `:2155` link, `:2189` import). **(b)** `pytest -k test_epilogue_callers_match_the_spec`: collect every `Call` node naming `_mutating_epilogue` across `cli.py` + `batch.py` as `(module, enclosing_function, lineno)` and assert the **site count** equals `len(EXPECTED_EPILOGUE_SITES)` — a module-level list transcribed from §3.3c — and that the `(module, function)` multiset matches, `_main` appearing **five** times. Counting sites, not names, is what makes a second epilogue call added inside `_main` redden (N-1r3: r4 compared a *set* of function names, so a sixth `_main` call passed). **(c)** `pytest cli/tests/test_lifecycle_cli.py -k "flushes_spool or emits_capture"` — `test_resolution_verb_flushes_spool_but_never_commits_telemetry` (`:236`, drives the `VERB_COMMANDS` branch, the exact site rewired, and asserts the spooled event reached the tracked plane) and `test_teach_emits_capture_event` (`:249`) | `M79` (drop the epilogue call from `batch.run`) ⇒ **(b)** red at 6 sites ≠ 7, **and BAT10 leg (a)** red at 3 commits instead of 4 · `predicted`. Leave any one `_main` branch on the raw helper ⇒ **(a)** red at 2 · `predicted`. Rewire the `VERB_COMMANDS` branch wrongly, **split by which half fails** *(r6, gate N-3r4)*: **the flush LOST** ⇒ **(c)** red — the one leg backed by a **shipped** test rather than a new one. **The raw call LEFT as well as the epilogue added (a double flush)** ⇒ **(a)** red at 2 callers, **not (c)**: measured, `test_lifecycle_cli.py:236` stays GREEN, because the second flush finds an empty spool and `telemetry._commit_flush` early-returns, and `support.py`'s `last_verb_sha`/`verb_subject` (`:99-115`, whose docstring says so: *"The newest commit that is NOT a telemetry-flush commit"*) deliberately skip telemetry-flush commits, so both of its assertions still hold. The criterion discriminates as a whole because (a) covers exactly what (c) cannot · `predicted` |
| **BAT10** | [A] | **The applied+refused mix exits `8`, never `1`** *(new r3, ruling M-6)*. A sheet of 4 items where 3 apply and 1 refuses exits **`EXIT_BATCH_PARTIAL = 8`**; the `--json` envelope carries `summary.applied == 3`, `summary.refused == 1`, and each item's own rc. A sheet where **every** item refuses and **no** commit landed exits **`1`** — `1`'s ratified meaning ("refused, nothing written") is preserved exactly | `pytest -k test_batch_partial_exit`, three legs: (a) 3 applied + 1 refused, **with the telemetry spool SEEDED** ⇒ rc 8, envelope counts, and `git rev-parse HEAD` moved by exactly **4** commits — 3 item commits **+ 1 flush commit** (§3.3c; the flush commits, `cli.py:1955-1969`). *(r4, gate M-4r2: r3 asserted "exactly 3", true only if `batch` never flushes. The **seeded** form is the one tested, because an empty spool moves `HEAD` by 3 whether the epilogue runs or not and so cannot see `M79`.)*; (b) 0 applied + 2 refused ⇒ rc 1 and `HEAD` **unchanged**; (c) 4 applied + 0 refused ⇒ rc 0. **Positive control for (b)**: the same two items on a sheet that also carries one applying item ⇒ rc 8, proving leg (b)'s `1` comes from "nothing landed" and not from "a refusal exists" | `M74` (return `1` on the mix, r2's rule) ⇒ BAT10 leg (a) red — and the run that wrote 3 commits reports the integer meaning "nothing was written" · `predicted` |
| **BAT3** | [A] | The run **stops** on the first 5/6/7 and **continues** past a 1 | `pytest -k test_batch_stop_and_continue` — two sheets; asserts `summary.stopped_at` is the failing item's index for the 7 sheet and `null` for the refusal sheet, and asserts the later items ran / did not run accordingly | stop on 1 too ⇒ BAT3 red on the refusal sheet · `predicted` |
| **BAT4** | [A] | The batch takes **exactly one OWNING sentinel hold** for the whole run and releases it in a `finally`, even when an item raises *(corrected r3, gate N-1: r2 counted `sentinel.hold` CALLS and asserted 1, which a **correct** batch fails — every verb self-holds, and `sentinel.hold()` returns `owned=False` on a live sentinel, `sentinel.py:98-111`)* | `pytest -k test_batch_holds_sentinel_once` over an N-item sheet: (a) **owning** holds (`SentinelHold.owned is True`) == **1**; (b) **total** `sentinel.hold()` calls == **N+1** — the positive control proving the verbs really do self-hold and (a) is measuring the right thing; (c) a leg where item 2 raises asserts the sentinel file is gone at exit | hold-and-own per item ⇒ BAT4 red on (a) with N owning holds · `predicted`. Assert total==1 instead ⇒ red on correct code, which is why (b) is stated separately |
| **BAT5** | [A] | Every item runs `no_push=True` and **one** `push_pending` runs at the end (zero under `--no-push` / `--dry-run`) | `pytest -k test_batch_pushes_once` — counts `verbs.push_pending` calls across three flag combinations | let items push ⇒ BAT5 red · `predicted` |
| **BAT6** | [A] | A route item whose resolved destination is `hook` is **refused** (rc 1 for that item, sheet continues), and `--dry-run` names it as a sheet-level blocker | `pytest -k test_batch_refuses_hook_routes` — S-29's hard floor | allow it ⇒ BAT6 red · `predicted` |
| **BAT7** | [A] | `host add|rebind|remove` inside a sheet is a **sheet-validation** failure (rc 64, nothing runs), and `--dry-run` reports an unregistered target host as a prerequisite | `pytest -k test_batch_refuses_host_verbs` + `test_batch_dry_run_names_unregistered_hosts` — the 08-25 script's hand-sequenced `host add` (§2.4) is the motivating case | accept `host add` as an item ⇒ BAT7 red · `predicted` |
| **BAT8** | [A] | **Re-running an applied sheet applies 0 items and exits 0**, with the ledger's `HEAD` unchanged — for a sheet exercising **all 15** Phase-1 permitted verbs, not a convenient subset *(widened r3, gate M-5: r2's `sheet_mixed` contained none of the four verbs whose fall-through broke the property — `note` appended a second entry, and `link-contradicts` / `followup-done` / `confirm-held` returned rc 1 instead of `already-applied`)* | `pytest -k test_batch_rerun_is_a_noop` against fixture `sheet_all_verbs` (15 items, one per permitted verb): run → re-run → assert `summary.applied == 0`, `summary.already_applied == 15`, rc **0**, and `git rev-parse HEAD` **identical** to after run 1. A second leg asserts the classification is a **state read**: it re-runs with every verb's refusal message monkeypatched to gibberish and the result is unchanged | `M36` (classify from the refusal message) ⇒ BAT8 red on the monkeypatched leg. `M77` (drop `note`'s idempotency key) ⇒ BAT8 red on `HEAD`-unchanged, with `applied == 1` · `predicted` |
| **BAT9** | [A] | `--dry-run` writes nothing at all — ledger AND hosts — and its per-item output for a `route` item is `route --dry-run`'s own payload | `pytest -k test_batch_dry_run_writes_nothing` (snapshot both trees, positive control first) + `test_batch_dry_run_delegates_to_route_dry_run` | give `batch --dry-run` its own preflight copy ⇒ BAT9 red on the delegation leg · `predicted` |

### 5.6 PROD — producer outcomes

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **PROD1** | [A] | `worker kick --json` emits one object carrying the library's own outcome string, for all **five** outcomes | `pytest -k test_worker_kick_json` — parametrised over `spawned, absorbed-window, absorbed-race, disabled, depth-limited` | re-derive a label ("ok"/"noop") instead of passing the outcome through ⇒ PROD1 red · **MEASURED** outcome set (`worker.kick`'s docstring, §2.7) |
| **PROD2** | [A] | `mine run --json` and `worker run --json` do the same for all **eight** / **three** statuses, with `ok` false only for `failed` and `landed-uncommitted` | `pytest -k test_producer_json_ok_flag` | set `ok` from the exit code ⇒ PROD2 red (`busy`/`held-gate` would read `ok: true` from a 0 that says nothing) · `predicted` |
| **PROD3** | [A] | **Exit codes are byte-unchanged** — the negative half. Every outcome maps to the same integer it maps to at `b206800` | `pytest -k test_producer_exit_codes_unchanged` — a table of (outcome → integer) asserted against the pinned map, with `landed-uncommitted → 7` and `failed → 1` present | map `busy` → 6 ⇒ PROD3 red · `predicted`. This criterion exists so a builder cannot "improve" the contract §3.7 deliberately left alone |

### 5.7 RER — reroute and real reference retirement (Phase 2)

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **RER1** | [B] | `reroute` rewrites a routed record's `routing` block, appends the OLD block to `history` with `event: "routing"`, and commits `self-learn: reroute lrn-… → <new-target>` | `pytest -k test_reroute_rewrites_routing` | overwrite `routing` without the history append ⇒ RER1 red · `predicted` |
| **RER2** | [B] | The old target is retired **and** the new one compiled in one motion: the old managed section no longer carries the record's entry line and the new target does | `pytest -k test_reroute_retires_and_compiles` — `claude-md → skill-md` and `reference → claude-md` legs | skip `_retirement_host_phase` ⇒ RER2 red (the entry survives in both) · `predicted` |
| **RER3** | [B] | `reroute` to the **same** destination refuses with rc 1 naming the current destination; nothing is written | `pytest -k test_reroute_same_dest_refuses` | omit the check ⇒ RER3 red (a no-op commit lands) · `predicted` |
| **RER4** | [B] | `reroute --dest hook` and `--dest new-skill` refuse with rc 1 naming the reason; rerouting **away from** either works | `pytest -k test_reroute_one_motion_destinations` — 2 refusal legs + 2 away-from legs | allow `--dest hook` ⇒ RER4 red · `predicted` |
| **RER5** | [B] | `compilers.retire_reference` removes exactly the record's block — heading through the line before the next `^## ` (or EOF) — leaves every other entry byte-identical, and is idempotent | `pytest -k test_retire_reference` — a 3-entry fixture, remove the middle one, byte-compare the other two and the header; call again and assert `applied is False` | end the block at the next blank line ⇒ RER5 red (a multi-paragraph entry leaves its tail) · `predicted`. **MEASURED anchor**: `_reference_block` (`compilers.py:1101`) emits `## <day> — <id>` and blank-line-separated `**Trigger:**`/`**Instruction:**` paragraphs, so a blank-line terminator is the plausible wrong implementation |
| **RER6** | [B] | `graduate` and `supersede` on a **reference-routed** record now remove its entry too, through the same `_retirement_preflight`/`_retirement_host_phase` path — no per-verb branch | `pytest -k test_graduate_retires_reference` and `test_supersede_retires_reference`. **Positive control first**: the same assertion against `b206800` shows the entry surviving | add a `if verb == "graduate"` branch instead ⇒ RER6 red on the `supersede` leg · **MEASURED** pre-state (`_retirement_preflight` returns a bare `_Retirement()` for `reference`, `verbs.py:2604`) |
| **RER7** | [B] | A reference retirement writes a `region: reference` compile-record entry, exactly as the reference write leg does | `pytest -k test_reference_retirement_writes_compile_record` — asserts a `compiled/<slug>.yaml` entry whose `sha256` matches the post-removal region | skip the compile-record write ⇒ RER7 red · `predicted` |

### 5.8 HOST — deregistration and pruning (Phase 2)

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **HOST1** | [B] | `host remove` **refuses** (rc 1) while ≥1 routed record compiles into that host, naming the count, up to five ids, and both repairs; `hosts.yaml` is unchanged | `pytest -k test_host_remove_refuses_with_routed_records`. **Positive control first**: the same fixture at `b206800` returns rc 0. **Second leg, the shipped suite**: `pytest cli/tests/test_hosting_fixes.py -k TestHostRemove` stays green. *(CORRECTED-r3, gate M-7: r2 said "all 4 use a PENDING record". Re-measured — `TestHostRemove` has 4 tests and **only ONE creates a record at all**, `test_remove_deregisters_but_keeps_records` (`:730-747`, one pending); `test_remove_works_for_a_vanished_repo` (`:749`), `test_remove_unknown_host_refuses` (`:756`) and `test_remove_cli` (`:760`) register a host with **no records**, so `M48` leaves those three green.)* **Third leg, this unit's own fixtures**, which give `M48` the witnesses the shipped suite does not: `host_with_routed` carries **4 routed + 2 pending** records, and a sibling `host_pending_only` carries **2 pending, 0 routed** — the second asserts `host remove` still succeeds (rc 0), which is the property `M48` breaks | count pending records too ⇒ HOST1 red on the `host_pending_only` leg, **and 1 of the 4 shipped `TestHostRemove` tests red** — pending records compile into nothing, so a pending-only host must still deregister · **MEASURED**: 1 of 4 shipped tests creates a record, and it is pending |
| **HOST2** | [B] | `--gate-only` proceeds and prints a post-note naming the count and the `recompile` WARN-and-skip consequence | `pytest -k test_host_remove_gate_only` — asserts rc 0, the note, and that a subsequent `recompile` emits the WARN line | drop the note ⇒ HOST2 red · `predicted` |
| **HOST3** | [B] | No bulk retirement exists: `host remove` accepts no `--retire`/`--force`, and `graduate`/`supersede` are never called from `hosts.py` | `self-learn host remove --help` shows only `--gate-only` (rc unpiped); `grep -c 'graduate\|supersede' cli/src/self_learn/hosts.py` = 0 | add `--retire` calling `graduate` in a loop ⇒ HOST3 red on both legs · `predicted` |
| **HOST4** | [B] | `bucket prune` removes exactly the record-less, proposal-less bucket dirs in one commit, never the `user/` bucket, and `--dry-run` writes nothing | `pytest -k test_bucket_prune` — a fixture with 2 empty project buckets, 1 empty skill bucket, 1 non-empty, and the user bucket; asserts 3 removed and the user bucket present | treat "no `lrn-*.md`" alone as empty ⇒ HOST4 red (a bucket holding an orphan proposal is pruned, losing it) · `predicted`. **MEASURED anchor**: 2 such buckets exist live (§2.6) |
| **HOST5** | [B] | `records_targeting` resolves through `hosts.yaml` + the bucket's `meta.yaml`, never by string-matching the path | `pytest -k test_records_targeting_resolves` — a fixture where the host path and the bucket's recorded path differ by a symlink; asserts the record is still found | compare `str(path)` ⇒ HOST5 red · `predicted` |

### 5.9 META — follow-up and reclassification (Phase 2)

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **META1** | [B] | `followup add` writes `routing.follow_up` on a routed record, validated by the shipped `records._validate_follow_up`, commit `self-learn: follow-up add lrn-…` | `pytest -k test_followup_add` | hand-roll a second validator ⇒ META1 red on a malformed-`unblocks_on` leg · `predicted` |
| **META2** | [B] | `followup add` refuses (rc 1) when one is already open, naming the open action; `followup done` then `followup add` succeeds | `pytest -k test_followup_add_refuses_when_open` | allow overwrite ⇒ META2 red (the open follow-up vanishes) · `predicted` |
| **META3** | [B] | `reclassify --kind` works in **every** status; `reclassify --type` is refused outside `LIVE_STATUSES`, naming 02 §2's freeze | `pytest -k test_reclassify_status_asymmetry` — 5 statuses × 2 flags = 10 legs | give `--kind` the same `LIVE_STATUSES` guard ⇒ META3 red on the routed/rejected/superseded `--kind` legs · `predicted`. This asymmetry is 02 §2's own wording, quoted in §3.1 |
| **META4** | [B] | A `--type` change **re-validates required sections** and refuses (rc 1) naming the missing headings; the record is never rewritten to fit | `pytest -k test_reclassify_type_revalidates` — `knowledge → behavior` on a record with only `## Fact` | write the missing heading ⇒ META4 red (the body changed, violating "substance") · `predicted`. **MEASURED anchor**: `records.REQUIRED_SECTIONS` (`records.py:71`) |
| **META5** | [B] | `reclassify` with neither flag is **64**, and an out-of-enum value is 64 naming the enum | `pytest -k test_reclassify_usage` | accept a free-string kind ⇒ META5 red · `predicted`. **MEASURED anchor**: `records.KINDS` / `records.TYPES` (`records.py:55-56`) |

### 5.10 UIP — UI parity (Phase 2)

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **UIP1** | [B] | `_KNOWN_VERBS` covers an **explicit, spec-listed set of record-mutating verbs**, and that set is proved exhaustive against a real closed set — never against a positional-name heuristic *(rewritten r3, gate M-3, ruled)*. **`UI_PARITY_VERBS`** (normative, listed here and asserted as a literal): the four G10 verbs `dismiss-suspect`, `rescope`, `supersede`, `confirm-held`; the already-present `route`, `reject`, `defer`, `graduate`, `confirm-recurrence`, `link-contradicts`, `followup-done`; this unit's Phase-1 additions `undefer`, `reopen`, `note`; and its Phase-2 additions `reroute`, `followup add`, `reclassify` — **17**. Excluded, each with its reason: `rehome` (09 §11 Y-18 decision 3 — no human-side control in M1; its label serves the proposal bar only), `teach` (creates, does not act on an existing record), `show` and `route --dry-run` (read-only), `batch` (takes a sheet, not a record id), `proposal validate` and `host commit-drift` (take a positional `ID` but are not record resolutions — the two the r2 heuristic would have swept in) | `pytest -k test_ui_knows_every_record_verb` (ui), two legs: **(a) parity** — `UI_PARITY_VERBS ⊆ _KNOWN_VERBS`; **(b) exhaustiveness** — `set(cli.VERB_COMMANDS) \| {this unit's new record verbs} \| {"link-contradicts","followup-done"}` minus the stated exclusion set equals `UI_PARITY_VERBS`, so a future unit adding a verb to `VERB_COMMANDS` (`cli.py:1997`, a real closed set) without touching either list fails here | `M58` (drop `supersede` from `_VERB_LABELS`) ⇒ **UIP1 leg (a) red** · `predicted`. **MEASURED, and why the r2 form could not work**: `grep -c 'add_argument("id"' cli.py` = **13**, two of which are `proposal validate` (`:633`) and `host commit-drift` (`:562`) — neither excludable by name — while `supersede`'s positionals are `OLD_ID`/`NEW_ID` (`:287-288`), so the heuristic never saw the one G10 verb it existed to force in |
| **UIP2** | [B] | `build_argv` emits the exact argv `cli.py`'s parser accepts for each new verb — proved by round-tripping through the real parser | `pytest -k test_build_argv_round_trips` (ui) — for each new verb, `cli._build_parser().parse_args(build_argv(...))` succeeds and the parsed namespace carries the passed values | append `--json` at the shared tail ⇒ UIP2 red for the verbs whose parser has no `--json` · `predicted`. **MEASURED anchor**: `build_argv`'s own docstring records that exact bug class for the four `json_flag` verbs |
| **UIP3** | [B] | The `holding` card renders a **Dismiss (k)** control that arms `dismiss-suspect` with the card's `event` nonce, and the `resolved` card renders **Still holding (m)** arming `confirm-held` | `pytest -k test_holding_card_offers_dismiss` and `test_resolved_card_offers_confirm_held` (ui) — DOM assertions on the rendered partial | omit the `event` hidden field ⇒ the arm POST refuses (the CLI requires `--event`) and UIP3 red · `predicted` |
| **UIP4** | [B] | Every keymap key is unique and `k`/`m` are the only additions; `l` and `z` stay free | `pytest cli`-side n/a; `pytest -k test_keymap_uniqueness` (ui, the **shipped** test) plus `test_free_keys_remaining` asserting `{"l","z"} ⊆ free` | bind `l` to `reroute` ⇒ `test_free_keys_remaining` red · `predicted`. **MEASURED**: free letters are `hklmz` at `b206800` (§2.8) |
| **UIP5** | [B] | `NOTICE_PROPOSAL_MOVED` fires for **every** new move leg, not only project→project | `pytest -k test_proposal_moved_notice_all_legs` (ui) — a waiting proposal + a CLI-side `rehome --to user`, asserting the slot clears with that notice | key the notice on the target being a project bucket ⇒ UIP5 red · `predicted` |

### 5.11 UN — the unaffected group behaves byte-identically

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **UN1** | [A] | `route`, `reject`, `defer` (future date), `graduate` and `supersede` are **byte-identical** on a fixture with no new verb involved: same commit subjects, same bodies, same target bytes, same exit codes | `pytest -k test_un_shipped_verbs_byte_identical` — a scripted 6-verb sequence whose ledger `git log --format='%s%n%b'` and host file sha256 are compared to a baseline whose **provenance is stated** *(r3, gate N-8)*: the fixture stores a `baseline.json` of `{commit_subject, commit_body, target_sha256, exit_code}` per step, generated **once** by running the same scripted sequence against the `b206800` read-only worktree (`git worktree add --detach … b206800`) and committed alongside the test with the commit it came from named in a comment. It is **never regenerated by the build** — a `make-baseline` helper that the test itself can call would make `UN1` a self-comparison, which is the exact defect this note exists to prevent | add an unconditional `history: []` key to every written record ⇒ UN1 red (frontmatter bytes change) · `predicted` |
| **UN2** | [A] | A record that never meets a new verb carries **no** `history` and **no** `notes` key — the schema addition is absent, not empty | `pytest -k test_no_empty_history_key` — `teach` → `route`, then grep the record's raw bytes for `history` / `notes` | initialise both keys at creation ⇒ UN2 red · `predicted` |
| **UN3** | [A] | The existing `rescope` suite is green unchanged (34 tests) and the existing `rehome` suite is green with exactly **one** declared rewrite (19 tests) | `pytest cli/tests/test_rescope.py cli/tests/test_rehome.py -q` — 53 tests, 0 failures; `git diff --stat` on the two files shows changes only in `test_rehome.py` | change `rescope`'s commit subject ⇒ 2 tests red (`test_rescope.py:144`, `:159`) · **MEASURED** as live pins |
| **UN4** | [A] | `test_lock_invariant.py` is green with **`_LOCKS` and `NOT_REPO_TRUTH` byte-unchanged**, every new mutating verb sits inside a `_ledger_write` span, and the file's OTHER table — **`_ARGV_FOR` — GAINS exactly two rows** *(rewritten r3, gate M-2: r2 asserted `git diff` on the whole file is empty, which is unsatisfiable on a correct build — `test_every_cmd_surface_is_covered` (`:651-658`) FAILS when a new `_cmd_*` has no `_ARGV_FOR` entry, and this unit adds `_cmd_batch` and `_cmd_show`)* | (a) `pytest cli/tests/test_lock_invariant.py -q` green; (b) `git diff` scoped to the `_LOCKS` and `NOT_REPO_TRUTH` definitions is **empty**; (c) `_ARGV_FOR` gains exactly `"_cmd_batch": [["batch", "{sheet}"]]` and `"_cmd_show": [["show", "lrn-eeee0001"]]`, and `set(_cmd_functions()) - set(_ARGV_FOR)` is empty. **MEASURED at `b206800`**: 25 `_cmd_*` functions, 25 `_ARGV_FOR` keys, `_LOCKS = ("commit_lock", "_ledger_write", "host_lock")` at `:97`; and **`test_lock_invariant.py` is NOT `_ARMOR_SHAS`-pinned** (`grep -c 'test_lock_invariant' cli/tests/test_worker_contract.py` = **0**), so no armor sha moves and no re-pin is owed | write `undefer`'s record outside the span ⇒ the walker reddens (a). `M76` (omit either `_ARGV_FOR` row) ⇒ `test_every_cmd_surface_is_covered` reddens (c) · `predicted` |
| **UN5** | [A] | **No `_ARMOR_SHAS` entry moves.** All seven pinned files are byte-unchanged | `pytest cli/tests/test_worker_contract.py -k armor -q`; `git diff --stat` over the seven paths is empty | touch any armored file ⇒ the armor test reddens with its own message · **MEASURED**: zero of this unit's verb names appear in any of the seven (§2.9) |

### 5.12 DOC — the docs footprint

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **DOC1** | [A] | `03-decisions.md` carries the **S-54** row (§11.1) | `grep -c "^| S-54 " docs/specs/self-learn/03-decisions.md` = 1 | delete ⇒ DOC1 red · `predicted` |
| **DOC2** | [B] | `14-forward-work-map.md` carries **FW-133 … FW-138** (§11.2), and the existing **FW-85, FW-114, FW-115** rows each gain a dated disposition note | `grep -cE "^\| \*\*FW-13[3-8]\*\* " …` = 6; `grep -c "S-54" …` ≥ 4 (the three amended rows plus at least one new one) | close FW-114/115 by deleting them ⇒ DOC2 red (the register's own rule: a settled row is amended in place, never removed) · `predicted` |
| **DOC3** | [A] | `02-schema.md` §2 carries the `history` / `notes` amendment, naming the closed `event` set and the `clear_resolution_note` precondition | `awk '/^## 2\. Field rules/,/^## 3\./' docs/specs/self-learn/02-schema.md | grep -c "history"` ≥ 1 and the same range contains `clear_resolution_note`. Positive control: that range's `grep -c "history"` **today** = 0 | put the amendment in §1 ⇒ DOC3 red on the range check · `predicted` |
| **DOC4** | [A] | `commands/review.md` names `self-learn batch` as the apply path and drops the "hand-write a script" shape; the exit-code section gains `batch`'s severity rule | `grep -c "self-learn batch" plugins/self-learn/commands/review.md` ≥ 1; the file contains the severity order literal `7 > 4 > 3 > 6 > 1 > 0` | leave review.md alone ⇒ DOC4 red — and the next batch is hand-written again, which is the whole defect · `predicted` |
| **DOC5** | [B] | `routing-doctrine.md` §3's re-home clause names the widened target vocabulary, and `11-telemetry-and-lifecycle.md` §2.5's verb table gains **six** rows — the three Phase-2 verbs **and the three Phase-1 ones** *(widened r3, gate D-3: r2 counted only the Phase-2 three and left `undefer`/`reopen`/`note`'s doc rows to "whichever table §2.5 keeps", i.e. unpinned)* | per-section: `awk '/^## 3\./,/^## 4\./' …/routing-doctrine.md \| grep -c "skill:<name>"` ≥ 1; and `grep -cE '^\| `(reroute\|followup add\|reclassify\|undefer\|reopen\|note)[ `]' docs/specs/self-learn/11-telemetry-and-lifecycle.md` = **6** *(CORRECTED-r4, gate M-3r2: r3 required a closing backtick immediately after the verb name, which the shipped §2.5 rows never have — they put the whole invocation in one code span, `| \`confirm-held <id> [--note …]\` | …`. A builder following §11.5's "the shipped format" would have reddened `DOC5`; one satisfying `DOC5` would have written rows that do not match the table. The `[ `]` class accepts both.)*. **Positive control, measured at `b206800`**: the same pattern over the three shipped rows this unit does not touch — `grep -cE '^\| `(confirm-held\|followup done\|link contradicts)[ `]' …` = **3**, while r3's trailing-backtick form returns **0** on those same rows. Third leg: `11 §4.2`'s doctrine sentence reads *"every mutating dispatch — single verb or batch — flushes once"* (§3.3c) | amend only the doctrine ⇒ DOC5 red on the `11` leg; ship only the Phase-2 rows ⇒ red at 3 ≠ 6 · `predicted` |
| **DOC8** | [A] | **Every measured rendering of the record-verb exit contract carries `8`, and the two non-renderings do not** *(new r5, gate N-3r3)*. The three: `cli.py:13-22`, `commands/review.md:230-264`, `skills/self-learn/SKILL.md:96-101` | Three greps, `rc` unpiped: `grep -c 'EXIT_BATCH_PARTIAL' cli/src/self_learn/cli.py` ≥ 2 (the constant and the docstring row); `awk '/^Read each verb/,/^## Session end/' commands/review.md \| grep -c '\*\*8\*\*'` ≥ 1; `awk '/^## Environment . exit codes/,0' skills/self-learn/SKILL.md \| grep -c '8 batch'` = 1. **Plus two NEGATIVE legs**: `grep -c 'EXIT_BATCH_PARTIAL\|\*\*8\*\*' commands/teach.md` = **0** (its `2/3/4` mean different things — its own header calls it "The COMPLETE contract — every code `teach` can return") and `grep -cE 'exit code\|exit [0-9]\|EXIT_' docs/specs/self-learn/11-telemetry-and-lifecycle.md` = **0**. **Positive controls, measured at `b206800`**: `git grep -c "Only 3, 4 and 7"` = **1** (review.md only), and 11's exit-code count is **0** today — so the negative legs assert a preserved property, not an accident | add an `8` row to `teach.md` or an exit-code paragraph to `11` ⇒ DOC8 red on a negative leg — the failure mode where a builder "completes" a contract onto a surface that renders a different one · `predicted`. Amend only `cli.py` ⇒ red on the review.md and SKILL.md legs · `predicted` |
| **DOC6** | [A] | The deployed skill is the repo's (symlink), so DOC5's doctrine edit is live without a copy step | `ls -la ~/.claude/skills/self-learn` shows a symlink into `plugins/self-learn/skills/self-learn` | replace the symlink with a copy ⇒ DOC6 red · **MEASURED** (this check is U-ancestry's `DOC4`, re-used) |
| **DOC7** | [A] | **The review skill becomes a thin caller of `batch` (ruling R3), in the three sections that actually change** — `commands/review.md`'s Apply block (inside `## The card`), its exit-code block, and `## Session end` — each checked **within its own heading range**, never by a whole-file count | Three `awk` range tests, `rc` captured unpiped, boundaries verified against the file's real headings (`## Session start` :16, `## Per record` :37, `## The card` :66, `Read each verb's output line` :230, `## Session end` :272): (a) `awk '/^## The card/,/^Read each verb/' … \| grep -c 'self-learn batch'` ≥ 1; (b) `awk '/^Read each verb/,/^## Session end/' … \| grep -c '7 > 4 > 3 > 6 > 1 > 0'` = 1; (c) `awk '/^## Session end/,0' … \| grep -c 'self-learn batch'` ≥ 1. **Positive controls, re-measured at `b206800` and `ba90ef9`**: all three targets return **0** now, while the same three ranges return **20 / 3 / 2** hits for the looser `self-learn ` — so each range is non-empty and each awk boundary matches a real line. *(CORRECTED-r3, gate M-9: r2 wrote `1` for the third; the `## Session end` range carries two — `self-learn sentinel release` and `self-learn push`.)* | put all three edits in one section ⇒ DOC7 red on the other two ranges — a whole-file `grep -c ≥ 3` would have stayed green · `predicted` |

**Criterion count: 80** — PH 2 · GUARD 4 · MOVE 10 · STATE 8 · DRY 4 ·
SHOW 3 · BAT 11 · PROD 3 · RER 7 · HOST 5 · META 5 · UIP 5 · UN 5 · DOC 8.
**Phase 1 [A]: 56. Phase 2 [B]: 24.**
*(r5 adds **`DOC8`** — gate N-3r3, the measured exit-contract rendering
set, positive and negative — and rewrites `BAT11` (three legs, sites not
names) and `MOVE1` leg 9 (the dead byte-identity control deleted).)*
*(r4 adds **`BAT11`** — ruling M-4r2, the shared mutating-verb epilogue —
and extends `MOVE1` with a ninth leg, `BAT2` with a fifth, and `BAT10`
leg (a) with the flush commit.)*
*(r2 added `MOVE10` (ruling R1) and `DOC7` (ruling R3); ruling R5 extended
`STATE8` and `SHOW1`. **r3 adds `SHOW3`** — gate M-2, `show` must not join
`VERB_COMMANDS`, whose flush commits — **and `BAT10`** — ruling M-6, the
applied+refused mix exits `8`, never `1` — and rewrites `BAT2`, `BAT4`,
`BAT8`, `MOVE9`, `UIP1`, `UN4`, `HOST1`, `DOC5`, `PH2` and `UN1` against
the gate's measurements.)* (Re-derived from the tables above by
`re.findall(r'^\| \*\*([A-Z]+\d+)\*\* \| \[([AB])\]', …)`; no id
appears twice.)

---

## 6. Mutation plan

Each row names the **exact edit** and the criterion whose named test must
go **RED**. Cells are `predicted` unless marked **MEASURED** (a pre-state
read off `b206800` during this spec's census, so the "before" half is
fact and only the "after" half is a prediction).

| # | Mutation (the exact edit) | Criteria that redden | Cell |
|---|---|---|---|
| M1 | `verbs.rehome`: restore the hand-rolled `if path.parent.name != "pending" or record.status not in ("pending","deferred")` in place of `require_status` | GUARD1, GUARD3 | **MEASURED** pre-state (`verbs.py:4281`) |
| M2 | `verbs.rescope`: same restoration | GUARD1 | **MEASURED** pre-state (`verbs.py:4467`) |
| M3 | `verbs.reopen`: inline `frozenset({"rejected"})` at the call site instead of `REOPENABLE_STATUSES` | GUARD2 | `predicted` |
| M4 | `verbs.undefer`: `find_record_path(home, id, statuses=("pending",))` instead of `require_status` | GUARD3 | `predicted` |
| M5 | `verbs.undefer`: drop the precondition entirely | GUARD4 | `predicted` |
| M6 | `ledger_ops.move_record`: drop the `record.set_scope(target_scope)` call | MOVE1 (6 of 8 legs) | `predicted` |
| M7 | `ledger_ops.move_record`: call `ensure_project_meta` unconditionally | MOVE2 | `predicted` |
| M8 | Keep `rescope_record` as a one-line shim over `move_record` | MOVE3 | `predicted` |
| M9 | `_resolve_move_target`: try the path/slug arm **before** the `user` / `skill:` literals | MOVE4 | `predicted` |
| M10 | `verbs._move`: emit `self-learn: rehome lrn-… → <slug>` (drop the `projects/` prefix) | MOVE5 — and the **shipped** `test_rehome.py:106` | **MEASURED** as a live pin |
| M11 | `verbs._move`: emit `post_notes` only when the invoked name is `rescope` | MOVE6 | **MEASURED** pre-state (`rehome` returns no `post_notes` at `b206800`) |
| M12 | `ledger_ops.move_record`: replace the pending/resolved collision check with an overwrite | MOVE7 | `predicted` |
| M13 | `ledger_ops.move_record`: `record.set_deferred_count(0)` on move | MOVE8 | `predicted` |
| M14 | `ui/proposals.py`: let the `to` validator call `verbs._resolve_move_target` directly | MOVE9 | `predicted` |
| M15 | `ledger_ops.defer_record`: remove the past-date comparison | STATE1 | **MEASURED** pre-state (no comparison exists at `b206800`) |
| M16 | `ledger_ops.defer_record`: refuse `until <= today` instead of `until < today` | STATE2 | `predicted` |
| M17 | `verbs.undefer`: clear `deferred_count` as well as `deferred_until` | STATE3 | `predicted` |
| M18 | `verbs.reopen`: drop the `append_history` call before `clear_resolution_note` | STATE4 — and `clear_resolution_note` must RAISE, which the test also asserts | `predicted` |
| M19 | `Record.clear_resolution_note`: drop the "already in history" precondition | STATE5 | `predicted` |
| M20 | `ledger_ops`: `REOPENABLE_STATUSES = RESOLUTION_STATUSES` | STATE6 | `predicted` |
| M21 | `verbs.reopen`: carry the proposal sibling instead of sweeping it | STATE7 | `predicted` |
| M22 | `verbs.note`: write into `resolution_note` when it is currently `None` | STATE8 | `predicted` |
| M23 | `verbs.route`'s dry-run leg: build the diff from the proposal's `destination` text instead of `_expected_managed_region` | **DRY1** (the isolator) | `predicted` |
| M24 | Dry-run leg: hand-roll a second `compile_managed_text` call | DRY2 | `predicted` |
| M25 | Dry-run leg: wrap the preflight in `_ledger_write(home)` "for consistency" | DRY3 | `predicted` |
| M26 | Dry-run leg: `return` at the first refusal | DRY4 | `predicted` |
| M27 | `show`: read `canon.present` from `record.routing` instead of the target file | SHOW1 | `predicted` |
| M28 | `cli`: drop the `SELF_LEARN_MINER_AUTOKICK` sentence from `show --help` | SHOW2 | `predicted` |
| M29 | `batch.load_sheet`: validate each item lazily, inside the run loop | BAT1 | `predicted` |
| M30 | `batch`: `max(item_codes)` on the raw integers instead of §3.3a's decision procedure | **BAT2**, on its `{3,6}` and `{4,6}` legs — raw max returns 6 for a run that committed, inverting the ledger-changed claim. *(r2's two legs `{0,1,3}` and `{0,7,1}` both give the identical answer under raw max, so this mutation used to redden nothing — gate M-1.)* | `predicted` |
| M31 | `batch`: add `1` to the stop set | BAT3 | `predicted` |
| M32 | `batch`: `sentinel.hold()` inside the item loop | BAT4 | `predicted` |
| M33 | `batch`: pass `no_push=False` to each item | BAT5 | `predicted` |
| M34 | `batch`: drop the `hook`-destination refusal | BAT6 | `predicted` |
| M35 | `batch`: add `host add` to the permitted verb set | BAT7 | `predicted` |
| M36 | `batch`: classify `already-applied` by matching the refusal message text | **BAT8**'s monkeypatched-message leg | `predicted` |
| M37 | `batch --dry-run`: give it its own preflight implementation instead of calling `route`'s dry-run function | BAT9 | `predicted` |
| M38 | `cli._cmd_worker`: emit `"outcome": "ok"` / `"noop"` instead of the library's own string | PROD1 | **MEASURED** outcome set |
| M39 | `cli._cmd_mine`: set `ok` from the exit code | PROD2 | `predicted` |
| M40 | `cli._cmd_mine`: map `busy` → `EXIT_GIT_FAILED` (6) | PROD3 | `predicted` |
| M41 | `verbs.reroute`: overwrite `routing` without appending the old block to `history` | RER1 | `predicted` |
| M42 | `verbs.reroute`: skip `_retirement_host_phase` for the old target | RER2 | `predicted` |
| M43 | `verbs.reroute`: omit the same-destination refusal | RER3 | `predicted` |
| M44 | `verbs.reroute`: remove `hook`/`new-skill` from the refused destination set | RER4 | `predicted` |
| M45 | `compilers.retire_reference`: terminate the block at the next **blank line** instead of the next `^## ` | RER5 | `predicted` (the plausible wrong implementation — `_reference_block` emits blank-line-separated paragraphs, **MEASURED** at `compilers.py:1101`) |
| M46 | `verbs`: implement reference retirement as an `if verb == "graduate"` branch instead of extending `_retirement_preflight` | RER6 (the `supersede` leg) | **MEASURED** pre-state (bare `_Retirement()` for `reference`, `verbs.py:2604`) |
| M47 | Reference retirement: skip the `_write_generic_region_entry` call | RER7 | `predicted` |
| M48 | `hosts.records_targeting`: include `pending` records in the count | **HOST1** on its `host_pending_only` leg — **and 1 of the 4 shipped `test_hosting_fixes.py::TestHostRemove` tests** (`test_remove_deregisters_but_keeps_records`, `:730-747`, the only one that creates a record; the other three register a host with no records and stay green) | **MEASURED**: 1 of 4 shipped tests creates a record, and it is pending *(CORRECTED-r3, gate M-7 — r2 claimed all four)* |
| M49 | `host remove --gate-only`: drop the consequence post-note | HOST2 | `predicted` |
| M50 | `host remove`: add `--retire`, looping `verbs.graduate` over the set | HOST3 | `predicted` |
| M51 | `bucket prune`: treat "no `lrn-*.md`" alone as empty (ignore `proposals/`) | HOST4 | `predicted` |
| M52 | `hosts.records_targeting`: compare `str(path)` instead of resolving both sides | HOST5 | `predicted` |
| M53 | `verbs.followup_add`: hand-roll a shape check instead of calling `records._validate_follow_up` | META1 | `predicted`, **MEASURED** (gate r2 M-A re-verify): pre-M-A the r1 fold's blanket `except RecordError` wrapper caught the ValidationError `Record.set_follow_up` raises regardless of this mutation and relabelled it `VerbError`, so `test_followup_add_malformed_unblocks_on_refuses` (`pytest.raises(VerbError)`) passed either way -- hollowed out. Post-M-A-fix (narrowed to `except records_mod.MutationError`), re-run: RC=1, the SAME `ValidationError` now escapes UNCAUGHT ("follow_up unblocks_on must be non-empty text") past `pytest.raises(verbs.VerbError)` -- lethality restored, MEASURED fresh this fold. |
| M54 | `verbs.followup_add`: overwrite an open `routing.follow_up` | META2 | `predicted`, **MEASURED** (gate r2 fold, re-verified against the rewritten `reclassify`/`followup_add` shape): neutralizing the `if existing: raise VerbError(...)` guard reddens `TestMETA2FollowupAddRefusesWhenOpen::test_followup_add_refuses_when_open` cleanly -- `Failed: DID NOT RAISE VerbError`. |
| M55 | `verbs.reclassify`: apply `LIVE_STATUSES` to `--kind` as well as `--type` | META3 | `predicted`, **MEASURED** (gate r2 fold, re-verified against `_reclassify_apply`): adding a `require_status(..., LIVE_STATUSES, verb="reclassify --kind")` gate to the `kind is not None` branch reddens `TestMETA3ReclassifyStatusAsymmetry::test_reclassify_status_asymmetry` cleanly on the first non-live status in the loop (`routed`) -- `VerbError: record lrn-50000003 is 'routed' — reclassify --kind needs status pending/deferred (02 §2)`, uncaught by the test (the loop expects success in every status). |
| M56 | `verbs.reclassify`: append the missing required heading on a `--type` change | META4 *(retargeted gate r2 fold, re-verified against `_reclassify_apply`: swallowing the early `except RecordError` refusal in the pre-lock type-change block alone leaves `test_reclassify_type_revalidates` GREEN -- MEASURED (`1 passed`). The criterion IS guarded, one layer down: gate r2's B-1 fix added an independent pre-lock simulate-and-`Record.validate()` step whose own `set_type(...)` call re-runs the identical body-shape validator and raises the SAME `ValidationError`, wrapped into the SAME `VerbError` message ("must contain a '## Trigger' section") the test asserts on -- so disabling the early check alone still reddens `pytest.raises(VerbError)` correctly, just one layer further in, same shape as M57's retargeting. Disabling BOTH the early check AND the B-1 simulation step DOES silence the test's easy path, but the LOCK BODY's own `_reclassify_apply(record, ...)` call (a fresh, unsimulated `set_type`) still raises the same `ValidationError` -- and gate r2 M-A's narrowed `except records_mod.MutationError` does NOT catch it, so it escapes UNCAUGHT past `pytest.raises(VerbError)` -- MEASURED RED, but via an uncaught `ValidationError` (wrong exception type, not the value sailing through unrefused), not the clean shape M56's own name suggests. All three layers would need removing to actually let a malformed body through to disk.)* | `predicted`, **MEASURED** (gate r2) |
| M57 | `cli`: make `--kind` a free string instead of `choices=sorted(records.KINDS)` | META5 *(retargeted gate r2, m-3: `TestMETA5ReclassifyUsage` drives `verbs.reclassify(...)` directly, never `cli.main`, so removing the CLI's own `choices=` alone leaves it GREEN -- MEASURED. The criterion IS guarded, one layer down: `verbs.reclassify`'s own `if kind not in records_mod.KINDS: raise VerbUsageError` (`verbs.py`) is what M57 actually needs to disable to redden META5 -- MEASURED RED, though not by the clean shape either mutation's own name suggests: gate r2's B-1 fix added an independent resulting-pair check (`_reclassify_apply` + `Record.validate()`) that ALSO rejects an out-of-enum `--kind` one layer further in, through `Record.set_kind`'s own enum check -- so disabling the verb-layer gate alone still reddens the test, but via an uncaught `VerbError` escaping a `pytest.raises(VerbUsageError)` block (wrong exit code, 1 not 64) rather than the value sailing through unrefused. Both checks would need removing to actually silence the test.)* | `predicted`, **MEASURED** (gate r2)
| M58 | `ui/routes.py`: drop `supersede` from `_VERB_LABELS` (and therefore from `_KNOWN_VERBS`) | **UIP1 leg (a)** — `supersede` is in the normative `UI_PARITY_VERBS` set *(retargeted r3, gate M-3: r2's mutation was "hand-write the expected list", whose own cell admitted it "would go green", i.e. it reddened no criterion)* | `predicted` |
| M59 | `ui.build_argv`: append `--json` at the shared `--note`/`--no-push` tail | UIP2 | `predicted` (**MEASURED** anchor: `build_argv`'s docstring records this exact bug class) |
| M60 | `action_bar.html`: omit the `event` hidden field from the Dismiss control | UIP3 | `predicted` |
| M61 | `keymap.py`: bind `l` to `reroute` | UIP4 | `predicted` |
| M62 | `routes.py`: fire `NOTICE_PROPOSAL_MOVED` only when the target is a project bucket | UIP5 | `predicted` |
| M63 | `records.Record`: initialise `history: []` and `notes: []` on every record write | UN1, UN2 | `predicted` |
| M64 | `verbs.undefer`: write the record outside the `_ledger_write` span | UN4 (the walker) | `predicted` |
| M65 | Touch any `_ARMOR_SHAS`-pinned file | UN5 | **MEASURED** as a live guard |
| M66 | Delete the `S-54` row / any `FW-13x` row / the 02 §2 amendment / `review.md`'s `batch` line / the `11 §2.5` rows | DOC1, DOC2, DOC3, DOC4, DOC5 | `predicted` |
| M67 | Import or call a Phase-2 symbol from a Phase-1 module | PH1 | `predicted` |
| M68 | `verbs.undefer`: call `_host_phase` | PH2 | `predicted` |
| M69 | `verbs._move`: emit `self-learn: refile lrn-… → …` for BOTH names (the Q1 'one verb word' option, applied without the doc amendments it requires) | UN3 — `test_rescope.py:144` and `:159` | **MEASURED** as live pins |
| M70 | Replace `~/.claude/skills/self-learn` with a copy of the repo's skill dir | DOC6 | **MEASURED** as a live invariant (U-ancestry's `DOC4`) |
| **M71** | *(ruling R1)* Reintroduce a **divergent write** in one entry point: give `verbs.rescope` back its own `record.set_scope(...)` + `git mv` + `remove_proposal_siblings(...)` and leave `verbs.rehome` on `move_record` | **MOVE10** — and **no other criterion**: every behavioural MOVE leg still passes, because the divergent copy does the same thing *today*. That silence is the finding — `MOVE10` is the only check that can see a second implementation before it drifts | `predicted` (pre-state **MEASURED**: two file-ops at `ledger_ops.py:2387`/`:2427`, §2.3) |
| **M72** | *(ruling R5)* Drop the `notes` rendering from `show` — JSON key and human render both | **STATE8** leg 2, **SHOW1** | `predicted` |
| **M73** | *(ruling R3)* Put all three `commands/review.md` edits inside `## The card` | **DOC7** ranges (b) and (c) | `predicted` — a whole-file `grep -c 'self-learn batch' >= 2` would stay green |

| **M74** | *(ruling M-6)* `batch`: return **1** on an applied+refused mix (r2's severity rule) | **BAT10** leg (a) — a run that committed 3 items reports the integer whose ratified meaning is "refused, nothing written" | `predicted` |
| **M75** | *(gate M-2)* `cli`: add `"show"` to `VERB_COMMANDS` | **SHOW3** on both legs — and **only** because the fixture seeds a non-empty spool; an empty-spool fixture stays green | `predicted`. **MEASURED**: the flush at `cli.py:2142-2146` commits (`:1955-1969` docstring) |
| **M76** | *(gate M-2)* Omit either new `_ARGV_FOR` row (`_cmd_batch` / `_cmd_show`) | **UN4** leg (c) — `test_every_cmd_surface_is_covered` (`test_lock_invariant.py:651-658`) reddens with the missing name | `predicted`. **MEASURED**: 25 `_cmd_*` = 25 `_ARGV_FOR` keys at `b206800` |
| **M77** | *(ruling M-5)* `verbs.note`: ignore `--key` and append unconditionally | **BAT8** — the second run applies 1 item and `HEAD` moves; **STATE8** stays green, which is the point (a human-facing `note` is *supposed* to append) | `predicted` |

| **M78** | *(gate M-1r2; retargeted r5, gate M-2r3)* `ledger_ops.move_record`: make step 5's `set_scope` **conditional on bucket equality** — skip it whenever the source and target buckets carry the same scope — instead of writing unconditionally | **MOVE1 leg 9 only** — all eight cell legs stay green, because they use well-formed records. That is precisely why leg 9 is owed: without it, both forms pass §5. *(r4 aimed this at "condition on the bucket-derived source scope"; same effect, but §3.2a no longer has a condition to change, so the mutation now describes ADDING one.)* | `predicted` |
| **M79** | *(ruling M-4r2)* `batch.run`: drop the `_mutating_epilogue(no_push=True)` call | **BAT11 leg (b)** — 6 sites ≠ the spec table's 7 — **and BAT10 leg (a)** (`HEAD +3` instead of `+4`); two independent witnesses, the second only because that fixture's spool is seeded | `predicted` |

| **M80** | *(gate N-3r3)* Add an `EXIT_BATCH_PARTIAL` / `**8**` row to `commands/teach.md` — the "helpful completion" onto a surface that renders a **different** contract (teach's `2`/`3`/`4` mean usage / scan refusal / analyst fallback) | **DOC8**'s first negative leg | `predicted`. The mirror mutation — amend only `cli.py` and leave `review.md`/`SKILL.md` — reddens DOC8's positive legs |

**Mutation count: 80** (M1…M80). Every one of the 80 criteria is
named by at least one row (verified by extracting both lists from this
file and differencing them).

**M23 is the unit's isolator.** `route --dry-run`'s entire value is that
the preview equals the write. A preview computed from the proposal rather
than from `_expected_managed_region` looks right in every hand test —
same destination, same target path, similar text — and is wrong exactly
when the compiler and the proposal disagree, which is the case the
`commands/review.md:86-87` note already warns about (*"the compiler
regenerates from the record at apply time, so what lands may differ in
detail"*). DRY1's byte comparison against a real
subsequent route is the only check that can tell them apart. **M24 is its
guard**: the plausible way to implement DRY1 wrongly is to compile a
second time in the dry-run path, which passes DRY1 and then drifts.

**M10, M11, M15, M46 and M65 have MEASURED pre-states**, so their "before"
half is not a prediction: `rehome`'s subject and its missing `post_notes`,
`defer_record`'s missing date check, `_retirement_preflight`'s empty
`reference` branch, and the armor guard were each read off `b206800`.

### 6.1 Unmutated-test census — what the existing 2,636 + 1,279 tests catch

```
$ grep -rlE '\brehome\b|\brescope\b|require_status|defer_record|_retirement_preflight|_KNOWN_VERBS|build_argv' \
      plugins/self-learn/cli/tests plugins/self-learn/ui/tests | sort | wc -l
20
```

**20 files** match, and most hit only the word `rehome` inside a pane or
proposal fixture. The four carrying real coverage of a surface this unit
changes are `test_rehome.py` (19), `test_rescope.py` (34),
`test_hosting_fixes.py::TestHostRemove` (4) and
`test_retirement_cleanup.py`.

| Mutation | Caught by an existing test? |
|---|---|
| **M10** (`rehome` subject) | **YES** — `test_rehome.py:106`. The only mutation in this unit an existing test catches loudly |
| **M1 / M2** (restore the hand-rolled checks) | **Partly** — `test_rehome.py:200` pins the hand-rolled *message*, so M1 makes it GREEN again and GUARD1's AST check is the only thing that reddens. That inversion is why `test_rehome.py:200` is **rewritten** (§7) rather than left: a test that passes on the defect is worse than no test |
| **M6 / M7 / M9 / M12 / M13** (move mechanics) | **NO** — the existing 53 rehome/rescope tests exercise only the four shipped legs, and none of the four crosses a scope family |
| **M15 / M16** (past-date) | **NO** — `test_route_cli.py::test_defer_cli_bad_date_is_usage_error` pins only the *format* refusal (64), never a semantically-valid past date |
| **M18–M22** (reopen/undefer/note) | **NO** — no such verb exists |
| **M23–M28** (dry-run/show) | **NO** — no such surface exists |
| **M29–M37** (batch) | **NO** |
| **M38–M40** (producer envelopes) | **NO** — `test_worker.py`/`test_miner.py` assert `EXIT_OK` for non-fire outcomes, which is the fail-open itself |
| **M41–M47** (reroute/reference) | **NO** — `test_retirement_cleanup.py` covers doc and hook retirement only; the `reference` leg has no test because it has no behaviour |
| **M48-M52** (host) | **PARTLY, and usefully.** `test_hosting_fixes.py::TestHostRemove` has 4 tests and `test_hostmode.py` 1 more, but **all of them use a PENDING record** (`test_remove_deregisters_but_keeps_records`, `:730-747`) — so `HOST1`'s routed-only refusal leaves every one green, while **M48 (count pending too) reddens all four at once**. The shipped suite is therefore the guard against the over-broad implementation, and `HOST1` supplies the missing half. M49-M52 are uncaught |
| **M53–M57** (meta) | **NO** |
| **M58-M62** (UI) | **NO** — measured: `grep -rn '_KNOWN_VERBS' ui/tests/` returns **0**. The set has never been asserted from outside `routes.py` at all, which is why `UIP1` derives its expectation from `cli._build_parser` rather than restating the set |
| **M63** (`history: []` everywhere) | **Probably** — several record-byte assertions across `test_records.py`/`test_verbs.py` would move, but noisily and in the wrong file; UN2 asserts it in the right one |
| **M64** | **YES** — `test_lock_invariant.py`'s walker |
| **M65** | **YES** — the armor test's own message |
| **M69** (both names emit one subject) | **YES** — `test_rescope.py:144` and `:159` |
| **M70** (skill symlink → copy) | **NO** — nothing asserts the symlink today; `DOC6` is where it becomes asserted |
| **M71** (a divergent write in one entry point) | **NO — and, uniquely, nothing NEW would catch it either except `MOVE10`.** Every behavioural MOVE leg passes, because a freshly-forked copy does the same thing on the day it is forked. This is the mutation that shows why ruling R1 needed a *structural* criterion and not just "keep both names" |
| **M72** (drop `show`'s notes rendering) | **NO** — `show` does not exist |
| **M73** (all three review.md edits in one section) | **NO** — and a naive whole-file `grep -c 'self-learn batch' >= 2` would pass it too, which is why `DOC7` checks per heading range |
| **M74** (batch returns 1 on the mix) | **NO** — `batch` does not exist. This was r2's own rule, so nothing anywhere would have flagged it |
| **M75** (`show` joins `VERB_COMMANDS`) | **NO** — and, crucially, **an EMPTY-spool `SHOW3` fixture would not catch it either**; the seeded spool (`spooled_home`) is what makes the criterion a discriminator |
| **M76** (drop an `_ARGV_FOR` row) | **YES** — `test_lock_invariant.py::test_every_cmd_surface_is_covered` (`:651-658`) reddens with the missing `_cmd_*` name. One of only six mutations the shipped suite catches |
| **M77** (`note` ignores `--key`) | **NO** — no such flag exists |
| **M78** (step 5 conditioned on the bucket) | **NO** — and, tellingly, **no NEW criterion catches it either except `MOVE1` leg 9**: the eight cell legs all use well-formed records and pass under both conditionings. The second mutation in this unit (after `M71`) that only a deliberately-added leg can see |
| **M79** (`batch` drops the flush) | **NO for M79 itself** — `batch` does not exist. *(CORRECTED-r5, gate M-3r3: r4 justified this with "nothing in either shipped suite asserts that any dispatch surface flushes at all", which is **false**. Two shipped tests do: `test_lifecycle_cli.py:236` drives the `VERB_COMMANDS` branch — the exact site §3.3c rewires — and asserts the spooled event reached the tracked plane, and `:249` does the same for `teach`. So the OTHER half of the extraction has a live shipped regression guard, and `test_lifecycle_cli.py` (20 tests, listed "unchanged" in §2.10) is load-bearing for it — which is why it is `BAT11` leg (c).)* |

**Conclusion: of the 79 mutations, the pre-existing 2,636 + 1,279 tests
catch exactly SIX loudly (M10, M63, M64, M65, M69, M76), catch TWO
invertedly (M1/M2 make a shipped assertion go GREEN on the defect —
which is why `test_rehome.py:200` is rewritten rather than left, §7), and
let the other SEVENTY-ONE pass silently.** Three of those seventy-one are
invisible to everything except one deliberately-added leg: **M71** (only
`MOVE10`'s AST check), **M78** (only `MOVE1` leg 9) and **M79** (only
`BAT11` and `BAT10`'s seeded fixture). **M75** is invisible to any
`SHOW3` fixture whose spool is empty.
coverage hole this unit's two new test files fill, and it is the reason
§5's checks name *positive controls first* wherever the pre-state is what
a naive assertion would already satisfy.

---

## 7. Tests — enumerated

**Two new files**, so no `_ARMOR_SHAS` entry moves (§2.9, `UN5`):

- `plugins/self-learn/cli/tests/test_u_verbs.py`
- `plugins/self-learn/ui/tests/test_u_verbs.py`

**One declared rewrite**, and only one:

- `cli/tests/test_rehome.py:200` —
  `test_resolved_record_refuses_on_status_never_existence` currently
  asserts the hand-rolled string `"record … is not pending (status
  'rejected') — a "`. After `GUARD1`, `rehome` refuses through
  `require_status`, whose message is `"record … is 'rejected' — rehome
  needs status pending/deferred (02 §2)"`. The test is **edited, not
  deleted**, keeps its name and its intent (refuse on status, never
  existence), and gains a comment naming `S-54 / GUARD1` as the
  authority. **The rest of `test_rehome.py` (18 tests) and all of
  `test_rescope.py` (34) are untouched** — `UN3` asserts exactly that
  with a `git diff --stat`.

**Fixtures** (all in `test_u_verbs.py`, all running under the neutralised
environment the CLI suite already requires: `env -u
SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT`,
`SELF_LEARN_MINER=0`, `SELF_LEARN_MINER_AUTOKICK=0`, foreground):

1. **`three_scope_home`** — a ledger home with the user bucket, two skill
   buckets (`skills/a`, `skills/b`), two project buckets with registered
   hosts, and one pending record in each. Drives `MOVE1`, `MOVE2`,
   `MOVE7`, `MOVE8`, `BAT8`.
2. **`host_named_user`** — a registered project host whose directory is
   literally named `user`. Drives `MOVE4` and its three assertions.
3. **`rejected_with_note`** — a rejected record carrying a distinctive
   `resolution_note` and a stale proposal sibling. Drives `STATE4`,
   `STATE5`, `STATE7`.
4. **`deferred_far`** — a deferred record with `deferred_until` well in
   the future and `deferred_count: 2`. Drives `STATE1`, `STATE2`,
   `STATE3`, `MOVE8`.
5. **`routed_fat_target`** — a routed record whose `claude-md` host file
   is ≥ 200 lines with a real compiler-written managed section. Drives
   `DRY1` (the dry-run/real byte comparison), `DRY2`, `SHOW1`,
   `RER1`-`RER2`.
6. **`sheet_mixed`** — a batch sheet with one already-applied item, one
   applying item, one item that refuses, and one hook route. Drives
   `BAT1`, `BAT3`, `BAT6`.
7. **`sheet_half_written`** — the same sheet with `_commit_ledger`
   monkeypatched to raise `HalfWrittenError` on item 3. Drives `BAT2`'s
   `{0,7,1}` leg and `BAT3`'s stop leg.
8. **`sheet_all_verbs`** *(added r4, gate N-2r2 — named verbatim by `BAT8`
   since r3 and never listed here)* — **15 items, one per Phase-1
   permitted verb** (§4.4), each against its own record so every §3.3b
   classification row is exercised exactly once. Drives `BAT8`; its
   `note` item is what `M77` breaks.
9. **`sheet_code_mix`** *(added r4, gate N-2r2)* — five one-item-per-code
   sheets whose item codes are forced by monkeypatch to `{3,6}`,
   `{4,6}`, `{6,1}`, `{0,1,3}` and `{0,7,1}`. Drives `BAT2`'s five legs;
   the first two are the only ones where §3.3a and a raw `max()` disagree.
10. **`sheet_partial_seeded`** *(added r4, gate M-4r2)* — a 4-item sheet
    (3 apply, 1 refuses) run against a home whose **telemetry spool is
    seeded with ≥1 event**, so the end-of-run flush commits. Drives
    `BAT10` leg (a)'s `HEAD +4` assertion and is the only fixture that
    can see `M79`; an empty-spool variant is kept beside it as the
    negative control showing `HEAD +3` and proving the seeding is what
    makes the leg discriminate.
11. **`ref_three_entries`** — a `references/LEARNINGS.md` with three
    entries, the middle one multi-paragraph. Drives `RER5`, `RER6`.
12. **`host_with_routed`** — a registered host with 4 routed records and
    2 pending ones. Drives `HOST1`'s refusal leg, `HOST5`.
13. **`host_pending_only`** *(added r4, gate N-2r2 — named by `HOST1`
    since r3 and never listed)* — a registered host with **2 pending, 0
    routed** records. Drives `HOST1`'s must-still-deregister leg and is
    `M48`'s second witness (the shipped suite supplies only one, §6.1).
14. **`empty_buckets`** — 2 record-less project buckets, 1 record-less
    skill bucket holding an orphan proposal, 1 non-empty bucket, plus the
    user bucket. Drives `HOST4`.
15. **`spooled_home`** *(added r4, gate N-2r2 — `SHOW3`'s whole
    discriminating power and never listed)* — a ledger home with ≥1
    **unflushed** telemetry event in `~/.cache/self-learn/home-<sha>/`.
    Drives `SHOW3`: `show` must leave `HEAD` unchanged against it, while
    the same fixture's positive control (`reject`, a `VERB_COMMANDS`
    member) moves `HEAD` and drains the spool. An empty-spool fixture
    cannot see `M75`.
16. **`scope_mismatch_pending`** *(added r4, gate M-1r2; sibling record
    dropped r6)* — a **pending** record in a project bucket whose
    frontmatter wrongly says `scope: user`. Drives **`MOVE1` leg 9**; the
    live analogue is FW-138's resolved record, which no verb may touch.
    *(r5 deleted leg 9's byte-identity control — `Record.write` is a
    byte-perfect round-trip, so it could never fire — and this entry
    still credited the fixture with driving it, and still carried the
    agreeing sibling that only that control needed. Found by §13.1's own
    sweep, not by a gate.)*
17. **`b206800_bytes`** — a **fixture copy of the pre-change
    `verbs.py`**, used only by `GUARD1`'s positive control and `MOVE6`'s.
    Stored as a small extracted excerpt (the two functions), not the
    whole 5,827-line file, with a comment naming the commit it came from.
18. **`un1_baseline.json`** *(added r4, gate N-2r2 — `UN1`'s committed
    artifact, described in `UN1` but absent from this list)* — the
    `{commit_subject, commit_body, target_sha256, exit_code}` sequence
    generated **once** against the `b206800` read-only worktree and
    committed beside the test, never regenerated by the build.

**Positive controls are asserted FIRST** in every criterion whose
pre-state a naive assertion would already satisfy — `GUARD1`, `MOVE6`,
**`MOVE9`** (the shipped source-scope refusal), `DRY3`, **`SHOW3`**
(`reject` drains the spool), `BAT9`, **`BAT10`** (the empty-spool
`HEAD +3` variant), **`BAT11`** (the **six** shipped
`_flush_spool_best_effort` call sites), `HOST1`, `RER6`, `PH2`, `DOC3`,
`DOC5`, `DOC7` and `DOC8` (its two negative legs)
*(CORRECTED-r6, gate N-1r4: r5 said "five" where its own headline
correction and `BAT11` leg (a) both say **six**, and it still named
`MOVE1`'s byte-identity sibling — a control the same round deleted)* *(list completed r4, gate N-2r2: r3
omitted `SHOW3`, `BAT10` and `MOVE9`, all three of which have one)*. This
is the lrn-ea833a5b/lrn-fc481dcb discipline made structural: a check whose
"pass" output is indistinguishable from "the thing under test is not
there" is worthless until it has a control.

**No test parses human-formatted stdout** (07 §4). Every machine
assertion reads a `--json` envelope, a return value, or the ledger's own
git state.

---

## 8. Failure modes and exit codes

New verbs, and the full set of codes each can reach. **Exactly ONE new
integer is introduced — `EXIT_BATCH_PARTIAL = 8` (§3.3a), for the one
surface that performs many mutations in one invocation; every other row
is one of the eight in §2.1** *(CORRECTED-r4, gate M-2r2: r3 appended the
`8` row to this table while leaving a preamble twenty lines above it that
said no new integer exists)*.

| Condition | Verb | Behaviour | Exit |
|---|---|---|---|
| unknown / malformed record id | all | `LedgerOpsError` → dispatch | **64** |
| record exists, wrong status | `undefer`, `reopen`, `reroute`, `followup add`, `reclassify --type`, `rehome`, `rescope` | `require_status` refuses naming the status; **before any lock** | **1** |
| `--until` in the past | `defer` | refuses naming today and `undefer` | **1** |
| `--until` not `YYYY-MM-DD` | `defer` | argparse-level, unchanged | **64** |
| `--to` unparseable / unregistered target / unknown skill | `rehome`, `rescope` | refuses naming the repair (`host add …`) | **1** |
| destination collision in the target bucket | `rehome`, `rescope` | refuses; "corruption to surface, never to merge into" | **1** |
| already in the requested state | `reroute` (same dest), `followup add` (open follow-up), `undefer` (pending) | refuses naming the state | **1** |
| `--type` change leaves a required section missing | `reclassify` | refuses naming the missing headings; the body is never edited | **1** |
| neither `--kind` nor `--type` | `reclassify` | usage | **64** |
| routed records still target the host | `host remove` | refuses naming count, ids and both repairs | **1** |
| secret-scan hit on `--append` / `--note` / the record file | all writing verbs | `SecretRefusal` | **1** |
| sheet fails whole-sheet validation | `batch` | nothing runs | **64** |
| an item refuses | `batch` | that item records **1**; the run continues; the **process** code is decided later by §3.3a steps 5-6 | item **1** · process **8** (anything landed) or **1** (nothing landed) *(CORRECTED-r4, gate M-2r2 — r3's cell still read "1 (process, by severity)", the replaced rule)* |
| push failed after the batch's commits | `batch` | commits kept | **3** |
| rebase conflict after the batch's commits | `batch` | commits kept, rebase aborted | **4** |
| lock held / git failed before the first mutation | all | nothing written, safe to retry | **6** |
| record moved, commit failed | all writing verbs, `batch` | `_report_half_written` prints the repair; `batch` stops | **7** |
| ledger home missing / not a repo | all | home gate | **5** |
| a preflight refuses under `--dry-run` | `route --dry-run`, `batch --dry-run` | every refusal listed; **nothing written** | **1** |
| everything fine under `--dry-run` | `route --dry-run`, `batch --dry-run` | preview printed; **nothing written** | **0** |
| **≥1 item refused AND ≥1 item's commit landed** | `batch` | the run completed; the envelope carries per-item rc and counts | **8** *(new — `EXIT_BATCH_PARTIAL`)* |
| ≥1 item refused and **zero** commits landed | `batch` | nothing written — `1` keeps its exact ratified meaning | **1** |

**`batch`'s process code is §3.3a's decision procedure, and `8` is the
one new integer in the whole contract.** *(REPLACED-r3, gate M-6: r2's
`max()` over `7 > 4 > 3 > 6 > 1 > 0` returned **1** for the designed-normal
case — 30 applied, 1 refused — which is the integer ratified to mean
"nothing was written". That is a fork, in the case the design was built
for.)* Restated:

1. sheet invalid → **64** · 2. home gate → **5** · both before any item;
3. a ledger-level failure (3/4/6/7) → the worst of those four under
   `7 > 4 > 3 > 6`, with the envelope naming the items that landed first;
4. every item applied or already-applied → **0**;
5. ≥1 refusal **and ≥1 commit landed** → **8**;
6. ≥1 refusal, **zero** commits → **1**.

Steps 5 and 6 split on *"did anything land"*, so **`1` is never emitted
after a write**.

**Where the contract is actually rendered — measured, not assumed**
*(CORRECTED-r5, gate N-3r3: r4 asserted "one table in three renderings,
as it does today" and named `11-telemetry-and-lifecycle.md` as the third.
That document carries **zero** exit-code content, and §2.5's columns are
`Verb | Writes | Commit subject`, which cannot hold a code row.)*

```
$ grep -cE 'exit code|exit [0-9]|EXIT_' docs/specs/self-learn/11-telemetry-and-lifecycle.md
0
$ awk '/^### 2\.5/,/^## 3/' docs/specs/self-learn/11-telemetry-and-lifecycle.md | grep -m1 '^|'
| Verb | Writes | Commit subject |
$ git grep -c "Only 3, 4 and 7"
plugins/self-learn/commands/review.md:1
```

**Three surfaces render the record-verb exit contract, and all three owe
the `8` row** (`DOC8` counts them):

| # | rendering | what it owes |
|---|---|---|
| 1 | `cli.py:13-22` — the source-of-truth prose | the `8` row + `EXIT_BATCH_PARTIAL = 8` beside the other constants |
| 2 | `commands/review.md:230-264` — the full per-code list a reviewer reads | the `8` bullet, **and** `:264`'s *"Only 3, 4 and 7 mean 'the ledger changed'"* → *"Only 3, 4, 7 and 8"* (measured: that sentence occurs **once** in the whole repo) |
| 3 | `skills/self-learn/SKILL.md:96-101` — the model-facing summary (`0 ok · 1 refusal · 3 push failed · 4 rebase conflict · 64 usage`) | the `8` clause, because the review skill is what invokes `batch` |

**Two surfaces owe nothing, and this is stated so a builder does not
"helpfully" edit them.** `commands/teach.md:108-140` renders **teach's
own divergent contract** — its own header says *"The COMPLETE contract —
every code `teach` can return"*, and its `2`/`3`/`4` mean usage / scan
refusal / analyst fallback, not this contract's meanings; `batch` is not
a teach surface. `11-telemetry-and-lifecycle.md` has no exit-code
rendering to amend (measured above); it takes only §11.5's six verb rows
and §3.3c's flush sentence.

---

## 9. IN / OUT

**IN — Phase 1 [A]**

- `ledger_ops`: `move_record` (replacing `rehome_record` + `rescope_record`),
  `REOPENABLE_STATUSES`, `DEFERRED_ONLY`, the `defer_record` past-date
  refusal.
- `verbs`: `_resolve_move_target`, `_move` (backing both `rehome` and
  `rescope`), `undefer`, `reopen`, `note`, `route(..., dry_run=True)`,
  `show`.
- `batch.py`: a new module — `load_sheet`, `classify`, `run`.
- `records`: `history`, `notes`, `append_history`, `append_note`,
  `clear_resolution_note`, and their validator clauses.
- `cli`: the parsers and dispatch for `undefer`, `reopen`, `note`,
  `show`, `batch`, `route --dry-run`, and `--json` on `worker kick|run`
  and `mine run`. **`EXIT_BATCH_PARTIAL = 8`** joins the module
  docstring's contract table (`cli.py:13-22`) — and, with it, the **two
  other measured renderings** of that contract: `commands/review.md`'s
  per-code list (`:230-264`, plus `:264`'s "Only 3, 4 and 7" sentence)
  and `skills/self-learn/SKILL.md:96-101`'s model-facing summary
  (`DOC8`). `commands/teach.md` and `11-telemetry-and-lifecycle.md` are
  **deliberately not** amended — §3.3a says why, and `DOC8`'s negative
  legs pin it *(added r5, gate N-3r3)*. **`show` and `batch` get
  their own `_cmd_*` and stay OUT of `VERB_COMMANDS`** — `show` because
  the flush that set triggers commits (`SHOW3`), `batch` because it takes
  a sheet rather than a record id and owns its own push.
- `cli._mutating_epilogue(home=None, *, no_push=False) -> str` — the ONE
  place 11 §4.2's flush is written (§3.3c), carrying
  `_flush_spool_best_effort`'s exact signature and return so every
  substitution is a one-line in-place edit; **and the rewiring of all six
  shipped raw call sites onto it** — `_cmd_report` (was `:1949`) and
  `_main`'s teach (`:2135`), `VERB_COMMANDS` (`:2145`), followup
  (`:2150`), link (`:2155`) and import (`:2189`) branches. After the fold
  `_flush_spool_best_effort` has exactly one caller (`BAT11` leg (a)).
  *(added r5, gate N-2r3 — r4 carried this in §3.3c/§4.4/`BAT11`/`M79`
  but never in the IN inventory.)*
- `cli/tests/test_lock_invariant.py`: **two `_ARGV_FOR` rows**
  (`"_cmd_batch"`, `"_cmd_show"`) so `test_every_cmd_surface_is_covered`
  stays green (`UN4` leg (c)). `_LOCKS` and `NOT_REPO_TRUTH` unchanged;
  the file is not armor-pinned, so no sha moves.
- `ui/src/self_learn_ui/proposals.py`: **delete** the `rehome` branch's
  source-scope refusal (`:354-358`), keep the target narrowing (`MOVE9`).
- *(the intake gate is the `ui/src/self_learn_ui/proposals.py` bullet above — r3 listed the file twice under two spellings; gate N-5r2)*
- Docs: `03` S-54; `02` §2's amendment; `commands/review.md`'s apply path.

**IN — Phase 2 [B]**

- `verbs`: `reroute`; `_retirement_preflight`'s `reference` branch.
- `compilers`: `retire_reference`; the corrected `_LEARNINGS_HEADER`
  constant and the 08 §1 pin.
- `hosts`: `records_targeting`; `host_remove`'s refusal + `--gate-only`.
- `verbs`/`cli`: `bucket prune`, `followup add`, `reclassify`.
- `ui`: `_VERB_LABELS` + `build_argv` for seven verbs; two keymap
  entries; two card controls; the `NOTICE_PROPOSAL_MOVED` widening.
- Docs: `14` FW-133…**138** + the dated notes on FW-85/114/115; `routing-doctrine.md`
  §3; `11` §2.5's verb table.

**OUT — each is a real thing a builder might reach for**

- **A third move verb (`refile`).** §3.2, refused by measurement.
- **Renaming `rescope` into `rehome`.** Q1, routed to the user; the
  spec's default is retention.
- **Retract / un-route (routed → pending).** FW-133.
- **`--retire` on `host remove`.** §3.6, refused with the reason.
- **New exit-code integers for producers.** §3.7; `PROD3` pins the
  absence.
- **A batch journal file.** §3.3; state-derived resumability instead.
- **Parsing human stdout anywhere.** 07 §4; every machine path is
  `--json`.
- **Widening `PROPOSABLE_VERBS`.** §1 non-objective 4; `MOVE9` pins the
  intake gate that keeps the widened `--to` out of an agent's reach.
- **A key for every new verb.** §4.9; four free letters, two spent,
  FW-136 records the ceiling.
- **Rewriting the seven live `LEARNINGS.md` headers.** §3.5, FW-135 —
  self-learn owns no region in those files.
- **Touching anything U-hostmode owns** — `mode`, `host_path`, the
  compile record, `chezmoi.py`'s deletion, the UI adopt surface.
- **The empty-bucket cleanup as part of a move.** A move that also prunes
  its source is two operations in one commit; `bucket prune` is its own
  verb (Phase 2).
- **`recompile`-time header or drift repair for reference files.** They
  carry no managed region; `selfcheck._check_drift` already treats them
  by entry-marker presence, and this unit does not change that.

---

## 10. Parallel units

Three T2 units are in flight around this one. **U-hostmode lands
BEFORE this unit** (this spec's whole code census is read off its Phase-1
branch); **U-ancestry and U-corrob have already landed on master**
(`0119add`, `8d3d5bc`). The table records the interface this spec
assumes, and nothing more — **no sibling's feature is designed here.**

| Shared surface | U-verbs (this unit) | U-hostmode | U-ancestry (landed) | U-corrob (landed) | Assumption this spec makes |
|---|---|---|---|---|---|
| **`verbs.TargetSpec`** | READS `host_path`, `mode`, `scope_kind`, `target`, `pointer_surface` in the dry-run and reroute paths; **constructs none** | Renames `host_repo`→`host_path`, adds `mode`, forbids `host_path is None` | May construct one for an ancestor | — | **This unit never constructs a `TargetSpec`.** Every spec it touches comes back from `_resolve_target`, so U-hostmode's `mode`-threading (MODE9's AST sweep) has nothing to enforce against here |
| **`verbs._resolve_target`** | **Does not modify it.** `route --dry-run` and `reroute` call it with today's `(scope, destination, ref_name)` triples | Mode-branches the gate/dirty calls **inside** it | Pins its returned target byte-identical (`ANC4`) | — | U-ancestry's `ANC4` says *"if U-verbs lands a new `--dest` grammar first, ANC4's baseline is re-pinned against the new triple set"*. **This unit lands NO new `--dest` grammar** — `reroute --dest` accepts exactly `route --dest`'s vocabulary minus `hook`/`new-skill`. `ANC4`'s baseline is unchanged |
| **`verbs._expected_managed_region` / `_expected_reference_region` / `_expected_pointer_region`** | **READ-ONLY consumers** — `route --dry-run` computes its preview from them (`DRY2`) | Author and own them (§4.5) | — | — | **The three functions' signatures are U-hostmode's to change.** If any grows a parameter, `DRY2`'s delegation test moves with it; the criterion is "no second byte computation exists", not "these signatures are frozen" |
| **`verbs._retirement_preflight` / `_retirement_host_phase`** | **Phase 2** adds the `reference` branch; the `skill-md`/`claude-md`/`new-skill`/`hook` branches are untouched | May mode-branch the host phase | — | — | Additive, one `elif`. A plain host's reference retirement takes `gitops.host_lock(path, mode)` like every other host write — **inside** the `_ledger_write` span (U-hostmode `REC12`), never beside it |
| **`verbs._ledger_write`'s SPAN** | Every new mutating verb opens exactly one span; `batch` opens one span **per item**, never one for the whole run | Widened to cover the compile + host write (§4.5b) | Takes no ledger lock | Producers contend across a local compile | **`batch` must NOT hold one span across the sheet.** A sheet-wide span would block every producer for the length of a 34-item run and would make a mid-sheet failure one unrecoverable half-write instead of N recoverable commits |
| **`ledger_ops`'s status constants** | Adds `REOPENABLE_STATUSES`, `DEFERRED_ONLY` | — | — | — | Closed sets, appended. `require_status`'s signature is unchanged; its `reason=` door (u-verbguards' own) is what any new verb with pre-existing wording would use |
| **`records.Record` frontmatter** | Adds `history` and `notes` (§4.10) | — | — | May add fields | **Distinct keys.** A sibling adding a key collides only on the name; `UN2` pins that neither of ours is written unless a verb writes it |
| **`ledger._LAYOUT` / `reconcile._RECONCILABLE`** | **Adds nothing.** No new ledger artifact — `batch` writes no journal (§3.3) | Adds `compiled/` and `_RECONCILABLE_HOME` | — | Writes to the cache only | **This is the row U-hostmode's own §11 warns about** (*"any sibling adding a ledger artifact must ALSO extend `_RECONCILABLE`"*). U-verbs adds none, deliberately, which is one of §3.3's reasons |
| **`cli._build_parser`** | Adds 5 subcommands (Phase 1) + 3 (Phase 2) + 3 flags | Adds `host add --mode` | — | — | Additive; distinct names |
| **`ui/routes._KNOWN_VERBS` / `_VERB_LABELS`** | Phase 2 adds 7 labels | Phase 2 **removes** `chezmoi-adopt` | — | — | **Sequencing matters.** `UIP1` derives its expectation from the CLI parser, so it stays correct whichever lands first: if U-hostmode's Phase 2 lands after, `chezmoi-adopt` simply leaves the parser and the derived set with it |
| **`ui/templates/partials/action_bar.html`** *(added r3, gate D-5)* | Adds a **Dismiss (k)** control to the `holding` branch (`:121`) and a **Still holding (m)** control to the `resolved` branch (`:156`) | **Phase 2 DELETES the `adopt` branch** (`:188`) and sweeps `ui/templates` for the literal `adopt` (`UIC5`) | — | — | **Merge order: U-hostmode Phase 2 lands FIRST**, then this unit rebases. The edits are ~30 lines apart in one file and semantically disjoint (two `{% elif kind == … %}` arms added, one deleted), so the conflict is textual only — but `UIC5`'s zero-`adopt` sweep would redden if this unit landed an `adopt` reference, and it lands none |
| **`ui/keymap.KEYMAP`** | Adds `k`, `m` | — | — | — | Uniqueness is pinned by the shipped `test_keymap.py`; `UIP4` additionally pins `l`/`z` free |
| **`cli/tests/test_worker_contract.py::_ARMOR_SHAS`** | **Touches nothing** (`UN5`, MEASURED) | — | Re-pinned `test_worker.py` at its merge | Re-pinned `test_u_fake.py` | If a sibling re-pins during this unit's build, the merge is theirs; this unit contributes no motion |
| **`03` / `14`** | `S-54` / `FW-133`-`138` | `S-51` / `FW-122`-`124` | `S-52` / `FW-125`-`127` | `S-53` / `FW-128`-`131` | Reserved, disjoint; ceilings re-derived in §2.0 |

---

## 11. Docs owed at merge

### 11.1 `03-decisions.md` — one new row after `S-53`

**`S-54` — the text is §3 of this spec, in full.** Provenance cell: this
spec; `misc/verb-coverage-2026-08-26.md` (znote
`IbSQPLO0i3vxFCgd96NYu`); the two `defer` commit bodies `59807c2` and
`e6b349a`; the two hand batch scripts `misc/review-batch-2026-08-2{4,5}.sh`.

**One-paragraph form, for the row itself:**

> **S-54 — The ledger's verb surface covers its own state machine: one
> guard vocabulary, one filing-move operation reaching every scope, one
> batch executor, one preview, and real retirement for references.**
> Measured before the build (code at U-hostmode Phase 1 `b206800`, ledger
> at `4444be7`): **10 of 12 record-verbs** already route their status
> precondition through `ledger_ops.require_status`; **`rehome` and
> `rescope` are the two holdouts** (`verbs.py:4281`, `:4467`), carrying
> FW-51's exact shape and a message that names "pending" instead of the
> status set — so this unit's move work also removes the last two
> hand-rolled checks. **The move matrix is completed, not extended by a
> third verb:** `rehome_record` and `rescope_record` were two
> half-complete implementations of one operation (one rewrites `scope:`
> and never stamps `meta.yaml`, the other the reverse), and they are
> replaced by one `move_record` that does both conditionally. Both verb
> names are retained with **one** widened `--to` grammar (`user` |
> `skill:<name>` | `project:<path-or-slug>` | `<path-or-slug>`);
> u-rescope §3 rationale 1's collision hazard is **measured away** — 12
> of 12 live slugs match `^-.+-[0-9a-f]{8}$`, so `user` and `skill:` are
> unreachable as slugs, and the residual (a relative path named `user`)
> has a pinned escape. `skill:<a> → skill:<b>` is ruled **IN**, closing
> **FW-114**: its stated blocker was a *carried* proposal's judgment
> drift, and u-rescope §5 already decided SWEEP, so nothing is carried on
> any leg. **FW-115** closes with the ownership ruling it asked for: the
> widening, not a third verb. **`batch` is the one executor the review
> skill calls** — 42 verb calls across two hand-written scripts,
> transcribed by hand from a 456-line sheet, re-derived the same
> sentinel/`--no-push`/one-push/unpiped-rc scaffolding twice; `batch`
> holds the sentinel once, runs each item `--no-push` through the same
> `verbs.*` functions, reports per-item codes on `--json`, returns the
> and returns a process code by a stated **decision procedure**, stops on
> 5/6/7, continues past a refusal, pushes once, and **refuses hook routes
> (S-29) and every `host` verb (Y-17 disclosed consent)**. **The
> eight-integer exit contract describes ONE mutation; a batch is many, so
> it gains exactly ONE integer — `EXIT_BATCH_PARTIAL = 8`: "batch
> completed; N applied, M refused; the ledger DID change; read the
> envelope"** (`8` is the next free integer — `2` is `proposal validate`'s
> scan hit and `cli.py:71` pins it as un-aliasable). `0` only when every
> item applied; `8` on an applied+refused mix; **`1` only when nothing
> landed**, so the integer ratified to mean "refused, nothing written" is
> never emitted after a write; `3`/`4`/`7` propagate, worst wins, with the
> envelope naming what landed first; `5`/`6`/`64` as today. The contract
> is rendered on **three** measured surfaces, all of which take the new
> row — `cli.py:13-22`, `commands/review.md:230-264` (whose *"Only 3, 4
> and 7 mean 'the ledger changed'"*, the sentence's **only** occurrence
> in the repo, becomes *"Only 3, 4, 7 and 8"*) and
> `skills/self-learn/SKILL.md:96-101` — while `commands/teach.md`'s
> divergent teach-only contract and `11-telemetry-and-lifecycle.md`
> (measured: zero exit-code content) take none. **Idempotence is defined and
> TOTAL:** an item whose effect is already present is SKIPPED as
> `already-applied` — never re-run, never a refusal — for **all 18**
> permitted verbs, decided by a state read; `note --append` is the one
> verb whose effect is not derivable from record state, so `batch` stamps
> a sheet-line idempotency key on the note entry. A second run of an
> applied sheet applies **0** items and exits **0**. **Resumability is
> derived from ledger state, not from a journal** — a journal in the
> ledger is an uncommitted artifact `reconcile` trips on, and one in the
> cache sits in the directory FW-130 measured at 31,291 stray namespaces /
> 1.1 GB, which an operator clears; the ledger's own one-commit-per-item
> history is the durable record, which is also why **`--continue` is
> dropped**: a plain re-run already is one.
> renders the bytes the compiler would write**, computed from
> U-hostmode's own `_expected_*_region` helpers rather than from the
> proposal — the distinction `commands/review.md` already warns about
> (`commands/review.md:86-87`: "the compiler regenerates from the record
> at apply time, so what lands may differ in detail") — and writes
> nothing, takes no lock, holds no sentinel; `batch --dry-run` is a loop
> over it. **One frontmatter key is added, not two:** `history`,
> append-only, closed `event` set `{resolution, routing}`, carrying what
> `reopen` displaces from the write-once `resolution_note` and what
> `reroute` displaces from `routing`; `Record.clear_resolution_note`
> **refuses unless the note is already in `history`**, so the write-once
> field can be displaced but never destroyed. **`reference` retirement
> becomes real — and THIS ROW is its ratification (ruling R4,
> 2026-08-28), deliberately rather than a separate S-row, because the
> measured live-instance count is zero:** `graduate`/`supersede`/`reroute`
> remove the record's
> `## <date> — <id>` block through the shared retirement path — measured
> exposure **27 of 92 routings across 7 files**, live instances **0** (no
> reference-routed record has ever been graduated or superseded), which
> is why it is Phase 2 and why it is still fixed. **`host remove`
> refuses while routed records target the host**, with `--gate-only` as
> the explicit override; **no `--retire` is offered**, because `graduate`
> ("canon already covers it") and `supersede` ("another record replaces
> it") are both *false statements* about a deregistered host's records,
> and writing false resolutions to make a deregistration convenient is
> the same inversion FW-51 was opened about. **Producers get the
> resolution verbs' contract, not new integers:** `worker kick|run` and
> `mine run` gain `--json` outcome envelopes (five and eight and three
> outcome names respectively, all currently collapsed onto exit 0);
> **exit codes are byte-unchanged**, pinned by a negative criterion,
> because `busy → 6` would make a benign concurrent timer tick report
> failure to systemd — FW-85's own named blast radius. **Refused here, by
> name:** a third move verb (`refile` — "only adds vocabulary"); retract
> / un-route (FW-133); a bulk host retirement (§3.6); new producer exit
> integers (FW-134); rewriting the seven live `LEARNINGS.md` headers
> (FW-135 — self-learn owns no region in them); a keybinding per verb
> (FW-136 — four free letters remain, two are spent).

### 11.2 `14-forward-work-map.md` — six new rows, three amended

*(r5: r4 reserved seven. **FW-139 is withdrawn** — gate M-1r3 measured
its stated obstacle false and §3.3c now folds every flush call site, so
there is no residual to register. Six rows, `FW-133`-`FW-138`, no hole.)*

| # | Item | Type | Trigger / when |
|---|---|---|---|
| **FW-133** | **Retract / un-route (routed → pending) has no verb, and this unit did not build one.** `reroute` covers the case with a live motivation — a wrong destination — by rewriting `routing` and moving canon in one motion. A true retraction is different in kind: it must un-write canon *and* return the record to the draft plane, which 02 §2's freeze-at-routing pin forbids (*"at routing the substance freezes … a wrong routed lesson is corrected by a new record with `supersedes:` set"*). Measured: **0 of 92 routings** have ever been retracted, and the two shipped workarounds (`teach --supersedes` + `route`, or `supersede` + a new record) both mint a new id, which is arguably the correct provenance for a re-decision. | WATCH | Trigger: a live case where the record's *substance* was right and only the decision to route at all was wrong — distinct from a wrong destination, which `reroute` now covers. Whoever takes it must first rule on whether un-freezing a routed record is permitted at all, which is a `03` row, not a verb |
| **FW-134** | **The producer exit-code integers stay uninformative, deliberately — the outcome now rides `--json`.** `worker kick` has five outcomes and `mine run` eight; after U-verbs, `mine run` still maps six of its eight to `0` and `worker kick` all five. Refused: `busy → 6`, which is defensible in isolation (`busy` genuinely is "refused before the first mutation") but would make a benign concurrent timer tick report failure to systemd — FW-85's own stated blast radius. `PROD3` pins the absence with a negative criterion so a later builder cannot "improve" it silently. **FW-85's automation prerequisite is met by the envelope**, which is what FW-82's item 4 actually needs. | WATCH | Trigger: a caller that genuinely cannot read stdout (a systemd `OnFailure=` unit, a shell `&&` chain someone will not change). Whoever takes it must first count the live unit files that would change meaning — under FW-119's `serve`, the scheduler calls the library directly and never sees these codes at all |
| **FW-135** | **Seven live `references/LEARNINGS.md` files carry a header saying "this file is append-only" that is one word stale after U-verbs, and self-learn may not fix it.** Measured: 7 files, 27 entries, 570-15,907 B (`~/repos/keyboards`, `~/.config`, `~/repos/3d-printing`, `~/repos/3d-printing/k1c-manta-m5p`, `~/repos/ignomi`, and two skill references dirs). A references file has **no managed marker region**, so every byte outside an entry block is the human's and the compiler's own contract forbids rewriting it; `compilers._LEARNINGS_HEADER` is corrected for newly created files only. | WATCH | Trigger: a references file is recreated (then it gets the new header), or a human asks. A `recompile`-time header refresh is refused for the reason above and should not be re-proposed without a decision row widening what the compiler owns in a references file |
| **FW-136** | **The review UI's keymap is four letters from full, and U-verbs spends two of them.** Measured at `b206800`: 22 entries, used letters `abcdefgijnopqrstuvwxy`, free `hklmz` — and `h` is unusable (printed on the header back-link, bound to nothing; `fixtures/ui-walks.md` W2-F1). U-verbs binds `k` (dismiss-suspect, on the existing holding card) and `m` (confirm-held, on the existing resolved card), leaving `l` and `z`. `reroute`/`reopen`/`undefer`/`rescope`/`supersede` get POST-surface parity with no key, reached through the generic arm-then-confirm path. The structural blocker: `keymap.py`'s own docstring records that *"app.js dispatches on the FIRST key match with no context filter, so every key must be unique across the whole table"* — context gates DISPLAY only. | WATCH | Trigger: the third verb that needs a key. Building it means giving app.js a real context filter, which turns `Context` from a display field into dispatch logic and re-opens every existing binding's uniqueness argument — a design round, not an addition |
| **FW-137** | **`host remove --gate-only` still orphans canon, by design, and there is no honest bulk retirement.** After U-verbs, `host remove` refuses while ≥1 routed record compiles into the host and names both repairs; `--gate-only` is the explicit override and prints the consequence (`recompile` WARNs and skips). What remains open is the case the override serves: a host that is genuinely gone (the directory deleted, the repo moved without `host rebind`), whose records are still `routed` with a `routing.destination` that resolves nowhere. `graduate` and `supersede` are both false statements about those records (§3.6), and `reroute` needs a *new* target, which a human must choose per record. Measured: `host remove` uses all-time **0**, so this has never happened. | WATCH | Trigger: the first real deregistration of a host with routed records. The design question to rule on first: is there a *fourth* terminal status — "orphaned" — or does the honest answer stay "a human reroutes each one"? Adding a status is a `02 §2` amendment and touches `report`'s every metric |

| **FW-138** | **One live record's `scope:` disagrees with its bucket, and no verb can repair it.** Measured 2026-08-28 by walking all 18 buckets and comparing each record's `scope:` against its bucket's own identity: **1 of 152** records mismatches — `user/resolved/lrn-c826137f.md` carries `scope: skill:cron-claude` while sitting in the `user` bucket. Bucket identity is `(scope, name)`, so this record is reachable through the user bucket and invisible to anything that re-derives the bucket from the scope (`ledger_ops.bucket_dir_for_scope`). It is **`resolved`**, so U-verbs' move verbs refuse it on status (`require_status(..., LIVE_STATUSES, ...)`) — deliberately: 02 §2 freezes substance at routing, and silently rewriting a frozen record's filing is the thing that pin forbids. **And it is one of the 27 reference routings** — `routed_at: 2026-08-10`, `destination: reference`, `by: analyst` — so its canon compiled through its *scope* into `~/repos/claude-skills/plugins/cron-claude/skills/cron-claude/references/LEARNINGS.md` (`grep -n '^## '` there → the file's single entry is `## 2026-08-10 — lrn-c826137f`), while its *bucket* says user. Phase 2's reference retirement resolves the file the same way the write did, so it lands correctly for this record; the residual is that `discover_buckets`-driven consumers and `bucket_dir_for_scope`-driven ones disagree about where this record lives. | WATCH | Trigger: a second instance, or a `recompile` that visibly mis-files this record's canon. The repair needs a ruling first — does a filing-only fix on a resolved record count as "substance" (02 §2 says the filing is never frozen, but also that the record does not move once resolved)? That is a `03` row, not a verb |

**Three existing rows gain a dated disposition note** (the register's own
rule: a settled row is amended in place, never removed):

> **FW-85** *(2026-08-28 — **partly closed by S-54**: `worker kick|run`
> and `mine run` gain `--json` outcome envelopes, which is the
> machine-readable channel FW-82's item 4 needs and the one this row's
> own trigger names second. The exit-code integers are deliberately
> unchanged; the residual is **FW-134**.)*
>
> **FW-114** *(2026-08-28 — **CLOSED by S-54**: `skill:<a> →
> skill:<b>` is supported. The row's stated blocker — "does a **carried**
> skill→skill proposal degrade gracefully?" — is moot for the shipped
> design: u-rescope §5 decided SWEEP, so no proposal is carried across
> any bucket boundary and there is no carried-proposal failure mode to
> characterise on this leg or any other.)*
>
> **FW-115** *(2026-08-28 — **CLOSED by S-54** with the ownership ruling
> this row asked for: **the widening, not a third verb.** `rehome` and
> `rescope` share one `--to` grammar, one resolver and one file-op
> (`ledger_ops.move_record`). The row's objection — that u-rescope §3
> rationale 1 argued against two `--to` shapes on one verb — is answered
> by measurement, not by overruling: every live project slug matches
> `^-.+-[0-9a-f]{8}$`, so the reserved literals `user` and `skill:` are
> unreachable as slugs and the union grammar has no ambiguity to
> resolve.)*

### 11.3 `02-schema.md` §2 — one amendment paragraph

Inserted after the 2026-08-24 U-dismiss amendment block:

> **Amendment 2026-08-28 (S-54 / U-verbs):** the frontmatter gains
> **`history`** and **`notes`**, both optional, both append-only, both
> the same metadata class as `recurrences` — verb-written, mutable in
> every status, never part of the substance freeze. **`history`** records
> a value a verb *displaced*: its `event` is a closed set,
> `{"resolution", "routing"}`. `reopen` (rejected → pending) appends
> `{at, event: resolution, status, note}` carrying the old
> `resolution_note`; `reroute` appends `{at, event: routing, routing}`
> carrying the old routing block. **`notes`** records commentary a human
> *added* (`self-learn note <id> --append`), in any status; an entry may
> also carry an optional **`key`**, an idempotency token supplied by the
> caller (`--key`, written only by `self-learn batch` — the hash of the
> sheet line that produced it) so a re-run of an applied sheet appends
> nothing. `key` is never generated by the record layer, and a human's
> `note` call omits it, because two identical observations on two days
> are two facts. The two are
> deliberately separate keys: merging "what was displaced" with "what was
> added" makes both unreadable.
>
> **`resolution_note` stays write-once, and gains exactly one clearing
> door.** `Record.clear_resolution_note()` is the only writer permitted
> to set it back to `null`, and it **refuses unless that exact note
> already appears in a `history` entry with `event: "resolution"`** — so
> the field can be displaced but never destroyed, and the M2
> rejected-proposal digest's fuel survives a reopen. A record that has
> never met `reopen` or `reroute` carries **neither key** — absent, not
> empty.
>
> **The `scope`/`kind`-vs-`type` asymmetry is now a verb.** This section
> already says the filing is never frozen (`scope`, `kind`) while
> `created_at`, `type`, `source` and the body freeze at routing.
> `self-learn reclassify` implements exactly that split: `--kind` in
> every status, `--type` only while `pending`/`deferred`, and a `--type`
> change re-validates `REQUIRED_SECTIONS` and refuses rather than editing
> the body to fit.

Also: `02 §2`'s `rehome`/`rescope` bullets (`:398`, `:453`) gain one
sentence each naming the widened `--to` vocabulary. Their **pinned commit
subjects are unchanged**, which is why no other doc site moves.

### 11.4 `commands/review.md` — the apply path

The Apply-a-batch shape changes from "call each verb" to:

> **Applying a batch.** Write the decisions to a sheet
> (`version: 1`, `items: [{id, verb, …}]`) and run
> `self-learn batch <sheet.yaml> --dry-run` first — it reports, per item,
> the target the compiler would write, every refusal (all of them, not
> the first), and any sheet-level prerequisite such as an unregistered
> host. Fix the sheet, then run `self-learn batch <sheet.yaml>`. It holds
> the sentinel once, runs every item `--no-push`, pushes once, and
> releases. **Never hand-write a batch script.**
>
> Read `batch`'s **process** exit code as a whole-run verdict, and its
> `--json` envelope for the per-item codes:
>
> - **0** — every item applied (or was already applied). Nothing left to do.
> - **8** — the run completed with a mix: N items applied, M refused. **The
>   ledger DID change.** Read the envelope, fix the M, re-run the same
>   sheet — the N already applied are skipped.
> - **1** — every item refused and **nothing was written**, the same
>   meaning `1` has for every other verb.
> - **3 / 4 / 7** — a git step failed *after* items had landed; the
>   envelope names which landed. Same repairs as for a single verb.
> - **6 / 5 / 64** — nothing was written.
>
> The run stops on the first 5/6/7 and continues past a refusal.
> **Re-running an applied sheet is a no-op** — every item classifies
> `already-applied` from the record's current state, so a corrected sheet
> is always safe to re-run whole.
>
> A **hook** route and any `host` verb are refused inside a sheet, by
> design (S-29; Y-17's disclosed consent). Sequence those by hand, first.

*(N-10: the shipped `commands/review.md` carries **zero** `misc/`
references today — `grep -c 'misc/' plugins/self-learn/commands/review.md`
→ 0 — and this amendment adds none. r2's draft named
`misc/review-batch-2026-08-2{4,5}.sh` in the shipped text; those paths are
git-excluded and machine-local, and the `misc/` precedent is register-side
only (`03-decisions.md` 1 hit, `14-forward-work-map.md` 4). The motivating
scripts stay cited in this spec and in `S-54`, where a reader can reach
them, and out of the public doc.)*

The exit-code section (`:230-264`) gains the **`8`** row and amends its
closing sentence from *"Only 3, 4 and 7 mean 'the ledger changed'"* to
*"Only 3, 4, 7 and 8 mean 'the ledger changed'"*, plus one line each for
the new verbs' refusals. The Scope-mismatch paragraph (`:116-123`,
measured) names the widened `--to` vocabulary, and the "not holding"
card's Dismiss line (`:219`) notes that the UI now offers it too.

### 11.5 `routing-doctrine.md` §3 and `11-telemetry-and-lifecycle.md` §2.5

**Into `routing-doctrine.md` §3**, replacing the parenthetical in *"Propose
a re-home (the `rehome` verb where you have it, prose in `rationale`
where you don't)"*:

> (the `rehome` verb where you have it — its `--to` now reaches every
> scope: `user`, `skill:<name>`, `project:<path-or-slug>`, or a bare
> project path/slug — prose in `rationale` where you don't. **You may
> propose only a PROJECT target**: a scope change is a human verb, so say
> it in `rationale` and let the human type it.)

**Into `11-telemetry-and-lifecycle.md` §2.5's verb table**, **six** rows
in the shipped format, each with its source status, its refusals and its
pinned commit subject *(pinned r3, gate D-3 — r2 left the Phase-1 three
to "whichever table §2.5 keeps", which `DOC5` could not count)*:

| verb | source status | commit subject | ph |
|---|---|---|---|
| `undefer` | `deferred` | `self-learn: undefer lrn-…` | 1 |
| `reopen` | `rejected` | `self-learn: reopen lrn-…` | 1 |
| `note` | any | `self-learn: note lrn-…` | 1 |
| `reroute` | `routed` | `self-learn: reroute lrn-… → <target>` | 2 |
| `followup add` | `routed` | `self-learn: follow-up add lrn-…` | 2 |
| `reclassify` | `--kind` any / `--type` live only | `self-learn: reclassify lrn-…` | 2 |

All six go in **§2.5's own table** — the one `followup done`,
`confirm-recurrence`, `dismiss-suspect` and `confirm-held` already
occupy — so `DOC5`'s `grep -c` has one range to count and finds **6**.
`batch` gets no row there: it resolves nothing itself, and its
documentation is `commands/review.md` (§11.4). **§2.5 takes NO
exit-code row** *(CORRECTED-r5, gate N-3r3: r4 asked for one here as
"the third rendering". Measured — `11-telemetry-and-lifecycle.md` has
zero exit-code content and §2.5's columns are `Verb | Writes | Commit
subject`, which cannot hold a code row. **§8** carries the measured list
of the three surfaces that really render the contract — §3.3a points
there rather than repeating it.)* What §4.2's bullet DOES take is
§3.3c's flush sentence.

---

## 12. Questions — all RULED

The five questions r1 raised were ruled by the orchestrator on
**2026-08-28**. §3.8 carries each ruling as a decision with its
reasoning; this table is the index, so a reader arriving at "open
questions" finds no open question.

| # | Question | Ruling | Where it landed |
|---|---|---|---|
| **Q1** | Retire `rescope` into `rehome`, or keep both names? | **KEEP BOTH — as two entry points over ONE implementation and ONE grammar.** Retiring a ratified surface name buys nothing a user can feel; a *second implementation* is what the root-cause preference forbids, and Finding V-2 says the codebase already has one | §3.8 **R1** · new **`MOVE10`** (no file-op in either verb body) · new **`M71`** (a divergent write in one entry point) · §3.2's four-rationale table unchanged |
| **Q2** | Ship `skill:<a> → skill:<b>` (FW-114)? | **SHIP IT.** The row's blocker was a *carried* proposal's drift; u-rescope §5 decided SWEEP, so nothing is carried on any leg and that failure mode cannot occur | §3.8 **R2** · §3.2c · `MOVE1`'s eight legs (unchanged) · **FW-114 closes** with the dated note in §11.2 |
| **Q3** | Does `batch` belong in the CLI or the review skill? | **CLI.** The sentinel hold, the single push, the severity ordering and already-applied idempotence are ledger semantics; the skill becomes a thin caller | §3.8 **R3** · §3.3 (unchanged) · new **`DOC7`** (three named `review.md` sections, each checked in its own heading range) · new **`M73`** |
| **Q4** | Reference retirement changes shipped `graduate`/`supersede`. Own S-row? | **FOLD into `S-54`.** Measured live-instance count is **0**, so nothing a human relies on changes, and the old behaviour is documented nowhere but a docstring | §3.8 **R4** · §11.1's row now states that it IS the ratification, keeping **27 of 92 across 7 files** as the evidence · `RER5`/`RER6` unchanged |
| **Q5** | `note --append` writes a key nothing reads. | **SHIP IT, and render it on `show` in the same phase**, so the key is never write-only for a release | §3.8 **R5** · **`STATE8` gains a second leg** (the note round-trips through `show`) · **`SHOW1` gains `notes`** · new **`M72`** |

**Nothing here blocks the code gate.** Q1 and Q3 changed the criterion
set and are folded above; Q2 and Q4 changed no criterion; Q5 extended two.

### 12.1 Blind spec gate r1 — every finding, and what changed

**Verdict: NOT SOUND — 0 Blockers · 9 Majors · 10 Nits · 6 Defers**
(znote `AosifSV6kYD2d4jyur1OF`). The gate re-ran ~150 quoted numbers
against its own throwaway read-only worktree at `b206800`; **all but two
reproduced byte-exactly**, and the two that did not are `M-7` and `M-9`
below. Nothing in the census, the phase split, §3.8's five rulings, or
the move design moved. Every finding is folded; the two that needed a
design decision (`M-5`, `M-6`) were ruled by the orchestrator and are
recorded in §3.3a and §3.3b.

| # | Finding | Fold |
|---|---|---|
| **M-1** | `BAT2`'s two legs both give the same answer under `M30`'s raw `max()`, so the named test could not redden its own mutation | `BAT2` rewritten with the two **discriminating** legs `{3,6}⇒3` and `{6,1}⇒6`; `M30`'s cell now names the `{3,6}` leg |
| **M-2** | `UN4`'s "`git diff` is empty" is unsatisfiable — `test_lock_invariant.py` carries `_ARGV_FOR` (`:600-635`) + `test_every_cmd_surface_is_covered`, which FAILS on a new `_cmd_*`; and `show` must not join `VERB_COMMANDS`, whose flush commits | `UN4` rewritten: diff scoped to `_LOCKS`/`NOT_REPO_TRUTH`, two `_ARGV_FOR` rows now an owed edit (§9), file measured **not** armor-pinned. **New `SHOW3`** + **`M75`/`M76`**; §4.3 states the wiring |
| **M-3** | `UIP1`'s positional-`ID` heuristic swept in `proposal validate` / `host commit-drift` and missed `supersede` (`OLD_ID`/`NEW_ID`); `M58` reddened nothing | `UIP1` rewritten around a normative **`UI_PARITY_VERBS`** (17, listed) plus an exhaustiveness leg over `cli.VERB_COMMANDS`; `M58` retargeted to dropping `supersede`, which reddens leg (a) |
| **M-4** | `proposals._resolve_rehome_to` does not exist, and the real gate refuses on the record's **source scope** — making §11.5's doctrine amendment unobeyable | §4.1 names `validate_proposal`'s `rehome` branch (`proposals.py:348-372`) and **specifies the source-scope refusal at `:354-358` is deleted**; `MOVE9` gains the user→project proposal leg with the shipped refusal as its positive control |
| **M-5** | 15 verbs permitted, 9 classified; `note` / `link-contradicts` / `followup-done` / `confirm-held` break `BAT8` | **Ruled.** §3.3b defines `already-applied` and classifies **all 18**; `note` gets a sheet-line idempotency key (`--key`, §4.2); `BAT8` widened to a 15-verb sheet; **`M77`** added |
| **M-6** | The severity order forks the contract: 30 applied + 1 refused exited **1**, the integer meaning "nothing written" | **Ruled.** §3.3a extends the contract by **one** integer, `EXIT_BATCH_PARTIAL = 8`, with a decision procedure in which `1` is emitted only when nothing landed. **New `BAT10`** + **`M74`**; §8, §9, §11.1 and §11.4 all take the same row |
| **M-7** | "all 4 `TestHostRemove` tests use a PENDING record" — measured, **1 of 4** creates a record at all | `HOST1` and `M48` restated; a `host_pending_only` fixture added so `M48` has a second witness |
| **M-8** | `last_confirmed` on 0 records was a bare zero, no command, no control | §4.9 pastes both lines (0, control 152) |
| **M-9** | `DOC7`'s third control claimed 1, measured **2** | corrected; the `## Session end` range carries `sentinel release` and `push` |
| **N-1** | `BAT4` counted `sentinel.hold` calls and asserted 1 — a correct batch makes N+1 | `BAT4` asserts **1 owning** hold and **N+1** total; §4.4 quotes `sentinel.py:98-111` |
| **N-2** | `sentinel.state()` does not exist | → `sentinel.is_live()` (`:68`) |
| **N-3** | The `LEARNINGS.md` header called "hand-owned"; self-learn wrote it | §3.5/FW-135 corrected with both texts pasted; the refusal now rests only on "no managed marker region" |
| **N-4** | Dangling "§2.3 SECTION D" | → the `grep -h '^scope: '` census |
| **N-5** | "all ≤ 2026-07-15" — the bootstrap commit is 2026-07-16 | corrected, with the command |
| **N-6** | Dangling `SHOW4` | → `SHOW2` |
| **N-7** | `SHOW1` asserts "every key §4.3 lists"; §4.3 listed none | §4.3 gains the full `show --json` block, `canon.present` included |
| **N-8** | `UN1`'s baseline had no stated provenance | generated once against the `b206800` read-only worktree, committed with the commit named, **never regenerated by the build** |
| **N-9** | The item-key set omitted `route`'s `--collapse` / `--follow-up` / `--allow-empty-glob` | §4.4's table is now per-verb and complete; a merge-collapse route is expressible |
| **N-10** | §11.4 would put `misc/` paths into a shipped public doc (0 today) | removed; the scripts stay cited here and in `S-54` |
| **D-1** | `PH2` unsatisfiable for `batch` | **Ruled.** `PH2` names its eight verbs and runs `batch` with a one-line `undefer` sheet — the discriminating choice |
| **D-2** | `--continue` had no procedure, no criterion, no distinct behaviour | **Ruled: DROPPED** |
| **D-3** | Phase-1 verbs' `11 §2.5` rows unpinned | `DOC5` counts **6** rows; §11.5 tables all six |
| **D-4** | `_Retirement` has two fields and "at most one of the two" | §4.5 specifies the third field `reference: tuple[Path, TargetSpec] \| None` and the third arm |
| **D-5** | `action_bar.html` shared with U-hostmode Phase 2, absent from §10 | row added; **merge order: hostmode first** |
| **D-6** | §3.2a step 5 (scope literal) contradicts §4.1 step 5 (bucket) | §3.2a fixed to the BUCKET — and the check surfaced **Finding V-6**: 1 of 152 live records disagrees with its bucket (**FW-138**) |

---

### 12.2 Blind spec gate r2 — every finding, and what changed

**Verdict: NOT SOUND — 0 Blockers · 4 Majors · 6 Nits · 0 Defers**
(znote `xC0jWpAeV2NkyZymJ9phy`). The gate re-verified **all 25 r1
findings as fixed**, re-measured everything r3 touched, and found the
four Majors to be **new defects the r3 fold introduced** — two internal
contradictions, one criterion that reddens a correct build, and one
doctrine the ruling's own logic exposed. All ten are folded; the one that
needed a decision (`M-4r2`) was ruled by the orchestrator and lives in
§3.3c.

| # | Finding | Fold |
|---|---|---|
| **M-1r2** | §3.2a step 5 contradicted itself: conditioned on the BUCKET-derived source scope, then claimed a project→project repair — where both sides are `"project"`, so `set_scope` never fires. The repair was unreachable in the leg it named, and untested | Step 5 now reads **`record.scope != target_scope`** — the FIELD — with §4.1 step 6's same-place refusal still reading the BUCKET, and the two questions separated in writing. **`MOVE1` gains leg 9** (a pending record whose frontmatter disagrees, repaired by a project→project move) plus a byte-identity control, and **`M78`** conditions on the bucket and reddens leg 9 alone |
| **M-2r2** | §8 still carried the replaced rule in two places: a preamble saying *"No new integer is introduced"* twenty lines above the `8` row, and a refusal row whose Exit cell read *"1 (process, by severity)"* | Preamble → *"Exactly ONE new integer … every other row is one of the eight in §2.1"*; the refusal row's cell → *item **1** · process **8** or **1** per §3.3a steps 5-6* |
| **M-3r2** | `DOC5`'s 6-row regex required a closing backtick right after the verb name; the shipped §2.5 rows put the whole invocation in one code span, so a builder following §11.5 reddens `DOC5` and one satisfying `DOC5` writes non-matching rows | Regex → `[ `]` class. **Measured control**: `^\| `(confirm-held\|followup done\|link contradicts)[ `]` = **3** on the shipped rows, while r3's trailing-backtick form = **0** on those same rows |
| **M-4r2** | `batch` never flushed the telemetry spool. r3 put it outside `VERB_COMMANDS` (correctly, for `SHOW3`), and 11 §4.2's rule lives only in that branch — so a review session that flushed 34 times would flush **zero** | **Ruled, and fixed at the root.** Measured: the rule is hand-repeated in **five** `_main` branches (`:2135/:2145/:2150/:2155/:2189`). New §3.3c extracts **`cli._mutating_epilogue`** with **exactly two callers** (the `VERB_COMMANDS` branch and `batch.run`); `batch` flushes once after the item loop, inside the hold, before the push, `no_push=True`. **New `BAT11`** + **`M79`**; **`BAT10` leg (a)** now seeds the spool and asserts `HEAD +4` (3 items + 1 flush) — the empty-spool form could not see `M79`; `DOC5` gains the 11 §4.2 doctrine sentence; the four legacy callers are **FW-139** *(withdrawn at r5 — see §12.3 M-1r3)* |
| **N-1r2** | `--key` was specified in §4.2/§3.3b but absent from `append_note`'s signature and from the 02 §2 amendment | `Record.append_note(text, *, by="human", key=None)` and `Record.note_has_key(key)`; §11.3's amendment now describes `key` and says the record layer never generates it |
| **N-2r2** | §7's fixture inventory was stale — `sheet_all_verbs`, `host_pending_only`, `SHOW3`'s spooled home, `BAT2`'s code-mix sheets and `UN1`'s baseline all unlisted, item 6 still crediting `sheet_mixed` for `BAT8` | Inventory rebuilt to **18** fixtures with the r4 additions marked; the positive-control list now includes `SHOW3`, `BAT10` and `MOVE9` |
| **N-3r2** | `BAT2` claimed `{3,6}` and `{6,1}` are the disagreeing pairs — `{6,1}` **agrees**, and `{4,6}` disagrees and was untested | Claim corrected to **`{3,6}` and `{4,6}`**; `{4,6}` added as a fifth leg; `{6,1}` kept and relabelled a non-discriminating pin |
| **N-4r2** | V-6's walker was the one command in the spec with an elided body, against §0's own rule | The walker is written out in full in §3.2a, with its measured output (18 buckets / 152 records / 1 mismatch) |
| **N-5r2** | Three stale cross-refs: §9 said `FW-133…137`; §12.1 cited `proposals.py:348-365`; §9 listed `proposals.py` under two spellings | All three corrected (`FW-133…139` after this round, `:348-372`, one bullet) |
| **N-6r2** | §3.3b row 4 skipped an `undefer` item aimed at a **never-deferred** record, where the verb would refuse naming the status — while row 5 has exactly the guard that prevents it | Row 4 now requires `status == pending` **and** `deferred_count >= 1`; `undefer` never clears that counter, so it is the durable witness that a defer happened |

---

### 12.3 Blind spec gate r3 — every finding, and what changed

**Verdict: NOT SOUND — 0 Blockers · 3 Majors · 3 Nits · 0 Defers**
(znote `pwQtXZt7aHOa0FEl6DRXE`). The gate verified **all ten r2 findings
fixed at the root**, re-ran every changed number (all reproduce), and
**executed V-6's walker verbatim from the fence** — identical output. The
three Majors are again new: two claims this fold introduced that the gate
could measure and that came back **false**, and one deferral whose stated
obstacle does not exist.

| # | Finding | Fold |
|---|---|---|
| **M-1r3** | FW-139 deferred four flush call sites on the grounds that folding them *"reorders `teach`'s worker kick and `import`'s exit-code branch"*. Measured: both branches are `code = X(); flush(); if <cond>: kick(); return code`, so an in-place substitution moves nothing — **the obstacle is false**. The deferral was also self-locking: `BAT11`'s control asserted the raw count "drops to four", so a later unit closing FW-139 would have *reddened* it | **Ruled: fold all of them.** §3.3c rewritten. And the census got **larger**: `grep -c` finds **7** occurrences = 1 def + **SIX** call sites, because `_cmd_report:1949` is a sixth — its shipped comment reads verbatim *"report is a flushing verb (11 §4.2)"*, the same rule hand-copied again. The enumerated caller set is now **seven sites** (5 `_main` + `_cmd_report` + `batch.run`), listed as a table §5 reads as data. **FW-139 is WITHDRAWN**; the ceiling returns to **FW-138** with no numbered hole |
| **M-2r3** | `MOVE1` leg 9's byte-identity control cannot fire: the gate measured `Record.write` to be a **byte-perfect round-trip** on four real ledger records, so a same-value write is indistinguishable from no write and "rewrite unconditionally" stays GREEN | **Ruled: take the simpler rule.** §3.2a step 5 now writes `scope:` **unconditionally** from the landing bucket — one rule, no predicate — and states the two consequences the gate named: the `09:2069` pin is satisfied by the round-trip (step 6 writes on every leg anyway), and the only observable fork is `M78`'s. The control and the third mutation cell are **deleted**; leg 9 and `M78` stand, with `M78` retargeted to *adding* a bucket-equality condition. §4.1 step 6's refusal still reads the bucket |
| **M-3r3** | §6.1's `M79` row claimed *"nothing in either shipped suite asserts that any dispatch surface flushes at all"* — **false**: `test_lifecycle_cli.py:236` drives the `VERB_COMMANDS` branch (the exact site §3.3c rewires) and asserts the spooled event reached the tracked plane; `:249` does the same for `teach` | Row corrected — `M79` itself is invisible, but the extraction's *other* half has a live shipped guard. Those two tests become **`BAT11` leg (c)**, the one leg backed by a shipped test rather than a new one, and `test_lifecycle_cli.py` is re-labelled load-bearing |
| **N-1r3** | `BAT11`'s "exactly two callers" compared a **set of function names**, so a second epilogue call added inside `_main` would pass | Leg (b) now collects `(module, function, lineno)` and asserts the **site count** against the spec's table, with `_main` appearing five times — counting sites, not names |
| **N-2r3** | §9's IN list never named `cli._mutating_epilogue` or the rewirings | Added, with all six shipped call sites enumerated |
| **N-3r3** | *"one table in three renderings, as it does today"* was false: `11-telemetry-and-lifecycle.md` has **zero** exit-code content, and §2.5's columns are `Verb \| Writes \| Commit subject`, which cannot hold a code row | §3.3a now carries the **measured** rendering list: three surfaces owe the `8` row (`cli.py:13-22`, `review.md:230-264`, `SKILL.md:96-101`) and two owe **nothing** — `teach.md` renders teach's own divergent contract (its `2/3/4` mean usage / scan refusal / analyst fallback), `11` has no exit-code content. **New `DOC8`** counts all five, positive **and** negative, with `git grep -c "Only 3, 4 and 7"` = **1** as its control; **new `M80`** is the "helpful completion" onto `teach.md`. §11.5's owed §2.5 exit row is withdrawn |

---

### 12.4 Blind spec gate r4 — every finding, and the sweep that ends the class

**Verdict: NOT SOUND — 0 Blockers · 1 Major · 3 Nits · 0 Defers**
(znote `we6w98VwqYC8aIYfzsWus`). The gate verified **all six r3 findings
fixed**, noted that two were fixed better than asked (the census grew
under re-measurement; the dead control was deleted rather than patched),
and re-measured every number r5 changed — all reproduce. Folded here
**without a further gate round** (repricing rule: only a contradiction
that must be resolved by choosing triggers one; all four are bounded text
substitutions).

| # | Finding | Fold |
|---|---|---|
| **M-1r4** | §3.3a still ended with *"`11-telemetry-and-lifecycle.md` and `commands/review.md:264` take the same row … one table in three renderings, as it does today"* — the sentence `N-3r3` measured false. Three places in the same spec contradicted it (§8's measured list, `DOC8`'s negative leg, §11.5). Worse, §11.5's own correction pointed readers at *"§3.3a lists the three surfaces"* — **§3.3a listed nothing**; the list is in **§8** | §3.3a's final paragraph replaced with a pointer to §8's measured list, naming both non-renderings; §11.5's cross-reference repointed from §3.3a to **§8** |
| **N-1r4** | §7's positive-control list was stale twice: *"`BAT11` (the **five** shipped call sites)"* against r5's own headline **six**, and *"`MOVE1` (leg 9's **byte-identity sibling**)"* — a control r5 deleted in the same round | Both corrected; `DOC8`'s two negative legs added to the list |
| **N-2r4** | §3.3c said the `_cmd_report` comment sits *"two lines above"* the call — measured, `:1945` and `:1949`, **four** lines (U-readref's two-line note between). And `MOVE1`'s statement still called leg 9 *"the leg §3.2a step 5's **condition** decides"* though step 5 no longer has one | Distance corrected (the quoted comment text was already exact); leg 9's statement reworded to *"the only leg on which the unconditional write and `M78`'s added condition give different answers"* |
| **N-3r4** | `BAT11` leg (c)'s mutation cell over-claimed: a **double flush** (raw call left AND epilogue added) leaves `test_lifecycle_cli.py:236` GREEN — the second flush finds an empty spool, `telemetry._commit_flush` early-returns, and `support.py:99-115`'s `last_verb_sha`/`verb_subject` deliberately skip telemetry-flush commits, so both assertions still hold. That case is caught by leg **(a)** | Cell split: *flush lost ⇒ (c) red; raw call left ⇒ (a) red at 2 callers, not (c)* — with the measured reason, and the note that the criterion discriminates as a whole because (a) covers what (c) cannot |

**The class the gate named, and the fix.** Three rounds running, a
correction landed in a **new** location while the **original** false
sentence survived: r2 `M-2r2` (§8's preamble, after §3.3a was fixed), r3
`N-3r3` (§3.3a, after §11.5 was fixed), r4 `M-1r4` (§3.3a again). The
per-finding fix is a substitution; the **class** fix is a sweep for the
corrected claim's own words, run over the whole spec after every fold.
§13.1 carries it, with the r6 run and its output.

---

## 13. What could NOT be measured

- **Whether a review batch actually gets faster or safer.** The two
  scripts both returned `rc=0` on every one of their 48 `run` lines
  (§2.4), so there is no failed batch to compare against. `batch`'s value
  is argued from the *scaffolding re-derivation* and the *unpreflighted
  sheet*, both of which are visible in the scripts, not from a measured
  failure rate.
- **The `reference` retirement in production.** 0 reference-routed
  records have ever been graduated or superseded (§2.5), so `RER5`/`RER6`
  are proved by fixture only. The 15-entry
  `home-assistant/references/LEARNINGS.md` is the only file where a
  multi-paragraph middle entry exists live, and it was read for shape,
  not modified.
- **`host remove` against a real host.** 0 uses ever (§2.1). `HOST1`'s
  positive control runs against a fixture, and the "recompile WARNs and
  skips" consequence is quoted from the assessment's probe log
  (`misc/verb-probe-2026-08-26.log`), **not re-measured here** — this
  spec ran no verb against any ledger.
- **The UI at runtime.** `UIP3`/`UIP5` are specified against the
  templates and routes as read; no browser was launched, and the
  Playwright legs are left to the build (FW-81's 14 environmentally
  failing UI tests are a known pre-existing condition and are not this
  unit's to fix).
- **`batch`'s behaviour under a real concurrent producer.** §10 asserts
  that `batch` must open one `_ledger_write` span *per item*, and the
  reasoning is structural (a sheet-wide span blocks producers for the
  length of the run and converts N recoverable commits into one
  unrecoverable half-write). It is **not** measured; U-hostmode's own
  `FW-123` records that the lock-invariant walker cannot see this class
  either. A two-process contention test is specified (`BAT4` is not it —
  `BAT4` counts sentinel holds) and is left to the build.
- **Whether `--json` on the producers is enough for FW-82.** FW-82's
  autonomous reviewer does not exist, so "enough" is an argument from its
  item-4 text, not an observation.
- **`b206800` is now read through a THROWAWAY DETACHED WORKTREE, not the
  live `u-hostmode` one** *(r3)*. Every r3 re-measurement ran in
  `.claude/worktrees/u-verbs-ro` (`git worktree add --detach … b206800`,
  porcelain clean, removed after), because the `u-hostmode` worktree is
  being edited by another agent. What could not be measured is whether
  that agent's in-flight fold changes any symbol this spec cites; §10
  states the assumption, and every citation carries a line number a gate
  can re-run against the same detached commit.
- **U-hostmode's own fold, which was IN FLIGHT while this spec was
  written.** Observed at 05:58 on 2026-08-28: the `u-hostmode` worktree's
  `git status` went from clean to three modified files —
  `cli/src/self_learn/compiled.py`, `cli/tests/test_hostmode.py`,
  `cli/tests/test_resolution_evidence.py` (117 insertions) — with `HEAD`
  still at `b206800`. Re-checked immediately: **`verbs.py`,
  `ledger_ops.py`, `hosts.py` and `compilers.py` are byte-unchanged**, so
  every line number this spec cites still holds, and `compiled.py`'s three
  cited symbols (`sha256_hex`, `region_key`, `write_entry`) show **no
  `def`-line change** in the diff. What could not be measured is where
  that fold lands: if it moves any of those four files before merge, §2.2's
  and §2.5's line citations need one re-run of the quoted `awk`/`grep`
  (which is exactly why §0 requires the command, not the script).
- **The post-U-hostmode master.** Every code number here is read off
  `b206800`. If U-hostmode's blind code gate changes a symbol this spec
  names — most plausibly one of the three `_expected_*_region` helpers —
  `DRY2` and `RER7` move with it. §10 states that as an assumption
  rather than a fact.

---

---

### 13.1 The stale-statement sweep — a fix for the CLASS, not a finding

*(added r6, gate M-1r4)* Three gate rounds running found the same shape:
a correction lands in a new location and the **original** sentence stays,
so the spec contradicts itself and the next gate spends a Major on it
(r2 `M-2r2`, r3 `N-3r3`, r4 `M-1r4`). The per-finding fix is a
substitution. The class fix is a sweep, run over the whole file after
every fold.

**The instrument** is `misc/u-verbs-measurements/uverbs_sweep.py`
(git-excluded, so it is convenience — §0's rule holds and the run below
is the evidence). It greps each corrected claim's own words and
classifies every hit: a hit is **LIVE** — a defect — unless it is in a
gate-fold table (§12.x), the revision history (§R), this section, or an
inline dated correction/withdrawal aside within ±3 lines
(`CORRECTED-rN`, `REPLACED-rN`, `WITHDRAWN`, `dropped`, `deleted`,
`was false`, …). Anything else is a live normative claim contradicting a
correction.

**Only the LIVE column is asserted, and here is why.** This section
quotes every pattern it sweeps for, so pasting a run *changes the totals*
of the next run — the `total` column has no fixed point and is reported
for context only. **`LIVE` does have one**: §13.1 is exempt by section, so
nothing written here can ever become a live hit, and `LIVE == 0` is stable
across re-runs. That is the invariant. *(Observed while writing this
section: the first paste reported `three renderings 7 / five shipped 3`;
re-running after the paste gave `8 / 1`. Both runs said `LIVE 0`.)*

**The r6 run:**

```
$ python3 misc/u-verbs-measurements/uverbs_sweep.py \
      docs/specs/self-learn/drafts/u-verbs-ledger-verb-completion-spec.md
pattern              total exempt  LIVE   live hits
three renderings         8      8     0   -
five shipped             1      1     0   -
byte-identity           12     12     0   -
FW-139                  10     10     0   -
SHOW4                    2      2     0   -
SECTION D                2      2     0   -
--continue               7      7     0   -
still uncommitted        1      1     0   -
not yet merged           1      1     0   -

FW-139 as a table ROW (must be 0): 0
VERDICT: CLEAN — 0 live stale statements
```

**A clean result from a permissive classifier is worthless without a
control**, which is this spec's own lrn-ea833a5b discipline applied to
itself. So the sweep was run again with two live stale statements
injected into §4.4, a normative section:

```
$ # injected into §4.4: "The runner also accepts `--continue` … and
$ # the contract keeps one table in three renderings."
three renderings         8      7     1   §4.4:1605
--continue               7      6     1   §4.4:1604
VERDICT: 2 LIVE HIT(S)
$ # injection reverted; file byte-identical (diff -q → IDENTICAL)
VERDICT: CLEAN — 0 live stale statements
```

**It found one the gate did not.** On its first run the sweep reported
**11** live hits; ten were correction asides the classifier had not yet
exempted, and **one was real**: §7's fixture 16 still said
`scope_mismatch_pending` *"Drives `MOVE1` leg 9 **and its byte-identity
control**"* and still carried the agreeing sibling record that only that
deleted control needed. r5 removed the control from `MOVE1` and from the
mutation table and did not remove it from the fixture. Corrected in r6,
and recorded here because it is the first evidence that the sweep pays
for itself.

**Reading a non-zero count.** Total ≠ defect. Only the **LIVE** column
matters, and every live hit is either a real stale statement or a missing
exemption — decide which by reading the line, never by widening the
regex to make the number go down.

## R. Revision history

| rev | date | change |
|---|---|---|
| r6 | 2026-08-28 | **Blind spec gate r4 → NOT SOUND (0 B / 1 M / 3 N / 0 D); all 4 findings folded, no further round** (§12.4; repricing rule — every one is a bounded text substitution). The gate verified all six r3 findings fixed, said two were fixed better than asked, and re-measured every number r5 changed — all reproduce. **`M-1r4`:** §3.3a still ended with the sentence `N-3r3` measured false (*"…one table in three renderings, as it does today"*), contradicted by three other places in the same spec — and §11.5's own correction pointed readers at *"§3.3a lists the three surfaces"* when **§3.3a listed nothing** and the measured list is in **§8**. §3.3a's paragraph is replaced by a pointer to §8; §11.5's cross-reference repointed. **`N-1r4`:** §7's positive-control list said "the **five** shipped call sites" against r5's own **six**, and still named `MOVE1`'s byte-identity sibling — a control r5 deleted the same round; both fixed, `DOC8`'s negative legs added. **`N-2r4`:** the `_cmd_report` comment is at `:1945`, **four** lines above the call at `:1949`, not two (the quoted text was already exact); `MOVE1` leg 9's statement no longer speaks of a step-5 "condition" that no longer exists. **`N-3r4`:** `BAT11` leg (c)'s mutation cell split — *flush lost ⇒ (c) red*, but *raw call left (a double flush) ⇒ **(a)** red, not (c)*, because the second flush finds an empty spool, `telemetry._commit_flush` early-returns, and `support.py:99-115`'s `last_verb_sha`/`verb_subject` deliberately skip telemetry-flush commits. **Class fix:** the gate named a pattern spanning three rounds — a correction lands in a new location and the original statement stays. **§13.1** adds a whole-spec stale-statement sweep, with the r6 run and its output pasted and a rule for reading a non-zero count. Counts **unchanged: 80 criteria (A 56 / B 24), 80 mutations, FW-133…138**. |
| r5 | 2026-08-28 | **Blind spec gate r3 → NOT SOUND (0 B / 3 M / 3 N / 0 D); all 6 findings folded** (§12.3). The gate verified all ten r2 findings fixed **at the root**, re-ran every changed number, and executed V-6's walker verbatim from the fence — identical output. **Two rulings.** `M-1r3`: FW-139's stated obstacle was **measured false** — folding `teach`/`import` in place is order-preserving (`code = X(); flush(); if <cond>: kick(); return code` on both) — so §3.3c is rewritten to fold **every** call site, and the census grew: `grep -c` finds **7** occurrences = 1 def + **SIX** call sites, `_cmd_report:1949` being a sixth whose own shipped comment says *"report is a flushing verb (11 §4.2)"*. The enumerated caller set is now a **seven-row table** §5 reads as data, and **FW-139 is WITHDRAWN** — ceiling back to **FW-138**, no numbered hole. `M-2r3`: `MOVE1` leg 9's byte-identity control **cannot fire** — the gate measured `Record.write` to be a byte-perfect round-trip on four real records, so a same-value write is indistinguishable from none. §3.2a step 5 now writes `scope:` **unconditionally** from the landing bucket (one rule, no predicate); the control and its mutation cell are deleted; `M78` is retargeted to *adding* a bucket-equality condition and still reddens leg 9 alone. **`M-3r3`:** §6.1's `M79` row claimed no shipped test asserts a dispatch surface flushes — false; `test_lifecycle_cli.py:236`/`:249` do, and they become **`BAT11` leg (c)**, the only leg backed by a shipped test. **`BAT11` rewritten to three legs** (N-1r3): (a) the raw helper has **exactly one** caller, positive control **six** at `b206800`; (b) the epilogue's call **SITES** — `(module, function, lineno)`, not a set of names, so a second call inside `_main` reddens — match the spec's table; (c) the two shipped guards. **`DOC8` + `M80` added** (N-3r3): r4's *"one table in three renderings"* was false — `11-telemetry-and-lifecycle.md` has **zero** exit-code content and §2.5's columns are `Verb \| Writes \| Commit subject`. The measured set is three surfaces that owe the `8` row (`cli.py:13-22`, `review.md:230-264`, `SKILL.md:96-101`) and two that owe **nothing** (`teach.md`, whose `2/3/4` mean different things, and `11`), with `git grep -c "Only 3, 4 and 7"` = **1** as the control; §11.5's owed §2.5 exit row is withdrawn. **N-2r3:** §9's IN list now names `cli._mutating_epilogue` and all six rewirings. Criteria **79 → 80** (A 55 → 56; B 24); mutations **79 → 80**; FW rows **FW-133…139 → FW-133…138**. |
| r4 | 2026-08-28 | **Blind spec gate r2 → NOT SOUND (0 B / 4 M / 6 N / 0 D); all 10 findings folded** (§12.2). The gate verified **all 25 r1 findings fixed** and re-measured everything r3 touched; the four Majors were new defects the r1 fold introduced. **One ruling — `M-4r2`, the biggest change in this round:** `batch` never flushed the telemetry spool, because 11 §4.2's rule lives only in `cli.main`'s `VERB_COMMANDS` branch and r3 correctly put `batch` outside it (`SHOW3`'s reason) — so a review session that flushed 34 times would have flushed **zero**. Measured root cause: the rule is **hand-repeated in five `_main` branches** (`:2135` teach, `:2145` VERB_COMMANDS, `:2150` followup, `:2155` link, `:2189` import), the same shape as Findings V-1 and V-2. New **§3.3c** extracts `cli._mutating_epilogue` with **exactly two callers**; `batch` flushes once after the item loop, inside the hold, before the push, `no_push=True`. New **`BAT11`** + **`M79`**; **`BAT10` leg (a)** now SEEDS the spool and asserts `HEAD +4` (3 item commits + 1 flush commit) — the empty-spool form could not see `M79`; `DOC5` gains 11 §4.2's amended sentence (*"every mutating dispatch — single verb or batch — flushes once"*); the four legacy callers are **FW-139**. **`M-1r2`:** §3.2a step 5 contradicted itself — conditioned on the bucket-derived source scope, then claimed a project→project repair that condition makes unreachable. Now conditioned on **`record.scope`** (the FIELD), with §4.1 step 6's same-place refusal still on the BUCKET and the two questions separated in writing; **`MOVE1` gains leg 9** (mismatch repair) with a byte-identity control, and **`M78`** reddens leg 9 alone. **`M-2r2`:** §8's preamble still said "No new integer is introduced" and its refusal row still carried the replaced severity rule — both corrected. **`M-3r2`:** `DOC5`'s regex required a trailing backtick the shipped §2.5 rows never have (measured: r3's form matches **0** of the three shipped rows, the `[ `]` form matches **3**). **Nits:** `--key` added to `append_note`'s signature and to the 02 §2 amendment (+ `note_has_key`); §7's fixture inventory rebuilt to **18** with `sheet_all_verbs`, `host_pending_only`, `spooled_home`, `sheet_code_mix`, `sheet_partial_seeded`, `scope_mismatch_pending` and `un1_baseline.json` now listed, and the positive-control list completed with `SHOW3`/`BAT10`/`MOVE9`; `BAT2`'s disagreeing pairs corrected to **`{3,6}` and `{4,6}`** (`{6,1}` agrees) with `{4,6}` added as a fifth leg; V-6's walker written out in full; three stale cross-refs fixed; `undefer`'s already-applied rule tightened with `deferred_count >= 1`. Criteria **78 → 79** (A 54 → 55; B 24); mutations **77 → 79**; FW rows **FW-133…138 → FW-133…139**. |
| r3 | 2026-08-28 | **Blind spec gate r1 → NOT SOUND (0 B / 9 M / 10 N / 6 D); all 25 findings folded** (§12.1 is the finding-by-finding table). The gate re-ran ~150 quoted numbers and all but two reproduced byte-exactly. **Two rulings:** `M-6` — the eight-integer exit contract describes ONE mutation and a batch is many, so it gains exactly one integer, **`EXIT_BATCH_PARTIAL = 8`**, under a decision procedure in which `1` is emitted only when nothing landed (§3.3a; new `BAT10` + `M74`; §8/§9/§11.1/§11.4 take the same row, and `review.md:264`'s sentence becomes "Only 3, 4, 7 and 8"). `M-5` — `already-applied` is **defined** and classified for **all 18** permitted verbs (§3.3b), with a sheet-line idempotency key on `note --append` (`--key`), so a second run of an applied sheet applies 0 items and exits 0. **Two new criteria:** `SHOW3` (`show` must not join `VERB_COMMANDS`, whose flush commits — `cli.py:2142-2146` + `:1955-1969`; the fixture seeds a NON-EMPTY spool, without which `M75` is invisible) and `BAT10`. **Ten criteria rewritten:** `BAT2` (discriminating `{3,6}`/`{6,1}` legs — r2's two legs both passed under `M30`), `BAT4` (1 **owning** hold, N+1 total), `BAT8` (15-verb sheet), `MOVE9` (the real gate is `proposals.validate_proposal`'s `rehome` branch, and its **source-scope refusal at `:354-358` is deleted** — with it in place §11.5's doctrine amendment was unobeyable), `UIP1` (a normative 17-name `UI_PARITY_VERBS` plus exhaustiveness over `cli.VERB_COMMANDS`; the r2 heuristic swept in `proposal validate`/`host commit-drift` and missed `supersede`), `UN4` (diff scoped to `_LOCKS`/`NOT_REPO_TRUTH`; two `_ARGV_FOR` rows owed; the file measured **not** armor-pinned), `HOST1` (**1** of 4 shipped `TestHostRemove` tests creates a record, not 4), `DOC5` (**6** `11 §2.5` rows), `PH2` (eight named verbs; `batch` via a one-line `undefer` sheet), `UN1` (baseline provenance stated). **`--continue` DROPPED** (D-2). **Four mutations added** (`M74`-`M77`), four retargeted (`M30`, `M36`, `M48`, `M58` — `M58` previously reddened nothing by its own admission). **Numbers corrected:** `DOC7`'s third control **1 → 2**; the bootstrap commit **≤07-15 → 2026-07-16**; `action_bar.html`'s `resolved` branch **:155 → :156**; `proposals.py`'s source-scope refusal **:353-357 → :354-358** (found while re-verifying every citation against `git show b206800:<path>` rather than any worktree); `sentinel.state()` → `is_live()`; the `LEARNINGS.md` header is **compiler-written**, not hand-owned. **One new finding of this fold — V-6:** checking D-6's bucket-vs-frontmatter rule against the live ledger found **1 of 152 records mismatched** (`user/resolved/lrn-c826137f.md`, `scope: skill:cron-claude`, reference-routed 2026-08-10 into the cron-claude skill's `LEARNINGS.md`) — **FW-138**, and the r3 draft's first wording of that clause ("0 mismatches") would have been false. Criteria **76 → 78** (A 52 → 54; B 24); mutations **73 → 77**; FW rows **FW-133…137 → FW-133…138**. |
| r2 | 2026-08-28 | **Orchestrator rulings on all five questions folded as decisions (§3.8), and every number made reproducible from a command quoted in this file.** **R1** (keep both names, one implementation) adds **`MOVE10`** — an AST assertion that neither `rehome` nor `rescope` contains a file-op of its own — and **`M71`**, a divergent write in one entry point that reddens `MOVE10` while every behavioural MOVE leg stays green. **R3** (`batch` in the CLI) adds **`DOC7`**, three `commands/review.md` sections checked per heading range with measured positive controls (all three targets 0 today; the ranges non-empty at 20/3/1), and **`M73`**. **R5** extends **`STATE8`** with a round-trip-through-`show` leg and **`SHOW1`** with `notes`, plus **`M72`**. **R2** and **R4** changed no criterion — FW-114 closes, and the reference-retirement behaviour change is ratified inside the `S-54` row itself on the strength of its zero live instances. §12 becomes "Questions — all RULED". **Instrument rewrite:** §2.1's usage table is now one quoted `git log` + `awk`, §2.2's guard census one quoted `awk` over `verbs.py`, §2.3's and §2.5's ledger figures quoted `ls`/`grep`/`sed` one-liners; the `misc/` scripts are convenience only and no number depends on them. **Five numbers changed** in that rewrite, each corrected against the command that now stands beside it: `_expected_*` helpers **4 → 3**; the `grep -rlE` test census **7 → 20 files**; `grep -c host_remove cli/tests` **0 → 6 hits in 2 files** (and the shipped `TestHostRemove` fixtures are pending-only, which makes them `M48`'s second discriminator); `ui/tests` `_KNOWN_VERBS` references **"asserts membership" → 0**; the non-`self-learn:` commit count **10 → 11** once `%s%n` replaced bare `%s` (a live instance of the fail-quiet class §0 now requires a control for). §2.2's past-date-absence grep gained a real positive control after its first form returned 1, not 0. Criteria **74 → 76** (A 50 → 52; B 24); mutations **70 → 73**. |
| r1 | 2026-08-28 | Authored. Census at `b206800` (code) + `4444be7` (ledger), §2, with five findings: **V-1** `require_status` covers 10 of 12 record-verbs, `rehome`/`rescope` still hand-roll it; **V-2** the move file-op was written twice, each half-complete; **V-3** u-rescope §3 rationale 1's slug/skill collision is measurably impossible (12/12 slugs match `^-.+-[0-9a-f]{8}$`); **V-4** the `reference` retirement no-op has 27 records of exposure and 0 live instances; **V-5** none of the six zero-mapped producer statuses is a failure, so the fix is an envelope, not an integer. Seven decisions (§3), field-exact design (§4), **74 criteria** in 14 groups across two phases (§5), **70 mutations** with an unmutated-test census showing 63 of the 70 pass the existing 2,636 + 1,279 tests silently and 2 more pass INVERTEDLY (§6), two new test files and one declared rewrite (§7), the exit-code table (§8), IN/OUT (§9), parallel units (§10), `S-54` + `FW-133`-`137` + three amended FW rows (§11), five questions routed with recommendations (§12). |
