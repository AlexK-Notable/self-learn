# Spec — U-xscope: the enumeration contract for managed-section compiles

Status: **r1 folded — gate round 1 returned CHANGES REQUIRED (2 BLOCKER, 4
MAJOR, 9 NIT); all findings folded in place, awaiting re-gate.** Unit
`U-xscope`, TaskList #12. Consumed by a blind Opus spec gate, then a Sonnet
builder.

**Gate round 1 outcome:** the defect diagnosis of §2 was independently
reproduced and **confirmed in full** (every probe re-run, every table
matched). What blocked was the *fix shape* — §3's mandated reuse of
`selfcheck._target_for` was not implementable as written. §3 is rewritten
below; §2 is unchanged except for three factual corrections (NIT 7, NIT 8,
NIT 9), each marked.

**What this unit is.** A managed section is regenerated **from scratch** on
every compile. Whatever the enumeration hands the compiler *is* the section;
whatever it fails to hand over is **deleted from canon**. Today the
enumeration for a `SKILL.md` asks *"which records were routed with THIS
destination, from THIS bucket"* instead of *"which records land in THIS
FILE"*. Two destinations resolve to the same file, so each one's compile
erases the other's lines. This unit replaces the question.

**The ruling this unit serves:** *a compiled target's content is a function
of the target, not of the route that happened to touch it last.* Every
regeneration of a file must consider every record that lands in that file.

**Where prose and the acceptance criteria conflict, §3 (the contract), §7
(tests) and §9 (acceptance criteria) win.** The prose is rationale.

**Citations.** Every `file:line` below was read against this worktree at
**`b316f1e`** and is written *anchor first, line second*
(`verbs.py::_compile_set`, currently `verbs.py:1605`). Paths are
repo-relative; the CLI package root is `plugins/self-learn/cli/`, so
`verbs.py` means `plugins/self-learn/cli/src/self_learn/verbs.py`.
Ledger observations were taken **read-only** against the live
`~/.self-learn` on 2026-08-23.

**Files this unit may touch.**

| File | Why |
|---|---|
| `cli/src/self_learn/verbs.py` | **home of the shared resolver** (§3.1); `_compile_set` becomes target-derived; `recompile`'s spec key; `_apply_new_skill`'s empty-set guard |
| `cli/src/self_learn/selfcheck.py` | **scoped: the import line `selfcheck.py:98` and the body of `_target_for` only** — `_target_for` is replaced by a delegation to the shared resolver in `verbs.py` (§3.1). No other line of this file may change. |
| `cli/src/self_learn/compilers.py` | docstring only, if the contract is restated there — **no behaviour change to `_eligible` / `compile_managed_text`** |
| `cli/tests/test_xscope_enumeration.py` *(new)* | the tests of §7 |
| `cli/tests/support.py` | ONLY if a collision-shaped host fixture helper is added (§7.1) |

Anything else is out of scope and must be **reported, not edited**. In
particular: no file in `~/.self-learn` is written by this unit, and no host
repo is committed by this unit's tests.

---

## 1. Objective

Make the compile set of a managed-section target **the union of every
resolved record that resolves to that target**, across every bucket, so
that:

1. A `skill-md` route into a skill that was **scaffolded** by `new-skill`
   stops deleting the scaffolding lessons (and vice versa).
2. `self-learn recompile` — the one advertised repair, and the repair the
   drift check itself recommends by name — actually **restores** what a
   blind compile deleted, instead of re-deleting it and reporting
   "up to date".

The fix is **one question, asked in one place**. It is emphatically *not* a
special case in the apply path: §2.4 shows the full-recompile path is blind
in exactly the same way, for exactly the same reason.

---

## 2. Current behavior (verified)

*Confirmed independently by the round-1 gate: §2.1 (12/12 layout), §2.3 (the
five-record table and `ff45510`'s 1+/4-), §2.4 (bucket walk order), §2.5
(drift output byte-for-byte), §2.6 (union order), §2.7 (sweep table and the
bare-scan false EXTRAs, 24 vs 22).*

### 2.1 Two destinations resolve to the SAME file

`verbs.py::_resolve_target`, `skill-md` leg (`verbs.py:978-993`):

```python
    if destination == "skill-md":
        if not scope.startswith("skill:"):
            raise VerbError(...)
        root, skill_dir = _hosts_skill_dir(home, scope.partition(":")[2])
        target = skill_dir / "SKILL.md"
```

`hosts.py::skill_dir_for` (`hosts.py:546-567`, the glob at
`hosts.py:555-557`) resolves that by globbing `plugins/*/skills/<name>`
under the registered skills root.

`verbs.py::_resolve_target`, `new-skill` leg (`verbs.py:1041-1084`, target
at `verbs.py:1062-1063`):

```python
        plugin_dir = root / "plugins" / name
        target = plugin_dir / "skills" / name / "SKILL.md"
```

**Every skill in the live skills root is laid out `plugins/<name>/skills/<name>/`**
— verified by `ls -d ~/repos/claude-skills/plugins/*/skills/*/`:
12 of 12 plugin directories are named exactly for the skill they contain.
So for **every** skill in the live host, the `skill-md` target and the
`new-skill` target are **byte-identical paths**. The collision is not an
edge case; it is the shipped layout.

### 2.2 The two compile sets are disjoint

`verbs.py::_compile_set` (`verbs.py:1605-1621`):

```python
    if spec.destination == "skill-md":
        return _routed_to([spec.bucket_dir], "skill-md")
    if spec.destination == "new-skill":
        # a scaffolded skill may collect lessons from ANY bucket — the
        # name on the routing block is the grouping key.
        return [
            r
            for r in _routed_to(_all_bucket_dirs(home), "new-skill")
            if (r.routing or {}).get("new_skill") == spec.new_skill
        ]
```

The `skill-md` leg reads **one bucket** and **one destination value**. The
`new-skill` leg reads **all buckets** but a **different destination value**.
`verbs.py::_routed_to` (`verbs.py:604-646`) hard-filters
`routing.destination != destination`, so the two sets can never intersect.

Both sets are then fed to `compilers.compile_managed_file` →
`compilers.compile_managed_text` (`compilers.py:289-346`), which
regenerates the **whole** section:

```python
    entries = [entry_line(r) for r in _eligible(records)]
    section = "\n".join([BEGIN_MARKER, *entries, END_MARKER])
```

(`compilers.py:301-302`). There is no merge with what was on disk. A
compile driven by set A **deletes** every entry of set B.

The same file already carries the fix for the *other* instance of this
collision — the `claude-md` leg at `verbs.py:1630-1671` unions project
scope and skill-root scope for a repo registered as both, with the comment
"*each route of one scope ERASES the other scope's lines and recompile
cannot restore them (adversarial review 2026-07-17 finding 3; latent since
M1)*". **U-xscope is the same defect, in the destination that was not
audited.**

### 2.3 The live damage — burn-in route 9

Ledger facts (read-only, `~/.self-learn`):

| id | bucket | `scope:` | `routing.destination` | `routing.new_skill` | `routed_at` |
|---|---|---|---|---|---|
| `lrn-4f89e33a` | `user/` | `user` | `new-skill` | `testing-methodology` | `2026-08-09T01:11:30Z` |
| `lrn-fe16fceb` | `user/` | `user` | `new-skill` | `testing-methodology` | `2026-08-09T01:11:36Z` |
| `lrn-566216a6` | `user/` | `user` | `new-skill` | `testing-methodology` | `2026-08-09T01:11:42Z` |
| `lrn-0529f554` | `user/` | `user` | `new-skill` | `testing-methodology` | `2026-08-09T01:11:48Z` |
| `lrn-0a76fae2` | `skills/testing-methodology/` | `skill:testing-methodology` | `skill-md` | — | `2026-08-21T06:26:54Z` |

All five are `status: routed`, `superseded_by: null`. These are the **only**
four `new-skill` records in the entire ledger, and `skills/testing-methodology/resolved/`
holds exactly one file.

Routing `lrn-0a76fae2` produced commit `ff45510` in
`~/repos/claude-skills`:

```
self-learn: apply lrn-0a76fae2 → plugins/testing-methodology/skills/testing-methodology/SKILL.md (skill-md)
 plugins/.../SKILL.md | 5 +----
 1 file changed, 1 insertion(+), 4 deletions(-)
```

The diff removes the four `new-skill` entry lines and inserts one. The
section on disk today has **one** entry.

### 2.4 `recompile` shares the blindness — and `setdefault` makes it deterministic

`verbs.py::recompile` enumerates targets by walking every bucket
(`verbs.py:3899`) and registering one spec per resolved target:

```python
            specs.setdefault((spec.host_repo, spec.target), spec)
```

(`verbs.py:3993`.) Both the `skill-md` spec and the `new-skill` spec key to
the **same** `(host_repo, target)` pair — both derive `host_repo` from the
same `_gate_host(home, hosts.skills_root, "skills-root")` call
(`verbs.py:710`, `verbs.py:1054`) — so `setdefault` keeps whichever bucket
is walked first, and `ledger.py::discover_buckets` (`ledger.py:142-160`)
walks `skills/*` **before** `projects/*` and `user/`. The
`skills/testing-methodology` bucket therefore always wins, its `skill-md`
spec is the one applied, `_compile_set` returns one record, and the compile
is byte-identical to what is already on disk — so `compile_result.changed`
is False and the entry reports no change.

This is exactly what the orchestrator's diagnostic observed on 2026-08-23
15:08: `self-learn recompile --no-push` reproduces the 1-line section and
reports it up to date. **The blindness is in the enumeration, shared by
both paths. There is no apply-path special case to write.**

Note also `verbs.py::_apply_target` (`verbs.py:1973`, `verbs.py:2005`) and
`verbs.py::_apply_new_skill` (`verbs.py:2069`) both call `_compile_set` —
one function, four call sites, one bug.

### 2.5 The drift check SEES the damage and recommends a repair that does nothing

Run read-only against the live ledger (2026-08-23):

```
selfcheck._check_drift(~/.self-learn) → ok=False
  lrn-0529f554: entry marker missing from .../testing-methodology/SKILL.md — run `self-learn recompile`
  lrn-4f89e33a: entry marker missing from .../testing-methodology/SKILL.md — run `self-learn recompile`
  lrn-566216a6: entry marker missing from .../testing-methodology/SKILL.md — run `self-learn recompile`
  lrn-fe16fceb: entry marker missing from .../testing-methodology/SKILL.md — run `self-learn recompile`
  lrn-c826137f: references target unresolvable via hosts.yaml — register the host, then `self-learn recompile`
```

This is the worst shape a system can have: the gate is **correct**, and the
remedy it names by string is a **no-op**. A human following the instruction
gets "up to date" and reasonably concludes the gate is noisy. Closing that
loop — the drift check going green *because the canon was repaired* — is
the acceptance criterion for §5.

(`lrn-c826137f` is a separate finding; see §6.4. It is **not** fixed here.)

### 2.6 A target-keyed union already exists — in the wrong module, and it is not the same resolution

`selfcheck.py::_section_targets` (`selfcheck.py:433-452`) accumulates
**by target path**:

```python
            target = _target_for(home, bucket, record)
            if target is not None:
                targets.setdefault(target, []).append(record)
```

and `selfcheck.py::_target_for` (`selfcheck.py:210-258`) resolves both
`SKILL.md` destinations to their files. Run against the live ledger with
`compilers._eligible` applied, this yields for
`plugins/testing-methodology/skills/testing-methodology/SKILL.md`:

```
['lrn-4f89e33a', 'lrn-fe16fceb', 'lrn-566216a6', 'lrn-0529f554', 'lrn-0a76fae2']
```

Five records, in exactly the order the pre-`ff45510` file had them. **The
union self-learn needs is already computed inside `selfcheck`; the compilers
just never ask for it.**

**But `_target_for` is NOT the verbs' resolution, and reusing it as-is is a
blanking bug** — see §3.1's B1 ruling. Its `skill-md` and `new-skill` legs
(`selfcheck.py:215-230`) agree with the verbs; its **claude-md legs do
not**, because it hardcodes `DEFAULT_USER_CLAUDE_MD` (`selfcheck.py:246`,
`selfcheck.py:252`) where `_resolve_target` honours a threaded
`user_claude_md` override (`verbs.py:1013-1015`). The shape §3 codifies is
the *union keyed on target*; the *resolver* it keys on must be the
parameterized one built in §3.1, not `_target_for` as it stands today.

### 2.7 The live sweep: one damaged target, and a trap in the naive instrument

Comparing, for every target `_section_targets` knows, the eligible union
against the entry ids actually present inside the on-disk marker pair:

| target | union | on disk | missing |
|---|---|---|---|
| `~/.claude/CLAUDE.md` | 22 | 22 | — |
| `~/.claude/rules/hooks.md` | 1 | 1 | — |
| `~/.claude/rules/session-transcripts.md` | 1 | 1 | — |
| `~/.config/CLAUDE.md` | 3 | 3 | — |
| `claude-skills/CLAUDE.md` | 2 | 2 | — |
| `.../chezmoi/SKILL.md` | 0 | 0 | — |
| `.../hypr-doctor/SKILL.md` | 3 | 3 | — |
| **`.../testing-methodology/SKILL.md`** | **5** | **1** | **4** |
| `keyboards/CLAUDE.md` | 1 | 1 | — |
| `keyboards/zmk-config-offsetkey/CLAUDE.md` | 1 | 1 | — |
| `nsys-marketplace/.claude/rules/command-agent-closure.md` | 1 | 1 | — |

**Exactly one target is damaged today.** But the first version of that sweep
reported two spurious EXTRA ids in `~/.claude/CLAUDE.md` (`lrn-ca690038`,
`lrn-dd9489b2`), because it scanned the section for **any** `lrn-` id. Both
"extras" are **prose mentions inside other entries' text** — e.g.
`… is covered separately by lrn-ca690038.) *(lrn-ea833a5b)*`. Anchoring the
scan on the entry-line suffix instead —
`^- .*\*\((lrn-[0-9a-f]{8})\)\*\s*$`, **compiled with `re.MULTILINE`**
(NIT 9: without that flag `^…$` matches nothing and the instrument silently
reports zero entries everywhere) — returns 22, matching the union exactly.
**§6 mandates the anchored form**; a bare id scan is a broken instrument.

---

## 3. The enumeration contract

### 3.1 The shared resolver: `verbs.py::managed_target_for(home, bucket, record, *, user_claude_md=None)`

**Where it lives (BLOCKER 2 ruling — do not improvise this).** The shared
resolver is a **new function in `verbs.py`**. `selfcheck.py::_target_for`
becomes a thin delegation to it.

The reason this must be stated rather than left to the builder: the obvious
route — importing `selfcheck._target_for` from `verbs.py` — is a **module
cycle**. `selfcheck.py:98` already reads
`from .verbs import DEFAULT_USER_CLAUDE_MD, _project_rules_dir, _user_rules_dir`,
so `selfcheck → verbs` exists at module level. And the three symbols
`_target_for` depends on live at `verbs.py:174` (`DEFAULT_USER_CLAUDE_MD`),
`verbs.py:753` (`_user_rules_dir`) and `verbs.py:760` (`_project_rules_dir`)
— all *after* any import block, so a top-of-file `verbs → selfcheck` import
cannot work either.

`verbs.py` is the right home because it already imports every lower-layer
dependency the resolver needs: `HostsError, load_hosts, skill_dir_for`
(`verbs.py:104-111`), `discover_buckets` (`verbs.py:112`),
`bucket_project_path` (`verbs.py:119`), `Record, RecordError`
(`verbs.py:132`), and it *owns* all three constants locally. Only the
`Bucket` dataclass needs adding to the existing `from .ledger import …`
line — `verbs → ledger` already exists, so that adds no cycle.

**Deferred-import ruling.** Route 3 above needs **no** deferred import: the
delegation runs `selfcheck → verbs`, the direction that already exists. If
the builder nonetheless hits an unforeseen cycle, an in-function deferred
import **is acceptable**, on the in-repo precedent
`skill_scaffold.py:56` — `from .ledger_ops import record_title  # local: avoids a module cycle`
— and must carry the same inline `# local: avoids a module cycle` comment
so the next reader knows it is deliberate. It is a fallback, not the plan.

**What it computes.** For a resolved record `r` living in bucket `B`, the
managed-section target it lands in:

| `r.routing.destination` | target | keyed on |
|---|---|---|
| `skill-md` | `skill_dir_for(hosts, B.name) / "SKILL.md"` | **the bucket's `name`** — requires `B.scope == "skill"` |
| `new-skill` | `skills_root / "plugins" / N / "skills" / N / "SKILL.md"`, `N = r.routing.new_skill` | **the routing block's `new_skill`** |
| `claude-md`, `variant=None`, `r.scope == "user"` | `Path(user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD).expanduser()` | **the threaded override** — see B1 below |
| `claude-md`, `variant="rules"`, `r.scope == "user"` | `_user_rules_dir(<that same resolved user path>) / f"{topic}.md"` | idem |
| `claude-md`, `variant="local"` / `variant=None` / `"rules"` at `project` scope | as `_resolve_target` computes today (`verbs.py:1021-1026`, `_resolve_local_target`, `_resolve_rules_target`) | `bucket_project_path(B.path)` |
| `claude-md` at `skill:` scope | `skills_root / "CLAUDE.md"` | hosts registry |
| `reference`, `hook` | **no managed-section target** — not part of `C(T)` | — |

`managed_target_for` returns `None` when the target is unresolvable (no
skills root, unregistered host, ambiguous skill name, missing `new_skill`).
A `None` is **skipped, never guessed** — the drift check already reports
those records (`selfcheck.py:563`).

**BLOCKER 1 — the `user_claude_md` parameter is load-bearing, not a
convenience.** `_resolve_target` computes the user-scope target as an
*override-aware* path (`verbs.py:1013-1015`), threaded from ~14 call sites
including `recompile` (`verbs.py:3969`). `selfcheck._target_for` takes no
such parameter and hardcodes the default (`selfcheck.py:252`;
`selfcheck.py:246` for the rules variant). Had the shared resolver simply
*been* `_target_for`, then for any user-scope `claude-md`/`rules` spec whose
`spec.target` is an override — **every sandbox test**
(`tests/test_verbs.py:316`, `tests/test_retirement_cleanup.py:275`) **and
the chezmoi flow** — `managed_target_for` would return `~/.claude/CLAUDE.md`,
which never equals `spec.target`. `C(T)` would be **empty and the user
section would blank**: the precise failure mode §3.4 exists to prevent,
reached through an un-threaded parameter instead of a scope mismatch. It
would also aim the sandbox at the operator's real `~/.claude/CLAUDE.md`.

Therefore, normatively:

1. `managed_target_for` **takes `user_claude_md`** and every caller threads
   the value it already holds. `_compile_set` reads it off the spec's own
   resolution context; `recompile` already carries it (`verbs.py:3969`);
   `selfcheck._section_targets` passes `None` (its callers have no
   override), which reproduces today's selfcheck behaviour exactly.
2. Project-scope resolution keys on `bucket_project_path(B.path)`, which is
   what both `_resolve_target` and `_target_for` already do — no new
   parameter needed there, but the builder must **verify** that rather than
   assume it, and report if a `project_path` override turns out to be
   threaded anywhere that matters.
3. **T8 (§7.3) is mandated to pass a `user_claude_md` override** and assert
   the section lands in the override file with the right ids. That test is
   the one that would have caught this blanking.

**One resolution, one copy.** After this change there must be exactly one
implementation of the table above. `selfcheck._target_for` delegates; it does
not keep a parallel body. Two copies of this rule, free to drift, is how
this defect class reproduces.

### 3.2 `C(T)` — the compile set of a target

For a managed-section target `T`:

> `C(T)` = every record `r` in `<bucket>/resolved/lrn-*.md`, for **every**
> bucket returned by `discover_buckets(home)`, whose
> `managed_target_for(home, B, r, user_claude_md=…)` equals `T` **under the
> normalization of §3.2.1**.

Three consequences, all normative:

1. **Destination is not a filter.** Membership is decided by the target
   path, not by which destination string produced it. A `skill-md` record
   and a `new-skill` record that land in the same file are in the same set.
2. **Bucket is not a filter.** `C(T)` is drawn from all buckets. A
   `user`-bucket record can be in a skill's set (that is precisely route 9).
3. **`C(T)` is a function of `T` alone** (given the same ledger and the same
   `user_claude_md`). The two `TargetSpec`s that resolve to `T` must produce
   **identical** sets. This is what makes `recompile`'s `setdefault` at
   `verbs.py:3993` safe for the *section*; §4.2 rules separately on its
   side effects.

#### 3.2.1 The single normalization point (MAJOR 5)

Path comparison is on `Path.resolve()` — but **normalization happens in
exactly one place: inside `managed_target_for`, on its return value.** The
function returns an already-resolved path, or `None`. Nothing downstream
re-normalizes, and nothing downstream compares an unresolved path.

This is not a stylistic pin. `_section_targets` today keys its dict on the
**unresolved** return of `_target_for` (`selfcheck.py:449-451`); a caller
that looked up `spec.target.resolve()` against those keys would miss every
entry and **blank every section**. Normalizing at the source makes dict keys
and lookups agree by construction. Concretely:

- `managed_target_for` returns `<path>.expanduser().resolve()`.
- Every lookup key is `spec.target.resolve()` (or, better, the spec's target
  passed through the same helper).
- `_section_targets`'s dict keys become resolved paths. That is a visible
  change to selfcheck's output paths; §7.4 must assert selfcheck's own
  target set is unchanged **as a set of resolved paths**, and the builder
  must confirm no selfcheck message formats a path the user would find
  surprising.

NIT 7 correction — the requirement is **defensive, not observed**: comparing
unresolved paths would silently split one target into two the moment the
skills root is reached through a symlink. **No live target resolves
differently today** — `readlink -f ~/repos/claude-skills` returns
itself, and `resolve()` is identity for all 11 live targets (measured
2026-08-23). The earlier claim that the skills root *is* symlinked was
false; the requirement stands on its own.

### 3.3 Eligibility and ordering — unchanged

`C(T)` is the *candidate* set. `compilers._eligible` (`compilers.py:278-283`)
still owns the rest, and this unit does not touch it:

```python
    kept = [r for r in records if r.status == "routed" and r.superseded_by is None]
    kept.sort(key=lambda r: (_iso((r.routing or {}).get("routed_at") or ""), r.id))
```

- `status != "routed"` → excluded (rejected, pending, deferred).
- `superseded_by is not None` → excluded. This covers **both** graduation
  (`superseded_by: canon`) and corrective supersession, across buckets: a
  `user`-bucket record graduated into a skill's canon must drop out of that
  skill's section, exactly as a same-bucket one does.
- Order is `(routing.routed_at, id)` (`compilers.py:282`) — routing order,
  id as tiebreak, computed over the **merged** set. `routed_at` is stamped
  at **second granularity** (`_now_iso()`, `ledger_ops.py:232`, used at
  `verbs.py:2388` and `verbs.py:2753`), so records routed within the same
  second **tie** and fall through to the id tiebreak. §7.2 T1 must respect
  that; see MAJOR 4 there.

For route 9 the live data yields the four 2026-08-09 entries (in their
01:11:30 → 01:11:48 order) followed by the 2026-08-21 entry, which is
byte-identical to the pre-`ff45510` file plus the new line. Verified in §2.6.

`expected_paths` / `_unpathed_by` / `_widened` (`compilers.py:509-564`)
already derive from `_eligible(records)` over the set they are handed, so
they inherit the corrected set with no edit. **They must not be given a
second, separately-computed set.**

### 3.4 How this contract avoids the bucket-identity hazard

Project memory `bucket-identity-is-scope-and-name.md` records that **five**
leaks of this class were found and fixed in one night (2026-08-02/03), and
that the *obvious* fix — `item["scope"] == bucket.scope` — is worse than the
leak: `Bucket.scope` is bare (`skill` / `project` / `user`) while a
**record's own** `scope:` frontmatter qualifies skills as `skill:<name>`, so
the equality is never true for a skill record and **every skill bucket goes
blank**. A merged count looks suspicious; a zero looks like an empty bucket.

This contract is built so that failure mode is **unreachable**:

1. **No NEW scope-vs-scope comparison may be introduced on the
   target-derivation path.** (MAJOR 3 rescope: the earlier blanket
   prohibition forbade a construct that correct, mandated-to-survive code
   already uses. Three sites are **explicitly whitelisted** and must keep
   working untouched: `verbs.py:1662` — `if b.scope == "skill"` — and
   `verbs.py:1665` — `scope_pred=lambda s: s.startswith("skill:")` — the
   pre-existing claude-md dual-role union §3.5 requires to survive
   byte-identically; and `selfcheck.py:215` — `if destination == "skill-md"
   and bucket.scope == "skill"` — which is the correct *bucket-kind* guard
   the shared resolver inherits.) What is forbidden is a **newly added**
   predicate comparing a *record's* `scope` frontmatter against a *bucket's*
   `scope`/`name` in order to decide set membership. The whitelisted sites
   compare a bucket's kind against a literal, or a record's scope against a
   literal — never one alphabet against the other.
2. **Where identity is unavoidable, it asks where the record LIVES.** The
   `skill-md` leg keys on `B.name` — the bucket directory the record is
   filed in — which is the memory's `_belongs_to_bucket` discipline ("asks
   where the record actually LIVES") and is what `selfcheck.py:215-217`
   already ships. It does **not** parse `r.scope`.
3. **The `new-skill` leg needs no identity at all.** It keys on
   `routing.new_skill`, a value written by the route itself. The memory's
   "*an item may carry no usable `scope` at all … dropping those silently is
   a fail-open*" hazard therefore cannot bite this leg: `Record.scope` is
   never consulted.
4. **A blanking regression is caught by construction.** §7 requires a
   positive control on **every** target class — a section that must be
   non-empty is asserted non-empty, with its ids named. A fix that blanks
   skill buckets fails those assertions immediately, at the exact granularity
   (per-target, per-id) that a count-only assertion would miss. **T8 in
   particular covers the B1 blanking route** (an un-threaded parameter),
   which is the same failure arriving by a different door.

A live datum that this hazard is not hypothetical here: `lrn-c826137f` is
filed in the **`user/` bucket** but carries `scope: skill:cron-claude`. Any
enumeration that attributed records by parsing `r.scope` would place it in a
`skills/cron-claude` bucket that **does not exist** (`ls ~/.self-learn/skills`
= `bitwarden-cli chezmoi home-assistant hypr-doctor testing-methodology`).
The contract above never looks at that field for attribution, so this record
is simply not a managed-section record (its destination is `reference`) and
is untouched.

### 3.5 What the contract does NOT change

- `compile_managed_text` / `compile_managed_file` / `_eligible` /
  `entry_line` — no behaviour change. This is an input-set fix.
- The `claude-md` dual-role union at `verbs.py:1630-1671` — its **effect**
  must survive byte-identically, including the two whitelisted predicates at
  `verbs.py:1662` / `verbs.py:1665`. Whether the builder re-expresses it
  through §3.2 or leaves it standing, `TestSharedClaudeMdUnion`
  (`tests/test_retirement_cleanup.py:418-456`) must stay green unmodified.
- `variant` / `rules_topic` partitioning (`verbs.py:604-646`,
  `verbs.py:1619-1629`) — distinct topics resolve to distinct **paths**, so
  target identity preserves the partition for free. It must not be weakened:
  a rules topic file and a plain `CLAUDE.md` are different targets and stay
  different sets.
- `reference` and `hook` destinations — append-only / verbatim, no managed
  section, out of `C(T)` entirely.
- Every line of `selfcheck.py` other than its import line and the body of
  `_target_for`.

---

## 4. New behavior

### 4.1 `_compile_set` becomes target-derived

`verbs.py::_compile_set(home, spec)` returns `C(spec.target)` per §3.2 for
every managed-section destination, threading `spec`'s own `user_claude_md`
context per §3.1(1). Required properties:

- **P1.** For a `spec` with `destination == "skill-md"` whose target is also
  a `new-skill` target, the returned set contains both destinations' records.
- **P2.** For a `spec` with `destination == "new-skill"`, likewise.
- **P3.** For two specs `s1`, `s2` with the same resolved target,
  `_compile_set(home, s1) == _compile_set(home, s2)` (same ids, same order).
- **P4.** For a target with no collision (every live target except
  testing-methodology, per §2.7), the returned set is **unchanged** from
  today's — same ids, same order. This explicitly includes every user-scope
  target reached through a `user_claude_md` override (B1).
- **P5.** Records are de-duplicated by id (the `seen` discipline already at
  `verbs.py:1652-1654` and `verbs.py:1668-1670`), so a record can appear at
  most once in a section.

The single-bucket read at `verbs.py:1610` is the line being deleted. Note
that widening `skill-md` to all buckets **without** also merging the
`new-skill` records fixes nothing: the two live in different destination
values, not different buckets. The fix must cross the **destination**
boundary, not just the bucket boundary.

### 4.2 `recompile`'s spec key, and the side effects the two legs do not share

With P3 holding, `specs.setdefault((spec.host_repo, spec.target), spec)`
(`verbs.py:3993`) yields the same **section bytes** whichever spec wins. The
two apply legs are **not otherwise equivalent** (MAJOR 6):

- `_apply_new_skill` stages **three** paths and runs the manifest/marketplace
  repair — `verbs.py:2114` returns `[target, manifest, marketplace]`, and the
  `marketplace_with_entry(...)` call at `verbs.py:2100-2103` is
  unconditional.
- The generic managed-file leg stages **one** — `verbs.py:2027`,
  `host_paths = [] if spec.variant == "local" else [spec.target]`.

Today the `skill-md` spec wins for testing-methodology (skills bucket walked
5th, user last), so the scaffold leg **never runs on recompile**.

**Ruling: the surviving spec must not change as a side effect of this
unit.** The builder keeps `setdefault`'s current key and current winner. If
a target-only key is adopted instead, the winner must be chosen
**deterministically and explicitly**, and the change must be stated in the
build report — not arrived at by reordering.

**Acceptance criterion on side effects (§9 AC#7):** for the route-9 target,
the set of paths staged by `recompile` must be exactly `[<the SKILL.md>]`,
unchanged from before the fix. A test must assert the staged-path set
directly, not infer it from V5's "nothing else moved".

Mitigating fact the builder should know: `marketplace_with_entry` returns
`(raw_text, False)` when the plugin name is already present
(`skill_scaffold.py:117-120`), so even if the scaffold leg did run, the
marketplace description would not be rewritten.

### 4.3 `_apply_new_skill`: the empty-set guard and the description seed

`verbs.py:2069-2083`:

- `records = _compile_set(home, spec)`; the guard `if not records: raise
  VerbError("no routed records name new-skill:<name> — nothing to compile")`
  now fires against the **union**. This is strictly weaker (a non-empty
  union can no longer be called empty) and is acceptable, but the error text
  says "name new-skill:<name>", which will be misleading if the union is
  empty only because everything retired. Reword to name the **target**, or
  leave it and say why in the build report.
- `description = scaffold_description(records[0])` (`verbs.py:2083`) —
  `records[0]` is the first element of whatever `_compile_set` returns.
  **NIT 13: it is NOT sorted.** §3.3 leaves ordering to `_eligible`, and
  `_routed_to` filters but never sorts (`verbs.py:625-647`), so `records[0]`
  is bucket-walk/glob order. **The in-code comment at `verbs.py:2081-2082`
  ("the compile set is already in pinned (routed_at, id) order") is false
  today** — do not trust it; correcting or deleting it is in scope as a
  comment-only edit.
  The value is only read when `plugin.json` / `SKILL.md` do not yet exist
  (the guarded block at `verbs.py:2087-2096`), and the marketplace call at
  `verbs.py:2100-2108` is also safe because `marketplace_with_entry` no-ops
  on an existing name (`skill_scaffold.py:117-120`). Confirm both with T15
  (§7.5) rather than by reading.

### 4.4 The cap consequence — expected, non-blocking, must be stated

Recompiling testing-methodology with its restored 5 entries yields
`word_count = 735` against `DEFAULT_MAX_WORDS = 150`
(`compilers.py:170-171`), so `SectionResult.over_cap` becomes `True` with
`cap_reason = "words"`. Measured, not predicted; independently re-measured
by the round-1 gate, which also confirmed all five ids survive.

Per the compiler's own contract (`compilers.py:32-36`) the entry is **still
applied** and the flag is surfaced to callers — **nothing is dropped**. The
repair in §5 will therefore print a cap/graduation warning. **That is a
correct repair, not a failure.** The builder must not add any suppression,
truncation, or cap-driven dropping in response to it; cap policy is out of
scope (§8).

---

## 5. Repair path

The fix restores canon by **re-running the existing repair**; this unit adds
no new verb.

### 5.1 Procedure

1. **Before.** Record the current state of
   `~/repos/claude-skills/plugins/testing-methodology/skills/testing-methodology/SKILL.md`:
   `git -C ~/repos/claude-skills rev-parse HEAD`, and the entry ids
   inside the marker pair via the anchored regex of §2.7. Expected: exactly
   `['lrn-0a76fae2']`.
2. **Verify the host is clean.** `recompile` skips dirty targets loudly
   (`verbs.py:4038-4046`); a dirty `claude-skills` makes the repair a silent
   skip, which would read exactly like the pre-fix no-op. Confirm clean, or
   stop.
3. **Run** `self-learn recompile --no-push` **on the fixed code**.
4. **After.** Re-read the section.

### 5.2 Verification — what "repaired" means

The repair is verified when **all** of these hold; anything less is not a
repair:

- **V1 — ids present.** The anchored entry-id scan of the section returns
  exactly, in this order:
  `lrn-4f89e33a, lrn-fe16fceb, lrn-566216a6, lrn-0529f554, lrn-0a76fae2`.
  Five entries. Not "at least five", not "the four are somewhere in the
  file" — a prose mention is not an entry (§2.7).
- **V2 — before/after diff.** `git -C ~/repos/claude-skills diff`
  (or the diff of the recompile commit) shows **+4 / -0** inside the marker
  pair, and **zero** changes outside it. The four restored lines must match
  the lines deleted by `ff45510`
  (`git show ff45510 -- <path>` gives the exact text) modulo any legitimate
  re-tightening of the record body; if any restored line differs from the
  `ff45510` deletion, that difference must be explained in the build report,
  not waved through.
- **V3 — the gate closes.** `selfcheck._check_drift(~/.self-learn)` no longer
  reports `entry marker missing` for any of the four ids. (`lrn-c826137f`'s
  unresolvable-reference failure will remain — §6.4 — so drift as a whole
  may still be red; the four named failures must be gone.)
- **V4 — idempotent.** A second `self-learn recompile --no-push` immediately
  after reports **no change** for that target. The union must be stable.
- **V5 — nothing else moved.** No other target in the §2.7 table changes.
  `recompile` touches every target; a repair that also rewrites
  `~/.claude/CLAUDE.md` or `hypr-doctor/SKILL.md` has broken something.
  Diff every host repo, not just `claude-skills`. **V5 is a backstop, not
  the side-effect check** — §4.2's staged-path criterion is the direct one.

### 5.3 Sequencing and consent

The repair writes to a host repo (`claude-skills`) that is **not** this
checkout. It runs **after** the code gate returns CLEAN, and its host commit
is the ordinary `self-learn: recompile <target>` commit the verb already
makes. `--no-push` is mandatory for the verification run. Whether to push
`claude-skills` afterwards is the operator's call, not the builder's.

---

## 6. Latent-damage sweep

The route-9 instance is the one that fired. The sweep answers: *which other
managed targets are under-compiled right now, and which are structurally
exposed?*

### 6.1 The instrument (mandatory shape)

For every target `T` and its records from the target-keyed enumeration:

- **union** = `[r.id for r in compilers._eligible(records)]`.
- **on-disk** = ids matched by `^- .*\*\((lrn-[0-9a-f]{8})\)\*\s*$`
  **compiled with `re.MULTILINE`** (NIT 9 — without the flag the pattern
  matches nothing and every target reads as empty), in order, **within**
  the `BEGIN_MARKER`…`END_MARKER` span only.
- Report `MISSING = union - on_disk` and `EXTRA = on_disk - union`, plus the
  `over_cap` / `word_count` the fixed compile would produce.

**Positive control, required before any result is believed:** the instrument
must be run once against a target known to be damaged and once against a
target known to be intact, and must distinguish them. Today's ledger
provides both for free — testing-methodology (`MISSING = 4`) and
hypr-doctor (`MISSING = 0`, union `['lrn-b85a9921','lrn-4736c04a','lrn-d399003c']`).
An instrument that reports "no damage anywhere" without having shown it can
see the known damage is worthless (this is the fail-open class: a check that
cannot see its target prints the same thing as a pass).

**Do not use a bare `lrn-` scan.** §2.7 shows it invents EXTRAs from prose.

### 6.2 What the sweep must cover

1. **Every skill `SKILL.md` under the registered skills root** — including
   skills with an empty section (chezmoi, union 0) and skills with **no
   ledger bucket at all**. A skill created purely by `new-skill` has no
   `skills/<name>/` bucket until someone files a skill-scoped lesson; the
   sweep must enumerate from the **ledger's records**, not from
   `ls ~/.self-learn/skills`, or it will not see them.
   **NIT 14 boundary:** the two enumerations differ — 12 `SKILL.md` files
   exist, 3 carry a managed section, and all 3 are record-visited, so there
   is no live blind spot. But a target that carries a managed section and
   **zero** records is structurally invisible to a record-driven sweep.
   Such targets cannot be *under-compiled* by this defect (an empty union
   compiles to an empty section, which is correct), so **EXTRA-detection on
   zero-record targets is out of scope for this unit.** State that in the
   sweep output rather than leaving it implicit.
2. **Every `claude-md` target**: `~/.claude/CLAUDE.md`, each project host's
   `CLAUDE.md`, `CLAUDE.local.md` (`local` variant), and every rules topic
   file under `~/.claude/rules/` and `<host>/.claude/rules/`. The dual-role
   union (`verbs.py:1630-1671`) is the pre-existing fix for this class;
   the sweep confirms it still holds after the change — `claude-skills` is
   registered as **both** skills root and project host in the live
   `hosts.yaml`, so this is a live configuration, not a hypothetical.
3. **`references/LEARNINGS.md` and named references targets** — these are
   **append-only** (`compilers.compile_reference`, `compilers.py:1104-1156`)
   and carry **no managed section**, so they cannot be under-compiled by
   this defect. The sweep must still confirm that by asserting no reference
   target appears in the target-keyed enumeration at all — i.e. the sweep
   reports "0 reference targets enumerated", a stated negative result, not
   silence. (**15** routed `reference` records live in
   `skills/home-assistant/` — NIT 8 correction, measured 2026-08-23; 18
   ledger-wide. If any of them showed up in a section enumeration, the
   change has leaked.)
4. **Hook targets** — verbatim script writes, no section. Same treatment as
   (3): assert absent, report the zero.

### 6.3 Expected outcome

Given §2.7, the sweep on the current ledger should report **exactly one**
damaged target before the fix (testing-methodology, `MISSING = 4`) and
**zero** after the repair. Any other `MISSING` or `EXTRA` the builder finds
is a **new** finding: report it with the target, the ids, and the mechanism.
Do not repair it silently, and do not widen this unit to fix it.

### 6.4 Found, deliberately not fixed: `lrn-c826137f`

`user/resolved/lrn-c826137f.md` carries `scope: skill:cron-claude`,
`destination: reference`, `status: routed`, and the drift check reports its
references target as **unresolvable via hosts.yaml** (§2.5). `cron-claude`
exists as a plugin in the skills root but has no ledger bucket. This is a
*reference-target resolution* defect for a skill-scoped record filed in the
user bucket — adjacent to, but not the same as, the section-enumeration
defect this unit fixes. It is **out of scope** (§8); record it in the build
report so it can be scheduled.

---

## 7. Tests

New file `cli/tests/test_xscope_enumeration.py` unless noted. All tests use
the sandbox fixtures; **none** touch `~/.self-learn` or any real host repo.

### 7.1 The fixture, and the control that proves the fixture is real

`support.make_env` (`tests/support.py:147-175`) seeds skills at
`plugins/<name>-plugin/skills/<name>` (`tests/support.py:159`), whereas the
`new-skill` scaffold targets `plugins/<name>/skills/<name>`
(`verbs.py:1062-1063`, hardcoded). **In the default sandbox the two
destinations therefore do NOT collide**, and a regression test written on it
would pass vacuously, before and after the fix.

The fixture must reproduce the live layout. The recommended construction —
which mirrors route 9's actual history — is to build it **through the verbs**:

1. Start from `test_new_skill.py`'s `Env` (`tests/test_new_skill.py:38-68`),
   which adds the `.claude-plugin/marketplace.json` that `new-skill`
   preflight requires (`verbs.py:1055-1061`).
2. Route N `user`-scope records with `--dest new-skill:tm`. This scaffolds
   `plugins/tm/skills/tm/SKILL.md` and files the records in `user/resolved/`.
3. Create a record with `scope: "skill:tm"` (which creates the
   `skills/tm/` bucket) and route it `--dest skill-md`. `skill_dir_for`
   globs `plugins/*/skills/tm` (`hosts.py:555-557`) and resolves to the
   scaffolded directory.

**T0 — the fixture control (must run first, and must be an explicit
assertion, not a comment).** Assert that the `skill-md` spec's target and
the `new-skill` spec's target `resolve()` to the **same path**. If they do
not, every test below is vacuous. This test must be written so that it would
FAIL when pointed at a `make_env`-seeded skill (`plugins/s-plugin/skills/s`)
instead of the scaffolded one — see §7.6 mutation 3.

### 7.2 Route-9 regression — the primary fixture

- **T1 — five entries, in a pinned order.** With the §7.1 fixture: after the
  `skill-md` route lands, the section contains **5** entries and the
  anchored id scan returns them in `(routed_at, id)` order.
  **MAJOR 4 — how the order is actually pinned.** `_eligible` sorts on
  `(routed_at, id)` (`compilers.py:282`); `created_at` never participates,
  and `routed_at` is stamped at second granularity (`ledger_ops.py:232`), so
  four routes inside one test land in the **same second**, tie, and collapse
  to the **id** tiebreak. The §7.1 "build through the verbs" recipe offers
  no `routed_at` hook at all. Pin the order by one of these two mechanisms,
  and say which was used:
  - **(a) Stamp `routed_at` explicitly** after routing, via the shipped
    idiom `record.set_routing({"routed_at": "…", …})` —
    `tests/test_retirement_cleanup.py:315`, `tests/test_pointer.py:91` —
    then re-read and assert the resulting order; or
  - **(b) Pin ids** via `make_behavior(record_id=…)` so the id tiebreak is
    deterministic, and assert the id-sorted order **deliberately**, with a
    comment saying the routed_at values tie.
  Do **not** write "routing order is controlled by route order" — it is not.
  Note the precedent test asserts membership only, never order
  (`tests/test_retirement_cleanup.py:439-440`); asserting order here is a
  deliberate strengthening and must be earned by (a) or (b).
- **T2 — direction symmetry.** The reverse order: route `skill-md` first,
  then a `new-skill` record into the same name. The section still contains
  both. (Pre-fix, this direction fails too — `_apply_new_skill` would drop
  the `skill-md` line.)
- **T3 — `recompile` restores.** From the T1 state, delete the four lines
  from the section by hand (mirroring `ff45510`), commit the host, run
  `verbs.recompile(..., no_push=True)`, and assert the five entries are
  back and the entry reports `changed=True`. This is the §5 repair,
  in-sandbox.
- **T4 — `recompile` is idempotent.** Immediately re-run: `not any(e.changed
  for e in result.entries)`. Mirrors
  `TestSharedClaudeMdUnion::test_recompile_preserves_union_and_is_idempotent`.
- **T5 — retirement crosses the boundary.** `verbs.graduate` one of the
  `new-skill` records; assert its line leaves the section and the other four
  remain. Then supersede the `skill-md` record; assert the same in the other
  direction. This proves §3.3's exclusion works across buckets, and that the
  fix did not turn the section into an append-only accumulator.

### 7.3 Positive controls, one per target class (mandatory)

Each asserts a section that **should** be non-empty **is** non-empty, naming
its ids — the blanking guard of §3.4(4). A count alone is not enough; assert
the ids.

- **T6 — non-colliding skill.** A skill whose only records are `skill-md`
  in its own bucket: the section keeps exactly those ids. This is the
  `hypr-doctor` shape and the direct guard against "the obvious equality fix
  blanks every skill bucket".
- **T7 — `new-skill`-only skill.** A skill with only `new-skill` records and
  **no ledger bucket**: the section keeps exactly those ids. Guards against
  a fix that enumerates from `discover_buckets` names instead of from
  records.
- **T8 — user `CLAUDE.md` through an OVERRIDE (the BLOCKER-1 guard).**
  Route user-scope `claude-md` records with an explicit
  `user_claude_md=<tmp_path/CLAUDE.md>` override — the shipped idiom at
  `tests/test_retirement_cleanup.py:274-275` and `tests/test_verbs.py:316`.
  Assert:
  1. the section lands in the **override** file with exactly those ids —
     non-empty, ids named;
  2. `~/.claude/CLAUDE.md` (the real one) is **never read or written** by
     the test — monkeypatch/assert rather than hope;
  3. a second route to the same override file **preserves** the first
     record's line (the blanking symptom is that it does not);
  4. no skill- or project-scope record leaks into it.
  Add the same assertion for the **`rules` variant** at user scope, whose
  target derives from the override too (`_user_rules_dir(...)`,
  `verbs.py:753` / `selfcheck.py:246`).
  **This is the test that would have caught the resolver-parameterization
  blanking. It is not optional.**
- **T9 — project `CLAUDE.md`.** Same, for a project host; and the
  dual-role union is unaffected: `tests/test_retirement_cleanup.py::TestSharedClaudeMdUnion`
  (three tests, `tests/test_retirement_cleanup.py:418-456`) must pass
  **unmodified**. Do not edit that class.
- **T10 — rules/local partition.** A `rules:<topic>` record, a `local`
  record and a plain `claude-md` record at the same scope keep three
  distinct, non-empty, non-overlapping sections.
  `tests/test_a2_rules_local.py` already covers this class; assert it stays
  green and add a targeted case only if the existing coverage does not
  exercise a colliding skill in the same sandbox.
- **T11 — empty is still empty.** A skill whose only record is superseded
  compiles to a **zero-entry** section (the chezmoi shape) — the fix must
  not resurrect retired entries.

### 7.4 Negative controls and selfcheck parity

- **T12 — references untouched.** A `reference`-routed record in a skill
  that also has a section: its id appears in `references/LEARNINGS.md` and
  **not** as an entry line in the section; the section's id set is unchanged
  by the reference route.
- **T13 — hooks untouched.** A `hook`-routed record does not appear in any
  section.
- **T13b — selfcheck parity (the §3.2.1 normalization guard).**
  `selfcheck._section_targets` must return the **same target set** after the
  delegation as before, compared **as resolved paths**, and
  `_check_compiler` / `_check_markers` / `_check_drift` must return the same
  verdicts on a sandbox ledger. This is the test that catches a
  normalization mismatch between the resolver's return value and
  `_section_targets`' dict keys.

### 7.5 Apply-path parity

- **T14 — P3 parity.** Construct both `TargetSpec`s for the colliding target
  and assert `_compile_set` returns the identical id list for both (§4.1 P3).
- **T15 — scaffold not re-seeded.** After T1, both
  `plugins/tm/.claude-plugin/plugin.json` **and**
  `.claude-plugin/marketplace.json` are byte-identical to what the first
  `new-skill` route wrote, even though `records[0]` may now be a different
  record (§4.3; NIT 10 — the marketplace path must be asserted too, not just
  the manifest).
- **T15b — staged-path set (the §4.2 / MAJOR 6 criterion).** For the
  route-9 target, assert `recompile` stages exactly `[<the SKILL.md>]` —
  not the three-path scaffold set. Assert the set directly.
- **T16 — no NEWLY-INTRODUCED scope-equality predicate.** A structural guard
  over the target-derivation path only, with the three whitelisted sites of
  §3.4(1) — `verbs.py:1662`, `verbs.py:1665`, `selfcheck.py:215` —
  **excluded by name**, so the guard is green on correct, mandated-to-survive
  code (MAJOR 3). Scope it to the new resolver and the new `_compile_set`
  body.
  Per `lrn-fe16fceb`'s rule, assert on what the **defect** must introduce
  (the comparison), not on what correct code happens to have; prefer an AST
  walk over a regex, and **verify the guard by reproducing the defect** —
  temporarily insert such a comparison into the resolver and confirm the
  guard goes RED. If a guard that is simultaneously green on the whitelist
  and red on the defect cannot be written, **drop T16 and say so** in the
  build report; do not ship a green-by-construction text match.

### 7.6 Mutation verification (for the code gate)

The code gate must confirm these tests can fail. At minimum:

1. Restore `verbs.py:1610` to `_routed_to([spec.bucket_dir], "skill-md")` →
   **T1, T3, T7, T14 must go RED.**
2. Force `_compile_set` to return `[]` for skill targets → **T1, T6, T7, T11
   must go RED** (T11 by asserting the *ids*, not merely emptiness — if T11
   passes under a blanking mutation it is testing nothing).
3. **(NIT 15 replacement — the old "revert the fixture layout" mutation is
   not an available edit, since the scaffold path is hardcoded at
   `verbs.py:1062-1063`.)** Point T0 at a `make_env`-seeded skill
   (`plugins/s-plugin/skills/s`) instead of the scaffolded one → **T0 must
   go RED.**
4. **(new, B1)** Drop the `user_claude_md` parameter from the shared
   resolver so it falls back to `DEFAULT_USER_CLAUDE_MD` → **T8 must go
   RED.**
5. **(new, M5)** Return an unresolved path from the resolver while keeping
   resolved lookup keys (or vice versa) → **T13b must go RED.**

### 7.7 Suite

`cd plugins/self-learn/cli && uv run pytest` must be green (CLI suite), and
`uv run --project plugins/self-learn/ui pytest` must be green apart from the
one known pre-existing failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`).
Subagent test runs are foreground-only.

---

## 8. Out of scope

Report, do not edit:

- **Routing gates.** `_resolve_target`'s preflight refusals — dirty-target
  aborts, unregistered/unsound hosts, the M3-9 foreign-plugin collision
  refusal (`verbs.py:1064-1077`), the `--allow-empty-glob` bypass. This unit
  changes which records are compiled, never whether a route is allowed.
- **Cap logic.** `DEFAULT_MAX_ENTRIES` / `DEFAULT_MAX_WORDS`, `over_cap`,
  `cap_reason`, graduation cards, and the whole cap-rework sequence. §4.4's
  `over_cap = True` after repair is an expected, reported outcome — not a
  problem to solve here. No truncation, no suppression, no threshold change.
- **The analyst / miner / worker.** No proposal logic, no destination
  *selection*, no decision table, no SDK invocation surface.
- **`lrn-c826137f`'s unresolvable reference target** (§6.4) — a different
  defect, recorded for scheduling.
- **The drift check's substring matcher.** `selfcheck.py:563` tests
  `f"({record.id})" not in section`, a bare substring rather than the
  anchored entry form of §2.7. It happens to be correct on today's data.
  Note it; do not change it in this unit.
- **`reference` / `hook` compilation.** Append-only and verbatim
  respectively; untouched.
- **Every line of `selfcheck.py` except its import line and the body of
  `_target_for`.**
- **Any write to `~/.self-learn`.** The ledger is read-only for this unit,
  including its tests.
- **Pushing `claude-skills`.** The repair runs with `--no-push`; publishing
  is the operator's decision.

---

## 9. Acceptance criteria

1. The shared resolver `managed_target_for` exists **in `verbs.py`**, takes
   `user_claude_md`, and is the **only** implementation of §3.1's table.
   `selfcheck._target_for` delegates to it and keeps no parallel body. If a
   deferred in-function import was used anywhere, it carries the
   `# local: avoids a module cycle` comment and is justified in the build
   report.
2. `_compile_set` satisfies P1–P5 of §4.1, threading the `user_claude_md`
   context.
3. No **newly introduced** comparison between a record's `scope` frontmatter
   and a bucket's `scope`/`name` appears on the target-derivation path
   (§3.4(1)). The three whitelisted sites — `verbs.py:1662`,
   `verbs.py:1665`, `selfcheck.py:215` — are **unchanged**.
4. Normalization happens at exactly one point (§3.2.1): the resolver returns
   resolved paths, and no caller re-normalizes or compares unresolved paths.
5. Tests T0–T15b exist and pass; T16 exists or its omission is justified in
   writing. The five mutations of §7.6 are shown to turn the named tests RED.
6. `tests/test_retirement_cleanup.py::TestSharedClaudeMdUnion` passes
   **unmodified**, and `tests/test_a2_rules_local.py` stays green.
7. The staged-path set for the route-9 target under `recompile` is exactly
   `[<the SKILL.md>]`, asserted directly (§4.2). If the surviving spec was
   changed, that change is stated explicitly in the build report.
8. Both suites are green per §7.7.
9. The §5 repair has been run and V1–V5 all verified, with the before/after
   diff quoted in the build report.
10. The §6 sweep has been run with its positive control shown, and its
    results — including the stated zeros for reference and hook targets and
    the §6.2(1) zero-record-target boundary — are in the build report.
11. `over_cap = True` on the repaired testing-methodology section is
    reported, not suppressed.
