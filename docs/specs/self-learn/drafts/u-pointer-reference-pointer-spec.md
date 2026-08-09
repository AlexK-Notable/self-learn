# Spec — U-pointer: reference-route pointer emission, the ALWAYS-surface write, and the R14 backfill

Status: **r2 — one blind gate round folded, awaiting delta re-check.**
r1 gate verdict: **UNSOUND — 2 BLOCKER / 5 MAJOR / 5 NOTE**, all twelve
folded here (§9). The gate verified ~35 `file:line` citations and
reproduced all eleven r1 measurements intact; **the design survived and
the register did not**. Four of r1's twenty-six mutations did not do
what r1 claimed, and the two BLOCKERs are both of one kind: **a
criterion that cannot fail**, which is this project's signature defect
appearing in the instrument written to prevent it. r2 adds **seven
criteria** (A8, A9, B5, E7, E8, F7, F8), rewrites six (B1, B2, C7, D2,
D3, G1), adds **five mutations** (M27-M31), and adds **four
measurements** (§8a) — and where a claim genuinely cannot be pinned
behaviourally, says so in the criterion instead of pretending coverage.
Unit `U-pointer`, the last unfixed finding of the 2026-07-27 routing
audit, addressing **FW-40**
(`docs/specs/self-learn/14-forward-work-map.md:95`) and the §2 unit-table
row of `docs/specs/self-learn/forward/r2-routing-campaign.md:89`
("Pointer emission, cap-exempt; reference-route triggers an ALWAYS
recompile | `compilers.py`, `verbs.py` | FW-40").

**Base commit:** `c8dcaf3` (master, the U-repair merge). Every `file:line`
citation below was read at that tree and re-checked while writing.

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/compilers.py` | the pointer block, its markers, the token computation, `apply_pointer`; receives `surface_names_target` (moved, see §3.10) |
| `plugins/self-learn/cli/src/self_learn/verbs.py` | thread the ALWAYS surface onto `TargetSpec`; the route apply leg; the commit gate; the recompile/backfill leg; the two preflight refusals |
| `plugins/self-learn/cli/src/self_learn/selfcheck.py` | **three lines only** — delete `_TOKEN_DELIMS` + `_surface_names_target`, import the moved function under the same private name (§3.10). Any other edit to this file is out of scope |
| `plugins/self-learn/cli/tests/test_pointer.py` | new; the unit's own tests |
| `plugins/self-learn/cli/tests/test_compilers.py`, `test_selftest.py`, `test_hosting*.py`, `test_lock_invariant.py` | only where an existing assertion must absorb a *declared* behaviour change (§3.9, §6-D8) |

Anything else is out of scope and must be **reported, not edited**.

---

## 0. Reading order and precedence

1. `docs/specs/self-learn/drafts/u-reach-reachability-selftest-spec.md` —
   the shipped detector and **the one hard interface clause** (§2.1).
   This spec must satisfy its *semantics*; it must not couple to any
   anchor text, because u-reach explicitly refused to give it one.
2. `docs/specs/self-learn/03-decisions.md` **S-23** (`:37`) — `reference`
   survives at skill/project scope and gets its pointer; user scope
   REFUSES `reference` and **that refusal stays**.
3. `docs/specs/self-learn/forward/r2-routing-campaign.md` §2 (the unit
   row), §4 Checkpoint B, §5 (positive controls; the pinned-algorithm
   rule this spec's §8 exists to satisfy).
4. This document. Where prose and §4/§5 conflict, **§4 and §5 win** —
   they are the normative register, and everything else is explanation.

---

## 1. The defect

### 1.1 The measured state — R14

Fourteen live records carry `routing.destination: reference`. Their
lesson text is on disk, in a references file, in a git repo. **No loaded
surface anywhere names that file**, so no session can reach any of them.
The pre-fix positive control is captured, unpiped, `rc=1`:

```
selftest: 1 of 7 checks FAILED
selftest: FAIL reach — 14 of 14 reference-routed record(s) unreachable:
  lrn-01865691: not named by its loaded surface
  (<skills-root>/plugins/home-assistant/skills/home-assistant/SKILL.md)
  — write a resolving pointer to
  <skills-root>/plugins/home-assistant/skills/home-assistant/references/LEARNINGS.md
  ; …13 more, same surface, same target
```

(`misc/evidence-2026-08-08-worker-maiden/u-pointer-precontrol-selftest.txt`
— **read-only, git-ignored, local to this host**; absolute paths elided
above because this repo is public.)

Two facts to carry forward from that capture:

- **All 14 share one surface and one target.** They belong to a single
  skill. The backfill is therefore *small*, and the check that closes it
  is a single number: `FAIL reach — 14 of 14` must become
  `PASS reach — 14 reference-routed record(s) reachable…`.
- **That surface has no managed section at all.** `SKILL.md` for
  `home-assistant` was never a compile target; the detector was
  deliberately built to scan the whole file for exactly this reason
  (`selfcheck.py:329-353` docstring). **The emitter inherits that
  constraint**: it cannot ride the managed-section machinery, because
  `compile_managed_file` refuses a missing target
  (`compilers.py:314-318`) and `compile_managed_text` would *bootstrap a
  marker pair into a file self-learn does not manage*
  (`compilers.py:266-271`).

### 1.2 Why the route cannot deliver — the three missing links

| # | Link | Where it breaks today |
|---|---|---|
| 1 | Nothing computes the ALWAYS surface at route time | `_resolve_target`'s reference branch (`verbs.py:1071-1106`) resolves `refs_dir`, `ref_name` and a `host`, sets `TargetSpec.target = None`, and never derives `SKILL.md` / `CLAUDE.md` at all |
| 2 | Nothing writes a pointer | `_apply_target`'s reference leg (`verbs.py:1881-1887`) has exactly one write: `compile_reference(spec.refs_dir, record, dest=spec.ref_name)` |
| 3 | The repair verb cannot heal it | `recompile`'s reference leg (`verbs.py:3994-4043`) re-appends record entries and commits `probe` alone; and it `continue`s past the commit entirely when nothing was appended (`:4028-4033`) — which is precisely the R14 state, where all 14 entries are *already* in the file |

Link 3 is why the backfill is not a script: **the repair verb already
visits every stranded record and already declines to do anything.**

### 1.3 What is *not* the defect

- **Not the references compiler.** `compile_reference`
  (`compilers.py:815-867`) writes the right bytes to the right file, is
  record-id idempotent (`:858-862`), and has no cap. It stays unchanged
  except for one added field on its result type (§3.6).
- **Not the detector.** `_check_reach` (`selfcheck.py:367-471`) and
  `_surface_names_target` (`:329-364`) are correct and are treated here
  as the **oracle**, not as code to adjust. If a pointer this unit emits
  does not satisfy them, the pointer is wrong.
- **Not the user-scope refusal.** `verbs.py:1087-1096` stays
  byte-identical (S-23 (2); criterion **F1**).
- **Not the UI.** See §7.2.

---

## 2. What binds this design from outside it

**B1 — the interface clause, verbatim** (u-reach, §"on the contract"):

> the pointer must contain a path token that resolves to the demand file.

Operationally, and this is the only definition this unit may use: after
the emitter has run, `surface_names_target(surface, target)` — the
shipped predicate — returns `True`. Not "the block was written", not
"the text contains the basename". **The post-condition is the contract**
(§3.3, criterion **A3**).

**B2 — the detector is anchor-free by design.** u-reach refused to
require any heading, sentence or marker. Consequences the emitter must
respect: (i) a hand-written pointer already in the file *satisfies the
contract*, so the emitter must not add a second one (§3.5); (ii) the
emitter may choose its own wording freely, because no wording is load-
bearing for the check — the *token* is.

**B3 — S-23.** `reference` survives at skill and project scope; user
scope refuses it. `paths:`-scoped rules, not this, are the primary cheap
tier. This unit makes the surviving tier deliver; it does not promote it.

**B4 — reference targets are append-only.** Stated three times in the
code: `verbs.py:1882-1883` ("reference targets are append-only —
nothing to apply"), `verbs.py:3869-3872` ("a retired entry stays; there
is nothing to regenerate or repair"), and the `LEARNINGS.md` header
itself (`compilers.py:134-140`). **The pointer inherits this**: it is
inserted, never removed, never re-sorted (§6-D3).

**B5 — the campaign row's two words.** *"cap-exempt"* → §3.8.
*"reference-route triggers an ALWAYS recompile"* → §3.4, which also
records what that phrase must **not** be read as.

**B6 — Checkpoint B.** The 14→0 transition is this unit's gate. The
second half of Checkpoint B — *does a session actually open that file at
the right moment?* — is **out of scope and stays unmeasured**; the only
lever this unit has on it is the block's preamble wording, which is
declared as a residual in §7.3, not claimed as a fix.

---

## 3. The change

### 3.1 P-BLOCK — the pointer block (NORMATIVE)

New constants in `compilers.py`, beside the existing marker pair
(`:123-124`):

```python
POINTER_BEGIN_MARKER = (
    "<!-- self-learn:pointers:begin (do not hand-edit inside; managed by self-learn) -->"
)
POINTER_END_MARKER = "<!-- self-learn:pointers:end -->"
```

The block, emitted exactly once per surface:

```
<!-- self-learn:pointers:begin (do not hand-edit inside; managed by self-learn) -->
## Reference material (self-learn)

Captured lessons that are NOT loaded into this context. Read the file whose
subject matches what you are about to do, before you start.

- `references/LEARNINGS.md` — captured lessons for this skill
<!-- self-learn:pointers:end -->
```

Pinned properties, each with its reason:

1. **Its own marker pair, distinct from the managed section's.** Measured
   (§8-X3): neither pointer marker contains `BEGIN_MARKER` or
   `END_MARKER` as a substring, so
   `compile_managed_text`'s `target_text.count(BEGIN_MARKER)` arithmetic
   (`compilers.py:263-264`) and `selfcheck._check_markers`'
   (`selfcheck.py:706-714`) are both unaffected. A surface may carry a
   managed section **and** a pointer block; measured that the section
   regenerates with the pointer block byte-identical (§8-X4).
2. **Appended at EOF when absent**, with exactly one blank line before it
   and a trailing newline — the same shape `compile_managed_text` pins
   for its own bootstrap (`compilers.py:266-271`). Position is
   semantically irrelevant (the detector scans the whole file); EOF is
   chosen because it is the least invasive place in a file a human owns.
3. **One `- ` line per reference file.** A surface with two reference
   files gets two lines in one block; measured that both resolve (§8-X8).
4. **Line grammar:** ``- `<token>` — <label>``. The backticks are
   deliberate: `` ` `` is in the detector's `_TOKEN_DELIMS`
   (`selfcheck.py:326`), so it terminates the leftward token scan
   cleanly. The em dash and the label are free text and are **never
   parsed back** (§6-D3).
5. **`<label>`** is `captured lessons for this skill` (skill scope) or
   `captured lessons for this project` (project scope), threaded from
   the caller — the compiler never infers scope.
6. **Broken markers refuse.** `0/0` → bootstrap; `1/1` → insert; anything
   else, or end-before-begin, raises `CompileError` naming the counts —
   mirroring `compilers.py:283-287` and `:275-278` exactly.

### 3.2 T-TOKEN — the path token (NORMATIVE)

```python
def pointer_token(surface: Path, target: Path) -> str:
    rel = os.path.relpath(target, surface.parent)
    if not rel.startswith(".."):
        return Path(rel).as_posix()
    try:
        return "~/" + Path(target).relative_to(Path.home()).as_posix()
    except ValueError:            # target is not under $HOME
        return str(target)
```

**r2 correction (NOTE 12).** An earlier draft wrapped `os.path.relpath`
in `try/except ValueError`. That is **dead code on this platform** —
`relpath` raises only across Windows drive letters; measured on POSIX,
`os.path.relpath("/a/b", "/c/d")` returns `"../../a/b"` (§8-X14). It is
removed rather than justified: an unreachable except clause is exactly
the shape a later reader mistakes for a handled case. The surviving
`except ValueError` on `relative_to` **is** live — that is how "not under
`$HOME`" is detected.

Reasons, in order of the branch:

- **Relative, against `surface.parent`.** The detector resolves a
  relative token against the surface's parent (`selfcheck.py:361`), so
  this is the form the contract is defined in. It is also the only form
  that survives being committed to a host repo: the surfaces this writes
  into (`SKILL.md` in a skills repo, a project `CLAUDE.md`) are pushed,
  shared, and cloned onto other machines, and an absolute `/home/<user>/…`
  token would be both a home-path leak and dead on arrival elsewhere.
  In both live scopes the token is exactly `references/<basename>`
  (measured, §8-X1/X2).
- **`..` disqualifies the relative form.** A lexical `relpath` that
  escapes upward stops being safe the moment a symlink sits in
  `surface.parent`. Reachable only via an **absolute** `--dest`, which
  `reference_target_path` accepts (`compilers.py:809-812`) and which can
  therefore put the target outside the surface's subtree.
- **`~`-form before a bare absolute.** Same leak argument; the detector
  `expanduser`s (`selfcheck.py:360`). Both forms measured resolving
  (§8-X10).
- **`as_posix()`** so no backslash can ever enter a token.

### 3.3 The `compilers.py` API (NORMATIVE)

```python
@dataclass(frozen=True)
class PointerResult:
    surface: Path
    target: Path
    token: str            # the token written, or the one already present
    changed: bool         # the surface file was rewritten
    created: bool         # the surface file did not exist and was created
    bootstrapped: bool    # the pointer block was absent and got appended

def pointer_token(surface: Path, target: Path) -> str: ...
def pointer_line(token: str, label: str) -> str: ...
def compile_pointer_text(surface_text: str, line: str) -> tuple[str, bool]: ...
def apply_pointer(surface, target, *, label: str, create: bool = False) -> PointerResult: ...
```

`compile_pointer_text` returns **`(new_text, bootstrapped)`** — the bool
reports whether the block was ABSENT and had to be appended at EOF, the
same thing `SectionResult.bootstrapped` reports (`compilers.py:158`).
It is **not** a `changed` flag: this function is only ever called when
the caller has already decided a write is owed, so `changed` would be a
constant `True` and therefore worthless. Named explicitly because an
unnamed second element of a tuple is where a builder guesses (NOTE 12).

**Insertion order (NORMATIVE, NOTE 12).** A new line is appended as the
**last** line inside the block, immediately before `POINTER_END_MARKER`,
preserving the order in which targets were first routed. Never sorted,
never prepended — §6-D3 rules out re-sorting, and "last" is the only
order that needs no knowledge of the lines already there.

`apply_pointer`, in order — this ordering is normative:

1. `surface` is not a file → `create` is True: `mkdir(parents=True)` +
   `write_text("")`, `created=True`. `create` is False: raise
   `CompileError` naming the surface, mirroring
   `compile_managed_file`'s refusal (`compilers.py:314-318`).
2. `surface_names_target(surface, target)` is True → return
   `changed=False`, `token=pointer_token(...)`, **no write at all** (B2).
3. Otherwise compute the token, build the line, `compile_pointer_text`,
   write, `changed=True`.
4. **Post-condition, mandatory.** Re-read the file through
   `surface_names_target(surface, target)`. If it is False, raise
   `CompileError` naming surface, target and token. This is not
   belt-and-braces: it is the one place where "we wrote something" is
   converted into "the contract holds", and this project's signature
   defect is a check that passes while seeing nothing. It costs one file
   read per changed route.

   **r2 (MAJOR 4): it needs its own test, because no other criterion
   reaches it.** The §5 invitation to break the post-condition and see
   whether anything reddens was taken up at the gate, and nothing did:
   under M2/M3 the A-criteria fail on the *token comparison* first, so
   the post-condition only ever changes the failure MODE, never the
   verdict. A guard that no test distinguishes from its own absence is
   decoration. Criterion **A8** covers it by monkeypatching
   `pointer_token` to emit a deliberately non-resolving token and
   asserting the raise.

`compile_pointer_text` is pure (no I/O), like `compile_managed_text`, so
the block arithmetic is unit-testable without a host tree.

### 3.4 Surface derivation, threading, and what "ALWAYS recompile" means

`TargetSpec` (`verbs.py:645-668`) gains one field:

```python
pointer_surface: Path | None = None   # reference destination only
```

Set in `_resolve_target`'s reference branch (`verbs.py:1071-1106`), where
both facts are already in hand:

| scope | `refs_dir` (today) | `pointer_surface` (new) |
|---|---|---|
| `skill:<name>` | `skill_dir / "references"` | `skill_dir / "SKILL.md"` |
| `project` | `host / "references"` | `host / "CLAUDE.md"` |
| `user` | — | — (refused before this point, `verbs.py:1087-1096`) |

This table is **the same derivation** `selfcheck._loaded_surface` makes
from the other side (`selfcheck.py:311-318`), reached by a different
route: `skill_dir_for(hosts, name)` in both cases (`hosts.py:546-566`,
via `_hosts_skill_dir` at `verbs.py:686-695`), and the recorded project
host in both cases (`bucket_project_path`, via `_project_host_or_refuse`
at `verbs.py:698-717`). Two derivations of one rule is the drift wart
this file already carries a scar from (`verbs.py:1097-1100`, audit
2026-07-16 MINOR 7), so criterion **C1** pins the agreement directly
rather than trusting it.

**What "a reference route triggers an ALWAYS recompile" means, and what
it must not be read as.** It means: *the always-loaded surface is
written on a reference route.* It does **not** mean calling
`compile_managed_file` / `compile_managed_text` on that surface. A build
that reads it the second way is wrong in three separate ways, all live:
(a) it refuses outright when the surface is missing
(`compilers.py:314-318`); (b) on `home-assistant`'s `SKILL.md` — the
file all 14 stranded records need — it would **bootstrap an empty
managed marker pair into a file self-learn does not manage**
(`compilers.py:266-271`); (c) the compile set for that surface is the
set of `claude-md`/`skill-md`-routed records, which a reference route
knows nothing about, so a wrong set would *delete* entries. **This unit
must never call the managed-section compilers on `pointer_surface`**
(criterion **B4**).

### 3.5 The route path

`_apply_target`'s reference leg (`verbs.py:1881-1887`) becomes:

```python
elif spec.destination == "reference":
    if routed_record is None:                       # unchanged, byte-identical
        raise VerbError("reference targets are append-only — nothing to apply")
    compile_result = compile_reference(spec.refs_dir, routed_record, dest=spec.ref_name)
    host_paths = [compile_result.path]
    if spec.pointer_surface is not None:
        pointer = apply_pointer(
            spec.pointer_surface,
            compile_result.path,
            label=POINTER_LABELS[spec.scope_kind],
            create=spec.scope_kind == "project",
        )
        if pointer.changed:
            compile_result = replace(compile_result, pointer_changed=True)
            host_paths.append(spec.pointer_surface)
            if notes is not None:
                notes.append(f"reference pointer written to {spec.pointer_surface}")
```

Pins:

- **The pointer's target is `ReferenceResult.path`**, the file
  `compile_reference` actually wrote — never a re-derived probe. *No
  mutation is offered for this*, and the spec says so rather than
  inventing one: the two are equal by construction today, because
  `reference_target_path` (`compilers.py:801-812`) is the one mapping
  both use. The pin exists so that a future divergence cannot silently
  produce a pointer to a file nothing was written to.
- **`create` is True only at project scope.** An absent project
  `CLAUDE.md` is already created empty by this same function for
  `claude-md` routes (`verbs.py:1926-1931`), so this is the established
  posture, not a new liberty. An absent `SKILL.md` is a different animal:
  it is a **manifest** with required frontmatter, and writing an empty
  one fabricates a broken plugin. Self-learn already refuses to touch a
  plugin it did not scaffold for this exact reason
  (`verbs.py:1049-1062`). Skill scope therefore refuses at preflight
  instead — §3.9.
- **`replace` is already imported** in `verbs.py` (used at `:1947`).
- **`POINTER_LABELS`** is a two-entry dict in `verbs.py` keyed by
  `scope_kind` (`"skill"` / `"project"`).

`_resolve_target` gains **three** preflight refusals alongside the
existing `_abort_if_dirty(host, probe)` (`verbs.py:1102-1103`) — L2
(skill-scope surface missing), L4 (surface dirty) and L5 (surface
undecodable), all **before** the ledger commit, per E-17. All three are
**gated on `check_dirty`**; see §3.7 for why that gating is load-bearing
and not merely a naming convention. (r2, NOTE 8: an earlier draft said
"two" here while §3.9 declared three — the register was complete, the
prose count was not.)

### 3.6 The commit gate — the fold that decides whether any of this lands

`ReferenceResult` (`compilers.py:165-172`) gains
`pointer_changed: bool = False`. It is defaulted, so neither existing
construction site (`compilers.py:862`, `:867`) changes.

`_host_phase`'s gate (`verbs.py:2096-2108`) reads today:

```python
changed = getattr(compile_result, "changed", None)
applied = getattr(compile_result, "applied", None)
if changed is not False and applied is not False:
```

`ReferenceResult` has no `changed`, and `applied` is **False whenever the
record id was already in the file** (`compilers.py:858-862`). So a route
whose reference append is a no-op **but whose pointer was just written**
would skip the commit and leave the pointer written-but-uncommitted —
the U-pathed "changed fold" hazard (`verbs.py:1940-1947`) one destination
over. Required change:

```python
pointer_changed = bool(getattr(compile_result, "pointer_changed", False))
if pointer_changed or (changed is not False and applied is not False):
```

Behaviour for every other destination is byte-identical, because
`pointer_changed` is False everywhere else (criterion **D2**).

**`cli.py` needs no change, and must not receive one.** The obvious
worry is `_reports_no_change` (`cli.py:989-1003`), which reads
`not compile_result.applied` for a `ReferenceResult` and would call a
pointer-writing route a `no_op`. It cannot: `_outcome_state`
(`cli.py:1040-1041`) tests `host_commit_sha is not None` **first** and
returns `"landed"`, before `_reports_no_change` is consulted at `:1044`;
and the gate above guarantees a sha exists exactly when the pointer
changed. The only path that reaches `_reports_no_change` is "entry
already present **and** pointer already present" — which really is a
no-op. Recorded so a builder does not "fix" a surface governed by its
own shipped spec.

**r2 (MAJOR 3) — how that claim is pinned, since a behavioural test
cannot pin it.** The gate showed the obvious mutation ("helpfully" teach
`_reports_no_change` about `pointer_changed`) reddens **nothing**: leg
(i) is unreachable behind the `:1040-1041` short-circuit, and on the
both-present fixture every plausible edit evaluates identically to the
unmutated function. So the short-circuit itself is the load-bearing
fact, and the criterion is written to assert **exactly that**: D3 pins
the `cli.py` region byte-unchanged and pins the short-circuit's ordering
directly, rather than pretending a behavioural probe covers it. This is
a case where the honest register entry is "asserted structurally,
because behaviour cannot see it".

### 3.7 The recompile path — which *is* the backfill mechanism

No new verb, no script. `recompile` already enumerates every
reference-routed record and resolves its `TargetSpec`
(`verbs.py:3868-3908`), so `spec.pointer_surface` arrives for free. The
reference leg (`verbs.py:3994-4043`) changes as follows:

1. **Before the lock**, alongside the existing `probe` dirty check
   (`:3997-4004`): if `spec.pointer_surface` exists and is dirty
   (`gitops.paths_dirty`), record a `RecompileEntry(target=surface,
   changed=False, skipped="dirty")` + a warning, and set a local
   `skip_pointer` flag. **The record appends still proceed** — the two
   repairs are independent, and a human's uncommitted edit to `SKILL.md`
   is no reason to withhold canon from `LEARNINGS.md`.
2. **Inside the existing `commit_lock(host_repo)`**, after the append
   loop and *before* the `if not applied: continue` at `:4028-4033`:
   call `apply_pointer(...)` with `create=(spec.scope_kind == "project")`,
   wrapped in **`try/except (CompileError, OSError, UnicodeDecodeError)`**
   → warning + treat as unchanged (recompile never crashes a batch on one
   host, `:4023-4026`).

   **r2 (BLOCKER 2) — the third member is not optional, and an earlier
   draft omitted it.** `UnicodeDecodeError` is a **`ValueError`, not an
   `OSError`** (measured, §8-X13), and `surface_names_target` reads the
   surface with `read_text` (`selfcheck.py:356`). With the two-member
   tuple this spec first pinned, one undecodable `SKILL.md` propagates
   out of the `ref_work` loop, out of `recompile()` (nothing intervenes
   but `finally: hold.release()` at `verbs.py:4114-4115`), and **aborts
   the entire nightly repair batch** — every later host silently
   unrepaired. That contradicts this spec's own D7 and the H-3 rule it
   cites. The shipped detector already treats this class explicitly and
   separately (`selfcheck.py:446`), which is the precedent. Criterion
   **E7** covers it; there was no criterion in r1.

   *Recorded, not fixed here:* `_HOST_PHASE_ERRORS`
   (`verbs.py:2045-2052`) has the same gap. It is unreachable while L5's
   preflight decode check stands (F5), so widening it is out of this
   unit's footprint — but if a later unit relaxes that preflight, the
   route path inherits the same shape.
3. **The commit gate becomes `if not applied and not pointer.changed:
   continue`**, and the two files get **one commit each**, both inside
   the same lock:
   - `applied` → stage `[probe]`, subject
     `self-learn: recompile <rel probe>` — *unchanged from today, byte
     for byte*;
   - `pointer.changed` → stage `[surface]`, subject
     `self-learn: pointer <rel surface>`, plus its own
     `RecompileEntry(target=surface, changed=True, commit_sha=…)`.

   **And on any commit, append `host_repo` to `touched_hosts` if absent**
   — the same two lines every other leg already carries (`:3989-3990`,
   `:4042-4043`, `:4105-4106`). `touched_hosts` is what the push loop at
   `:4109-4113` iterates; a restructured leg that drops it leaves the
   **entire backfill committed locally and never pushed**, which looks
   exactly like success from `recompile`'s own output (r2, NOTE 9;
   criterion **E8**).

   **Commit topology, stated because route and recompile deliberately
   differ (r2, NOTE 10).** The *route* path commits both files under one
   subject naming only the references file (`verbs.py:2103-2108` derives
   `rel` from `host_paths[0]`), because a route is **one human decision**
   producing one atomic canon change, and `_host_phase` is generic across
   all six destinations — special-casing its subject line for one
   destination would be the wrong seam. The *recompile* path splits,
   because its two repairs are **independent** (either can fire without
   the other, and E5 requires the appends to proceed when the pointer is
   skipped) and its subject line names exactly one relative path by
   existing convention. Same rule, different unit of work: **one commit
   per decision at route, one commit per independent repair at
   recompile.**

**This is the whole backfill.** For R14: all 14 entries are already in
`LEARNINGS.md`, so `applied` is False, the old code `continue`d, and the
new code writes one pointer line into one `SKILL.md` and commits it. The
operational run against the real ledger is a **user-executed step after
merge** and is deliberately not part of this spec's acceptance —
criteria **E1-E5** prove the mechanism against fixtures only.

### 3.8 Cap exemption — where it lives, so it cannot rot

The campaign row says "cap-exempt". The exemption is **structural, not a
flag**: the pointer is not an entry and never passes through
`_eligible` (`compilers.py:229-234`), `entry_line` (`:211-220`) or
`compile_managed_text` (`:240-297`). There is no counting code path that
can reach it, so there is no predicate to forget to update. `over_cap` /
`cap_reason` / `word_count` / `entry_count` are computed from `entries`
alone (`:252-261`), and `entries` is derived from records.

**r2 (BLOCKER 1) — the argument above is sound and r1's criterion for it
was worthless. Both halves matter.** The counts are derived
**exclusively** from the `records` argument (`:252-261`); `target_text`
enters only the marker arithmetic at `:263-264`. That is *why* the
exemption is structural — and it is also why "assert `entry_count` is
unchanged" **cannot fail**, for any build, ever. Measured (§8-X12): a
build that emits the pointer line INSIDE the managed markers reports
`entry_count=1, word_count=10, over_cap=False, cap_reason=None` —
**identical** to the correct build. r1's B1 compared two numbers that
are blind to the thing it was checking.

**And the damage that criterion was supposed to catch is worse than a
miscounted cap — it is latent.** Measured on the same fixture: a
pointer emitted inside the managed markers satisfies
`_surface_names_target` **immediately after the route** (`True`), so the
selftest goes 14→0 and the unit ships looking correct; the **next**
`claude-md` route to that surface regenerates the section from records,
the pointer line is not an entry, and it is **silently deleted** —
`_surface_names_target` then returns `False` and the records are
re-stranded, with no error anywhere. A wrong build here does not fail
loudly at build time; it fails months later, invisibly, in exactly the
way FW-40 already failed once.

So the register changes shape: **B1 asserts what the emitter actually
controls** (the pointer marker is present after `apply_pointer`, and the
managed-marker count is unchanged by it), **B2's fixture must be
produced by calling `apply_pointer`** rather than hand-written (a
literal fixture is blind to every emitter mutation), and a new
end-to-end criterion **B5** routes a reference, regenerates the managed
section, and re-asserts `_check_reach` — the only criterion that can see
the latent wipe. `DEFAULT_MAX_ENTRIES = 10` (`:127`) still appears in
B1's second leg, now as a *regression* guard on the surrounding
behaviour rather than as the exemption's proof.

### 3.9 Refusal and failure legs (NORMATIVE)

| # | Condition | `route` (preflight, `check_dirty=True`) | `recompile` (`check_dirty=False`) |
|---|---|---|---|
| L1 | user scope + `reference` | refuse, message **byte-identical** to `verbs.py:1087-1096` | unreachable |
| L2 | surface missing, **skill** scope | `VerbError`: the skill's `SKILL.md` is missing — name the path, and `self-learn host rebind` / repair the skill; **before the ledger commit** | warning + skip the pointer; appends proceed |
| L3 | surface missing, **project** scope | create empty `CLAUDE.md`, write the pointer, stage it (`verbs.py:1926-1931` precedent) | same |
| L4 | surface dirty in the host repo | `_abort_if_dirty(host, surface)` — the same call already made for `probe` at `:1102-1103` | skip the pointer loudly (§3.7 step 1); appends proceed |
| L5 | surface not decodable as UTF-8 | `VerbError` at preflight naming the file — refuse before the ledger commit rather than after it | warning + skip, **which requires `UnicodeDecodeError` in the except tuple** (§3.7 step 2; it is a `ValueError`, not an `OSError`) |
| L6 | host unregistered / unsound | **unchanged** — `_hosts_skill_dir` / `_project_host_or_refuse` raise before the branch is reached | **unchanged** — warning, continue (`:3901-3903`) |
| L7 | surface already names the target (hand-written or ours) | no write, `changed=False`, no commit | same |
| L8 | `supersede` / `graduate` reaching the reference leg | **unchanged** — `verbs.py:1882-1883` still refuses | unreachable |

L2 is a **declared behaviour change**: a skill-scope reference route with
a missing `SKILL.md` succeeds today (writing unreachable canon) and
refuses after this unit. That is the point of the unit — the alternative
is knowingly creating the exact defect FW-40 exists to close. L5 is the
same argument applied to a file that cannot be read.

**r2 (MAJOR 7) — the mechanism that makes this table's two columns
differ, stated in build text rather than left in the column headers.**
L2 and L5 must be raised **only when `check_dirty` is True**, the same
parameter that already gates `_abort_if_dirty` at `verbs.py:1102-1103`.
`recompile` calls `_resolve_target(..., check_dirty=False, ...)`
(`:3878-3900`), so a `check_dirty`-gated refusal is simply not raised
there and the recompile leg reaches its own warn-and-skip handling.
**An ungated refusal silently produces the wrong column**: the
`VerbError` is raised at `:3879`, caught at `:3901-3903`, and the loop
`continue`s past the **entire `ref_work` entry** — so the record appends
never happen either, contradicting the "appends proceed" cell this table
declares for L2 and L5. That is not a cosmetic difference: a skill whose
`SKILL.md` went missing would stop receiving canon entirely, and the
only symptom would be one warning line in a nightly run. Criteria **F7**
and **F8** distinguish the two builds; **M29** is the mutation.

### 3.10 One predicate, one home

`surface_names_target` **moves** from `selfcheck.py:329-364` into
`compilers.py`, public, with `_TOKEN_DELIMS` (`selfcheck.py:324-326`)
alongside it and its docstring carried over verbatim. `selfcheck.py`
then reads:

```python
from .compilers import surface_names_target as _surface_names_target
```

Why a move and not a copy: the emitter's idempotence test (§3.3 step 2)
and its post-condition (step 4) are the *same question* the detector
asks. Two implementations of that question is precisely the shape this
file already documents a scar from (`verbs.py:1097-1100`), and it would
be a silent one — a drifted copy makes the emitter write a pointer the
selftest then reports as unreachable, i.e. the unit shipping while
appearing to fail. Direction is forced: `selfcheck` already imports from
`compilers` (`reference_target_path`, used at `selfcheck.py:280`), so
the reverse import would be circular.

The private alias is kept deliberately: `test_selftest.py:296-332` calls
`selfcheck._surface_names_target` in six assertions that are the
detector's precision tests. They must stay green **unmodified** — that
is the regression proof for the move (criterion **A1**).

---

## 4. Acceptance criteria

**These criteria are the contract.** Each names the mutation from §5
that reddens it. Each states what it reports when its target is absent —
a check that cannot fail is this project's signature defect.

Tests live in `plugins/self-learn/cli/tests/test_pointer.py` unless a
criterion says otherwise. Markers, caps and labels are **imported**
(`POINTER_BEGIN_MARKER`, `POINTER_END_MARKER`, `BEGIN_MARKER`,
`END_MARKER`, `DEFAULT_MAX_ENTRIES`, `POINTER_LABELS`), never re-typed
as literals — a hand-copied marker is FW-44/FW-48's defect exactly.

### A. The pointer contract

**A1 — the move is a move, not a rewrite.** `test_selftest.py:296-332`'s
six `selfcheck._surface_names_target` assertions pass **with no edits to
that file**, and `selfcheck._surface_names_target is
compilers.surface_names_target` (identity, not equality). *Absent:* if a
builder copies the predicate instead of importing it, the identity
assertion fails while the six behaviour assertions still pass — which is
why the identity leg exists. → **M1**

**A2 — the token form, both live scopes.** Build a skill fixture
(`<root>/plugins/p/skills/s/SKILL.md` + `…/skills/s/references/LEARNINGS.md`)
and a project fixture (`<host>/CLAUDE.md` + `<host>/references/LEARNINGS.md`).
Assert `pointer_token(surface, target) == "references/LEARNINGS.md"` in
both. *Absent:* a builder emitting a bare basename or an absolute path
fails here before any file is written. → **M2**, **M3**

**A3 — the post-condition IS the contract (the load-bearing criterion).**
For both fixtures of A2: call `apply_pointer`, then assert
`selfcheck._surface_names_target(surface, target) is True`, **calling the
detector, not re-parsing the block**. *Vacuity guard, mandatory:* the
same test asserts the predicate is `False` on the pristine surface
*before* the call. Without that leg a builder whose fixture accidentally
already named the target gets a green run over a no-op. → **M2**, **M3**,
**M4**

**A4 — negative controls: the token is load-bearing.** For each of four
wrong tokens written into a pointer block by hand —
`LEARNINGS.md` (bare basename), `../references/LEARNINGS.md`
(relative to the *file* instead of its parent), `docs/LEARNINGS.md`
(other directory), `references/myLEARNINGS.md` (basename-suffix
collision) — assert `_surface_names_target` is `False`. All four measured
`False` (§8-X5). *Absent:* this is the test that proves A3 is not
passing for a vacuous reason. → no mutation; it guards A3.

**A5 — the block's shape.** After `apply_pointer` on an empty surface:
the file contains exactly one `POINTER_BEGIN_MARKER` and one
`POINTER_END_MARKER`, in that order; exactly one line matching the
`pointer_line` grammar; `bootstrapped is True`; and the text ends with a
single trailing newline. *Absent:* a builder emitting the block twice, or
without an end marker, reddens. → **M5**

**A6 — the absolute-`--dest` leg.** With `target` outside the surface's
subtree: if the target is under `Path.home()`, `pointer_token` returns a
`~/…` token; otherwise the absolute path. Both satisfy A3's
post-condition (measured, §8-X10). *Absent:* a builder that always emits
`os.path.relpath` produces a `..`-laden token and fails the
post-condition. → **M6**

**A7 — broken markers refuse.** A surface carrying two begin markers, or
an end before a begin, makes `compile_pointer_text` raise `CompileError`
whose message contains both counts (respectively the words
`end`/`begin`). *Absent:* a builder that silently appends a second block
reddens. → **M7**

**A8 — the post-condition is reachable and fires (r2, MAJOR 4).**
Monkeypatch `compilers.pointer_token` to return a token that cannot
resolve to the target (e.g. `"nope/NOWHERE.md"`), call `apply_pointer`
on a fixture whose surface does not yet name the target, and assert
`CompileError` is raised **and** that its message contains the surface
path, the target path and the bad token. *Absent:* this is the one
criterion that distinguishes the post-condition from its own deletion —
the gate verified that under M2/M3 the A-criteria fail on the token
comparison first, so nothing else in §4 reaches it. → **M28**

**A9 — the no-write path still reports a usable token (r2, NOTE 12).**
On a surface that already names the target, assert `changed is False`
**and** `PointerResult.token == pointer_token(surface, target)` (not
`""`, not `None`). *Absent:* a builder returning an empty token on the
early-return path leaves the caller's note text and any future consumer
reading a blank. → **M4**

### B. Non-interference with the managed section

**B1 — the pointer lands OUTSIDE the managed markers (r2, replaces r1's
vacuous count comparison).** Two legs, both asserted on the file
**after** calling `apply_pointer`, never on a hand-written fixture:

- **(i) the emitter's own output.** `POINTER_BEGIN_MARKER in text` and
  `POINTER_END_MARKER in text`; and the substring of `text` **between
  the managed `BEGIN_MARKER` and `END_MARKER`** does **not** contain the
  emitted token. On a surface with no managed section, assert
  `text.count(BEGIN_MARKER) == 0` — i.e. `apply_pointer` did not create
  one.
- **(ii) the managed-marker count is unchanged by the call.** Capture
  `text.count(BEGIN_MARKER)` before and after `apply_pointer`; assert
  equal (0 before/after on a section-less surface, 1 before/after on a
  surface that has a section).

*Why not the r1 form:* `compile_managed_text` derives every count from
its `records` argument alone (`compilers.py:252-261`), so "assert
`entry_count` is unchanged" is **identical for a correct build and for
M8** — measured (§8-X12). A criterion that cannot separate the mutation
it names is not a criterion. *Retained as a regression guard, not as
the exemption's proof:* with `DEFAULT_MAX_ENTRIES` records plus a
pointer block, `over_cap is False` and `cap_reason is None`. → **M8**

**B2 — the block survives a managed-section regeneration byte-identical.**
**The fixture must be PRODUCED BY CALLING `apply_pointer`** — not a
hand-written literal, which is blind to every emitter mutation and would
pass while the emitter writes anywhere at all. Then
`compile_managed_text(surface.read_text(), records).text` contains that
produced block unchanged, and `selfcheck._surface_names_target` is still
`True` when the regenerated text is written back. *Absent:* a marker
collision, or an emitter writing inside the markers, is eaten here. →
**M8**, **M9**

**B5 — end-to-end: a route survives the NEXT managed-section route
(r2, the criterion that catches the latent wipe).** Route a record to
`reference` at project scope; assert `_check_reach` passes. Then route a
second record to `claude-md` on the **same** host — a real
`compile_managed_file` regeneration of the same surface — and assert
`_check_reach` **still** passes. *Absent:* measured (§8-X12), an M8
build passes the first assertion and **fails the second**, silently
deleting the pointer and re-stranding the records with no error emitted
anywhere. This is the only criterion in §4 that can see it, and without
it an M8 build may redden **nothing at all**. → **M8**

**B3 — marker counts are untouched.** On a surface carrying both blocks:
`text.count(BEGIN_MARKER) == 1` and `text.count(END_MARKER) == 1`, and
`selfcheck._check_markers({surface: [record]})` returns `ok=True`.
Additionally assert `BEGIN_MARKER not in POINTER_BEGIN_MARKER` and
`END_MARKER not in POINTER_END_MARKER`. *Absent:* a builder who reuses
the managed markers for the pointer block reddens all three legs. →
**M9**

**B4 — the managed compilers are never called on the surface.** A
skill-scope reference route into a `SKILL.md` that has **no managed
section** leaves that file with **zero** `BEGIN_MARKER` occurrences
afterwards. This is the home-assistant shape, and it is the criterion
that catches the wrong reading of "ALWAYS recompile" (§3.4). *Absent:* a
build calling `compile_managed_file` bootstraps a marker pair and this
goes from 0 to 1. → **M10**

### C. Threading and the route path

**C1 — the two derivations agree (cross-module).** For a skill-scope and
a project-scope fixture, assert
`_resolve_target(...).pointer_surface == selfcheck._loaded_surface(home,
bucket, record)[0].resolve()` (compare `.resolve()` on both sides; the
verb path passes the host through `validate_host_path`). *Absent:* a
builder pointing skill scope at the skills-root `CLAUDE.md`, or project
scope at `.claude/CLAUDE.md`, reddens — and would otherwise ship a
pointer in a file the detector never opens. → **M11**

**C2 — a fresh skill-scope reference route makes `reach` pass
end-to-end.** Seed a sandbox, route one record with
`--dest reference`, then assert `selfcheck._check_reach(home)` returns
`ok=True` **and** its message names the count (`1 reference-routed
record(s) reachable`). *Mandatory positive control in the same test:*
assert `_check_reach` returns `ok=False` for the same ledger state with
the pointer block stripped from the surface. This criterion is the
unit's whole purpose expressed as one assertion. → **M2**, **M3**,
**M12**

**C3 — the pointer file is staged and committed with the route.** After
C2's route, the host repo's HEAD commit touches **both** the references
file and the surface (`support.verb_files`), and the surface is not left
dirty. *Absent:* a build that writes the pointer but omits it from
`host_paths` leaves an uncommitted file, and this reddens. → **M13**

**C4 — the human is told.** The route's warnings/notes channel carries a
line naming the surface path when a pointer line was added, and carries
**no** such line when the surface already named the target. *Absent:* a
build that always emits the note reddens the second leg. → **M14**

**C5 — idempotence across routes.** Route a second record to the same
reference file. Assert the surface's byte content is **unchanged** by
the second route, and that the pointer block still holds exactly one
line for that target. *Absent:* an emitter keying idempotence on "did I
write this in this process" appends a duplicate and reddens. → **M4**

**C6 — a pre-existing hand-written pointer is respected.** Write
`See references/LEARNINGS.md.` into the surface by hand (measured
resolving, §8-X9), then route. Assert the surface is **byte-unchanged**
and no pointer block was created. *Absent:* an emitter that skips the
predicate and always writes reddens. → **M4**

**C7 — two reference files, two lines, one block, in route order.**
Route to `LEARNINGS.md` and then to a second existing references file.
Assert exactly one pointer block, two lines, `_surface_names_target`
True for **both** targets, **and that the second target's line is the
LAST line inside the block** (§3.3's insertion-order pin; r1 asserted
the count but not the order, so a prepending build passed). → **M5**,
**M31**

### D. The commit gate

**D1 — a no-op append with a new pointer still commits.** Drive
`_host_phase` directly against a state where the record's id is **already**
in the references file (so `compile_reference` returns `applied=False`)
and the surface names nothing. Assert a host commit sha is returned, the
surface is committed, and the working tree is clean afterwards. *Absent:*
against the unmodified gate (`verbs.py:2098-2100`) this is exactly the
silent write-without-commit — the file is rewritten on disk and never
recorded — and it reddens. → **M15**

**D2 — every other destination's gate is byte-identical (r2, rewritten:
r1's assertion could not see M16).** A `claude-md` route whose managed
section is unchanged must still be a **clean no-op**, asserted on three
things, not one: (a) no commit; (b) `cli._outcome_state(result) ==
"no_op"`; (c) `result.warnings` contains **no** host-phase-failure line.

*Why the extra legs:* the gate measured M16 (`pointer_changed or True`)
and found r1's bare "no commit" assertion **still passes** — under M16
the gate is entered, `git commit -- <unchanged path>` exits 1
(measured), `GitOpsError` is raised, `_host_phase`'s handler catches it
and returns `(None, None)`. No commit, so r1 was green — while the verb
had in fact taken a failure path and told the user canon was stale.
Legs (b) and (c) see it: `_outcome_state` flips `"no_op"` → `"drift"`,
and the warnings gain the `HOST PHASE FAILED` line. The `hook` leg r1
also listed is **struck**: it is structurally unreachable, because
`host_paths` is `[]` at `verbs.py:1880` when nothing changed and the
`:2097` guard short-circuits before any gate predicate runs. → **M16**

**D3 — `cli.py` is untouched, and the short-circuit that makes that safe
is pinned (r2, MAJOR 3: r1's behavioural legs were unreachable).** Two
legs:

- **(i) structural.** Assert `cli._reports_no_change`'s source is
  byte-unchanged from base (`inspect.getsource` compared against the
  literal in the test), and assert `_outcome_state` returns `"landed"`
  for **any** `VerbResult` carrying a non-`None` `host_commit_sha`
  **whose `compile_result` is a `ReferenceResult` with
  `applied=False`** — i.e. the short-circuit at `cli.py:1040-1041`
  precedes the `_reports_no_change` consult at `:1044`.
- **(ii) behavioural, honestly scoped.** A route where entry and pointer
  are both already present yields `"no_op"`.

*Recorded so the gate does not read it as a gap:* leg (ii) alone cannot
redden for a `_reports_no_change` edit — every plausible edit evaluates
identically on that fixture, which is exactly why leg (i) is
structural. A criterion that names its own blind spot is worth more than
one that pretends to cover it. → **M17**

### E. Recompile — the backfill mechanism

**E1 — the R14 shape, reproduced and repaired.** Fixture: a
reference-routed record whose entry is **already** in `LEARNINGS.md` and
whose surface names nothing. Assert `_check_reach` is `ok=False` before
(**the positive control — it must be asserted, not assumed**), run
`recompile`, assert `ok=True` after. *Absent:* without the before-leg
this test passes on a ledger with zero reference records. → **M18**

**E2 — the old `continue` is dead.** In E1's fixture, assert `recompile`
produced a commit whose subject starts `self-learn: pointer ` and whose
files are exactly `[<rel surface>]`. *Absent:* the unmodified
`if not applied: continue` (`verbs.py:4028-4033`) yields zero commits
and reddens. → **M18**

**E3 — the reference commit is unchanged when entries do land.** With a
missing entry **and** a missing pointer, assert two commits: one
`self-learn: recompile <rel probe>` over the references file (subject and
pathspec byte-identical to today's), one `self-learn: pointer …`. →
**M19**

**E4 — idempotence.** A second `recompile` over E1's repaired tree
produces **zero** commits and `RecompileResult.committed == 0`. *Absent:*
an emitter that rewrites the block every run makes every nightly run
commit, and reddens. → **M4**

**E5 — a dirty surface is skipped loudly, and does not block the
appends.** Fixture with an uncommitted edit in the surface and a missing
entry in `LEARNINGS.md`: assert the entry **is** appended and committed,
a `RecompileEntry(target=surface, skipped="dirty")` exists, a warning
names the surface, and the surface is **not** rewritten. *Absent:* a
build that skips the whole ref_work entry on a dirty surface withholds
canon and reddens the append leg. → **M20**

**E6 — an unresolvable host still only warns.** A reference-routed record
whose host is unregistered leaves `recompile` completing, with a warning
naming the record — unchanged from today (`verbs.py:3901-3903`). → **M21**

**E7 — an undecodable surface does not abort the batch (r2, BLOCKER 2;
no criterion existed in r1).** Fixture: **two** hosts with
reference-routed records, the FIRST of which has a surface containing
invalid UTF-8 bytes and the second sound. Assert `recompile` **returns**
(no exception escapes), a warning names the undecodable surface, and the
**second** host's repair still happened — its entry appended, its
pointer written, its commits present. *Vacuity guard, mandatory:* assert
the second host's `RecompileEntry` exists, not merely that no exception
was raised; a build that returns early past both hosts would otherwise
pass. *Absent:* with the two-member except tuple this spec first pinned,
the `UnicodeDecodeError` escapes `recompile()` entirely and every host
after the first is silently unrepaired. → **M27**

**E8 — the backfill is PUSHED, not just committed (r2, NOTE 9).** With a
host repo that has a remote, assert the pointer commit reaches the
remote — or, if the fixture stubs `gitops.push_if_remote`, assert it was
called with that `host_repo`. *Absent:* a leg that commits without
appending to `touched_hosts` (`verbs.py:4109-4113` iterates it) leaves
the entire R14 backfill local, which is indistinguishable from success
in `recompile`'s own output. → **M30**

### F. Scope invariants and refusals

**F1 — the user-scope refusal is byte-identical.** Assert the raised
message equals the string at `verbs.py:1087-1096` verbatim (compare
against the literal in the test, and assert it contains `S-23 (2)`).
*Absent:* deleting or softening the refusal builds the user-level
reference file S-23 rejected. → **M22**

**F2 — L2: skill scope, missing `SKILL.md`, refuses before the ledger
commit.** Assert `VerbError` naming the missing path, **and** that the
record is still `pending` (nothing resolved, nothing committed). *Absent:*
a build that refuses *after* the ledger commit reddens the second leg. →
**M23**

**F3 — L3: project scope, missing `CLAUDE.md`, is created and pointed.**
Assert the file now exists, carries the pointer block, is staged in the
route commit, and `_check_reach` passes. → **M23**

**F4 — L4: dirty surface refuses the route before the ledger commit.**
Assert `DirtyTargetError` (a `VerbError`), the record still pending, and
the surface unmodified. → **M24**

**F5 — L5: an undecodable surface refuses at preflight.** Write invalid
UTF-8 bytes into the surface; assert `VerbError` naming the file and the
record still pending. *Absent:* without this the route commits the ledger
and then dies in the host phase, leaving drift the repair verb cannot
heal either. → **M25**

**F6 — L8: supersede/graduate still refuse.** The message at
`verbs.py:1882-1883` is unchanged and still raised when
`routed_record is None`. → **M26**

**F7 — L2 at recompile: a missing skill surface warns, and the appends
still happen (r2, MAJOR 7).** Fixture: a skill-scope reference-routed
record whose `SKILL.md` does not exist and whose entry is **missing**
from `LEARNINGS.md`. Assert `recompile` (i) appends and commits the
entry, (ii) emits a warning naming the missing surface, (iii) writes no
pointer. *Absent:* if L2's refusal is not `check_dirty`-gated, the
`VerbError` is raised at `verbs.py:3879`, caught at `:3901-3903`, and the
loop `continue`s past the whole `ref_work` entry — leg (i) reddens,
which is the entire point. → **M29**

**F8 — L5 at recompile, same shape.** As F7 with an undecodable surface
instead of a missing one: the entry is appended and committed, a warning
names the surface, no pointer is written. Distinct from **E7**, which
tests the *except tuple*; this tests the *preflight gating*. Both are
needed — the gate found each hides the other's defect on a one-host
fixture. → **M27**, **M29**

### G. Hygiene

**G1 — suite and types.** `cd plugins/self-learn/cli && ./.venv/bin/python
-m pytest -q` → **1520 + new passed, 5 skipped, 0 failed** (the CLI suite
has **no** tolerated failure — any red is new). `pyright` clean on the
three touched source files. Exit codes captured **unpiped**.

*r2 (MAJOR 5): r1 said 1266, which predates U-repair's merge and is
stale by 254 tests — a code gate reading it literally would fail a
correct build.* **1520 / 5 / 0** was re-measured at base `c8dcaf3` for
this revision (§8-X15, unpiped rc 0), independently of the gate's own
measurement of the same number. The five skips are four
`test_lock_invariant.py:669` rows plus `test_regime_fixes.py:337`
("repo-root suite absent") — named so a builder can tell a *pre-existing*
skip from one it introduced.

**G2 — no new literals.** No test and no source line re-types a marker
string, a cap number, or a label; all are imported (see §4 preamble).

---

## 5. Mutation plan

The code gate runs these. **Before any sweep:** `export
PYTHONDONTWRITEBYTECODE=1` and
`find . -name __pycache__ -type d -prune -exec rm -rf {} +` — a stale
cache reports mutations as survived that never executed (FW-61). Use
absolute paths and machine-check that
`realpath(self_learn.__file__)` resolves inside the tree under review; a
worktree `.venv` can be an editable install pinned to the main checkout,
which manufactures **false survivals** only.

| # | one-line edit | reddens |
|---|---|---|
| M1 | copy `surface_names_target`'s body into `selfcheck.py` instead of importing it | A1 (identity leg **only** — the six behaviour assertions stay green, which is exactly why the identity leg exists) |
| M2 | `pointer_token` returns `target.name` | A2, A3, C2 |
| M3 | `pointer_token` uses `os.path.relpath(target, surface)` (the file, not its parent) | A2, A3, C2 |
| M4 | `apply_pointer` skips the `surface_names_target` check and always writes | A3 (vacuity leg), C5, C6, E4 |
| M5 | `compile_pointer_text` always appends a fresh block instead of inserting into an existing one | A5, C7 |
| M6 | delete the `..` branch — always return the lexical `relpath` | A6 |
| M7 | `compile_pointer_text` tolerates 2 begin markers | A7 |
| M8 | emit the pointer line **inside** `BEGIN_MARKER`/`END_MARKER` instead of the pointer block | **B1(i), B2, B5** — *r2: NOT the r1 count comparison, which is provably identical under this mutation (§8-X12). B5 is the only leg that sees the latent wipe; run it and confirm it reddens on the SECOND assertion, not the first* |
| M9 | set `POINTER_BEGIN_MARKER = BEGIN_MARKER` | B2, B3 |
| M10 | call `compile_managed_file(spec.pointer_surface, records)` in the reference leg (the wrong reading of "ALWAYS recompile") | B4 |
| M11 | skill scope threads `root / "CLAUDE.md"` as `pointer_surface` | C1, C2 |
| M12 | drop the `apply_pointer` call from `_apply_target`'s reference leg entirely | C2, C3, C4 — the whole unit, in one line |
| M13 | write the pointer but do not append the surface to `host_paths` | C3 |
| M14 | append the note unconditionally, not only when `pointer.changed` | C4 (second leg) |
| M15 | revert `_host_phase`'s gate to `changed is not False and applied is not False` | D1 — **and only D1**: `recompile` has its own gate (§3.7 step 3), so every E criterion stays green, which is precisely why D1 must be red-verified rather than assumed covered |
| M16 | gate on `pointer_changed or True` | **D2 legs (b)+(c) only** — *r2: leg (a) ("no commit") survives, because the mutated gate reaches `git commit -- <unchanged path>`, which exits 1 → `GitOpsError` → caught → `(None, None)`. A reviewer checking only "was a commit made" will wrongly record this as SURVIVED* |
| M17 | "fix" `cli._reports_no_change` to consult `pointer_changed` | **D3 leg (i) only** — *r2: leg (ii) cannot redden; every plausible edit evaluates identically on the both-present fixture, and leg (i)'s short-circuit assertion is unreachable behind `cli.py:1040-1041`. This mutation is verified STRUCTURALLY or not at all* |
| M18 | leave `if not applied: continue` (`verbs.py:4028-4033`) unchanged | E1, E2 |
| M19 | commit both files under one subject naming only the surface | E3 |
| M20 | on a dirty surface, `continue` past the whole `ref_work` entry | E5 (append leg) |
| M21 | let the `VerbError` from an unresolvable host escape `recompile` | E6 |
| M22 | delete the user-scope refusal branch | F1 |
| M23 | `create=True` for skill scope too (write an empty `SKILL.md`) | F2 |
| M24 | drop `_abort_if_dirty(host, surface)` from the preflight | F4 |
| M25 | drop the preflight decode check | F5 |
| M26 | delete the `routed_record is None` refusal | F6 |
| **M27** | drop `UnicodeDecodeError` from the recompile except tuple (i.e. r1's `except (CompileError, OSError)`) | **E7**, F8 — the whole-batch abort |
| **M28** | make `apply_pointer`'s post-condition a no-op (`pass` instead of the raise) | **A8** — and *only* A8, which is the finding: r1 shipped a guard nothing could see |
| **M29** | raise L2/L5 unconditionally instead of gating on `check_dirty` | **F7, F8** (append legs) — the silent "record appends stop happening" regression |
| **M30** | commit the pointer without appending `host_repo` to `touched_hosts` | **E8** — backfill committed, never pushed |
| **M31** | insert the new pointer line FIRST inside the block instead of last | **C7** (order leg) |

**Reviewers are invited to invent mutations not listed here, and the
invitation has already paid.** r1 asked for exactly one probe — make
`apply_pointer`'s post-condition a no-op and see whether anything
reddens — and the answer was **nothing did**. That is now **M28/A8**.
Three more of r1's own mutations turned out not to do what r1 said
(**M8**, **M16**, **M17**), each for a different reason, all recorded
in their rows above. **Read those parenthetical notes before recording a
SURVIVED verdict on any of the four** — in three of the four, the naive
observation is exactly the one that reports the mutation as survived
when it is caught, or caught when it survives.

The r2 probe most worth trying next: build a **section-less** surface
(the home-assistant shape) and run every B-criterion against it. r1's
reasoning about caps was correct and its criterion still could not see a
wrong build; the same gap may exist elsewhere in the B group.

---

## 6. Builder decisions, made here rather than left open

**D1 — a dedicated marker block, not the managed section, not a bare
append.** Rejected: (a) *inside the managed section* — it would enter
`_eligible`'s entry and word counts, contradicting "cap-exempt", and it
cannot work at all on a surface with no section, which is the surface
all 14 stranded records need; (b) *bare append with no markers* — then
"exactly one pointer" has no structural definition and every write has to
guess where the previous one ended. The block gives the exemption a
structural home (§3.8) and gives idempotence a definition.

**D2 — presence is decided by the whole-file predicate, not by parsing
the block.** The contract is "the surface names the target" (B1), so a
hand-written mention already satisfies it and must be left alone (C6).
This also removes the only place a parse-back algorithm would have been
needed — and §5 of the campaign playbook is explicit about what happens
to algorithms pinned in prose and shipped untested.

**D3 — insert-only; never remove, never re-sort.** Reference files are
append-only (B4), so a pointer that was ever correct stays correct;
removing one would strand history that is still on disk. Re-sorting was
rejected because it forces parsing existing lines back out of the block
(see D2), buying only cross-machine byte-identity, which nothing needs.

**D4 — relative token, `~`-then-absolute fallback.** §3.2. The deciding
argument is not aesthetics: these surfaces are committed and cloned, and
an absolute `/home/<user>/…` token is both a personal-path leak into a
public repo and dead on any other machine.

**D5 — the label is threaded, not inferred.** `compilers.py` has no
notion of scope; giving it one to write two words would be the wrong
seam.

**D6 — project creates a missing surface, skill refuses.** §3.5. Not an
inconsistency: `CLAUDE.md` is prose that self-learn already creates
(`verbs.py:1926-1931`); `SKILL.md` is a manifest with required
frontmatter, and an empty one is a broken plugin — a line self-learn
already refuses to cross (`verbs.py:1049-1062`).

**D7 — refuse at preflight, warn at recompile.** The existing split
posture: `route` must never leave the ledger committed with a host it
cannot write (E-17), while `recompile` must never let one bad host abort
a batch repair (H-3).

**D8 — existing tests may absorb declared changes, and only those.** Two
are foreseeable: a reference-route test asserting the host commit touches
one file (now two, criterion C3), and any test asserting
`RecompileResult.committed` for a fixture that now also emits a pointer
(E3). Both are consequences of criteria in §4. **Any other test that
needs editing is a finding, not a chore** — report it with the reason,
do not quietly adjust it.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **The operational R14 run.** The mechanism ships and is proven against
  fixtures; running `self-learn recompile` against the real ledger and
  the real skills repo is a **user-executed step after merge**. The
  ledger is read-only to every agent in this campaign.
- **Any UI change.** §7.2.
- **A `route` telemetry event for the pointer.** Telemetry kinds are
  FW-45/U-reach's register.
- **Instrumenting whether a session opens the file.** Checkpoint B's
  question, explicitly out of scope (B6).

### 7.2 DISCLOSED — the review surface still cannot name the file

`ui/src/self_learn_ui/models.py` knows the `reference` **destination**
(`:97`, `:108-112`, `:530-533`, and the `"Reference file"` group label at
`:543`) and no template renders a `reference_file`. After this
unit the human approving a reference proposal still cannot see *which*
file the lesson lands in, nor that a pointer will be written into
`SKILL.md`/`CLAUDE.md`. That is a real gap in informed consent for a
route that now writes **two** files instead of one. It is **not** fixed
here — it is genuine UI work (a new datum through the proposal model, a
template change, and a test), the UI is a contended file set, and this
unit's file discipline is what keeps it gateable. Recommended as its own
row in `14-forward-work-map.md` at merge time.

### 7.3 ACCEPTED residual — the pointer's *efficacy* stays unmeasured

The block's preamble ("Read the file whose subject matches what you are
about to do, before you start") is the only lever this unit has on
whether a session actually opens the file. Its efficacy is **unmeasured
and is not claimed**; r2 §8 item 6 names this the design's soft spot, and
S-23 chose PATHED as the primary cheap tier precisely because pathed
injection does not depend on it. This unit closes *reachability*
(a mechanical property, now measured 14→0), not *retrieval*. Checkpoint B
decides whether retrieval gets instrumented or formally ACCEPTED; this
residual is the input to that decision, not a substitute for it.

### 7.4 ACCEPTED residual — a dangling pointer still reads as reachable

`_surface_names_target` compares resolved paths and never asks whether
the target exists (`Path.resolve()` is non-strict). If a human deletes a
references file, its pointer keeps satisfying `reach`. Not closed here:
the detector is u-reach's, the emitter has no business widening it, and
the failure mode (a deleted canon file) is louder than the symptom.

### 7.5 ACCEPTED residual — the pointer block's words are not budgeted

`_apply_target` spools one `surface-budget` telemetry event per apply
(`verbs.py:1958-1963`) reading `word_count` off the compile result;
`ReferenceResult` has none, so it already reports `None`. The pointer
block adds roughly 25 words to an ALWAYS surface and this unit does not
spool a second event for it — a second `surface-budget` event per route
would double-count the route in the attention ledger, and the event's
shape belongs to FW-45. Recorded so the omission is not later read as an
oversight.

---

### 7.6 ACCEPTED residual — the `~`-form fallback token is machine-specific

§3.2's fallback exists to keep a `/home/<user>/…` literal out of a
committed file, and it does: measured resolving (§8-X10). But `~` is a
**per-user** path, and the surfaces this writes into are committed and
cloned. A `~`-form token resolves correctly for the author and points at
a non-existent path for anyone else who clones that skill repo — the
**leak** half of the problem is answered, the **portability** half is
not (r2, NOTE 11). Accepted rather than fixed, on three grounds: the
branch is reachable only through an absolute `--dest`, which is rare and
deliberate; there is no portable encoding of "a file outside this
repository" to fall back to; and the failure is loud for the second user
(a dead link they can see) rather than silent. If absolute `--dest`
usage ever becomes common, the right fix is to refuse it for
reference routes, not to invent a token form.

---

## 8. What was executed, and against what oracle

Per campaign §5: *a spec that pins an algorithm in prose has pinned an
untested claim.* The pointer format and token rule below were **executed**
against the shipped detector before being pinned here.

**Oracle:** `self_learn.selfcheck._surface_names_target` and
`self_learn.compilers.compile_managed_text` at commit `c8dcaf3`, imported
from the **worktree** source tree, with provenance machine-checked and
printed: `realpath(self_learn.__file__)` resolved inside
`…/.claude/worktrees/agent-a56eb897c747962d8/plugins/self-learn/cli/src/self_learn/`.
Fixtures were `tempfile.mkdtemp` trees; the real ledger was not touched.
Record fixtures needed `kind:` and `source:` to pass `Record.validate`.

| id | what was run | result |
|---|---|---|
| **X1** | skill fixture (`plugins/p/skills/s/SKILL.md`, no managed section), token `references/LEARNINGS.md` from `os.path.relpath(target, surface.parent)` | `True` |
| **X2** | project fixture (`<host>/CLAUDE.md` **with** a managed section), same token form | `True` |
| **X3** | marker collision: `BEGIN_MARKER in POINTER_BEGIN_MARKER`, `END_MARKER in POINTER_END_MARKER` | `False`, `False`; counts on a both-blocks file: `1 begin / 1 end` |
| **X4** | `compile_managed_text` over a surface carrying a pointer block | `entry_count=1, word_count=10, over_cap=False`; **identical** to the same regeneration without the block; pointer block present byte-identical in the output |
| **X5** | `compile_managed_text` with 10 records (= `DEFAULT_MAX_ENTRIES`) + a pointer block | `over_cap=False, cap_reason=None`; block intact |
| **X6** | four wrong tokens: `LEARNINGS.md`, `../references/LEARNINGS.md`, `docs/LEARNINGS.md`, `references/myLEARNINGS.md` | `False` ×4 — the detector is not vacuous, and the token form is load-bearing |
| **X7** | managed-section **bootstrap** into a `SKILL.md` that already carries a pointer block | `bootstrapped=True`, block intact, reach still `True` |
| **X8** | two pointer lines in one block, two distinct targets | `True` for both |
| **X9** | hand-written shapes: `See references/LEARNINGS.md.` (sentence-final period), a backtick-free list line, `(references/LEARNINGS.md)` | `True` ×3 — confirms C6's fixture and B2's "leave a human's pointer alone" |
| **X10** | absolute fallback: `~/.cache/…/LEARNINGS.md` and the same path absolute | `True`, `True` |
| **X11** | token computed and resolved through a **symlinked** skills root | `True`; and surface-via-symlink vs target-via-real-path also compares equal (both sides `.resolve()`) |

**What X4/X5 do *not* prove — and r1 got this wrong.** They show the
pointer block does not *enter* the counts. They do **not** distinguish a
correct build from M8, because the counts are blind to `target_text`
altogether. r1's sentence here claimed "B1 is written to catch it"; B1
was not. X12 below is the measurement that establishes what actually
catches it.

### 8a. Measurements added at r2

Same oracle, same provenance discipline, same commit (`c8dcaf3`).

| id | what was run | result |
|---|---|---|
| **X12** | **M8 executed end-to-end**: pointer line emitted INSIDE the managed markers, then `compile_managed_text` regenerated the section (i.e. the next `claude-md` route to that surface) | reach **True** immediately after the route; reach **False** after the regeneration — the pointer is **silently deleted** and the records re-stranded. Counts reported by that regeneration: `entry_count=1 word_count=10 over_cap=False cap_reason=None` — **byte-identical to the correct build's**, confirming r1's B1 could not fail. Marker counts also identical (1/1), so the discriminating leg is the presence of `POINTER_BEGIN_MARKER`, not a count |
| **X13** | `UnicodeDecodeError.__mro__`; `issubclass(UnicodeDecodeError, OSError)`; `issubclass(..., ValueError)` | `[UnicodeDecodeError, UnicodeError, ValueError, Exception, …]`; **False**; **True** — r1's `except (CompileError, OSError)` could not catch it |
| **X14** | `os.path.relpath("/a/b", "/c/d")` on this platform | `"../../a/b"` — no raise, so r1's `try/except ValueError` around `relpath` was dead code (§3.2) |
| **X15** | the CLI suite at base, unpiped rc | **1520 passed, 5 skipped, 0 failed**, rc 0, 87.77s. Re-measured for this revision independently of the gate's own run of the same number; r1's `1266` was stale by 254 tests |

**Provenance for all four:** `realpath(self_learn.__file__)` printed and
confirmed inside this worktree's `cli/src/self_learn/`; the branch
carries **zero** code delta from `c8dcaf3` (`git diff --name-only
c8dcaf3 HEAD` lists only this spec file), so the suite number measured
through the shared editable install is a valid reading of the base tree
— stated because "a worktree `.venv` can resolve back to the original
source tree" is the campaign's own named trap, and here the two trees
are provably identical.

---

## 9. Fold report — r1 gate, twelve findings

One line per finding, naming the change and where it landed.

| # | Finding | Fold |
|---|---|---|
| **B1** | B1 cannot fail; M8 survives; M8's damage is latent | B1 rewritten to assert what the emitter controls (marker presence + marker-count-unchanged); **B2's fixture must now be produced by `apply_pointer`**; new end-to-end **B5** (route → managed regeneration → re-assert `_check_reach`); §3.8 rewritten to state that the counts are blind to `target_text`; **M8**'s row now names B1(i)/B2/B5 and warns which assertion reddens; measurement **X12** added — reproduced independently (reach True→False across a regeneration) |
| **B2** | recompile's except tuple cannot catch `UnicodeDecodeError`; whole-batch abort | §3.7 step 2 tuple → `(CompileError, OSError, UnicodeDecodeError)` with the MRO reason inline; §3.9 L5 cell amended; new **E7** (two-host fixture with a vacuity guard) and **M27**; `_HOST_PHASE_ERRORS`' identical gap recorded as out-of-footprint with its reachability condition; measurement **X13** |
| **M3** | M17 cannot redden D3 either leg | D3 rewritten into a **structural** leg (source byte-unchanged + the `cli.py:1040-1041` short-circuit asserted directly) plus an honestly-scoped behavioural leg; §3.6 now says *why* behaviour cannot see it; **M17** re-scoped to "verified structurally or not at all" |
| **M4** | the post-condition has zero coverage | New **A8** (monkeypatch `pointer_token` to a non-resolving token, assert the raise names surface/target/token) and **M28**; §3.3 step 4 records that r1's own invited probe found nothing reddening |
| **M5** | G1's number stale by 254 tests | G1 → **1520 passed / 5 skipped / 0 failed**, re-measured independently (**X15**, unpiped rc 0) with the five skips named so a builder can tell pre-existing from introduced |
| **M6** | M16 does not redden D2 as worded | D2 rewritten to three legs — no commit, `_outcome_state == "no_op"`, no host-phase-failure warning — with the `git commit` exit-1 → `GitOpsError` → `(None, None)` path explained; the unreachable `hook` leg **struck**; **M16**'s row warns that leg (a) survives |
| **M7** | L2/L5's recompile column has no criterion and no stated mechanism | §3.9 gains a normative paragraph pinning the refusals as **`check_dirty`-gated** and tracing what an ungated build does (`:3879` → `:3901-3903` → `continue` past the whole entry, appends lost); new **F7**/**F8** and **M29**; §3.5's cross-reference added |
| **N8** | prose said "two preflight refusals", register said three | §3.5 → three, enumerated (L2/L4/L5), with the r1 discrepancy noted in place |
| **N9** | `touched_hosts` never mentioned; no criterion that the backfill is pushed | §3.7 step 3 now mandates the append with the three existing precedent sites cited; new **E8** and **M30** |
| **N10** | commit-topology asymmetry unexplained | §3.7 states the rule both ways: one commit per *decision* at route (generic `_host_phase`, one human choice), one commit per *independent repair* at recompile (E5 requires independence) |
| **N11** | the `~` fallback is machine-specific in a shared repo | New **§7.6** ACCEPTED residual separating the leak half (answered) from the portability half (not), with the named alternative if absolute `--dest` ever becomes common |
| **N12** | four small register gaps | §3.3 names `compile_pointer_text`'s bool as `bootstrapped` (and why it is not `changed`) and pins **insertion order = last**; §3.2 deletes the dead `except ValueError` with measurement **X14**; **C7** gains an order leg + **M31**; new **A9** reads `PointerResult.token` on the no-write path |

**Nothing was folded by weakening a criterion.** Two criteria got
*narrower* claims (D2's hook leg struck, D3's behavioural leg scoped) —
in both cases because the r1 claim was unreachable, and a register that
lists an unreachable assertion is how a gate comes to trust a check that
never ran.

---

## 10. Revision history

- **r1 (2026-08-08)** — first draft. Design settled: dedicated marker
  block (§3.1), relative token with `~`/absolute fallback (§3.2),
  whole-file predicate for idempotence with the detector as the
  post-condition (§3.3), `pointer_surface` threaded on `TargetSpec`
  (§3.4), the `_host_phase` gate fold (§3.6), backfill riding `recompile`
  (§3.7), structural cap exemption (§3.8), and `surface_names_target`
  promoted to one home (§3.10). Eleven measurements executed against the
  shipped detector (§8). One disclosure (§7.2, the UI gap), three
  ACCEPTED residuals (§7.3-7.5), and one declared behaviour change
  (§3.9 L2).
- **r2 (2026-08-09)** — blind gate returned **UNSOUND — 2 BLOCKER /
  5 MAJOR / 5 NOTE**; all twelve folded, one line each in §9. Design
  unchanged: every §3 decision survived the round, and the gate
  reproduced all eleven r1 measurements. What changed is the **register**
  — seven criteria added (**A8, A9, B5, E7, E8, F7, F8**), six rewritten
  (**B1, B2, C7, D2, D3, G1**), five mutations added (**M27-M31**),
  three mutation rows corrected to say what they actually redden
  (**M8, M16, M17**) plus the post-condition probe promoted from a §5
  invitation to **M28**, and four measurements added (**X12-X15**, §8a) —
  X12, X13, X14 and X15 each re-run here before being pinned, rather
  than transcribed from the gate. Three build choices that r1 left implicit are now normative:
  the `check_dirty` gating of L2/L5 (§3.9), the `touched_hosts` append
  (§3.7), and the insertion order (§3.3). One residual added (**§7.6**,
  the `~` token's portability half). G1's acceptance number corrected
  **1266 → 1520**.
