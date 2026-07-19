# Review record — rider/near-miss round: FW-31/32 + FW-34 (+ ruling folds, U-C3/C3b), 2026-07-19

Origin: the user's "proceed with development" after the deep-spec
round. First round back on the S-18 default split (Sonnet builders,
Opus reviewers) after the one-round Opus-everything override.

## Ruling folds (spec gate before FW-35/FW-30 builds)

The user resolved the four blocking rulings: fast-lane sweep guard =
**option (A) count cap** (FAST_SWEEP_CAP=5 pinned, server-side batch
gate at the sweep loop, v1 code constant); settings tier table
**ratified as written**; miner timer **confirmed as spec'd**;
precedence **config.yaml > env > default** — overruling the draft's
env-wins recommendation (bootstrap keys excepted; invalid values fall
through loudly; sandbox-env caveat named). Blind Opus gate round 1:
**both drafts NOT SOUND** — the fold left env-wins text standing (two
BLOCKERs in settings §6 test obligations, one MAJOR in §1.3 pane
provenance) and the cap pin claimed a verb-layer home the no-bulk-CLI
doctrine forbids (MAJOR). All nine findings folded; delta to the same
reviewer: **both SOUND**. Committed a01147e. FW-35/FW-30 builds are
unblocked.

## U-C1 — analyst riders FW-31/32 (Y-22 lint + Y-23 contradiction): CLEAN first pass

Sonnet builder, worktree off 1e830b5, one commit (9f9335e).
`_validate_lint` in validate_proposal; `lint`/`conflict` card
sections (orders 50/55, after `discuss`); routing-doctrine.md §9
(lint rules + kind-aware non-punitive posture) + §10 (bounded
contradiction) — the rules living in the doctrine is what makes
detection three-producer; `_PROMPT_TEMPLATE` narrowed to the
destination-section scope with pointer-only lint references; Y-22/23
register rows. Blind Opus gate: **CLEAN** — all 12 claimed mutations
killed exactly the claimed test; reviewer's own probes confirmed
non-vacuous ordering coverage; secret-scan coverage of the new prose
verified in code (worker.py whole-file scan), not asserted. One MINOR
(DoD trial then unlogged — since executed, below), one NIT
(required-when-present coverage; accepted as-is). Merged da9e538.

## U-C2 — miner near-miss + canaries FW-34 (Y-24 + 12 §12): CLEAN + 2 MINOR folds

Sonnet builder, worktree off 1e830b5, two commits (fb91efb, 0797507).
Disposition fold + plain-words reason + scanned/capped snippet
(scan-before-`_outcome` at BOTH sites, closing the never-scanned
dropped-cap leak); the `rejected` double-absence (record= kwarg
removed); `near_misses[]` reader extension under the full injection
defenses; canary plant/score reusing `worker._tokens` + Jaccard;
Miner-region drill + `/mine/near-miss/promote` riding teach
(`--session`, never `--quote` — teach verified to accept it alone,
no parser change needed). Blind Opus gate: **CLEAN** — 6 claimed
mutations + 3 reviewer-devised; the +1 lock-invariant skip verified
legitimate. Two MINORs folded (900cf81): the disposition fold-table
regression test (the reviewer's `folded → other` remap had survived
all 220 tests; now killed) + spec notes (snippet carries scope/kind;
CLAUDE_SESSION_ID dormancy — `missed` scoring is inert until
something sets it). Delta to the same reviewer: **CLEAN**. Merged
8e48621 (09 §11 register conflict script-resolved ours-then-theirs;
Y-20..24 numeric order asserted).

## U-C3/U-C3b — the offer defect the trial found

The DoD walk exposed that the **post-route contradicts offer had
never been reachable in production**: the route verb removes the
proposal sibling at resolution (08 §1), the handler read
`contradicts` after the verb, and the old test passed via a
FakeRunner that deletes nothing — mock theater, unreachable until
Y-23 created the first real producer of edges. U-C3 (Sonnet, off the
merged tip): pre-verb `_capture_contradicts` in BOTH confirm routes
(the pane twin was the builder's find), reload-defer leg (d) on the
one existing `reloadDeferred()` predicate, deletion-faithful
`RouteSideEffectRunner` fixture. Gate: **CLEAN** (3 claimed + 2
reviewer mutations); two findings folded (marker-seam assertions;
failed-route-never-offers negatives) and delta-verified. Merged
d94b5ee.

The retrial STILL failed live — U-C3b instrumented the real ordering
(real uvicorn + CLI + Chromium, 11 trials): the coordinator's
applying-strip hypothesis was **falsified** (those frames are inert
client-side); leg (d) alone proved sufficient (removal reproduces the
symptom 4/4; restored holds 0/11); the retrial failure was a **stale
cached app.js** (StaticFiles ships no cache-busting — a tab from
before a deploy holds the old script). Deliverable: the stronger
mid-flight-ordering js test (leg (b)→(d) handoff asserted at the
settle instant). Gate: **CLEAN**. Merged post-0569567. The final
live retrial (fresh browser context) passed end-to-end: route →
offer rendered and held → Link contradiction → Enter →
`links.contradicts` written in one ledger commit.

## DoD trials

Full walk logged in `fixtures/ui-trials.md` (rider/near-miss round
section): lint live PASS first draw; contradiction fires on
same-operation opposite-instruction conflicts and defensibly declined
the spec's own borderline worked example; capped mine run PASS first
attempt with the cap-refused near-miss journaled; drill/Promote PASS
(one seeded promotable row, logged as such); canaries + DP-2 refusal
PASS; the offer flow FAILED twice for the two real reasons above,
then PASSED.

## Assembled master

**CLI 1009 passed / 4 skipped; UI 784 passed (incl. 24 js); pyright
ui src 0, cli src 56 pre-existing baseline.** Worktrees pruned,
branches deleted. Live service idle-exited (Y-14); next launch runs
the merged code.

## Open items minted by this round

1. **Multi-edge offer abandonment** (pre-existing, confirmed both
   sides of U-C3): confirming one edge HX-redirects away, abandoning
   the rest — needs the link-contradicts branch to re-render
   remaining edges.
2. **Promote bucket targeting**: a promoted project-scope near-miss
   lands in the UI server's CWD project, not the transcript's
   (snippet carries no project path). Mitigation: rehome verb. Fix
   needs a small FW-34 spec amendment.
3. **Snippet cap calibration (watch)**: MAX_NEARMISS_SNIPPET_CHARS=600
   made the first real near-miss non-promotable ({overlength}) — the
   cap looks too tight for real reader output; consider per-field
   caps or a raise (ruling-adjacent).
4. **Static asset cache-busting**: a stale app.js across deploys
   reproduces fixed bugs in the browser; version/hash the static
   URLs. Until then: hard-refresh after updates.

**Round CLOSED: FW-31, FW-32, FW-34 SHIPPED; ruling queue emptied of
build-blockers; FW-35 (fast lane) and FW-30 (settings) are next by
the user's rank, both spec-unblocked.**
