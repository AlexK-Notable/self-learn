# U-ancestry — ancestor canon inheritance, and the already-canon scan's blind spot

Status: **r5 — 2026-08-28.** Blind spec gate r3 returned **SOUND** (0 B / 0 M / 3 N / 0 D) at r4; the spec's normative content has not changed since. r5 folds blind CODE gate r1's D/N findings against the BUILD (D1, D2, D4, N5, N7, N8, N11 — see §16) — text-only amendments to this document (a cited fixture name, a stated filter, a declared test-deletion, a table addition, a dated clarification); no criterion, mutation, or normative decision changed.

*(r4 — 2026-08-27, blind spec gate r3 returned **SOUND** (0 B / 0 M / 3 N / 0 D); its three nits folded here and the spec committed as-is — **no further gate round** (repricing rule, 2026-07-26). The gate ruled in this spec's favour on §15.2's over-cap count (three surfaces, two marker-bearing) and replicated all five `SCAN8` mutations against the positive assertions.)*

*(r3 — amended 2026-08-27 per blind spec gate r2 (NOT SOUND narrowly:
0 BLOCKER, 1 MAJOR, 11 NIT, 1 DOC). One structural change: §6.2's truncation
retention is now an **ordered priority** (managed region reserved first, then head
fill, then tail fill), because without it `SCAN8`'s mutations could not
discriminate — every live managed section sits in the last 3% of its file, where
tail fill retained it however the markers were matched. `SCAN8`'s fixture places
the real section in the middle, outside both fills, and asserts positively and
negatively. No criterion added (36); three mutations added (37). Every r2 N/D is
folded, including one gate measurement this spec corrects (§15.2).)*

*(r2 — amended 2026-08-27 per blind spec gate r1 (NOT SOUND: 2 BLOCKER,
3 MAJOR, 18 NIT, 3 DOC). Structural changes, not docs-only: `SCAN1` now states
its supersession of `u-marker-excerpt-case-spec.md` §3 criterion A and `SCAN8`
re-homes criterion B (`B1`); the doctrine amendment drops its `references/`
clause and `CARD4` refuses a `references/` path as `g0.canon` evidence (`B2`);
`§2.2`'s instrument is replaced by the `InstructionsLoaded` hook with a
`nested_traversal` positive control (`M1`); `ANC7`/`ANC8` give
`_loaded_surface`'s ancestor members and the pointer prose their first positive
criteria (`M2`); `LOAD6` pins "derived, never persisted" (`M3`). Criterion count
**24 (claimed) / 29 (listed) → 36**. Every N/D substitution is folded and marked.
Unit `U-ancestry` (T2, full two-gate).)*

Authored in the throwaway worktree `.claude/worktrees/u-ancestry-spec`
(branch `u-ancestry-spec`, base `50fa815` = `origin/master`). **Uncommitted.**

Reserved numbering: **S-52**; **FW-125 … FW-127**.

**Path convention.** Every pasted command output below has had the operator's
literal home prefix replaced by `~`, and nothing else altered — the drafts
convention (`scrub-personal-literals-spec.md` §"Group C"; only 2 of 54 drafts
carry a literal `/home/<user>` today, and one of them is that scrub spec
itself). Commands as run used absolute paths.

**The instruments are on disk.** Every script cited below lives in
`misc/u-ancestry-measurements/` in this worktree — `anc_setup.sh` /
`anc_run.sh` (§2.2's loading measurement), `uanc_census.py` (§3.1, §3.3, §3.4),
`uanc_excerpt.py` (§3.3), `uanc_retro.py` (§3.4, §3.7), `uanc_prompt.py`
(§3.1, §3.5). `misc/` is git-excluded on this host
(`.git/info/exclude:11:/misc/`), so they do not appear in the worktree's
status; a gate reproducing these numbers should run them from there. `$SCRATCH`
in a pasted command is the throwaway `/tmp` directory the marker tree
lived in; `anc_setup.sh` and `anc_run.sh` carry that absolute base path as a
literal and a re-runner must edit it to a directory outside every registered
host.

**Every number below is a command output.** Where something could not be
measured it is said so.

---

## 0. Reading order and precedence

1. `03-decisions.md` rows **S-23** (user scope has no references dir),
   **S-26** (the decision trace is mandatory), **G-3**'s 2026-07-17 dated
   note (canon read scope pinned to canon surfaces only, *user-ratifiable*),
   and **S-42/S-48** as the disposition-rule precedent. Where this spec and
   a row disagree, **the row wins**.
2. `plugins/self-learn/skills/self-learn/references/routing-doctrine.md`
   **§2 (G0/T3)**, **§3 (the ancestor-project clause)**, **§4** (repo
   conventions). This file is the single source of routing judgment; this
   unit amends it, it does not fork it.
3. `13-hosting-and-separation.md` **§4** (routing across repos: ledger-first
   two-phase; drift is repaired by recompile) and **§8** invariant **H-3**
   (compile targets come from `hosts.yaml` only — capture is open, canon is
   registered).
4. `u-reach-reachability-selftest-spec.md` **§2.1** (the loaded-surface model
   `LS(bucket, record)`) and `u-pointer-reachability-emitter-spec.md` **§4**
   (the emission surface). Ancestry changes what "reachable" means for a
   child session; §3.6 below is the measurement.
5. `u-cap-context-budget-spec.md` **§3.1/§4.0** (the load-class model and the
   report-only posture). Any new scan surface is an always-on cost and is
   priced here in bytes.
5a. `u-marker-excerpt-case-spec.md` **§2 (the import rule)** and **§3 criteria
   A and B** *(added r2, gate B1)*. This unit **supersedes criterion A** and
   **re-homes criterion B**; §2's import rule is untouched and still binding.
   §10.1, §11, §14.3 and §14.4 carry the disposition, the four test rewrites,
   and the `_ARMOR_SHAS` re-pin. Nothing here may quietly break a shipped
   criterion — a superseded criterion is superseded **in writing**, in its own
   spec.
6. `u-dismiss-false-recurrence-spec.md` **§10** (mutation table with
   MEASURED/`predicted` cells) — the format §10 below follows.
7. The code, in the order §3 measures it.

**Precedence inside this spec.** §9's criteria ARE the spec. Prose is
rationale. Where a criterion and a paragraph disagree, the criterion wins.

---

## 1. Objective, and the non-objectives

**Objective.** Close two doctrine gaps found in review batch 2 (2026-08-25),
both of which cause the analyst to answer **G0.canon `no`** on a lesson that
is already loaded, already written down, or both:

- **(a) Ancestor canon inheritance.** Claude Code loads `CLAUDE.md` from
  every ancestor directory of the session cwd (§2, sourced and measured), so
  an umbrella host's canon binds every child project's sessions. Self-learn's
  model has no edge for this: `canon_excerpt` reads exactly one file, and
  `_loaded_surface` returns exactly one member.
- **(b) The already-canon scan reads a 11.5% excerpt of one managed file.**
  Measured miss `lrn-bcf6b3e7`: 4 of its own 5 `t3.scan_terms` are present in
  the very `CLAUDE.md` the analyst was handed — and 0 of 5 in the 2,923 bytes
  of it the analyst actually received. The covering rule sits 188 lines above
  the excerpt window (208 above the managed marker).

**Non-objectives**

1. **A new verb.** `route --dest`, `rehome`, `rescope` and `graduate` already
   exist. **`U-verbs` is fenced out by name**: this unit adds no verb, no
   flag on an existing verb, and no new `--dest` grammar. §4.3 proves why the
   one behaviour that WOULD need a verb (umbrella-as-destination) is refused
   here and carried as **FW-125** instead.
2. **A new bucket key.** Bucket identity stays `(scope, name)`; projects stay
   keyed by slug. Ancestry is **derived** by path arithmetic over
   `hosts.yaml` at read time and is never persisted (§6.1).
3. **Registering anything.** An unregistered ancestor stays a fact told to
   the human (doctrine §3, quoted in §3.2). This unit never writes to, and
   never *reads content from*, an unregistered path.
4. **Widening the canon read scope beyond `canon_read_roots`.** §3.2 quotes
   the posture; §5.3 rejects the whole-host-tree option with its measured
   price (43.3 MB / ~10.8 M tokens across the 9 hosts, de-duplicated).
5. **Fixing the two hosts whose `CLAUDE.md` has no managed markers.** §3.3
   measures the consequence (the analyst sees the first 60 lines of a 277-
   and a 403-line file); §5.2's widening incidentally repairs it, and no
   criterion here asserts anything about marker bootstrapping.

---

## 2. The loading rule — SOURCED, then MEASURED

### 2.1 What the docs say

Fetched 2026-08-27 against `claude --version` → `2.1.250 (Claude Code)`.

- **The walk exists, and its stopping point is undocumented.**
  `https://code.claude.com/docs/en/memory.md`:
  > "Claude Code loads `CLAUDE.md` and `CLAUDE.local.md` from your current
  > working directory and every directory above it. Run Claude Code in
  > `foo/bar/` and it loads instructions from `foo/bar/CLAUDE.md`,
  > `foo/CLAUDE.md`, and any `CLAUDE.local.md` files alongside them."

  `https://code.claude.com/docs/en/large-codebases.md`:
  > "Claude Code loads every CLAUDE.md file from your working directory and
  > every parent directory at launch, then loads each subdirectory's file on
  > demand when it reads files there."

  **No page names a terminus** — not the git root, not the home directory,
  not `/`. *Docs silent.*

- **Ancestors are eager, subdirectories are lazy.** `memory.md`:
  > "CLAUDE.md and CLAUDE.local.md files in the directory hierarchy above the
  > working directory are loaded at launch. Files in subdirectories load on
  > demand when Claude reads files in those directories."

  Corroborated by `hooks.md`'s `InstructionsLoaded` event, whose
  `load_reason` enum is `session_start | nested_traversal | path_glob_match |
  include | compact`, and by the Agent SDK page's load-location table
  (`agent-sdk/claude-code-features.md`): *Project (parent dirs) … loaded at
  session start* vs *Project (child dirs) … loaded on demand*.

- **`.claude/CLAUDE.md` in an ANCESTOR:** *docs silent.* Both forms are
  documented as equivalent at the starting directory ("A project CLAUDE.md
  can be stored in either `./CLAUDE.md` or `./.claude/CLAUDE.md`"), but every
  ancestor-walk sentence and the SDK table's "parent dirs" row name only the
  bare form.

- **`--setting-sources`** (`cli-reference.md`): "Comma-separated list of
  setting sources to load (`user`, `project`, `local`)". `memory.md`:
  "`CLAUDE.local.md` is skipped if you exclude `local` from
  `--setting-sources`" and "Project rules are skipped if you exclude
  `project`". There is **no documented `-p` analogue of `/context`** for
  printing which memory files loaded.

### 2.2 The measurement

The stopping point and the ancestor `.claude/CLAUDE.md` question are both
docs-silent, so they were measured. A throwaway tree was built OUTSIDE every
registered host, with a distinct marker per candidate location, a `git init`
partway up so a git boundary would be crossed, and a descendant + a sibling
as negative controls:

```
$ bash misc/u-ancestry-measurements/anc_setup.sh
--- tree ---
$SCRATCH/anctest/CLAUDE.md                      ANCTOKEN-ALPHA    (2 levels above the git root)
$SCRATCH/anctest/outer/.claude/CLAUDE.md        ANCTOKEN-CHARLIE  (ancestor, .claude/ form)
$SCRATCH/anctest/outer/CLAUDE.local.md          ANCTOKEN-BRAVO    (ancestor, .local form)
$SCRATCH/anctest/outer/CLAUDE.md                ANCTOKEN-DELTA    (ancestor, above the git root)
$SCRATCH/anctest/outer/repo/CLAUDE.md           ANCTOKEN-ECHO     (the git root)
$SCRATCH/anctest/outer/repo/sub/CLAUDE.md       ANCTOKEN-FOXTROT  (immediate parent of cwd)
$SCRATCH/anctest/outer/repo/sub/leaf/child/CLAUDE.md  ANCTOKEN-GOLF   (descendant — negative control)
$SCRATCH/anctest/outer/repo/sibling/CLAUDE.md   ANCTOKEN-HOTEL    (sibling subtree — negative control)
--- git root of leaf ---
$SCRATCH/anctest/outer/repo
```

Run from the leaf, one turn, cheapest model:

```
$ cd $SCRATCH/anctest/outer/repo/sub/leaf
$ claude -p 'List every ANCTOKEN- marker sentence present in your instructions, one per line, verbatim, nothing else. If none, print NONE.' --max-turns 1 --model haiku
ANCTOKEN-ALPHA is the top-of-tree marker.
ANCTOKEN-DELTA is the outer plain marker.
ANCTOKEN-CHARLIE is the outer dot-claude marker.
ANCTOKEN-BRAVO is the outer local marker.
ANCTOKEN-ECHO is the git-root marker.
ANCTOKEN-FOXTROT is the mid marker.
```

**(CORRECTED-r2, gate M1.)** r1 asserted "the model's self-report is not the
instrument; the transcript is", and pasted a grep of the session `.jsonl`. That
claim was **false**, and r1's own pasted counts disprove it: a count of exactly
**1** per marker means each token appears once — in the assistant's reply.
Claude Code 2.1.250 does **not** write loaded instruction files into the session
transcript, so that grep corroborated the answer rather than replacing it, and
the descendant/sibling negatives rested on self-report.

**A real instrument exists on 2.1.250 and was used.** `--debug` and
`--debug-file` were tried first and do **not** expose a loaded-file list (a
434-line debug log carrying MCP, hook and telemetry records; `grep -c ANCTOKEN`
= 0, and only two incidental `CLAUDE.md` mentions, neither a load record). The
`InstructionsLoaded` hook does — the event exists in this build
(`strings ~/.local/share/claude/versions/2.1.250 | grep -c InstructionsLoaded`
→ **14**). A project-scope hook was installed in the throwaway leaf directory
only:

```
$ cat $SCRATCH/anctest/outer/repo/sub/leaf/.claude/settings.json
{"hooks": {"InstructionsLoaded": [ {"hooks": [
   {"type": "command", "command": "cat >> /tmp/claude-1000/instr.jsonl"} ]} ]}}

$ cd $SCRATCH/anctest/outer/repo/sub/leaf
$ claude -p 'Print OK and nothing else.' --max-turns 1 --model haiku \
      --setting-sources user,project,local < /dev/null
OK
```

Every event the run emitted, rendered as `load_reason · memory_type · file_path`
(paths `~`/`$SCRATCH`-shortened):

```
session_start    User       ~/.claude/CLAUDE.md
session_start    Project    $SCRATCH/anctest/CLAUDE.md                    (ALPHA)
session_start    Project    $SCRATCH/anctest/outer/CLAUDE.md              (DELTA)
session_start    Project    $SCRATCH/anctest/outer/.claude/CLAUDE.md      (CHARLIE)
session_start    Local      $SCRATCH/anctest/outer/CLAUDE.local.md        (BRAVO)
session_start    Project    $SCRATCH/anctest/outer/repo/CLAUDE.md         (ECHO)
session_start    Project    $SCRATCH/anctest/outer/repo/sub/CLAUDE.md     (FOXTROT)
```

Seven events. **GOLF (descendant) and HOTEL (sibling) emit nothing** — and that
silence is now a machine-emitted fact, not the model's word.

**Positive control — the hook is not simply blind to descendants.** A second
run, same tree, same hook, asked the agent to read a file inside the descendant
directory. The descendant's `CLAUDE.md` then fires, with a different reason:

```
$ printf 'PINEAPPLE is the word.\n' > .../leaf/child/note.txt
$ claude -p 'Read the file child/note.txt and print its first word, nothing else.' \
      --max-turns 3 --model haiku --setting-sources user,project,local < /dev/null
PINEAPPLE

session_start    User       ~/.claude/CLAUDE.md
session_start    Project    $SCRATCH/anctest/CLAUDE.md
session_start    Project    $SCRATCH/anctest/outer/CLAUDE.md
session_start    Project    $SCRATCH/anctest/outer/.claude/CLAUDE.md
session_start    Local      $SCRATCH/anctest/outer/CLAUDE.local.md
session_start    Project    $SCRATCH/anctest/outer/repo/CLAUDE.md
session_start    Project    $SCRATCH/anctest/outer/repo/sub/CLAUDE.md
nested_traversal Project    $SCRATCH/anctest/outer/repo/sub/leaf/child/CLAUDE.md   (GOLF)
```

GOLF arrives with `load_reason: nested_traversal`, only after its directory was
read. **HOTEL (the sibling subtree) fires in neither run.** So the instrument
does report descendants — which is exactly what makes its silence at
`session_start` meaningful.

**One r1 claim is withdrawn, not corrected** *(reasoning strengthened r3, gate
r2-N10)*. The hook establishes **which** files load; it cannot establish the order
they are **concatenated** in, because hook *emission* order is a different fact
from concatenation order — that holds however stable the emission looks. (One
pair of runs here also differed in emission order, run 1 putting
`.../repo/sub/CLAUDE.md` before `.../repo/CLAUDE.md`; **that variance was
observed once by the author and did NOT reproduce for the gate**, whose two runs
were both broadest-first. It changes nothing: the claim is withdrawn on the
instrument's reach, not on the variance.) r1's "concatenated broadest-first" was
doc-sourced and is demoted to doc-sourced below.

### 2.3 The rule, as measured

> **THE LOADING RULE (measured on Claude Code 2.1.250, 2026-08-27; instrument =
> the `InstructionsLoaded` hook, with a positive control).** At session start
> Claude Code loads `CLAUDE.md`, `.claude/CLAUDE.md`, and `CLAUDE.local.md`
> from the cwd and from **every ancestor directory**, each reported as one
> `load_reason: session_start` event (`memory_type` `Project` for the
> `CLAUDE.md` family, `Local` for `CLAUDE.local.md`). **The git repository root
> is not a stop** — markers two levels above the git root loaded. **Descendant**
> `CLAUDE.md` files load only on demand, reported as
> `load_reason: nested_traversal` once their directory is read; **sibling**
> subtrees never load. `~/.claude/CLAUDE.md` loads separately as `memory_type:
> User`, independent of cwd.
>
> *Doc-sourced, NOT measured:* the concatenation ORDER of the loaded files (the
> hook's emission order varied between two runs), and the walk's terminus.

What the measurement settles that the docs did not: **the ancestor
`.claude/CLAUDE.md` form IS discovered** (CHARLIE fires a `session_start`
event), **git boundaries are not stops** (ALPHA and DELTA fire from above the
git root), and **the descendant/sibling negatives are real** (the hook fires for
a descendant when it genuinely loads, and never for the sibling).

What it does **not** settle, and this spec does not claim: whether the walk
terminates at `/` or at `$HOME`. The tree lived under `/tmp`, and no
`CLAUDE.md` exists above it to detect a terminus with. The probe does establish
the walk is not `$HOME`-**gated** — the whole tree sat outside `$HOME` and every
ancestor still loaded. **It does not matter for any live case**: both ancestor
pairs (§3.1) are a single directory level apart and both live under `$HOME`, so
every candidate terminus is above them.

This measurement corroborates the deferred record **`lrn-b21d1969`**
(`user/pending/`, `status: deferred`, `deferred_until: 2026-09-25`), which
recorded the same rule from `code.claude.com/docs/en/memory.md` on 2026-08-25
and marked itself *"Doc-sourced, not locally repro-tested."* It is now
repro-tested for everything except its ordering clause. Its sibling clause —
that `--add-dir` does not load sibling `CLAUDE.md` unless
`CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` — was **not** exercised here
and stays doc-sourced (the sibling half *without* `--add-dir` is now measured:
HOTEL never loaded).

### 2.4 Consequence for the two live ancestor pairs

```
$ uv run python misc/u-ancestry-measurements/uanc_census.py   # section B
ANCESTOR ~/repos/3d-printing  ->  CHILD ~/repos/3d-printing/k1c-manta-m5p   (depth 1)
ANCESTOR ~/repos/keyboards    ->  CHILD ~/repos/keyboards/zmk-config-offsetkey (depth 1)
```

- Every session with cwd under `~/repos/3d-printing/k1c-manta-m5p` loads
  `~/repos/3d-printing/CLAUDE.md` (356 B) **in addition to** the child's
  25,499 B. The analyst sees only the child's, and only 2,923 B of it.
- Every session with cwd under `~/repos/keyboards/zmk-config-offsetkey` loads
  `~/repos/keyboards/CLAUDE.md` (12,175 B) in addition to the child's 621 B.
  The child's file is 100% managed section (0 hand-written lines); **its
  entire non-self-learn canon lives in the ancestor**, and the analyst has
  never seen a byte of it.

---

## 3. Census, measured at `50fa815`

### 3.1 Hosts, buckets, and the ancestry relation

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

Nine registered project hosts; two ancestor→child pairs (§2.4). `~/.config`
is **a project host, not a user-scope surface**: it is a registered project
path whose `CLAUDE.md` is 817 lines / 72,467 B, it owns ledger bucket
`-home-…-config-…` with 6 resolved records, and it is unrelated to the user
scope's `~/.claude/CLAUDE.md` (which the loading rule loads by scope, not by
ancestry). It has no registered ancestor and no registered descendant.

`ledger.discover_buckets()` returns **18 buckets** (5 skill, 12 project, 1
user) *(CORRECTED-r2, gate N1)*. Three project buckets are **unregistered**, and two of those three are
*descendants of registered hosts*:

```
$ uv run --with pyyaml python misc/u-ancestry-measurements/uanc_census.py   # section C
UNREGISTERED pend=0 res=0  ~/.claude/reports
UNREGISTERED pend=2 res=0  ~/repos/3d-printing/k1c-manta-m5p/.claude/worktrees/beacon-thermal-mitigation
             registered ancestor(s): ~/repos/3d-printing/k1c-manta-m5p, ~/repos/3d-printing
UNREGISTERED pend=0 res=0  ~/repos/nsys-marketplace-local/.claude/worktrees/bench-accuracy
             registered ancestor(s): ~/repos/nsys-marketplace-local
```

**Finding C-1 (measured).** `worker.canon_excerpt` has **no registry gate**.
For the unregistered worktree bucket above it returned a 2,923-byte excerpt —
byte-identical to the registered k1c bucket's — because the project leg is
`Path(bucket_project_path(bucket_dir)) / "CLAUDE.md"` with no `load_hosts`
call (`worker.py::canon_excerpt`, the `elif scope == "project"` branch).
`path_roster` is the same by design: *"pure path arithmetic, never
`verbs._resolve_target`"* (`worker.py::path_roster` docstring). H-3 gates
**writes**, not the analyst's reads. This is the precedent the ancestor read
in §6.2 sits on, and it is also why §6.1 tightens ancestry to **registered
hosts only** — the existing looseness is a bucket's *own* recorded path, not
an arbitrary directory self-learn went looking for.

### 3.2 How routing picks a destination today

**Doctrine.** `routing-doctrine.md` §1: five destinations, and *"You do not
pick a destination directly."* The gate procedure (§2: G0 → T1 → T2 → T3 →
T3a → T-N → T4 → E1) derives a **tier**, and §1's table renders the tier to a
destination **at the record's scope**. Every row of that table is keyed by
`skill:X | project | user` — **there is no host axis.**

**Code.** `verbs._resolve_target(home, bucket_dir, scope, destination,
ref_name, …)`. Its project legs are:

- `claude-md`: `host = _project_host_or_refuse(home, bucket_dir,
  project_path)`; `target = host / "CLAUDE.md"`.
- `reference`: same `host`, `refs_dir = host / "references"`, then
  `compilers.reference_target_path(refs_dir, ref_name)`.

`ref_name` is the destination's *qualifier* (`reference:<file>`,
`new-skill:<name>`, `claude-md:local`, `claude-md:rules:<topic>` — decoded by
`_decode_claude_md_qualifier`). **It never names a host.** The host comes from
the bucket's `meta.yaml` and nothing else. Therefore:

> **The only knob that moves a lesson's canon from one host to another is
> `rehome`, which moves the RECORD's bucket.** `route --dest` cannot express
> "this record stays in the child bucket, its canon lands in the ancestor".

**Doctrine already covers the umbrella — as a re-home, not a destination.**
`routing-doctrine.md` §3, verbatim:

> "The **nearest registered ancestor project** (the umbrella repo containing
> the trigger's surfaces) is then the narrowest surface that still fires,
> honestly applied. Propose a re-home (the `rehome` verb where you have it,
> prose in `rationale` where you don't) and **name the evidence: which
> trigger elements live outside the record's own repo** — a re-home proposal
> without that evidence is a hunch. Never leap to user scope just because a
> trigger spans two repos; check for the ancestor project first. An
> unregistered ancestor is a fact you tell the human, never something you
> register yourself."

*(CORRECTED-r2, gate D1: r1 rendered the last sentence bold; the source has no
emphasis there. The quote is otherwise verbatim.)*

`09-surface-spec.md` §4.5 states the same boundary for the pane: *"an
unregistered umbrella project stays a fact the agent tells the human, never a
registration path."*

**The read-scope posture, quoted** (`hosts.canon_read_roots` docstring; the
`03-decisions.md` G-3 dated note of 2026-07-17 records it as *user-ratifiable
and unexercised*):

> "given the registered host set, the CANON-SURFACE read prefixes — never a
> whole host repo (H-3's `host add` consents to compilers WRITING managed
> sections, not a model session reading an entire tree, untracked files
> included)."

Its project family is exactly two prefixes per host: `host / "CLAUDE.md"` and
`host / "references"`. §5 stays inside that set.

### 3.3 Where already-canon is computed, and exactly what it reads

**Already-canon is `G0.canon`, not `T3`.** The mandate names "t3"; the code
and the doctrine split the two:

- `gates.g0.canon` — *"is it already fully present in canon that already
  loads (`canon` — cite the canon target by name, e.g. an existing SKILL.md
  rule **or the curated doc this record was mined from**)"* (doctrine §2).
  `yes` ⇒ outcome `GRADUATE`. Enforced at `ledger_ops.py:1669`: *"a GRADUATE
  proposal must carry `already_canon: true`"*; and by `TRACE_CONDITIONALS`
  (`worker.py:1380-1382` — *CORRECTED-r2, gate D2*): `g0.canon.target` non-empty text and
  `g0.canon.evidence` a **TARGET-sourced quote**, required when the answer is
  `yes`.
- `gates.t3` — *"does an existing skill roster entry already own this?"*
  Answered **over the skill roster only** (doctrine §2 rule 2: *"T3 answers
  over the routable roster you were handed, never over memory"*).
  `t3.scan_terms` are the terms searched **against that roster**, required on
  the `no` branch. The roster is `worker.skill_roster(home)` — 11,477 B,
  `sha256:eae137988de9` at measurement time.

**The whole set of canon the analyst is handed, per record**, is
`worker.compose_record_block` — four ingredients, no more:

```
--- record <id> ---            Record.to_text()
--- cluster candidates (T-N) --- _render_candidates(candidates)
--- path roster ---            path_roster(home, entry)      # PATHS ONLY, no content
--- candidate target canon excerpt --- _canon_excerpt(home, entry)
```

`worker.canon_excerpt(home, record, bucket_dir)` resolves **one** file by
scope — skill → `<skills_root>/…/SKILL.md`; project → `<bucket host>/CLAUDE.md`;
user → `~/.claude/CLAUDE.md` — and then:

- `< 200 lines` ⇒ the whole file;
- `≥ 200 lines` with both markers ⇒ `lines[begin-20 : end+21]`;
- `≥ 200 lines` with no marker pair ⇒ `lines[:60] + "\n… (truncated)"`.

Measured per host (`misc/u-ancestry-measurements/uanc_census.py`, section D):

| host | vcs | lines | bytes | markers | mgd lines | hand lines | excerpt branch |
|---|---|---|---|---|---|---|---|
| `~/.config` | git | 817 | 72,467 | yes | 5 | 812 | markers ±20 |
| `~/repos/3d-printing` | git | 8 | 356 | no | 0 | 8 | WHOLE FILE |
| `~/repos/3d-printing/k1c-manta-m5p` | git | 365 | 25,499 | yes | 3 | 362 | markers ±20 |
| `~/repos/claude-skills` | git | 120 | 12,988 | yes | 4 | 116 | WHOLE FILE |
| `~/repos/ignomi` | git | 277 | 16,674 | **no** | 0 | 277 | **first 60 + trunc** |
| `~/repos/keyboards` | git | 232 | 12,175 | yes | 3 | 229 | markers ±20 |
| `~/repos/keyboards/zmk-config-offsetkey` | git | 3 | 621 | yes | 3 | 0 | WHOLE FILE |
| `~/repos/nsys-marketplace` | git | 403 | 39,146 | **no** | 0 | 403 | **first 60 + trunc** |
| `~/repos/nsys-marketplace-local` | git | 399 | 39,714 | yes | 3 | 396 | markers ±20 |
| USER `~/.claude/CLAUDE.md` | — | 74 | 24,329 | yes | 27 | 47 | WHOLE FILE |

**"Managed sections only" is precise for 4 of 9 project hosts and false for
the rest, in three different ways.** Four hosts get the whole file because it
is under 200 lines; two get an arbitrary first-60-line window because they
have no managed markers at all; four get the marker window ±20. The `≥200 +
markers` case is the one that produced the measured miss.

**Finding C-2 (measured) — `lrn-bcf6b3e7`.** The record's own proposal,
recovered from the ledger repo:

```
$ git -C ~/.self-learn show 904b335:projects/…-k1c-manta-m5p-…/proposals/lrn-bcf6b3e7.yaml
already_canon: false
gates:
  g0: {reject: {answer: no}, defer: {answer: no}, canon: {answer: no}}
  t3: {answer: no, owner: null,
       scan_terms: [backup, sha256sum, checksum, verify, k1c-backup-system],
       roster_sha: "sha256:eae137988de9"}
  outcome: ALWAYS
recommendation: route
```

The human's resolution, in the record:

```
status: superseded ; superseded_by: canon
resolution_note: 'already canon: k1c docs/known-issues.md #24; script fixed
  2026-08-21 (atomic write + DONE marker) so the fact is stale'
```

Where the terms actually are:

```
$ uv run python misc/u-ancestry-measurements/uanc_excerpt.py
k1c CLAUDE.md: 25499 bytes whole, 2923 bytes in canon_excerpt (11.5%)

scan_term              in excerpt in whole CLAUDE in known-issues
backup                 False      True           True
sha256sum              False      True           True
checksum               False      False          False
verify                 False      True           True
k1c-backup-system      False      True           True
```

The covering text is a hand-written rule in the file the analyst **was
handed**, at lines 146–149 of 365 — **188 lines above the excerpt window**, which
begins at line 334 (`begin` marker at 354, minus 20; 208 is the distance to
the marker, not to the window) *(CORRECTED-r2, gate N2)*:

```
$ sed -n '146,149p' ~/repos/3d-printing/k1c-manta-m5p/CLAUDE.md
- **Backups.** `k1c-backup-system` completion = `DONE` marker (+ log line
  `[k1c-backup] done —`). `SHA256SUMS` is written atomically now, but `DONE`
  is the signal. Verify: `sudo k1c-backup-system --verify`. Pull off-device:
  `bin/pull-system-backup.sh`.
```

**The miss did not require reading `docs/known-issues.md`.** It required
reading the remaining 88.5% of a file already resolved, already opened,
already read into memory by `canon_excerpt`, and already thrown away.

### 3.4 The hand-written surfaces, sized

Three candidate scan tiers, measured per host
(`misc/u-ancestry-measurements/uanc_retro.py`, section "surface sizes"):

- **excerpt** — what `canon_excerpt` returns today.
- **whole CM** — the host's whole `CLAUDE.md`.
- **tier A** — `canon_read_roots`' project family (`CLAUDE.md` minus the
  managed block, plus `<host>/references/**/*.md`), **plus `CLAUDE.local.md`
  for comparison only**. *(CORRECTED-r2, gate N9: `canon_read_roots` appends
  exactly `host/"CLAUDE.md"` and `host/"references"` per project —
  `CLAUDE.local.md` is NOT in it, and §6.2/`SCAN4` correctly exclude it *(CORRECTED-r3, gate r2-N5: r2 cited `SCAN3`, which is now the references-label criterion; the read-scope criterion is `SCAN4`)*. It is
  measured in this column only so the reader can see what stays invisible; see
  §12 OUT.)*
- **tier B** — tier A plus `<host>/*.md` plus `<host>/docs/**/*.md`.

| host | excerpt | whole CM | tier A | tier B |
|---|---|---|---|---|
| `~/.config` | 5,030 | 72,467 | 72,117 | 177,695 |
| `~/repos/3d-printing` | 355 | 356 | 1,590 | 140,585 |
| `~/repos/3d-printing/k1c-manta-m5p` | 2,923 | 25,499 | 25,265 | 434,876 |
| `~/repos/claude-skills` | 12,987 | 12,988 | 11,810 | 191,408 |
| `~/repos/ignomi` | 2,873 | 16,674 | 17,246 | 47,740 |
| `~/repos/keyboards` | 2,686 | 12,175 | 12,374 | 47,970 |
| `~/repos/keyboards/zmk-config-offsetkey` | 620 | 621 | **1** | 33,586 |
| `~/repos/nsys-marketplace` | 5,120 | 39,146 | 39,147 | 2,045,357 |
| `~/repos/nsys-marketplace-local` | 6,446 | 39,714 | 41,968 | 2,045,021 |
| USER `~/.claude/CLAUDE.md` | 24,328 | 24,329 | 6,862 | 6,862 |

And the ceiling, for the "scan every hand-written doc" reading of gap (b):

*(CORRECTED-r2, gate N5: r1 quoted 25,888,856 B from an instrument whose
exclusion set it never stated — and whose walk was depth-capped at 3, which the
prose did not say either. Re-derived with the set written out; the figure is
larger, so the direction of §5.3's rejection is unchanged and strengthened.)*

```
$ uv run --with pyyaml python misc/u-ancestry-measurements/uanc_r2_fixes.py   # section N5
### N5 — ALL *.md under each host; excluded dir NAMES (at any depth):
    .backups .claude-worktrees .git .venv __pycache__ build dist node_modules
    site-packages target vendor venv
    no depth limit; symlinks not followed; broken symlinks skipped
  ~/.config                               files=391   bytes=2591254    ~tok=647813
  ~/repos/3d-printing                     files=659   bytes=6143547    ~tok=1535886
  ~/repos/3d-printing/k1c-manta-m5p       files=172   bytes=1721498    ~tok=430374
  ~/repos/claude-skills                   files=93    bytes=1013991    ~tok=253497
  ~/repos/ignomi                          files=39    bytes=418885     ~tok=104721
  ~/repos/keyboards                       files=1988  bytes=12616725   ~tok=3154181
  ~/repos/keyboards/zmk-config-offsetkey  files=900   bytes=5072123    ~tok=1268030
  ~/repos/nsys-marketplace                files=960   bytes=12720941   ~tok=3180235
  ~/repos/nsys-marketplace-local          files=614   bytes=7823512    ~tok=1955878
  SUM over the 9 registered hosts (nested pairs double-counted): 50122476 B (~12530619 tok)
  DE-DUPLICATED (child bytes counted once, under the child only): 43328855 B (~10832213 tok)
```

**The figure this spec uses is the de-duplicated one: 43,328,855 B ≈ 10.8 M
tokens** across the nine registered hosts.

### 3.5 The composed prompt, sized — the budget baseline

*(CORRECTED-r2, gate N6.)* `path_roster` embeds `str(SELF_LEARN_HOME)` **four
times** per record (`ledger home`, `bucket`, `record file`, `proposals dir`), so
every block and roster byte count is a function of how long the ledger home's
path is. r1 measured against a copy at a deep `/tmp` scratch path and its
figures were inflated by 486 B/block and 324 B/roster. Re-measured against a
copy whose path is **exactly as long as the real ledger home** — both
`/home/<user>/.self-learn` and `/tmp/uanc-ledger-copy1` are 22 characters — so
the byte counts below are what a real-home run produces:

```
$ python3 -c "print(len('/home/<user>/.self-learn'), len('/tmp/uanc-ledger-copy1'))"   # 22 22
$ cp -a ~/.self-learn /tmp/uanc-ledger-copy1 && git -C /tmp/uanc-ledger-copy1 remote remove origin
$ SELF_LEARN_HOME=/tmp/uanc-ledger-copy1 SELF_LEARN_MINER=0 SELF_LEARN_MINER_AUTOKICK=0 \
      uv run python misc/u-ancestry-measurements/uanc_prompt.py
### pending queue: 3 entries
roster: sha=sha256:eae137988de9  bytes=11477
  lrn-d42f3619  block= 6832 B  excerpt=2923 B  pathroster=1056 B
  lrn-f4bf288d  block= 5465 B  excerpt=2923 B  pathroster=1056 B
  lrn-1fbfbc39  block= 5339 B  excerpt=2923 B  pathroster= 748 B
  TOTAL record blocks: 17636 B
### whole batch prompt: 97230 B (~24307 tok at 4 B/tok); BATCH_CAP=15
```

**Block sha256s are deliberately not quoted.** Equal path *length* makes the
byte counts right; it cannot make the *content* right, so a block hash taken
against any copy differs from a real-home run's. `UN2` therefore pins a
fixture-local baseline, never a live-queue sha.

Fixed part = 97,230 − 17,636 = **79,594 B**, of which the doctrine is 46,490 B
and the card registry 5,205 B (`wc -c` on the two reference files). The
per-record variable part is **5.3–6.8 KB**, of which the canon excerpt is
2,923 B.

**The budget headroom is in the per-record part, and `BATCH_CAP = 15`
multiplies it.** Any per-record addition must be priced × 15.

### 3.6 The reachability model, and the ancestry defect it cannot see

`selfcheck._loaded_surface(home, bucket, record)` — "LS", the U-reach model
of *what a session loads for a record's scope*:

```python
if bucket.scope == "skill":  return [skill_dir_for(...) / "SKILL.md"]
if record.scope == "project": return [] if host is None else [Path(host) / "CLAUDE.md"]
if record.scope == "user":    return [DEFAULT_USER_CLAUDE_MD.expanduser()]
return []
```

Its own docstring says the shape was chosen for exactly this: *"A list from
day one, one member per scope in v1 … The list shape exists so a future Model
B remap adds a member instead of editing a predicate."* **Ancestry is that
remap.** Per §2.3, a project record's LS is one member short whenever its host
has a registered ancestor.

**Finding C-3 (measured) — three byte-identical pointer blocks, and a
resolution base the checker and the session do not share.**

```
$ for f in ~/repos/3d-printing/CLAUDE.md \
           ~/repos/3d-printing/k1c-manta-m5p/CLAUDE.md \
           ~/repos/keyboards/CLAUDE.md ; do
    awk '/self-learn:pointers:begin/,/self-learn:pointers:end/' "$f" | sha256sum ; done
9b8c6e641db2ccc76574351878b3d37fce2c18bddacdfa4f0a23d791754e921e  -
9b8c6e641db2ccc76574351878b3d37fce2c18bddacdfa4f0a23d791754e921e  -
9b8c6e641db2ccc76574351878b3d37fce2c18bddacdfa4f0a23d791754e921e  -
```

Each block contains the line ``- `references/LEARNINGS.md` — captured lessons
for this project``. In a session with cwd `~/repos/3d-printing/k1c-manta-m5p`,
**two** of those blocks load (the ancestor's and the child's), saying "this
project" about two different projects, and the bare relative token has two
live resolutions:

```
$ wc -c ~/repos/3d-printing/references/LEARNINGS.md \
        ~/repos/3d-printing/k1c-manta-m5p/references/LEARNINGS.md
1232 …/3d-printing/references/LEARNINGS.md          # 2 records: lrn-ba478bfa, lrn-bd563ee1
1356 …/k1c-manta-m5p/references/LEARNINGS.md        # k1c's own records
```

`selfcheck._check_reach` passes on both, because
`compilers.surface_names_target` resolves a relative token against
`surface.parent` — its docstring is explicit: *"an absolute token is used
as-is, else resolved against `surface.parent` (the token is read as the
AUTHOR meant it — a relative pointer written in the surface file, relative to
that file)"*. A live agent resolves it against the **session cwd**. The two
agree only when cwd equals the surface's directory — which ancestry
guarantees is false for the ancestor's block. So:

- the umbrella's two reference-routed lessons are **not reachable** from a
  k1c session (the pointer resolves to the child's file instead), while
- `--selftest`'s `reach` row reports them reachable, because it resolves
  author-relative.

The keyboards pair is worse: `~/repos/keyboards/zmk-config-offsetkey/` has
**no `references/` directory at all**, so the ancestor's pointer resolves in a
zmk session to a path that does not exist:

```
$ ls ~/repos/keyboards/zmk-config-offsetkey/references/LEARNINGS.md
ls: cannot access '…/zmk-config-offsetkey/references/LEARNINGS.md': No such file or directory
```

**Named, not solved here:** the parked `_check_drift` / `_check_reach`
**real-home resolution** discussion — `selfcheck._target_for`'s docstring
(*"selfcheck never threads a `user_claude_md` override, so this always
resolves against the operator's real `~/.claude/CLAUDE.md`"*) and
`u-pointer-reachability-emitter-spec.md`'s `T-NO-REAL-HOME` /`M20` pair. This
unit adds ancestor members to LS for **project** scope only and touches
neither the user-scope resolution nor that discussion.

### 3.7 Retro-measure over the resolved ledger

```
$ uv run python misc/u-ancestry-measurements/uanc_retro.py
proposals recoverable from ledger git history: 85
routed=83  graduated(superseded_by:canon)=24  total resolved considered=107
```

**MEASURE 1 — real `t3.scan_terms`.** *(CORRECTED-r2, gate N10: r1 gave `N=24`
without stating the filter that produced it. The filter is now written out and
its full drop census pasted, so N is reproducible rather than asserted.)*

```
$ uv run --with pyyaml python misc/u-ancestry-measurements/uanc_r2_fixes.py   # section N10
### N10 — MEASURE-1 filter, stated
    blob   = the NEWEST commit that ADDED <bucket>/proposals/<id>.yaml
    keep   = record exists AND status in {routed, superseded}
             AND gates.t3.scan_terms non-empty
             AND a host surface resolves (project host, or user scope)
    {'blobs': 85, 'drop:status=rejected': 18, 'drop:status=deferred': 10,
     'KEPT': 24, 'drop:no-scan-terms': 31,
     'drop:no-host-surface(scope=skill:testing-methodology)': 1,
     'drop:no-host-surface(scope=skill:cron-claude)': 1}
    N = 24  (project: 14  user: 10 )
```

85 + 0 unaccounted: 18 + 10 + 31 + 2 dropped, 24 kept. For each kept record,
how many of its own terms appear in each surface:

```
N=24  {'excerpt_any': 20, 'whole_any': 22, 'tierA_any': 19, 'tierB_any': 19,
       'tierB_but_not_excerpt': 3, 'tierB_but_not_wholeCM': 1}
```

**The filter has a selection bias, now named** *(CORRECTED-r3, gate r2-N9)*.
"The NEWEST commit that ADDED the file" reads the **first creation** of each
proposal, so it drops records whose proposal was **regenerated by a later
`worker` round** and carried `scan_terms` only then. There are exactly **three**,
all user-scope, all `routed`/`superseded`:

- `lrn-566216a6` — created by `bdd159e worker 2 proposals` with no terms,
  rewritten by `efd5ebd worker 3 proposals` with
  `[system load, flaky test, timing-sensitive, manufactured load]`
- `lrn-74d0b52b` — created by `4825a7e worker 1 proposal`, rewritten by
  `efd5ebd` with `[scratch directory, tmp, subagent report, durable artifact]`
- `lrn-792f43c8` — created by `44bc1ec worker 7 proposals`, rewritten by
  `fe4700a worker 15 proposals` with `[pkill, pgrep, bash, self-match, process]`

The universe matching this measure's own intent — *the terms the analyst produced
for the proposal that was acted on* — is therefore **N = 27**, not 24. Both are
reported because both are reproducible, and **the conclusion is identical at
either**:

```
stated filter (first creation)  N=24 {excerpt_any:20, whole_any:22, tierA_any:19,
                                      tierB_but_not_excerpt:3, tierB_but_not_wholeCM:1}
acted-on proposal               N=27 {excerpt_any:22, whole_any:24, tierA_any:20,
                                      tierB_but_not_excerpt:3, tierB_but_not_wholeCM:1}
```

`tierB_but_not_wholeCM` = **1** at both, so Q1's recommendation does not move.
`tierA_any`/`tierB_any` are filter- and tier-definition-sensitive and carry no
conclusion. (An earlier blind re-derivation reported N=25; that figure was an
artifact of an early-break traversal and is withdrawn by its own author.)

Per-record rows worth naming:

| record | host | terms | in excerpt | in whole CM | tier A | tier B |
|---|---|---|---|---|---|---|
| `lrn-bcf6b3e7` | k1c-manta-m5p | 5 | **0/5** | 4/5 | 4/5 | 4/5 |
| `lrn-bd563ee1` | 3d-printing | 6 | 0/6 | **0/6** | 6/6 | 6/6 |
| `lrn-4e95b3a6` | `.config` | 5 | 0/5 | 5/5 | 5/5 | 5/5 |
| `lrn-90a32f8a` | k1c-manta-m5p | 5 | 1/5 | 3/5 | 5/5 | 5/5 |
| `lrn-4f911239` | keyboards | 5 | 1/5 | 1/5 | 5/5 | 5/5 |

**MEASURE 2 — proxy.** `scan_terms` exist for only 24 records, so the full
corpus is measured with a labelled **proxy**: the record's own Trigger/Fact
tokens: the same tokenisation `worker._tokens` uses (alnum→space, lowercased)
but with a **≥6-character** filter and a **first-12** cut instead of its `>2`
*(CORRECTED-r2, gate D3)*. It covers
the 58 of 107 resolved records that are project- or user-scope (the other 49
are skill-scope and have no host surface).

```
N=58  {'excerpt>=0.5': 42, 'wholeCM>=0.5': 48, 'tierA>=0.5': 26,
       'tierB>=0.5': 29, 'tierB>=0.5_and_excerpt<0.5': 12}
```

Records whose lesson text is ≥50% present in a hand-written surface the analyst
never read, while <50% present in the excerpt it did read:
`lrn-069dbe39`, `lrn-4c75079e`, `lrn-4e95b3a6`, `lrn-4f911239`, `lrn-90a32f8a`,
`lrn-95a39182`, `lrn-a0356947`, `lrn-b197d06b`, `lrn-ba478bfa`, `lrn-bcf6b3e7`,
`lrn-bd563ee1`, `lrn-d8ef72cb` — **11 or 12 depending on the token cut**
*(CORRECTED-r2, gate N10)*: a blind re-derivation with a wider tier-B
concatenation reproduced 11 of these 12 ids exactly and dropped
`lrn-4c75079e`. The count is a magnitude, not a threshold; nothing in §5
depends on 11 vs 12.

**Positive control** (required: a matcher that cannot miss proves nothing).
A sentinel string absent from every surface returns `False` on all four
surfaces of all ten hosts; the negative control (`k1c-backup-system` in the
k1c host) returns `excerpt=False whole=True tierA=True tierB=True` — i.e. the
instrument distinguishes the excerpt from the file, which is the whole point.

**Honest reading of these numbers.** They do **not** say "11–12 records should
have been graduated". A hand-written *mention* is not a *rule*; `lrn-4f911239`
scoring 5/5 in tier A means the words appear in prose that may or may not
already instruct. They say: **for 11–12 of 58 records the analyst answered
G0.canon `no` without having read the text that would have let it answer.**
That is a missing input, not a wrong answer — and §5.2's design keeps the
answer with the human for exactly that reason.

### 3.8 What review batch 2 actually did (the steelman's numbers)

```
$ git -C ~/.self-learn log --pretty="%h %ad %s" --date=short --since=2026-08-24 | grep -vE "telemetry|mine "
686843a 2026-08-26 self-learn: suspect dismissed on lrn-566216a6
5d62084 2026-08-26 self-learn: reject lrn-0c1f898a
0ab44bd 2026-08-25 self-learn: route lrn-b9f78305 → skill-md
844d43c 2026-08-25 self-learn: route lrn-a0356947 → reference
7199958 2026-08-25 self-learn: route lrn-90a32f8a → reference
ccf1649 2026-08-25 self-learn: route lrn-bd563ee1 → reference
123e8d0 2026-08-25 self-learn: route lrn-ba478bfa → reference
e6b349a 2026-08-25 self-learn: defer lrn-b21d1969 until 2026-09-25
06df654 2026-08-25 self-learn: graduate lrn-bcf6b3e7
e375ab3 2026-08-25 self-learn: host add project ~/repos/3d-printing
904b335 2026-08-25 self-learn: worker 6 proposals
d6fac30 2026-08-25 self-learn: capture lrn-b21d1969 (user)
```

Five reference routes in the batch and its immediate predecessor
(`dcaca65 route lrn-d8ef72cb → reference`, after `91982af rehome lrn-d8ef72cb
→ …k1c…`); **two landed on the umbrella host** (`lrn-ba478bfa`,
`lrn-bd563ee1`). Both landed there because their **records were already in the
umbrella bucket** — the miner created them from a session whose cwd was the
umbrella, and the human ran `host add` mid-batch so they could be routed.
Neither was moved there by a destination choice.

```
$ git -C ~/.self-learn log --oneline --grep="rehome"
91982af self-learn: rehome lrn-d8ef72cb → projects/…-3d-printing-k1c-manta-m5p-…
7ba1561 self-learn: rehome lrn-bd425ddd → projects/…-nsys-marketplace-local-…
99bac30 self-learn: rehome lrn-4c75079e → projects/…-nsys-marketplace-…
```

**Zero of 107 resolved records were routed from a child bucket into an
ancestor host.** Not because it was judged wrong — because §3.2 shows there is
no way to express it.

---

## 4. Gap (a) — ancestor canon: option map and DECISION

### 4.1 The options

| # | Option | What it changes | Measured price | Verdict |
|---|---|---|---|---|
| **A1** | **Do nothing** — `--dest` and `rehome` by hand are enough | nothing | 0 B | **REJECTED**, §4.3 |
| **A2** | **Ancestor-aware reads**: registered ancestors' `CLAUDE.md` joins the analyst's canon ingredient and `_loaded_surface`; no new destination | `canon_excerpt`, `_loaded_surface`, one card section | +356 B per k1c record, +12,175 B per zmk record, **0 B for the other 7 hosts** | **ADOPTED** |
| **A3** | A2 **+ umbrella-as-destination**: route a child-bucket record's canon into the ancestor host | a host axis on `_resolve_target`; `_compile_set`; a new `--dest` grammar or verb | unpriced — collides with U-hostmode and U-verbs | **REFUSED here → FW-125** |
| **A4** | A2 **+ sibling awareness**: tell the analyst which sibling hosts exist so it can spot a ≥2-sibling lesson | a new prompt ingredient | +1 line per sibling; 2 sibling sets exist | **PARTIAL** — folded into A2's flag, §6.3 |
| **A5** | Auto-rehome on an ancestor-fit judgment | the analyst mutates bucket identity | — | **REFUSED** — doctrine §3 and Y-11's no-agent-path pin: the agent must never widen its own read scope or mint write targets |

### 4.2 DECISION

**A2 + A4's flag.** Three concrete changes, all read-side:

1. **`ancestors_of(hosts, path)`** — derive ancestry from **registered hosts
   only**, by resolved-path prefix arithmetic, nearest-first. No new key, no
   persistence, no registry entry. (§6.1)
2. **The analyst's canon ingredient gains a labelled ancestor block per
   registered ancestor** (§6.2), so `G0.canon` can fire on inherited canon and
   `T4`'s narrowest-surface bias can see the umbrella's contents.
3. **`_loaded_surface` gains the registered ancestors' `CLAUDE.md` as
   additional members** for project scope (§6.4) — the "Model B remap" its own
   docstring anticipated — and the pointer block emitted into a host that has
   a registered ancestor **or** a registered descendant names its base in
   prose, so the two identical blocks in one session stop being ambiguous
   (§6.4, Finding C-3).

**Why registered-only, and what happens to an unregistered ancestor.** Reading
content out of an arbitrary ancestor directory is precisely the whole-tree
read `canon_read_roots` refuses, and doctrine §3 already rules the case: *"An
unregistered ancestor is a fact you tell the human, never something you
register yourself."* So: `ancestors_of` returns registered hosts only; a
**separate, content-free** probe reports whether an unregistered directory
between the record's host and the nearest registered ancestor contains a
`CLAUDE.md`, as a **flag** (`unregistered-ancestor`) plus its path — never its
bytes. The human registers it or does not.

### 4.3 Designs rejected, with the measurement

- **A1 "do nothing".** Its strongest form: batch 2 routed two lessons to the
  umbrella with no new machinery, and `rehome` shipped for exactly this
  (`09 §11 Y-18`). The measurement refutes the *scope* of that claim, not its
  spirit: §3.8 shows both umbrella routes were **capture-side accidents** (the
  miner put the records in the umbrella bucket), and **zero** records ever
  crossed from a child bucket to an ancestor host. Meanwhile §3.6 measures a
  live, currently-shipping defect that "do nothing" leaves in place — two
  byte-identical pointer blocks in one session, the umbrella's two
  reference-routed lessons unreachable from child sessions, and a `--selftest`
  row that reports them reachable. A1 is rejected because it is not "no
  change"; it is "keep a measured false PASS".
- **A3 umbrella-as-destination.** Rejected *for this unit*, not on merit. It
  needs `_resolve_target` to accept a host that is not the bucket's host,
  which (i) is exactly the axis **U-hostmode** is reworking (per-host
  `git|plain` mode + a ledger-side compile record), (ii) needs a `--dest`
  grammar or a verb, which **U-verbs** owns, and (iii) forks the compile set:
  `_compile_set` gathers a host's records by bucket, so a foreign-bucket
  record landing in a host's managed section would be invisible to
  `recompile` and would drift on the next run — the exact failure `13 §4`
  item 2 exists to prevent. Carried as **FW-125** with its trigger.
- **A5 auto-rehome.** Refused by two standing pins, quoted in §3.2.
- **Persisting an `ancestor:` field on the bucket `meta.yaml`.** Rejected: it
  is a second source of truth for a relation `hosts.yaml` already determines,
  and it would go stale the moment a `host add`/`host remove` changes the set.
  Derive at read time; the derivation is ~10 lines of path arithmetic.

---

## 5. Gap (b) — the already-canon scan: option map and DECISION

### 5.1 The options

Prices are **per record**, and must be read × `BATCH_CAP = 15` (§3.5).

| # | Option | Surface read | Measured price per record (min–max over 9 hosts) | Verdict |
|---|---|---|---|---|
| **B1** | Do nothing | excerpt only | 355–24,328 B (today) | **REJECTED** — §3.3/§3.7 |
| **B2** | **Whole `CLAUDE.md`, byte-capped** | `<host>/CLAUDE.md` | 356–72,467 B; delta over today **+1 to +67,437 B** | **ADOPTED** |
| **B3** | B2 **+ `<host>/references/**/*.md`** | tier A | 1–72,117 B added | **ADOPTED** |
| **B4** | B3 + `<host>/docs/**` + `<host>/*.md` | tier B | 33,586–**2,045,357** B | **REJECTED**, §5.3 |
| **B5** | Lexical pre-pass: grep `scan_terms` over tier B, feed only matching spans | tier B, filtered | small, but requires the terms first | **REJECTED**, §5.3 |

### 5.2 DECISION

**B2 + B3, capped, labelled, and non-authoritative.**

1. **The canon ingredient becomes a set of labelled blocks, not one anonymous
   excerpt** (§6.2): the record's own host `CLAUDE.md` (whole, capped), each
   registered ancestor's `CLAUDE.md` (whole, capped) labelled *inherited*, and
   the host's `references/**/*.md` (capped, per-file, labelled **captured, NOT
   loaded** — the shelf, never `g0.canon` evidence; §6.2 item 3, criterion `SCAN4` for the read scope — *CORRECTED-r3, gate r2-N5*). Each block is prefixed
   with its absolute path and, when truncated, with an explicit truncation
   marker naming the bytes dropped. **Nothing outside `canon_read_roots`'
   project family is read** (§6.2, criterion `SCAN4` — *CORRECTED-r4, gate
   r3-N2*).

2. **The budget rule, normative:**

   > **BR-1.** The per-record canon ingredient is capped at
   > `CANON_BYTES_PER_RECORD` total bytes. Within it, each file is capped at
   > `CANON_BYTES_PER_FILE`, and at most `ANCESTOR_DEPTH_CAP` ancestors
   > contribute. Truncation follows **§6.2's three-clause ordered priority** —
   > (1) the case-sensitively located managed region, reserved first and always
   > retained; (2) head fill; (3) tail fill, budgets computed after the
   > reservation — and every dropped span is marked in the text.
   > *(CORRECTED-r4, gate r3-N3: this rule still carried the r2 wording
   > "head-and-tail (the managed-marker window is always retained)", which is
   > the unpinned split r3 replaced; BR-1 now points at the order rather than
   > restating a superseded form of it.)*
   >
   > **BR-2.** The realised total is **reported**, never enforced silently:
   > every worker/analyst run logs `canon_bytes=<n>` per record and the batch
   > total, in the same report-only posture `u-cap` §4.0 sets for the four
   > budget signals. A cap that fires is a logged fact, not an exception.
   >
   > **BR-3.** Defaults, chosen from §3.4's measurements:
   > `CANON_BYTES_PER_FILE = 32768` (covers 8 of 9 hosts' whole `CLAUDE.md`
   > untouched; `~/.config` truncates from 72,467 B),
   > `ANCESTOR_DEPTH_CAP = 2` (the live max is 1),
   > `CANON_BYTES_PER_RECORD = 65536`. Worst case per record therefore rises
   > from 24,328 B to 65,536 B, and the batch worst case from ~365 KB to
   > ~983 KB (×15) — priced, bounded, and reported.

3. **A hand-written region can never, by itself, resolve a record.** The
   analyst may set `already_canon: true` / `g0.canon.answer: yes` from a
   hand-written region **only** when it can also write `g0.canon.target` as
   `<absolute path>:<line>` and `g0.canon.evidence` as a verbatim span from
   that target — which the shipped validator already requires
   (`worker.py` `TRACE_CONDITIONALS`; `ledger_ops.py:1669`). This spec adds
   one rule on top, because a *mention* is not a *rule*:

   > **HW-1.** When `g0.canon.target` names a region **outside** a managed
   > section, the proposal MUST carry the new card section (§7) and the flag
   > `canon-hand-written`. The recommendation may be `graduate`; the
   > **resolution is always the human's** — no verb auto-graduates on this
   > signal, and no compiler consumes it.

   This is what keeps `lrn-bcf6b3e7`'s shape safe: its covering text was both
   *already canon* and *stale* (the script was fixed 2026-08-21). A machine
   that graduates on a lexical hit would have laundered a stale fact into a
   resolution. A card that shows the span and its line lets the human do what
   the human actually did.

4. **Scope of the fix, stated plainly.** §3.7 MEASURE 1 says `tierB_but_not_
   wholeCM` = **1 of 24** — i.e. adding `docs/` beyond tier A would newly
   reach exactly one more record's terms, for the price in §5.3. Whole-file +
   `references/` is where the recovered signal is.

### 5.3 Designs rejected, with the measurement

- **B4 "scan the hand-written docs".** The literal reading of the mandate.
  Priced: tier B is 33,586–2,045,357 B **per record**; at `BATCH_CAP = 15`
  with nsys-marketplace records that is ~30.7 MB (~7.7 M tokens) in one
  prompt. The unbounded form — every `*.md` under every host — is
  **43,328,855 B (~10.8 M tokens)** de-duplicated (§3.4, with its exclusion set
  written out). It also breaches the
  `canon_read_roots` posture (`03-decisions.md` G-3 dated note: whole-root
  reads are *user-ratifiable and unexercised*), which is a **user decision**,
  not a spec author's. Routed as open question **Q3**.
- **B5 lexical pre-pass.** Attractive on cost and rejected on *ordering*:
  `t3.scan_terms` are an **output** of the gate procedure (doctrine §2: the
  terms *"you searched the roster for and found nothing on"*), not an input.
  There is no term list before the analyst runs. A record-derived proxy exists
  (`worker._tokens`' tokenisation over `record_title` at a >=6-char cut, the
  recurrence detector's basis) —
  §3.7 MEASURE 2 uses exactly it — but promoting a proxy to a *canon-presence
  gate* would make a Jaccard threshold decide graduation. Carried as **FW-126**
  with its trigger: a term source that exists before the analyst does.
- **Bootstrapping managed markers into the two marker-less hosts so the
  `±20` branch applies.** Rejected as a fix for gap (b): it would give
  `~/repos/ignomi` and `~/repos/nsys-marketplace` a *smaller* excerpt than the
  first-60-lines branch they get today for two of them, and it writes into a
  host to fix a read-side defect. §5.2's widening makes the branch moot.
- **Caching the whole-file reads across a batch.** Deferred, not rejected:
  §3.5 shows all three pending records in the live queue share one host and
  therefore one 2,923 B excerpt, so a per-batch memo on `(path, mtime, size)`
  would collapse the ×15 worst case substantially. It is a pure optimisation
  with no behaviour change and no criterion here; the builder may add it.

---

## 6. Behaviour spec (field-exact)

### 6.1 `hosts.ancestors_of(hosts, path) -> list[Path]`

New function in `hosts.py`, beside `canon_read_roots` (the module that already
owns "what the registered host set implies").

- Input: a `Hosts` and a candidate path (a bucket's recorded `meta.yaml`
  path, or any host path).
- Returns registered project paths `a` such that
  `str(target.resolve()).startswith(str(a.resolve()) + os.sep)` — **proper
  prefixes only**, never the target itself.
- Ordered **nearest-first** (longest prefix first).
- Never returns a sibling, never a descendant, never an unregistered path.
- Never consults the filesystem beyond `resolve()`; never reads a file.
- The git boundary is **not** consulted: §2.3 measured that Claude Code
  ignores it, and a derivation that stopped at a git root would model a rule
  that does not exist. *(This is the interface assumption U-hostmode must
  hold: ancestry is path arithmetic, independent of whether either host is
  `git` or `plain`.)*
- **Derived, never persisted** *(added r2, gate M3)*. Neither function writes
  anything: no `meta.yaml` field, no bucket key, no cache file, no ledger byte.
  Bucket identity stays `(scope, name)` and projects stay keyed by slug. The
  relation is recomputed from `hosts.yaml` on every call, so a `host add` /
  `host remove` changes it immediately and nothing can go stale. `LOAD6` is the
  criterion; its instrument is a before/after `sha256 + mtime` snapshot of every
  file under a fixture home across an analyst run, plus a census of `meta.yaml`
  writers.
- **Both sides are `Path.resolve()`d, and the loading rule was measured on real
  paths** *(added r2, gate N18)*. `ancestors_of` compares
  `target.resolve()` against `a.resolve()`; a live session's ancestor walk
  operates on the cwd it was given. If a host were reachable through a symlink
  whose realpath is not under the ancestor, the two would disagree in both
  directions. **Not live today** — `readlink -f` on all nine registered hosts
  returns the path itself, no registered host is a symlink — and a session whose
  cwd reaches a host through a symlink is out of scope for this unit.

`hosts.unregistered_ancestor_dirs(hosts, path) -> list[Path]` — the
content-free probe: directories strictly between `path` and its nearest
registered ancestor (or the filesystem root, if none) that contain a
`CLAUDE.md` or `.claude/CLAUDE.md`. Returns **paths only**; no caller may read
their bytes.

### 6.2 The canon ingredient

`worker.canon_excerpt` is replaced by `worker.canon_blocks(home, record,
bucket_dir) -> str`, keeping `canon_excerpt`'s call sites
(`worker._canon_excerpt`, and `ui/src/self_learn_ui/pane.py`'s
`target_canon_excerpt`, which **delegates and must keep delegating** — FW-48 /
U-marker-ui, the one-implementation rule).

Emitted blocks, in this order, each opened by a line
`### <absolute path> (<n> B[, truncated from <m> B])`:

1. **own host** — the record's own `CLAUDE.md` (skill scope: `SKILL.md`;
   user scope: `~/.claude/CLAUDE.md`), **whole**, capped per BR-1.
2. **ancestors** — for `scope == "project"` only, one block per member of
   `ancestors_of(...)` up to `ANCESTOR_DEPTH_CAP`, each labelled
   `(inherited — loads in every session under this host)`.
3. **references** — sorted, capped, each opened with the fixed label
   `(captured, NOT loaded — pointer-reached; not eligible for g0.canon)`
   *(CORRECTED-r2, gate B2)*. A `references/` file is on the **shelf**, not in
   the session: the pointer block self-learn itself compiles says so verbatim
   ("Captured lessons that are **NOT loaded into this context**"), and
   `selfcheck._loaded_surface` — the shipped model of what a session loads —
   never returns one. So a hit here is a *different signal* from an ancestor or
   hand-written-`CLAUDE.md` hit: it populates the `already_kept` card section
   (§7) and nothing else. It may not set `already_canon`, may not answer
   `g0.canon` `yes`, and may not pre-select `graduate`; the human reads the
   span and picks among the normal resolutions with it in view.

   **Which `references/` dir, per scope** *(added r3, gate r2-N8 — r1/r2 said
   only "`<own host>/references/**`", and 49 of the 107 considered records are
   skill-scope)*: **project** → `<host>/references/**/*.md`; **skill** →
   `<skill_dir>/references/**/*.md`, the same directory
   `verbs._resolve_target`'s reference branch resolves for that scope and the
   DEMAND target at skill scope (measured: 10 skill trees under `skills_root`
   have a `references/` dir today, and `canon_read_roots` admits
   `plugins/*/skills/*` **whole**, so including them breaches no read posture);
   **user** → **none**, and the block is omitted entirely, because S-23 rules
   that user scope has no references dir (`_resolve_target`'s reference branch
   refuses user scope outright). An omitted user-scope references block is the
   correct output, not a degraded one — no sentinel line is emitted for it.

Rules:

- **No ancestor blocks for skill or user scope.** Skill scope's surface is a
  skills-root file and user scope's is cwd-independent; neither has a path
  ancestry relation to a project host.
- **Truncation retention is ORDERED, and the order is normative**
  *(CORRECTED-r3, gate r2-M1 — r2 said "the marker window ±20 plus
  head-and-tail fill up to the cap" and left the split unpinned, which is why
  `SCAN8`'s mutations were not discriminators: every live managed section sits
  in the last 3% of its file (k1c: markers at 354/356 of 365), so tail fill
  retained the real section no matter how the markers were matched)*. When a
  file exceeds `CANON_BYTES_PER_FILE`, the retained bytes are, **in priority
  order**:

  1. **the managed region** — the marker window ±20 lines, located by the
     imported `BEGIN_MARKER`/`END_MARKER` **case-sensitively**. It is
     **reserved first and always retained**, whatever its offset in the file.
     When the markers cannot be located, (1) is empty and the block is
     head-and-tail fill only, **marked as such**.
  2. **head fill** — from the start of the file.
  3. **tail fill** — from the end of the file.

  Head and tail budgets are computed **after** the reservation, from whatever
  the cap leaves. Every dropped span is marked. A truncated block never
  silently looks whole.

  **Residual scope of the guarantee, stated honestly** *(added r3, gate r2-N4,
  with the gate's own count corrected)*: this rule binds only files over
  `CANON_BYTES_PER_FILE = 32768`. Measured against the live surface set at
  `50fa815` — **three** of the ten surfaces are over the cap (`~/.config`
  72,467 B; `~/repos/nsys-marketplace` 39,146 B;
  `~/repos/nsys-marketplace-local` 39,714 B), and of those **two are
  marker-bearing** (`~/.config`, `~/repos/nsys-marketplace-local`);
  `~/repos/nsys-marketplace` has no managed section at all, so clause (1) is
  empty there and it is head-and-tail fill only. The other seven surfaces are
  returned whole and marker matching has no observable effect on them. So
  criterion B's re-homed guarantee is exercised **live on two hosts** and by
  fixture everywhere else. *(The r2 gate measured "exactly one … `~/.config`";
  re-measured here against the same §3.3 byte column, 39,146 and 39,714 both
  exceed 32,768 — see §15.2.)*
- **Missing / unreadable file** ⇒ an explicit sentinel line naming the reason,
  never omission (the `path_roster` "no slot is ever omitted" discipline).
- **Unregistered ancestors** ⇒ a single line
  `### (unregistered ancestor with a CLAUDE.md: <path>) — not read` per
  member of `unregistered_ancestor_dirs`, plus flag `unregistered-ancestor`
  on the proposal.
- `canon_bytes=<n>` is logged per record and summed per batch (BR-2).

### 6.3 Doctrine

`routing-doctrine.md` gains the amendment text in §14.2. In summary: G0's
`canon` leg is told that canon "that already loads" is a **two-item** list —
an **ancestor host's** `CLAUDE.md` and the **hand-written** regions of the
record's own host `CLAUDE.md`. **`references/` files are deliberately not on
that list** *(CORRECTED-r2, gate B2: r1's §14.2 shipped a three-item list whose
extra clause would have made a DEMAND-tier lesson eligible for GRADUATE — the
exact failure the DEMAND tier, the pointer block and `--selftest reach` exist
to prevent)*; a `references/` hit is the separate "already on the shelf" signal
of §6.2 item 3, and it reaches the human only through the card; T4's narrowest-surface ranking is told that an ancestor
`CLAUDE.md` is **more** expensive than the child's (it loads in every child of
that ancestor, not just this one) and **less** expensive than `~/.claude`; and
§3's ancestor-project clause gains one sentence separating a *re-home*
(the record belongs to the umbrella) from *inheritance* (the lesson is already
loaded there — that is `G0.canon`, not a re-home).

### 6.4 Reachability

- `selfcheck._loaded_surface`: for `record.scope == "project"`, return
  `[host/"CLAUDE.md"] + [a/"CLAUDE.md" for a in ancestors_of(...)]` —
  appended, nearest-first, after the own-host member. Skill and user rows
  unchanged. Empty stays a FAILURE, never a skip (U-reach criterion 8).
- `compilers.surface_names_target` is **unchanged**. Adding members can only
  turn an unreachable record reachable, never the reverse; no predicate moves.
- **The pointer prose gains a base** when the host has a registered ancestor
  **or** a registered descendant — the only configurations in which two
  self-learn pointer blocks can load in one session. Today all three live blocks
  are byte-identical (§3.6). Such a host's block gains this sentence, **verbatim**
  (`ANC8` pins the string; a builder may not reword it):

  > `paths are relative to the directory containing this file, not your working directory`

  The **token is unchanged** — still `references/LEARNINGS.md` — so
  `compilers.surface_names_target`, `compilers.pointer_token` and every
  `test_pointer.py` contract keep their meaning; only the surrounding prose
  disambiguates. **The base is deliberately NOT an absolute path** (ruling Q2):
  `surface_names_target` would accept an absolute token and it would resolve
  correctly from any cwd, but a `CLAUDE.md` is a tracked file and
  `~/repos/claude-skills` has a public remote, so an absolute token would commit
  a real home path into a public repo. Hosts with neither an ancestor nor a
  descendant emit today's byte-identical line (UN group; `UN2`/`UN3` and `M23`
  are what keep the sentence off them).

### 6.5 Telemetry — traced, not changed

Traced for question 5; **this unit changes nothing in the telemetry plane.**

- **Fire → violated → suspect (the miner's crossover).** `miner._canon_index`
  iterates `discover_buckets(home)` — **every** bucket, every scope — so a
  session mined under the child host can report a fire against an
  **umbrella-bucket** record. `miner._raise_recurrence_suspect` spools
  `recurrence-suspect` with `record=<the routed record's id>`, and
  `verbs.confirm_recurrence` appends to **that record's** `recurrences:` list
  wherever it lives. **Correct today; asserted as a no-regression criterion
  (`TEL1`).**
- **Title-overlap suspects (the worker's basis).**
  `worker._recurrence_suspects` scans `entry.bucket_dir / "resolved"` — the
  **same bucket only**. A new pending record captured in the child that
  restates an umbrella-routed lesson raises **no** suspect. **This unit does
  not widen it** (`TEL2`): widening the domain changes the Jaccard base rate
  for every bucket at once, and FW-49 records that this basis was already
  narrowed once on measured evidence. Carried as **FW-127**.
- **`dismiss-suspect` (U-dismiss).** Operates on `record_id` + the suspect's
  frontmatter entry; host-agnostic. Unaffected.

---

## 7. Card sections — the registry is the only source

One new section, added to
`plugins/self-learn/skills/self-learn/references/card-sections.yaml` **and
nowhere else** (the file's own contract: *"to change, add, or retire a section
… edit THIS FILE ONLY. Nothing downstream breaks, because nothing downstream
knows section names."*).

```yaml
already_kept:
  label: "You may already have this"
  order: 35
  required: optional
  instruction: >
    Write this section only when the lesson's substance already appears
    somewhere this project can reach: a parent/umbrella project's CLAUDE.md, a
    hand-written part of this project's own CLAUDE.md, or one of this project's
    references files. Quote the shortest span that covers it and name the file
    and the line it came from. Then say which of two very different things you
    found. (a) It LOADS — a parent project's CLAUDE.md or this project's own
    CLAUDE.md is in front of Claude in every session here. (b) It is ON THE
    SHELF — a references file is only read when someone follows a pointer to
    it, so the lesson is written down but not in play. Say which, in plain
    words, every time; a shelf entry is not the same as a rule that is already
    running, and a reader who cannot tell them apart will make the wrong call.
    Also say whether the text you found INSTRUCTS or merely MENTIONS the same
    subject, and if it looks out of date say so and say why — "already written
    down" and "still true" are two different claims. Never present this as a
    verdict and never argue for one resolution: it is evidence for the reader's
    decision, and the reader makes that decision.
```

`order: 35` places it after `impact` ("What changes if you keep it") and
before `discuss` ("Worth discussing"): a reader deciding whether to keep a
lesson needs "you may already have this" before the steelman, not after it.

**`already_kept` is not `conflict`, and the two must never be written about the
same span** *(added r2, gate N17)*. The registry already carries
`conflict: {label: "May clash with a rule you already kept", order: 55}`.
`already_kept` says *the lesson is ALREADY covered* — keeping it adds nothing.
`conflict` says *an existing rule would CLASH with it* — keeping it creates a
contradiction. They are opposite findings about existing canon, and a card that
asserts both about one span is incoherent on its face.

No surface change is required or permitted: surfaces iterate by ascending
`order`, emit `label` + text for keys present, and skip absent keys.

---

## 8. Failure modes and exit codes

**No new verb, therefore no new exit code.** The table is the full set this
unit can reach.

| Condition | Where | Behaviour | Exit code |
|---|---|---|---|
| `hosts.yaml` missing / unreadable | `ancestors_of` via `load_hosts` | returns `[]`; own-host block still emitted | unchanged (worker run continues) |
| Ancestor `CLAUDE.md` missing | `canon_blocks` | sentinel line naming the path; no ancestor block | unchanged |
| Ancestor `CLAUDE.md` not UTF-8 | `canon_blocks` | sentinel line naming the decode error; block omitted | unchanged (contrast `_check_reach`, where an undecodable **loaded surface** is a FAILURE — FW-66) |
| Own-host `CLAUDE.md` over `CANON_BYTES_PER_FILE` | `canon_blocks` | truncated, marker window retained, truncation marked, `canon_bytes` logged | unchanged |
| Per-record total over `CANON_BYTES_PER_RECORD` | `canon_blocks` | `references` blocks dropped last-first, drop logged | unchanged (report-only, BR-2) |
| Unregistered directory with a `CLAUDE.md` on the ancestor path | `unregistered_ancestor_dirs` | path-only line + flag `unregistered-ancestor` | unchanged |
| A reference-routed record unreachable from own host **and** every registered ancestor | `selfcheck._check_reach` | FAIL, counted, named | `--selftest` **rc 1** (existing) |
| `g0.canon.target` outside a managed section without the `already_kept` card section or the `canon-hand-written` flag | proposal validator | refusal, proposal not stamped | `proposal validate` **rc 1** (existing `EXIT_SCHEMA_INVALID`) |
| `g0.canon.target` resolves inside `<host>/references/` (or `<skill_dir>/references/`) *(added r3, gate r2-N6 — `CARD4`'s refusal was missing from a table that claims completeness)* | proposal validator | refusal, proposal not stamped; the analyst is told to write `already_kept` instead | `proposal validate` **rc 1** (existing `EXIT_SCHEMA_INVALID`) |

---

## 9. Criteria

Each criterion: **ID · statement · check command · mutation**. No code exists
yet, so every mutation cell is `predicted` unless marked **MEASURED** (those
were applied to shipped code, or read off it, during this spec's census).

### LOAD — the derivation matches the measured loading rule

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **LOAD1** | `ancestors_of` returns exactly the registered hosts that are proper resolved-path prefixes of the target, **nearest-first** | `pytest -k test_ancestors_of`. **Fixture requirement (r2, gate N12): `hosts.yaml` lists the ancestors FARTHEST-first, and the assertion is on the ordered list, not a set** — otherwise removing the sort leaves the output unchanged and the mutation cannot fire | drop the nearest-first sort ⇒ LOAD1 red · `predicted` |
| **LOAD2** | It never returns the target itself, a sibling, or a descendant | same fixture, three negative assertions. **Fixture requirement (r2, gate N12): the registered set contains a `/x/a` + `/x/ab` pair**, so the separator-less prefix test is observable on the sibling leg as well as the self leg | change `startswith(a + os.sep)` to `startswith(a)` ⇒ LOAD2 red (both legs: `/x/ab` matches `/x/a`, and the target matches itself) · `predicted` |
| **LOAD3** | A registered ancestor **above the child's git root** is still returned | fixture: `git init` in the child only | add a `gitops.toplevel` stop ⇒ LOAD3 red · `predicted` |
| **LOAD4** | An unregistered directory carrying a `CLAUDE.md` between child and nearest registered ancestor is **not** in `ancestors_of`, and **is** in `unregistered_ancestor_dirs` | fixture with an unregistered mid-directory | make `ancestors_of` fall back to "any dir with a CLAUDE.md" ⇒ LOAD4 red · `predicted` |
| **LOAD5** | `03-decisions.md` S-52 records the loading rule **and names the instrument that produced each half**: `InstructionsLoaded` hook events for the positives AND for the descendant/sibling negatives, with the `nested_traversal` positive control; and records the concatenation ORDER and the walk's terminus as **doc-sourced, not measured** | `grep -n "S-52" docs/specs/self-learn/03-decisions.md`; the row must contain `InstructionsLoaded`, `nested_traversal`, and the phrase "not measured" — matched **case-insensitively** (`grep -ci "not measured"` >= 1), because S-52 writes it as **"NOT measured"** for emphasis *(CORRECTED-r3, gate r2-N1: r2's check demanded the lowercase literal while the row it checks writes the uppercase one — fail-closed, but a builder would have "fixed" it by loosening the check instead of reconciling the two)* | delete the instrument clause, or restore r1's "the transcript is the instrument" ⇒ LOAD5 red · `predicted`. *(r1's claim was **MEASURED false**: the session `.jsonl` carries each marker exactly once, in the assistant record — §2.2.)* |
| **LOAD6** | Ancestry is **derived, never persisted**: `ancestors_of` and `unregistered_ancestor_dirs` write nothing, `Bucket`'s identity fields are unchanged, and no ledger file's bytes change across an analyst run *(added r2, gate M3)* | (a) `pytest -k test_bucket_identity_unchanged`; (b) an end-to-end test that snapshots `sha256 + mtime` of **every** file under a two-host fixture home, runs the analyst path, and asserts the snapshot is unchanged; (c) a `meta.yaml`-writer census (`grep -rn "meta.yaml" cli/src/self_learn/*.py`) asserting the write set is exactly **two** functions — `ledger_ops.ensure_project_meta` (`ledger_ops.py:325`, bucket creation) and `hosts._dump_meta` (`hosts.py:537`, called at `hosts.py:480` on the `host rebind` bucket-move path) — and that neither `ancestors_of` nor `unregistered_ancestor_dirs` appears in it *(CORRECTED-r3, gate r2-N11: r2 named `ensure_project_meta` only, so leg (c) was red against correct code; both writers verified by measurement)* | memoise ancestry by writing an `ancestor:` key into `<bucket>/meta.yaml` ⇒ LOAD6 red on legs (b) and (c) · `predicted` |

### ANC — the ancestor edge reaches the analyst, the checker, and the pointer

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **ANC1** | For a project record whose host has a registered ancestor, `canon_blocks` contains a block headed by the ancestor's absolute `CLAUDE.md` path and labelled `inherited` | `pytest -k test_canon_blocks_ancestor` | drop the ancestor loop ⇒ ANC1 red · `predicted` |
| **ANC2** | Ancestor blocks are nearest-first and at most `ANCESTOR_DEPTH_CAP` | fixture with 3 registered ancestors | raise/remove the cap ⇒ ANC2 red · `predicted` |
| **ANC3** | Skill- and user-scope records get **no** ancestor block | `pytest -k test_canon_blocks_no_ancestor_offproject`. **Fixture requirement (r2, gate N13): the fixture must register a host at the PARENT of its user-scope surface** — otherwise no registered host is a proper prefix of `~/.claude`, the mutant returns `[]`, and the user leg stays green while the guard is gone. The skill leg is observable under the live shape without help (`skills_root` is itself a registered project host, so every `plugins/*/skills/*/SKILL.md` has a registered proper prefix) | drop the scope guard ⇒ ANC3 red on **both** legs · `predicted` |
| **ANC4** | No **write target** is derived from an ancestor: `_resolve_target`'s returned `TargetSpec` is byte-identical for every (scope, destination, ref_name) triple before and after | `pytest -k test_resolve_target_unchanged_under_ancestry` | make `_resolve_target`'s project leg call `ancestors_of` ⇒ ANC4 red · `predicted`. **Scope note (r2, gate N11): ANC4 pins the resolver's routing/destination OUTPUT, not the function's source bytes.** U-hostmode is expected to mode-branch the dirty/gate calls already inside it; that changes no returned target and leaves ANC4 green |
| **ANC5** | An unregistered ancestor dir with a `CLAUDE.md` yields a **path-only** line plus the `unregistered-ancestor` flag, and its bytes appear nowhere in the composed prompt | assert the file's distinctive content is absent from `compose_record_block` output | read the file instead of naming it ⇒ ANC5 red · `predicted` |
| **ANC6** | `ui`'s `target_canon_excerpt` still **delegates** (no second implementation) | `grep -n "from self_learn.worker import" ui/src/self_learn_ui/pane.py` + `pytest -k test_pane_delegates` | hand-copy the body into `pane.py` ⇒ ANC6 red · **MEASURED**: `pane.py:72` is `from self_learn.worker import cache_dir, canon_excerpt` and `target_canon_excerpt` (`:272-277`) is a one-line delegation (FW-48) |
| **ANC7** | For a project record whose host has a registered ancestor, `selfcheck._loaded_surface(...)` returns `[host/CLAUDE.md, ancestor/CLAUDE.md]` **in that order** *(added r2, gate M2)* | `pytest -k test_loaded_surface_includes_ancestor`; plus an end-to-end leg — a reference-routed record in the ANCESTOR bucket, pointed at only from the ancestor's `CLAUDE.md`, is reported **reachable** by `--selftest` | revert the append ⇒ ANC7 red, and `--selftest`'s `reach` row goes to rc 1 on the end-to-end leg · `predicted` |
| **ANC8** | A host with a registered ancestor **or** a registered descendant emits a pointer block whose prose contains, verbatim, `paths are relative to the directory containing this file, not your working directory`, while the pointer **token** is byte-unchanged *(added r2, gate M2)* | `pytest -k test_pointer_prose_names_its_base`; plus `test_pointer.py` unchanged (the token contract) | drop the sentence ⇒ ANC8 red · `predicted`. Change the token instead ⇒ existing U-pointer tests red · `predicted`. **Per the Q2 ruling the base is NOT an absolute path**: an absolute token would put a real home path into `CLAUDE.md` files committed to public repos |

### SCAN — the hand-written surface, and what supersedes what

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **SCAN1** | The own-host block is the **whole** file up to `CANON_BYTES_PER_FILE`; the `<200 lines` / `markers ±20` / `first-60` three-way branch is gone. **This criterion SUPERSEDES `u-marker-excerpt-case-spec.md` §3 criterion A's A3 leg** *(r2, gate B1; narrowed r3, gate r2-N2)* — **A3**'s exact-window equality (`excerpt_lines == lines[begin-20:end+21]`) is obsolete once the whole file is read, while **A0/A1/A2 are preserved** and re-asserted here against the whole-file contract (the fixture stays ≥200 lines with its begin index >60, and both imported markers and `compilers.entry_line(R)` must be present). The four shipped tests that pin A3 are rewritten in-scope (§11) | `pytest -k test_canon_blocks_whole_file` — the shipped fixture is `test_canon_blocks_whole_file_reaches_the_compiler_written_section` (`cli/tests/test_worker.py`): 250 synthetic `authored line N` lines, a REAL compiler-written section (`compile_managed_text`, no marker spelling typed), and 30 trailing lines, asserting both markers, `compilers.entry_line(R)`, and text far on EITHER side of the section are all present *(D1, code gate r1: this cell named a literal k1c-shape/`lrn-bcf6b3e7` regression fixture — 365 lines, markers at 354/356, covering rule at 146, asserting `k1c-backup-system` present — that was never built; a byte-faithful reproduction of that record's real content was not available to construct one, so the shipped test proves the same WHOLE-FILE-REACH property generically instead. The MEASURED pre-state figure just right of this cell is unaffected — it describes `lrn-bcf6b3e7`'s actual historical miss, not this fixture, and remains true either way)* | restore the `±20` window ⇒ SCAN1 red · `predicted` (the pre-state is **MEASURED**: 0/5 terms in 2,923 of 25,499 B) |
| **SCAN2** | The references blocks appear, sorted, capped, **and scope-correct** *(r3, gate r2-N8)*: project → `<host>/references/**`; skill → `<skill_dir>/references/**`; user → **no block at all** (S-23: user scope has no references dir) | `pytest -k test_canon_blocks_references`, three legs — one per scope; the user leg asserts **absence**, not a sentinel | drop the references loop ⇒ SCAN2 red (project + skill legs) · `predicted`. Emit a references block at user scope ⇒ SCAN2 red (user leg) · `predicted` |
| **SCAN3** | Every references block carries the verbatim label `(captured, NOT loaded — pointer-reached; not eligible for g0.canon)` *(added r2, gate B2)* | `pytest -k test_references_block_labelled_not_loaded` | drop the label ⇒ SCAN3 red · `predicted` |
| **SCAN4** | **Nothing** outside `canon_read_roots`' project family is read: for a fixture host containing `docs/known-issues.md`, `README.md`, `src/x.md` **and `CLAUDE.local.md`**, each with a distinct sentinel, none appears in the composed prompt | `pytest -k test_canon_blocks_reads_nothing_outside_canon_roots` | add `host.glob("docs/**/*.md")`, or add `CLAUDE.local.md`, ⇒ SCAN4 red · `predicted`. **MEASURED anchor**: `hosts.canon_read_roots` (`hosts.py:617-621`) appends exactly `host/"CLAUDE.md"` and `host/"references"` per project |
| **SCAN5** | `canon_bytes` is logged per record and per batch, and a cap that fires is logged, never raised | `pytest -k test_canon_bytes_logged`; positive control — a fixture over the cap logs a **non-zero** drop | make the cap raise ⇒ SCAN5 red · `predicted` |
| **SCAN6** | A `g0.canon.target` naming a region **outside** a managed section, without the `already_kept` card section **or** without the `canon-hand-written` flag, is **refused** by `proposal validate` with rc 1 (HW-1) | `pytest -k test_hand_written_canon_needs_card_and_flag` | drop either half of the conjunction ⇒ SCAN6 red · `predicted`. **MEASURED anchor**: `ledger_ops.py:1669-1671` already refuses a `GRADUATE` proposal lacking `already_canon: true` |
| **SCAN7** | No verb auto-resolves on a hand-written hit: `graduate` still requires an explicit human invocation and `already_canon: true` | `pytest -k test_no_autograduate` | **(r2, gate N15 — the mutation now names a site the test can drive)** make `verbs.route` invoke `verbs.graduate` when the proposal carries flag `canon-hand-written` ⇒ SCAN7 red · `predicted` |
| **SCAN8** | Under the byte cap the compiler-written managed region is **always** retained — reserved FIRST by §6.2's ordered retention, before any head or tail fill — and it is located by the imported `BEGIN_MARKER`/`END_MARKER` **case-sensitively**, so a case-variant the compiler never wrote is not treated as a managed region. **This is `u-marker-excerpt-case-spec.md` §3 criterion B, re-homed** *(r2, gate B1)*: B's discriminator outlives the branch it used to guard, moving to the truncation path | `pytest -k test_cap_retains_managed_region`. **Fixture requirement, load-bearing (r3, gate r2-M1): the real compiler-written section must sit in the MIDDLE of the file, outside BOTH the head fill and the tail fill** — at least `CANON_BYTES_PER_FILE` of filler before it and after it — so that **only** clause (1)'s marker location can retain it. Without that placement the mutations cannot fire: every live managed section sits in the last 3% of its file (k1c: markers at 354/356 of 365), where tail fill retains it regardless of how the markers are matched. The fixture also carries an **uppercase decoy marker pair placed early but AFTER the head-fill budget**, and before the real section *(CORRECTED-r4, gate r3-N1: r3 put the decoy "inside the head fill", where correct code retains it as ordinary fill — which made the negative assertion RED on correct code. After the head-fill budget it lands in the dropped span under correct code, while remaining the FIRST case-folded match, so `M30`/`M37` are untouched)*. Layout, start to end: head filler ≥ the head-fill budget · the decoy pair · filler · the real compiler-written section · tail filler ≥ the tail-fill budget. Assertions, positive **and** negative: (+) both imported markers and `compilers.entry_line(R)` are present, and the retained window's line numbers are the REAL section's; (−) the decoy pair's ±20 neighbourhood is **absent** from the block. **The negative leg is now a second, independent discriminator**: under `M30`/`M37` the decoy becomes the reserved window and therefore APPEARS, so those mutations redden both legs, not one | **Re-predicted r3 against the middle-placed fixture (gate r2-M1); all fire.** **M30** case-fold the marker match (`BEGIN_MARKER.lower() in ln.lower()`, same for end — u-marker's own `M5`, "the plausible defensive fix") ⇒ clause (1) reserves the DECOY's window and the real section is in neither fill ⇒ both assertions red. **M31** drop clause (1) entirely (head-and-tail fill only) ⇒ the real section is retained by neither fill ⇒ positive assertions red. **M35 / M36** *(added r3, gate r2-N3 — u-marker's `M1`/`M2`, the two halves of the shipped legacy-needle bug)* restore the legacy needle on the begin line only / the end line only ⇒ the markers are unlocatable, clause (1) is empty, the real section falls in neither fill ⇒ red. **M37** *(u-marker's `M3`)* replace both needles with a case-folded short token ⇒ the decoy matches ⇒ red. **This over-cap path is where u-marker's whole mutation table now lives**: under whole-file reading `A1` is vacuously true (the file contains the markers whatever needle the code searches for), so the marker-respelling defect is observable nowhere else · all `predicted` |

### CARD — the registry is the only source

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **CARD1** | `already_kept` exists in `card-sections.yaml` with `order: 35`, `required: optional` | `python -c "import yaml;print(yaml.safe_load(open('…/card-sections.yaml'))['already_kept'])"` | delete the entry ⇒ CARD1 red · `predicted` |
| **CARD2** | **No** surface names the key — including **command prose** *(r2, gate N14)*: `grep -rn "already_kept" plugins/self-learn ui/src --include='*.py' --include='*.md'` filtered of `references/card-sections.yaml` **and of every path under a `tests/` directory** *(added r5, code gate r1 D2)* returns 0, `rc` captured **unpiped**. **Measured 2026-08-28: the grep as r2 left it (filtered of `references/card-sections.yaml` only) returns 18 hits** — all 18 are in `cli/tests/test_u_ancestry.py` (10) and `ui/tests/test_card_sections.py` (8), CARD1/CARD3/SCAN6's own fixtures and assertions exercising the literal key by name. Test files are not a rendering SURFACE in this criterion's sense — they verify the registry's contract, they do not re-derive a section name from it the way a doctrine paragraph or a validator message would — so the `tests/` exclusion is added here rather than left as an undeclared filter inside the test. | that grep. **Positive control**: the same grep for `conflict` returns hits in `plugins/self-learn/commands/review.md`, `README.md` and `SKILL.md` — proving the grep can see command prose, which r1's narrower scope (`cli/src ui/src`) could not; re-run **with** the `tests/` exclusion, `conflict` still hits `commands/review.md` (outside any `tests/` dir), so the exclusion does not blind the positive control | hardcode the key in `plugins/self-learn/commands/review.md` ⇒ CARD2 red (r1's grep would have stayed green) · `predicted` |
| **CARD3** | A proposal carrying `already_kept` renders it between `impact` and `discuss` on both the slash-command card and the web UI | `pytest -k test_card_order` (ui) | change `order` to 95 ⇒ CARD3 red · `predicted` |
| **CARD4** | A hit found **only** in a `references/` file never sets `already_canon: true`, never yields `g0.canon.answer: yes`, and never derives outcome `GRADUATE` — it populates `already_kept` and nothing else *(added r2, gate B2)* | `pytest -k test_references_hit_is_not_already_canon`: a proposal whose `g0.canon.target` resolves inside `<host>/references/` is **refused** by `proposal validate` (rc 1) | accept a `references/` path as a `g0.canon.target` ⇒ CARD4 red · `predicted`. **MEASURED anchor for the rule**: `selfcheck._loaded_surface` never returns a `references/` file, and the compiled pointer block says verbatim "Captured lessons that are **NOT loaded into this context**" |

### TEL — the telemetry plane, asserted unchanged

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **TEL1** | A `fire … outcome: violated` naming an **ancestor-bucket** record, observed while mining a **child-host** session, raises the `recurrence-suspect` against that ancestor record and `confirm-recurrence` appends to it | `pytest -k test_fire_crosses_host_boundary` (fixture: 2 buckets in an ancestor relation) | narrow `miner._canon_index` to the session's own bucket ⇒ TEL1 red · `predicted` |
| **TEL2** | `worker._recurrence_suspects` still compares only within `entry.bucket_dir / "resolved"` — this unit does **not** widen it | `pytest -k test_recurrence_suspects_same_bucket_only`; positive control — an ancestor-bucket routed record with 1.0 title overlap raises **0** suspects | widen to `discover_buckets` ⇒ TEL2 red · `predicted` |

### UN — the unaffected group behaves byte-identically

"UN group" means two different memberships, and r2 used one label for both
*(CORRECTED-r3, gate r2-N7)*:

- **Ancestry half — 7 hosts** with no registered ancestor: `~/.config`,
  `3d-printing`, `claude-skills`, `ignomi`, `keyboards`, `nsys-marketplace`,
  `nsys-marketplace-local`. These get no ancestor block (`UN1`) and no extra
  `_loaded_surface` member (`UN3`).
- **Pointer half — 5 hosts**, with neither a registered ancestor **nor** a
  registered descendant: the seven above **minus `3d-printing` and
  `keyboards`**, which have registered descendants (`k1c-manta-m5p`,
  `zmk-config-offsetkey`) and therefore **DO** receive `ANC8`'s base-naming
  sentence. A builder writing a "UN" test over the live host list from r2's
  single definition would have asserted byte-identity on two hosts that are
  supposed to change.

Plus a synthetic host with neither an ancestor, nor a descendant, nor any
hand-written region, for the combined half (`UN2`).

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **UN1** | For a record in a no-ancestor host, `canon_blocks` emits **no** ancestor block and **no** unregistered-ancestor line | `pytest -k test_un_no_ancestor_block` | emit an empty ancestor header unconditionally ⇒ UN1 red · `predicted` |
| **UN2** | For a synthetic host whose `CLAUDE.md` is 100% managed section and whose `references/` is absent, `compose_record_block` output is **byte-identical** to the pre-change baseline | `pytest -k test_un_block_sha_unchanged`, against a **fixture-local** baseline sha captured pre-change. *(CORRECTED-r2, gate N6: r1 pinned three live-queue shas as MEASURED. They are not reproducible — `path_roster` embeds the ledger-home path 4× per record, so the hash is a function of where the ledger copy lives. Byte COUNTS at an equal-length home are reproducible (§3.5); hashes are not, and no live-queue sha is pinned anywhere in this spec.)* `zmk-config-offsetkey` is the live instance of the shape (3 lines, 0 hand-written, tier A = **1 B**) | append any unconditional label line ⇒ UN2 red · `predicted` |
| **UN3** | `--selftest`'s `reach` row output is byte-identical for a ledger containing only no-ancestor hosts | `self-learn --selftest` against a fixture home, diff. *(This is the NEGATIVE half only; `ANC7` carries the positive half — r1 had no positive criterion, gate M2.)* | append ancestors unconditionally in `_loaded_surface` ⇒ UN3 red · `predicted` |

### DOC — the docs footprint

| ID | Criterion | Check | Mutation |
|---|---|---|---|
| **DOC1** | `03-decisions.md` carries the **S-52** row (§14.1 text) | `grep -c "^| S-52 " docs/specs/self-learn/03-decisions.md` = 1 | delete ⇒ DOC1 red · `predicted` |
| **DOC2** | `14-forward-work-map.md` carries **FW-125**, **FW-126**, **FW-127** (§14.3 text) | `grep -cE "^\| FW-12[567] " docs/specs/self-learn/14-forward-work-map.md` = 3 | delete any ⇒ DOC2 red · `predicted` |
| **DOC3** | The doctrine amendment lands in **all three** sections — `routing-doctrine.md` §2 (G0), §3, §4 — not three times in one *(r2, gate N16)* | per-section, not whole-file: `awk '/^## 2\. The gate procedure/,/^## 2a\./' … ` piped to `grep -c "ancestor host"` ≥ 1, and the same `awk` range test for `^## 3\. The tier model` and `^## 4\. Repo conventions`. **Positive control**: `grep -c "ancestor host"` on the file today = **0** | put all three insertions in §2 ⇒ DOC3 red on the §3 and §4 ranges · `predicted` |
| **DOC4** | The deployed skill is the repo's (symlink), so DOC3 is live without a copy step | `ls -la ~/.claude/skills/self-learn` shows a symlink into `plugins/self-learn/skills/self-learn` | replace the symlink with a copy ⇒ DOC4 red · **MEASURED** 2026-08-27 |
| **DOC5** | The U-marker supersession is written where a reader of U-marker will meet it *(added r2, gate B1)*: `u-marker-excerpt-case-spec.md`'s status header carries a dated `superseded by S-52 (SCAN1/SCAN8)` line naming which criterion leg died (**A3 only** — A0/A1/A2 survive, *r3, gate r2-N2*), which was re-homed (B), and where each of u-marker §3.1's five mutations went, and `14-forward-work-map.md`'s **FW-44** row gains the same dated note | `grep -n "superseded by S-52" docs/specs/self-learn/drafts/u-marker-excerpt-case-spec.md` = 1; `grep -n "S-52" docs/specs/self-learn/14-forward-work-map.md` hits the FW-44 row | delete either ⇒ DOC5 red · `predicted`. *(FW-44 is the register row U-marker names in its own header; it currently reads `✅ FIXED 2026-08-02`, and there is **no** U-marker row in `03-decisions.md` — measured.)* |

**Criterion count: 36** — LOAD 6, ANC 8, SCAN 8, CARD 4, TEL 2, UN 3, DOC 5.
**Mutation count: 37** (M1…M37).
*(r1 claimed 24 while listing 5+6+6+3+2+3+4 = 29 — an arithmetic error, gate N3.
r2 added LOAD6, ANC7, ANC8, SCAN3, SCAN8, CARD4 and DOC5 for the two blockers and
three majors, reaching 36 criteria / 34 mutations. **r3 adds no criterion** — the
r2 gate's single MAJOR was that `SCAN8`'s mutations did not discriminate, which is
fixed by pinning §6.2's retention ORDER and the fixture's middle placement, not by
adding a criterion — and adds three mutations, `M35`/`M36`/`M37`, carrying
u-marker §3.1's `M1`/`M2`/`M3` to their new home. Both totals are re-derived from
the tables above.)*

## 10. Mutation plan

| # | Mutation | Criteria that redden | Cell |
|---|---|---|---|
| M1 | `ancestors_of`: drop the nearest-first sort | LOAD1, ANC2 | `predicted` |
| M2 | `ancestors_of`: `startswith(a)` instead of `startswith(a + os.sep)` | LOAD2 | `predicted` |
| M3 | `ancestors_of`: stop at the child's git root | LOAD3, ANC1 | `predicted` |
| M4 | `ancestors_of`: return any ancestor dir containing a `CLAUDE.md`, registered or not | LOAD4, ANC5 | `predicted` |
| M5 | `canon_blocks`: drop the ancestor loop | ANC1, ANC2 (UN3 stays green — that is the control) | `predicted` |
| M6 | `canon_blocks`: emit ancestor blocks for skill/user scope too | ANC3 | `predicted` |
| M7 | `_resolve_target`: resolve the project host through `ancestors_of` | ANC4 | `predicted` |
| M8 | `canon_blocks`: read an unregistered ancestor's bytes | ANC5, SCAN4 | `predicted` |
| M9 | `canon_blocks`: restore the `markers ±20` window | **SCAN1**, and the `lrn-bcf6b3e7` regression fixture | pre-state **MEASURED** (§3.3: 0/5 terms in 2,923 of 25,499 B) |
| M10 | `canon_blocks`: drop the `references/**` loop | SCAN2 | `predicted` |
| M11 | `canon_blocks`: add `host.glob("docs/**/*.md")` | SCAN4 | `predicted` |
| M12 | `canon_blocks`: raise instead of logging when a cap fires | SCAN5 | `predicted` |
| M13 | Validator: accept a non-managed `g0.canon.target` without the flag | SCAN6 | `predicted` |
| M14 | *(retargeted r2, gate N15 — r1 said "add an auto-graduate branch" and named no site, so a validator test could not drive it)* make `verbs.route` invoke `verbs.graduate` when the proposal carries flag `canon-hand-written` | SCAN7, SCAN6 | `predicted` |
| M15 | Delete `already_kept` from `card-sections.yaml` | CARD1, CARD3 | `predicted` |
| M16 | Hardcode `already_kept` into a card **template** (`ui`) | CARD2 | `predicted` |
| M17 | `miner._canon_index`: narrow to the session's own bucket | TEL1 | `predicted` |
| M18 | `worker._recurrence_suspects`: widen to `discover_buckets` | TEL2 | `predicted` |
| M19 | `canon_blocks`: emit an empty ancestor header unconditionally | UN1, UN2 | `predicted` |
| M20 | `_loaded_surface`: append ancestors for every scope, unconditionally | UN3, ANC3 | `predicted` |
| M21 | `pane.py`: hand-copy `canon_blocks`' body instead of delegating | ANC6 | **MEASURED** as a live invariant (FW-48; `pane.py:72` imports, `:272-277` delegates) |
| M22 | Delete the S-52 / FW / doctrine text | DOC1, DOC2, DOC3 | `predicted` |
| M23 | Emit the disambiguating pointer prose for **every** host, ancestor or not | UN2, UN3 | `predicted` |
| **M24** | `_loaded_surface`: revert the ancestor append *(added r2, gate M2)* | **ANC7** — and `--selftest`'s `reach` row goes rc 1 on ANC7's end-to-end leg | `predicted` |
| **M25** | Pointer emitter: drop the base-naming sentence *(added r2, gate M2)* | **ANC8** | `predicted` |
| **M26** | Pointer emitter: replace the relative token with an absolute path *(added r2, gate M2 / ruling Q2)* | existing `test_pointer.py` token tests, and the §12 OUT rule against home paths in tracked `CLAUDE.md` | `predicted` |
| **M27** | Memoise ancestry by writing an `ancestor:` key into `<bucket>/meta.yaml` *(added r2, gate M3)* | **LOAD6** legs (b) and (c) | `predicted` |
| **M28** | `canon_blocks`: drop the `captured, NOT loaded` label from the references blocks *(added r2, gate B2)* | **SCAN3** | `predicted` |
| **M29** | Validator: accept a `<host>/references/…` path as a `g0.canon.target` *(added r2, gate B2)* | **CARD4** | `predicted` |
| **M30** | Case-fold the marker match (`BEGIN_MARKER.lower() in ln.lower()`, same for end) — u-marker's own `M5`, "the plausible defensive fix" *(added r2, gate B1; re-predicted r3, gate r2-M1)* | **SCAN8** — §6.2's clause (1) reserves the DECOY pair's window; the real section sits in the fixture's middle, in neither fill, so **both** the positive and the negative assertion go red. *(In r2 this mutation was NOT a discriminator: with the head/tail split unpinned and the real section at the file's end, tail fill retained it regardless of the match.)* | `predicted` |
| **M31** | Drop clause (1) from §6.2's retention entirely — head-and-tail fill only *(added r2, gate B1; re-predicted r3, gate r2-M1)* | **SCAN8** — the middle-placed section is retained by neither fill ⇒ positive assertions red | `predicted` |
| **M35** | Restore the legacy needle on the **begin** line only — u-marker's `M1` *(added r3, gate r2-N3)* | **SCAN8** — the markers are unlocatable, clause (1) is empty, the middle-placed section falls in neither fill | `predicted` |
| **M36** | Restore the legacy needle on the **end** line only — u-marker's `M2` *(added r3, gate r2-N3)* | **SCAN8**, same shape as M35 | `predicted` |
| **M37** | Replace both needles with a case-folded **short token** (`"self-learn:begin" in ln.lower()`) — u-marker's `M3` *(added r3, gate r2-N3)* | **SCAN8** — the uppercase decoy matches the short token, so clause (1) reserves the wrong window | `predicted` |
| **M32** | Hardcode `already_kept` into `plugins/self-learn/commands/review.md` *(added r2, gate N14)* | **CARD2** — and r1's narrower grep (`cli/src ui/src`) would have stayed green, which is why the scope moved | `predicted` |
| **M33** | Put all three doctrine insertions into `routing-doctrine.md` §2 *(added r2, gate N16)* | **DOC3** on the §3 and §4 `awk` ranges — r1's whole-file `grep … ≥ 3` would have stayed green | `predicted` |
| **M34** | Delete the `superseded by S-52` line from `u-marker-excerpt-case-spec.md`, or the FW-44 note *(added r2, gate B1)* | **DOC5** | `predicted` |

**M9 is the unit's isolator.** It is the one mutation whose red cell is the
measured defect itself: with the `±20` window restored, a fixture built from the
live k1c shape finds 0 of `lrn-bcf6b3e7`'s 5 scan terms; with the whole file,
4 of 5. **M30 is its guard**: the plausible way to *implement* SCAN1 wrongly is
to relax the marker search while widening the read, and M30 is the mutation that
catches it.

### 10.1 Unmutated-test census

*(CORRECTED-r2, gate B1. r1's central claim here was wrong in the direction that
matters — it told the builder the tests were absent when four of them pin the
exact behaviour SCAN1 removes.)*

```
$ grep -rlE "canon_excerpt|_loaded_surface|card-sections|compose_record_block|path_roster" cli/tests
test_composer.py  test_hosting.py  test_pointer.py  test_selftest.py  test_worker.py
$ uv run pytest tests/test_selftest.py tests/test_worker.py tests/test_composer.py tests/test_pointer.py --collect-only -q | tail -1
172 tests collected
```

**`test_worker.py` pins the excerpt by EXACT LIST EQUALITY in four tests, all
calling `worker._canon_excerpt(...)` directly** (`grep -n "canon_excerpt"
cli/tests/test_worker.py` → `:1396 :1445 :1496 :1539 :1572`):

| test | line | what it asserts | fate under SCAN1 |
|---|---|---|---|
| `test_canon_excerpt_finds_the_compiler_written_markers_in_a_fat_target` | 1403 | `excerpt_lines == lines[lo:hi]` *(A3 — exact list equality)* and `excerpt_lines == lines[231:274]`; docstring cites *u-marker §3 criterion A* | **RED.** Only **A3** is superseded by SCAN1 (*r3, gate r2-N2*); the test is rewritten to the new contract — whole file ≤ cap, with A0's fat-fixture guard, A1's two markers and A2's `entry_line(R)` all re-asserted |
| `test_canon_excerpt_case_variant_of_compiler_marker_does_not_match` | 1458 | `excerpt.splitlines() == [f"line {i}" for i in range(60)] + ["… (truncated)"]` | **RED.** Its *discriminator* survives as `SCAN8`; rewritten to assert the case-variant is not treated as a managed region under the cap |
| `test_canon_excerpt_begin_only_case_variant_does_not_match` | 1503 | same first-60 assertion | **RED**, same rewrite (half-fold, begin side) |
| `test_canon_excerpt_end_only_case_variant_does_not_match` | 1545 | same first-60 assertion | **RED**, same rewrite (half-fold, end side) |

**`test_worker.py` is ARMOR** — `cli/tests/test_worker_contract.py::_ARMOR_SHAS`
line 513 pins
`96ac0b4606a4e643b24c67df7202a897864ea404390fa6fd353655345d6eefe7`, and the
armor test hashes the working-tree file and refuses any change with *"Shipped
armor changed. If this was deliberate, U-sdkw is the wrong unit for it."*
**This unit must re-pin that sha, with its reason recorded beside it**, exactly
as `U-flip` and `U-cleanup-A` did for `conftest.py` / `test_invocation.py` /
`test_invocation_sdk.py` (the block of `#:` comments at `:517-534` is the
precedent and the required form). The re-pin justification is one line: *S-52
(SCAN1) supersedes u-marker §3 criterion A; the four `canon_excerpt` tests are
rewritten to the whole-file contract and criterion B is re-homed as SCAN8.* A
code gate that sees an unexplained armor motion should reject it; this one is
explained here, in the spec, before the build.

Remaining census, corrected:

- `test_selftest.py` carries **21** `test_reach_*` tests, 17 of them naming a
  criterion (`grep -c "def test_reach_"` = 21; `grep -c "def test_reach_.*criterion"`
  = 17) *(CORRECTED-r2, gate N8; r1 said 13)*. They pin the reachability
  *predicate* and the *message shape*; **none constructs an ancestor pair**, so
  **M5, M20 and M24 pass the existing suite**. `ANC7`, `UN3` and `TEL1` exist
  because of that.
- `test_pointer.py::TestScopeInvariants::test_c1_pointer_surface_matches_loaded_surface_project`
  (`:429`) pins LS's project member. It asserts a **match**, not a length, so
  appending ancestors leaves it green — correct, and the reason `ANC7` asserts
  the returned list positively rather than relying on this test.
- `test_composer.py` pins the byte-identity of the record block between the
  batch and single prompt forms (A11). It compares the two forms **to each
  other**, not to a baseline, so an addition made to both forms passes:
  **M19 and M23 pass it**. `UN2` supplies the missing baseline.
- Nothing anywhere reads `card-sections.yaml` keys by name; `CARD2` is a grep,
  green today (0 hits), with a live positive control (`conflict` hits three
  files, one of them `commands/review.md`).

**Conclusion of the census, corrected: the existing 172 tests would catch none
of M5, M19, M20, M23, M24, M25, M27–M34 — and they WOULD catch M9, loudly, in
four tests that must therefore be rewritten rather than left to fail.**

---

## 11. Tests — enumerated

New file: `cli/tests/test_u_ancestry.py`, plus additions to
`cli/tests/test_selftest.py` (the ancestor LS legs), `ui/tests/test_card_sections.py`
(CARD3), and **rewrites** of four existing tests.

**Rewrites (r2, gate B1)** — in `cli/tests/test_worker.py`, all four named in
§10.1. They are edited, not deleted, and each keeps its U-marker provenance
comment updated to say what superseded it:

1. `test_canon_excerpt_finds_the_compiler_written_markers_in_a_fat_target` →
   asserts the whole file is returned when under `CANON_BYTES_PER_FILE`, and
   that the compiled `entry_line(R)` and both markers are present. (A0's
   fixture guard — ≥200 lines, begin index >60 — is kept: it is what makes the
   fixture *fat*, which SCAN8 still needs.)
2. `test_canon_excerpt_case_variant_of_compiler_marker_does_not_match` →
   becomes `SCAN8`'s test: an over-cap file with an uppercase decoy pair early
   and the real section late; asserts the real section is retained.
3. + 4. the begin-only and end-only half-fold variants → same rewrite, each
   keeping its own half-fold so u-marker's M1/M2/M3 discrimination survives.

Re-pin `_ARMOR_SHAS["plugins/self-learn/cli/tests/test_worker.py"]` in the same
commit, with the one-line justification from §10.1.

**`ui/tests/test_pane.py` — three deletions, declared here** *(added D4, code gate
r1)*: `TestTargetCanonExcerpt` carried its own parallel copies of three of the
four u-marker-era tests above (`test_over_threshold_excerpts_around_markers`,
`test_over_threshold_case_variant_of_compiler_marker_does_not_match`,
`test_over_threshold_no_markers_truncates_first_60`) — window-math and
case-variant assertions against `pane.target_canon_excerpt`'s OWN output,
written when that function still risked a hand-copy (FW-48's original defect).
They are DELETED, not rewritten, and replaced by two tests: `test_delegates_
to_worker_canon_blocks` (ANC6 — asserts `pane.target_canon_excerpt(...) ==
worker.canon_blocks(...)` byte-for-byte on a real fixture) and `test_whole_
file_reaches_the_compiler_written_section` (a pane-side SCAN1 sanity check,
same shape as the CLI one). A fourth u-marker-era test in the same class,
`test_over_threshold_finds_the_compiler_written_section`, is REWRITTEN (not
deleted) into that second replacement, keeping its own name change tracked
alongside the CLI four above. The reason for deleting rather than rewriting
the other three: once ANC6's delegation test proves pane.py calls the EXACT
same `worker.canon_blocks` `test_worker.py`'s own SCAN1/SCAN8 tests already
pin, re-asserting the window-math/case-variant algorithm a SECOND time here
would be a driftable duplicate of that pin, not new coverage — the algorithm
has exactly one implementation and exactly one place its behaviour is proven.

**New fixtures:**

1. **`anc_pair`** — a ledger home with two registered hosts in an ancestor
   relation, a bucket + pending record under the child, ancestor `CLAUDE.md`
   carrying a distinctive rule. Drives ANC1/ANC2/ANC7, TEL1, UN3's negative half.
2. **`anc_none`** — one registered host, no ancestor, `CLAUDE.md` 100% managed
   section, no `references/`. Drives UN1/UN2. Modelled on
   `zmk-config-offsetkey` (3 lines, 0 hand-written).
3. **`anc_unregistered`** — child registered, mid-directory unregistered but
   carrying a `CLAUDE.md` with a distinctive string, grandparent registered.
   Drives LOAD4, ANC5.
4. **`k1c_shape`** — a 365-line `CLAUDE.md` with markers at 354/356 and the
   covering rule at line 146. The `lrn-bcf6b3e7` regression. Drives SCAN1, M9.
5. **`fat_two_markers`** — over `CANON_BYTES_PER_FILE`. Layout, start to end:
   head filler ≥ the head-fill budget · an **uppercase decoy marker pair,
   after that budget** · filler · the real compiler-written section **in the
   MIDDLE, outside both the head fill and the tail fill** (≥ one
   `CANON_BYTES_PER_FILE` of filler on each side of it) · tail filler ≥ the
   tail-fill budget. *(CORRECTED-r4, gate r3-N1: r3 placed the decoy "inside
   the head fill", where correct code retains it as ordinary fill and the
   negative assertion is red on a correct build. After the head-fill budget the
   decoy is dropped under correct code and reserved under `M30`/`M37`, which
   makes the negative leg a real second discriminator instead of a false
   alarm.)* *(CORRECTED-r3, gate
   r2-M1: r2 placed the real section "late", which is where every live managed
   section actually sits — k1c's markers are at 354/356 of 365 — and there the
   tail fill retains it regardless of how the markers are matched, so none of
   SCAN8's mutations could fire.)* Drives SCAN8 and M30, M31, M35, M36, M37.
6. **`noise_host`** — a host with `docs/known-issues.md`, `README.md`,
   `src/x.md` **and `CLAUDE.local.md`**, each with a distinct sentinel. Drives
   SCAN4.
7. **`git_boundary`** — `git init` in the child, registered ancestor above it.
   Drives LOAD3.
8. **`farthest_first`** — `hosts.yaml` listing ancestors farthest-first, and a
   `/x/a` + `/x/ab` sibling pair. Drives LOAD1 and LOAD2's mutations (gate N12).
9. **`user_scope_under_a_host`** — a registered host at the parent of the
   fixture's user-scope surface, so ANC3's user leg is observable (gate N13).
10. **`ledger_snapshot`** — a two-host home whose every file's `sha256 + mtime`
    is captured before and after an analyst run. Drives LOAD6.

Every fixture runs under the neutralised environment the CLI suite already
requires (`env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT`,
`SELF_LEARN_MINER=0`, `SELF_LEARN_MINER_AUTOKICK=0`), foreground.

## 12. IN / OUT

**IN**

- `hosts.ancestors_of`, `hosts.unregistered_ancestor_dirs` — pure, read-only,
  no writes (LOAD6).
- `worker.canon_excerpt` → `worker.canon_blocks`: whole own-host file (capped,
  managed region always retained and located case-sensitively), registered-ancestor
  blocks labelled *inherited*, `references/**` blocks labelled *captured, NOT
  loaded*, byte accounting.
- `selfcheck._loaded_surface`: ancestor members for project scope (ANC7).
- The pointer block's base-naming sentence for hosts with a registered ancestor
  or descendant; token unchanged (ANC8).
- One new `card-sections.yaml` entry (`already_kept`) and two new flags
  (`canon-hand-written`, `unregistered-ancestor`).
- Validator rules HW-1 (SCAN6) and the `references/`-is-not-canon refusal (CARD4).
- **Rewrites of four shipped tests** in `cli/tests/test_worker.py` and the
  matching `_ARMOR_SHAS` re-pin, with its justification (§10.1, §11).
- `03-decisions.md` S-52; `14-forward-work-map.md` FW-125…127 **and** the FW-44
  supersession note; `routing-doctrine.md` §2/§3/§4 amendment;
  `u-marker-excerpt-case-spec.md` status-header supersession line.

**OUT**

- **Any new verb or `--dest` grammar** — U-verbs owns that surface, by name.
- **Umbrella-as-destination** (a child record's canon landing in an ancestor
  host) — FW-125.
- **Widening `worker._recurrence_suspects`** across the ancestor edge — FW-127.
- **Reading anything outside `canon_read_roots`' project family** — the
  whole-root widening is user-ratifiable (Q3), not a spec author's call.
- **`<host>/CLAUDE.local.md`** *(added r2, gate N9)*. It **does** load — measured
  (`ANCTOKEN-BRAVO`, `memory_type: Local`, §2.2) — so this is a hand-written
  surface that binds the session and stays invisible to the analyst after this
  unit. It is excluded deliberately, on two standing grounds: it is **not in
  `canon_read_roots`** (`hosts.py:617-621` appends only `CLAUDE.md` and
  `references`), and U-reach §6 already rules it out as a loaded surface for
  pointer purposes because *"a pointer must be at least as durable as the thing
  it points at, and `local` is git-excluded by design"* (`selfcheck._loaded_surface`
  docstring). Feeding a git-excluded, machine-local file to the analyst would
  also make `already_canon` depend on state no teammate and no other machine
  has. `SCAN4`'s fixture asserts its exclusion; `§3.4`'s tier-A column measures
  its size so the residual gap is visible rather than silent.
- **Registering anything**, auto-rehoming, or reading an unregistered path's
  bytes.
- **Skill- and user-scope ancestry.** Neither has a path ancestry relation to a
  project host.
- **`~/.claude/CLAUDE.md`'s loading**, `--add-dir`, and
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` — out of scope in §2.3;
  `lrn-b21d1969`'s `--add-dir` clause stays doc-sourced.
- **The concatenation ORDER of loaded files, and the walk's terminus** — both
  doc-sourced, neither measured (§2.3), neither relied on by any criterion.
- **The `_check_drift`/`_check_reach` real-home resolution** discussion — named
  in §3.6, untouched.
- **Marker bootstrapping** for the two marker-less hosts.
- **The staleness question.** `lrn-bcf6b3e7` was *already canon* **and**
  *stale*; this unit surfaces the span and says so on the card, and rules
  nothing about how a stale-but-present fact should resolve.

---

## 13. Parallel units

Four units are in flight at the same base (`50fa815`). Files, symbols and doc
rows they may touch, with the interface assumption this spec makes about each:

| Shared surface | U-ancestry (this unit) | U-hostmode | U-corrob | U-verbs | Assumption this spec makes |
|---|---|---|---|---|---|
| `cli/src/self_learn/hosts.py` | adds `ancestors_of`, `unregistered_ancestor_dirs` (pure, read-only, no `gitops` call) | adds per-host `mode: git\|plain` and a ledger-side compile record; likely touches `host_add`'s git validation | — | — | **Ancestry is path arithmetic and never consults VCS state** (§6.1, normative). Whatever `mode` a host carries, `ancestors_of` behaves identically. The umbrella `~/repos/3d-printing` is the likely first `plain` host; this spec assumes nothing about its `.git` (it has one, created by `host add --init`, with **no remote** — `git -C ~/repos/3d-printing remote -v` is empty) |
| `worker.py` — the analyst prompt path (`canon_excerpt`, `compose_record_block`, `_PROMPT_TEMPLATE`) | replaces `canon_excerpt` with `canon_blocks`; adds `canon_bytes` logging | may add a per-host mode line to `path_roster` | may add a tool-events block | — | **Additive, disjoint regions.** `path_roster` (paths) and `canon_blocks` (content) are separate ingredients with separate headers. The A11 byte-identity contract between the batch and single prompt forms binds all of us |
| `selfcheck.py` — `_loaded_surface`, `_check_reach` | appends ancestor members for project scope | may change how an unresolvable/`plain` host is reported | — | — | **This unit only ever APPENDS members.** Appending can turn unreachable → reachable, never the reverse, so a U-hostmode change to the *resolution* of the own-host member composes without conflict |
| `verbs.py` — `_resolve_target` | **does not touch it**; `ANC4` pins its returned `TargetSpec` byte-identical for today's (scope, destination, ref_name) triples | expected to mode-branch the dirty-check/gate calls **already inside** it | — | owns any new `--dest` grammar or verb | *(added r2, gate N11)* **`ANC4` pins the resolver's OUTPUT, not its source bytes.** A U-hostmode change to how a dirty check or a registry gate runs inside `_resolve_target` returns the same target and leaves ANC4 green. If **U-verbs** lands a new `--dest` grammar first, ANC4's baseline is **re-pinned against the new triple set, not deleted** — the criterion is "no ancestor influences a write target", not "this function never changes" |
| `cli/src/self_learn/compilers.py` | *(added r5, code gate r1 N11)* `compile_pointer_text` gains a keyword-only `names_base: bool = False`; new `_POINTER_BASE_SENTENCE` + `_pointer_preamble(names_base=...)` build the ANC8 disambiguating sentence into a freshly-bootstrapped pointer block only | — | — | — | **Pure block arithmetic, no new I/O.** `names_base` only ever comes from `verbs._pointer_names_base` (read at APPLY time, never inside `_resolve_target` — ANC4); an ALREADY-PRESENT pointer block's prose is never rewritten (`compile_pointer_text` only inserts INTO an existing block or bootstraps a fresh one), so no sibling unit's prior write to a pointer block can be reverted by a later ANC8 apply |
| `cli/src/self_learn/ledger_ops.py` | *(added r5, code gate r1 N11)* adds `canon-hand-written` + `unregistered-ancestor` to `TRACE_FLAGS` (closed set; its length is pinned once, by `test_decision_trace.py`'s own assertion, never restated as a second hardcoded count); new `_validate_canon_target` (HW-1: a hand-written `g0.canon.target` needs BOTH the `canon-hand-written` flag and a non-empty `card` entry); `validate_proposal`/`write_proposal` gain a keyword-only `home: Path \| None = None` param that `_validate_canon_target` reads | — | — | — | **Additive to the closed sets and to the validator's own parameter list.** A sibling adding an 11th `TRACE_FLAGS` value collides only if it picks the same tuple position (unlikely — this unit appends at the end); `home` defaults to `None` (S4 — no filesystem I/O when omitted), so every existing positional/no-`home` call site is unaffected |
| `references/card-sections.yaml` | adds `already_kept` at `order: 35` | may add a host-mode section | may add a corroboration section | — | **Distinct keys, distinct orders.** This unit claims `already_kept` and `order: 35`; the registry contract makes any order legal, so a collision is resolved by whoever lands second moving |
| `03-decisions.md` | **S-52** | S-51 (assumed) | S-53 (assumed) | — | Reserved by the orchestrator; no overlap |
| `14-forward-work-map.md` | **FW-125, FW-126, FW-127**, plus a dated note on the existing **FW-44** | FW-122…124 (assumed) | FW-128+ (assumed) | — | Reserved; the FW-44 note is an edit to a `✅ FIXED` row nobody else has reason to touch |
| `routing-doctrine.md` | §2 (G0), §3 (ancestor clause), §4 (narrowest-surface ranking) | possibly §4 (a `plain` host's conventions) | possibly §2 (a new evidence source) | — | **§3's ancestor-project clause is this unit's.** If U-hostmode edits §4, the two land in different bullets; the whole-file mtime rule means either edit reaches all three consumers with no code change |
| `cli/tests/test_worker.py` + `test_worker_contract.py::_ARMOR_SHAS` | **rewrites four tests and re-pins the armor sha** (§10.1) | — | — | — | The armor sha is a single line; if another unit also re-pins it, the later lander re-hashes and appends its own `#:` justification, following the `U-flip` / `U-cleanup-A` precedent at `:517-534` |

**No sibling's feature is designed here.** Where a sibling's outcome would
change this unit's shape, the dependency is named and nothing more.

---

## 14. Docs to update in the same commit

**Builder note, dated** *(added r3, gate r2-D1)*: every date in §14.1–§14.4 is **2026-08-27**, this spec's authoring date. Two of these blocks ship into tracked files (`14-forward-work-map.md`'s FW-44 row and `u-marker-excerpt-case-spec.md`'s status header). If the build lands on a different day, substitute the landing date — never paste a placeholder, and never leave one behind: `grep -rn '2026-08-2' ` over the touched docs must return only real dates.

**Date-alignment note** *(added r5, code gate r1 N7)*: this rule governs the SPEC's own citation dates — when the loading-rule measurement was run, when a doc block was authored — not the BUILD's. The build lands separately (this unit's implementation started 2026-08-28, confirmed by the working tree's own file-write times), and code-side artifacts dated to the build's real day — e.g. `test_worker_contract.py::_ARMOR_SHAS`'s re-pin comments, `2026-08-28` — are correct as their OWN actual edit date, not a drift from this note's `2026-08-27`. The two dates cite two different real events (research vs. implementation); neither is a placeholder, and reconciling them to a single date would falsify one.

### 14.1 `03-decisions.md` — the S-52 row

> | S-52 | **Ancestor canon is INHERITED, read-side only; the already-canon scan reads whole canon files, not a marker window.** Measured 2026-08-27 on Claude Code `2.1.250`. **Instrument: the `InstructionsLoaded` hook** — a project-scope hook in a throwaway tree outside every registered host, appending each event's `{file_path, memory_type, load_reason}` to a file. It reports that Claude Code loads `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` from the cwd **and every ancestor directory**, each as one `load_reason: session_start` event (`memory_type` `Project`, or `Local` for `CLAUDE.local.md`), with `~/.claude/CLAUDE.md` arriving separately as `User`; **the git root is not a stop** (markers two levels above it fired). **Descendant** files load only on demand, as `load_reason: nested_traversal`, once their directory is read; **sibling** subtrees never load. That descendant/sibling result is a real negative, not instrument blindness: the **positive control** is a second run that reads a file inside the descendant directory and makes its `CLAUDE.md` fire with `nested_traversal`, while the sibling stays silent in both runs. **Two things were NOT measured and are doc-sourced only: the concatenation ORDER of the loaded files** (the hook's emission order differed between two runs) **and the walk's terminus** (`/` vs `$HOME`; the tree lived outside `$HOME` and every ancestor still loaded, so the walk is at least not `$HOME`-gated — and both live ancestor pairs are one level apart under `$HOME`, so no terminus can matter). `--debug`/`--debug-file` were tried first and expose **no** loaded-file list on this build; an earlier draft claimed the session transcript was the instrument, which is **false** — 2.1.250 does not write loaded instruction files into the transcript, and the marker tokens appear there exactly once each, in the assistant's own reply. This corroborates deferred record `lrn-b21d1969` (doc-sourced 2026-08-25) for everything but its ordering clause; its `--add-dir` clause remains untested. **Consequences, all read-side:** (1) a registered ancestor host's `CLAUDE.md` is canon that already loads for every child session, so `gates.g0.canon` may fire on it, and the analyst is handed it as a labelled *inherited* block; (2) `selfcheck._loaded_surface` gains the registered ancestors' `CLAUDE.md` as members for project scope — the "Model B remap" its own docstring anticipated; (3) ancestry is **derived** from `hosts.yaml` by resolved-path prefix arithmetic at read time, **never persisted** and never a bucket key (bucket identity stays `(scope, name)`); (4) an **unregistered** ancestor stays a fact told to the human (routing-doctrine §3) — its path is reported, its bytes are never read; (5) a host with a registered ancestor or descendant gets a base-naming sentence in its compiled pointer block, because all three live blocks are byte-identical today and two of them load in one session. **The already-canon scan is widened in the same unit and for the same reason:** `canon_excerpt` returned the marker window ±20 for files ≥200 lines, which is **11.5%** of the k1c host's `CLAUDE.md` (2,923 of 25,499 B); `lrn-bcf6b3e7` had 4 of its own 5 `t3.scan_terms` in that file and 0 of 5 in the excerpt, and the covering hand-written rule sat **188 lines above the excerpt window** (208 above the marker) — the human graduated it by hand. The analyst now reads the **whole** own-host file plus `<host>/references/**`, capped and byte-reported (BR-1/BR-3: 32 KB/file, 64 KB/record, depth 2), and **nothing outside `canon_read_roots`' project family** — the whole-host-tree read, priced at **43.3 MB / ~10.8 M tokens** across the 9 hosts, stays refused and user-ratifiable per G-3's 2026-07-17 note; `<host>/CLAUDE.local.md` also stays out, because it is git-excluded by design and not in `canon_read_roots`. **This row SUPERSEDES `u-marker-excerpt-case-spec.md` §3 criterion A's A3 leg ONLY** *(CORRECTED-r3, gate r2-N2: r2 said "criterion A", which reads as retiring A1/A2 — i.e. as dropping the requirement that the compiled section reach the analyst at all, the opposite of what this unit does)* — A3's exact-window equality (`excerpt == lines[begin-20:end+21]`) is obsolete once the whole file is read, while **A0 (the ≥200-line / begin-index>60 fixture guard), A1 (both markers present) and A2 (`entry_line(R)` present) are PRESERVED and re-asserted against the whole-file contract**. **Criterion B is re-homed, not retired**: under the byte cap the compiler-written managed region is always retained, and it is located by the imported markers **case-sensitively**, so a case-variant the compiler never wrote cannot capture the retained window. Four shipped tests in `cli/tests/test_worker.py` pin criterion A by exact list equality and are rewritten in the same commit; that file is armor (`test_worker_contract.py::_ARMOR_SHAS`) and its sha is re-pinned with this row as the reason. **A hand-written mention is not a rule:** a `g0.canon.target` outside a managed section requires the `already_kept` card section and the `canon-hand-written` flag, no verb auto-resolves on it, and a hit found only in a `references/` file may never set `already_canon` at all — references are the DEMAND shelf, reached by a pointer, not loaded. **Refused here, by name:** umbrella-as-destination (FW-125), any new verb or `--dest` grammar (U-verbs owns it), and widening the worker's title-overlap recurrence basis across the ancestor edge (FW-127). | Loading rule sourced from `code.claude.com/docs/en/memory.md` + `large-codebases.md` + `agent-sdk/claude-code-features.md` (stopping point and ancestor `.claude/CLAUDE.md` both **docs silent**), then measured with the `InstructionsLoaded` hook and a `nested_traversal` positive control. Census, retro-measure and budget figures in `drafts/u-ancestry-ancestor-canon-spec.md` §2–§3, all reproducible command outputs; instruments in that unit's `misc/u-ancestry-measurements/`. |

### 14.2 `routing-doctrine.md` — the amendment text

**Into §2, G0's `canon` leg**, after "…or the curated doc this record was
mined from":

> Canon "that already loads" is wider than the managed section you were
> handed, and it is **exactly two things**: **(1)** the **hand-written** parts
> of this project's own `CLAUDE.md` — you now receive the whole file, not a
> window around the managed block — and **(2)** the `CLAUDE.md` of a registered
> **ancestor host**, which loads in every session under it and is given to you
> as a block labelled *inherited*. Cite whichever one covers the lesson as
> `g0.canon.target` — `<absolute path>:<line>` — with a verbatim span from it
> as `g0.canon.evidence`.
>
> **A `references/` file is NOT on that list.** You are now shown this
> project's `references/` files too, each labelled *captured, NOT loaded —
> pointer-reached*. They are the DEMAND shelf: a session reaches them through a
> pointer, it does not load them. Finding the lesson there is a real and useful
> observation — write it in the `already_kept` card section, quote the span,
> name the file — but it is **never** a `g0.canon` `yes`, never
> `already_canon: true`, and never a reason to prefer `graduate` over the other
> resolutions. Say what is on the shelf and let the human decide whether a
> shelf entry is enough.
>
> **A mention is not a rule.** When the text you found merely names the same
> subject, or reads as out of date, say so: write the `already_kept` card
> section, quote the span, name the file and line, and state plainly whether it
> *instructs* or only *mentions*. Add flag `canon-hand-written`. You may still
> recommend `graduate` — the human decides, and "already written down" and
> "still true" are two different claims you must not merge.

**Into §3, after the ancestor-project clause's last sentence:**

> **Re-home and inheritance are different questions; do not answer one with
> the other.** A re-home says *the record belongs to the umbrella* — its
> trigger's surfaces live outside its own repo (the evidence you must name).
> Inheritance says *the lesson is already loaded there* — the **ancestor host's**
> `CLAUDE.md` already carries it, and every session under that umbrella already
> has it. Inheritance is a **G0.canon** answer, not a re-home; a lesson that is
> already inherited needs no move at all. And an ancestor host is only an
> ancestor when it is **registered**: an unregistered directory on the path is
> reported to you by path alone, never by content, and stays a fact you tell the
> human.

**Into §4 (repo conventions), as a new bullet after the user-scope bullet:**

> - **An ancestor host's `CLAUDE.md` is more expensive than the child's and
>   cheaper than `~/.claude/CLAUDE.md`.** It loads in every session under that
>   ancestor — every sibling project, not just this one — so the
>   narrowest-surface bias ranks child `CLAUDE.md` < **ancestor host** `CLAUDE.md`
>   < user `CLAUDE.md`. Prefer the child unless the lesson genuinely fires in
>   the siblings too, and when it does, say which siblings and why.

*(`DOC3` checks these three landings per section range, not by a whole-file
count — three hits in one section would satisfy a naive grep.)*

### 14.3 `14-forward-work-map.md` — the FW rows

> | FW-125 | **Umbrella-as-destination: route a child-bucket record's canon into a registered ANCESTOR host without moving the record.** Today the only host-changing knob is `rehome`, which moves the record's bucket; `route --dest` carries a destination *qualifier* (`reference:<file>`, `claude-md:rules:<topic>`, …) and cannot name a host, so **0 of 107 resolved records** ever crossed from a child bucket into an ancestor host. U-ancestry refused this deliberately: it needs a host axis on `verbs._resolve_target` (U-hostmode's surface), a `--dest` grammar or a verb (U-verbs' surface), and it forks the compile set — `verbs._compile_set` gathers a host's records **by bucket** (its project leg iterates `discover_buckets` and keeps only buckets whose recorded project path resolves to the host), so a foreign-bucket record in a host's managed section would be invisible to `recompile` and would drift on the next run (13 §4 item 2). Source: `drafts/u-ancestry-ancestor-canon-spec.md` §4.3. | WATCH | Trigger: a live case where a lesson genuinely fires in ≥2 sibling projects AND the human declines the re-home (the record's own repo is still the right home for its evidence). Whichever unit takes it must first rule on compile-set ownership — does the ancestor host's compile set gain a foreign-bucket member, or does a routed record grow a `routing.host` field the compilers key on? — because that ruling, not the grammar, is the hard half |
> | FW-126 | **The already-canon scan has no term source that exists before the analyst runs.** `gates.t3.scan_terms` are an OUTPUT of the gate procedure, so the cheap design for a wide hand-written scan — grep the terms over the host's docs, feed back only matching spans — cannot be built: there are no terms yet. U-ancestry therefore widened the *read* (whole `CLAUDE.md` + `references/**`, capped) instead of adding a *filter*, and priced the unfiltered alternative at **43.3 MB / ~10.8 M tokens** across the 9 registered hosts (de-duplicated; exclusion set stated in the spec's §3.4). A record-derived proxy exists (`worker._tokens`' tokenisation over `record_title` at a ≥6-char / first-12 cut, the recurrence detector's basis) and was used to retro-measure the corpus (11–12 of 58 project/user-scope resolved records, depending on that cut, have ≥50% of their tokens in a hand-written surface the analyst never read) — but promoting a Jaccard proxy to a canon-presence gate would let a threshold decide graduation. Source: `drafts/u-ancestry-ancestor-canon-spec.md` §5.3. | WATCH | Trigger: a term source that exists before the analyst does — e.g. the miner emitting candidate terms alongside a candidate, or a cheap pre-pass model whose only job is term extraction. Building it needs a ruling on what a term-match may and may not decide: U-ancestry's HW-1 pins that a hand-written hit never auto-resolves, and any filter design inherits that pin |
> | FW-127 | **Two ancestry-shaped gaps left open by U-ancestry, both measured.** (1) `worker._recurrence_suspects` compares a new pending record only against `entry.bucket_dir / "resolved"` — same bucket only — so a child-host capture restating an **ancestor-routed** lesson raises no suspect. The miner's crossover basis does not share this limit (`miner._canon_index` iterates every bucket), so the two suspect producers now disagree across the ancestor edge. Widening was refused because it changes the Jaccard base rate for every bucket at once, and FW-49 records that this basis was already narrowed once on measured evidence. (2) `compilers.surface_names_target` resolves a relative pointer token against `surface.parent` (*"the token is read as the AUTHOR meant it"*) while a live session resolves it against the session **cwd**; ancestry makes the two disagree by construction, and all three live self-learn pointer blocks are byte-identical (`sha256:9b8c6e64…`), so a k1c session sees two blocks saying "captured lessons for this project" about two different projects. U-ancestry closes only the ancestor/descendant case, and only by adding a base-naming sentence to the surrounding **prose** (the token is unchanged, so U-pointer's predicate and tests are untouched; an absolute token was refused because a `CLAUDE.md` is tracked and one host has a public remote). The general divergence — any two loaded surfaces at different depths, `--add-dir` surfaces, a future Model B remap — is unclosed. Source: `drafts/u-ancestry-ancestor-canon-spec.md` §3.6, §6.5. | WATCH | Trigger for (1): a confirmed recurrence whose earlier routing lives in an ancestor bucket. Trigger for (2): a third pointer-bearing surface in one session, or the first `--add-dir` host |

**And an edit to an existing row** *(added r2, gate B1)* — `FW-44`
(`✅ FIXED 2026-08-02`, the register row `u-marker-excerpt-case-spec.md` names in
its own header) gains a dated note:

> *(2026-08-27 — **superseded in part by S-52**: U-ancestry's `SCAN1` replaces
> the excerpt window with the whole file under a byte cap, so u-marker §3
> criterion **A3**'s exact-window equality no longer describes any code —
> **A0/A1/A2 survive** and are re-asserted against the whole-file contract.
> **Criterion B is re-homed, not retired** — it becomes `SCAN8`: over the byte
> cap the managed region is reserved first and located by the imported markers
> case-sensitively, so a case-variant the compiler never wrote cannot capture the
> retained window. §3.1's mutations follow their criteria: `M1`/`M2`/`M3`/`M5`
> are carried to `SCAN8` (as its `M35`/`M36`/`M37`/`M30`), `M4` is retired with
> A3. The marker-import rule this row fixed is unchanged and still binding, and
> `SCAN8` is now its only observable consequence.)*

### 14.4 `u-marker-excerpt-case-spec.md` — the supersession line

*(added r2, gate B1)* Into its status header, directly under the
`Status: **DRAFT r1**` line:

> **Superseded in part by S-52 (2026-08-27)** — `u-ancestry-ancestor-canon-spec.md`
> `SCAN1`/`SCAN8`.
>
> **§3 criterion A — only A3 is retired.** `worker.canon_blocks` reads the whole
> own-host `CLAUDE.md` under a byte cap, so **A3**'s exact
> `lines[begin-20:end+21]` equality has no window to assert. **A0, A1 and A2
> survive** and are re-asserted against the whole-file contract by S-52's
> `SCAN1`: A0 as the fixture guard that keeps the target *fat* (which `SCAN8`
> still needs), A1 as "both imported markers are present", A2 as
> "`compilers.entry_line(R)` is present — the payload, not the frame". Nothing
> here weakens the requirement that the compiled section reach the analyst; it
> strengthens it, from a window to the whole file.
>
> **§3 criterion B is re-homed** to `SCAN8`, guarding the **truncation path**
> instead of the branch selector: over the byte cap, the managed region is
> reserved first and located case-sensitively, so a case-variant the compiler
> never wrote cannot capture the retained window.
>
> **The §3.1 mutation table's disposition, one by one.** `M1` (legacy needle,
> begin only) and `M2` (end only) mapped to **A**; under whole-file reading A1
> is *vacuously* true — the file contains the markers whatever needle the code
> searches for — so both are **carried to `SCAN8`** as its `M35`/`M36`, where an
> unlocatable marker means an unreserved managed region. `M3` (case-folded short
> token) and `M5` (case-folding the imported constants) mapped to **B** and are
> carried as `SCAN8`'s `M37`/`M30`. `M4` (return the whole file instead of the
> window) is **retired with A3** — it is the new behaviour. So all five survive
> or are retired **deliberately**, none by omission.
>
> **§2's import rule — search the markers the compiler actually writes, never a
> hand-typed literal — is unchanged and still binding**, and `SCAN8` is now its
> only observable consequence.
>
> The four tests in `cli/tests/test_worker.py` that pinned A and B are rewritten
> by S-52's unit, which also re-pins that file's `_ARMOR_SHAS` entry.

---

## 15. Open questions for the user

Each carries this spec's recommendation. None blocks the code gate; **Q1 and
Q3 change the shape of the build and should be answered before it starts.**

**Q1 — How much of a host may the analyst read?** §5.2 adopts whole
`CLAUDE.md` + `<host>/references/**` — exactly `canon_read_roots`' project
family, no widening of the read posture. The measured miss (`lrn-bcf6b3e7`)
is fully recovered by that, because the covering rule was in the host's own
`CLAUDE.md`. The mandate's literal wording ("hand-written docs") would also
include `docs/known-issues.md`, which the retro-measure says would newly reach
**1 more record** — `tierB_but_not_wholeCM` = 1, unchanged at both N=24 (the
stated first-creation filter) and N=27 (the acted-on-proposal universe) — at a
price of up to 2,045,357 B per record.
**Recommendation: adopt §5.2 as specified; do not read `docs/`.**

**Q2 — May an emitted pointer name an absolute base? — RULED, folded in r2:
no.** Finding C-3 shows three byte-identical pointer blocks, and the cleanest
mechanical fix would be an absolute token (`surface_names_target` accepts
absolute tokens as-is), which resolves correctly from any cwd. It was **refused**
because a `CLAUDE.md` is a tracked file and `~/repos/claude-skills` has a public
remote (`git@github.com:…/claude-skills.git`; the two umbrella hosts have no
remote — measured), so an absolute token would commit a real home path into a
public repo. §6.4 therefore ships **prose-only**: the token is byte-unchanged and
the block gains one verbatim sentence naming its base, pinned by `ANC8`. Recorded
here as a decision, not a question.

**Q3 — The G-3 whole-root read widening (2026-07-17, "user-ratifiable and
unexercised").** This unit did not exercise it and does not propose to. If you
ever want the analyst to read a host tree, this is the row to ratify, and the
price is §3.4's 43.3 MB / ~10.8 M tokens. **Recommendation: leave unratified.**

**Q4 — Should `unregistered_ancestor_dirs` exist at all?** It reports paths
only, never bytes, and its whole purpose is to let the card say "there is a
`CLAUDE.md` at `~/repos/foo` that binds this session and is not registered".
It is one `is_file()` probe per directory on the path. The alternative is
silence, which is what happens today.
**Recommendation: keep it. It is the mechanised form of doctrine §3's "a fact
you tell the human", and it costs one line per hit.**

**Q5 — `lrn-b21d1969` is deferred to 2026-09-25.** Its fact is now
repro-tested (§2.2) and its consequence is being built. Leave it deferred,
undefer it so the loading rule itself gets routed to user canon, or graduate
it against S-52? **Recommendation: graduate against S-52 once this unit lands
— the rule will be recorded, tested, and consumed, which is what "already
canon" means; and its untested sibling/`--add-dir` half is worth re-capturing
as its own record rather than riding this one.**

**Q6 — `~/repos/keyboards/CLAUDE.md` says "**Not a git repo** -- each
subdirectory has its own git repo", and it now is one** (`host add --init`,
2026-08-24). That prose is stale hand-written canon inside a registered host,
and §5.2's widening will start feeding it to the analyst.
**Recommendation: not this unit's to fix — but worth a `teach` or a manual
edit before the widening ships, or the analyst will reason from a false
statement about a host it is routing into.**

---

### 15.1 One ruling folded with a corrected direction — flagged, not silently changed

The orchestrator's `B1` ruling asked for criterion B to be re-homed with the
mutation *"break case-insensitivity → the managed region falls outside the cap
on a fat fixture → RED"*. **`SCAN8` implements the substance of that ruling and
inverts its wording, deliberately**, because the wording as written would ship
the exact bug u-marker exists to prevent.

u-marker §3 criterion B requires that a **case-variant of the compiler's marker
does NOT match** — the compiler is the sole writer of a managed section and it
writes one exact spelling, so a case-*insensitive* search would treat a
hand-typed uppercase decoy as a managed region. u-marker's own mutation table
names case-folding as `M5`, *"the plausible 'defensive' fix"*, and criterion B
is the only thing that catches it. So the marker search must stay
**case-SENSITIVE**, and "break case-insensitivity" would be an instruction to
introduce the defect.

`SCAN8` therefore states: the managed region is located case-sensitively, and
its mutation is **`M30` — case-FOLD the marker match** (u-marker's M5 verbatim),
whose red cell is exactly the shape the ruling asked for: on a fat fixture
carrying an uppercase decoy pair early and the real compiler-written section
late, the decoy captures the retained window and the real managed region falls
outside the cap. Same fixture, same failure, opposite sign on the word. If the
orchestrator meant the literal wording, this needs an explicit reversal of
u-marker §3 B and §2's import rule, which is a decision row, not a spec fold.

---

### 15.2 One gate measurement corrected — flagged, not silently adopted

The r2 gate's finding **N4** asked for `SCAN8`'s residual scope to be stated and
supplied the number: *"exactly one of the ten surfaces qualifies — `~/.config` at
72,467 B."* **Re-measured against the same §3.3 byte column and
`CANON_BYTES_PER_FILE = 32768`, three surfaces are over the cap, not one:**

```
$ uv run --with pyyaml python - <<'PY'   # CAP = 32768, over §3.3's own byte column
surface                                           bytes  over32k markers
~/.config                                         72467    True   True
~/repos/nsys-marketplace                          39146    True   False
~/repos/nsys-marketplace-local                    39714    True   True
… (the other seven surfaces are under the cap)
OVER CAP (3): ['~/.config', '~/repos/nsys-marketplace', '~/repos/nsys-marketplace-local']
OVER CAP *and* marker-bearing (2): ['~/.config', '~/repos/nsys-marketplace-local']
PY
```

39,146 and 39,714 both exceed 32,768. §6.2 therefore states the corrected figure:
**three** surfaces are over the cap, and criterion B's re-homed guarantee — which
needs a managed region to locate — binds the **two** of them that carry markers.
`~/repos/nsys-marketplace` is over the cap with no managed section at all, so
clause (1) is empty there and it is head-and-tail fill only; that is a third,
distinct case r2's prose did not name either.

The direction of the finding is unaffected: the guarantee is still exercised on a
small live minority and by fixture everywhere else, which is exactly why `SCAN8`'s
fixture requirement (§9, §11 fixture 5) is load-bearing rather than incidental.

---

## 16. Revision history

| rev | date | change |
|---|---|---|
| r5 | 2026-08-28 | **Blind CODE gate r1 on the BUILD → NOT CLEAN narrowly (0 B / 2 M / 11 N / 4 D); text-only fold, no criterion/mutation/decision changed.** The two MAJORs (`M-1`: ANC8's emission path had no test exercising the real `_pointer_names_base`/`_apply_target` path; `M-2`: UN2 was a self-comparison, never catching a regression identical on both sides of the comparison) were fixed in the BUILD's own test file, not this spec — no spec-text change corresponds to them. Spec-text folds: **D1** SCAN1's Check cell now names the actual shipped fixture (`test_canon_blocks_whole_file_reaches_the_compiler_written_section`) instead of a never-built "k1c shape" reproduction, dated. **D2** CARD2's grep gains a stated `tests/`-directory exclusion, dated with the 18-hit measurement it corrects. **D4** §11 gains a declared-deletions paragraph for `ui/tests/test_pane.py`'s three pure deletions (replaced by the delegation test). **N7** a date-alignment note distinguishes this spec's own citation dates from the build's real implementation date. **N8/N11** additive-only: §13 gains `compilers.py`/`ledger_ops.py` rows for surfaces this unit's build actually touches. **N1, N5, D3** were BUILD-only fixes (a behavioural leg on SCAN7's test, LOAD5's distinct-sentence tightening, SCAN6's explicit `already_kept` assertion) with no spec-text counterpart. **N3/N4/N6/N9/N10** accepted as-is, not folded. |
| r4 | 2026-08-27 | **r4: three gate nits folded post-SOUND (no re-gate, repricing rule 2026-07-26).** Blind spec gate r3 returned SOUND (0 B / 0 M / 3 N / 0 D), ruled in this spec's favour on §15.2's over-cap count and replicated all five `SCAN8` mutations. **r3-N1**: `SCAN8`'s negative assertion was red on correct code — the decoy marker pair sat "inside the head fill", where a correct build retains it as ordinary fill. The decoy moves to **after the head-fill budget** and before the real section, so it is dropped under correct code and reserved under `M30`/`M37`; the negative leg becomes a second independent discriminator, and the full layout is written into both `SCAN8`'s Check cell and §11 fixture 5. **r3-N2**: the last stale `SCAN3` cross-reference (§5.2 item 1's read-scope citation) corrected to `SCAN4`. **r3-N3**: `BR-1` still carried the r2 wording "head-and-tail (the managed-marker window is always retained)" — the unpinned split r3 replaced — and now points at §6.2's three-clause ordered priority instead of restating a superseded form of it. No criterion or mutation added: 36 criteria, 37 mutations. |
| r3 | 2026-08-27 | **Blind spec gate r2 → NOT SOUND narrowly (0 B / 1 M / 11 N / 1 D); all folded in place.** **r2-M1** (the only MAJOR): `SCAN8`'s mutations were not discriminators, because §6.2's truncation kept "the marker window plus head-and-tail fill" with the split unpinned, and every live managed section sits in the last 3% of its file (k1c: 354/356 of 365) where tail fill retains it however the markers are matched. §6.2's retention is now **ordered and normative** — (1) the case-sensitively located managed region, reserved first and always retained; (2) head fill; (3) tail fill, budgets computed after the reservation — and `SCAN8`'s fixture now places the real section in the **middle**, outside both fills, with positive **and** negative assertions. `M30`/`M31` re-predicted against that fixture. **r2-N1** LOAD5's literal reconciled with S-52's "NOT measured" (case-insensitive check). **r2-N2** the supersession narrowed to **A3 only** in §14.1, §14.3 and §14.4 — A0/A1/A2 survive, as §11 already said. **r2-N3** u-marker §3.1's whole mutation table disposed one by one: `M1`/`M2`/`M3`/`M5` carried to `SCAN8` as `M35`/`M36`/`M37`/`M30`, `M4` retired with A3. **r2-N4** the residual scope stated — and the gate's own count corrected from one over-cap surface to **three** (two marker-bearing); see §15.2. **r2-N5** stale `SCAN3`→`SCAN4` at both sites. **r2-N6** §8 gains `CARD4`'s refusal row. **r2-N7** the UN group split into its ancestry half (7 hosts) and its pointer half (**5** — `3d-printing` and `keyboards` have registered descendants and DO get `ANC8`'s sentence). **r2-N8** §6.2 item 3 and `SCAN2` now state the references behaviour per scope (project / skill / **none** at user scope). **r2-N9** MEASURE-1's first-creation bias named, with the three regenerated-proposal records and the **N=27** universe reported beside N=24; both load-bearing cells identical. **r2-N10** the ordering withdrawal restated on the instrument's reach (emission order ≠ concatenation order); the variance is recorded as observed once by the author and not reproduced by the gate. **r2-N11** LOAD6 leg (c) names **both** `meta.yaml` writers (`ledger_ops.ensure_project_meta:325`, `hosts._dump_meta:537` called at `hosts.py:480`), verified by measurement. **r2-D1** both placeholder dates in §14.3/§14.4 replaced with the real one, 2026-08-27, and §14 gains a builder note forbidding a placeholder in text destined for a tracked file. Criteria unchanged at 36; mutations 34 → **37**. §15.2 records the one gate measurement corrected. |
| r2 | 2026-08-27 | **Blind spec gate r1 → NOT SOUND (2 B / 3 M / 18 N / 3 D); all folded in place.** **B1**: `SCAN1` explicitly supersedes `u-marker-excerpt-case-spec.md` §3 criterion A; criterion B re-homed as new `SCAN8` (case-sensitive marker location under the cap) with mutations `M30`/`M31`; §10.1's false census corrected — four shipped tests pin the excerpt by exact list equality and are rewritten in §11; `test_worker.py` identified as `_ARMOR_SHAS` armor and its re-pin prescribed with a justification; new `DOC5` + §14.3 FW-44 note + §14.4 supersession line. **B2**: the doctrine amendment's `references/` clause deleted (it would have routed a DEMAND-tier lesson to GRADUATE); references blocks now labelled *captured, NOT loaded*; new `SCAN3` + `CARD4`. **M1**: §2.2's transcript instrument was false — replaced by the `InstructionsLoaded` hook with a `nested_traversal` positive control; `--debug`/`--debug-file` measured to expose no loaded-file list; the concatenation-order claim withdrawn as doc-sourced. **M2**: new `ANC7` (ancestor members in `_loaded_surface`) and `ANC8` (verbatim pointer sentence) + `M24`/`M25`/`M26`. **M3**: new `LOAD6` (derived, never persisted) + `M27`. **N/D**: 18 buckets; 188 not 208 lines; criterion count re-derived to 36; excerpt cells 2,873 / 5,120; the 25.9 MB ceiling re-derived to 43.3 MB with its exclusion set written out; §3.5 re-measured at an equal-length ledger-home path and live-queue shas dropped; the missing `git log` line added; 21 `test_reach_*`; tier A relabelled and `CLAUDE.local.md` moved to §12 OUT with its reason; MEASURE-1's filter stated with its full drop census; §13 gains a U-verbs column and reconciles `ANC4` with U-hostmode; LOAD1/LOAD2/ANC3 fixture requirements named; `CARD2`'s grep widened to command prose; `M14` retargeted to a drivable site; `DOC3` bound per section range; `already_kept` distinguished from `conflict`; the symlink edge stated; the doctrine quote's added bold removed; `worker.py:1380-1382`; `_tokens`' `>2` filter named. §15.1 records the one ruling folded with a corrected direction. |
| r1 | 2026-08-27 | Authored. Loading rule sourced (§2.1) and measured (§2.2). Census at `50fa815` (§3), including three findings: C-1 (`canon_excerpt` has no registry gate), C-2 (the `lrn-bcf6b3e7` miss is an 11.5%-excerpt miss, not a `docs/` miss), C-3 (three byte-identical pointer blocks; author-relative vs cwd-relative resolution). Option maps and decisions (§4, §5). 24 criteria in 7 groups (§9), 23 mutations (§10), unmutated-test census over 172 existing tests (§10.1). Six questions routed to the user (§15). |
