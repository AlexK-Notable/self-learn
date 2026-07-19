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

## 9. Change control

Same as 08 §9: dated entries here when practice changes; anything
that would alter a settled decision routes through 03 first. New
gotchas append to §7 at round-close — the bank is this file's living
half.
