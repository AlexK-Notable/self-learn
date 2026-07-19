# Forward theme A — Supply quality: the miner becomes the main character

*Companion to `../14-forward-work-map.md` §2 (FW-1…FW-5). Dated
2026-07-18. The structural argument: four shipped rounds improved how
lessons are **judged**; none yet measured how well they are **found and
composed**. The adjudication surface is now good enough that supply
quality is the binding constraint on the system's value.*

## 1. Why this theme leads the map

The system's founding failure mode (E-3, ha-note's grave) was queue
death — but the *second* failure mode, never yet tested, is queue
pollution: a miner that lands noise trains the human to skim, and
skimming is queue death with extra steps. Every mechanism below exists;
none has an evidence trail. The theme is therefore mostly DRILL: run
the built machinery against reality, journal what it does, and only
then tune.

## 2. FW-1 — Episode-brief live verification

**What**: the open U18 DoD leg. The next real miner cycle should land
records whose bodies carry `## Episode brief` (composed in
`_build_record` before `_scan_candidate`, ≤1200 chars refuse-not-clip).
**Done-shape**: a freshly mined record displays a collapsed "Episode
brief (b)" region on Detail; the brief reads as a story, not a
restatement of the finding; the run journal shows no brief-related
refusals (or shows them with intelligible reasons).
**Failure branches, planned**: (a) briefs missing → check the journal
for cap-refusals first (a systematic >1200-char pattern means the cap
or the prompt rubric needs tuning, spec change → gate); (b) briefs
present but vacuous → prompt-rubric iteration (12 §11), which is
spec-adjacent and gets a lightweight gate; (c) briefs present on
sighting-appends → **bug** (violates the source:session-only pin),
fix-with-regression-test.

## 3. FW-2 — The precision/recall observation window

**What**: ~2 weeks of journaled miner cycles, then one accounting pass
over `runs/*.jsonl` + the resulting queue: candidates found vs landed
vs cap-refused; already-canon rate; the human's accept/reject ratio on
mined records specifically (vs teach-sourced records).
**Why journaled-first**: the miner's knobs (rubric wording, caps,
digest thresholds) should move on measured misses, not on vibes — the
same counted-not-modeled doctrine the metrics obey. The run journal was
built as the observability contract (12 §journal) precisely for this;
FW-2 is its first real consumer.
**Done-shape**: a short dated memo in `research/` with the counts and
a tune/don't-tune disposition per knob. If tuning is warranted, the
rubric change is a 12 amendment → its own gate.
**Dependency**: needs FW-1 resolved first (briefs change what "landed
well" means).

## 4. FW-3 — The rejected-proposal digest loop

**What**: the analyst prompt carries a rejected-proposal digest as
negative exemplars (S-5/01 §3.3) so declined lesson classes stop being
re-proposed. This loop has never been observed working — rejections
have been too few.
**Drill**: when a class of proposal has been rejected 2–3 times with
notes, plant the conditions for the analyst to re-encounter that class
and verify the digest suppresses it (worker run → no re-proposal; or a
proposal that *names the digest entry* and argues why this instance
differs, which is acceptable behavior, not a failure).
**Watch item folded in**: digest growth. The digest rides the analyst
prompt; at some rejection volume it stops being a curated exemplar set
and starts being context bloat. No cap exists today. **Foreseeable
decision**: a digest budget (N most-recent-per-class?) once it exceeds
~a dozen entries — spec change, gated, not urgent.

## 5. FW-4 — The DP-2 live recall test

**What**: the standing experiment — one real lesson (the DP-2 window
placement rule) was deliberately left uncaptured, with the decline
logged, as a live test of whether the miner finds what a human declined
to hand-feed. **Scored when the miner meets it**: PASS = a mined record
lands carrying the lesson in recognizable form; the interesting partial
is a *sighting* of the transcript moment without a durable-lesson
extraction (rubric recall gap → FW-2 evidence).
**Standing rule preserved**: nobody captures it manually in the
meantime — doing so destroys the experiment.

## 6. FW-5 — The 2026-08-17 accounting

**What**: the O-3/O-7 revisit, now with a month of real numbers:
supply mix (teach vs import vs mined), time-to-triage median, queue
health (% pending >30d).
**Why it's in the supply theme**: its outcome arbitrates this theme's
future. Healthy queue + mined-majority supply → invest further here
(FW-2 tuning, maybe an autonomy-ladder step per 12, user-gated).
Healthy queue + teach-majority supply → the miner is a safety net, not
a producer; stop tuning it. Rotting queue → **stop feature work and
have the design conversation** — the founding fear materialized and
more supply would make it worse, per the 04 metrics section's own
instruction.
**Done-shape**: dated memo + a disposition note on this theme's items;
O-7 (ha-note unification) gets its deferred answer in the same pass.

## 7. What this theme refuses to do

No autonomy-ladder steps ahead of FW-2's evidence (12's ladder is
explicitly staged on demonstrated precision); no new capture producers
(a fourth supply channel before the third is measured is pure E-3
risk); no embedding/similarity infrastructure for dedup — G-5's
trigger is *observed* lexical-clustering misses, and none have been
observed.
