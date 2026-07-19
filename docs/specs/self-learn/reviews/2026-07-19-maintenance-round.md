# Review record — maintenance round: FW-17 + FW-18 (+ FW-26/27 riders), 2026-07-18/19

Origin: the user's "proceed with the maintenance round. use opus
agents" — an explicit per-round override of S-18 (Opus builders AND
reviewers; the Sonnet-builds default resumes after this round).
Scope per 14 §3 move 1: the JS DOM harness, the carried FW-18 fixes,
with the orchestration runbook (15) and records index riding.

## Spec gate (pre-build): the unreadable-record pair

09 §5 gained the "record file fails to read or parse" row; 08 §1
gained the `status --json` `unreadable` field. Blind gate: **NOT
SOUND** (F1: two of the three enumerated failure classes escape every
existing catch and 500 today — the row was written against loaders
that don't behave as assumed; F2: the count clause had no data source
and §2.1 forbids server derivation; F3 salvage layers indeterminate;
F4 I/O class missing; F5 overclaimed implication) → folded → delta:
09 row faithful but the 08 field spec was **NOT SOUND again**
(Problem A: pinned to `fast_status`, which the UI never calls and
which structurally cannot see the schema-validation class within its
budget; Problem B: no per-bucket granularity) → corrected (sourced
from `unparseable_pending` at `_cmd_status`'s existing iteration
site; `buckets[]` int + top-level total; `--fast` omits,
absence-means-unknown) → **delta 2: SOUND**. Committed b9cacc5;
builders cut from that tip.

## U-B1 — JS DOM harness (FW-17): CLEAN first pass

Opus builder, worktree. pytest + Playwright-python (no npm), one
in-process uvicorn of the real app against a sandbox ledger, 22
js-marked tests: the three reload-defer legs + defer-never-drop +
a fires-when-clear control; focus management incl. BOTH
not-stolen negatives; key dispatch pinned against `keymap_as_dicts()`
(the source module — drift-proof). Blind gate: **CLEAN** — the
reviewer re-ran the builder's four kills and devised two more
(defer-queue removal → 8 tests fail; focus-guard removal → both
negatives fail), verified the htmx event shapes against the vendored
minified source (refuting their own initial concern), and confirmed
the reload assertion detects a real navigation, not a proxy. Two
NITs accepted as-is (0.6 s false-pass ceiling bounded by the control
test; leaf actions covered via the dispatch mechanism). Merged
9c722e0.

## U-B2 — the three fixes (FW-18): CLEAN first pass

Opus builder, worktree, three commits. (1) Unreadable-record
degradation exactly per the gated pair — salvage layers, never-500,
degraded Detail template, Front/Bucket count lines, catch-set
widening in `_load_pending`/`unparseable_pending`/`read_record` +
`fast_status` decode-crash prevention; one justified-and-verified
scope extension (report.py's two record walks — the status payload
itself would have 500'd) and one unpinned name settled
(`total_unreadable`, mirroring `total_pending`). (2) SSE pane_block
duplication **root-caused**: `_finalize_current` awaited the publish
between appending the finalized block and clearing the in-flight
state — a snapshot in that suspension window rendered the block
twice; fixed by reordering to the consistent shape before the await,
byte-identical frames. (3) swapError added to the structural pin's
asserted set (U14-F2 NIT closed). Blind gate: **CLEAN** — six
mutations killed; never-500 hunted live with directory-swap,
symlink-loop, exotic-frontmatter, and list-frontmatter corruption
(all 200 + degraded render). Two MINORs recorded: test-hermeticity
(the `~/bin/self-learn` PATH wrapper can shadow a worktree venv —
gotcha-banked in 15 §7) and the bucket-page full-status walk cost
(spec-conformant; noted for the FW-19 watch). Merged 4358a9d.

## Assembled master

**CLI 976 passed / 3 skipped; UI 758 passed (736 + 22 js); pyright
ui src 0 errors, cli src 56 pre-existing baseline.** Worktrees
pruned, branches deleted, `self-learn-ui.service` restarted on the
merged code (active). Live-trial evidence for the degraded view is
the gate's own executed corruption battery (F6), logged here in lieu
of a separate sandbox walk — four corruption classes rendered
degraded-not-500 against the running app.

## Riders

FW-26 (15-orchestration-runbook.md) and FW-27 (records-index.md)
shipped 87ac35f; the B2 gate's PATH-shadowing find was appended to
the runbook's gotcha bank at round close, which is the runbook's §9
discipline working on its first day.

**Maintenance round CLOSED: FW-17 + FW-18 SHIPPED (FW-18 item 1
promoted to FW-20 remains open in the sync theme; the Esc-backstop
item remains WATCH).**
