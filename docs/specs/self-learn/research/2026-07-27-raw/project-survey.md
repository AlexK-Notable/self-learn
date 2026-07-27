# self-learn — independent project survey (2026-07-26)

Method: read-only. Sources: full git history (367 commits, 2026-07-11 → 2026-07-26),
file/line/test counts via `git ls-files` + `grep -c "def test_"`, the spec corpus
(`docs/specs/self-learn/`), draft statuses, `journalctl --user` for the miner timer,
`systemctl --user` for unit state. I did **not** run the product, the test suite, or
read `~/.self-learn`. Claims marked *(measured)* come from commands I ran; claims
marked *(inferred)* or *(unverified)* are labeled as such.

---

## 1. What the project is (verified)

Your description is accurate. The repo README states it plainly: a capture → triage →
route system for lessons from Claude Code sessions; lessons accumulate in a git-backed
ledger (`~/.self-learn`), a background analyst proposes routings, and a **human-gated
review** compiles approved lessons into SKILL.md managed sections, CLAUDE.md, reference
files, PreToolUse guard scripts, and new-skill scaffolds. One correction of emphasis:
the web UI is not a general product surface — **doc 07 defines it as the G-3
adjudication (review) surface**. "UI work" and "review-surface work" are the same
thing here; that matters for the strategic question.

The repo is 15 days old (first commit 282a97c, 2026-07-11) and became publicly
installable on 2026-07-25 (1fef1d5: FSL-1.1-MIT, CLA, marketplace entry). One git tag
exists: `v1.1` (M3, 2026-07-17). *(measured)*

## 2. Surface map *(measured)*

| Surface | Location | Size | Tests | Last-touch profile |
|---|---|---|---|---|
| CLI | `plugins/self-learn/cli/src/self_learn/` | 27 files, ~17.9k lines | 65 test files, **1068** `def test_` fns (~21.4k lines) | `verbs.py` (3756) + `cli.py` (1943) touched today; capture/compile path (`teach.py`, `compilers.py`, `hook_compiler.py`, `import_*`, `scan.py`) untouched since 07-13..16 |
| Web UI (review surface) | `plugins/self-learn/ui/` | 23 py files ~10.4k lines + 19 templates + `app.js` (828) + `style.css` (1356) | 47 test files, **1055** `def test_` fns (~21k lines) | `routes.py` (2543), `app.js`, `style.css` all touched today |
| Walk instrument | `plugins/self-learn/ui/tools/` | 4 files, 1917 lines (`probe.js` 692, `sandbox_ui.py` 899, WALK.md protocol) | — (it *is* an instrument) | all touched today; probe at version 4 |
| Plugin layer | `skills/` (6 files, 917 ln), `commands/` (review.md, teach.md — 369 ln), `hooks/` (1 script, 70 ln) | small by design — thin callers over CLI verbs | hook script indirectly covered (`test_batch_fixes.py`) | stable |
| Deploy | `install.sh` (102), `systemd/` (3 units, 65 ln), 4 `scripts/` shims | — | thinnest-tested corner: UI `test_serve.py` (2), `test_cli.py` (4), `test_wrapper.py` (5); the one known-failing test (`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`) lives here | |
| Spec corpus | `docs/specs/self-learn/` | **97 files, ~30.4k lines** (drafts: 20 files, 12.4k lines) | 26 review records, 86-row records index | active daily |

Aggregate: ~30k lines of product+test code, ~30k lines of spec/records. The corpus is
as large as the codebase.

## 3. Trajectory *(measured from git log)*

Commit-date histogram: 07-11..13 corpus+M1 (62), 07-14..15 M2 (49), 07-16..17 M3 + UI
ship (100), 07-18..19 UI extension rounds (112 — the peak; 80 on 07-18 alone),
07-20..22 CLI defect repair (13: home-state predicate, chezmoi-as-capability,
portability + `init`, A1/A2), 07-24..25 scrub + public release + inflight-SSE (7),
**07-26: 24 commits — the entire walk program** (instrument, walks 1–5, resolution-
evidence unit, commit-drift unit, ring-targeting spec through 6 gate rounds).

Commit classification (subject prefixes, all 367): docs/spec ≈ **138 (38%)**, merge
records 37 (10%), ui feat/fix/test 49, cli feat/fix 6, cli+ui 5, miner 2, other/early
~116 (mostly pre-convention corpus and M1–M3 commits). File-touch counts across all
commits: docs 462, ui 439, cli 359. *(measured)*

Two corrections to your framing:

1. **The CLI is not long-neglected.** It received a focused defect-repair arc
   2026-07-20..24 (0f5c679, 97726df, 74fcfc7, b11d9aa) and `verbs.py`/`cli.py` were
   touched today (commit-drift verb evidence, resolution evidence). What is genuinely
   static is the **capture/compile path** (`teach.py` 07-16, `compilers.py` 07-15,
   `scan.py` 07-13) — but those shipped under M1–M3 gates with heavy tests; static
   reads as *stable*, not neglected. *(measured; "stable" is inferred)*
2. **The walk loop is younger than "several sessions" suggests.** All five walks in
   `fixtures/ui-walks.md` are dated 2026-07-26; the instrument itself (60e8b6f) is in
   today's commit block. The loop's self-sustaining character showed up on day one of
   its existence — which strengthens, not weakens, your concern. *(measured)*

## 4. Spec corpus health

20 drafts, 12,362 lines. My tally by actual disposition (cross-checked against
commits, not just status headers):

- **Shipped: 14 of 20** — commit-drift (3308d6a), resolution-evidence (29d1672),
  ui-inflight (f69d38e), pane-transcript/U22 (cf56a6c), f5-round/U19–U21,
  analyst-riders/FW-31/32 (da9e538), miner-visibility/FW-34 (8e48621), a1 (4950929),
  a2 (b11d9aa), c1 (74fcfc7), c2 (97726df), home-state (0f5c679), scrub (6105983),
  public-release (1fef1d5).
- **Gated SOUND, ready/unblocked, unbuilt: 3** — ring-targeting (rev 7, ready to
  build), **fast-lane (FW-35)** and **settings-surface (FW-30)** — both re-gated SOUND
  and declared "build-unblocked" in the FW map's 2026-07-19 disposition, untouched
  since. That is 7 days of sitting for the two, during which ~9 UI units shipped.
- **Parked/stalled: 3** — noop-hint (deliberately parked, split from ring),
  claude-md-parameterization (parent re-scoped after A1/A2 split),
  16-ecology (blind-gated NOT SOUND twice; Stage C awaits ratification).

Verdict: the spec process **ships** — 70% of drafts landed, most within 1–2 days of
gating. This is not spec debt in the "documents pile up" sense. Two real problems
though: (a) **stale status headers** — `analyst-riders-spec.md` says "Not gated, not
built" though FW-31/32 merged 07-19; `a1-labels-spec.md` still says "DRAFT — for blind
Opus spec gate" though shipped; `f5-round-spec.md` says "unratified" though U19–U21
merged. Anyone (human or agent) trusting headers will mis-plan. (b) **Process weight
per unit is high and growing**: ring-targeting — a fix whose entire defect is an
unscoped `querySelector` in `app.js:54-61` — consumed a 279-line spec and **6 gate
rounds** (3eb3849→0349fe9, 7 commits) before a line of build. The spec's own header
admits "Six rounds of gate findings were one drifted enumeration after another."
Median shipped unit costs ~5–8 commits of spec/gate/record scaffolding around 1–2 code
commits. That overhead is affordable for P0s; applied to every walk finding it caps
ship rate at ~1–2 units/session, which is exactly why findings outrun ships.

## 5. Dogfooding — the part of your red signal you have inverted

*(measured from journalctl)* The miner timer is enabled and healthy: nightly at 03:40,
last two runs completed OK — "2 landed, 0 folded, 0 recurrences, 3 fires" on both
07-25 and 07-26, ~4 min wall, 1.5 GB peak. The UI service is `inactive`, which is the
designed idle-exit posture (Y-14), not a failure.

So the **supply side runs itself and lands ~2 records/night**. The "11 pending,
oldest 3d" is therefore not a product defect signal — it is arithmetic: production is
automated, consumption is manual, and no review sessions are being run. The review
path itself is not under-developed: `/self-learn:review` is a bounded 10-card batch;
the worker's M2 fast path makes an analyzed record one tap; the web UI is the same
substrate with three sessions of polish on it. The friction that remains was
identified *by your own gated research* (`research/2026-07-18-ux-enhancement-survey.md`:
"the residual friction to remove is navigation/staleness/waiting and never the
decision gate") and the one built-for-throughput unit — **fast-lane FW-35 — is the
thing that has sat unbuilt for a week**. *(pending-count of 11 itself unverified — I
did not read the ledger; taken from your report.)*

The sharpest structural fact I found: the forward map (14, gated SOUND 07-18) says in
§1: *"every shipped round improved adjudication; almost nothing has yet tested supply
quality, the post-routing lifecycle, or distribution — and those are exactly where the
next phases live."* In the 8 days since that sentence was ratified, virtually every
shipped unit (~15) again improved adjudication. The map's own §5 trigger table lists
graduation-pressure, staleness, recurrence, and supersession as "built and shipped but
essentially unexercised." FW-1 (episode-brief live verification) still waits on
someone looking at a real miner cycle — which has now run nightly for at least two
nights with landings.

## 6. Under-developed areas, concretely

1. **Consumption of the loop** (see §5). Not code — sessions.
2. **FW-35 fast lane + FW-30 settings**: gated SOUND, build-unblocked 07-19, unbuilt.
3. **Packaging discipline now has an armed trigger**: FW-12 reads "Ledger schema
   migration machinery — BUILD — *Before any installed base exists*." The repo became
   publicly installable 07-25. One tag (`v1.1`, 07-17) predates the release; FW-11
   versioning/release discipline not started; FW-13 external docs = README only.
   Every day public without migration machinery makes a future schema change harder.
4. **Worker "Force run" wholly unresponsive** — found independently by walks 1, 2, 3
   *and* a hand-driven session (four sightings), still unfixed and untriaged into a
   spec. It is a worker-integration defect, not polish, and arguably outranks most of
   the remaining walk queue.
5. **Deploy/install corner**: thinnest tests (test_serve 2, test_cli 4, test_wrapper
   5), the suite's one known-failing test, and `install.sh` covered mainly by
   docs-consistency tests. Now user-facing post-release.
6. **Stale draft status headers** (§4) — cheap to fix, misleading until fixed.
7. **Lifecycle back-half** — graduation/staleness/recurrence/supersession flows have
   code and tests but zero live exercise (FW-6..9 all "first occurrence" drills).

Not under-developed despite appearances: the CLI core (1068 tests, recent defect
rounds), the hook layer (deliberately 70 lines, semantics all delegated to
`status --json --fast`), the miner (1882 lines, running nightly in production).

## 7. Pressure-testing your concerns

- **"UI-walk loop may be self-sustaining."** Confirmed, with numbers: walks 1–5 (all
  2026-07-26) produced ~26 findings; 2 units shipped from them (resolution-evidence,
  commit-drift — both today); 1 more spec'd (ring-targeting). Finding rate ~10×
  ship rate at current process weight. The loop will never self-terminate; it must be
  budget-terminated. **But** the instrument is not the streetlight you fear: it found
  a P0 correctness bug (W4-F1: verb keys act on record 1 regardless of ring — can
  deny the wrong record) and a silent-resolution hole in the *recovery* path (W3-F1)
  that a green suite had covered since it shipped. The instrument is good. The error
  would be letting instrument quality set the agenda — which the ratified FW map
  already warns against in its own §1.
- **"CLI neglected?"** Mostly no (§3). The genuinely unmeasured surface is not the
  CLI binary — it is **supply quality and the post-routing lifecycle**, whose
  measuring instrument already exists: real review sessions plus the already-shipped
  telemetry/near-miss/canary surfaces (FW-34). You don't need to build a CLI walk
  instrument; you need to run the loop and read its own journals.
- **"Review verb under-developed / costly?"** No. It is two mature surfaces over one
  substrate, with a worker fast path. The cost is session initiation, and the gated
  throughput unit (fast lane) is specced and waiting.
- **"Test-suite shape."** Both suites are heavy (1068 + 1055 test fns; the ~1082
  collected UI count is consistent with parametrization). Confidence is genuinely
  thin only at deploy/install (§6.5) and at anything requiring live state — which is
  precisely where walks and DoD trials keep beating gates (the records index lists at
  least five defects found live that CLEAN gates missed: SIGTERM-143 restart loop,
  unreachable contradicts-offer, reload-wiped error strips, dead Tier-2 resume,
  W3-F1). The suite is not where marginal confidence comes from anymore.
- **"Spec debt piling up?"** No — 14/20 shipped. The debt is *status-header rot* and
  *per-unit process weight*, not unshipped paper.

## 8. Recommendation

**Neither pure (a) nor pure (b). Sequence: finish the one P0, then pivot the next
sessions from building the review surface to running it, plus the smallest structural
payments.**

1. **Ship ring-targeting now** (half a session; spec'd, gated, P0 correctness — the
   only walk finding that can resolve the *wrong record*). Leaving a known
   wrong-target destructive-key bug unshipped while walking more would be indefensible.
2. **Then stop grinding the walk queue.** Declare a walk moratorium until the shipped
   backlog catches up. Batch the remaining walk findings (h/v dead keys, Enter-on-
   button, Escape-at-root, vocabulary, /report triple-count, worker Force-run) into
   **one maintenance round** like 2026-07-19's — one spec, one gate, many small fixes
   — instead of one 6-round spec each. The per-unit process weight is the actual
   reason findings outrun ships.
3. **Run real review sessions** — drain the 11. This is simultaneously: the red
   dogfood signal answered; the missing "instrument" for the un-walked half (walks
   couldn't reach analyzed/live states in the sandbox — W2-F5); the first live data
   for FW-1/FW-2/FW-3 (miner precision, proposal quality — the miner has now run
   nightly with landings and nobody has looked); and a live exercise of exactly the
   evidence surfaces you just built. If review friction is real, you'll feel it and
   **build fast-lane FW-35** (gated, unblocked, 7 days idle) with evidence instead
   of speculation.
4. **Pay the two cheap structural debts**: fix stale draft status headers (an hour),
   and open the packaging arc the corpus declared "next phase" on 07-18 — at minimum
   FW-11 (tag the public release) and FW-12 (schema migration machinery), because the
   public install on 07-25 armed FW-12's own stated trigger.

On your framing: the question "(a) grind / (b) pivot surface / (c) build instrument"
presumes the next unit is a build. The evidence says the binding constraint on the
product's value loop is **adjudication throughput — sessions spent using it** — and
every walk-and-fix session spends the review budget on the review surface instead of
on reviews. The tool's thesis is that corrections should stick; the 11-record queue
is the thesis waiting to be tested.

## Appendix: things I could not verify

- The pending-queue contents/count (constraint: no reading `~/.self-learn`). Taken
  from your session-hook report.
- Whether the worker (M2 analyst) has analyzed the 11 pending (same constraint; the
  hook would warn at >3 days worker-stale, and you did not report that warning).
- Actual pytest collected counts (did not run the suites; used `def test_` counts:
  CLI 1068, UI 1055).
- Walk-finding count "twelve from the last three walks": walks 3–5 carry 9 numbered
  findings + 4 cross-walk agreement rows; consistent with ~12 but the exact tally
  depends on how agreements are counted.
