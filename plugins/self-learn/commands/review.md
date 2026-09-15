---
description: Triage pending self-learn records in a bounded review batch — analyze, card, resolve via CLI verbs.
argument-hint: [--skill <name> to scope the batch]
---

*(For readers of older specs: what this command calls* **retire** *the
specs used to call* **graduate***, and what it calls* **replaced** *they
called corrective supersession — both land in the same ledger status,
`superseded`, told apart by the field that names what covers or replaces
the record.)*

Run one bounded self-learn review session. You are a **thin caller**: you
analyze and present; every resolution — compile, commit, sentinel, push,
note capture — is a `self-learn` CLI verb. You never edit canon targets,
never run git, never implement routing mechanics yourself. If you find
yourself about to compile or commit something, stop: that is the verb's
job.

Let `LEDGER = ${SELF_LEARN_HOME:-~/.self-learn}` throughout — the ledger
home, its own git repo, independent of any code repo (doc 13).

## Session start

1. `self-learn sentinel hold` — pause autosync for the batch. (The verbs
   heartbeat it on every mutation; you release it at the end.)
2. Read the routing doctrine — you will analyze with it:
   `~/.claude/skills/self-learn/references/routing-doctrine.md` (the
   deployed skill's references dir)
   and the card-section registry beside it (`card-sections.yaml`) — the
   sections it defines are what you write per proposal and show per
   card, in its order, under its labels. This command deliberately names
   no section keys: the registry is the only source of the section set,
   so section changes never require editing this file.
3. `self-learn list --json` — build the queue: **treat every item the
   CLI returns as queued** (it already excludes still-deferred records;
   an expired deferral resurfaces with `status: deferred` — never filter
   on `status` yourself), **oldest first**, at most **10 cards this
   session** (respect a `--skill <name>` scope from
   $ARGUMENTS). Bounded batches are the point: a session that tries to
   drain everything is the session that kills the habit. Say up front how
   many are pending and how many this batch covers.

## Per record: analyze BEFORE presenting

For each queued record **without a fresh valid proposal** (`has_proposal`
false, or `proposal_fresh` false), perform the inline analysis the M2
worker will later take over (a pure producer swap — same file, same
schema):

1. Read the record (`pending/lrn-<id>.md` in its bucket under `LEDGER`:
   `skills/<name>/` for `skill:<name>` scope, `projects/<slug>/` for
   project scope (the slug appears in `list --json` output), `user/` for
   user scope).
2. Apply the doctrine and write the proposal sibling
   `<bucket>/proposals/lrn-<id>.yaml` — destination, alternates,
   rationale, already_canon(+reason), model, analyzed_at, **and the
   `card:` map** — every section the registry requires for this proposal
   kind, written per that section's `instruction` and the doctrine §8
   register (story first; concrete behavioral before/after; steelman the
   no). **Never emit `record_sha`** — the CLI stamps it next.
3. `self-learn proposal validate <id>` — validates the schema and stamps
   `record_sha`. Exit 1 = your YAML is schema-invalid: fix it and
   re-validate. Exit 2 = secret-scan hit: treat as blocked (below).

Only then present the card. A card must never show an unanalyzed record.

**Fast path (M2):** a record whose proposal is fresh and schema-valid
(`has_proposal` + `proposal_fresh` both true — usually the background
worker's output) is presented AS-IS, one tap, no re-analysis. The inline
analysis above is the fallback, kept forever, never the default.

## The card

**Layout — the card is the `card:` map, rendered for a human.** The
question text is the card sections in registry order (headline leading,
under the registry's labels where a label helps), written for a reader
returning cold after a week away. Machine metadata — record id,
destination enum, scope, diff preview — is a compact footer AFTER the
human sections, never the opener. Do not lead with `lrn-…`, do not
paste record slugs as titles, and do not let filing rationale masquerade
as decision context. Render every section present in the proposal's
`card:` map — including any whose content is "nothing here": an explicit
all-clear is decision information, not filler, and the registry's
instructions say which section gives the reader their foothold for the
Discuss option.

One AskUserQuestion per record — **four options** (the tool's hard
limit; free-text "Other" is always there beyond them):

- **Apply** — the option's description names the destination; the
  preview may carry the diff of what the managed section/reference
  gains. Honesty note on the card: the compiler regenerates from the
  record at apply time, so what lands may differ in detail from the
  preview. On choice:
  `self-learn route <id>` (proposal's destination) or
  `self-learn route <id> --dest <target>` if the user overrides; add
  `--note "…"` if they give a why.
  **Hook proposals are the one exception to regenerate-at-apply
  (M3-2):** the preview must show the proposal's `script` field IN FULL
  — the exact executable bytes the route will commit verbatim (P9: eyes
  on the exact diff, never a summary) — plus the analyst's stated
  over-block from the rationale. After a hook Apply, the CLI prints two
  required manual steps (./install.sh + the settings.json snippet):
  relay them verbatim — the guard is inert until both are done. Inside a
  *human* review session the two manual steps stay exactly as printed —
  with one shortcut: `self-learn hook activate <id>` performs both by
  hand (and `hook deactivate <id>` reverses it), no setting required.
  Separately, when the user's delegation switch
  (`overseer.hook_activation`) is on, the overseer places and activates
  an approved hook route by code on its own owned path (S-66); with the
  switch off it places the route and parks it with a receipt saying
  activation is delegated but switched off.
- **Discuss** — open-ended: drop into conversation with the record and
  proposal in context. You may **edit the pending record** per the user's
  direction (pending substance is freely editable; use Edit on the record
  file only). Every Discuss-path edit **ends by calling
  `self-learn proposal validate <id>`** — it re-stamps freshness and
  scans the edit. Exit 2 = scan hit: the card is **BLOCKED** — show the
  matched span, and do not resolve this record until the user redacts or
  rephrases (edit again, re-validate). Exit 1 = schema-invalid proposal:
  fix and re-validate before proceeding. When the discussion lands on a
  decision, re-present the card (or invoke the verb the user named).
- **Reject** — ask one line: *why?* The note is the analyst's fuel (`_digest`
  reads it, though as of U7 that function has no caller in the analyst
  prompt path — prior decisions arrive there as cited cases instead) —
  encourage it, never gate on it. Then `self-learn reject <id> --note "…"`
  (or without `--note` if they decline).
- **Defer** — `self-learn defer <id>` (default +30 days) or
  `self-learn defer <id> --until YYYY-MM-DD` if they name a date.

**Applying decisions — `self-learn batch`, never a hand-written script
(U-verbs S-54, R3).** Each bullet above names the verb call ONE decision
resolves to; you record it as one line in this session's decision sheet
(`{id, verb, ...that verb's own fields — note/until/to/dest/…}`) rather
than firing it immediately. Apply the whole sheet in **one locked run**
at Session end (or at any natural pause — mid-batch is fine): `self-learn
batch <sheet.yaml>`, previewed first with `self-learn batch <sheet.yaml>
--dry-run` when you want to see every item's outcome before committing
anything. `batch` is the **one** executor — 42 verb calls across two
hand-written apply scripts is exactly the scaffolding this replaces; a
review session must never hand-sequence a run of individual `self-learn
<verb> <id>` shell commands as its own bulk-apply mechanism. A sheet item
naming a `host` verb or a hook route is refused at validation (nothing
runs) — sequence those by hand, outside the sheet. A `--dry-run` of a
sheet carrying a hook route reports that item refused and exits 1,
exactly as the real run would — the overseer's own runner (13 §7.4) is
the one caller a hook route is ever not refused for, and this session
is never that caller.

**A sheet may name the decision case it is applying (S-65).** A
top-level `case: case-<8hex>` key is optional; when present, the sheet's
receipts thread automatically to that case's Application section (no
extra call needed). An unknown top-level key — including a hand-written
`actor:` — is refused before item 1 runs, the same way an unknown item
key is refused today. Results JSON gains the same `case` field, and a
sheet item after a stop point is reported with `state: not-attempted`
rather than being silently dropped from the output.

**One new verb joins the sheet grammar**, scanned and lock-guarded like
every other write:

- `revise` — a wording fix, never a substance change: keys `section`,
  `text`, `because`. Refused on anything but a pending or deferred
  record. Use it before a `route`/`reject`/etc. in the same sheet when
  the lesson is right and its sentence is wrong.

`reconsider` is not a sheet verb — it is a command,
`self-learn reconsider <lrn-…> --case case-…`, run by the steward's
runner or by hand against a successor case (`kind: reconsider`, naming
the record's original case in `supersedes`). The sheet that then carries
the corrected verb names that same case with the top-level `case:` key;
naming it is what makes a resolution verb legal again on an
already-routed record — a resolution verb on an already-routed record is
otherwise refused. This is what lets a wrong route or reject be
corrected: the original case is marked superseded by the `reconsider`
case, and it is the new verb the sheet applies that actually takes
effect. For a wrong **reject** specifically, the corrected sheet's first
item is `reopen` (already legal on a rejected record, no case needed for
that step) followed by the corrective verb, both receipted to the same
case — reopening back to `pending` is what makes the corrective verb
ordinary again, never a further widening of `route`/`rehome`/`revise`
to admit a rejected record directly. A `routed → rejected` (or
`→ deferred`) correction is a plain status flip plus the removal of the
record's compiled line from its host surface inside the same locked
section — never a `supersede` of the record; the CASE is superseded,
the record is re-decided (decided at U5's gate, 2026-09-14). A record
routed to a `reference` or `hook` destination cannot yet be corrected
this way and the verb refuses by name.

**Two different undo paths — do not confuse them.** Among supersessions,
`reopen` is for a mistaken retirement only: `self-learn reopen <id>`
restores a wrongly retired record to `pending` with no successor case
needed, because the named surface never actually covered it, so there is
nothing to supersede. A wrong `route` or other resolution is revisited
with `reconsider` instead, which opens a new case and a new verb rather
than reverting the old one — a routed record's correction is itself a
decision, recorded as one, not a reset to an earlier state. `reopen`
also keeps its existing use for a rejected record, unchanged; it is
refused for a replaced record, which has a live successor.

`by:` names the actor that made the decision and is permitted on every
resolution verb (this build widens it from today's `route`-only key);
inside a human review session it is implicit (`by: human`) and you never
need to set it. The value set now includes `steward` and `overseer`
alongside `human`, `analyst`, and `agent` — those two are written only by
the steward's and the overseer's own runners, never by a hand-written
sheet.

**Scope mismatch** — not a card option, but tell the user when you see it:
if a pending record's firing range clearly belongs to a different scope
than the bucket it's filed in (captured at user scope but really only
fires inside one skill, or vice versa), `self-learn rescope <id> --to
<scope>` (`user` or `skill:<name>`) is the repair. Say plainly that using
it **discards the current proposal and re-analyzes the record in the new
bucket** — the analyst's judgment is bucket-relative, so a carried
proposal would render a stale card reasoning from the wrong scope.

**Retire** — when the proposal sets `already_canon: true` on a single
card, the right resolution is retirement, not routing: replace Apply with
**Retire** (`self-learn retire <id> --covered-by <surface>`), naming the
surface that already covers it (a `claude-md`, a `SKILL.md`, a reference
file, or an output style), and showing `already_canon_reason`. Never
reject an already-canon record for being redundant — the lesson won.
(`graduate` is the old name for this verb and stays a hidden alias for
one release; `superseded_by` now carries `covered_by:<kind>:<name>` in
place of the old literal `"canon"`.) For compatibility, `report --json`
keeps its existing `graduated` machine key even though human-facing
report text says "retired."

**Bulk-acknowledge** — a homogeneous group of already-canon records gets
**one** multiSelect card listing them, not N detail cards. Each item gets
**one human line** (the proposal's first card section in registry order —
what the episode was about, in plain words) plus where canon already covers it
(`already_canon_reason`); the record id rides along as metadata, never
as the label. Every selected record resolves via its own
`self-learn retire <id> --covered-by <surface>` call; any the user
de-selects gets an individual card in this batch.

**Budget card (U-cap, 02 §4).** Run `self-learn report --json` and read
`.context_budget`. If **any** signal carries `flagged: true`, open the
batch with **one** budget card — never one card per signal. The card
**states the flagged facts and offers**; it never demands, never blocks,
and is dismissible with no action.

Offers, in this order, and only for signals that are actually flagged:

- **`crowding` flagged** → **state the near-duplicate pairs and their
  scores.** Do **not** offer `route --collapse`: those records are
  routed, and the collapse path refuses anything not still pending
  (`verbs.py:2559-2564`), so the offer would be an action that cannot
  run. Describe the consolidation path in prose instead: capture one
  rewritten record covering both lessons, linked to one predecessor with
  `self-learn teach … --supersedes <lrn-id>` (**one id — the flag is
  single-valued and the field is scalar; never repeat it**), route it,
  then retire each remaining member individually with
  `self-learn retire <id> --covered-by <surface>`. The human runs these;
  the card runs nothing.
- **`composition` flagged** → offer **Retire**
  (`self-learn retire <id> --covered-by <surface>`) for the named oldest
  entries, showing `managed_share`, `managed_share_growth_30d_pp`, and
  `caution_share`. State `past_is_lower_bound` when any delta is shown.
- **`growth` flagged** → state the rate and `doubling_days_est`. **Offer
  nothing.** There is no per-record action for a rate; it is a fact for
  the human, and manufacturing an action for it would re-create the cap.
- **`budget` flagged** → state `session_baseline_words` /
  `session_baseline_tokens_est` and the largest **baseline** surface,
  then `session_max_words` with `largest_project_key` named as the
  project that would add it. **Never quote `all_hosts_words` as a
  session cost** — if it is shown at all, label it "not a session cost".
  If `totals_are_lower_bound`, say so.

**Tri-state, before any of the above:** a signal whose `flagged` is
`null` is **not** an all-clear. Say "could not measure" and name the
states from `surfaces_unmeasured` / the row `state` values. A card that
renders `null` as quiet is the exact fail-open the design forbids.

**The constraint that rides on every offer:** read
`.context_budget.conditional.reference.safe_overflow`. When it is
`false` or `null`, the card **must not** suggest "route it to references
instead" as the relief. Quote `.why`. Routing to an uninstrumented or
cold shelf trades a measured cost for an unmeasured one, and that is the
move this whole design exists to refuse.

**A signal is never a reason to refuse a route.** If the human routes
into a flagged surface after reading the card, that is a correct outcome
and the verb behaves identically to an unflagged route.

**Merge cards (M2).** After the budget card, before the per-record cards, list
`<bucket>/proposals/merge-*.yaml`. A cluster whose members are ALL still
pending gets ONE card (never per-member cards): show each member's
leading card section (registry order), with the `suggested_survivor` pre-selected and overridable.
Apply resolves the whole cluster in one verb call:
`self-learn route <survivor-id> --collapse <cluster-id> [--dest …]` —
all mechanics (evidence merge, sightings, losers superseded, proposal
sweep) live in the verb. A cluster with any resolved member is
invalidated — never show its card; the worker sweeps the file.

**Contradiction edges.** If a proposal carries `contradicts:`, say so on
the card in plain words ("this conflicts with <target>"). After a route
the user approves, apply each edge they accept with
`self-learn link contradicts <id> <target>` — proposed by the analyst,
written only by the verb (11 §2.4).

**"Not holding" cards (11 §2.2).** After the queue cards, read
`self-learn report --json`: any ROUTED record with unconfirmed
recurrence-suspect telemetry (suspects exist beyond the record's own
`recurrences` list — match on the event `nonce` vs recorded `ref`s) gets
one card: *"Routed <date>. Sighted <N> times since. Revise, escalate,
tolerate, or retire?"* The resolutions map to verbs:
- **Revise** → capture the better wording (`self-learn teach
  --supersedes <id> …`) and route it — supersession does the retirement.
- **Escalate** → same, routed toward the stronger surface (`--dest`).
- **Tolerate** → `self-learn confirm-recurrence <id> --event <nonce>
  --tolerate --note "<why the rule stays>"`.
- **Retire** → discuss; retirement without a successor is
  `self-learn retire <id> --covered-by <surface>` (something already
  loaded covers it) — or, if a rewritten successor exists, `supersede`
  (which displays as **replaced**, `replaced by lrn-…`) — the user
  chooses, you never guess.
- **Dismiss** → `self-learn dismiss-suspect <id> --event <nonce> --why
  <reason> [--note "<why it's false>"]` — the sighting was a matcher
  false-positive, not a recurrence at all; the telemetry event is
  preserved, only the card clears.
A plain confirmation (recurrence is real, fix comes later) is
`confirm-recurrence` without `--tolerate`. Read `basis` before choosing
Tolerate vs Dismiss: `fire-suspected-violation` (renamed from
`fire-violated` — a fire is always a suspicion for the steward to check
against the transcript line, never a confirmed violation by itself) is
the model's own suspected report, while `miner-match` and
`title-token-overlap` are text-similarity heuristics that can fire on a
lesson nobody actually violated. (A basis recorded before this rename
still reads `fire-violated`; the CLI accepts both spellings on read.)

Read each verb's output line: it reports the commit and push state. Show
the CLI's message verbatim on the card and never work around it with
direct file or git operations. A non-zero exit is not one thing — read
which:

- **1** — the verb REFUSED (secret scan, dirty compile target, an
  unregistered host; on a hook route also: no validated hook proposal,
  a stale `record_sha`, or a failed example replay). An unknown record
  id is **64** (usage), not 1. Nothing was written. *(All five destinations compile as of M3 — the
  old exit-2 "compiler lands at M3" no longer exists for verbs; a hook
  refusal names the missing step, show it verbatim. The ledger
  `config.yaml` `one_motion_route:` opt-in — S-10 amendment 2026-07-16 —
  affects only one-motion `teach --route`; inside review you always
  route captured records through the cards, config or no config.)*
- **3** — committed, but the **push failed**. The resolution is safe
  locally; `self-learn push` retries it (see Session end).
- **4** — committed, but the push hit a **rebase conflict**. The rebase was
  aborted and the commit kept; this one needs a human `git pull --rebase`.
- **5** — the ledger home is missing / not a git repo. Nothing was written
  and nothing can be: stop the batch and tell the user.
- **6** — a git operation failed or timed out **before the verb wrote
  anything** (commonly: another producer — a worker or the miner — held
  the commit lock too long). The lock is taken before the first mutation,
  so nothing is half-done: it is safe to retry once the other producer
  finishes. `reconcile` also returns 6 when it refuses an invalid orphan;
  there the repair is the one it prints, not a retry.
- **7** — the record WAS written but its **commit failed**. This is the
  opposite of 6 and must never be treated as it: the record has already
  moved (e.g. pending→resolved) and a blind retry fails with 64 "record
  not found". The CLI prints the exact repair command — show it verbatim
  and say the ledger is half-written. `self-learn reconcile` fixes the
  simple cases (an uncommitted record); a half-committed rename needs the
  printed command.
- **64** — usage error (bad flag/id); for `batch`, also a whole-sheet
  validation failure (unknown verb, unknown item key, malformed id,
  `version != 1`) — nothing in the sheet ran. `self-learn teach` (the
  Revise action above, and one-motion `teach --route`) shares this same
  64 for its own usage errors (A22, fold r1, 2026-09-04 — was a private
  2; a bad *home* is still 5, unchanged).
- **8** — `batch` only (`EXIT_BATCH_PARTIAL`): the run completed with
  **some items applied and at least one refused** — the ledger DID
  change. Read the `--json` envelope's per-item `rc`/`state` to see which
  landed and which refused; a refused item's own reason renders the same
  as a single verb's would. `batch` returns **1** only when **nothing**
  in the sheet landed — 1 keeps its "nothing was written" meaning exactly
  even inside a batch; 8 is what a partial run reports instead.

Only 3, 4, 7 and 8 mean "the ledger changed"; 1, 5, 6 and 64 mean it did not.

**`batch`'s process code, when more than one item hits a ledger-level
failure (3/4/6/7), is the WORST of those under the severity order
`7 > 4 > 3 > 6 > 1 > 0`** — never a raw max of the item codes, which
gives the wrong answer on two pairs (`{3,6}` and `{4,6}`, where the
ledger DID change but a naive max reports 6, "nothing written"). Read
`batch`'s own summary line, never re-derive the process code by hand.

Codes 6 and 7 exist separately because they used to be one code making one
claim, which was true for one of its two causes (audit 2026-07-16). If you
ever see a self-learn surface report a state it cannot know — "nothing was
written" from a layer that did not do the writing — that is the same bug
class, and it is worth a capture.

Separately from the table above, the unattended run commands — `mine
run`, `worker run`, `worker kick`, and `steward run` (the `## Cases` and
`## Steward run` sections, below) — use a smaller, separate contract
(FW-85): `0` something ran and landed; the new `EXIT_HELD` (10) means
the run found nothing due and held — this is NOT a failure, and before
FW-85 it was indistinguishable from `0`; `6` a STOP intent blocked the
run before it started — a different cause from the verb table's `6`
above, with the same consequence: nothing was written; `64` usage.
Before FW-85, a held run and an actually-successful run both returned
`0`, so a wrapper script or a human glancing at `$?` could not tell
"nothing to do" from "something happened" — `EXIT_HELD` is the fix, not
a new failure mode.

## Cases

Every steward and overseer decision is a **decision case**
(`$LEDGER/cases/<yyyy-mm>/case-<8hex>.md` — six frozen-then-appended
sections; S-65) rather than a bare verb call. You do not normally need to
touch these directly in a human review session — routing through the
cards above still works exactly as before — but they are how you inspect
what an unattended run decided, and how you correct it:

- `self-learn case show <id> [--evidence-only] [--json]` — the frozen
  decided account. `--evidence-only` is BLIND by default (no separate
  `--blind` flag): it is an ALLOWLIST, keeping only the frontmatter's
  `case`, `opened_at`, `actor`, `kind`, `records`, and `supersedes` —
  `outcome`, `superseded_by`, `parked_for`, `parked_reason`, `presented`,
  and any key added later stay out unless named here — plus the Identity
  and scope, Evidence, and Dependencies sections; never the Decision,
  Application, or Later-observations sections — so it hides the verb,
  the reasoning, and the receipts, not only the reasoning. Read it first
  if you are re-examining a decision before reading the full view, the
  same discipline the overseer follows.
- `self-learn case list [--since T] [--provisional] [--parked-for
  overseer] [--parked-reason <reason>] [--record lrn-…] [--json]` — the
  index; use it to find what ran overnight or what is waiting on the
  overseer. `--parked-reason` filters on the closed set (`hook`,
  `always-loaded-user-scope`, `broad-removal`, `authority-unclear`,
  `scope-conflict`).
- `self-learn case observe <id> --kind
  examined|presented|statement|corrected|dependency-moved --text …
  [--ref …] [--presented-outcome agreed|corrected|noted]` — appends a Later
  observations entry with its own `obs-<8hex>` id; never edits the
  frozen account. `--presented-outcome` applies to a `presented` observation only.
  A `statement` or `dependency-moved` observation whose reference is one
  of the case's own dependencies queues that case for the steward's next
  nightly run automatically — you do not additionally ask for a
  reconsideration.
- `self-learn statement add --verbatim … --ref
  transcript:<session>#L<n>|conversation:<obs-id> [--answers …]
  [--scope …]` — records something the user actually said, verbatim,
  with what it answers and its stated scope. `conversation:<obs-id>` is
  the reference to use for words typed into the overseer's own
  conversation, where no transcript line exists.
- `self-learn user-model add --statements stmt-…[,stmt-…]
  [--basis um-…@r…,…] …` / `user-model lapse um-…
  --changed-condition <key>|--contrary <ref>|--consolidated-into um-…
  --at <date>` — the human path into the model of the user. A system
  reading in containers B or C needs at least one statement id behind it
  — the CLI refuses one that names none. An entry is marked seen only
  through `case observe --kind presented`, never by any other write, and
  a presentation clears "provisional" regardless of what the user says
  in reply, or whether they reply at all.

A parked case (`kind: parked`, `parked_for: overseer`) is a question the
steward could not settle alone — its `parked_reason` names which of the
five kinds stopped it, and section 3 holds its tentative answer, if it
has one, and its reason for stopping there. Deciding a parked item
yourself in a human session still needs the successor case: write the
stage file, `self-learn case record <stage-file>` to get its id (naming
`supersedes: <parked case>`), put that id in the sheet's top-level
`case:` key, then apply the sheet the usual way — the receipts thread
back to the case automatically. Skipping the case leaves the parked case
with `parked_for: overseer` and no `superseded_by`, so it never leaves
the overseer's intake and draws a refused attempt every week. This is
the same order the overseer's own
runner uses when it decides a parked item in the user's stead — a human
resolving one is not a special case.

## Steward run

`self-learn steward run [--dry-run] [--json]` runs the same decision the
nightly `serve` job runs, on demand. It is the manual path for the
maiden run and for a human who wants a run right now rather than waiting
for the schedule; it never has a smaller authority than the automatic
run — it applies its own decisions immediately, the same as the nightly
job does, unless `--dry-run` is given. A normal run first resumes every
obligation discoverable from a committed `cases/runs/<run_id>.json`
manifest; cache `run.json`, result JSON, the journal, and the last-run
marker are projections and never recovery authority.

- `--dry-run` writes its stage files and no ledger commit or completed-run
  watermark — a fixture and
  inspection flag, never a rollout step. Use it to see what the steward
  would do before trusting it unattended, the same way you would inspect
  a batch sheet with `--dry-run` first.
- Every routed or resolved record from a steward run carries `by:
  steward` — filter `case list` or the record's own history to see which
  decisions were the steward's.
- Exit codes follow the unattended-run contract in the exit-code list
  above: `0` is `dry-run` or `applied`; `EXIT_HELD` (10) is `idle`,
  `disabled`, or a held `steward.lock`; `8` is `partial`; `1` is
  `refused`; `6` is `stopped` because a STOP intent blocked the run before
  it started; `64` is usage.
- There is no per-run cap on records decided — a large queue is decided
  in one run, across as many model calls as it needs; the run record
  prints calls, turns, and duration per call so an unusually long run is
  visible the morning after, never silent.
- `partial` output names both the committed results already established
  and the original record obligations still unfinished. A failed packet
  does not erase a committed prefix or prevent a later independent packet
  from being decided; a STOP or bookkeeping halt does stop every later
  packet and maintenance operation.
- The run's report names its coverage across the nine case outcomes
  (route, reject, defer, retire, replaced, rehome, revise, no-action,
  parked — the outcome set in `02-schema.md` §3a) crossed with the three
  scopes (user, project, skill) and says plainly which of those
  twenty-seven cells had nothing in them this run — an empty cell is
  stated, never left for you to notice by its absence. A case decided
  after being parked counts under its deciding outcome; the overseer's
  consolidations of user-model entries are reported on their own line,
  not as a case outcome.

A steward run never asks you anything mid-run; read its cases afterward
(§ Cases, above) the same way you would read anyone else's.

## Session end

1. If the session's decision sheet still has unapplied items, apply it
   now: `self-learn batch <sheet.yaml>` (one locked run — never a
   hand-written sequence of individual verb calls). Read its exit code
   per the table above; on **8** or **1**, show the refused items' own
   reasons from the `--json` envelope.
2. `self-learn sentinel release`.
3. Summary: resolved (routed/rejected/retired), deferred, and what
   remains pending beyond this batch.
4. If `batch` (or any verb) reported a failed push ("PUSH FAILED —
   commit kept", exit **3**), run `self-learn push` once and show its
   result. If it still fails, say so loudly — the commits are safe
   locally.
