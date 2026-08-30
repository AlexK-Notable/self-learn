# 15 — Orchestration runbook: how the agent rounds actually run

*Authored 2026-07-18 (FW-26) by the orchestrator, externalizing
operational knowledge that until now lived in session memory and an
out-of-repo handoff file. Test of done (set in `forward/
process-and-horizon.md` §1): a competent orchestrator who has never
seen this project can run a small round from this document without
violating a standing rule. Normative process authority stays with 03
(S-18 model split), 10 §8 (wave plan precedent), and the standing
rules; this file is the practice, not the policy.*

## 1. The round lifecycle

Every substantive unit moves through, in order:

1. **Spec** — the change lands as 09 §11 register entries (Y-numbers)
   / 10 §3 task rows (U-numbers) / dated amendments in the owning doc.
   Small spec changes (one row, one field) still count.
2. **Spec gate** — a blind reviewer (see §4) judges the spec BEFORE
   any build: implementable exactly as written? contradicts pinned
   decisions? every clause testable? Verdict SOUND / NOT SOUND;
   findings folded; delta re-check on the folds. Do not start a build
   on an ungated spec — the round-3 consent-hole BLOCKER and the
   maintenance-round unreadable-record NOT SOUND both prove the gate
   catches build-wrecking errors at paper cost.
3. **Build** — builder agent(s) in isolated worktrees (§3),
   test-first, suites + pyright green before handoff.
4. **Code gate** — a different blind reviewer against the diff + the
   gated spec, with **mutation verification**: for each load-bearing
   test the builder claims, the reviewer mutates the guarded code and
   confirms exactly that test fails. Verdict CLEAN / NOT CLEAN; fold;
   delta.

> **4a. Guard-amendment review (when the diff touches a protected file).**
> A file is protected if it is a key in `cli/tests/test_armor.py::ARMOR`.
> If the diff touches one, the code gate additionally checks, **against the
> unit's gated spec**, and reports each as its own finding:
>
> - **Deleted or renamed nodes.** Every key added to
> `Behaviour.missing` must be named in the spec, with the section that
> authorises it. A test that vanished without a `missing` entry is a
> BLOCKER regardless of whether the suite is green — `B1` should have
> caught it, and if it did not, the guard itself is the finding.
> - **Edited nodes.** Every entry added to `Behaviour.edited` must be
> reviewed as a diff of the test's **body**, anchor beside head, and the
> gate must say which failure the anchor version could see that the head
> version cannot. "Refactored" is not a reason. Note the edit may be
> anywhere in the body — a setup line, a `with pytest.raises(...)` block,
> a loop bound — not only in an assertion.
> - **Re-pinned fixtures.** Every `Fixture.repinned` entry is reviewed as
> production code: the gate diffs the fixture against its anchor bytes
> and mutates the new body to confirm a test reddens.
> - **Removed positive controls.** If a deleted or edited node's name, or
> the docstring of a **test function** (never the module docstring —
> a module-docstring reword is always free), contains `positive control`,
> `negative control`, `tripwire`, or `guard`, the finding is a BLOCKER by
> default. These are the tests that prove the other tests can fail.
> - **Edited exports.** Every entry added to `Behaviour.edited_exports` is
> reviewed as production code: the gate mutates the new body and confirms
> a test reddens.
>
> - **Anchor advance.** A diff that changes `ANCHOR` is **refused**. The
> anchor is advanced by the landing chain after the merge, never inside a
> reviewed diff (§5). Conversely, the gate's own starting evidence IS
> the previous chain run's `git diff --stat <old> <new> --
> plugins/self-learn/cli/tests` output: read it first, and treat anything
> in this diff that it does not explain as unaccounted for.
> (For `u-armor` specifically: once its own merge has landed, its
> UN1/UN3/UN5 criteria stop re-deriving this diff dynamically and
> pin permanently to that landing's own base/tip commit pair — see
> `test_armor.py`'s `_LANDING_BASE`/`_LANDING_TIP`.)
>
>
> The blindness rules (§4) are unchanged: the reviewer sees the diff and
> the gated spec, never `reviews/`. Source:
> `docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-spec.md`
> §4.8.

5. **Merge** — orchestrator merges (never the builder), resolves
   cross-unit joins by hand (§5), re-runs combined suites.
6. **Trials** — sandboxed live walk of the DoD legs (§6); log in
   `fixtures/ui-trials.md` (or `fixtures/trials.md` for CLI-only).
7. **Records** — review record in `reviews/` (gate chains, verdicts,
   mutations), status addenda in the touched docs, README revision-log
   entry, `records-index.md` row. Then commit; push stays manual (D3).

Docs-only status/record maintenance (revision logs, index rows, dated
disposition notes) is orchestrator-direct — no gate. Anything that
pins behavior gates.

## 2. Models (S-18 in practice)

Default: **builders = Sonnet, reviewers/spec-authors/judges = Opus,
orchestrator = the main session, never spawned as a subagent.** Pass
`model:` explicitly on every spawn — a subagent otherwise inherits the
orchestrator's model, which is the expensive mistake S-18 exists to
prevent. The user may override per-round (e.g. the 2026-07-18
maintenance round ran Opus builders on explicit instruction); the
override is per-round, not a new default.

## 3. Worktree discipline (every failure here has already happened)

- Cut builder worktrees **from the gated master tip**, and say so in
  the prompt ("fast-forward/verify you are at <sha> before building").
  A worktree cut before the spec merge builds against the wrong spec —
  this happened (U16) and cost a rebase.
- **Never `git add -A` from the repo root while agent worktrees
  exist** — worktrees under `.claude/worktrees/` staged as gitlink
  entries into a merge commit once; `.claude/worktrees/` is gitignored
  now, but the reflex should die anyway. Stage explicit paths.
- After merge: `git worktree list` → prune merged worktrees, delete
  their branches. Stale worktrees hide unmerged work and confuse the
  next round.
- Parallel authors WILL collide on register numbers and insertion
  points. **Pre-allocate in the prompts** ("you own Y-22 and the §11
  slot after Y-21; the other author owns Y-23") and resolve merge
  conflicts theirs-then-ours by number order. Auto-merge mis-orders
  register blocks — check §11 numeric order after every merge.

## 4. Reviewer isolation (the blindness rules)

- Blind reviewers **never see `docs/specs/self-learn/reviews/`** —
  state it as a hard constraint in the prompt. They review the
  artifact against the corpus and code, not against prior reviewers'
  opinions.
- Builders don't read `reviews/` either (they get the gated spec and
  the fold text in their prompt — everything they need travels
  explicitly).
- Reviewers get: the exact target (files/sections/diff), the
  dimensions to judge, the severity scale, the verdict rule
  (SOUND/NOT SOUND; CLEAN/NOT CLEAN), and for code gates the mutation
  mandate. Reviewers verify claims **by running things** — a review
  that only reads is an opinion.
- Delta re-checks go to the **same reviewer** (they hold the finding
  context); a fresh reviewer re-litigates instead of verifying folds.

## 5. Merging parallel units

- Merge sequentially, combined suites after each. Semantic join
  obligations (one unit's feature must ride inside another's
  mechanism — e.g. U17's budget probe inside U16's cached bundle) are
  **the orchestrator's to execute by hand** at the merge point; name
  them before the builds start so both specs pin toward the same seam.
- diff3 conflict blocks in spec registers: resolve with a scripted
  `re.subn` over the markers, theirs-then-ours by register number —
  never hand-retype spec text (a hand-resolve once corrupted a
  load-bearing schema bullet; script + assert the anchor).
- **The armor re-anchor rides inside the merge commit, never a
  follow-up.** After the last unit's suite/pyright bar is met and the
  merge is ready, run:

  ```sh
  git merge-tree HEAD "$BRANCH"                      # 1. preview
  git merge --no-ff --no-commit "$BRANCH"            # 2. merge, NOT committed
  #    ... resolve conflicts by hand ...             # 3. resolve
  python3 plugins/self-learn/cli/tests/test_armor.py --remeasure \
          --anchor "$(git rev-parse --short=7 HEAD)" \
  && git add plugins/self-learn/cli/tests/test_armor.py \
  && git commit --no-edit                            # 4. re-anchor RIDES INSIDE the merge
  ```

  `--remeasure` computes the anchor, the census and the owed set
  BEFORE writing anything, and refuses (writing nothing) on a
  non-empty owed set — a builder never advances `ANCHOR`; only this
  chain, after the gate has passed, does. The resulting
  `git diff --stat <old> <new> -- plugins/self-learn/cli/tests` is the
  NEXT code gate's starting evidence (§1.4a). Source:
  `docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-spec.md`
  §4.2.

  **Refusing is the normal FIRST outcome, and it refuses more than an
  owed node.** The same run also refuses when the advance would strand
  an exemption entry the new anchor no longer owes (`VACUOUS:`) or a
  transcribed literal in `cli/tests/test_armor.py::MEASURED` that
  the new anchor invalidates (`STALE:` — the numbers `BEH5`, `BEH7`
  and `EXM3` assert). All three are computed before anything is
  written and printed together, and the file is left byte-identical,
  so the `&&`-chain stops with the merge still uncommitted. Do exactly
  what the report says, **inside that still-uncommitted merge**:
  write the owed exemption entry, drop the vacuous one, and copy each
  printed `value at <anchor>:` into that `MEASURED` row's `value=`,
  re-dating its `reason`. Then re-run the same command — it writes,
  and the transcription rides inside the merge commit alongside the
  anchor advance. Between the transcription and that second run the
  armor suite is briefly red; that is inherent to check-then-write and
  is why the transcription is never committed on its own.

  **Never teach `--remeasure` to write a `MEASURED` value.** Not
  because those numbers are an independent check on the census — they
  are not. Whoever advances the anchor transcribes what the refusal
  printed, and that printout comes from the same extractor that fills
  the `ARMOR` table, so copying it into a second location corroborates
  nothing. Two other things are what the rule buys, and both are real:

  1. **A refusal against silent staleness.** Before this door existed,
     the anchor advanced, the write went through, and the suite went
     red *afterwards* — with assertions naming nothing about the
     anchor (measured 2026-08-29 in a throwaway clone: `2 failed, 39
     passed`, `BEH7` and `EXM3`). Now the motion stops at a named
     refusal before anything is written. A tool that rewrote the value
     would report nothing stale and advance unannounced.
  2. **A dated audit trail.** These literals change only through a
     deliberate, recorded, justified edit carrying a date and an
     anchor — the same discipline §4.7 already requires of every
     exemption entry, and reviewable the same way at the gate.

  **Who writes them.** The author of the landing, whoever that is. An
  **agent** performing the landing is a sanctioned author, exactly as
  for an exemption entry — commit `e59534b` landed agent-written
  exemption entries with dated justifications and that was correct.
  What is required is that the change be deliberate, attributed and
  dated; not that a person be at the keyboard. Source:
  `docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-spec.md`
  §4.2/§4.6, and `test_armor.py`'s own `ANC1`–`ANC6`.

  ### 5.1 The `--remeasure` refusal contract

  Written so another unit's runner can implement against it **without
  reading `test_armor.py`**. Measured against the CLI on 2026-08-29
  and pinned by `ANC6`; `ARM6` pins the success leg.

  - **Exit code.** `0` on success, `1` on every modelled refusal.
    Other codes mean the run did not get far enough to model
    anything — argparse exits `2` on a malformed invocation, and an
    unexpected `git` failure raises. Treat anything that is not `0`
    or a `1` carrying one of the tokens below as an unmodelled
    failure and do not proceed.
  - **Stream.** Every diagnostic goes to **stderr**. **stdout is
    always empty** — success and refusal alike. A caller that treats
    empty stdout as failure, or empty stderr as success, is wrong in
    both directions.
  - **Success.** stderr is exactly one line, and the file is written:

    ```
    ANCHOR <old7> -> <new7>
    ```

  - **The four legs, distinguished by a START-OF-LINE token.** Match
    anchored at the beginning of a line (`^TOKEN: `). The trailer is
    written to contain no bare token, so an unanchored substring match
    also happens to work — but the contract is the anchored form.

    | token | leg | file after the run |
    |---|---|---|
    | `OWED: ` | a node has no exemption entry covering it | byte-unchanged |
    | `VACUOUS: ` | an exemption entry the new anchor no longer owes (§4.7 `FW-140`) | byte-unchanged |
    | `STALE: ` | a `MEASURED` literal the new anchor invalidates | byte-unchanged |
    | `ANCHOR did not change (` | the no-op guard | **rewritten**, byte-identical content |

    The first three are **pre-write** and can appear together in one
    run — a landing behind a sibling unit routinely produces two or
    three at once. The fourth is **post-write**: it fires after the
    `os.replace()`, so the file is rewritten, with byte-identical
    content whenever the table was already current (measured, `ANC6`).

  - **Line shapes.**

    ```
    OWED: <armor-key>: <missing|edited>:<node-key>
    VACUOUS: <armor-key>: <entry>
    ```

    `VACUOUS:`'s `<entry>` is one of **seven** shapes — one per checked
    field. All seven are listed because a caller must not infer the set
    from a sample; the two that used to be documented alone hide both
    traps below.

    | door | `<entry>` shape | real example |
    |---|---|---|
    | `repinned` | bare — **no suffix at all** | `repinned` |
    | `missing` | `missing:<node-key>` | `missing:assign:REWRITTEN` |
    | `edited` | `edited:<node-key>` | `edited:func:test_wr7_reader_contract` |
    | `edited_exports` | `edited_exports:<def-name>` | `edited_exports:_skill_gates_yaml` |
    | `new_funcs` | `new_funcs:<function name>` | `new_funcs:_gate_probe` |
    | `new_scenario_keys` | `new_scenario_keys:<scenario key>` | `new_scenario_keys:budget_probe` |
    | `new_stmt_keys` | `new_stmt_keys:<part>\|<part>…` — **contains `\|`** | `new_stmt_keys:assign\|SESSION_ID` |

    **Two traps, both invisible from the `missing`/`edited` pair alone:**

    - `new_stmt_keys` entries are `|`-joined, so **never split an entry
      on `|`**. A nested key flattens to its leaves
      (`import|os|sys`), and a part carrying whitespace is replaced by
      the first 12 hex of its sha256 (`other|4f2a91c0d3be`) so the
      whole entry stays one `\S+` token.
    - `missing`/`edited` node keys **contain their own `:`**
      (`assign:REWRITTEN`, `func:test_x`), so an entry can hold three
      or more colon-separated parts. **Never split an entry on `:`.**

    Parse a report line as `line.split(": ", 2)` → `(token, armor-key,
    entry)` and stop there; then match `entry` against a door name,
    prefix-wise. Treat everything after the door as an opaque
    identifier — it is only ever echoed back to a human.

    `STALE:` is a **three-line record**, always in this order:

    ```
    STALE: <repo-relative path>: MEASURED['<row>'] (scope=<anchor|anchor+head|head>)
    STALE:       shipped value: <python repr>
    STALE:   value at <new7>: <python repr>
    ```

    Both values are `repr()`, so the third line's value pastes
    verbatim into that row's `value=`.

  - **Trailer.** After the report comes one multi-line explanation
    whose first line begins:

    ```
    refusing to write test_armor.py (
    ```

    It deliberately contains **no** bare `OWED:` / `VACUOUS:` /
    `STALE:` token. An earlier draft's trailer spelled all three out
    in its legend, which made an unanchored `"OWED:" not in stderr`
    false for *every* refusal — caught by this unit's own first test
    run, and now pinned by `ANC6`.

  - **What `VACUOUS:` covers.** Every anchor-diff field of every
    `ARMOR` row type, derived from the row types themselves rather than
    enumerated: `Behaviour.missing` / `.edited` / `.edited_exports`,
    `Fixture.repinned`, and `Additive.new_funcs` / `.new_scenario_keys`
    / `.new_stmt_keys`. Two fields are explicit, dated exclusions
    because they carry no anchor-diff state at all (`Behaviour.nodes`
    and `.dump_sha` are rewritten by the run itself; `edited_funcs` is
    a permanent allowlist per §4.4). A row type or a field that no rule
    covers makes the run abort **loudly** rather than pass silently —
    see `test_armor.py::VACUITY_MODEL` and `ANC7`. An earlier draft
    enumerated three families by hand and omitted `Additive`'s, so a
    landing could strand a declaration and leave `ADD1` red with rc 0.

  - **Order is not part of the contract.** Report lines follow
    `ARMOR` table order, then field-declaration order within a row.
    Match on tokens, never on position.

  - **What a caller should do.** rc `0` → proceed. rc `1` with any
    `^OWED:`/`^VACUOUS:`/`^STALE:` line → stop; the tree is untouched
    and the report says what to edit. rc `1` with
    `^ANCHOR did not change (` → stop; there was nothing to advance.
    rc `1` with none of these → an unmodelled failure; do not proceed.

## 6. Sandbox invariants (H-3 protection)

Dev/test instances ALWAYS redirect `SELF_LEARN_HOME` +
`XDG_RUNTIME_DIR` + `XDG_CACHE_HOME` to a scratch tree; never touch
the real `~/.self-learn`, real `~/.claude`, or real canon. **Never run
`self-learn host add` against the real ledger** — registration
consent is the human's (H-3); sandbox fixtures are fine. Live UI
trials run a second instance on a spare port (7457 precedent) against
the sandbox home. Windows for browser trials on DP-2, never DP-1.
`cp -r` of a uv project copies `.venv` whose editable install points
at the ORIGINAL tree — `rm -rf .venv` in the copy first, or mutation
tests silently run the wrong code.

## 7. Gotcha bank (host- and repo-specific)

- zsh `ls` is aliased to eza — `$(ls …)` in command substitution
  breaks ("invalid value for --icons"); use python glob or `\ls`.
- Bare `===` as an echo separator breaks zsh compound commands.
- `notify-send -A` on this host (swaync): always bound the wait
  (finite `-t`, or timeout(1)); expiry returns rc 0 with EMPTY action
  output — branch on output, not rc. Unbounded waits hang forever.
- The verb runner pushes a refresh on FAILED verbs too — any error
  rendering on an SSE page must survive a broadcast reload (the Y-16
  chokepoint-defer is the pattern).
- "disarm" is a PINNED term (survives-to-waiting); never use it in
  spec text for a clear-the-slot outcome.
- Playwright: `submit=true` on browser_type works for the pane send;
  `body.focus()` before keyboard y/Enter arming.
- pyright baseline: ui src = 0 errors required; cli src carries 56
  pre-existing — new code adds zero.
- pyright baseline CORRECTION (r1 gate fold, N-1, GATE3-safe: pure
  addition, the bullet above is unedited): re-measured 2026-08-28
  with `uv run --no-sync pyright src` from each of `plugins/self-
  learn/cli` and `plugins/self-learn/ui` — this is the instrument, a
  bare `pyright` off PATH resolves the wrong interpreter. cli src
  still carries **56**, unchanged; ui src carries **30**, not the 0
  claimed above — new code adds zero to either baseline.
- No sudo via the tool shell (no tty → pam_faillock locks the user
  account for 10 min).
- `~/bin/self-learn` (the install.sh wrapper) resolves via
  `readlink -f` to the ORIGINAL repo tree — in a worktree, tests that
  shell `shutil.which("self-learn")` can silently run master's CLI
  unless the worktree venv's bin is first on PATH. Same family as the
  copied-.venv gotcha; put `.venv/bin` first when running suites in
  worktrees (found by the B2 code gate, 2026-07-19).

## 8. Prompt skeletons (what every agent prompt must carry)

Builder: the gated spec text (or exact pointers), the worktree tip
sha, pre-allocated register numbers, the sandbox invariants (§6), the
suite/pyright bar, "test-first", and what NOT to touch. Reviewer: the
target, the blindness constraint (§4), dimensions, severity scale,
verdict rule, mutation mandate (code gates), and "verify by
executing". Both: `model:` explicit; worktree isolation for anything
that mutates files in parallel.

Reviewer, additionally: if the diff touches a key of `cli/tests/test_armor.py::ARMOR`, run §1.4a's guard-amendment review and report each clause separately.

## 9. Change control

Same as 08 §9: dated entries here when practice changes; anything
that would alter a settled decision routes through 03 first. New
gotchas append to §7 at round-close — the bank is this file's living
half.
