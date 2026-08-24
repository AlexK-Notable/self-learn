---
description: Triage pending self-learn records in a bounded review batch — analyze, card, resolve via CLI verbs.
argument-hint: [--skill <name> to scope the batch]
---

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
  relay them verbatim — the guard is inert until both are done.
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
- **Reject** — ask one line: *why?* The note is the analyst's fuel (the
  M2 rejected-proposal digest reads it) — encourage it, never gate on it.
  Then `self-learn reject <id> --note "…"` (or without `--note` if they
  decline).
- **Defer** — `self-learn defer <id>` (default +30 days) or
  `self-learn defer <id> --until YYYY-MM-DD` if they name a date.

**Scope mismatch** — not a card option, but tell the user when you see it:
if a pending record's firing range clearly belongs to a different scope
than the bucket it's filed in (captured at user scope but really only
fires inside one skill, or vice versa), `self-learn rescope <id> --to
<scope>` (`user` or `skill:<name>`) is the repair. Say plainly that using
it **discards the current proposal and re-analyzes the record in the new
bucket** — the analyst's judgment is bucket-relative, so a carried
proposal would render a stale card reasoning from the wrong scope.

**Graduate** — when the proposal sets `already_canon: true` on a single
card, the right resolution is graduation, not routing: replace Apply with
**Graduate** (`self-learn graduate <id>`), showing
`already_canon_reason`. Never reject an already-canon record for being
redundant — the lesson won.

**Bulk-acknowledge** — a homogeneous group of already-canon records gets
**one** multiSelect card listing them, not N detail cards. Each item gets
**one human line** (the proposal's first card section in registry order —
what the episode was about, in plain words) plus where canon already covers it
(`already_canon_reason`); the record id rides along as metadata, never
as the label. Every selected record resolves via its own
`self-learn graduate <id>` call; any the user de-selects gets an
individual card in this batch.

If any route in this session printed the over-cap WARNING (managed
section at its entry/word cap), open the next batch with a graduation
card for that section's oldest entries (02 §4).

**Merge cards (M2).** Before the per-record cards, list
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
  `self-learn graduate <id>` (woven into canon) or a bare supersede —
  the user chooses, you never guess.
A plain confirmation (recurrence is real, fix comes later) is
`confirm-recurrence` without `--tolerate`.

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
  finishes.
- **7** — the record WAS written but its **commit failed**. This is the
  opposite of 6 and must never be treated as it: the record has already
  moved (e.g. pending→resolved) and a blind retry fails with 64 "record
  not found". The CLI prints the exact repair command — show it verbatim
  and say the ledger is half-written. `self-learn reconcile` fixes the
  simple cases (an uncommitted record); a half-committed rename needs the
  printed command.
- **64** — usage error (bad flag/id).

Only 3, 4 and 7 mean "the ledger changed"; 1, 5, 6 and 64 mean it did not.

Codes 6 and 7 exist separately because they used to be one code making one
claim, which was true for one of its two causes (audit 2026-07-16). If you
ever see a self-learn surface report a state it cannot know — "nothing was
written" from a layer that did not do the writing — that is the same bug
class, and it is worth a capture.

## Session end

1. `self-learn sentinel release`.
2. Summary: resolved (routed/rejected/graduated), deferred, and what
   remains pending beyond this batch.
3. If **any** verb reported a failed push ("PUSH FAILED — commit kept"),
   run `self-learn push` once and show its result. If it still fails,
   say so loudly — the commits are safe locally.
