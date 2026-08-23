# Spec — U-glob: a user-scope rules glob must be proved reachable, and co-firing must be measured, not counted

Status: **r2 — gate findings folded, back to the gate.** Blind spec gate
round 1 returned **NOT SOUND — 3 BLOCKER, 6 MAJOR, 8 NIT**; every finding
is folded in place, and §13 maps finding → change. The gate independently
reproduced all four defect citations of §2, measurements M5/M6/M7, and
re-implemented §4.3 verbatim — those sections are unchanged except where a
finding named them. Unit `U-glob` of the r2 routing campaign (TaskList #5).
Consumed by the blind Opus spec gate, then a Sonnet builder.

**Where prose and the acceptance criteria conflict, the criteria (§7, §9)
and the mutation plan (§11) win.** The prose is rationale; the criteria are
the contract.

**Citations.** Every `file:line` below was read against this worktree at
**`b316f1e`** and is written *anchor first, line second*
(`verbs.py::_resolve_rules_target`, currently `verbs.py:837`). Paths are
relative to `plugins/self-learn/cli/src/self_learn/` unless written out.

**Measurements.** Every number in §3 was produced on this host on
2026-08-23 by the commands named beside it. Nothing in §3 is inferred.

**Files this unit may touch.**

| File | Why |
|---|---|
| `cli/src/self_learn/ledger_ops.py` | the two new glob primitives (`glob_reaches`, `globs_may_intersect`) live beside the existing glob translation |
| `cli/src/self_learn/verbs.py` | `_validate_project_globs` → scope-general `_validate_rules_globs`; the user-scope skip at `verbs.py:925-930`; `surface_fill`'s topic-count trigger |
| `cli/src/self_learn/selfcheck.py` | the *same* user-scope skip on the drift side (`selfcheck.py:569-586`) |
| `cli/src/self_learn/cli.py` | `--allow-empty-glob` help text only (the flag itself does not change) |
| `cli/tests/` | the tests of §9 |
| `misc/u-glob-loader-check/` | the real-loader check harness and its recorded output (§8) |

Anything else is **reported, not edited**.

---

## 1. Objective

Three things, in one unit.

1. **Close the user-scope zero-match fail-open.** A user-scope
   `rules_paths` glob that matches nothing anywhere on the host is
   accepted today and routes silently. The rule file is written, the
   ledger records it as routed, and the rule can never fire. Project
   scope already refuses this; user scope explicitly skips the check.
2. **Decide the escape hatch's user-scope semantics.** `--allow-empty-glob`
   exists for project scope only. It must mean something exact at user
   scope, and the ledger must record *what* was bypassed.
3. **Replace the co-firing proxy.** `surface_fill` reports
   `rules_topic_count` — how many `*.md` files sit in the rules directory
   — and escalates `over_cap` when that count exceeds five. A count is not
   co-firing. The replacement datum is the set of topics whose globs can
   match the **same file**, which is what "these rules load together"
   actually means.

The governing ruling for this unit is **strict at the gate, light at the
file**: route time (the gate) refuses anything it cannot prove reachable;
the compiled rule file and the runtime gain no new machinery.

---

## 2. Current behavior — four defects, each verified

### 2.1 Defect 1 — user scope explicitly skips the zero-match check

`verbs.py::_resolve_rules_target` (currently `verbs.py:837`) validates
globs on the project leg and, on the user leg, says so in a comment.
Verbatim, `verbs.py:925-930`:

```python
            # E-17 preflight, same as plain user claude-md: chezmoi
            # drift/dirty aborts BEFORE the ledger commit. U-A2-glob-tree
            # (§5.1): no canonical tree exists for a user-scope glob, so
            # only the schema-shape check (already run at proposal
            # validation, §4.3(4)) applies — no zero-match assertion here.
            preflight_user_scope(target, chezmoi=chezmoi_bin)
        return TargetSpec(
            "claude-md", "user", bucket_dir, target, None,
            variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
        )
```

The user leg **returns** at `verbs.py:931` without ever calling
`_validate_project_globs`. The project leg, four lines later
(`verbs.py:937-939`), does:

```python
    bypassed = False
    if check_dirty and paths_tuple:
        bypassed = _validate_project_globs(host, paths_tuple, allow_empty_glob)
```

The stated reason — *"no canonical tree exists for a user-scope glob"* —
is true and is exactly what §4 rules on. It is a reason to pick a tree, not
a reason to skip the check.

The one shape check that *does* run on the user leg is
`verbs.py:866-884`: an absolute or `~`-leading pattern is refused for both
scopes. That is a syntax check. It cannot see a well-formed pattern that
matches nothing.

### 2.2 Defect 2 — the escape hatch is project-only and under-recorded

`verbs.py::_validate_project_globs` (currently `verbs.py:765`), body at
`verbs.py:785-800`:

```python
    dead = [
        pattern
        for pattern in patterns
        if not glob_mod.glob(pattern, root_dir=host, recursive=True)
    ]
    if not dead:
        return False
    if not allow_empty_glob:
        listed = ", ".join(repr(p) for p in dead)
        raise VerbError(
            f"rules_paths pattern(s) match nothing in {host}: {listed} — "
            "a rule with a non-matching pattern never fires; fix the "
            "pattern(s), or pass --allow-empty-glob to route unverified "
            "(the write-the-rule-before-the-files case)"
        )
    return True
```

The flag is declared at `cli.py:220-227` and its help text says
*"route a **project-scope** rules_paths glob that matches nothing"*. The
bypass is recorded at `ledger_ops.py:1854-1858` as
`routing["allow_empty_glob"] = True` — a bare boolean, with no record of
*which* condition it excused.

**A second, independent defect in the same three lines.** The matcher here
is `glob.glob(..., recursive=True)` with `include_hidden` left at its
default `False`. The project's *other* glob validator —
`ledger_ops.py::_glob_match`, `ledger_ops.py:758`, used by the analyst's
X1 proposal check at `ledger_ops.py:1045` — documents itself as

> *"measured equivalent to `glob.glob(pattern, root_dir=…, recursive=True,
> include_hidden=True)` over files (not directories) across 13 patterns, 0
> mismatches"*

The two validators therefore disagree about hidden paths. Measured on this
worktree (§3, row M6): `**/*.yml` at the repo root returns **0** matches
under `_validate_project_globs`'s matcher and **117** under `_glob_match`'s.
A project-scope rule with `rules_paths: ["**/*.yml"]` passes proposal
validation and is then refused at route time as dead. This unit removes the
*hidden-path* disagreement by moving both onto `include_hidden=True`.

A **symlinked-directory divergence remains**, declared rather than implied:
`_glob_match` is a pure string relation, so a pattern whose only match lies
under a symlinked directory still passes X1 and is refused by
`glob_reaches`, which never descends symlinks (§4.3 step 5). That is the
same limitation `glob.glob`'s `**` already has, so it is not a regression —
but it is not closed here either.

### 2.3 Defect 3 — `surface_fill` escalates on a topic count

`verbs.py::surface_fill` (currently `verbs.py:1674`), at
`verbs.py:1774-1784`:

```python
            count = (
                len(list(rules_dir.glob("*.md")))
                if rules_dir is not None and rules_dir.is_dir()
                else 0
            )
            entry["rules_topic_count"] = count
            if count > 5:
                # OR-ed with, never replacing, the per-file over_cap above
                # (§8 pin: both signals feed the SAME WARNING path).
                entry["over_cap"] = True
                entry["cap_reason"] = "rules-topics"
```

`count` is `len(rules_dir.glob("*.md"))` — every topic file, regardless of
whether any two of them can ever be loaded by the same session. The live
user rules directory on this host holds exactly two topics whose globs are
`**/.claude/hooks/*.sh` and `**/.claude/projects/**/*.jsonl`. Those two
**cannot** match a common file (measured, §3 row M7). Six such mutually
disjoint topics would trip `over_cap` today while no session could ever
load more than one of them.

`rules_topic_count` has no reader outside the CLI: the UI's `BudgetRow`
(`ui/src/self_learn_ui/models.py::BudgetRow`, currently `models.py:1543`; `models.py::_budget_rows`, currently `models.py:1754`) reads
`entries`, `entries_cap`, `words`, `words_cap`, `over_cap` and nothing
else. The only assertions on it are
`cli/tests/test_a2_rules_local.py:364-377` and
`cli/tests/test_surface_fill.py:259`.

### 2.4 Defect 4 — the *same* skip on the drift side (in scope)

`selfcheck.py:569-586` re-asserts recorded globs still match, and skips
user scope for the identical stated reason:

```python
            # A2 §5.2 item 3: for a PROJECT-scope pathed rule ONLY,
            # re-assert every recorded glob still matches ≥1 file — the
            # same drift class as a stale marker (files moved out from
            # under the pattern since routing), the same repair
            # (`recompile` surfaces it; the human retargets). User-scope
            # pathed globs are NOT re-asserted here (no canonical tree,
            # U-A2-glob-tree) — their presence-in-file check above still
            # ran.
            routing = record.routing or {}
            if routing.get("variant") == "rules" and record.scope == "project":
```

This is in scope because leaving it would ship an incoherent system: route
time would refuse a dead user glob while the drift audit stayed blind to a
user glob that *went* dead. It is the same predicate and the same new
primitive; the change is the `and record.scope == "project"` guard and the
matcher call.

---

## 3. Measurements

Every row was run on this host (`$HOME` = `/home/komi`) on 2026-08-23,
warm page cache, under `uv run --project plugins/self-learn/cli python`.
`$HOME` scale at the time of measurement: **676,026 directories,
4,575,239 files** (`os.walk`, 5.0 s).

| id | What was measured | Result |
|---|---|---|
| **M1** | `glob.glob("**/.claude/projects/**/*.jsonl", root_dir="/home/komi", recursive=True)` — i.e. `_validate_project_globs` naively pointed at `$HOME` | **TIMEOUT > 120 s** (also > 600 s in an earlier run) |
| **M2** | same call, `"**/.claude/hooks/*.sh"` | **TIMEOUT > 120 s** |
| **M3** | same call, `"**/nonexistent-xyzzy/*.md"` (a dead pattern) | **TIMEOUT > 120 s** |
| **M4** | the same three patterns rooted at each *registered* host (`~/.self-learn/hosts.yaml`: `claude-skills`, `keyboards`, `keyboards/zmk-config-offsetkey`, `.config`, `nsys-marketplace`) and at `~/.claude` | `**/.claude/projects/**/*.jsonl` → **0 matches** at `~/.claude` (0.21 s), at `repos/self-learn` (0.00 s), at `repos/nsys-marketplace` (0.00 s) |
| **M5** | the **anchored probe** of §4.3 rooted at `$HOME`, `include_hidden=True` | `**/.claude/projects/**/*.jsonl` → MATCH, **0.00 s**; `**/.claude/hooks/*.sh` → MATCH, **0.00 s**; `**/*.py` → MATCH, **0.02 s** (2,308 dirs scanned); `**/nonexistent-xyzzy/*.md` → NOMATCH, **2.61 s** (676,027 dirs); `**/*.xyzzyqq` → NOMATCH, **6.18 s**; `docs/specs/**/*.md` → NOMATCH, **0.00 s** |
| **M6** | `glob.glob("**/*.yml", root_dir="<this repo>", recursive=True)` with and without `include_hidden` | **0** vs **117** (the 117 are under the untracked `.playwright-mcp/`; the file set is incidental — the *disagreement between two in-tree validators* is the finding) |
| **M7** | the §5.2 intersection algorithm on 16 pattern pairs, both orders | **16/16 correct, symmetric.** In particular `**/.claude/hooks/*.sh` × `**/.claude/projects/**/*.jsonl` → **False** |
| **M8** | bounded-depth directory walk of `$HOME` | depth 3 → 66,312 dirs / 0.03 s; depth 4 → 115,706 / 0.22 s; depth 6 → 201,497 / 0.53 s; unbounded → 676,026 / **2.65 s** |
| **M9** | first file matching `**/.claude/projects/**/*.jsonl` returned by a *plain DFS walk* of `$HOME` | `.config/Claude/local-agent-mode-sessions/<uuid>/<uuid>/local_<uuid>/.claude/projects/<slug>/<uuid>.jsonl` — path depth 10. **A DFS-ordering artifact and nothing more:** the same rule also matches `~/.claude/projects/<slug>/<uuid>.jsonl` at depth 4, which the §4.3 probe reaches with 0 directories walked (M5). M9 does **not** show that a depth bound would refuse the live rule, and §4.2 no longer argues that it does. |
| **M10** | the same `$HOME` directory walk, first walk of a session vs immediate repeats (independently reproduced at the spec gate, 2026-08-23) | **17.95 s** cold; **3.74 s** / **3.69 s** warm |

Two readings drive §4:

* **M1–M3 kill the naive extension.** Pointing today's
  `_validate_project_globs` at `$HOME` is not "expensive"; it does not
  finish. Note M3: even the *dead* pattern — the case the check exists to
  catch — times out.
* **M4 kills the registered-hosts-only tree.** The one live pathed
  user rule on this host (`~/.claude/rules/session-transcripts.md`, glob
  `**/.claude/projects/**/*.jsonl`, carrying `lrn-2221cec9`) matches
  **nothing** in any registered host, and nothing rooted at `~/.claude`
  either. A registered-hosts tree would refuse the only real instance of
  the thing it validates.
* **M10 sets the budget.** A first-of-session walk of this `$HOME` costs
  **17.95 s**; immediate repeats cost 3.74 s and 3.69 s. Page-cache state,
  not tree size, dominates — so §4.3's budget is calibrated on the cold
  number, never the warm one.

---

## 4. DECISION A — the user-scope reachability tree (RULED)

### 4.1 The ruling

A user-scope `rules_paths` pattern is validated against a **root set**:

```
roots(user) = ($HOME,) + tuple(
    p for p in (registered project hosts + skills_root)
    if p is not $HOME and $HOME not in p.parents
)
```

de-duplicated, `$HOME` first, the remainder sorted. `$HOME` is derived from
the **already-overridable** user target — `user_claude_md.parent.parent`
(i.e. the parent of `~/.claude`) — not from `Path.home()`, so every
existing test that overrides `user_claude_md` also relocates the root set,
with no second override handle invented. The registered hosts come from
`hosts.load_hosts(home)`; a `HostsError` is **not** fatal here and yields
just `($HOME,)`.

Project scope keeps `roots(project) = (host,)`.

**No depth bound.** The tree is walked whole, or not at all.

The walk is the **anchored probe** of §4.3, never `glob.glob` against a
root.

### 4.2 Why — and why not the two alternatives the work order named

**Not `$HOME` with a depth bound.** One reason, measured: **a bound is not
needed.** M8 shows the *unbounded* directory-only walk of this `$HOME`
costs 2.65 s warm (M10: 17.95 s cold). The cost that made a bound look
necessary is `glob`'s `**` expansion (M1–M3), not the walk — remove that
and the bound has no work left to do. What remains is pure added failure
surface: every depth a bound excludes is a place a real match could sit,
and nothing is bought for it.

*Withdrawn from r1:* an earlier draft argued a second reason — that M9's
depth-10 path proves a depth-4 bound would have refused the live rule.
That was an inference presented as a measurement, and it is wrong: the
live rule **also** matches at depth 4 under `~/.claude/projects/`, which
the §4.3 probe reaches with 0 directories walked (M5). M9's depth-10 hit
is an artifact of plain-DFS ordering. The no-bound ruling stands on the
reason above alone.

**Not the registered hosts' trees.** M4: the live rule matches nothing in
any of them. The registered-host set exists to answer "where does a
*project* bucket compile", which is a different question from "where can a
session that loads a *user* rule be reading files". A user rule fires in
sessions rooted anywhere; `$HOME` is the honest superset of "anywhere this
user works", and the registered hosts are added only to cover a host that
lives *outside* `$HOME` (none on this machine — the addition is for
correctness elsewhere, and costs one `is_relative_to` test).

**Why not simply keep skipping.** The comment at `verbs.py:927` is right
that no tree is *canonical*. But the check does not need a canonical tree —
it needs a tree whose emptiness is decisive. If a pattern matches nothing
under `$HOME` *and* nothing under any registered host, the claim "this rule
can fire" has no support anywhere on the machine, and the honest response
is to refuse and offer the hatch. Approximation in the *conservative*
direction is what makes it a gate.

### 4.3 The anchored probe

`ledger_ops.glob_reaches(roots, pattern, *, budget_s) -> str`, returning
one of `"match"`, `"none"`, `"budget"`.

1. `segs = [s for s in pattern.split("/") if s]`.
2. Strip leading `"**"` segments; `floating = True` if any were stripped.
3. Pop leading segments that contain none of `*`, `?`, `[` and are not
   `"**"` into `literal` (a list of literal directory names, possibly
   empty). `rem = "/".join(remaining segs)`.
4. `_first_hit(base, rem)` is `base.exists()` when `rem == ""`, else
   `next(iter(glob.iglob(rem, root_dir=base, recursive=True,
   include_hidden=True)), None) is not None`, with `OSError` caught and
   read as no hit. **`include_hidden=True` is mandatory** — it is what
   `_glob_match` is measured equivalent to (§2.2).
5. For each root `r`, in order:
   * If **not** `floating`: `base = r / *literal`; if `base` does not
     exist, this root contributes nothing; else return `"match"` on
     `_first_hit(base, rem)`.
   * If `floating`: first try the zero-directory expansion —
     `base = r / *literal` (or `r` when `literal` is empty) — and return
     `"match"` on a hit. Then walk directories under `r` with
     `os.scandir`, testing `entry.is_dir(follow_symlinks=False)` so
     symlinked directories are never descended (no cycles). At each
     directory entry whose name equals `literal[0]`, form
     `cand = entry.path / *literal[1:]`; if `cand.is_dir()` (or `literal`
     has a single part), return `"match"` on `_first_hit(cand, rem)`.
     When `literal` is empty, test `_first_hit(d, rem)` at every visited
     directory `d` instead.
   * Check the wall clock once per visited directory; on exceeding
     `budget_s`, return `"budget"` immediately.
6. All roots exhausted with no hit → `"none"`.

`budget_s` defaults to **30.0** seconds per pattern, overridable by the
environment variable `SELF_LEARN_GLOB_PROBE_BUDGET_S` (a float; an
unparseable value falls back to the default without raising).

**Calibrated on the cold number, not the warm one.** M5's worst warm case
is 6.18 s, which made 10 s look like comfortable headroom — but M10
measures the same `$HOME` walk at **17.95 s on the first walk of a
session**, 1.8× *over* a 10 s budget. A budget set on warm numbers turns an
ordinary cold cache into a routine refusal and — through the hatch — into
routing blocks that assert "matches nothing" about rules that in fact
match. 30 s is ~1.7× the cold measurement. It is also why §6.6 must not
treat a budget bypass as a permanent exemption.

**Budget exhaustion is a refusal, not a pass** (§7.2). A probe that cannot
finish has not proved reachability, and the whole point of this unit is
that "could not tell" must never read as "fine".

---

## 5. DECISION B — the co-firing set (RULED)

### 5.1 The ruling

Co-firing is **a property of the patterns, decided symbolically, with no
filesystem access**. Two topics co-fire iff some pattern of one and some
pattern of the other can match a common path.

Rejected: a witness-based definition (scan the tree, find a real file both
match). It is the wrong shape for this question. The common answer is
"these two never co-fire" (M7: the two live topics do not), and a witness
search can never *prove* a negative cheaply — it must exhaust the tree
every time the answer is no, which is almost always. A symbolic decision is
exact, costs no I/O, is deterministic on fixtures, and stays true for files
that do not exist yet — which is right, because a rule pair that will
collide next week is already a fact about the rule set.

### 5.2 The intersection algorithm

`ledger_ops.globs_may_intersect(a: str, b: str) -> bool`. Two memoized
recursions.

**Segment level** — `_segment_may_intersect(a, b)` over two single-segment
patterns (no `/`), positions `i`, `j`:

* `i == len(a) and j == len(b)` → `True`.
* `i < len(a) and a[i] == "*"` → `go(i+1, j) or (j < len(b) and go(i, j+1))`.
* `j < len(b) and b[j] == "*"` → `go(i, j+1) or (i < len(a) and go(i+1, j))`.
* `i == len(a) or j == len(b)` (reached only when neither side sits on a
  `*`) → `False`.
* Otherwise read one token from each side — a literal char, `?`, or a
  bracket class — and advance both iff the two tokens *may* share a
  character. `_tokens_may_share` returns `a == b` for literal-vs-literal
  and **`True` for every case involving `?` or a class.**

**The bounds guards are part of the contract, not style.** Each `*` bullet
carries its own `i < len(a)` / `j < len(b)` test because the bullets are
evaluated in order: written as a bare `a[i] == "*"`, the rule raises
`IndexError` whenever one side is exhausted and the other is not — which is
most real pairs, not an edge case.

**Class extent is scanned exactly as `_translate_glob_segment` does**
(`ledger_ops.py:634-651`): skip a leading `!`, then skip a leading `]`,
then scan to the next `]`. An **unbalanced** `[` degrades to a literal `[`
(`ledger_ops.py:612`), never an exception. Verified against the shipped
translator: `[]abc]d` → class `[]abc]` + literal `d`; `[!]a]b` → `[^]a]` +
`b`; `[unclosed*` → literal `[` + `unclosed` + `*`. A builder who ends the
class at `seg.index("]")` misaligns every later token and can return
`False` — the one direction §5.2 calls a guarantee.

**Path level** — `globs_may_intersect(a, b)` over the two `/`-split
segment lists, positions `i`, `j`:

* `i == len(A) and j == len(B)` → `True`.
* `i < len(A) and A[i] == "**"` → `go(i+1, j) or (j < len(B) and go(i, j+1))`.
* `j < len(B) and B[j] == "**"` → `go(i, j+1) or (i < len(A) and go(i+1, j))`.
* `i == len(A) or j == len(B)` (reached only when neither side sits on a
  `**`) → `False`.
* Otherwise `_segment_may_intersect(A[i], B[j]) and go(i+1, j+1)`.

Same bounds-guard rule as the segment level, for the same reason.

**Directional soundness, stated because it is load-bearing.** The relation
**over-approximates**: `False` is a guarantee that no path can match both;
`True` means "may co-fire". The over-approximating steps are **two**:

1. `_tokens_may_share` returns `True` whenever a `?` or a bracket class is
   involved on either side.
2. A **trailing `**`** may consume zero segments, so the DP answers `True`
   for pairs the shipped matcher would not agree on. Verified:
   `_compile_glob_pattern("a/**").match("a")` is `None` (a final `**`
   compiles to `.*` with a `/` prepended), while the path-level DP returns
   `True` for `a/**` × `a`.

Both lean the same way, and that direction is deliberate — a report that
hides a real collision is worse than one that names a possible one.

**Verified.** M7: 16 pairs, both orders, 16/16 correct and symmetric,
including the two live topics (`False`) and the shape family that motivates
the whole datum (`**/*.py` × `**/test_*` → `True`, `*.sh` × `*.jsonl` →
`False`). §9 T7 re-runs exactly these as a unit test.

### 5.3 The datum `surface_fill` emits

The `claude-md` entry keeps `rules_topic_count` as a **raw datum with no
trigger attached** (it is cheap, it is already asserted by two tests, and
"how many topic files exist" is still worth reporting) and gains:

```python
entry["rules_cofire"] = {
    "topics":   [...],   # sorted topic stems that carry a paths: key
    "unpathed": [...],   # sorted topic stems with NO paths: key
    "pairs":    [[a, b], ...],   # sorted, a < b, pathed topics only
    "max_fanin": <int>,
}
```

* Topic stem = the `.md` filename stem in the resolved rules directory
  (`_user_rules_dir(target)` / `_project_rules_dir(spec.host_repo)`, the
  existing derivation at `verbs.py:1768-1773`, unchanged).
* Patterns come from `compilers.read_paths_frontmatter(text)`
  (`compilers.py:591`); membership of `unpathed` is decided by
  `compilers.has_paths_key(text)` returning `False` (`compilers.py:613`) —
  the *raw-key* predicate, not the reader, because the reader normalizes
  `paths: []`, `paths: null` and a scalar all down to the same empty tuple
  as "no key at all", and this datum must tell those apart.
* `pairs` contains `[a, b]` iff `any(globs_may_intersect(p, q) for p in
  patterns[a] for q in patterns[b])`.
* An **unreadable or undecodable** topic file is skipped, and its stem is
  in neither list — the same degradation discipline `surface_fill` already
  applies (`verbs.py:1735-1750`).
* `max_fanin = len(unpathed) + max over pathed topics t of
  (1 + |{u : [min(t,u), max(t,u)] in pairs}|)`, or `len(unpathed)` when
  there are no pathed topics.

**What `max_fanin` is, in plain terms:** the largest number of rule topics
that one file Read could pull into a session. **What it is not:** a
guarantee that some single real file matches all of them. Pairwise
intersection does not compose — three globs can pair up without sharing a
common path. It is an **upper bound**, and the spec says so rather than
letting a later reader assume otherwise.

The `len(unpathed)` term encodes "a rule with no `paths:` key loads in
every session, so it is present alongside whatever else fires". That
premise is **measured, not assumed** — §8 leg 3. If leg 3 disconfirms it,
the builder drops the `len(unpathed)` term, keeps the `unpathed` list as
reported data, records the measurement, and reports the change (§12 Q2).

### 5.4 The `cap_reason` replacement

`cap_reason = "rules-topics"` (triggered by `count > 5`) becomes
`cap_reason = "rules-cofire"`, triggered by `max_fanin > 5`. The **same
numeric threshold on the new quantity** — a like-for-like swap. Re-deriving
the threshold is TaskList #1's job; this unit hands #1 the data (`pairs`,
`unpathed`, `max_fanin`) and changes nothing about how the trigger feeds
the WARNING path. The `over_cap` OR-ing at `verbs.py:1781-1783` is
preserved verbatim in behaviour: the per-file cap still wins its own way in,
and the co-firing signal only ever sets `over_cap` True, never False.

---

## 6. The change, file by file

### 6.1 `ledger_ops.py` — two new primitives

Added beside the existing glob machinery (`_translate_glob_segment`
`ledger_ops.py:612`, `_compile_glob_pattern` `ledger_ops.py:741`,
`_glob_match` `ledger_ops.py:758`), which is where glob *semantics* already
live in this codebase. `ledger_ops` imports neither `compilers` nor
`verbs`, so no cycle is created; `verbs.py` already imports from it
(`verbs.py:113`) and so does `selfcheck.py` (`selfcheck.py:89`).

1. `glob_reaches(roots, pattern, *, budget_s=None) -> str` — §4.3.
   Exported. `budget_s=None` reads `SELF_LEARN_GLOB_PROBE_BUDGET_S`, else
   `30.0`.
2. `globs_may_intersect(a, b) -> bool` — §5.2. Exported, with the
   private `_segment_may_intersect` beside it.
3. `GLOB_PROBE_BUDGET_ENV = "SELF_LEARN_GLOB_PROBE_BUDGET_S"` and
   `DEFAULT_GLOB_PROBE_BUDGET_S = 30.0` as module constants, so tests set
   the budget through the documented handle rather than a literal.

### 6.2 `verbs.py` — `_validate_project_globs` becomes scope-general

`_validate_project_globs(host, patterns, allow_empty_glob)`
(`verbs.py:765`) becomes

```python
def _validate_rules_globs(
    roots: tuple[Path, ...], patterns: tuple[str, ...], allow_empty_glob: bool
) -> str | None:
```

returning `None` when every pattern reached, `"zero-match"` or `"budget"`
when at least one did not **and** `allow_empty_glob` was passed, and
raising `VerbError` (§7) otherwise. The per-pattern verdict comes from
`glob_reaches(roots, pattern)`; the dead list is built per pattern, exactly
as today (`verbs.py:785-789`) — a rule-level "did any pattern match?" would
pass a partial failure, which the existing docstring already forbids.

When both failure kinds are present in one call, the returned reason is
`"zero-match"` (the more actionable of the two) and **both** lists appear
in the refusal text (§7.3).

### 6.3 `verbs.py` — the user leg validates

At `verbs.py:925-930`, the comment is replaced and the call added, on the
same `check_dirty` guard the project leg uses and **before**
`preflight_user_scope` (so a dead glob is refused before any chezmoi
preflight side effect, and long before the ledger commit):

```python
        bypassed = None
        if check_dirty and paths_tuple:
            bypassed = _validate_rules_globs(
                _user_reachability_roots(home, base), paths_tuple, allow_empty_glob
            )
        if check_dirty:
            ...                      # the chezmoi-managed refusal, unchanged
            preflight_user_scope(target, chezmoi=chezmoi_bin)
        return TargetSpec(
            "claude-md", "user", bucket_dir, target, None,
            variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
            glob_bypass=bool(bypassed), glob_bypass_reason=bypassed,
        )
```

`_user_reachability_roots(home, user_claude_md_target)` implements §4.1:
`(user_claude_md_target.parent.parent,)` plus registered hosts and
`skills_root` from `load_hosts(home)` that are not `$HOME` and not under
it, de-duplicated, `$HOME` first, remainder sorted. `HostsError` is caught
and yields `(user_claude_md_target.parent.parent,)`.

**Read that parameter name exactly.** The argument passed at the call site
is `base` — the user *`CLAUDE.md`* target — whose `.parent.parent` is
`$HOME`. It is **not** the `target` local in the snippet above, which is
the rules file `~/.claude/rules/<topic>.md` and whose `.parent.parent` is
`~/.claude` (`_user_rules_dir` is `user_claude_md_target.parent / "rules"`,
`verbs.py:753-757`). The wrong reading is exactly the root M4 measured and
ruled out: rooted at `~/.claude`, the only live pathed user rule on this
host matches nothing and would be refused.

The chezmoi-managed refusal at `verbs.py:912-924` is **not** reordered
relative to the glob check by accident: the glob check must come **first**,
because it is the cheaper and more common refusal and because a
chezmoi-managed target with a dead glob should name the dead glob (the
thing the human can actually fix) rather than the management state.

The project leg's call site (`verbs.py:937-939`) changes only to
`_validate_rules_globs((host,), paths_tuple, allow_empty_glob)` and to
thread `glob_bypass_reason`.

### 6.4 `verbs.py` — `TargetSpec` gains one field

`TargetSpec` (`verbs.py:675-678`) keeps `glob_bypass: bool = False` and
gains `glob_bypass_reason: str | None = None` (`"zero-match"` |
`"budget"` | `None`). `glob_bypass` stays for byte-compatibility with
existing readers; `glob_bypass_reason` is what the ledger records.

### 6.5 `ledger_ops.py` — the routing block records *what* was bypassed

At `ledger_ops.py:1852-1858`, `routing["allow_empty_glob"] = True` is kept
verbatim (existing readers, existing tests at
`cli/tests/test_a2_rules_local.py:247,277,1180`) and joined by
`routing["glob_bypass_reason"] = <reason>` when the caller supplies one.
`ledger_ops::resolve_record` (currently `ledger_ops.py:1762`) gains `glob_bypass_reason: str | None = None`
alongside the existing `allow_empty_glob: bool = False`
(`ledger_ops.py:1778-1779`).

A bare boolean cannot distinguish "I know it matches nothing and I am
writing the rule first" from "the machine could not tell in thirty
seconds". Those are different states of knowledge, and §6.6 now *acts* on
the difference — so the difference has to be on disk, not inferred.

**`allow_empty_glob: true` is kept on both branches for compatibility, but
it is no longer the field anything reasons from.** `glob_bypass_reason` is.
Two facts make that necessary rather than tidy: a `"budget"` bypass writes
a routing block that asserts "matches nothing" about a rule that may well
match, and (§6.6) it must not silence the drift audit for that record
forever. A reader keying on `allow_empty_glob` alone cannot tell those two
records apart and will get both wrong.

### 6.6 `selfcheck.py` — the drift audit stops skipping user scope

`selfcheck.py:578` loses `and record.scope == "project"`. The root set is
`(bucket_project_path(bucket.path),)` for a project record and, for a user
record, `_user_reachability_roots(home, DEFAULT_USER_CLAUDE_MD.expanduser())`.
The matcher becomes `glob_reaches(roots, p) != "match"`, replacing
`not glob_mod.glob(p, root_dir=host, recursive=True)`
(`selfcheck.py:582-586`).

**`selfcheck` has no `user_claude_md` parameter, and this unit does not add
one.** It hardcodes `DEFAULT_USER_CLAUDE_MD.expanduser()` (imported at
`selfcheck.py:98`, used at `selfcheck.py:246,252,322`), and §4.1 forbids
inventing a second override handle. The consequence is a **test**
obligation, not a code one: the existing precedent
`monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)` — used
for exactly this reason at `cli/tests/test_a2_rules_local.py:434-439` — is
mandatory on every selfcheck-path test (T10). Unpinned, such a test walks
~688k real directories per run.

**One deliberate asymmetry.** In `selfcheck`, a `"budget"` verdict is
**not** a failure — it is skipped silently. `selfcheck` is an audit that
runs over every routed record, not the gate; turning a slow probe into an
audit failure would make the audit's result depend on machine load. The
gate is where "could not tell" must refuse (§4.3), and the gate is route
time. This is the "strict at the gate, light at the file" ruling applied
literally: only `"none"` — a positive determination of unreachability — is
reported as drift.

**The drift exemption is keyed on the *reason*, never on the boolean.** A
record is exempt from the staleness assertion iff its routing block has

* `glob_bypass_reason == "zero-match"`, or
* `allow_empty_glob: true` **and no `glob_bypass_reason` key at all**
  (a legacy record written before this unit; nothing else can be inferred
  about it).

A record carrying `glob_bypass_reason == "budget"` is **not** exempt: it is
re-probed on every audit like any other, and reported if the probe now
returns `"none"`.

This is the finding that makes §6.5's extra field load-bearing rather than
decorative. A budget bypass records a *timeout*, not a fact about the
tree — M10 measures the same `$HOME` walk at 17.95 s cold against 3.7 s
warm, so a single cold-cache run can produce one. Exempting it forever
would let a transient slow probe permanently disable drift detection for
that record: the "silently accept" direction this whole unit exists to
close, re-entering through the escape hatch. The re-probe is cheap in
exactly the case that matters — once the cache is warm, the same walk that
timed out costs seconds.

The `"zero-match"` exemption *is* new for project scope too, and is a
behaviour change — called out here rather than smuggled in.

### 6.7 `verbs.py` — `surface_fill`

`verbs.py:1774-1784` is replaced per §5.3/§5.4. The rules-directory
derivation at `verbs.py:1768-1773` is untouched. All per-topic file reads
sit inside the same `try` as the rest of the probe, or are individually
guarded, so one unreadable topic file never removes the `claude-md` key.

The computation is memoized per resolved rules directory in the same
`cache` dict `surface_fill` already threads (`verbs.py:1718-1719`), under a
key that cannot collide with a target path — e.g. `("cofire", rules_dir
.resolve())`. Without this, `list --json` recomputes the whole co-firing
graph once per record.

### 6.8 `cli.py` — help text only

The current string, verbatim from `cli.py:224-226` — the `A2 §5.1:` prefix
is part of it, and a literal-match edit that drops the prefix will not
anchor:

```
"A2 §5.1: route a project-scope rules_paths glob "
"that matches nothing in the tree anyway (write-the-rule-before-the-"
"files); the bypass is recorded in the routing block"
```

**The `A2 §5.1:` prefix is kept** — spec-section prefixes are the
convention throughout `cli.py` help text and this unit does not change it.
The rest becomes:

```
"A2 §5.1 / U-glob: route a rules_paths glob (either scope) that "
"matches nothing, or that the reachability probe could not decide "
"within its budget; the bypass and its reason are recorded in the "
"routing block"
```

The flag name, `dest`, and `action` do not change.

---

## 7. Validation and the exact refusal text

### 7.1 When the check runs

| Scope | Trigger | Roots |
|---|---|---|
| user | `check_dirty` **and** `rules_paths` non-empty | §4.1 |
| project | `check_dirty` **and** `rules_paths` non-empty | `(host,)` |

Unchanged from today's project leg: `check_dirty=False` (the read-only
`surface_fill` / `list` path) **never** probes. A read-only probe must not
walk `$HOME` once per record.

### 7.2 The verdict table

| `glob_reaches` | `--allow-empty-glob` absent | `--allow-empty-glob` present |
|---|---|---|
| `"match"` | route | route |
| `"none"` | **refuse** (§7.3) | route; `allow_empty_glob: true`, `glob_bypass_reason: "zero-match"` |
| `"budget"` | **refuse** (§7.4) | route; `allow_empty_glob: true`, `glob_bypass_reason: "budget"` |

### 7.3 Exact refusal text — zero match

Raised as `VerbError`, one message naming every dead pattern:

```
rules_paths pattern(s) match nothing under {roots}: {listed} — a rule with a non-matching pattern never fires; fix the pattern(s), or pass --allow-empty-glob to route unverified (the write-the-rule-before-the-files case)
```

* `{roots}` = `", ".join(str(r) for r in roots)`.
* `{listed}` = `", ".join(repr(p) for p in dead)` — `repr`, per today's
  `verbs.py:793`, so an empty or whitespace pattern is visible.

This is today's project-scope wording (`verbs.py:795-798`) with `in {host}`
widened to `under {roots}`. No existing test asserts the string: the only
occurrence of `match nothing` under `cli/tests/` or `ui/tests/` is prose in
a docstring (`ui/tests/test_routes.py:4158`), never an assertion. The
widening is therefore safe.

### 7.4 Exact refusal text — budget exhausted

```
rules_paths pattern(s) could not be checked within the {budget}s reachability budget under {roots}: {listed} — self-learn refuses rather than route a glob it could not verify; anchor the pattern with a literal directory segment (e.g. '**/<dir>/...'), raise SELF_LEARN_GLOB_PROBE_BUDGET_S, or pass --allow-empty-glob to route unverified
```

* `{budget}` is formatted with `:g` so `30.0` renders `30`.

The "anchor the pattern" advice is not decoration: M5 shows an anchored
pattern resolves in 0.00 s where an unanchored dead one costs 6.18 s. It is
the fix that actually works.

### 7.5 Mixed failures

Both kinds in one call → **refuse**, with §7.3's sentence for the dead
patterns and §7.4's for the undecided ones, joined by `" ... and "`. Both
lists appear; neither is swallowed. When the caller *did* pass
`--allow-empty-glob`, the recorded `glob_bypass_reason` is `"zero-match"`
(§6.2) — the more actionable and, per §6.6, the *less* forgiving of the two
exemptions, so a mixed record is never quietly exempted on its budget half.

Verified by **T13** and mutation **M-15**. A contract pinned in two binding
sections and checked by nothing is how the last three defects in §2 got
shipped.

---

## 8. Real-loader check — MANDATORY, and the builder RUNS it

Everything in §1–§7 rests on one premise: **that Claude Code actually loads
`~/.claude/rules/<topic>.md` into a session when that session Reads a file
matching the topic's `paths:` glob.** Nothing in this repository proves
that. If it is false, this unit is elaborate machinery guarding a rule that
never fires, and the right action is to stop, not to ship.

So the builder **runs** the check below and **records the literal output**
— every command's stdout/stderr verbatim, not a summary — into
`misc/u-glob-loader-check/RESULTS.md`, and cites it in the build report.
A build report that describes this check without literal recorded output
is a failed build.

`misc/` is deliberate: it is git-ignored but durable, and this measurement
is the only evidence the premise was ever tested. It does not go in `/tmp`.

### 8.0 One leg, one shell invocation — binding on all three legs

**Each leg below MUST be a single Bash tool call** that writes its fixtures,
runs its session(s), greps, and verifies cleanup — in that one call.

Each Bash tool call is its own `bash -c`, and an `EXIT` trap fires when
*that* call ends. A builder that writes the probe rule in one call and runs
the arms in another gets one of two failures, both silent: the trap fires
at the end of the writing call and the rule is gone before the session
runs (measuring nothing, reading as FAIL), or no trap was installed and the
file is left behind in the user's live configuration. "The builder verifies
the file is gone afterwards" is not a guarantee when the guarding shell has
already exited.

Two consequences, both mandatory:

* **Stale-file assertion at the start of every leg.** Before writing
  anything, `test ! -e ~/.claude/rules/selflearn-loader-probe.md` — abort
  the leg if it exists, and report it. A leftover from a previous run makes
  every arm of the current one meaningless.
* **`trap` is belt, not braces.** `SIGKILL` bypasses `EXIT` traps entirely,
  and this is the only mutation of the user's live configuration in the
  whole unit. The start-of-run assertion is what catches the case the trap
  could not.

### 8.1 Environment facts already established

* `claude` is at `/home/komi/.local/bin/claude`, version **2.1.241**
  (`claude --version`, 2026-08-23).
* Relevant flags exist and were read from `claude --help` on 2026-08-23:
  `-p/--print`, `--output-format {text,json,stream-json}`,
  `--session-id <uuid>`, `--allowedTools`, `--disallowedTools`,
  `--permission-mode`, `--add-dir`, `--model`, `--no-session-persistence`.
  There is **no** `--config-dir` flag.
* The live pathed user rules on this host are
  `~/.claude/rules/hooks.md` (`paths: ["**/.claude/hooks/*.sh"]`, carrying
  `lrn-899d4893`) and `~/.claude/rules/session-transcripts.md`
  (`paths: ["**/.claude/projects/**/*.jsonl"]`, carrying `lrn-2221cec9`).
  Both use the leading `**/` idiom.

### 8.2 Leg 1 — the live rule, no mutation

Purpose: does the shipped, unmodified `session-transcripts.md` enter a
session's context when that session Reads a matching file?

1. Pick a real transcript: `TARGET=$(ls -S ~/.claude/projects/*/*.jsonl |
   head -1)`. Assert it is non-empty and print its path and size.
2. Generate `SID=$(uuidgen)`.
3. Run, from a scratch directory:
   ```sh
   claude -p --session-id "$SID" --model sonnet \
     --allowedTools Read --disallowedTools 'Bash' 'Grep' 'Glob' \
     --add-dir "$HOME/.claude/projects" \
     "Use the Read tool once on $TARGET with limit 5. Then reply with exactly: DONE"
   ```
4. Locate the transcript: `find ~/.claude/projects -name "$SID.jsonl"`.
   Search **all** project directories, not the one matching the cwd —
   `lrn-2221cec9`, the very lesson under test, says a session's transcript
   can be filed under a directory other than its origin.
5. **Leg-1 instrument positive control (P4b), run BEFORE the transcript is
   grepped.** The probe substring is

   ```
   the session's cwd migrates mid-life
   ```

   and `grep -c "the session's cwd migrates mid-life" ~/.claude/rules/session-transcripts.md`
   must print **≥ 1**. If it prints `0`, the substring is wrong and the leg
   is INVALID — the string is fixed, not the verdict.
6. Only then, grep the transcript for that same substring.

**Why this control exists, with the near-miss recorded.** r1 of this spec
specified the substring as `a session's cwd migrates mid-life`. Measured:
`grep -c "a session's cwd migrates mid-life" ~/.claude/rules/session-transcripts.md`
prints `0`, `rc=1` — the live rule (line 7) reads *"…but if **the**
session's cwd migrates mid-life…"*. A wrong substring makes Leg 1 return
zero matches, and zero is byte-identical to "the rule did not load": the
exact fail-open shape §8.5 was written to prevent, sitting inside §8
itself. §8.5's P4 is a positive control for the *canary* grep only and
would not have caught it.

### 8.3 Leg 2 — a canary rule, with a negative control

Leg 1 alone cannot separate "the rule was injected because the glob
matched" from "the rule was injected regardless". Leg 2 does.

1. `CANARY="SELFLEARN-LOADER-CANARY-$(uuidgen)"`.
2. Write `~/.claude/rules/selflearn-loader-probe.md`:
   ```
   ---
   paths:
     - "**/selflearn-loader-canary/*.txt"
   ---

   <!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->
   - Probe rule for the U-glob real-loader check. Canary: SELFLEARN-LOADER-CANARY-<uuid>
   <!-- self-learn:end -->
   ```
   Ordering inside the leg's **single** shell invocation (§8.0), and this
   ordering is normative:

   ```sh
   test ! -e ~/.claude/rules/selflearn-loader-probe.md || { echo "STALE PROBE FILE — abort"; exit 2; }
   trap 'rm -f ~/.claude/rules/selflearn-loader-probe.md' EXIT INT TERM
   # ...write the rule, run both arms, grep both transcripts...
   ```

   The stale-file test comes **first**, the trap **second**, the write
   **third**. This is the only mutation of the user's live configuration
   this unit performs; it is additive, its glob matches nothing outside the
   probe fixture, and it is removed on every exit path a trap can see. The
   leg's last statement re-checks `ls ~/.claude/rules/` and records that
   output.
3. **Matching arm.** `mkdir -p "$TMP/selflearn-loader-canary"`, write
   `probe.txt`, and run a `claude -p` session with `cwd = $TMP` and a fresh
   `--session-id`, prompting a single Read of
   `selflearn-loader-canary/probe.txt`. The relative path *and* the
   absolute path both match the glob, because of the leading `**/` —
   which is exactly why the precedent idiom uses it.
4. **Non-matching arm (the negative control).** `mkdir -p
   "$TMP/selflearn-loader-nomatch"`, write an identical `probe.txt`, run an
   identical session with a fresh `--session-id` reading *that* file.
5. Grep each arm's transcript for `$CANARY`.

### 8.4 Leg 3 — the unpathed premise (§5.3)

Same harness — including §8.0's single-invocation rule and §8.3's
stale-test / trap / write ordering — with one change: write the canary rule
**without** a `paths:` key at all, and run only the non-matching arm. This
measures whether a rule with no `paths:` key loads unconditionally, the
premise behind the `len(unpathed)` term in `max_fanin`.

### 8.5 Preconditions — checked before any verdict is read

Every one of these must hold, or the run is **INVALID** and is re-run; an
invalid run is never recorded as a pass or a fail.

* **P1** — the transcript file for the run's `--session-id` was found, and
  `wc -l` on it is greater than zero. *(A grep against a file that does not
  exist prints nothing, which is byte-identical to "the canary is absent" —
  the fail-open shape this project has been burned by. Assert the file
  exists and is non-empty before reading any grep result.)*
* **P2** — the transcript contains a `Read` tool use whose input path is
  the intended fixture. If the model answered without reading, nothing was
  measured.
* **P3** — the transcript contains **no** tool use touching
  `~/.claude/rules/`. If the session read the rule file itself, the canary
  in the transcript proves nothing about injection.
* **P4a** — instrument positive control for the **canary** grep (legs 2
  and 3): `grep -c "$CANARY" ~/.claude/rules/selflearn-loader-probe.md`
  prints `1`.
* **P4b** — instrument positive control for the **Leg 1** grep:
  `grep -c "the session's cwd migrates mid-life" ~/.claude/rules/session-transcripts.md`
  prints ≥ 1 (§8.2 step 5). **Every grep in this check needs its own
  positive control.** P4a covers only the canary string; a Leg-1 substring
  that does not exist in the live rule prints `0` and reads as "the rule
  did not load". That is not hypothetical — r1 of this spec specified such
  a substring, and it measured `0` / `rc=1`.
* **P5** — the `claude -p` process exited 0 and its stdout is non-empty.
* **P6** — the leg's own start-of-run stale-file assertion (§8.0) passed:
  no `~/.claude/rules/selflearn-loader-probe.md` existed before the leg
  wrote one.

### 8.6 Pass / fail criteria

| Outcome | Condition | Consequence |
|---|---|---|
| **PASS** | Leg 1 finds the rule text; Leg 2 matching arm finds `$CANARY` **and** Leg 2 non-matching arm does **not** | The premise holds. Build proceeds. Record all four transcript greps verbatim. |
| **FAIL — rules do not load** | Leg 2 matching arm does **not** contain `$CANARY` (with P1–P6 all satisfied) | **STOP.** Do not ship §6. Report to the orchestrator: pathed user rules do not fire on Read, and this unit's premise is void. |
| **INCONCLUSIVE — not glob-gated** | `$CANARY` present in **both** Leg 2 arms | Rules load, but not because of the glob. Reachability validation is still coherent (a rule whose glob is dead is still a mistake) but the co-firing datum's meaning changes. Record it, ship §6, and route the finding to §12 Q3. |
| **INVALID — instrument** | Leg 1 does **not** find the rule text while Leg 2's matching arm **does** | The premise is confirmed by Leg 2, so this is an *instrument* defect in Leg 1, not a premise failure. Almost always the Leg-1 substring (see P4b). **Re-run Leg 1 after fixing the instrument; never record it as FAIL.** If P4b passed and Leg 1 still finds nothing while Leg 2 passes, stop and report — the two legs disagree about the same mechanism and neither verdict can be trusted. |
| **FAIL — premise** | Leg 1 does **not** find the rule text **and** Leg 2's matching arm does **not** contain `$CANARY` (P1–P6 all satisfied) | Same consequence as the FAIL row above: **STOP**, do not ship §6, report. |
| **INVALID** | any of P1–P6 fails | Re-run. Never recorded as pass or fail. |

Leg 3 reads separately: `$CANARY` present in the unpathed non-matching arm
confirms the `len(unpathed)` term; absent disconfirms it and triggers the
§5.3 fallback.

### 8.7 What must appear in `RESULTS.md`

The literal command line of every invocation; `claude --version`; each
session id; the resolved transcript path and its `wc -l`; the literal
output of every precondition check P1–P6 (P4b included); the literal
`grep -c` output of
every arm; the post-run `ls ~/.claude/rules/` proving the probe file was
removed; and the date. No paraphrase, no "verified" without the output that
verifies it.

---

## 9. Tests — enumerated

All CLI tests, run with
`uv run --project plugins/self-learn/cli pytest`. Every test that needs a
tree builds one under `tmp_path` and points the user root at it via the
existing `user_claude_md` override (§4.1) — **no test may probe the real
`$HOME`**, and a test that does is a defect in the test, not a slow test.
On the `selfcheck` path there is no `user_claude_md` parameter, so the
override is `monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD",
target)` (§6.6; precedent at `cli/tests/test_a2_rules_local.py:434-439`).
The budget is set through `SELF_LEARN_GLOB_PROBE_BUDGET_S`
(`monkeypatch.setenv`), never a literal.

### 9.0 T0 — four existing tests this unit REVERSES

T12 demands a green suite. §6 breaks four currently-passing tests, and each
reversal is a **spec ruling**, not a builder judgement call — a builder who
"fixes" one of these by weakening §6 has undone the unit. They are listed
with the required update.

| # | Test (`cli/tests/test_a2_rules_local.py`) | Why it breaks | Required update |
|---|---|---|---|
| 1 | `test_user_scope_glob_is_parse_only_never_zero_match` (**:279-299**) | routes `this/matches/nothing/**/*.ts` at user scope and asserts success; §6.3 now raises. Its name and its comment (*"this must NOT raise"*) **are** the fail-open being closed. | **Rewrite, do not delete.** Rename to `test_user_scope_zero_match_glob_is_refused`, invert to `pytest.raises(verbs.VerbError, match="match nothing under")`, and assert the record is still `pending` and the rules file absent. It becomes T1. |
| 2 | `test_user_scope_glob_not_reasserted_but_presence_still_checked` (**:428-453**) | routes `never/matches/anything/**` (now refuses at **:448**) and asserts `ok is True` at **:453**; §6.6 now returns False. | Rewrite as T10's primary case: materialize a matching file, route, delete it, assert `_check_drift` now reports. Keep its existing `monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)` at **:439** — it is the precedent M-3 pins. |
| 3 | `test_user_scope_emits_paths_frontmatter_A2` (**:896-917**) | routes `src/**/*.ts` against a `tmp_path` user root containing no `src/`; now refuses. | **Fixture change only, no assertion change.** Create `tmp_path/src/x.ts` before routing. The test is about frontmatter emission, and must stay about that. |
| 4 | `test_pathed_route_refuses_pre_ledger_on_managed_A11a` (**:1247-1261**) | `pytest.raises(VerbError, match="chezmoi")` on `a/**` with no `a/`; §6.3 orders the glob check *before* the chezmoi refusal, so the message is now the zero-match text. | **Fixture change, and a second test.** Create `tmp_path/a/x` so the glob reaches and the chezmoi refusal is what fires — this preserves the A11a coverage §6.3 would otherwise silently delete. Then **add** `test_pathed_route_refuses_dead_glob_before_chezmoi_on_managed`: the same managed fixture with `a/**` and no `a/`, asserting `match="match nothing under"` — pinning the ordering §6.3 argues for instead of leaving it untested. |

**The systemic rule, which is the actual ruling:** from this unit on,
**every user-scope pathed test fixture must materialize a file its glob
matches**, or explicitly assert the refusal. There is no longer such a
thing as a user-scope pathed route that neither matches nor refuses.

**And a fixture-coupling rule, because §4.1 widened the root set.** The
root set now includes registered hosts, so in principle a pattern could be
satisfied by the sandbox host rather than by the fixture the test built —
a coupling that does not exist today. Two facts bound it, and both were
checked:

* `make_env` (`cli/tests/support.py:147-175`) puts the sandbox host at
  `tmp_path/host-repo` and the ledger at `tmp_path/ledger-home`, while the
  user root in these tests is `target.parent.parent` = `tmp_path`. The host
  is therefore **under** `$HOME`, so §4.1's "not under `$HOME`" filter
  drops it from the root list — the *registered-host* coupling does not
  arise in this fixture family.
* But the walk still descends `host-repo/` and `ledger-home/`, because they
  live under the user root. A pattern like `plugins/**/SKILL.md` would be
  satisfied by the sandbox host's seeded skill tree, not by the test's own
  fixture.

**Ruling:** every user-scope pathed test pattern must carry a
**fixture-unique literal anchor** (e.g. `u-glob-fixture/**/*.ts`, not
`src/**/*.ts` or `plugins/**/*.md`), so no seeded sandbox content can
satisfy or deny it by accident. Case 3 above is grandfathered only because
its assertion is about frontmatter, not about reachability.

**T1 — a zero-match user glob is refused.** Fixture: a user-scope pathed
rules route with `rules_paths: ["**/nowhere-xyzzy/*.md"]` and a fixture
`$HOME` containing no such path. Assert `VerbError` is raised, that its
message contains `match nothing under`, the fixture root's path, and
`'**/nowhere-xyzzy/*.md'` (with quotes, from `repr`), and — the part that
makes this a real test — that **the record is still `pending`** and the
rules file was **not** written. A refusal that fires after the ledger
commit is not a refusal.

**T2 — positive control for T1.** *Written and run before T1's assertion
is trusted.* The same fixture with a matching file present routes
successfully, the rules file exists, and `routing` carries **no**
`allow_empty_glob` and **no** `glob_bypass_reason`. Without T2, T1 passes
identically against a build where user-scope routing is broken for every
reason.

**T3 — `--allow-empty-glob` at user scope routes and records the reason.**
T1's fixture plus `allow_empty_glob=True`: the route succeeds, the rules
file is written, `routing["allow_empty_glob"] is True`, and
`routing["glob_bypass_reason"] == "zero-match"`. Run at **both** the verb
level and through `cli.main(["route", <id>, "--allow-empty-glob"])`,
mirroring the existing pair at
`cli/tests/test_a2_rules_local.py:233,250`.

**T4 — budget exhaustion refuses, and its bypass reason differs.** Set
`SELF_LEARN_GLOB_PROBE_BUDGET_S=0` so the probe returns `"budget"` on the
first clock check. Assert: (a) without the flag, `VerbError` whose message
contains `could not be checked within the 0s reachability budget` and
`SELF_LEARN_GLOB_PROBE_BUDGET_S`; (b) with the flag, the route succeeds
and `routing["glob_bypass_reason"] == "budget"`. (b) is what proves the
two bypass reasons are actually distinguished rather than both collapsing
to `"zero-match"`.

**T5 — a matching user glob is accepted, including the live idiom.**
Fixture tree containing `<root>/.claude/projects/<slug>/x.jsonl`; the
pattern `**/.claude/projects/**/*.jsonl` routes without a bypass. A second
case places the match **eight directories deep** under the fixture root —
the M9 shape — and must also route, which is the regression guard against
anyone reintroducing a depth bound.

**T6 — `glob_reaches` unit behaviour**, against a small fixture tree, with
one case per branch of §4.3: floating pattern matching at the root's zero-
directory expansion; floating pattern matching only via the DFS; non-
floating pattern; empty-literal pattern (`**/*.ext`); a pattern whose only
match sits inside a **hidden** directory (must be `"match"` — this is the
§2.2 `include_hidden` fix, and it fails against the old matcher); a
symlinked directory pointing at a matching tree (must **not** be followed
by the DFS); multiple roots where only the second one matches; and
`budget_s` exhaustion returning `"budget"` rather than `"none"` (the
distinction the refusal texts depend on).

**T7 — `globs_may_intersect` on fixtures.** The 16 pairs of M7 as a
parametrized table, asserted in **both** argument orders (the relation must
be symmetric):

| a | b | expected |
|---|---|---|
| `**/.claude/hooks/*.sh` | `**/.claude/projects/**/*.jsonl` | False |
| `**/*.py` | `**/test_*` | True |
| `src/**/*.py` | `**/*.py` | True |
| `docs/*.md` | `src/*.md` | False |
| `**/*.md` | `**/*.py` | False |
| `a/b/c.txt` | `a/*/c.txt` | True |
| `**/x/**` | `**/y/**` | True |
| `*.sh` | `*.jsonl` | False |
| `**/*.jsonl` | `**/.claude/projects/**/*.jsonl` | True |
| `**/*.sh` | `**/.claude/hooks/*.sh` | True |
| `plugins/**/*.py` | `docs/**/*.py` | False |
| `**/[abc]*.md` | `**/b*.md` | True |
| `**/*.md` | `**/*.md` | True |
| `a/**` | `a/b/c` | True |
| `**/CLAUDE.md` | `**/*.md` | True |
| `**/CLAUDE.md` | `**/*.py` | False |

**Three more rows, added because the 16 above never exercise `?` or a
bracket class at all** — both route through `_tokens_may_share`, so with
the §5.2 class-extent rule unimplemented nothing in the table would notice
a mis-scanned class. All three verified against the algorithm, both orders:

| a | b | expected |
|---|---|---|
| `**/?.md` | `**/a.md` | True |
| `**/[!a]b.md` | `**/ab.md` | True |
| `**/[]x]y.md` | `**/]y.md` | True (the leading-`]` extent case) |

Plus one malformed-pattern case (`**/[unclosed*.md`) asserting the
unbalanced `[` is treated as a literal and **no exception escapes** —
matching `_translate_glob_segment`'s own rule.

**T8 — the co-firing set is computed on a fixture rules directory.**
Fixture `rules/` with five topic files: `alpha.md` (`**/*.py`),
`beta.md` (`**/test_*`), `gamma.md` (`**/*.md`), `delta.md`
(`**/*.jsonl`), `epsilon.md` (no `paths:` key at all). Assert
`surface_fill(...)["claude-md"]["rules_cofire"]` equals

```python
{"topics": ["alpha", "beta", "delta", "gamma"],
 "unpathed": ["epsilon"],
 "pairs": [["alpha", "beta"], ["beta", "gamma"]],
 "max_fanin": 4}
```

(`beta` = `**/test_*` intersects both `**/*.py` and `**/*.md`; `delta`
intersects nothing; `max_fanin` = 1 unpathed + (1 + 2) for `beta` = **4**,
per §5.3's formula. r1 asserted `3` here while its own parenthetical
computed 4 — a build matching the wrong number *was* the M-10 mutation, so
M-10 could not fail. The number below is the one §5.3 defines, and M-10 now
lands on it.) Add a
sixth topic whose `paths:` value is `[]` and assert it lands in
`unpathed` — the `has_paths_key` vs `read_paths_frontmatter` distinction
of §5.3, which a build keyed on the reader would get wrong.

**T9 — `cap_reason` replacement.** Two cases against the same
`surface_fill` call:
* **Six mutually disjoint topics** (`**/*.a` … `**/*.f`):
  `rules_topic_count == 6`, `max_fanin == 1`, `over_cap` is **False**, and
  `cap_reason` is not `"rules-topics"`. This is the defect: today's build
  reports `over_cap` here.
* **Six topics that all intersect** (all `**/*.md`-family):
  `max_fanin == 6`, `over_cap` is **True**, `cap_reason == "rules-cofire"`.
* A third case asserts the OR-ing survives: a target already `over_cap`
  from the entry/word cap keeps `over_cap` True and its original
  `cap_reason` is only overwritten when the co-firing signal also fires —
  the `verbs.py:1781-1783` pin.
* The two existing assertions at
  `cli/tests/test_a2_rules_local.py:364-377` are updated, not deleted:
  `rules_topic_count` stays asserted (it is still emitted); the
  `cap_reason == "rules-topics"` assertion becomes the new pair above.
  `cli/tests/test_surface_fill.py:259` gains the `rules_cofire` key for an
  empty rules directory: `{"topics": [], "unpathed": [], "pairs": [],
  "max_fanin": 0}`.

**T10 — `selfcheck` reports a user-scope glob that has gone dead.**
Derived from the existing test at `cli/tests/test_a2_rules_local.py:428-453`
(T0 case 2).

**Mandatory first line of this test:**
`monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)`.
`selfcheck` takes no `user_claude_md` argument — it hardcodes
`DEFAULT_USER_CLAUDE_MD.expanduser()` (`selfcheck.py:98,246,252,322`) — and
§4.1 forbids inventing a second handle. Without this line the test probes
the **real** `$HOME` (~688k directories per run), and §9's own "a test that
does is a defect in the test" fires on it. The precedent is already in that
same file at **:434-439**, with a comment saying why.

Primary case: a routed user-scope pathed record whose glob matched at route
time and whose fixture file is then deleted — `selfcheck` returns a failure
naming the record id and the pattern.

Companion cases, one per §6.6 branch:
* `glob_bypass_reason == "zero-match"` → **not** reported (deliberate
  write-the-rule-first).
* `allow_empty_glob: true` with **no** `glob_bypass_reason` key (a legacy
  record) → **not** reported.
* `glob_bypass_reason == "budget"` → **IS** reported when the probe now
  returns `"none"`. This is the M-2 finding: a transient timeout must not
  buy a permanent exemption. Asserting the *opposite* here is the single
  easiest way to build §6.6 backwards, which is why it is enumerated.
* a live `"budget"` verdict during the audit itself (via
  `SELF_LEARN_GLOB_PROBE_BUDGET_S=0`) → **not** reported as drift; only
  `"none"` is. That is the §6.6 asymmetry between gate and audit.

**T11 — the read-only path never probes.** `surface_fill` and any
`check_dirty=False` resolve must not call `glob_reaches`. Assert by
monkeypatching `glob_reaches` to raise, then calling `surface_fill` and
`_resolve_target(..., check_dirty=False)` and asserting neither raises.
Without this, `list --json` walks `$HOME` once per record.

**T12 — the whole suite.** `uv run --project plugins/self-learn/ui pytest`
must be green apart from the one known pre-existing failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`).
Note that T12 is only *reachable* once §9.0's four reversals are done — a
builder who leaves them is looking at four red tests that this spec
predicted, not at a regression.

**T13 — mixed failures refuse, and name both lists (§7.5).** One route
whose `rules_paths` holds two patterns: one provably dead, one that hits
the budget (`SELF_LEARN_GLOB_PROBE_BUDGET_S` set so the second exhausts).
Assert: (a) without the flag, one `VerbError` whose message contains
**both** `match nothing under` **and** `could not be checked within`, and
contains **both** patterns' `repr`; (b) with `--allow-empty-glob`, the
route succeeds and `routing["glob_bypass_reason"] == "zero-match"` (the
more actionable reason wins, §6.2) — which also means §6.6 gives the record
the *stricter* exemption, never the budget one. Paired with mutation M-15.

---

## 10. Out of scope

1. **The cap threshold (TaskList #1).** `> 5` is carried over unchanged
   onto the new quantity. This unit produces the data (`pairs`,
   `unpathed`, `max_fanin`); #1 decides what number means "too much" and
   whether a fan-in bound is even the right control. Do **not** re-derive
   the threshold here.
2. **A general reachability emitter (U-pointer, TaskList #10).** `#10`
   generalises these point checks into one emitter. This unit adds two
   named primitives and calls them from three sites. It does **not** build
   a framework, a registry of checks, or a pluggable verdict type.
3. **S-24, the search-only gap.** Rules fire on `Read`, not on a
   `grep`-and-give-up. Adjacent, real, and explicitly not this unit's.
   Nothing in §8 should be redesigned to measure it.
4. **Skill-scope rules (P-A13).** Still deferred; the refusal at
   `verbs.py:859-864` is untouched.
5. **The UI.** `BudgetRow` and `_budget_text` read `over_cap` and the four
   fill numbers; `rules_cofire` gains no display in this unit. A surface
   for it is a separate decision about what a human should see.
6. **`glob.glob` elsewhere in the tree.** Only the two rules-glob call
   sites (`verbs.py:788`, `selfcheck.py:585`) move to the new probe. Other
   `glob_mod` uses are reported, not edited.
7. **Retro-fixing already-routed records.** Records routed before this
   unit under the old user-scope skip are not re-validated at upgrade
   time; `selfcheck` (§6.6) will surface the dead ones on its next run,
   which is the intended and only migration.

---

## 11. Mutation plan

Each row is a single-edit mutation the code gate applies to the built
tree; the named test **must** fail. A mutation that leaves the suite green
means the test is decorative.

Two of these (**M-10**, **M-16**) exist because r1 shipped a contract that
no test could distinguish from its own mutation — B-2 and M-2 at the gate.
A mutation row whose "test that must fail" passes is the same defect
recurring, and is a build failure, not a note.

| # | Mutation | Test that must fail |
|---|---|---|
| M-1 | In `_resolve_rules_target`'s user leg, delete the `_validate_rules_globs` call | T1 |
| M-2 | In `glob_reaches`, return `"match"` instead of `"none"` when all roots are exhausted | T1, T6, T10 |
| M-3 | In `glob_reaches`, return `"none"` instead of `"budget"` on clock exhaustion | T4(a) message assertion, T6, T10 |
| M-4 | Drop `include_hidden=True` from `_first_hit` | T6 hidden-directory case |
| M-5 | In `_user_reachability_roots`, cap the DFS at depth 4 | T5 deep-match case |
| M-6 | In `globs_may_intersect`, make `_tokens_may_share` always return `True` | T7 (`*.sh` × `*.jsonl`) |
| M-7 | In `globs_may_intersect`, make the `**` branch consume exactly one segment | T7 (`src/**/*.py` × `**/*.py`) |
| M-8 | In `surface_fill`, key `unpathed` on `read_paths_frontmatter` instead of `has_paths_key` | T8 `paths: []` case |
| M-9 | Restore `if count > 5` as the `over_cap` trigger | T9 disjoint-topics case |
| M-10 | Drop `len(unpathed)` from `max_fanin` (yielding 3 where §5.3 defines 4) | T8 |
| M-11 | In `selfcheck`, restore `and record.scope == "project"` | T10 |
| M-12 | In `selfcheck`, treat a live `"budget"` verdict as a failure | T10 live-budget case |
| M-13 | Record `glob_bypass_reason` as always `"zero-match"` | T4(b) |
| M-14 | Call `glob_reaches` from `surface_fill` | T11 |
| M-15 | In `_validate_rules_globs`, return after the first dead pattern instead of collecting both kinds | T13(a) |
| M-16 | Key §6.6's drift exemption on `allow_empty_glob` alone instead of on `glob_bypass_reason` | T10 `"budget"`-is-reported case |
| M-17 | In `_user_reachability_roots`, use the rules-file `target.parent.parent` (`~/.claude`) instead of the CLAUDE.md `base.parent.parent` (`$HOME`) | T5 (the `**/.claude/projects/**/*.jsonl` idiom case) |
| M-18 | In `_segment_may_intersect`, end a bracket class at the first `]` (`seg.index("]")`) | T7 `**/[]x]y.md` row |
| M-19 | Drop the `i < len(a)` guard from the segment-level `*` bullet | T7 (raises `IndexError`, so any asymmetric row) |

---

## 12. Open questions routed to the gate

**Q1 — is `$HOME` + registered hosts the right root set for a machine
unlike this one?** §4 rules on measured facts from *this* host: `$HOME` is
676k directories and walks in 2.65 s, and the registered hosts all sit
inside it. A host with `$HOME` on a network filesystem, or with work trees
outside `$HOME` and unregistered, would behave differently. The escape
hatch and the budget refusal are the designed answer; the gate should say
whether that is enough or whether a `hosts.yaml` key naming extra
reachability roots belongs in this unit rather than a later one.

**Q2 — does an unpathed rule load unconditionally?** §5.3's `len(unpathed)`
term assumes yes. §8 leg 3 measures it. If leg 3 disconfirms, the builder
applies the stated fallback (drop the term, keep the list). The gate should
confirm that a measured disconfirmation is a build-time adjustment and not
a fresh spec round.

**Q3 — what if rules load regardless of the glob?** §8.6's INCONCLUSIVE
row ships §6 anyway, on the ground that a rule whose glob matches nothing
is still a defect a human wants named. The gate should confirm that
reading, because the alternative — that the glob is decorative and this
whole unit is guarding nothing — is a materially different conclusion and
belongs to the orchestrator, not the builder.

**Q4 — is the project-scope `include_hidden` change a behaviour change the
campaign wants now?** §2.2 shows the two validators disagree today (M6).
Fixing it makes previously-refused project patterns route. That is the
correct direction (it aligns route time with proposal time), but it is a
behaviour change to a shipped path, and the gate should ratify it rather
than let it ride in as a side effect of the rewrite.

---

## 13. What r2 changed — gate finding → fold

Round-1 verdict: **NOT SOUND, 3 BLOCKER / 6 MAJOR / 8 NIT.** All folded in
place; nothing deferred.

| Finding | Fold |
|---|---|
| **B-1** Leg-1 grep string absent from the live rule; no Leg-1 positive control | §8.2's substring corrected to `the session's cwd migrates mid-life` — the live file reads *"**the** session's cwd"*, and the r1 string measures `0` / `rc=1`. New step 5 runs the control **before** the transcript grep; §8.5 splits P4 into **P4a** (canary) and **P4b** (Leg 1), with the standing rule that every grep in the check carries its own positive control. |
| **B-2** T8's `max_fanin: 3` contradicts §5.3's formula, so M-10 could not fail | T8 asserts **4**; the parenthetical states the arithmetic and names the r1 error; M-10's row now names the wrong value it produces. |
| **B-3** four existing user-scope tests reversed and unlisted; T12 unreachable | New **§9.0 (T0)** enumerates all four (`:279-299`, `:428-453`, `:896-917`, `:1247-1261`) with per-test required updates — rewrite, fixture-only, or fixture plus a new ordering test that preserves the A11a coverage §6.3 would otherwise delete. States the systemic rule (*every user-scope pathed fixture materializes a matching file or asserts the refusal*) and **rules** the fixture-coupling question: the sandbox host sits at `tmp_path/host-repo`, under the user root, so §4.1's filter drops it from the root list — but the walk still descends it, hence the new **fixture-unique literal anchor** requirement. T12 now states it is only reachable after T0. |
| **M-1** §4.2 reason (ii) was inferred from M9, not measured | Reason (ii) **withdrawn**, and marked as withdrawn rather than quietly deleted. M9's row restated as a DFS-ordering artifact — the live rule also matches at depth 4, which the probe reaches with 0 directories walked. The no-bound ruling stands on reason (i) alone. |
| **M-2** a transient timeout permanently disables drift detection for that record | §6.6's exemption re-keyed on **`glob_bypass_reason == "zero-match"`** (plus legacy records carrying no reason key); a `"budget"` record is re-probed on every audit. §6.5 states `allow_empty_glob` is compatibility-only and nothing reasons from it. New measurement row **M10** (17.95 s cold vs 3.74 / 3.69 s warm) and the budget raised **10 s → 30 s**, calibrated on the cold number. New mutation **M-16**. |
| **M-3** `selfcheck` has no `user_claude_md` handle, so T10 probed the real `$HOME` | §6.6 spells the argument (`DEFAULT_USER_CLAUDE_MD.expanduser()`) and states no second handle is added; §9's preamble and T10 both pin `monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)`, citing the precedent at `test_a2_rules_local.py:434-439`. |
| **M-4** §7.5 had no test and no mutation | New **T13** (both message halves, both patterns, `"zero-match"`-wins bypass reason) and new mutation **M-15**. |
| **M-5** §8.6 verdict hole | Two rows added — **INVALID — instrument** (Leg 1 fails while Leg 2 passes ⇒ instrument defect, re-run, never FAIL) and **FAIL — premise** (both fail). The precondition range is P1–P6 throughout. |
| **M-6** `trap` bounds one shell; the builder is a multi-call agent | New **§8.0**, binding on all three legs: one leg = one Bash invocation; normative ordering stale-test → trap → write; new **P6**; `SIGKILL` bypassing `EXIT` noted as why the start-of-run assertion exists. |
| **N-1** `target.parent.parent` collides with the snippet's local (yields `~/.claude`) | Substituted to `user_claude_md_target.parent.parent`, with a paragraph naming both readings and why M4 rules the wrong one out. New mutation **M-17**. |
| **N-2** "the single over-approximating step" is false | Restated as **two** steps, the second being a trailing `**` consuming zero segments; verified (`_compile_glob_pattern("a/**").match("a")` is `None` while the DP returns `True`). |
| **N-3** balanced-class extent unpinned | §5.2 pins the scan exactly as `_translate_glob_segment` does (`ledger_ops.py:634-651`), with three examples verified against the shipped translator. New mutation **M-18**. |
| **N-4** rule ordering `IndexError`s when one side is exhausted | Both levels rewritten with explicit `i < len(...)` / `j < len(...)` guards and the exhaustion bullet moved below them, plus a note that the guards are contract, not style. New mutation **M-19**. |
| **N-5** T7 never exercises `?` or a bracket class | Three rows added (`**/?.md` × `**/a.md`, `**/[!a]b.md` × `**/ab.md`, `**/[]x]y.md` × `**/]y.md`), all verified True in both orders. |
| **N-6** §2.1 citation drift | `verbs.py:862-880` → **`verbs.py:866-884`**. |
| **N-7** §2.2 overstates the fix | "removes the disagreement" → "removes the *hidden-path* disagreement", with the remaining symlinked-directory divergence declared and marked not-a-regression. |
| **N-8** §6.8's quoted "before" text drops the `A2 §5.1:` prefix | The current string is quoted verbatim including the prefix; the spec states the prefix is **kept** and gives the replacement text in full. |

**Unchanged by ruling** (the gate verified these and no finding named
them): §2.1–§2.4's citations, §3's M1–M9, §4.1's root set, §5.1's
symbolic-over-witness ruling, §5.3's datum shape, §10's scope boundaries,
and Q1–Q4.
