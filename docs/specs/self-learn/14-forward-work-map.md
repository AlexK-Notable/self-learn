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
| `forward/ui-ux.md` | **D — UI/UX**: round 4, the JS harness, backlog burn-down, composition pressure, settings surface (FW-16…FW-19, FW-30, FW-37…FW-39) |
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
| FW-37 | Measure per-verb latency across the remaining 39 htmx verbs, then decide indicators on data | DRILL→BUILD | Unit 2's natural first job (R-1's deferral) |
| FW-38 | In-flight state-resync envelope (`sse.py` + new route) — closes the post-reconnect silent window | BUILD | After FW-37; needs the same SSE plumbing exercised there |
| FW-39 | Reusable, project-agnostic perceptual (ARIA-snapshot) test harness, own repo — self-learn as target #1 | BUILD | After FW-37/38 stabilize the pattern in-repo |
| FW-40 | **`reference` routes but does not deliver** — add a "target reachable from a loaded surface" selftest, re-deliver the stranded records | BUILD | **DECIDE half ANSWERED 2026-08-02 (S-23 (1))** — `reference` survives and gets its pointer. The selftest half **SHIPPED** with `U-reach` (`17aa06c`): `selfcheck._check_reach`, positive control 14 of 14 unreachable. Remaining: emit the pointer (`U-pointer`) and re-deliver. No longer gates FW-35 |
| FW-41 | `analyst.analyze()` can never return `hook` — its fixed key set drops the `hook:`/`examples:` the validator then demands | BUILD | **Now.** A bug against a *quoted* user ruling (S-10 scope ruling: the knob opens "fully… Considered and rejected: splitting the knob per authorship"). Fix, do not adjudicate |
| FW-42 | User-scope destination availability — `_SCOPE_DESTINATIONS["user"]` is a one-element tuple | BUILD | **DECIDED 2026-08-02 (S-23 (2))**: user scope's cheap surface is PATHED. So the menu gains the pathed-rules destination, **not** `reference` — and the `verbs.py:950-955` refusal of `reference` at user scope **stays** (correct its stale chezmoi reason to cite S-23). Unblocked; campaign unit `U-demand-user`. See S-22 |
| FW-43 | Stale premises in the analyst's system prompt — the chezmoi ground (retired 2026-07-24) at `routing-doctrine.md:124` + `verbs.py:950-955` + `fast-lane-spec.md:39`, and the autosync claim at `:129` (contradicted by user-ratified D3) | BUILD | Now; cheap text, and it currently mis-teaches every user-scope call. **Keep the no-secrets rule** — restate it on its own merits |
| FW-44 | Managed-section excerpt marker case mismatch — `worker.py` searches `SELF-LEARN:BEGIN`, `compilers.py` writes `self-learn:begin` | BUILD | Now. Live today for any target ≥200 lines (`~/.config/CLAUDE.md`, 703) — the analyst gets `lines[:60]` and the contradiction check is blind |
| FW-45 | Resolution observability — no telemetry event kind exists for route/reject/defer/graduate, and `routing.by` is a hardcoded `"human"` constant | BUILD | Before any autonomy-ladder measurement (12 §L1–L3): the evidence substrate those gates read does not exist |
| FW-46 | Implement S-21 — the analyst names the skill | BUILD | **UNBLOCKED 2026-08-02** — both sub-questions answered (§4): analyst proposes, CLI validates, human confirms; and the review surface gets a text field. Campaign unit `U-name`. Scope is wider than the one positional at `verbs.py:512`: **`routing-doctrine.md:262-263` still states the REVERSED pin** ("a `new-skill` proposal never names the skill") and is injected into the analyst's system prompt every run (`analyst.py:14`, `worker.py:621`), and `08-build-plan.md:469` still repeats its debunked "confirmed §4 human call" justification. Until that text changes, the model is told the opposite of the ruling on every invocation |
| FW-47 | Test-isolation residuals from the cache unit — `HOME`/hardcoded `~/.claude/CLAUDE.md` (F-4) and the module-scoped bring-up leak (F-5) | BUILD | Opportunistic. F-5's naive fix hides Chromium and silently skips 77 browser tests — pair with `PLAYWRIGHT_BROWSERS_PATH` |
| FW-48 | **FW-44's defect is cloned in the UI and a green test pins it as the contract.** `ui/pane.py` re-declares the wrong marker inside a hand-copied `_canon_excerpt`, and `ui/tests/test_pane.py` hand-writes that same wrong marker into its fixture — so the test passes *because* the code is broken. This is the excerpt the **human** reads in the review pane | BUILD | With or immediately after FW-44. Fixing `worker.py` alone leaves the human adjudicating from a head-of-file truncation, which is the surface that matters most. Found 2026-08-02 while spec'ing FW-44; tracked as campaign unit `U-marker-ui`. **Added 2026-08-02 after `U-marker` merged:** `pane.py:254`'s comment — "Mirrors `self_learn.worker._canon_excerpt` EXACTLY" — was true that morning and is false as of `bb89e43`; `worker.py:53` now imports the real constants while `pane.py:266-267` still hardcodes `_BEGIN_MARKER = "SELF-LEARN:BEGIN"`. Fix the comment with the code, or it becomes an invariant claim that actively misleads. Same shape at `models.py:98-99`, which still gives the retired chezmoi premise as its reason for excluding `reference` at user scope (the real reason is now S-23) |
| FW-53 | **A record file with invalid UTF-8 wedges a mine run — pre-existing on master, isolated 2026-08-02.** The crash is `_compose_prompt` → `_ledger_index` → `Record.from_path` → `read_text`, which runs **before** `_reconcile_and_land`, so `run()`'s outer handler turns the run into `status: failed`. Confirmed pre-existing by neutering `U-recur`'s backfill and reproducing it anyway; that unit adds no new exposure because the backfill is never reached | BUILD | Opportunistic. Same permanent-wedge class as the guard `U-recur` closes, through a door no unit currently owns. Found at `U-recur`'s code gate while hunting the unresolvable-record ground; recorded so it is not later mis-attributed as a `U-recur` regression |
| FW-52 | **FW-44's fixture catches case-blindness only when it is applied to BOTH markers.** The code gate modelled five implementations against three fixture shapes and measured it: a build that folds case on the *begin* needle only, or the *end* needle only, survives the entire suite. Mechanism — the shipped fixture uppercases both markers, so a half-blind build finds one and misses the other, falls into the `begin is None or end is None` branch, and lands on the same head truncation the criterion asserts. Closure is two more fixtures (begin-uppercased-only, end-uppercased-only) **added alongside** the shipped one, never replacing it: neither is red pre-fix, so only the both-uppercased fixture is a valid positive control | BUILD | Opportunistic, low. Disclosed by the gate as a coverage fact rather than a build defect — the spec pre-declared this outcome for one of its own mutations ("worth seeing"), so it is a known accepted limitation, not a regression. Recorded so a later reader does not mistake the green suite for full coverage of the unit's own subject. Found 2026-08-02 at U-marker's code gate |
| FW-49 | **"Zero `recurrence-suspect` events" has TWO dead producers, not one.** The channel-split diagnosis (campaign §7) names the miner; `worker._recurrence_suspects` (`worker.py:969-1016`) also spools `recurrence-suspect` and has likewise emitted zero. The campaign's `U-recur` fixes only the miner | BUILD | After `U-recur` lands, since it shares `worker.py` with FW-44. Until then the suspect surface stays under-reporting even once the miner crosses over. Found 2026-08-02 while spec'ing `U-recur` |
| FW-51 | **`graduate` on a REJECTED record succeeds, silently rewriting a denied lesson to `superseded_by: canon`.** Unguarded in the CLI — measured in a throwaway sandbox 2026-08-02, not inferred. `graduate` on an already-graduated record fails safe (nothing to commit); on a rejected one it goes through and inverts the human's decision | BUILD | Independent of the campaign; `verbs.py` is contended, so sequence it after. **Correction 2026-08-02 (audit):** this row previously said "not reachable through `U-grad-ui`'s surface (which gates the action to `routed`), so this is a CLI-side hole only." **That containment claim is false.** The status gate exists on the GET render only (`detail_resolved.html:87`); the POST half has none — `routes.py:1283` (`action_arm`) and `:1417` (`action_confirm`) validate only `if verb not in _KNOWN_VERBS:`. A hand-crafted POST with `kind="resolved"` against a graduated or rejected record still dispatches `graduate`. The shipped code says so itself at `ui/templates/partials/action_bar.html:152-159` (code-gate MAJOR 1), and `u-grad-ui-resolved-surface-spec.md:107` agrees while `:720` repeats the overstatement. Treat this as reachable from the UI, not CLI-only. Found 2026-08-02 while spec'ing `U-grad-ui`; containment corrected the same day |
| FW-57 | **`self-learn list` can HANG — not raise — on a `rules_paths` pattern with consecutive `**`.** `ledger_ops.py:667` emits a separate `(?:[^/]+/)*` per `**` segment, and adjacent groups nest exponentially; `glob.translate` — the oracle the docstring names — collapses consecutive `**` into one `(?:.+/)?`. Measured against a 24-segment non-matching path: 8 repeats → 0.24s, 10 → 3.36s, **12 → 33.5s**, versus 2µs through the oracle. A proposal with `gates.t2.answer: yes`, a long `match_path` and `rules_paths: ["**/**/**/…/x.py"]` wedges the listing. **This is the one failure mode `U-schema`'s S6 guarantee structurally cannot cover** — S6 catches `ProposalError`, and non-termination never reaches an `except`. It sits on the eligibility hot path. Two related prose claims that do not hold: `_compile_glob_pattern`'s *"Memoized: this runs on the eligibility hot path"* memoizes **compilation only** (three identical `_glob_match` calls: 0.516 / 0.495 / 0.491s), and `lru_cache` never caches exceptions, so an untranslatable pattern is re-translated for every record on every listing (`cache_info()` after five identical calls: `hits=0, misses=5, currsize=0`) | BUILD | **Highest of the audit rows.** Honestly scoped: the *intra-segment* blowup (`src/*a*a*a…*.py`) is NOT a divergence — the oracle is equally slow — so only consecutive `**` regresses against the named oracle. Fix is to collapse consecutive `**` the way the oracle does. CONFIRMED by execution 2026-08-02, post-wave code audit |
| FW-58 | **Five more `U-schema` production checks that no test can see.** Each, neutralized individually, leaves `test_decision_trace.py` at **73 passed** with the full-suite failure set byte-identical: `ledger_ops.py:822` (`g0.reject/defer.evidence` required-when-`yes`), `:912` (`t2.evidence` `required=True` — the "required BOTH ways" rule), `:896` (`t1.cost_bearing.evidence` required-when-`yes`), `:815` (`g0.<leg>.answer` yes/no enum), and `:630` (the `&`/`~`/`\|` class-body escape — *the unit's own false-refusal fix*). No fixture ever sets `gates.g0.reject/defer.answer: "yes"` or `t2.evidence: None`. The merge commit folded in "eight production checks no test could see"; the same sweep found eight and left at least these five | BUILD | Test-only. CONFIRMED by mutation 2026-08-02. Note the shape: the gate's sweep was thorough within the shapes it modelled and blind to the ones it did not — the same lesson `U-pathed`'s A17 taught at a different level |
| FW-59 | **A criterion whose docstring says it "must never be vacuous" is vacuous.** `test_decision_trace.py:1095` — deleting the `or not rules_paths` clause at `ledger_ops.py:929` leaves both halves green: with `rules_paths=[]`, `any(...)` over an empty list is `False` and the next check raises with a **byte-identical** message, so the empty-list case never discriminated the clause it targets. No behavioural bug (both refuse). Same file, `test_missing_gate_key_refused:434`: its `match=key` is satisfied by every message, because they all echo `list(TRACE_GATE_KEYS)` | BUILD | Low, test-only. CONFIRMED 2026-08-02. Worth fixing precisely because the docstring asserts the opposite — a comment claiming non-vacuity on a vacuous assertion is the strongest form of this project's signature defect |
| FW-60 | **Two `_glob_match` divergences from the named oracle, both benign but one contradicting a spec sentence.** 6000 fuzzed patterns × 60 paths: **564 mismatches, all one shape** — `_glob_match("", "*")` is `True`, oracle `False`; zero other semantic mismatches and zero non-`ProposalError` exceptions. Separately `_glob_match("/src/a.py", "**/*.py")` is `False` where the oracle is `True` — **a false refusal, the direction `u-schema-decision-trace-spec.md` §3.4a says cannot happen**, though §8-O6 claims the absolute-path behaviour deliberately. The docstring's "0 mismatches on a real tree" is literally true only because a real tree cannot hold an empty filename | BUILD | Low. Reconcile §3.4a with §8-O6 rather than changing behaviour. Also record here, disclosed-not-defect: `_glob_match(".claude/rules/ts.md", "**/*.md")` is `True` while `verbs._validate_project_globs` (`verbs.py:698`, `glob.glob(recursive=True)` with `include_hidden` defaulted **False**) refuses the same tree with "matches nothing" — §8-O6 rules `verbs.py` is the side that moves, but note the divergence lands exactly on `.claude/rules/`, this project's own rules-variant destination. CONFIRMED 2026-08-02 |
| FW-61 | **Mutation sweeps in this repo need `PYTHONDONTWRITEBYTECODE=1` and a cache clear, or they report survivors that never ran.** Python reused stale `__pycache__` when a source file was rewritten inside the same second, so the audit's first mutation run produced garbage — mutations recorded as "survived" that were never actually executed. That is itself a check passing for the wrong reason, at the level of the tooling the gates depend on | BUILD | Process, not code: fold into the campaign playbook's mutation-verification instructions so every future code gate carries it. Found 2026-08-02; the audit's own findings were re-run under the corrected setup |
| FW-54 | **`U-reach`'s shipped code and tests state a reason S-23 closed the other way.** `selfcheck.py:284-290` says the `user` row is "**dead code end-to-end until `U-demand-user`**", repeated at `test_selftest.py:511-514` and `:533-537` and four times in `u-reach-reachability-selftest-spec.md` (`:303-304`, `:526-531`, `:532-533`, `:627-632` — the last describing a "seam into this unit's file" for when B7 opens). Under S-23 (2) user-scope `reference` is dead **permanently**, not pending: the branch is correct, its stated reason is not, and the promised seam is moot. Note the spec was *partially* updated for S-23 (it cites it at `:573`), so half the file was reconciled and half was not | BUILD | Comment/docstring/test-name accuracy only — no behaviour changes. Cheap, and worth doing before someone builds the seam that S-23 removed the need for. Found 2026-08-02 by the post-wave bookkeeping audit |
| FW-55 | **Two shipped specs still describe mechanisms their own build replaced.** (1) `u-schema-decision-trace-spec.md:417-420` pins the glob recipe as "`[...]` → a passed-through character class"; shipped `ledger_ops.py:629-630` **sanitises** it instead (`\\` doubled, `&~\|` escaped), and the spec's §9 revision history stops at r3 with no entry for the code-gate round that changed it. The `re.error` backstop at `ledger_ops.py:675-680` and its two tests appear nowhere in the spec, whose final step (`:435-436`) ends at `re.compile`; and §3.4a's unconditional "the divergence direction is false accept, never false refusal" (`:480-482`) now holds *because of* the escaping the spec omits. (2) `u-analyst-proposal-fidelity-spec.md:61-66` states as measured that a proposal carrying `gates:`/`flags:`/`recommendation:` "validates clean today" — U-schema merged after and closed half of it (`ledger_ops.py:776-779`, `:784-789` now refuse out-of-set `flags:`/`recommendation:`; measured on master: `banana` → CLEAN, `flags:['banana']` → REFUSED) | BUILD | Doc-accuracy only. (1) is the exact failure the campaign playbook §5 warns about — a spec pinning an algorithm in prose that the build then had to correct — so it is worth fixing as the worked example of that rule. (2) is ordinary cross-unit staleness from concurrent merges. Found 2026-08-02 by the post-wave bookkeeping audit |
| FW-56 | **Citation drift across the wave's specs — roughly 80 `file:LINE` anchors no longer resolve.** Almost all were exact at each unit's own base commit and drifted from the units' own inserts and same-day sibling merges, so this is honest drift rather than fabrication. Four matter because they sit in load-bearing text: the campaign playbook's completion checklist (`r2-routing-campaign.md:542`) cites `miner.py:1174-1185` for the recurrence-suspect spool (now `:1236-1251`; `:1174` is a docstring tail) and `verbs.py:3147` for `confirm-recurrence` (now `:3204`; `:3147` is unrelated code), and `u-grad-ui-resolved-surface-spec.md:93-94` cites `verbs.graduate` at `verbs.py:2913` (now inside **`rehome`**'s refusal; `def graduate(` is `:2969`) and `:772` cites `ledger_ops.list_items:1108` (now mid-`validate_proposal`; `def list_items(` is `:1797`) | BUILD | Low individually, systemic in aggregate: a citation that resolves to *unrelated but plausible* code is worse than one that resolves to nothing, because a reader checking it may believe they have verified the claim. Consider whether load-bearing citations should name a symbol rather than a line. Found 2026-08-02 by the post-wave bookkeeping audit |
| FW-50 | **Quote containment closes the record-sourced legs only — the S-21 *flavour* stays open.** `U-schema`'s validator checks a cited quote against the record, which covers the load-bearing judgment gates; it does **not** check a quote against a canon **target file**, which is precisely the shape S-21's fabricated citation took (a pin quoting a document section that contained no such text). Deliberately out of scope there: it needs hot-path I/O, it reads mutable canon (an unrelated edit would silently re-queue a record through a swallowed exception), and it needs `verbs.py::_resolve_target`, which is contended | BUILD | After the campaign's `verbs.py` units settle. Recorded so a later reader does not read "quote containment shipped" as "fabrication is closed" — it is closed against records, open against documents. Found 2026-08-02 while spec'ing `U-schema` |

## 3. Sequencing: the recommended next three moves

> **DISPOSITION 2026-07-27 — this section predates the routing/pin audit and
> should not be read as current.** It was written 2026-07-18. None of its
> three moves touches routing, delivery, or the analyst, and
> `research/2026-07-27-routing-monoculture-and-pin-audit.md` subsequently
> established that all three are defective (FW-40…FW-45). An independent
> review (`research/2026-07-27-status-review.md` §3.1) flagged the mismatch;
> its argument on move 3 specifically: the repo is **already public**, so
> packaging no longer "freezes first impressions" — what a new user meets
> first is the routing layer, which is the broken part.
>
> **Two consequences pinned here, because they bind regardless of what the
> next sequence turns out to be:**
> - **FW-35 (fast lane) is HELD pending FW-40's ruling.** It is gated SOUND
>   and build-unblocked, and it tiers `reference` FAST on the grounds that
>   it is an "unloaded surface… affects zero activations" — true, and the
>   reason the tiering is wrong until `reference` delivers. Building it
>   first would industrialise the defect at throughput.
> - The replacement sequence is **not yet decided** — §4's outstanding user
>   rulings gate most of it. Do not treat the list below, or the review's
>   proposed ordering, as authorised.

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
| ~~**What should `reference` DO?**~~ | FW-40 | **ANSWERED 2026-08-02 → S-23 (1).** `reference` survives and gets its pointer (the 14 stranded records become reachable), but `paths:`-scoped rules become the **primary** cheap tier and DEMAND shrinks to lessons that are genuinely not file-scoped. No longer gates anything |
| ~~**Should user scope get a cheap surface at all**~~ | FW-42 | **ANSWERED 2026-08-02 → S-23 (2).** Yes, and it is **pathed rules only** — explicitly NOT a user-level reference file. Note the consequence: the `verbs.py:950-955` refusal **stays** (rewrite its stale chezmoi reason to cite S-23; do not delete it). FW-42 narrows to the UI destination menu |
| ~~**S-21 (a): is the analyst's proposed skill name trusted or CLI-regenerated?**~~ | FW-46 | **ANSWERED 2026-08-02 → S-21 amendment.** Neither: the analyst proposes, the CLI mechanically validates (kebab-case, plugin collision, marketplace entry), the human confirms. A rejected name comes back **with its reason**, never silently rewritten |
| ~~**S-21 (b): "change the name" has no UI**~~ | FW-46 | **ANSWERED 2026-08-02 → S-21 amendment.** Yes — the review surface gets a text field. Costed at ruling time as genuine UI work (new input, validation feedback, re-render), not a one-liner |
| Reverse either agent-authored narrowing of an explicit user request? (a pane agent that *acts* → may only propose, `09:1652`; *"potentially autonomous review, are goals"* → M-1 *"No exception, no flag"*) | `research/2026-07-27-…-pin-audit.md` §5 | **OPEN — surfaced, not recommended either way** |
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

- *2026-07-18*: **FW-26 SHIPPED** (`15-orchestration-runbook.md`).
  **FW-27 SHIPPED** (`records-index.md`, agent-built, 21/11/18 rows).
- *2026-07-19*: **FW-17 SHIPPED** (22 js-marked Playwright tests, gate
  CLEAN, merge 9c722e0) and **FW-18 SHIPPED** (unreadable-record
  degradation per the gated 09 §5/08 §1 pair, SSE pane_block
  root-cause fix, swapError NIT; gate CLEAN, merge 4358a9d) — record:
  `reviews/2026-07-19-maintenance-round.md`. Master counts: CLI 976/3,
  UI 758, pyright ui 0. **FW-30…FW-36 (minus FW-33's build) now have
  GATED BUILD-GRADE SPECS** in `drafts/` — five drafts, all SOUND
  (record: `reviews/2026-07-18-deep-specs.md`); doc-16 Stage C rides
  its stated ratification gate; builds await the user's go + the §4
  ruling queue.
- *2026-07-19*: **FW-31 + FW-32 SHIPPED** (Y-22 proposal-time lint +
  Y-23 destination-bounded contradiction check; gate CLEAN first pass,
  merged da9e538) and **FW-34 SHIPPED** (Y-24 near-miss visibility +
  canaries + 12 §12; gate CLEAN + 2 delta-verified MINOR folds, merged
  8e48621). The four blocking rulings were resolved and folded into
  the fast-lane/settings drafts (both re-gated SOUND, a01147e) —
  **FW-35 and FW-30 are build-unblocked**. The DoD walk found and this
  round fixed a latent Y-8 defect: the post-route contradicts offer
  was unreachable live (proposal swept before the handler read it;
  FakeRunner masked it) — U-C3/C3b shipped the pre-verb capture +
  reload-defer + the instrumented falsification of the follow-up
  alarm (stale cached app.js). Record:
  `reviews/2026-07-19-rider-nearmiss-round.md`. **New backlog minted:**
  multi-edge offer abandonment; promote bucket targeting (FW-34
  amendment); near-miss snippet cap calibration (WATCH — 600 chars
  refused the first real draft); static asset cache-busting.

- *2026-07-19 (evening)*: **FEEDBACK ROUND 5 SHIPPED** — nine user
  items investigated (2 were silent-no-op UX gaps, not dead keys),
  two rulings taken (guided commit-first, pin intact; pane transcript
  persist+resume). U19 (overlay containment + no-op hints +
  collapsible raw YAML + humanize_ts + destination glosses), U20
  (host commit-drift verb + armed strip leg), U21 (post-iterate
  change summary), U22 (durable pane transcripts + Tier-2 SDK resume,
  Y-28) — all two-gate CLEAN, merged, live-walked. The walk found and
  the round fixed two latent defects gates couldn't see: action-bar
  error strips reload-wiped (leg-(a) marker missing) and every Tier-2
  resume aborting (SDK identity-probe vs pyright stubs). Record:
  `reviews/2026-07-19-feedback-round-5.md`. Backlog minted:
  bulk-graduate errors invisible (hx-swap="none"); keyboard path to
  Resume; js-flake watch; guided re-add for chezmoi drift.

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
- *2026-07-25*: FW-37…FW-39 added per `drafts/ui-inflight-feedback-
  spec.md` §7.3/§9.2 (unit gated SOUND, builder-landed; corpus
  amendments per its own §7). FW-37 (per-verb latency measurement)
  is R-1's explicit deferral — indicators landed on the three confirm
  routes + the bulk-graduate loop only, refusing to decide the other
  39 htmx verbs' latency without data. FW-38 (the state-resync
  envelope) closes the residual post-reconnect silent window the unit
  measured and disclosed rather than fixed (§8 of that spec; R3-M2;
  recorded standing in `03-decisions.md` S-20 per that spec's R4-m3).
  FW-39 (the reusable perceptual harness) is that spec's Unit 2 —
  explicitly out of scope for the unit that just shipped (R-5: no
  harness generality there), factored out as its own future item
  instead.

## 7. Change control

Same discipline as 08 §9: items get dated disposition notes here when
they fire, die, or graduate into a spec; a new foreseeable-work class
gets a new FW number and a home in the right theme doc; anything that
would alter a settled decision's inputs goes through the 03 register
first. This file is re-audited whenever the README status header
advances a phase.
