# 04 — Roadmap: milestones, acceptance, metrics

*No code until the user ratifies this corpus. Build in this worktree,
test-first, merge to master when green (repo convention).*

## 0. Pre-build acceptance fixture (defines "worth it" before anything exists)

> **Superseded in part, 2026-07-13/14 (Phase 0 outcome — see 08's
> Build-findings appendix + `fixtures/trials.md`):** original B, original C,
> C's named backup, and three replacement candidates all disqualified at the
> hardened gate (baselines pass — general good practice is baseline-native
> on a frontier model). **B := B3, the notify-send/swaync action-button
> hang — qualified 3/3 baseline FAIL, proven 3/3 post-routing PASS with
> attribution.** The C-half has no qualified candidate; the M1+M2 boundary
> decision (find a C-class environment-specific lesson, or re-scope the
> checkpoint to the proven B-half) is with the user. The protocol below
> remains the method record; do not execute the original B/C provocations.

*(Rewritten 2026-07-12 after the independent fixture review —
`reviews/2026-07-12-fixture-review.md`. The original wording carried a
class error: "pick from the existing canon" selects for lessons whose
baseline already passes, because this user hand-folds lessons into canon
effectively — the very fact `00-vision.md` opens with. Fixtures come from
the corpus **excluding any surface loaded during the trial**.)*

Three fixtures, **one per delivery surface** — the mapping is a constraint,
not a coincidence (a set that collapses onto one surface proves little).
`references/` append is deliberately left unproven: its value claim is
progressive disclosure, which no single-session A/B can score.

**A — hook surface: the `.storage`-while-running guard.** The claim under
test is **deterministic enforcement of an already-probabilistically-followed
rule** — not new model behavior: the rule already lives in home-assistant's
activation-loaded SKILL.md body, so a behavioral A/B has no delta arm.
Predicate: before routing, an Edit/Write targeting a `.storage/*.json` path
in a sandbox tree passes unguarded; after routing, the compiled PreToolUse
guard denies it. One mechanical trial each side; no live HA involved (the
guard's primary predicate is the path pattern — locally testable).
Deliberate side effect, stated so nobody misreads it: A's teach record
duplicates existing canon, so the analyst should **note the canon overlap
in its rationale** — a feature of the fixture, not a failure. (The
*bulk* already-canon flag does not apply: its pinned criterion is
`type: knowledge` from a canon source file, which A's `type: behavior`,
`source: teach` record structurally cannot satisfy — M3 review,
2026-07-12.)
**Evaluated at M3 exit**, where the hook compiler lives — A essentially
*is* M3's exit criterion; the M1+M2 checkpoint covers B and C only.

**B — user-scope CLAUDE.md surface: the silent-substitution rule.** The
lesson, sharpened (the built-in Edit tool self-verifies — the failure class
is scripted edits that exit 0 on zero matches): *"Before any in-place
scripted text substitution whose failure is silent (`sed -i`, `perl -pi`,
awk rewrite, ad-hoc script), first print the anchor's match count against
the exact target files; after the edit, verify the replacement landed. A
zero-match substitution is a failure to report, never a success."*
Provocation harness: a canned scratch repo whose contents subtly deviate
from the task's phrasing (e.g. "replace the `timeout = 30` setting in these
12 configs" where four spell it `timeout=30`), task phrased as a bulk edit.
Predicate: the transcript shows a match-count check against the target
files before the first substitution command, and the zero-match files are
reported, never claimed done. This is also the fixture that proves the
**E-17 chezmoi coupling**: after routing, run `chezmoi apply` and verify
the managed section survives.

**C — SKILL.md surface: a references-only lesson promoted into the loaded
body.** Pinned: **"a config-entry reload does NOT re-read `data.host` — an
IP change needs the stop→edit→start surgery"** (home-assistant; lives only
in `references/GOTCHAS.md`, absent from the loaded SKILL.md body — the
promotion *is* the mechanism self-learn claims to provide). Trials run in
**plan-elicitation mode** (sanctioned for fixtures whose real execution
touches live infra): provoke with a changed-IP scenario plus "state your
exact plan before touching anything," and score the stated plan. Predicate:
the plan says stop → edit → start (the config surgery), not "reload the
integration." Backup if C's baseline unexpectedly passes: the
registry-write-batching GOTCHAS entry, same shape.

**Qualification gate — a candidate is not a fixture until it passes this:**

1. **Absence proof**: the instruction is absent from every surface loaded
   during the trial (grep the SKILL.md body, both CLAUDE.md files, and
   hook outputs) — the class error that made the original fixture A
   unfalsifiable as specified.
2. **Baseline demonstrated, not assumed**: ≥3 pre-routing fresh-session
   provocations with **≥2 failures** for the stochastic fixtures (B, C);
   one mechanical pre-routing trial for A (the unguarded call passes). A
   fixture whose baseline doesn't fail cannot show a change.
3. **A written binary predicate**, fixed before routing — post-routing
   scoring is transcript inspection, never judgment.

**Trial protocol (all fixtures):** fresh session, cwd **outside this repo**
(its CLAUDE.md names and describes the skills under test), no priming — a
provocation that mentions the lesson tests reading comprehension, not
learning. Per trial, record the attribution set: `attributionSkill` (did
the skill activate — free and reliable, E-10), SessionStart hook output
(the hypr-doctor drift line varies day to day), and cwd — so a failed
trial names its broken link: capture, compilation, loading/activation, or
compliance. **Pass bar: 3/3 post-routing provocations for B and C** (these
are hand-picked best cases; anything less gets each failure attributed
before the fixture is called passed). One trial of a stochastic system is
an anecdote, not a result.

If routed canon doesn't move behavior on hand-picked best cases, no amount
of pipeline sophistication was going to matter — stop and rethink.

## M1 — The core loop (teach → triage → canon)

**Packaging + versions (pinned 2026-07-12, implementability review):**
self-learn is a new plugin at `plugins/self-learn/` — `.claude-plugin/
plugin.json`, a `marketplace.json` entry, `skills/self-learn/SKILL.md`,
slash commands under `commands/` (expected `/self-learn:teach`,
`/self-learn:review` — deployed by a new install.sh commands surface,
with a written flat-name fallback if colon-namespacing doesn't
materialize; `08-build-plan.md` §1 "Command deploy"), and the CLI at
`scripts/self-learn` (Python/uv,
shebang'd, no extension) symlinked to `~/bin` by `install.sh`'s existing
glob. The CLI locates the ledger via `SELF_LEARN_HOME` (default
`~/repos/claude-skills`) so captures work from any cwd and tests point at
sandbox repos. **Version↔milestone mapping: v1.0 = M1+M2; v1.1 = M3+** —
which places S-14's auto-memory importer in M1, below (its former M3
listing was stale). Full interface pins: `08-build-plan.md` §1.

Scope: record schema + ledger ops (create/supersede/move) · `self-learn`
CLI (`teach` with scope/type/structured-field/`--route` flags, `list`,
`status`, **`route`/`reject`/`defer`** — the resolution verbs own
compile+commit, sentinel set/heartbeat/release, self-push, and `--note`
(`resolution_note`); `graduate`, `--selftest`; `--json` on read verbs; the
slash command is a thin caller (S-2 amendment, `07-review-ui.md` §4);
secret scan on **every** record write) ·
`/teach` wrapper with in-session extraction (O-4) · backlog importer with
already-canon flagging (criterion pinned in `01` §3.2) · **auto-memory
importer** (S-14: origin-dedupe across all statuses per `02` §2's key
format; S-13's post-decision prune sweep with visible confirmation) ·
`/self-learn:review` command (bounded batches,
four-option cards with diff previews, bulk-acknowledge, TTL'd+heartbeated
autosync pause sentinel, **self-push at session end** — the sync's
clean-tree branch never pushes) · **pause-sentinel support in
`bin/claude-skills-watch`/`claude-skills-sync`** — a main-repo change on
master with its own test; the watcher honors no sentinel today, and it must
ignore only sentinels whose heartbeat is older than the ~2 h TTL · three compilers
(SKILL.md managed section, CLAUDE.md managed section — chezmoi-aware for
user scope (E-17) — references append) · commit flow with record→commit
linkage, one commit per routed lesson · the S-15 standing offer line
(settled yes — it lives in `~/.claude/CLAUDE.md` as a documented
chezmoi-managed install step, not compiler output; exact wording pinned in
`08-build-plan.md` §1, because the filter words are load-bearing spec).

Known residual, accepted: home-network's capture prompts commit+push this
repo directly, bypassing the sentinel — but they `git add` only their own
reference files, so they cannot sweep mid-review `.self-learn` state, and
their non-FF pushes already tolerate failure (`08-build-plan.md` §5).

**Exit criteria** *(tagged: [auto] = mechanically testable; [protocol] =
human-in-the-loop run, scripted in `08-build-plan.md`)*: (a) [protocol]
`teach --route` round-trips lesson→diff→commit on home-assistant in one
motion; (b) [protocol] backlog import of home-assistant's GOTCHAS
flags the already-canon majority into one bulk-acknowledge and produces a
card set — the behavioral minority (E-2: ~5–7) plus analyst-flagged misfiles
— that one bounded review session fully triages, ending in real commits;
(c) [auto] `--selftest` passes and fails loud when a target that should
have a managed section (≥1 routed record) lacks markers (`02` §4's
bootstrap rule covers first-route targets); (d) [auto] all writes honor
the layout/mutation rules in `02-schema.md` (verified by tests, including
the no-per-session-writes rule and the secret-scan refusal path);
(e) [auto] auto-memory import round-trips: entries appear in triage with
origin preserved, re-import resurrects nothing (including rejected
records), and the S-13 prune sweep edits `MEMORY.md` only for
terminal-status records, with visible confirmation.

Note: M1 has **no worker and no notifications** — analysis runs inline during
`review` (slower per item, zero infrastructure). This proves the loop's value
with the minimum surface, per the pre-mortem's lesson. Inline analysis
**writes the same `proposals/lrn-<id>.yaml` sibling the M2 worker will
write**, so `route` always reads a proposal file (with `--dest` as the
human override) and M1→M2 is a pure producer swap — never analysis logic
living in the slash command's prompt (`07-review-ui.md` §4 contract 1).

## M2 — Surfacing (worker + nudges)

Scope: detached pre-analysis worker (any host — **fully append-only**:
analysis proposals + merge proposals as new files, never record writes;
coalesced, flock'd per machine, restricted `--allowedTools`; analyst prompt
carries the **rejected-proposal digest** as negative exemplars — never
re-propose a declined lesson class, `01` §3.3; the digest reads
`resolution_note` where present) · SessionStart
pending-count line (manual `settings.json`
registration — a documented install step, not an assumed one) ·
**per-worker-run ambient notifications** carrying the aggregate line and
record ids in the payload (the TUI deep-link contract, `07-review-ui.md`
§4 — honored from day one) · threshold escalation `notify-send` ·
staleness alarm (computed by the SessionStart
hook from the worker's `~/.cache` last-run marker) · review consumes
precomputed proposals (one-tap fast path).

**Exit criteria:** (a) a taught lesson has a proposal attached within one
worker cycle without any session involvement; (b) clustering emits a
merge proposal for a planted near-duplicate pair, and the next review
collapses it into one routed survivor + one superseded record with
`sightings: 2`; (c) killing the worker
trips the staleness alarm within its window; (d) a 10-item triage session
completes in under ~5 minutes using only card taps.

## M3 — Remaining compilers + supply review (v1.1)

Scope: hook compiler (scaffold + settings.json
snippet, P9 flow) · new-skill compiler (CLI-owned template — S-6 as amended 2026-07-12; plugin-dev = optional post-hoc enrichment) · statusline
count (optional) · revisit O-3 (SessionEnd appender) and O-7 (ha-note
unification) against a month of observed supply. (`/teach` moved to M1 —
it's the primary capture UX, not an optional wrapper; O-4. The auto-memory
importer moved to M1 per S-14 — 2026-07-12; the *other-projects* memory
sweep remains O-2's G-2-gated extension, not M3 scope.)

**Exit criteria:** one real anti-pattern lesson routed end-to-end into a
working PreToolUse hook through the explicit-approval flow — **this is
acceptance fixture A (§0), evaluated here** (the hook compiler ships in
M3, so §0's staging puts A's trial at this exit, not the M1+M2
checkpoint).

## M4 — Gated futures

Whatever `03-decisions.md` gates open: standalone UI (G-3/O-1), statistical
layer (G-1 — evaluate SkillOpt-Sleep before building), portability
extraction (G-2), forensic drain (G-4), znote backend (G-5), staleness
revalidation (G-6). Each arrives with its own blind review (P10). The
team-scale staging that would fire most of these is `06-horizon.md`.

## Success metrics (honest at n=1 — counted, not modeled)

- **Time-to-triage**: median days a learning sits pending. (Target: the
  notification thresholds keep it under ~2 weeks.)
- **Queue health**: % of pending older than 30 days. (The ha-note failure
  signature was 100%; sustained >50% means P3–P5 failed and the design
  needs the standing review, not more capture.)
- **Routed-and-corrected**: routed lessons later *correctively* superseded
  (`supersedes: <record-id>` + recompile) — the honest "was it a good
  lesson" counter. **Excludes `superseded_by: canon` graduations**, which
  are successes, not failures (conflating them would inflate the bad-lesson
  rate — blind adjudication 2026-07-12). Per-lesson commits keep
  attribution clean; `git revert` is not the correction mechanism (S-12).
- **The acceptance fixture**: the three behaviors from §0, re-checked after
  routing — B (= B3, already proven 2026-07-14) at the M1+M2 checkpoint, the
  C-half per the boundary decision, A at M3 exit (§0's staging),
  each against its written predicate. This is the only behavior-change
  metric v1 claims.
- **Supply mix**: teach vs import vs (later) appender — tells us where
  lessons actually come from before we invest in more capture (O-3's input).

Explicitly *not* metrics in v1: surfaced counts, reputation, recurrence
statistics — nothing that needs volume this deployment lacks (P7).
