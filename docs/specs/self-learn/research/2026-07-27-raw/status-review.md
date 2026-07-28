# self-learn — independent status review (2026-07-27)

Reviewer: independent agent, given no orchestrator framing. Everything below is
grounded in files read or commands run in this session; each section marks what
is verified vs inferred. Repo: `/home/komi/repos/self-learn`, HEAD `6bd30eb`,
master == origin/master, tree clean.

## 0. One-paragraph verdict

The product is live, healthy, and unusually well-disciplined — miner ran this
morning, CLI suite 1133 passed / 5 skipped in this session, the two-gate +
blind-walk methodology keeps catching defects green suites cannot see. But the
2026-07-27 routing/pin audit changed what "healthy" means: it showed the
system's *delivery* layer — the entire point of routing — is measurably broken
in three independent ways (half the routed corpus landed in a file nothing
loads; user scope has exactly one destination by construction; the analyst can
never emit `hook`, failing silently 34% of the time), and none of those are
fixed yet. Recent effort has gone to UI perceptibility polish, which is good
work aimed one layer above the actual problem. The best path forward is to stop
new UI rounds after the already-specced ring-targeting P0, run the audit's
fallout to ground (mechanical fixes + the four user rulings + the §13 values
questions), and keep packaging parked until routing efficacy is demonstrably
repaired.

## 1. Recently completed (verified against git + code)

Since the last README revision-log entry (2026-07-24 publication), in order:

- **Public release shipped and executed (07-24).** FSL-1.1-MIT, CLA,
  marketplace manifest; repo flipped public. Pre-publication hygiene was done
  in the right order and verified here: portability fixes + `self-learn init`
  (`74fcfc7`), home-state repo-root predicate (`0f5c679`), chezmoi demoted to
  detected capability (`97726df`), A1/A2 claude-md label/variant work
  (`4950929`, `b11d9aa`), and a 22-file personal-literals scrub (`6105983`) —
  I confirmed no `komi`/`DEFAULT_MEMORY_DIR` literals survive in shipped
  source; the memory-dir default is now deliberately absent (env-only).
- **In-flight SSE feedback unit (`f69d38e`, 07-25).** Perceptual
  (aria-snapshot) assertions moved into CI; the S-20 register row records the
  Map-not-counter design and the disclosed residual SSE-reconnect gap (FW-38).
- **Source-blind walk instrument (`60e8b6f` + fixes, 07-26).** A sandboxed UI
  + probe + walk protocol; five walks run by source-blind agents, findings in
  `fixtures/ui-walks.md`. The instrument found its own blind spots (below-fold
  under-reporting, selection-ring invisibility) and they were fixed
  (`0ca1ef5`, `951cedf`).
- **Resolution-evidence surface (`29d1672`, 07-26).** Confirmed resolutions
  now say what they did. Spec records 7 defects a green suite couldn't see.
- **Commit-drift evidence unit W3-F1 (`3308d6a`, 07-26).** The guided
  commit-and-retry path — previously the "longest, most anxious path ends in
  silence" — now reports what it did. Spec marked SHIPPED (`e1a6445`).
- **Ring-targeting spec to revision 7** — split (`2c027cd`): targeting core is
  build-ready; the no-op hint surface got its own draft. **The build has NOT
  happened** — `app.js` untouched since `29d1672` (verified).
- **The routing-monoculture and pin-provenance audit (07-27, `f0fa9ef`).**
  Findings record + 8 raw subagent reports preserved with an explicit
  not-corpus README. Provenance-marked ([V]/[R]/[U]), deliberately pins
  nothing.
- **UI test cache isolation (`6bd30eb`, 07-27).** The audit's §10 leak (UI
  suite writing `home-*` dirs into real `~/.cache`) fixed with an autouse
  five-variable redirect fixture + mechanism-level guard tests that call the
  real resolvers. I read both; the fix is sound, and my own sandboxed UI suite
  run wrote nothing to the real cache.

**Is it in good shape?** Yes, at the unit level. CLI suite: **1133 passed /
5 skipped** (run in this session, fully env-redirected). UI suite: run in this
session, results at the end of this file. Miner: last run 2026-07-27 03:36
local, `ok — 0 landed, 1 fire`; timer armed for tomorrow. Ledger consistent:
13 pending (10 user-scope, 1 home-assistant, 2 hypr-doctor), 51 resolved, 13
proposal files. `self-learn-ui.service` inactive — correct (idle self-exit is
the designed Y-14 posture). Push discipline: everything committed is pushed.

## 2. Outstanding — the audit's fallout is the real backlog

The 07-27 audit (`research/2026-07-27-routing-monoculture-and-pin-audit.md`)
is findings-only by design, and almost none of it has landed as work items
yet. I re-verified its central code claims myself at HEAD — all still live:

1. **Delivery hole (audit §3, highest severity).** `compile_reference`
   appends to `references/LEARNINGS.md` and writes no pointer anywhere; 14 of
   28 routed records (50%) sit in a file nothing references (grep control:
   `GOTCHAS` appears in 8 files, `LEARNINGS` in 1 — itself). "Routed" and
   "loadable" are not distinguished by any metric. This breaks P2 for half
   the corpus the product has ever routed.
2. **User-scope monoculture (audit §2).** `ui/models.py` `"user":
   ("claude-md",)` — verified, a one-element tuple; `verbs.py:950-955` still
   refuses `reference` at user scope citing "the chezmoi-managed CLAUDE.md"
   — a premise dead since 07-24 (chezmoi retired) yet still in the refusal
   text, the models.py docstring, and the routing doctrine. The 10 user-scope
   pending records all propose `claude-md` — the review cards present a
   forced choice as a considered one.
3. **Analyst can never return `hook` (audit §4).** Verified at
   `analyst.py:196-211`: the serializer copies a fixed key set plus
   `variant`/`rules_topic`/`rules_paths`; `hook:`/`examples:` are dropped,
   then the validator rejects. Measured 34% silent failure (all rc=0) in 38
   sandboxed runs. This also silently re-implements the per-authorship split
   of S-10 the user explicitly rejected — a bug against a quoted ruling.
4. **Excerpt marker never matches (audit §6).** Verified: `worker.py:572-574`
   searches `SELF-LEARN:BEGIN`; `compilers.py:84` writes lowercase
   `self-learn:begin`. Live consequence: the 703-line `~/.config/CLAUDE.md`
   bucket's analyst is blind to its managed section.
5. **`routing.by` is a constant (audit §2).** Verified: `verbs.py:2325`
   hardcodes `"by": "human"`. Any autonomy-ladder analysis keyed on it
   measures nothing — and per audit §11 there is *no telemetry event at all*
   for route/reject/defer/graduate, so doc 12's staged-autonomy ladder
   ("per-class accept rates from day one") currently has no evidence
   substrate.
6. **Caps: the binding axis is hidden (audit §7).** `~/.claude/CLAUDE.md`
   managed section at 506/150 words (337%) while the UI budget line leads
   with the non-binding entries axis (5/10 reads as headroom).
7. **Cache detritus.** The *fix* shipped (`6bd30eb`) but the 1.1 GB /
   31,214 `home-*` dirs are still in `~/.cache/self-learn` (recounted this
   session; slightly up from the audit's 31,033). Cleanup is a user-owned
   action and hasn't happened.

**Ratified-but-not-graduated user rulings (audit §12):** analyst may name the
skill (with two sub-questions left open); loosen the funnels; pins get
provenance accounting; autonomous push (already operative via
`CLAUDE.local.md`). The register still ends at S-20 and the FW map at FW-39 —
none of these have FW rows or specs yet.

**Open values questions routed to the user (audit §13):** what `reference`
should *do*; whether user scope gets a cheap surface; model-authored names
trusted vs regenerated; the two request-narrowings. Plus the pre-existing
queue in `14 §4`: host-add tightening, pane canon-read widening, FW-10
distribution shape, round-4 unpark.

**UI defect backlog from the walks (`fixtures/ui-walks.md`):**
- **W4-F1 ring targeting — P0 correctness, spec-ready, unbuilt.** Verb keys
  act on the first row in document order, not the selected row: "with the
  ring on record 5, `x` denies a different record." This is the only walk
  finding that can resolve the *wrong record*.
- Worker "Force run" produced no perceptible response in three independent
  walks (the adjacent miner Force-run visibly works, so it's not obviously a
  sandbox artifact) — needs triage.
- W4-F2 (Enter on a focused button navigates), W4-F3 (Escape descends at
  root), W4-F4 dead keys (`h`/`r`/`v`/`b` — `v` is the fourth
  advertised-key-bound-to-nothing, found *inside the unit built to end
  them*), W4-F5 ("any other key cancels" vs "n to say why" contradiction),
  W4-F6 (invisible live pane session), W5-F1 (undefined vocabulary), W5-F2
  (confirm strip names `skill-md` for verbs that don't write there),
  `/report` counting one graduate three ways. Most are ruled out of the ring
  spec's scope; the no-op hint draft is ungated.

**Spec-pipeline state (drafts/):** ready-but-unbuilt: ring-targeting (rev 7),
fast-lane (SOUND — but see §3), settings-surface FW-30 (SOUND). Not sound /
ungated: 16-ecology, noop-hint. Blocked on user rulings: Spec C3 (carved from
C1). Several draft headers are stale — c1, scrub, analyst-riders,
miner-visibility all still say DRAFT/for-gate although their units shipped
(commit log proves it). In a project whose own audit documents that "a fossil
rationale reads exactly like a live one," stale status headers are not
cosmetic.

**Corpus bookkeeping is behind:** the README revision log ends at 07-24 —
the walk instrument, resolution-evidence, commit-drift, the audit, and the
cache fix have no entries; `records-index.md`'s reviews table ends at 07-19
(missing `reviews/2026-07-24-ui-inflight-feedback-spec.md`) and its fixtures
table has no `ui-walks.md` rows. FW-27 says the index is maintained at
round-close; it wasn't, for roughly three rounds.

## 3. Assessment and disagreements

- **The audit is the best document in the corpus** and its self-restraint
  (pins nothing, provenance-marked, fail-open-aware) is exactly right. But
  restraint has a cost: three days of high-severity, code-verified findings
  currently exist *only* as a findings record. Until they graduate to FW rows
  / specs, the project's official forward register (14) still says the next
  moves are UI harness work and packaging — which no longer matches reality.
- **Priorities drifted upward in the stack.** Since 07-25 nearly all build
  effort went to perceptibility (in-flight feedback, resolution receipts,
  commit-drift receipts). Those are real defects, well fixed — but they make
  the *review experience* honest while the *routing outcome* stays broken:
  a user can now watch, with excellent feedback, a lesson being routed to a
  file nothing will ever load. The audit's §3 finding outranks everything in
  the UI backlog except W4-F1.
- **The fast-lane spec is a loaded gun.** It is gated SOUND and
  build-unblocked, and it tiers `reference` as FAST precisely because the
  destination "affects zero activations" — the exact property the audit shows
  is a defect. Building it before the §13.1 ruling would industrialize the
  delivery hole. It should be explicitly blocked on that ruling (it currently
  isn't, anywhere).
- **A2's shipped variants are inert.** `variant: rules`/`local` shipped
  07-24 and were used 0 times in 38 probe runs and 0 of 12 claude-md
  routings — capability without prompting is dead weight. Funnel-loosening
  (ruling 2) is where that investment pays off or is written off.
- **Chezmoi ghosts.** The host retired chezmoi on 07-24; the code still
  reasons from it in at least three places (verbs.py refusal, models.py
  docstring, routing-doctrine §user-scope cost). C2 made chezmoi a detected
  capability but the *premise text* survived. Cheap sweep, real confusion
  cost — it is actively mis-teaching the analyst today.
- **What I could not establish:** whether the worker path's routing
  distribution shares the analyst path's biases (audit marks it untested);
  whether the walks' Force-run finding reproduces outside the sandbox; the
  live UI's behavior (service idle; I did not force-start it against the
  real ledger).

## 4. Recommended path forward (ordered, with reasoning)

1. **Graduate the audit.** One session: mint FW rows / a repair spec for §§2,
   3, 4, 6, 7 findings and register entries for the four §12 rulings; put the
   §13 values questions to the user as one AskUserQuestion round (they are
   cheap to answer and they block everything downstream). This converts the
   findings record into the plan of record and closes the gap between doc 14
   and reality.
2. **Mechanical fixes, no design questions, straight through the two-gate
   pipeline:** analyst serializer passthrough for `hook:`/`examples:` (+ pin
   `cwd`, + one reprompt on parse failure), excerpt-marker case fix,
   `routing.by` plumbed, route/reject/defer/graduate telemetry kinds, budget
   line led by the binding axis, chezmoi-premise text sweep. Each is small;
   several are bugs against explicit rulings (S-10) or against measurement.
3. **Ship ring-targeting (W4-F1).** Spec is at rev 7 with two clean rounds on
   the core; it is the one live defect that can destroy the wrong record.
   This is the last UI unit that should ship before the funnel work.
4. **Decide `reference`, then act on the 14 stranded records.** Whatever the
   user chooses (pointer-maintaining compiler vs demoting the destination),
   add the audit's proposed selftest — "every reference target reachable from
   a loaded surface" — which fails 14 times today and turns the delivery
   property into a regression-proof invariant. Re-deliver or re-home the 14.
5. **Funnel-loosening round (ruling 2)** as the next *major* phase: doctrine
   + destination-set rework so user scope has a real option space, prompted
   variants, analyst-named skills (with the trust/regenerate sub-question
   answered). Hold fast-lane until after this lands; re-gate it against the
   new reference semantics.
6. **Cache cleanup** (user-owned, one command, after confirming the guard
   tests are on master — they are).
7. **Bookkeeping catch-up:** README revision-log entries for 07-25..27,
   records-index rows, stale draft headers corrected. Cheap, and this
   project's method depends on records being load-bearing.
8. **Packaging (FW-10..15) stays queued** behind 1–5. The repo is already
   public and installable; what a new user would hit first is the routing
   layer, and that is the broken part. First impressions argue for fixing
   efficacy before distribution, by the FW map's own round-4 logic.

## 5. Verification appendix

- Suites (this session, all five env vars + autokick redirected to scratch):
  CLI `1133 passed, 5 skipped` (105 s). UI `1010 passed, 77 skipped,
  1 failed` (73 s) — the one failure is exactly the known pre-existing
  `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
  documented in `CLAUDE.local.md` as non-blocking; the 77 skips include the
  Playwright-dependent perceptual tests (no browsers under the redirected
  cache — environment artifact of the sandboxing, not a regression). Real
  `~/.cache/self-learn` count identical before and after the run (31,214):
  the new isolation fixture holds.
- Code claims re-verified at HEAD: `models.py` user tuple; `verbs.py:945-955`
  chezmoi refusal text; `verbs.py:2325` `"by": "human"`; `analyst.py:196-216`
  key set; `worker.py:572-574` vs `compilers.py:84` marker case; absence of
  `DEFAULT_MEMORY_DIR`/`komi` in shipped source (git grep HEAD vs `b11d9aa`).
- Environment: ledger counts via read-only find/ls; miner log tail; systemd
  timer table; cache dir count 31,214 / 1.1 GB; `~/.self-learn` untouched,
  no mutating verbs run, repo tree left clean.
