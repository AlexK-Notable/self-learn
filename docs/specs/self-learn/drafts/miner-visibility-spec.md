# DRAFT — FW-34: miner near-miss visibility + canary recall checks

**Status: DRAFT 2026-07-18. Build-grade; unratified.** Proposed final
home: the **surface half** graduates as `09-surface-spec.md` §11 entry
**Y-24** (this draft owns Y-24 only); the **miner half** graduates as a
`12-transcript-miner.md` amendment (a new §12, sibling to the §11
episode-brief amendment it deliberately mirrors). Charter:
`forward/worker-ecology.md` §5 (transcript-intake domain — "near-miss
visibility, mostly rendering over the existing journal") + §6 (the
file:line anchors below); `forward/supply-quality.md` §5 (the DP-2
canary lineage, FW-4). **Binding rule inherited from the charter**
(worker-ecology §2 "field reporter", §5, and the queue-pollution fear of
supply-quality §1): *aggregate counts with an on-demand drill, never a
second queue.* Every decision below is measured against it. Invariants
**M-1** (never auto-route) and **M-3** (never load-bearing) are inviolable
and reaffirmed §6. All file:line anchors verified against master
2026-07-18; re-verify before building (worker-ecology §6 drift note).

## 0. What already exists (audit of the journal machinery)

The run journal is a first-class contract already (12 §8 A1, shipped).
Verified sites:

- `miner.py:130 journal_path()` → `miner_dir()/journal.jsonl`; append via
  `:1135 _journal()`; `:85 JOURNAL_CAP_BYTES = 2_000_000` truncate-oldest.
- `:1142 read_journal(limit=20)` — tolerant read (OSError → `[]`, bad line
  skipped). `mine status --json` (`cli.py:527-538`) emits
  `{last_run, stale, runs: [entry…]}`; the UI's `MinerBlock`
  (`models.py:355-498`) consumes it verbatim (no server-side re-derivation
  — worker-ecology §6).
- **Per-candidate dispositions today** (`_reconcile_and_land`, def at
  `miner.py:934` (~934-1130), written via `:760 _outcome(result, origin,
  tag, **extra)`): `landed`, `folded(record)`, `recurrence(record)`,
  `recurrence-already-known(record)`, `dropped-rejected(record,sightings)`,
  `dropped-cap`, `dropped-invalid(reason)`, `dropped-land-failed(reason)`,
  `scan-refused(rule)`, `fold-quote-scan-refused(rule)`,
  `quote-dropped-overlength`, `skipped-known-origin`,
  `skipped-resolved(record)`, `resurfaced(record,sightings)`,
  `match-claim-invalid(claimed)`. Each entry is
  `{origin, outcome, **extra}` where `origin` is `transcript:<sid>#L<n>`.

**The precise gap.** An outcome dict carries the enum + the transcript
`origin` + a few ids/reasons — **never the candidate's draft content**
(trigger / instruction / fact / `why_durable` / quote). Transcripts are
pruned on `cleanupPeriodDays` (12 §0/§3), so by the time a human notices
a near-miss the raw episode is gone and **there is nothing to promote
from**. FW-34 is: (a) add a self-contained snippet so a near-miss is
recoverable; (b) render the counts + drill; (c) one promote action;
(d) canary recall counts. (a) is the only new *miner* write; (b)-(c) are
rendering; the charter's "mostly rendering" holds.

## 1. Journal enrichment — the near-miss snippet (12 amendment)

### 1.1 The human-facing disposition (folds the internal enum to 5)

The journal keeps its shipped `outcome` vocabulary unchanged (12 A1). Each
outcome that is a **near-miss** (the reader found something the run did not
land) gains an emitted, human-facing `disposition` so the UI renders it
verbatim (no UI-side mapping — the no-derivation rule):

| `disposition` | Folds internal outcomes | Promotable? | Snippet stored? | Record id shown? |
|---|---|---|---|---|
| `cap-refused` | `dropped-cap` | **yes** | yes | n/a (no match) |
| `rubric-dropped` | new reader `near_misses[]` (§1.3) | **yes** | yes | n/a (no match) |
| `already-canon` | `folded`, `skipped-resolved`, `recurrence`, `recurrence-already-known`, `skipped-known-origin` | no | no | yes (links the matched record) |
| `rejected` | `dropped-rejected` | **no** | **never** | **no** (see below) |
| `scan-blocked` | `scan-refused`, `fold-quote-scan-refused` | no | **never** (rule only) | no |
| `other` | `dropped-invalid`, `dropped-land-failed`, `match-claim-invalid`, `quote-dropped-overlength` | no | no (reason only) | no |

Each near-miss outcome additionally carries `reason`: one plain-words line
(Y-9 register — no enums, no ids, no unexpanded acronyms), e.g. *"a real
lesson, but this run had already landed its cap."*

**`rejected` — the deliberate double-absence** (§2.4's re-litigation ban,
made a data pin, not just a UI one): a `dropped-rejected` outcome
(`miner.py:1021-1031`) is rendered **counts-only** — it carries **no
snippet** *and* **no matched-record id**. Surfacing the rejected content
would resurface a lesson the human said no to; naming the rejected id
would invite re-promoting it. Both are withheld at the journal-write site,
so neither ever reaches `mine status --json`. **Concrete edit this pin
demands (delta-review, spelled out for the builder): the existing
`dropped-rejected` `_outcome` call at `miner.py:1024-1030` today emits
`record=record.id` — that kwarg is REMOVED (the `sightings` count may
stay; counts-only). Safe: nothing consumes that journal field today,
and the resurfacing lineage lives independently in
`rejected-sightings.json`.** The resurfacing counter
(`_rejected_counter_bump`, `miner.py:779`) stays the *only* path a
rejected class returns — untouched. t-e enforces the absence.

### 1.2 The self-contained snippet

For `cap-refused` and `rubric-dropped` only, the outcome carries
`snippet`: a small object that survives transcript pruning —
`{type, trigger, instruction}` (behavior) or `{type, fact, context}`
(knowledge), plus `why_durable`, drawn from the candidate dict already in
scope at the disposition site. It carries **no evidence quote** (§2.3 /
F3-(a)): the transcript span is not journaled; the near-miss's `origin`
(`transcript:<sid>#L<n>`) preserves the provenance ref, and promote passes
it as `--session`, never `--quote`. So the scan set below is the snippet
fields only. Landing safety, pinned (mirrors the episode-brief
compose-before-scan invariant, 12 §11):

**Build-fold amendment (2026-07-19):** the shipped snippet also carries
`scope` and, for behavior, `kind` — when the source dict has them (a
full `candidates[]` entry does; the leaner `near_misses[]` entry, §1.3,
does not). These are the *only* source §2.3's promote argv has for
`teach --<scope> [--kind …]`; without them promote could not build a
scope-correct call at all. Same scan + `MAX_NEARMISS_SNIPPET_CHARS`
coverage applies to them as every other snippet field — no new landing
surface. A `rubric-dropped` snippet with no `scope` (the common case,
since `near_misses[]` never carries one) falls back to `teach`'s own
documented project default (01 §2) at promote time.

- **Build-pin — scan *before* `_outcome`, at EACH disposition site.** The
  snippet is `secret_scan`-ed **field-by-field** and reduced to a clean
  dict, `{scan_refused_rule: "<rule>"}`, or `{overlength: true}`
  **before** the `_outcome(result, origin, …, snippet=…)` call — nothing
  enters `result.outcomes` unscanned. Named sites: **the `dropped-cap`
  branch, `miner.py:1046-1049`** — which today fires *before*
  `_build_record`/`_scan_candidate` (`:1050-1057`), so cap-refused prose
  is **currently never scanned at all**; this is the leak the pin closes —
  and **the new `near_misses[]` handler** (§1.3). A snippet that trips the
  scan is stored as `{scan_refused_rule}` — **rule name only, never the
  content** — and `promotable:false` (§2.3, F5). (A `scan-blocked`
  candidate failed the landing scan and never reaches here; this pin
  guards the *near-miss* prose, which the landing scan never touched.)
- **Char-capped, refuse-not-clip.** `MAX_NEARMISS_SNIPPET_CHARS` (pin
  **600**, ≈ the quote/field register; smaller than the brief because a
  snippet is a draft stub, not a story), checked in the same pre-`_outcome`
  step. Over the cap → `{overlength: true}` and the near-miss records
  *counts only*; a truncated draft is never journaled.
- **Cache-local, like the whole journal** (12 §10-8): the snippet lives in
  `journal.jsonl`, never autosynced, never a tracked file. Only an
  explicit human **promote** (§2.3) lifts it into the repo — through
  `teach`'s full scan/gate, exactly as if the human typed it.

### 1.3 `rubric-dropped` — the one reader-output extension

`cap-refused` / `already-canon` / `scan-blocked` / `other` are all
observable from candidates the reader *already emits*. `rubric-dropped`
— "the reader saw a moment but judged it below the durability bar" — is
invisible unless the reader names it. **This is the one genuine
Phase-2 output-schema addition** (see Conflicts): an **optional**
`near_misses: [{type, trigger|fact, instruction|context, why_durable,
session, line, confidence}]` array beside `candidates` and `fire
observations` (12 §2). It is marginal output tokens in the same paid
`claude -p` call (the episode-brief §11 posture), and the miner works
completely without it (M-3). Every `near_misses` field rides the
**identical** injection-bandwidth defenses as candidate fields:
`MAX_FIELD_CHARS` (1000) refuse-not-clip, the §1.2 build-pin scan
(field-by-field `secret_scan` **before** `_outcome`, in this handler), and
— for its `session`/`line` ref — `_valid_ref` (`miner.py:906`) gating
before it builds the origin (a ref that fails `_valid_ref` drops the whole
near-miss, never a guessed origin). Reader containment (Read/Grep/Glob-less,
§10-2) is untouched.

### 1.4 Retention

The 2 MB `JOURNAL_CAP_BYTES` truncate-oldest is unchanged; snippets make
each `ok`-run entry larger, so the window holds fewer runs. Accepted —
the journal is a rolling recent-activity surface, not an archive; the
counts a human acts on are always the most recent run. Revisit only if a
run's entry alone approaches the cap (it cannot: cap × snippet-cap ×
per-run landing cap all bound it).

## 2. The surface — Y-24 (09 §11)

### 2.1 Page-level composition statement (FW-19 tripwire, required)

Y-24 ships **zero new top-level regions.** It extends the existing Front
**Miner** region (`index.html` §`aria-label="miner"`, lines 109-129;
`models.MinerBlock`). Front regions after the addition, in display order:
status-strip → Buckets → *Is it holding?* (cond) → *Open follow-ups*
(cond) → Worker → **Miner** *(extended)*. The near-miss count rides the
Miner block's existing one-line summary; the drill is a **default-collapsed
`<details>`**, the same progressive-disclosure posture as the episode
brief (09 §2.3) and the existing `runs` disclosure right beside it —
"compose, don't stack" (ui-ux §2/§4). No region-count growth: the FW-19
tripwire is not tripped.

### 2.2 The one-liner and the drill

- **One-liner** (always visible, in the Miner block): *"miner: N sessions
  read, K landed, M near-misses"* + the existing `last run <ts> — <stale
  label>`. `M` = count of near-miss outcomes in **the latest `ok`/
  `landed-uncommitted` run only** — the same run the counts describe.
- **Drill** (collapsed `<details summary="near-misses (M)">`): **rows from
  that one latest run only** (F4). Older runs' near-misses are **never
  re-surfaced as rows** — they age out with the journal (§1.4). An
  accumulating multi-run list would be exactly the standing worklist the
  charter forbids; the drill is a snapshot of the last pass, not a ledger.
  A row shows: the `disposition` badge, the plain-words `reason`, and —
  for promotable rows — the snippet's trigger/instruction (or fact/context)
  as a single dimmed draft line. `already-canon` rows link the matched
  record id; `rejected`/`scan-blocked`/`other` rows show the reason only
  (no content, no id — there is none to show).

### 2.3 The one allowed action — promote to pending

**`promotable` is emitted by the CLI, one rule (F5):** `promotable == true`
**iff a real content snippet exists** — i.e. `snippet` is a populated
`{type,…}` dict, and **false** for `{scan_refused_rule}`, `{overlength}`,
absent (pre-amendment rows), or any non-promotable disposition. The drill
control and the endpoint read the *same* flag, so a row can never offer a
Promote button the endpoint would reject.

A **promotable** row (`cap-refused` / `rubric-dropped`) carries exactly one
control: **Promote to pending**. It is a *human capture act* (the human,
reading the miner's draft, chooses to capture it), so it **rides the
`teach` writer** — the existing human-capture verb with the full scan /
field-cap / pending-gate discipline (`teach.py`).

- **Endpoint**: `POST /mine/near-miss/promote` (sibling to `/mine/run`,
  `routes.py:677`), body = run-id + outcome index (server re-reads the
  snippet from `mine status --json` — server truth, never a
  client-supplied body; mirrors the Y-18 rehome re-resolve; rejects a
  non-promotable index). It calls `runner.run(["teach", …])` with the argv
  built from the snippet: `teach --<scope> --type <t> [--kind …] --trigger
  … --instruction …` (or `--fact/--context`). **Provenance (F3-(a)): no
  `--quote`** — the near-miss carries no journaled evidence span; instead
  the validated origin's session id rides as **`--session <sid>`** (parsed
  from `transcript:<sid>#L<n>`), so the trail "the miner saw it here"
  survives as the record's evidence session even though `source` is `teach`
  (honest: a human captured it). **Build-time verify (delta-review
  residual): teach's docs pair `--quote` with `--session` — confirm the
  parser accepts `--session` alone; if it refuses, the build amends the
  teach parser to accept it (an 08-owned nit riding this unit), never
  synthesizes a quote.** t-j pins the no-quote argv either way. No arm-then-confirm ceremony, matching
  `/mine/run` and `/worker/kick`.
- **Consent posture**: the tap *is* the confirmation (teach's legitimacy
  model — 12 §0). One tap → one real pending record in the correct bucket
  → the worker analyzes it before it shows as a card. It has left the
  near-miss list and joined the ordinary queue — **there is no near-miss
  state left to manage.**

### 2.4 Absence of action is the design

The drill has **no other control.** No dismiss, no dismiss-with-note, no
snooze, no "seen." A near-miss is either promoted (→ the one real queue)
or it ages out of the rolling journal on its own. Withholding every other
verb is what keeps this a *view over counts*, not a second queue the human
must service (the charter rule). `already-canon`, `scan-blocked`, `other`,
and **`rejected`** are shown but never promotable — `rejected` under the
§1.1 double-absence pin (no snippet, no id): promoting it would re-litigate
a human's recorded *no* (12 §8 Q4), so the resurfacing counter
(`_rejected_counter_bump`, `miner.py:779`) stays the *only* path a rejected
class returns, untouched.

## 3. Canary recall checks

The honest low-ceremony mechanism (no synthetic transcripts, ever):

- **Plant** (a human act, in a real session): the user states a genuine
  durable lesson in-session as normal speech *and* runs
  `self-learn canary plant --lesson "<short description>"
  [--expect "<trigger phrase>"]`. This writes a canary to
  `miner_dir()/canaries.json` with plant-ts and (best-effort) the session
  id — cache-local, like cursors. The plant is *the human deliberately
  dropping a known-catchable lesson into the wild.* It never writes to a
  transcript (those are Claude Code's append-only logs; the CLI cannot and
  must not forge them).
- **Score** (deterministic CLI, next run, no reader change): after
  `_reconcile_and_land`, the CLI compares each open canary's
  `lesson`/`expect` against this run's landed + folded records + sightings
  by the **same title-token overlap the WORKER's recurrence-suspect path
  uses** — `worker.py:961 _tokens` + the Jaccard ≥ `SUSPECT_JACCARD` (0.6)
  test at `worker.py:1003`, reused here, not reimplemented — so no new
  infrastructure, fixture-testable, drift-free (the §5 "signal is
  structural" doctrine; the reader's containment is not widened). Outcome
  per canary: `caught` (matched from a session mined after plant-ts) or,
  once its source session has been mined with no match, `missed`.
- **Counts only** (worker-ecology §4-3 "counts, never scores"):
  `{planted, caught, missed}` + the open list. A weak title-token match is
  acceptable here precisely because a mis-scored canary is *cheap* (unlike
  a missed dedup, 12 §5) — and the honest counts are themselves the signal
  that the heuristic needs work (a human-obvious catch scored `missed`).

**Build-fold amendment (2026-07-19):** the "best-effort session id"
plant records comes from a `CLAUDE_SESSION_ID` env var — nothing in the
current stack sets it. Until an operator exports it (or a future
producer wires it), a planted canary's `session` field is `null`, and
the `missed` half of scoring (which requires it) never fires — `missed`
is dormant in production. This is a degrade-safe absence, not a bug: an
absent/wrong session id can only leave a canary `open` longer, never
produce a false `missed`. `caught` scoring is unaffected (it needs no
session id at all).

**What canaries never do**: (1) never auto-generate or inject transcript
content — the miner grading homework it wrote is worthless; (2) never
count toward supply metrics — the mined-card accept rate (12 §4) stays
"adjudicated cards only"; canary recall is an orthogonal *recall* probe,
reported on its own line. **DP-2 relationship**: the DP-2 window-placement
rule (supply-quality §5 / FW-4) **stays the first natural canary and is
never planted artificially** — it is already live, adjudicated by human
judgment at review (PASS = a mined record carries it recognizably). The
`canary plant` machinery is the low-ceremony *supplement*, and
`plant --lesson` **refuses any lesson that names DP-2** (guard, tested)
so the standing experiment is never contaminated.

## 4. `mine status --json` additions + degradation

- **Per-run entry**: unchanged top-level keys, plus `near_miss_count`
  (int). Each near-miss outcome dict gains `disposition`, `reason`,
  `promotable` (bool), and `snippet` (object | `{scan_refused_rule}` |
  `{overlength:true}` | absent). Existing `outcome`/`origin`/`record`
  keys are untouched (additive extension of 12 A1).
- **Top-level**: `canaries: {planted, caught, missed, open: [{lesson,
  planted_at}]}` (absent/empty when none — the one-liner appends
  "· canaries K/N caught" only when `planted > 0`, no clutter otherwise).
- **`--fast` interaction: none.** `mine status` has no `--fast`; the
  Front page's fast path is `_cmd_status_fast` (`cli.py:450`) →
  `worker.fast_status` (`worker.py:1162`), pending-only, and is untouched.
  Near-miss + canary data ride the regular `mine status --json` the
  `MinerBlock` already consumes.
- **Degradation** (mirror the shipped skip+log): journal corrupt/absent →
  `read_journal` already returns `[]` / skips bad lines; a malformed
  `snippet` is ignored and the row renders enum+reason only; a missing
  `canaries` key reads as empty; `canaries.json` unreadable → `{planted:0…}`
  and a `log()` line, never a crash (E-11 spirit / M-3). **No backfill**
  (mirror §11): pre-amendment near-misses have no snippet → `promotable:
  false`, rendered as count+reason; nothing to reconstruct.

## 5. Test obligations + DoD

- **Unit (miner)**: (t-a) a `cap-refused` candidate journals a
  `snippet` that round-trips its trigger/instruction; (t-b) a **planted
  secret in a candidate's draft is journaled as `{scan_refused_rule}` —
  content never in `journal.jsonl` — on BOTH near-miss paths**: the
  `cap-refused` branch (`miner.py:1046-1049`, proving the pre-`_outcome`
  scan the current code lacks) AND the `rubric-dropped` `near_misses[]`
  handler (the §1.2 build-pin, mirroring 12 m-g); **the secret is
  planted in `why_durable`** — the easily-forgotten field — so a
  partial field-by-field scan that covers only trigger/instruction
  fails the test (delta-review refinement); (t-c) an over-cap snippet
  → `{overlength}`, no clipped content; (t-d) `rubric-dropped` from
  `near_misses[]` obeys `MAX_FIELD_CHARS` refuse-not-clip + `_valid_ref`;
  (t-e) `dropped-rejected` is emitted `promotable:false` with **neither
  `snippet` nor `record` id** present (the §1.1 double-absence).
- **Unit (canary)**: (t-f) `plant` writes a cache entry; a later run that
  lands a matching record scores `caught`; mining the source session with
  no match scores `missed`; counts only. (t-g) `plant --lesson` naming
  DP-2 is refused. (t-h) **`plant` writes ONLY `canaries.json` — no
  `*.jsonl` transcript under `~/.claude/projects/` is created or mutated**
  (the honesty pin: canaries never forge transcript content). (t-i)
  **canary catches never enter `supply_mix` or the mined-accept-rate**
  (`report`'s §4 surface): a run that scores a `caught` canary leaves both
  numbers byte-identical to the no-canary run.
- **UI/route**: (t-j) `/mine/near-miss/promote` re-reads server-side and
  builds the exact `teach` argv (matches `cli.py`'s parser, the `build_argv`
  discipline) — `--session` present, **no `--quote`** (F3-(a)); (t-k) the
  one-liner renders N/K/M; the drill is collapsed-by-default, shows **only
  the latest run's** rows (F4); a non-promotable row shows no control.
- **DoD / sandbox trial (user-present, one shape)**: with
  `SELF_LEARN_MINE_CAP_MAX=1`, force a `mine run` over a synthetic
  transcript carrying two clear failure→fix arcs so exactly one real
  candidate lands and the second is `cap-refused`. Then: `mine status`
  reports `1 near-miss`; the Front Miner region shows "…1 near-miss";
  expand the drill; tap **Promote to pending**; a pending record appears
  in the right bucket carrying the miner's draft and is worker-analyzed;
  **confirm no near-miss bucket, card, or review flow exists anywhere.**

## 6. Non-goals

No dismiss/snooze/note/seen on near-misses; no near-miss bucket, cards,
or review cadence (the charter rule — the drill is a view, promote is the
only exit); no multi-run near-miss list (F4 — latest run only); no
auto-promotion (M-1); no re-litigating rejected records (the `rejected`
disposition is counts-only, no snippet, no id; resurfacing counter is the
only return path); canaries never synthesize transcript content, never enter
supply metrics, never auto-plant, and never touch DP-2; no reader
tool-surface widening (canary scoring is deterministic CLI); no journal
autosync (only human promote moves a snippet into the repo, via teach);
no backfill; no embedding/similarity work (G-5-gated, 14 §6).
