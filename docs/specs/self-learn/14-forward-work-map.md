# 14 — Forward work map: the potential-work register (FW)

*Authored 2026-07-18 by the orchestrator at the user's direction
("project into the future… write up substantial documentation that can
provide a deep mapping of the potential required work"). Status:
**GATED SOUND 2026-07-18** — blind Opus review NOT SOUND (F1 BLOCKER:
an early draft scheduled an automatic ledger fetch, a D3 weakening
this map has no authority to make; F2 MAJOR: a G-6 scope misquote) →
all findings folded → delta re-check SOUND. Record:
`reviews/2026-07-18-forward-work-map.md`.*

*What this is: a **map of likely required work**, with triggers,
dependencies, decision points, and done-shapes — written before any of
it is scheduled. What this is not: a build plan (no task is authorized
by appearing here), a spec (it pins nothing — items graduate into 09/10
or a new numbered doc when they become real), or a promise (items exist
to be *ready*, several exist to be *watched*, and some should die
unbuilt if their trigger never fires). Authority relationships: 03's
register wins on decision state; 09/10 win on surface truth; the README
header wins on status. When an FW item becomes real work, it gets a
spec + its own gates per the standing two-gate discipline, and this
file gets a dated disposition note on the item.*

## 0. Reading map

| Doc | Theme |
|---|---|
| `forward/supply-quality.md` | **A — Supply quality**: the miner becomes the main character (FW-1…FW-5) |
| `forward/canon-lifecycle.md` | **B — Canon lifecycle back-half**: first-firing readiness for graduation, staleness, recurrence, supersession (FW-6…FW-9) |
| `forward/packaging.md` | **C — Packaging & distribution**: the next major phase, mapped (FW-10…FW-15) |
| `forward/ui-ux.md` | **D — UI/UX**: round 4, the JS harness, backlog burn-down, composition pressure, settings surface (FW-16…FW-19, FW-30) |
| `forward/sync-and-fleet.md` | **E — Sync & multi-machine**: push-state visibility and the divergence playbook (FW-20…FW-22) |
| `forward/platform-drift.md` | **F — Platform drift**: the risks we don't control, and the watch protocol for each (FW-23…FW-25) |
| `forward/process-and-horizon.md` | **G — Process debt & horizon discipline**: orchestration runbook, records index, suite budget, team-scale guard rails (FW-26…FW-29) |
| `forward/worker-ecology.md` | **H — Worker ecology**: the four-worker community, its channels (field reports, briefs, doctrine drafts), the (c)-ish domain boundary, and the user's 2026-07-18 feature ranking (FW-31…FW-36) |

## 1. Where the system stands (one paragraph, pointers only)

M1–M3 shipped, v1.1 tagged; the G-3 surface is live and has absorbed
seven extension units (U12–U18, carrying Y-11 and Y-13…Y-21); the capture-and-route half
of the loop is mature and in daily solo use (README header + revision
log; 03 G-3 row for counts). The structural observation driving this
map: **every shipped round improved adjudication; almost nothing has
yet tested supply quality, the post-routing lifecycle, or distribution
— and those are exactly where the next phases live.**

## 2. The FW register

One line per item; depth lives in the theme docs. **Type** column:
BUILD (work to do), DRILL (exercise/verify something already built),
DECIDE (a user ruling is the deliverable), WATCH (monitor a trigger;
building early is the failure mode).

| # | Item | Type | Trigger / when |
|---|---|---|---|
| FW-1 | Episode-brief live verification (open U18 DoD leg) | DRILL | Next real miner cycle |
| FW-2 | Miner precision/recall observation window → tuning pass | DRILL→BUILD | ~2 weeks of journaled cycles |
| FW-3 | Rejected-proposal digest loop validation | DRILL | First rejections with notes accumulate |
| FW-4 | DP-2 live recall test (the deliberately-uncaptured lesson) | DRILL | Standing; scored when the miner meets it |
| FW-5 | Supply-mix + queue-health accounting | DRILL | **2026-08-17** (O-3/O-7 revisit) |
| FW-6 | Over-cap graduation pressure: first-firing readiness | DRILL→BUILD | First 02 §4 over-cap WARNING |
| FW-7 | G-6 staleness revalidation | BUILD (gated) | First routed lesson observed stale (03 G-6) |
| FW-8 | Recurrence resolution flows: first-firing readiness | DRILL | First confirmed recurrence |
| FW-9 | Supersession end-to-end drill (correct a routed lesson) | DRILL | First genuinely wrong routed lesson |
| FW-10 | Distribution shape | **DECIDE** | Opens the packaging phase |
| FW-11 | Versioning + release discipline | BUILD | With FW-10 |
| FW-12 | Ledger schema migration machinery | BUILD | Before any installed base exists |
| FW-13 | External-facing docs (quickstart; corpus stays internal) | BUILD | Packaging phase |
| FW-14 | Install/upgrade story + environment preflights | BUILD | Packaging phase |
| FW-15 | SDK pin drift management (verify-at-build as release gate) | BUILD | With FW-11 |
| FW-16 | Round 4: the composition/IA pass | BUILD (parked) | User unparks (O-9) |
| FW-17 | JS DOM harness | BUILD | Next; cheapest before further UI rounds |
| FW-18 | UI backlog burn-down (5 carried items) | BUILD | Opportunistic; batch with FW-17 |
| FW-19 | Detail-page information-architecture pressure | WATCH | Region count grows again |
| FW-20 | Push-state surfacing in UI (fail + ahead/behind) | BUILD | Before a second capturing host |
| FW-21 | Ledger divergence/conflict playbook | BUILD (doc-first) | Before a second capturing host |
| FW-22 | D3 posture review at fleet scale | **DECIDE** | Second host captures regularly |
| FW-23 | SDK upgrade cadence + verify-at-build standing gate | WATCH→BUILD | Any SDK bump |
| FW-24 | Native per-skill memory watch (S-1 reopen protocol) | WATCH | Anthropic ships it (E-9) |
| FW-25 | Plugin/skill format drift watch | WATCH | Claude Code release notes |
| FW-26 | Orchestration runbook, in-repo | BUILD | Soon; knowledge currently session-fragile |
| FW-27 | Review-record + research index | BUILD | Cheap; with FW-26 |
| FW-28 | Suite runtime budget | WATCH | CI wall-clock exceeds ~3 min |
| FW-29 | Team-scale guard rails (what NOT to build early) | WATCH | Standing; see 06-horizon triggers |
| FW-30 | Settings surface in the web UI (models-per-role, miner cadence, doctrine/rubric editing) | BUILD | User-requested 2026-07-18; dated addition per §7 — see `forward/ui-ux.md` §5 |
| FW-31 | Proposal-time lint: trigger recognizability + why-clause (analyst rider) | BUILD | Upranked by user 2026-07-18; supersedes cold-read at entry level |
| FW-32 | Destination-bounded contradiction check (analyst rider) | BUILD | Upranked 2026-07-18; canon-wide detection stays G-5-gated |
| FW-33 | Portfolio auditor: receipts digest + worker briefs + one-time why-audit | BUILD (deferred) | Upranked 2026-07-18; builds only when the digest is spec'd — the (c)-ish ruling |
| FW-34 | Miner near-miss visibility (+ canary recall checks) | BUILD | Upranked 2026-07-18; mostly rendering over the existing run journal |
| FW-35 | Review fast lane, stakes-tiered by destination | BUILD | Upranked 2026-07-18; hooks/user-scope never qualify — invariant, not default |
| FW-36 | Worker ecology channels: miner field reports + pane doctrine drafts | BUILD | The ecology's two new information products; constitution in `forward/worker-ecology.md` §4 |

## 3. Sequencing: the recommended next three moves

1. **FW-17 + FW-18 (+ FW-26/27 riding along)** — small, protective,
   and every later UI round gets cheaper for it. No user decisions
   required; pure build + records hygiene.
2. **FW-16 (round 4)** when the user unparks it — *before* packaging,
   because packaging freezes first impressions and round 4 is
   predicted to be an information-architecture pass, not styling
   (rationale in `forward/ui-ux.md` §2).
3. **FW-10…FW-15 (packaging)** as the declared next major phase — with
   migrations (FW-12) and external docs (FW-13) treated as first-class
   parts, not afterthoughts.

Riding alongside on their own clocks, independent of the sequence:
FW-1 (next miner cycle), FW-5 (2026-08-17), and every WATCH item.

## 4. The consolidated decision queue (user rulings outstanding or foreseeable)

The rulings below bind work; none should be absorbed silently. Existing
open ones are listed with their home row; foreseeable ones name the
moment they'll be asked.

| Decision | Home | State |
|---|---|---|
| Tighten terminal `host add` (no `--init`) against paths inside a parent work tree? | 03 G-3 dated note / Y-17 fold | **OPEN — awaiting yes/no** |
| Widen the pane agent's canon read scope to whole host roots? | 03 G-3 row (user-ratifiable) | OPEN — default conservative, unexercised |
| Distribution shape: binary vs `uv tool install` vs both | FW-10 | Foreseeable — opens packaging |
| Unpark round 4 — when? | O-9 | User's call; sequencing above recommends pre-packaging |
| D3 manual-push posture at fleet scale | FW-22 | Foreseeable — only if a second host captures |
| Miner autonomy ladder: any step up? | 12 §staged-autonomy | Foreseeable — only after FW-2's evidence window |
| FW-30 settings exposure tiers: what's freely exposed vs guarded vs never | `forward/ui-ux.md` §5 | Foreseeable — routes first when FW-30 is spec'd |
| S-18 model split — reopen? | 03 S-18 | Only on material model/pricing change |

## 5. The trigger table (event → dormant mechanism → FW item)

The lifecycle mechanisms below are **built and shipped but essentially
unexercised** — each activates on a first occurrence. The plan is
readiness, not rebuilding; details in `forward/canon-lifecycle.md`.

| First occurrence of… | Activates | FW |
|---|---|---|
| 02 §4 over-cap WARNING on a route | Graduation-pressure flow (oldest-entries card) | FW-6 |
| A routed lesson observed stale in live canon | G-6 gate (03) — staleness revalidation build | FW-7 |
| A confirmed recurrence (`confirm-recurrence`) | Revise/escalate/tolerate/retire resolution flow | FW-8 |
| A routed lesson found wrong | Supersede-and-recompile path (S-12) end-to-end | FW-9 |
| A second host/user wanting an install | G-2 proper + FW-21/FW-22 | — |
| Anthropic ships native per-skill memory | S-1 reopens (its stated input changed) | FW-24 |
| 2026-08-17 arrives | O-3/O-7 metrics revisit | FW-5 |

## 6. Non-goals, restated (the map's guard rails)

Unchanged from 03/06 and binding on this map's execution: no autonomous
writes to canon, ever (P1 generalizes, never relaxes); no team-scale
mechanism (PR routing, scope tiers, provenance tiers) before its 06
stage trigger; no modeled metrics — counts only; no vector/retrieval
infrastructure without G-5's observed failure; the Go port stays parked
(O-8) and is not packaging's fallback plan until packaging *demonstrably
fails* on Python; round 4's principles bind all interim UI work even
while the pass itself is parked (O-9).

## 6a. Dated dispositions

- *2026-07-18*: **FW-26 SHIPPED** (`15-orchestration-runbook.md`;
  round-reviewer verification against repo reality owed at the
  maintenance round's close). **FW-27 SHIPPED** (`records-index.md`,
  agent-built, 21/11/18 rows). **FW-17 + FW-18 IN BUILD** — the
  maintenance round is running (user-directed, Opus agents by
  explicit per-round override of S-18): unreadable-record spec pair
  gated SOUND (b9cacc5), two builders in worktrees.

## 6b. Dated additions log

- *2026-07-18*: FW-30 (settings surface) added on user request.
- *2026-07-18 (later same day)*: FW-31…FW-36 added from the user-seat
  pain-point analysis + the user's re-ranking + the worker-domain
  ruling ("(c)-ish": three domains pinned now — per-record judgment /
  transcript intake / portfolio synthesis — auditor built only when
  FW-33's digest is spec'd). Full ecology design:
  `forward/worker-ecology.md`. Downranked in the same ruling:
  challenge verb (deferred), cold-read audit (superseded by FW-31 at
  entry level).

## 7. Change control

Same discipline as 08 §9: items get dated disposition notes here when
they fire, die, or graduate into a spec; a new foreseeable-work class
gets a new FW number and a home in the right theme doc; anything that
would alter a settled decision's inputs goes through the 03 register
first. This file is re-audited whenever the README status header
advances a phase.
