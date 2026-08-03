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
| FW-44 | ✅ **FIXED 2026-08-02** (`c7b1f14`, merge `bb89e43`) — `worker.py` now imports the real `BEGIN_MARKER`/`END_MARKER` from `compilers.py` instead of re-declaring them. Row left saying BUILD while its same-day siblings FW-48/49/52 were marked fixed; caught 2026-08-03 by the citation-repair pass. The UI half is FW-48, also fixed. Managed-section excerpt marker case mismatch — `worker.py` searches `SELF-LEARN:BEGIN`, `compilers.py` writes `self-learn:begin` | BUILD | Now. Live today for any target ≥200 lines (`~/.config/CLAUDE.md`, 703) — the analyst gets `lines[:60]` and the contradiction check is blind |
| FW-45 | Resolution observability — no telemetry event kind exists for route/reject/defer/graduate, and `routing.by` is a hardcoded `"human"` constant | BUILD | Before any autonomy-ladder measurement (12 §L1–L3): the evidence substrate those gates read does not exist |
| FW-46 | Implement S-21 — the analyst names the skill | BUILD | **UNBLOCKED 2026-08-02** — both sub-questions answered (§4): analyst proposes, CLI validates, human confirms; and the review surface gets a text field. Campaign unit `U-name`. Scope is wider than the one positional at `verbs.py:512`: **`routing-doctrine.md:262-263` still states the REVERSED pin** ("a `new-skill` proposal never names the skill") and is injected into the analyst's system prompt every run (`analyst.py:14`, `worker.py:621`), and `08-build-plan.md:469` still repeats its debunked "confirmed §4 human call" justification. Until that text changes, the model is told the opposite of the ruling on every invocation |
| FW-47 | Test-isolation residuals from the cache unit — `HOME`/hardcoded `~/.claude/CLAUDE.md` (F-4) and the module-scoped bring-up leak (F-5) | BUILD | Opportunistic. F-5's naive fix hides Chromium and silently skips 77 browser tests — pair with `PLAYWRIGHT_BROWSERS_PATH` |
| FW-48 | ✅ **FIXED 2026-08-02** (`f8d8433`) — and fixed at the root: rather than re-syncing the copied marker, `worker.canon_excerpt` became a shared public function and `pane.py`'s hand-copy was deleted. Both live victims verified rendering correctly against the real target file. A whole-repo sweep confirms zero remaining literal consumers of the legacy needle. **FW-44's defect is cloned in the UI and a green test pins it as the contract.** `ui/pane.py` re-declares the wrong marker inside a hand-copied `_canon_excerpt`, and `ui/tests/test_pane.py` hand-writes that same wrong marker into its fixture — so the test passes *because* the code is broken. This is the excerpt the **human** reads in the review pane | BUILD | With or immediately after FW-44. Fixing `worker.py` alone leaves the human adjudicating from a head-of-file truncation, which is the surface that matters most. Found 2026-08-02 while spec'ing FW-44; tracked as campaign unit `U-marker-ui`. **Added 2026-08-02 after `U-marker` merged:** `pane.py:254`'s comment — "Mirrors `self_learn.worker._canon_excerpt` EXACTLY" — was true that morning and is false as of `bb89e43`; `worker.py:53` now imports the real constants while `pane.py:266-267` still hardcodes `_BEGIN_MARKER = "SELF-LEARN:BEGIN"`. Fix the comment with the code, or it becomes an invariant claim that actively misleads. Same shape at `models.py:98-99`, which still gives the retired chezmoi premise as its reason for excluding `reference` at user scope (the real reason is now S-23). **Escalated 2026-08-02 by the post-wave code audit — this now has LIVE VICTIMS and a NEW hazard U-marker created.** Measured against a section written by the real compiler into a 284-line file: `pane.target_canon_excerpt` returns a 61-line head-of-file truncation with no markers where the fixed worker returns the correct 43-line window. Two records are `pane_truncated=True` on the live ledger right now — `lrn-b197d06b` and `lrn-be6dca06`, both project scope, both targeting a 720-line `CLAUDE.md` with one lowercase marker pair. **The new hazard:** before U-marker shipped, both halves were wrong *consistently*; now the analyst reads the managed section while the human adjudicating its proposal reads the head of the file, **with no indication they differ**. Fixing `worker.py` alone made the divergence possible. A whole-repo sweep confirms `ui/pane.py` and `ui/tests/test_pane.py` are the only remaining code consumers of the legacy needle; `test_pane.py:702` writes `"<!-- SELF-LEARN:BEGIN -->"` — a string no compiler emits — so `test_over_threshold_excerpts_around_markers` passes *because* the code is broken |
| FW-53 | ✅ **FIXED 2026-08-03** (`5fa3fbb`) — **and it was FIVE crash sites, not one.** Each was found by fixing the confirmed one and re-running the reproduction, which exposed the next: `_ledger_index`/`_canon_index` (the reported crash), `import_common.existing_origins` (unreachable until site 1 was fixed), `telemetry.read_events` and `telemetry.flush` (both on the hot path of EVERY productive run), plus `_find_record` fixed proactively because its own comment already asserted the invariant. The telemetry fixes decode **per line**, so one torn line no longer discards the whole event history. Decision: skip-and-report, not fail-run — the nightly producer degrades rather than stopping — but the skip is carried in `MineResult.corrupt_records`, every journal entry from detection onward, `miner.log`, AND the human-readable `mine status` line, never `--json` only. **Residual, declined with reason:** `flush()`'s heal-a-torn-trailing-line read of the *tracked* target still crashes if that file is itself corrupt — a different corruption source, and fixing it needs a decision about appending to a target you cannot read. Own follow-up, not folded in **A record file with invalid UTF-8 wedges a mine run — pre-existing on master, isolated 2026-08-02.** The crash is `_compose_prompt` → `_ledger_index` → `Record.from_path` → `read_text`, which runs **before** `_reconcile_and_land`, so `run()`'s outer handler turns the run into `status: failed`. Confirmed pre-existing by neutering `U-recur`'s backfill and reproducing it anyway; that unit adds no new exposure because the backfill is never reached | BUILD | Opportunistic. Same permanent-wedge class as the guard `U-recur` closes, through a door no unit currently owns. Found at `U-recur`'s code gate while hunting the unresolvable-record ground; recorded so it is not later mis-attributed as a `U-recur` regression |
| FW-52 | ✅ **FIXED 2026-08-02** (`fcffbf8`) — two half-blind fixtures added ALONGSIDE the shipped one (never replacing it), each proven to redden when its own half-fold is reintroduced while the original stays green. The both-uppercased fixture remains the sole valid positive control against the original bug, and both docstrings say so. **FW-44's fixture catches case-blindness only when it is applied to BOTH markers.** The code gate modelled five implementations against three fixture shapes and measured it: a build that folds case on the *begin* needle only, or the *end* needle only, survives the entire suite. Mechanism — the shipped fixture uppercases both markers, so a half-blind build finds one and misses the other, falls into the `begin is None or end is None` branch, and lands on the same head truncation the criterion asserts. Closure is two more fixtures (begin-uppercased-only, end-uppercased-only) **added alongside** the shipped one, never replacing it: neither is red pre-fix, so only the both-uppercased fixture is a valid positive control | BUILD | Opportunistic, low. Disclosed by the gate as a coverage fact rather than a build defect — the spec pre-declared this outcome for one of its own mutations ("worth seeing"), so it is a known accepted limitation, not a regression. Recorded so a later reader does not mistake the green suite for full coverage of the unit's own subject. Found 2026-08-02 at U-marker's code gate |
| FW-49 | ✅ **FIXED 2026-08-02** (`fcffbf8`) — **and the row's premise was half wrong, which is the finding.** `_recurrence_suspects` is neither uncalled nor output-dropped: it runs on every `worker.run()` and its output does reach tracked telemetry. The defect is in the predicate, and its two bases are not equally dead. **`origin-match` is provably, permanently unreachable** — `import_common.existing_origins()` enforces global uniqueness of `evidence.origin` before any mined candidate lands, so a fresh pending record's origins are always disjoint from every routed record's; and independently, `teach`-authored records never write an `origin` key at all. That branch is removed. **`title-token-overlap` is NOT dead** — the pre-existing unit test proves it live; it is *starved*, because the miner folds genuine duplicates before they reach pending (the campaign's own §5 diagnosis). Measured against a full copy of the live ledger (35 pending × 31 routed): 0 hits before and after. Broadening it to full-section-body tokens was tried and measured WORSE (the one near-miss pair drops 0.571 → 0.33 Jaccard — longer text dilutes overlap), and that pair is a deliberate `--supersedes` refinement rather than a recurrence, so the basis was left alone rather than recalibrated on weak evidence. Adds ZERO new suspects on top of the miner's 4. Double-emission is impossible by construction: the two producers' `origin` value spaces are disjoint (pending-record-id vs transcript-ref). **"Zero `recurrence-suspect` events" has TWO dead producers, not one.** The channel-split diagnosis (campaign §7) names the miner; `worker._recurrence_suspects` (`worker.py:969-1016`) also spools `recurrence-suspect` and has likewise emitted zero. The campaign's `U-recur` fixes only the miner | BUILD | After `U-recur` lands, since it shares `worker.py` with FW-44. Until then the suspect surface stays under-reporting even once the miner crosses over. Found 2026-08-02 while spec'ing `U-recur` |
| FW-51 | **`graduate` on a REJECTED record succeeds, silently rewriting a denied lesson to `superseded_by: canon`.** Unguarded in the CLI — measured in a throwaway sandbox 2026-08-02, not inferred. `graduate` on an already-graduated record fails safe (nothing to commit); on a rejected one it goes through and inverts the human's decision | BUILD | Independent of the campaign; `verbs.py` is contended, so sequence it after. **Correction 2026-08-02 (audit):** this row previously said "not reachable through `U-grad-ui`'s surface (which gates the action to `routed`), so this is a CLI-side hole only." **That containment claim is false.** The status gate exists on the GET render only (`detail_resolved.html:87`); the POST half has none — `routes.py:1283` (`action_arm`) and `:1417` (`action_confirm`) validate only `if verb not in _KNOWN_VERBS:`. A hand-crafted POST with `kind="resolved"` against a graduated or rejected record still dispatches `graduate`. The shipped code says so itself at `ui/templates/partials/action_bar.html:152-159` (code-gate MAJOR 1), and `u-grad-ui-resolved-surface-spec.md:107` agrees while `:720` repeats the overstatement. Treat this as reachable from the UI, not CLI-only. Found 2026-08-02 while spec'ing `U-grad-ui`; containment corrected the same day |
| FW-62 | ✅ **FIXED 2026-08-02** (`81cb694`) — `record_text=` now passed, matching the exact text form `write_proposal` uses so the two paths cannot disagree again. Verified a no-op on the live ledger (none of the 20 real pending proposals carries a `gates:` trace), so no transition was needed. **`self-learn proposal validate` reports VALID — and STAMPS — a proposal that `write_proposal` refuses.** `selfcheck.py:154` calls `validate_proposal(read_proposal(...))` positionally with no `record_text=`, so U-schema's quote containment never runs on the one surface built to ask "is this honest?". Measured on identical bytes in a scratch ledger: `write_proposal` → *REFUSED — gates.t1.field_shaped.evidence is not contained in the record it claims to quote*; `proposal validate` → *"valid — record_sha stamped in place"*, rc=0. `SKILL.md:52` documents this verb as **REQUIRED after any direct edit of a pending record outside CLI verbs** — so the fail-open sits exactly where a hand-edited record gets its only check. The fix is already in hand at the call site: `selfcheck.py:153` does `Record.from_path(record_path)` and **discards the result on the line above**, so it is `record_text=Record.from_path(record_path).to_text()` | BUILD | **Top of the audit rows with FW-57.** A validator whose stricter surface is the machine path and whose lenient surface is the human path has its permissions inverted. CONFIRMED by execution 2026-08-02 |
| FW-63 | ✅ **FIXED 2026-08-02** (`05f8a5b`) — `key=repr` on both sites, AND on the pre-existing clone in `_validate_hook_extension`, because fixing the instance and not the class is how this recurs. **S6 — "raises only `ProposalError`, on every input" — is false, and `self-learn list` tracebacks for everyone.** `ledger_ops.py:798`, inside `_validate_gates`: `sorted(gate_keys - set(TRACE_GATE_KEYS))`. A `gates:` mapping with **two or more unknown keys of mutually incomparable types** (YAML permits non-string keys — `{1: x, zzz: y}`; also reproduced with `None`, `True`, tuple) raises `TypeError`, which is neither `ProposalError` nor `LedgerOpsError`. `proposal_info` catches only `ProposalError`; `queue()`/`list_items` catch nothing. Measured end to end: `cli.main(["list"])` → `TypeError: '<' not supported between instances of 'str' and 'int'`. **A malformed trace on somebody else's record breaks `list` for everyone** — verbatim the symptom the unit's own `re.error` backstop was added to close, one branch earlier in the same function. One-token fix: `sorted(..., key=repr)`; pair it at `:803`. **Why no test caught it:** the A7/M22 mutation catalog models one mechanism, *index-before-type-check*, which `_mapping` closes thoroughly — this is a second mechanism *above* any `_mapping` call, since the key-set diff runs on the raw mapping before any leaf is touched. **Honest scoping:** the identical construct pre-exists at `ledger_ops.py:505` (`_validate_hook_extension`) and raises the same way, so the shape is repo-wide; what is new is declaring S6 *unconditionally* while cloning the escape into it. 12 other hostile `gates` shapes fuzzed: 0 further escapes | BUILD | CONFIRMED by execution 2026-08-02. Together with FW-57 these are the two escapes from a guarantee the merge commit stated without qualification |
| FW-64 | ✅ **FIXED 2026-08-03** (`4f8817a`) — the `dest is None` proxy is replaced by an explicit `by`, validated against a closed `{human, analyst, agent}`. **A third value was added deliberately**: the SDK pane agent is a real third chooser and was previously misrepresented as one of the other two; checked and confirmed this does NOT touch `SCHEMA_VERSION` (a value inside an existing kind, not a new kind — important, since that constant is already double-booked per FW-65). The UI distinguishes approve-as-proposed from an override via `dest_touched` — **a positive fact (did the human use the cycle control), not a comparison against the proposal, which was rejected because the proposal can go stale between render and confirm.** Mutation testing found THREE defects in the builder's own first-pass tests, all closed before delivery — notably a hardcoded `False` in the commit-drift retry context that left all 18 pre-existing commit-drift tests green. Historical records deliberately not rewritten. **FW-45 may now be closed** **`routing.by` is still dishonest on BOTH live routing surfaces — FW-45 is on track to be closed while the capability it names is dead.** U-reach's Part C rests on the premise (`verbs.py:2052-2054` comment, `test_route_observability.py:15` docstring) that *"the review UI's approve-as-proposed argv omits `--dest` entirely."* Driving the shipped app end to end disproves it: the detail page renders `<input type="hidden" name="dest" value="skill-md">` (fed by `RecordRow.destination_default`, the analyst's own scope-corrected destination), and confirm dispatches `['route', '<id>', '--dest', 'skill-md', '--json']`. So `by = "human" if dest is not None else "analyst"` yields **`human` for every UI approval, including approve-as-proposed, where the ANALYST chose.** The second surface is the already-known `teach.py:697` (no `by=`, so `resolve_record`'s `"human"` default applies) — **which no FW row records**, existing only in a commit message and a docstring. A third, same root cause: `ui/proposals.py:141`, the SDK pane agent, records `analyst` when it omits dest and `human` when it supplies one — wrong in *both* branches, since the chooser was neither. `dest is None` is a proxy that cannot distinguish three choosers. Nothing pins the seam: `ui/tests/support.py:199` hardcodes `"by": "human"` and no UI test asserts on `by`; the CLI tests DO discriminate (mutating `verbs.py:2058` reddens criteria 16/21/24), so the gap is purely at the package boundary where no test looks | BUILD | **Do not close FW-45 until this is fixed.** The whole point of `routing.by` is measuring how much routing the analyst actually does; recording `human` for analyst-chosen routes makes the autonomy-ladder evidence substrate report the opposite of the truth. CONFIRMED by driving the app 2026-08-02 |
| FW-65 | ✅ **FIXED 2026-08-02** (`92454a7`) — F6 now asserts the INCREMENT and tells the builder to read the current value first. **`SCHEMA_VERSION = 2` is double-booked, and a future acceptance criterion will pass vacuously.** `telemetry.py:68` is now `2` for U-reach's `route` kind. `drafts/16-ecology-spec.md:902` pins **`SCHEMA_VERSION = 2`** as *its* bump for adding `contradiction-suspect`, instructing "bump the literal, currently `1`", with acceptance criterion **F6** reading "`SCHEMA_VERSION = 2` pinned". When 16-ecology Stage A lands, **F6 passes with nobody having bumped anything** — a criterion satisfied by a different unit's work — while two different closed kind-sets both label themselves v2, which the constant's own contract forbids. Same file: `:904` describes `miner._event_seen`'s pre-U-recur signature (U-recur changed it from `set` to `tuple[set, list]`), and its `telemetry.py` line refs are stale | BUILD | Cheap now, confusing later. Bump 16-ecology's target to 3 and re-word F6 to assert the *increment*, not a literal. Documentary, not executable. Found 2026-08-02 |
| FW-66 | ✅ **FIXED 2026-08-02** (`81cb694`) — and it was worse than recorded: the crash fired even earlier, in `_section_targets`, so `--selftest` printed ZERO of its seven rows. Fixed across six sites (`_check_reach`, `_section_targets`, `_check_drift`, `_check_compiler`, `_check_markers`, `_check_hooks`); an undecodable surface now FAILS loud naming the file rather than passing silently. **`_check_reach` raises `UnicodeDecodeError` on two inputs it appears to guard.** `selfcheck.py:336` (`surface.read_text(encoding="utf-8")`) and `:383` (`Record.from_path`, whose `except RecordError: continue` at `:384` does not catch a decode error). One non-UTF-8 byte in a loaded surface or a resolved record → `--selftest` tracebacks instead of printing its seven PASS/FAIL rows. Both reproduced. **Honest qualifier:** identical shape pre-exists in `_check_drift` (`:438`), so this is a clone, not a regression — but the blast radius is new. Drift reads compiler-owned targets; reach reads the **loaded surface** (`SKILL.md`, a project `CLAUDE.md`, `~/.claude/CLAUDE.md`) — files self-learn does not own and cannot constrain. Same class as FW-53, which explicitly certifies *U-recur* added no new exposure; nobody ran that check against U-reach | BUILD | With FW-53 — one decode-hardening pass over every `read_text` on a file self-learn does not own. CONFIRMED 2026-08-02 |
| FW-67 | ✅ **FIXED 2026-08-02** (`358c9c1`) — rewritten as the general RULE (containment iff `record_text=`) pointing at §2's S2 census as the single authoritative list, rather than a second enumeration that would drift again. All seven sites re-verified against current code first. **U-schema's containment disclosure names two of seven positional call sites.** §3.7 item 9 (`u-schema-decision-trace-spec.md:641-655`) is the unit's stated "here is exactly how far containment reaches" paragraph; it names `worker.py:909` and `verbs.py:509`. Seven sites call `validate_proposal(data)` positionally (containment OFF): those two plus `worker.py:1237`, `verbs.py:1098`, `verbs.py:1152`, **`analyst.py:235`** and **`selfcheck.py:154`**. Only `ledger_ops.py:1342` (`write_proposal`) and `:1745` (`proposal_info`) pass `record_text=`. Items 3–5 are arguably covered by "the worker and route call sites"; **6 and 7 are not covered by any reading** — `analyst.py:235` is the PRODUCER, where a fabricated quote first arrives from the model, and `selfcheck.py:154` is FW-62. The spec's S2 list at `:131` does enumerate all seven, so the information is in the document — the defect is a second, narrower enumeration in the paragraph that exists to be the authoritative one, in a unit whose §0 forbids exactly that | BUILD | With FW-62. Also fold in the prose drift the same pass found: `analyst.py:167-170`'s docstring still enumerates the old fixed key set *on the very function whose shipped defect was enumerating a fixed key set*; `miner.py:1008-1009` still says the journal's outcome vocabulary is "UNCHANGED (12 A1)" after U-recur added `recurrence-from-fire` and edited the next line of the same block (`12-transcript-miner.md:406-409` likewise); and `skills/self-learn/SKILL.md:53`'s user-facing `--selftest` list names neither `drift` nor `reach` | 
| FW-57 | ✅ **FIXED 2026-08-02** (`05f8a5b`) — consecutive `**` now collapse before translation, as the oracle does. Pre-fix measurement reproduced at 40.4s for twelve; `_compile_glob_pattern` was also split so failures are cached too (`lru_cache` never caches exceptions). **`self-learn list` can HANG — not raise — on a `rules_paths` pattern with consecutive `**`.** `ledger_ops.py:667` emits a separate `(?:[^/]+/)*` per `**` segment, and adjacent groups nest exponentially; `glob.translate` — the oracle the docstring names — collapses consecutive `**` into one `(?:.+/)?`. Measured against a 24-segment non-matching path: 8 repeats → 0.24s, 10 → 3.36s, **12 → 33.5s**, versus 2µs through the oracle. A proposal with `gates.t2.answer: yes`, a long `match_path` and `rules_paths: ["**/**/**/…/x.py"]` wedges the listing. **This is the one failure mode `U-schema`'s S6 guarantee structurally cannot cover** — S6 catches `ProposalError`, and non-termination never reaches an `except`. It sits on the eligibility hot path. Two related prose claims that do not hold: `_compile_glob_pattern`'s *"Memoized: this runs on the eligibility hot path"* memoizes **compilation only** (three identical `_glob_match` calls: 0.516 / 0.495 / 0.491s), and `lru_cache` never caches exceptions, so an untranslatable pattern is re-translated for every record on every listing (`cache_info()` after five identical calls: `hits=0, misses=5, currsize=0`) | BUILD | **Highest of the audit rows.** Honestly scoped: the *intra-segment* blowup (`src/*a*a*a…*.py`) is NOT a divergence — the oracle is equally slow — so only consecutive `**` regresses against the named oracle. Fix is to collapse consecutive `**` the way the oracle does. CONFIRMED by execution 2026-08-02, post-wave code audit |
| FW-58 | ✅ **FIXED 2026-08-03** (`cf9a700`) — all five confirmed STILL uncovered first (including the `&`/`~`/`|` escape, whose enclosing function was rewritten hours earlier by FW-57/63 without touching that line). Test-only; no production code changed. One honest limitation recorded: escaped and unescaped `&`/`~`/`|` compile and match IDENTICALLY under this interpreter, so that check can only be pinned on the translated pattern's SHAPE, not its behaviour — stated rather than papered over with a behavioural assertion that could not fail **Five more `U-schema` production checks that no test can see.** Each, neutralized individually, leaves `test_decision_trace.py` at **73 passed** with the full-suite failure set byte-identical: `ledger_ops.py:822` (`g0.reject/defer.evidence` required-when-`yes`), `:912` (`t2.evidence` `required=True` — the "required BOTH ways" rule), `:896` (`t1.cost_bearing.evidence` required-when-`yes`), `:815` (`g0.<leg>.answer` yes/no enum), and `:630` (the `&`/`~`/`\|` class-body escape — *the unit's own false-refusal fix*). No fixture ever sets `gates.g0.reject/defer.answer: "yes"` or `t2.evidence: None`. The merge commit folded in "eight production checks no test could see"; the same sweep found eight and left at least these five | BUILD | Test-only. CONFIRMED by mutation 2026-08-02. Note the shape: the gate's sweep was thorough within the shapes it modelled and blind to the ones it did not — the same lesson `U-pathed`'s A17 taught at a different level |
| FW-59 | ✅ **FIXED 2026-08-03** (`cf9a700`) — **and the mechanism is worth naming: one check was silently BACKSTOPPED by another.** With `rules_paths=[]`, deleting the target clause did not make the call succeed — a downstream glob check raised `ProposalError` anyway, for an unrelated reason, so the assertion stayed green while the thing it guarded was gone. Fixed by pinning the exact message on both legs so a swap between them is visible. The second vacuity was cruder: `match=key` was satisfied for EVERY key because every message echoes the full key list — proved by hardcoding the production list to `["g0"]` and watching the old assertion stay green for **8 of 9** deleted keys **A criterion whose docstring says it "must never be vacuous" is vacuous.** `test_decision_trace.py:1095` — deleting the `or not rules_paths` clause at `ledger_ops.py:929` leaves both halves green: with `rules_paths=[]`, `any(...)` over an empty list is `False` and the next check raises with a **byte-identical** message, so the empty-list case never discriminated the clause it targets. No behavioural bug (both refuse). Same file, `test_missing_gate_key_refused:434`: its `match=key` is satisfied by every message, because they all echo `list(TRACE_GATE_KEYS)` | BUILD | Low, test-only. CONFIRMED 2026-08-02. Worth fixing precisely because the docstring asserts the opposite — a comment claiming non-vacuity on a vacuous assertion is the strongest form of this project's signature defect |
| FW-60 | ✅ **FIXED 2026-08-02** (`358c9c1`) — §3.4a treated as normative and narrowed to name the one measured false-refusal exception, with both measurements stated; also disclosed that it is NOT proven unreachable, since nothing in Schema-1 forbids an absolute `match_path`. **Two `_glob_match` divergences from the named oracle, both benign but one contradicting a spec sentence.** 6000 fuzzed patterns × 60 paths: **564 mismatches, all one shape** — `_glob_match("", "*")` is `True`, oracle `False`; zero other semantic mismatches and zero non-`ProposalError` exceptions. Separately `_glob_match("/src/a.py", "**/*.py")` is `False` where the oracle is `True` — **a false refusal, the direction `u-schema-decision-trace-spec.md` §3.4a says cannot happen**, though §8-O6 claims the absolute-path behaviour deliberately. The docstring's "0 mismatches on a real tree" is literally true only because a real tree cannot hold an empty filename | BUILD | Low. Reconcile §3.4a with §8-O6 rather than changing behaviour. Also record here, disclosed-not-defect: `_glob_match(".claude/rules/ts.md", "**/*.md")` is `True` while `verbs._validate_project_globs` (`verbs.py:698`, `glob.glob(recursive=True)` with `include_hidden` defaulted **False**) refuses the same tree with "matches nothing" — §8-O6 rules `verbs.py` is the side that moves, but note the divergence lands exactly on `.claude/rules/`, this project's own rules-variant destination. CONFIRMED 2026-08-02 |
| FW-61 | ✅ **FIXED 2026-08-02** (`92454a7`) — folded into the campaign playbook's mutation-verification section, along with the wrong-tree and editable-install variants and the survivals-are-suspect asymmetry. **Mutation sweeps in this repo need `PYTHONDONTWRITEBYTECODE=1` and a cache clear, or they report survivors that never ran.** Python reused stale `__pycache__` when a source file was rewritten inside the same second, so the audit's first mutation run produced garbage — mutations recorded as "survived" that were never actually executed. That is itself a check passing for the wrong reason, at the level of the tooling the gates depend on | BUILD | Process, not code: fold into the campaign playbook's mutation-verification instructions so every future code gate carries it. Found 2026-08-02; the audit's own findings were re-run under the corrected setup |
| FW-54 | **`U-reach`'s shipped code and tests state a reason S-23 closed the other way.** `selfcheck.py:284-290` says the `user` row is "**dead code end-to-end until `U-demand-user`**", repeated at `test_selftest.py:511-514` and `:533-537` and four times in `u-reach-reachability-selftest-spec.md` (`:303-304`, `:526-531`, `:532-533`, `:627-632` — the last describing a "seam into this unit's file" for when B7 opens). Under S-23 (2) user-scope `reference` is dead **permanently**, not pending: the branch is correct, its stated reason is not, and the promised seam is moot. Note the spec was *partially* updated for S-23 (it cites it at `:573`), so half the file was reconciled and half was not | BUILD | Comment/docstring/test-name accuracy only — no behaviour changes. Cheap, and worth doing before someone builds the seam that S-23 removed the need for. Found 2026-08-02 by the post-wave bookkeeping audit |
| FW-55 | ✅ **PARTLY FIXED 2026-08-02** (`358c9c1`) — the U-schema half is closed (sanitiser and `re.error` backstop described, §9 gains the missing code-gate round). The U-analyst half (its §61-66 measured claim, half-closed by U-schema's later merge) is still open. **Two shipped specs still describe mechanisms their own build replaced.** (1) `u-schema-decision-trace-spec.md:417-420` pins the glob recipe as "`[...]` → a passed-through character class"; shipped `ledger_ops.py:629-630` **sanitises** it instead (`\\` doubled, `&~\|` escaped), and the spec's §9 revision history stops at r3 with no entry for the code-gate round that changed it. The `re.error` backstop at `ledger_ops.py:675-680` and its two tests appear nowhere in the spec, whose final step (`:435-436`) ends at `re.compile`; and §3.4a's unconditional "the divergence direction is false accept, never false refusal" (`:480-482`) now holds *because of* the escaping the spec omits. (2) `u-analyst-proposal-fidelity-spec.md:61-66` states as measured that a proposal carrying `gates:`/`flags:`/`recommendation:` "validates clean today" — U-schema merged after and closed half of it (`ledger_ops.py:776-779`, `:784-789` now refuse out-of-set `flags:`/`recommendation:`; measured on master: `banana` → CLEAN, `flags:['banana']` → REFUSED) | BUILD | Doc-accuracy only. (1) is the exact failure the campaign playbook §5 warns about — a spec pinning an algorithm in prose that the build then had to correct — so it is worth fixing as the worked example of that rule. (2) is ordinary cross-unit staleness from concurrent merges. Found 2026-08-02 by the post-wave bookkeeping audit |
| FW-56 | ✅ **FIXED 2026-08-03** (`f641178`) — and the scale was far past this row's estimate: **~301 citations checked, ~208 stale, 0 unresolvable.** These specs cite the same construct repeatedly and nearly every unit had shipped, so sibling merges drifted almost everything. **Most were converted to SYMBOL names rather than re-pinned to new line numbers** — a symbol survives the next insert; re-pinning ~200 line numbers would only reset the clock. All four named examples confirmed and fixed. Where a citation pointed at code its own fix had REPLACED (not merely moved), the citation was corrected and a dated note added, without rewriting the historical narrative around it. **Citation drift across the wave's specs — roughly 80 `file:LINE` anchors no longer resolve.** Almost all were exact at each unit's own base commit and drifted from the units' own inserts and same-day sibling merges, so this is honest drift rather than fabrication. Four matter because they sit in load-bearing text: the campaign playbook's completion checklist (`r2-routing-campaign.md:542`) cites `miner.py:1174-1185` for the recurrence-suspect spool (now `:1236-1251`; `:1174` is a docstring tail) and `verbs.py:3147` for `confirm-recurrence` (now `:3204`; `:3147` is unrelated code), and `u-grad-ui-resolved-surface-spec.md:93-94` cites `verbs.graduate` at `verbs.py:2913` (now inside **`rehome`**'s refusal; `def graduate(` is `:2969`) and `:772` cites `ledger_ops.list_items:1108` (now mid-`validate_proposal`; `def list_items(` is `:1797`) | BUILD | Low individually, systemic in aggregate: a citation that resolves to *unrelated but plausible* code is worse than one that resolves to nothing, because a reader checking it may believe they have verified the claim. Consider whether load-bearing citations should name a symbol rather than a line. Found 2026-08-02 by the post-wave bookkeeping audit |
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
