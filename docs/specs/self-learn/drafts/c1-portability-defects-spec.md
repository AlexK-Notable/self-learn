# Spec C1 — portability defects: bootstrap + post-D2 stale references

Status: DRAFT rev 7 — folded after delta 5 (NOT SOUND: 1 BLOCKER,
1 MINOR, 1 NIT — "one deletion away from clean"). For delta 6 re-check
by the same reviewer.
Origin: user question 2026-07-19 — "as it stands is the project
'universal' right now? is the repo sharable, or does it contain
artifacts specific to me."

Scope: defect repair with no design question. The live shipped bug rev 5
briefly absorbed is carved out to **Spec C3** (§1.5a), blocked on a user
ruling.

## Fold summary (rev 6 → rev 7)

| Delta-5 finding | Disposition |
|---|---|
| **BLOCKER 1** — O-14/O-15 declared withdrawn in three narrative places but left **live and verbatim** in §3; since §3 says "read as a set," C1 still commanded the reclassification the carve exists to prevent | **Folded.** Both deleted from §3. The carve removed the narrative and left the executable obligation — the fold summary asserted "withdrawn" as done when it had not been done |
| MINOR 2 — deleting them would leave an unrecorded numbering gap, the same audit hole this spec twice condemned (P-C1.2, P-C1.11) | **Folded.** Withdrawal recorded **in place** in §3, where a reader of the obligation set meets the gap — not only in §1.5a. Carries forward that O-15 must not be revived as-written (satisfiable-while-broken, delta-4 MAJOR 2) |
| NIT 3 — the numbering note moved from one mid-list position to another | **Folded.** Now genuinely last in §3, after O-9 |

**Verified clean by delta 5, carried forward:** the structural header
repair; O-16's premise (empirically re-confirmed — dangling symlink is
`exists()==False`/`lexists()==True`, FIFO is `exists()==True`, both
raise `FileExistsError` on `mkdir`); every surviving §1.5a-replacement
citation (`ledger.py:67-73`, `cli.py:469`, ten `_home_gate` call sites);
§1.4's independence from the carved-out behavior; and both user rulings,
still confined.

**Pattern note, closing.** Six reviews, one recurring shape: a coarse
stand-in for an exact thing — `home_state` for per-directory checks, one
pattern for per-surface spellings, work-tree for repo-root, "nested
non-repo" for "nested **empty** non-repo", and finally a *narrative*
withdrawal standing in for an *actual* deletion. The last instance is
the sharpest: the document said the thing was done, in three places, and
it was not.

Rev 2-6 fold summaries are retained below for audit.

## Fold summary (rev 5 → rev 6)

| Delta-4 finding | Disposition |
|---|---|
| **BLOCKER 1** — §1.5a's reclassification destroys read access to a nested non-repo ledger that already holds records (classifies `ok` today, verified working live), and its cited recovery leg refuses that exact population because `init` step 5 requires an **empty** dir | **Carved out to Spec C3** (§1.5a). Not folded in place: the reviewer's judgment — a breaking change to data access needs its own user ruling, not a scope-growth footnote — is accepted |
| **MAJOR 2** — O-15 was satisfiable-while-broken: every repo-root shape is unchanged *by construction*, so it passes before, after, and while the BLOCKER is live | **Withdrawn with O-14.** Moves to C3, where the no-regression obligation must enumerate the **changed** set, not the unchanged one. This was the failure P-C1.17 condemns, committed in the obligation written to guard the change |
| MINOR 3 — `cli.py:465-468` off by one (the decision is `:469`) | **Resolved by the carve**; the corrected citation travels to C3 |
| MINOR 4 — P-C1.24 untested; O-13's FIFO passes an `exists()`-keyed step 2 | **Folded.** O-16 tests the dangling symlink specifically |
| NIT 5 — `ledger.py:65-73` over-reached by two lines | **Resolved by the carve**; corrected to `:67-73` in C3 |
| NIT 6 — numbering note sat mid-list | **Folded.** Moved to the end of §3 |

**Pattern note, final.** Four reviews found the same shape four times: a
coarse predicate standing in for an exact one, then — in rev 5 — a
coarse *claim* ("nested non-repo → `init` fixes it") standing in for the
exact one ("nested **empty** non-repo → `init` fixes it"), written three
sections from P-C1.20 which condemns exactly that. The pin did not
prevent its own recurrence.

Rev 2-5 fold summaries are retained below for audit.

## Fold summary (rev 4 → rev 5)

| Delta-3 finding | Disposition |
|---|---|
| MAJOR 1 — the same data damage reachable via the capture door: `home_state` decides `not-a-repo` with the very predicate P-C1.20 condemns, so a nested non-repo home reads `uninitialized`, `_home_gate` waves it through, and captures commit into the parent repo | **Folded as §1.5a** — `home_state` classifies via `is_repo_root()`. P-C1.22 declares the scope growth; P-C1.23 pins the blast-radius check; O-14/O-15 cover it |
| MINOR 2 — O-12 bullet 3 / P-C1.21 unimplementable (a legitimate nested ledger *does* put dirs under the parent, showing `?? ledger/`) | **Folded.** Assertion re-pinned to **tracked** state: parent index unchanged + no `_LAYOUT` path tracked |
| MINOR 3 — second copy of the bogus `§4.4` at `sentinel.py:3` | **Folded.** §1.2a and O-11 are now **file-wide**, not line-targeted |
| NIT 4 — dangling symlink still fell through to a raw `mkdir` error | **Folded.** P-C1.24: key step 2 on `os.path.lexists()` |
| NIT 5 — O-11 named no assertion; list order jumbled | **Folded.** Assertions named; numbering note added |

**Pattern note, updated.** Delta 2 flagged the coarse-vs-exact predicate
substitution as a recurring shape and P-C1.20 recorded it as a standing
suspicion. Delta 3 then found a **fourth** instance — in shipped code,
three lines from the pin that predicted it. The lesson generalizes past
this spec: writing the pin is not applying it.

Rev 2-4 fold summaries are retained below for audit.

## Fold summary (rev 3 → rev 4)

| Delta-2 finding | Disposition |
|---|---|
| BLOCKER 1 — steps 4-6 branched on is-inside-work-tree; a nested home wrote the ledger into the parent repo, and §2.1 row 1 already pinned the correct primitive | **Folded.** Steps 4-6 now branch on **`is_repo_root()`** (P-C1.20). One substitution closes all three legs: data damage, the failed MINOR-H fold (row 5 is now true — a nested non-empty dir reaches step 4 and refuses), and the §2.1↔§2.2 self-contradiction |
| MINOR 2 — no obligation pinned the branch predicate | **Folded.** O-12 asserts both nested cases **and the parent repo's cleanliness** (P-C1.21) — the shipped-green mode was every child-side assertion passing while dirs landed in the parent |
| MINOR 3 — P-C1.11 absent with no record | **Folded.** Retirement recorded in place (P-C1.18) |
| NIT 4 — steps 2-5 didn't partition exhaustively (FIFO/socket/device fell to a raw `mkdir` error) | **Folded.** Step 2 is now "exists and is not a directory," mirroring `hosts.py:249`; O-13 covers it |

**Pattern note.** Delta 2 identified this as the **third** instance of one
failure shape — a coarse predicate standing in for an exact one
(`home_state` vs. per-directory; one pattern vs. per-surface spelling;
work-tree vs. repo-root). P-C1.20 records it as a standing suspicion for
future work rather than three unrelated fixes.

Rev 2 and rev 3 fold summaries are retained below for audit.

## Fold summary (rev 2 → rev 3)

| Delta-1 finding | Disposition |
|---|---|
| MAJOR A — §2.2 step 4 unreachable for the realistic partial layout; O-2 mandated the wrong refusal | **Folded.** §2.2 rebuilt to branch **per-directory**, not per-state (P-C1.14); O-2 reworded; O-10 added for the real case |
| MAJOR B — §1.6's `test_hosting.py` fix would delete working coverage | **Folded — prescription REVOKED.** Reclassified out of scope; the `Path.home()` read is the point of the test (§1.6) |
| MINOR C — off-by-one in §0's own first-hand citations | **Folded.** `install.sh:97` links the UI unit; `:94` prints the enable step |
| MINOR D — `verbs.py:626` is a path assignment, not creation | **Folded.** → `_apply_new_skill`, `:1374`/`:1380` |
| MINOR E — P-C1.10 cited but never defined; P-C1.2 vanished | **Folded.** P-C1.10 defined (§2.2); P-C1.2 retirement recorded (§1.2) |
| MINOR F — O-6 vacuous; allowlist misleading | **Folded.** Per-surface patterns (P-C1.17); allowlist reframed as the *reason* for surface-scoping, never an exclusion list (P-C1.18) |
| MINOR G — step-4 path left the repo HEAD-less | **Folded.** P-C1.16 + O-10 |
| MINOR H — undeclared fifth divergence (nested init) | **Folded.** Added to the §2.1 table with justification |
| MINOR I — three in-scope fixes untested | **Folded.** O-11 |
| NIT J — `sentinel.py:55` still carries the bogus reference | **Folded.** Fixed at source (§1.2a, P-C1.19) |
| §5 judgment — "correctly bounded" | No change required; only its citation was wrong (MINOR D) |

Rev 2's fold summary is retained below for audit.

## Fold summary (rev 1 → rev 2)

| Gate finding | Disposition |
|---|---|
| BLOCKER 1 — §2 reinvented `host add --init` | **Folded.** §2 now derives from doc 13 §3 and reuses its primitives; the one departure is user-ruled and documented (§2.1) |
| BLOCKER 2 — obligation 6 unsatisfiable + destructive if widened | **Folded.** Scoped to registration/manifest surfaces with a justified allowlist (§3, O-6) |
| MAJOR 3 — P-C1.8 justification empirically false | **Folded.** Reviewer's disproof accepted and recorded; pin re-grounded on doc 13 parity (P-C1.8) |
| MAJOR 4 — wrong refusal set | **Folded.** `uninitialized` completes the layout; regular-file refusal added (§2.2) |
| MAJOR 5 — §1.3 fix contradicted P-C1.4 | **Folded via user ruling** — repoint to `self-learn`, private accepted (§1.3) |
| MAJOR 6 — registration blocks obsolete, not stale | **Folded.** Fix changed from string-swap to removal; `ui.service` added (§1.1) |
| 8 MINORs | **All folded** — corrected citations, symbol name, layout-bootstrap precision, 4 missed artifacts (§1.6) |

Scope discipline: every item is a thing that is *wrong*. Deferred:

| Deferred to | Why |
|---|---|
| **Spec C2** | chezmoi dependency → detected capability |
| **Spec D** | `DEFAULT_MEMORY_DIR` + all-projects sweep (the ruling changes what the default *means*) |
| **Spec A** | `claude-md` parameterization |
| **Spec B** | `permissions.deny` destination |

---

## 0. Provenance

Rev 1 claimed universal first-hand verification and **failed that claim**
(MAJOR 3: a mechanism asserted without being run; MINOR: a doc citation
copied from a source comment unchecked). Rev 2 states the weaker, true
thing: every citation below was re-read at rev-2 writing time, and every
reviewer-supplied finding was independently re-confirmed before folding
(`install.sh:91-98`, `hosts.py:191/194/261`, `13-…:407-409`,
`sentinel.py:53` all checked first-hand). Where a claim rests on someone
else's test rather than mine, it says so.

---

## 1. The defects

### 1.1 The systemd registration blocks are OBSOLETE, not merely stale

Rev 1 read this as a stale path. It is worse: the instructions describe
work the installer already does.

`install.sh:91-92` links both miner units into `$UNIT_DIR`; **`:97`**
links the UI unit; `:93` and `:98` run `systemctl --user daemon-reload`.
Yet:

- `systemd/self-learn-miner.service:2-6` — "Registration (manual, like
  the autosync unit)" + a `ln -sf ~/repos/claude-skills/systemd/…` block
- `plugins/self-learn/README.md:104-105` — the same `ln -sf` line
- `systemd/self-learn-ui.service:14-16` — the same obsolete "Registration
  (manual…)" framing, with a *correct* path

**Fix.** Delete the manual-registration instructions from all three;
replace with a one-line pointer to `install.sh` plus the `systemctl
--user enable` step, which the installer deliberately leaves to the human
(**`install.sh:94`** and `:99-100` print it as the next action).

**Pin (P-C1.1).** Rev 1 held `ui.service:15` up as "correctly updated."
It carries the identical defect with a right-looking path — which is why
the string-swap fix was wrong. **The defect is the obsolete instruction,
not the path inside it.** A fix that corrects the path and keeps the
instruction ships a lie with better spelling.

### 1.2 *(merged into §1.1)*

Rev 1 split the README duplicate from the unit comment. They are one
defect with three copies; splitting them produced the string-swap framing
the gate rejected. Merged. Rev 1's citation was also off by one — the
`ln -sf` line is `plugins/self-learn/README.md:104`, not 103; line 103 is
the ```` ```bash ```` fence.

**Rev-1 pin P-C1.2 is retired with this merge** (gate MINOR E: it
vanished unexplained). It required the unit comment and the README copy
to be kept in sync. Once both instructions are *deleted* per §1.1 there
is nothing left to keep in sync, so the pin has no referent. Recorded
rather than silently dropped.

### 1.2a Fix the bogus cross-reference at its source

`sentinel.py` cites "doc 13 §4.4" for the cross-repo pause contract in
**two** places — the module docstring at **`:3`** and the comment at
**`:55`**. No such section exists (doc 13's sections are
0,1,2,3,4,5,6,7,7.1,7.2,7.3,8); the authority is **doc 13 §6, lines
191-199**. This is the *origin* of §1.5's bad citation: rev 1 copied it
verbatim without checking, and the gate flagged the copy while the
source kept generating it.

**Fix.** Correct **every** occurrence in `sentinel.py` — file-wide, not
line-targeted. *(Delta-3 MINOR 3: revs 3-4 named only `:55` and missed
the docstring copy — defeating P-C1.19's own stated purpose in the very
section that states it.)*

**Pin (P-C1.19).** A wrong cross-reference that a spec has already
propagated once is a demonstrated hazard, not a cosmetic nit. Fix it at
the source or it will be copied again.

### 1.3 The plugin manifest points at the wrong repository

`plugins/self-learn/.claude-plugin/plugin.json:10,13`:

```json
"homepage": "https://github.com/AlexK-Notable/claude-skills",
"repository": { "url": "https://github.com/AlexK-Notable/claude-skills.git" }
```

Both name the *canon* repo. The product's repo is `AlexK-Notable/`
`self-learn` (D2).

**Fix (USER RULING 2026-07-19).** Repoint both to `self-learn`.

**Pin (P-C1.4) — rev 1's version of this pin is REVOKED.** Rev 1 required
verifying the substitute's visibility and forbade swapping one dead link
for another. `13-hosting-and-separation.md:407-409` ratifies
`github.com/AlexK-Notable/self-learn` as **private**, so the substitution
does point at a repo a stranger cannot reach. The user ruled this
acceptable — *"repoint to the self-learn repo for now. it's okay that
it's private."* Naming the right repo is correct today and becomes
publicly correct the day the repo opens. **Recorded as a knowing
trade-off, not an oversight** — a future reviewer must not re-raise it as
a defect.

**Pin (P-C1.3) — the author block is OUT OF SCOPE.** `plugin.json:5-9`
carries `author.name` / `author.email`; `plugins/self-learn/cli/`
`pyproject.toml:8` carries the same identity (a second copy the rev-1
sweep missed). Both are normal for an authored project. **Do not touch
either.** Removing identity is a values call the user has not made.

### 1.4 README documents a bootstrap the product does not perform

`README.md:45-46`:

> The ledger initializes on first use (`self-learn status`); register
> canon targets with `self-learn host add <path> [--skills-root]`.

Ground truth — `ledger.py::home_state` (`:47-76`) classifies four states;
`_home_gate` (`cli.py:456-470`) gates on them:

| state | meaning | gate |
|---|---|---|
| `missing` | no such dir | **exit 5** |
| `not-a-repo` | a dir, not a git work tree | **exit 5** |
| `uninitialized` | git repo, no layout dirs, no `hosts.yaml` | passes (warns) |
| `ok` | any `_LAYOUT` dir exists, or `hosts.yaml` does | passes |

`_LAYOUT = ("skills", "projects", "user", "telemetry")` (`ledger.py:28`).

**Precision correction (gate MINOR).** Rev 1 said layout dirs
"self-bootstrap." Only the dirs a capture's own scope needs are created —
a `--user` capture yields `user/` and `telemetry/`, never `skills/` or
`projects/`. The sentence is true enough to mislead, which is why
obligation O-1 asserts all four after `init` rather than after a capture.

**Fix.** Name the missing prerequisite (the git repo) and point at `init`.

**Pin (P-C1.5).** The sentence is *missing a prerequisite*, not false.
Fix by adding it. `home_state_message` (`ledger.py:79+`) already prints
the honest version; README must not contradict a message the CLI itself
prints.

### 1.5 Stale cache path in the plugin README

`plugins/self-learn/README.md:126` documents
`~/.cache/claude-skills/self-learn/autosync-pause`. `sentinel.py:56-58`
computes `base / "self-learn" / "autosync-pause"` (base = `$XDG_CACHE_`
`HOME` or `~/.cache`) — no `claude-skills/` segment.

**Fix.** Correct the doc to match the code.

**Pin (P-C1.6).** `sentinel.py` is the authority; the README is the copy.
Never "fix" the code to match the doc — the sentinel is a cross-repo
pause contract (**doc 13 §6 "Cache namespacing", lines 191-199** — rev 1
cited "§4.4", which does not exist; the bad reference was copied verbatim
from `sentinel.py:55` without checking).

### 1.5a *(REMOVED — carved out to Spec C3)*

Rev 5 folded a **live shipped bug** here: `home_state` decides
`not-a-repo` with `--is-inside-work-tree` (`ledger.py:67-73`), so a
nested non-repo home reads `uninitialized`, `_home_gate` waves it
through (`cli.py:469`), and captures commit into the parent repo.

**Delta 4 rejected the fold as a BLOCKER, and the rejection is correct.**
The reclassification is *breaking*: a nested non-repo home with a
populated layout classifies `ok` today and is a **working ledger** —
verified live — and would have become exit-5 at all ten `_home_gate`
call sites, making existing records unreadable. Worse, rev 5's cited
recovery (`init` step 5) requires an **empty** dir, so every home that
ever took a capture would be refused by the very path meant to rescue
it.

**Carved out to `c3-ledger-home-classification-spec.md`**, which is
blocked on a user ruling: the change removes read access to an existing
ledger shape and therefore needs a ruling on the same footing as
P-C1.12, not a scope-growth footnote. P-C1.22 and P-C1.23 move with it;
O-14 and O-15 are withdrawn (O-15 was *satisfiable-while-broken* —
delta-4 MAJOR 2).

**C1 reverts to its stated scope: defect repair with no design
question.** The `init` verb's own nested handling (§2.2 steps 4-6,
P-C1.20) is unaffected and stays here — it was verified complete across
all nine states by delta 3.

### 1.6 Items the rev-1 sweep missed

Surfaced by the gate's independent sweep, each re-confirmed here:

| Item | Disposition |
|---|---|
| `plugins/self-learn/README.md:82` — a **third** copy of the `-home-komi-repos-claude-skills` memory literal, in a shipped doc | **Defer to Spec D** with `cli.py:79` and `test_import_cli.py:115`. Noted so D's sweep covers all three |
| `README.md:38` — `git clone git@github.com:…/self-learn.git` (SSH, private repo) in the top-level install block | **In scope.** Same stranger-failure as §1.3, but here it is the *first* instruction. Per the §1.3 ruling the repo stays private, so the block must say so rather than read as a working public clone |
| `plugins/self-learn/cli/pyproject.toml:8` — author identity | **Out of scope**, folded into P-C1.3 |
| `test_hosting.py:777-778` — reads `~/repos/claude-skills` from the real home | **OUT OF SCOPE — rev 2's prescription is REVOKED (gate MAJOR B).** Rev 2 called it a machine-layout defect and directed a `tmp_path` redirect "like its neighbours." Wrong on both counts: `:780-785` already **skips loudly** with an explanation citing 13 §7.3, and it probes a **cross-repo sentinel contract with a foreign repo**. `conftest.py:13-32` pins only *self-owned* dirs (`XDG_CACHE_HOME`, `SELF_LEARN_CLAUDE_DIR`, transcripts) — a foreign repo's script cannot exist under `tmp_path`, so the redirect converts a real contract probe into a tautology that passes while the contract breaks. **Leave it alone.** Its `Path.home()` read is the point of the test, not a defect in it |

---

## 2. The `init` verb

### 2.1 Derivation from the ratified primitive

**`host add --init` is the precedent** (ratified `13-hosting-and-`
`separation.md:99-124`; shipped `hosts.py:187-261`). Rev 1 did not cite
it and contradicted it on four axes. Rev 2 derives from it:

| Ratified behavior | Ledger `init` | Same? |
|---|---|---|
| `is_repo_root()` decides "already a repo" (`hosts.py:194`) | reuse the same function | ✅ reuse |
| empty commit, pinned subject constant (`hosts.py:191`, `:261` `--allow-empty`) | empty commit, own pinned subject constant | ✅ mirror |
| clean refusal on a **regular file** (F8) | same refusal | ✅ mirror |
| zero-commit repo → no-op | → complete the layout + commit, then no-op | ⚠️ extended |
| nested init inside a parent work tree is "acceptable and intended" (`13-…:111-113`) | step 4 refuses a **non-empty** non-repo dir regardless of nesting | ⚠️ **narrower** |
| **"creates nothing"** — refuses a missing dir | **creates the directory** | ❌ **departs** |

**Row 4 note (gate MINOR H).** The nesting divergence is deliberate: a
host repo is often legitimately nested inside a larger tree, whereas a
ledger `git init`ed over foreign files is a data-loss shape. But rev 2
omitted it from a table that claims to enumerate the axes — an
undeclared fifth divergence. Declared now; it is narrower than the
ratified primitive, never broader.

**Pin (P-C1.12) — the departure is deliberate and user-ruled.** The
ratified "creates nothing" rule fits `host add --init`, where the target
is a repo the user already has and is pointing self-learn at. It does not
fit the ledger, which for a new user **does not exist** — that is the
dead-on-arrival defect this spec exists to fix.

The user's ruling and its reasoning (2026-07-19): *"we need to support
directory/repo creation if for no other reason than potential routing
needs. if we suggest to a user that a learning needs to take the form of
a new skill, but we don't provide them with a quick and easy way to
create a new directory or repo for said skill, that's problematic."*

**Pin (P-C1.13) — the departure is CONFINED to the ledger home.** The
ruling's reasoning reaches further than this spec (see §5); a builder
MUST NOT generalize it. `host add --init`'s semantics are unchanged by
this spec. Two commands, two documented behaviors, one stated reason for
the difference — recorded here so the inconsistency is never "tidied
away" by someone who finds it without the context.

### 2.2 What it does

**Pin (P-C1.10) — resolve-and-echo.** `init` honors `$SELF_LEARN_HOME`
exactly as every other verb does and **echoes the resolved absolute path
before creating anything**. The failure this guards (audit 2026-07-16
BLOCKER 11) is a wrong/unset home making a ledger invisible; an `init`
that silently creates a *second* ledger at a mistyped path reintroduces
it from the other direction. *(Rev 2 cited this pin without defining it —
gate MINOR E.)*

1. Resolve `$SELF_LEARN_HOME`; **echo the resolved path** (P-C1.10).
2. Path **exists on the filesystem and is not a directory** — regular
   file, FIFO, socket, device node, **or a dangling symlink** → refuse
   (F8 parity with `hosts.py:249`).

   **Pin (P-C1.24) — key on `os.path.lexists()`, not `exists()`.**
   *(Delta-3 NIT 4.)* A dangling symlink answers `exists() == False` and
   `is_dir() == False`, so an `exists()`-keyed step 2 lets it fall to
   step 3 (absent) → `mkdir` → raw `FileExistsError [Errno 17]` — the
   exact shape NIT 4 was folded to remove. `hosts.py` never hits this
   because **both** its branches refuse; step 3 *creates*, so mirroring
   `exists()` here is strictly worse than the primitive it copies.
   `lexists()` sees the link itself. Unreadable directories at steps 4-5
   are the same class and refuse with the same message.
3. Path is **absent** → create dir, `git init`, create all four
   `_LAYOUT` dirs, initial commit (P-C1.8). Done.
4. **`is_repo_root()` is False** and the dir is **non-empty** → refuse.
   Never `git init` over foreign files.
5. **`is_repo_root()` is False** and the dir is **empty** → `git init`,
   create all four `_LAYOUT` dirs, initial commit. *(A nested empty dir
   lands here and gets its own repo — doc 13`:111-113` blesses nested
   init.)*
6. **`is_repo_root()` is True** → **top up, per directory**: create
   whatever `_LAYOUT` dirs are missing; if the repo has **no HEAD**, make
   the initial commit. Report exactly what was added. If nothing was
   missing and HEAD exists → report already-complete and mutate nothing.

**Pin (P-C1.20) — the branch predicate is `is_repo_root()`, NEVER
is-inside-work-tree.** Rev 3 named `is_repo_root()` in §2.1 row 1 and
then branched steps 4-6 on "is a git work tree," which resolves via
`--is-inside-work-tree` (`ledger.py:67-73`). `hosts.py:194-204` states
the hazard explicitly: *"The existing is-inside-work-tree check cannot
carry this decision: it answers TRUE for a path swallowed by a PARENT
repo's work tree."*

The delta gate confirmed empirically that a fresh dir inside a parent
repo reports `home_state = uninitialized` **and** `is_repo_root = False`.
Under the wrong predicate, `SELF_LEARN_HOME=~/repos/someproject/ledger`
routed to step 6, created the layout dirs **inside the user's unrelated
repo**, and — because that repo already had a HEAD — never triggered
P-C1.16's commit, so no ledger repo was ever created and every later
ledger commit would land in the user's project. P-C1.10's echo does not
mitigate it: the echoed path is *correct*; the outcome is still wrong.

This is the third instance of one failure shape in this spec — **a
coarse predicate used where an exact one is required** (P-C1.14:
`home_state` vs. per-directory; P-C1.17: one pattern vs. per-surface
spelling; this pin). Treat any future `home_state` or work-tree check in
a decision path as suspect by default.

**Pin (P-C1.14) — the branch is per-DIRECTORY, not per-STATE.** Rev 1
refused on `uninitialized`; rev 2 "fixed" that by branching on the state
name, which the delta gate showed was still wrong: `home_state`
(`ledger.py:74`) returns `ok` when **any one** `_LAYOUT` dir *or*
`hosts.yaml` exists, so the realistic partial layout — a `--user`
capture creates exactly `user/` + `telemetry/` (verified empirically by
the gate) — reports `ok` and would have been refused, stranding
`skills/` and `projects/` permanently. A home that ran `host add`
(writing `hosts.yaml`, the only way it arrives per P-C1.9) with zero
layout dirs has the same problem.

`home_state` is a coarse any-of predicate and **must not gate a
per-directory action**. Step 6 consults the four dirs individually and
is idempotent by construction: it is safe on every repo state, and
"already a ledger" is an *outcome* it reports, never a precondition it
tests.

**Pin (P-C1.16) — every successful path ends with a HEAD.** Step 6's
top-up on a HEAD-less repo must commit (gate MINOR G): rev 2's step 4
completed the layout without committing, and since P-C1.15 forbids
keep-files, the new dirs were git-invisible and the repo kept no HEAD —
silently violating P-C1.8's own "HEAD from birth" parity on the one path
most likely to be taken by a user who hand-made the repo.

**Pin (P-C1.8) — initial commit, re-grounded.** Rev 1 justified this by
claiming a no-HEAD repo "is an untested edge for every producer."
**That was disproved by the gate**, which ran `self-learn teach --user`
against a bare `git init` home: exit 0, two clean commits.
`gitops.commit()` (`:490-521`) only reaches the HEAD-dependent
`ls-files --with-tree=HEAD` probe (`:482-484`) for paths absent from the
worktree, which never happens on first capture.

The commit stays, on the **real** ground: parity with the ratified
`--allow-empty` root commit (`hosts.py:261`), which gives the ledger a
HEAD from birth and one pinned, greppable subject. It is a
**consistency** requirement, not a correctness one — and this spec now
says so rather than inventing a failure mode.

**Pin (P-C1.15).** Use `--allow-empty` with a pinned subject constant.
Do **not** use keep-files: rev 1's keep-file approach implied a
non-empty commit and diverged from the ratified pattern for no gain.
Empty dirs not surviving a clone is acceptable — `init` recreates them,
and `discover_buckets` (`ledger.py:130-138`) filters on `is_dir()`, so a
missing dir is never a phantom bucket.

**Pin (P-C1.7).** `init` is **explicit**. No read verb creates the
ledger. Creating a git repo as a side effect of `status` would let a
typo'd `$SELF_LEARN_HOME` silently self-heal into a ledger the user never
asked for — the inverse of audit 2026-07-16 BLOCKER 11, which is exactly
why `home_state` exists. The `missing` / `not-a-repo` errors keep exiting
5 and gain a mention of `self-learn init`.

**Pin (P-C1.9) — no remote, ever.** `init` MUST NOT add, prompt for, or
infer a remote. `push_if_remote` (`gitops.py:651-658`) already returns
`ok=True, skipped=True` with no remote, so local-only is fully supported
and must be the default. **Scope note (gate MINOR):** doc 13's T-H1
(`:203`) describes the full home bootstrap as "git init, private remote,
layout dirs, hosts.yaml seeded." `init` covers **git init + layout dirs
only**; the remote and `hosts.yaml` seeding stay manual (`hosts.yaml`
arrives via `host add`). This is a deliberate subset, not an omission.

---

## 3. Test obligations

The code gate will mutate each of these to verify it fails.

- **O-1.** `init` on a missing path → git repo with a HEAD commit and all
  four `_LAYOUT` dirs; `home_state` is then `ok`.
- **O-2.** *(reworded — rev 2's version mandated the wrong behavior)*
  `init` on a **complete** ledger (all four `_LAYOUT` dirs present, HEAD
  exists) reports already-complete and mutates nothing. Rev 2 asserted
  this for any `ok` home, which — because `home_state` is an any-of
  predicate — **required** the refusal that MAJOR A identified as the
  bug. The test encoded the defect.
- **O-3.** `init` on an existing **empty non-repo** directory `git init`s
  in place, creates the layout, and commits (step 5).
- **O-4.** `init` on a non-empty non-repo directory refuses; `init` on a
  **regular file** refuses (F8 parity).
- **O-5.** `init` adds **no** remote; a routed lesson afterwards commits
  cleanly with no push failure — the regression `push_if_remote`'s
  docstring records as audit 2026-07-16 MINOR 7.
- **O-6.** *(rewritten twice — rev 1's version was unsatisfiable and
  destructive; rev 2's was vacuous, gate MINOR F)* **Per-surface
  assertions, each with the pattern that surface can actually contain:**

  | Surface | Assertion |
  |---|---|
  | `systemd/*.service`, `systemd/*.timer` | contains no `claude-skills` in any form |
  | `README.md` and `plugins/self-learn/README.md`, **install/registration blocks only** | contain no `repos/claude-skills` |
  | `plugins/self-learn/.claude-plugin/plugin.json` | covered by **O-8**, not here |

  **Pin (P-C1.17) — the pattern must match the surface's own spelling.**
  Rev 2 asserted `repos/claude-skills` across all three surfaces, but
  `plugin.json:10,13` spell it `github.com/AlexK-Notable/claude-skills`
  — which never matches. The assertion was **green while the defect it
  targeted was live**, and post-fix it constrained `systemd/**` alone.
  A single pattern applied to surfaces that spell the string differently
  is a test that certifies nothing.

  **Pin (P-C1.18) — there is deliberately NO global allowlist, because
  there is deliberately NO repo-wide sweep.** Rev 2 published an
  allowlist (`worker.py`, `hosts.py:9-22`, `cli.py:79`, …) whose entries
  all lay *outside* its own asserted surfaces. A builder reading that
  list as exhaustive would infer a repo-wide sweep was intended, write
  one, and re-create BLOCKER 2 — it would fire on `install.sh`,
  `docs/specs/**`, `test_batch_fixes.py:20`, `test_hosting_fixes.py:6`
  and more.

  **P-C1.11 is retired here** (delta-2 MINOR 3: it went missing with no
  record). It was rev 1's "search the concept, not one string spelling"
  pin — the instruction that would have broken cache migration. Rev 3
  replaced its mechanism with P-C1.17/P-C1.18 and dropped the number
  silently, reproducing the same audit hole as MINOR E. Its intent lives
  on in P-C1.18's closing sentence; the number is retired, not reused.

  Recorded as the *reason* for surface-scoping, never as an exclusion
  list to be applied to a broader sweep: `worker.py:119,126,131`
  (`_migrate_cache`, `MIGRATION_MARKER =
  ".migrated-from-claude-skills"`) **must** name `claude-skills` — it is
  what makes old-cache migration work. Breadth comes from **enumerating
  the surfaces that must be clean**, not from loosening the pattern or
  widening the scan.
- **O-10.** *(new — gate MINOR G/P-C1.16)* `init` on an existing git repo
  with **no HEAD** produces a HEAD; `init` on a repo with a **partial**
  layout (e.g. only `user/` + `telemetry/`, `home_state` = `ok`) creates
  the missing dirs and does **not** refuse. This is the MAJOR-A case and
  the one a real user hits.
- **O-12.** *(new — delta-2 MINOR 2; the BLOCKER-1 regression guard)*
  **Nested-path obligations.** With `$SELF_LEARN_HOME` pointed inside a
  parent git work tree:
  - an **empty** nested dir → gets its **own** repo (`git init` ran;
    `is_repo_root()` true afterwards) and the parent repo's index is
    **untouched**;
  - a **non-empty** nested dir → **refuses**;
  - the parent repo **tracks** no `_LAYOUT` path, and its index is
    unchanged.

  **Pin (P-C1.21) — assert TRACKED state, not filesystem cleanliness.**
  *(Corrected, delta-3 MINOR 2.)* Rev 4 said "creates no `_LAYOUT` dirs
  inside the parent repo" and "assert the parent's cleanliness" — both
  **fail on correct behavior**: a legitimate nested ledger at
  `<parent>/ledger/` puts real dirs under the parent's work tree, and
  `git status --porcelain` on the parent shows `?? ledger/`. Measured by
  the gate. The assertion must be `git diff-index --quiet HEAD` on the
  parent plus "no `_LAYOUT` path is *tracked* by the parent" — untracked
  presence is expected and correct.

  Rationale unchanged: the shipped-green failure mode was every
  child-side assertion passing while the dirs landed in the parent.
- **O-13.** *(new — delta-2 NIT 4)* `init` on a path that exists and is
  not a directory (test with a FIFO) refuses cleanly with the step-2
  message, never a raw OS error from `mkdir`.
- **O-11.** *(assertions named — delta-3 NIT 5; rev 4 said only
  "coverage," which a trivial test satisfies)*
  - `README.md` states the git-repo prerequisite and names
    `self-learn init` (§1.4);
  - `README.md:38`'s clone block discloses that the repo is private
    (§1.6);
  - **no occurrence of `§4.4` remains anywhere in `sentinel.py`** —
    asserted file-wide, not at `:55` (§1.2a).
- **O-14 and O-15 — WITHDRAWN to Spec C3** *(delta-5 BLOCKER 1 +
  MINOR 2)*. They asserted the `home_state` reclassification carved out
  at §1.5a. Rev 6 declared them withdrawn in three narrative places but
  **left them live here** — and because this section's closing note
  tells a builder to read §3 as a set, C1 still *commanded* the very
  reclassification the carve exists to prevent. Deleted now, and the
  withdrawal is recorded **in place**, where a reader of the obligation
  set meets the gap — the same remedy this spec applied to P-C1.2
  (§1.2) and P-C1.11 (O-6). O-15 additionally must not be revived
  as-written: it was satisfiable-while-broken (delta-4 MAJOR 2). C3's
  no-regression obligation must enumerate the **changed** classification
  set, never the unchanged one.

- **O-16.** *(new — delta-4 MINOR 4)* `init` on a **dangling symlink**
  refuses with the step-2 message. Measured: a dangling symlink is
  `exists() == False`, `lexists() == True`, `is_dir() == False`, and
  `Path.mkdir()` on it raises `FileExistsError [Errno 17]`. O-13's FIFO
  (`exists() == True`) **passes an `exists()`-keyed step 2**, so it
  cannot detect the very substitution P-C1.24 forbids. This obligation
  is the one that fails when the pin is ignored.

- **O-7.** The sentinel path documented in the plugin README matches
  **`sentinel.sentinel_path()`** — asserted against the function, not a
  literal. *(Rev 1 named `sentinel.cache_path()`, which does not exist;
  a test written against it would not import — `sentinel.py:53`.)*
- **O-8.** `plugin.json`'s `homepage` and `repository.url` both name
  `self-learn` *(rev 1 had no test for §1.3 at all)*.
- **O-9.** No systemd unit or README install block instructs a manual
  `ln -sf` of a unit `install.sh` already links (§1.1).

*(Obligation numbering is append-order across six revisions and is
deliberately not renumbered — O-N references appear in fold summaries
and gate records, and O-14/O-15 are withdrawn above. Read §3 as a set,
not a sequence.)*

---

## 4. Explicitly out of scope

- `DEFAULT_MEMORY_DIR` + its two doc/test copies → **Spec D**.
- chezmoi decoupling → **Spec C2**.
- `hosts.py:9-22` docstrings; `commands/teach.md:88`; routing-doctrine
  examples using the user's repos — illustrative, and changing them is a
  documentation-voice decision.
- Author identity in `plugin.json` / `pyproject.toml` → P-C1.3.
- `new-skill`'s missing scope gate (`verbs.py:605-648`) — a real latent
  defect, unrelated to portability. Named so a reviewer knows it was seen.

---

## 5. Consequence of Ruling 1 that this spec does NOT take

The user's stated reason for allowing creation was **routing**: if
self-learn proposes `new-skill`, it should be able to create what it
proposed. That reasoning is broader than the ledger home.

Today `new-skill` **does** create the plugin dir and `SKILL.md`
(`_apply_new_skill`, `verbs.py:1374`/`:1380` — rev 2 cited `:626`, which
is only the `plugin_dir` path assignment inside target resolution; gate
MINOR D), but **refuses** when the skills root has no
`.claude-plugin/marketplace.json` — "the scaffold appends an entry to an
EXISTING marketplace (08 §8.1); it never creates one." So on a fresh
machine, the `new-skill` destination is unreachable for exactly the
reason the ruling objects to.

**This spec does not change that.** Amending an 08 §8.1 pin is a separate
ruling on a separate surface. It is recorded here so the gap is tracked
rather than rediscovered, and so a reviewer can see the boundary was
drawn deliberately.
