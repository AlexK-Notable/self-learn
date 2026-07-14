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

Let `HOME_REPO = ${SELF_LEARN_HOME:-~/repos/claude-skills}` throughout.

## Session start

1. `self-learn sentinel hold` — pause autosync for the batch. (The verbs
   heartbeat it on every mutation; you release it at the end.)
2. Read the routing doctrine — you will analyze with it:
   `HOME_REPO/plugins/self-learn/skills/self-learn/references/routing-doctrine.md`
   and the card-section registry beside it (`card-sections.yaml`) — the
   sections it defines are what you will write per proposal and show per
   card, in its order, under its labels. Never hardcode a section name
   this file doesn't currently make you load from there.
3. `self-learn list --json` — build the queue: `status: pending` items
   (deferred ones are already excluded), **oldest first**, at most **10
   cards this session** (respect a `--skill <name>` scope from
   $ARGUMENTS). Bounded batches are the point: a session that tries to
   drain everything is the session that kills the habit. Say up front how
   many are pending and how many this batch covers.

## Per record: analyze BEFORE presenting

For each queued record **without a fresh valid proposal** (`has_proposal`
false, or `proposal_fresh` false), perform the inline analysis the M2
worker will later take over (a pure producer swap — same file, same
schema):

1. Read the record (`pending/lrn-<id>.md` in its bucket:
   `plugins/<p>/skills/<name>/.self-learn/` for `skill:<name>` scope,
   `HOME_REPO/.self-learn/` for project/user).
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

## The card

**Layout — the card is the `card:` map, rendered for a human.** The
question text is the card sections in registry order (headline leading,
under the registry's labels where a label helps), written for a reader
returning cold after a week away. Machine metadata — record id,
destination enum, scope, diff preview — is a compact footer AFTER the
human sections, never the opener. Do not lead with `lrn-…`, do not
paste record slugs as titles, and do not let filing rationale masquerade
as decision context. The "Worth discussing" section always appears — it
is the reader's foothold for the Discuss option, and an explicit
"nothing contentious" licenses fast approval.

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

**Graduate** — when the proposal sets `already_canon: true` on a single
card, the right resolution is graduation, not routing: replace Apply with
**Graduate** (`self-learn graduate <id>`), showing
`already_canon_reason`. Never reject an already-canon record for being
redundant — the lesson won.

**Bulk-acknowledge** — a homogeneous group of already-canon records gets
**one** multiSelect card listing them (id + title + reason), not N detail
cards. Every selected record resolves via its own
`self-learn graduate <id>` call; any the user de-selects gets an
individual card in this batch.

Read each verb's output line: it reports the commit and push state. A
non-zero exit means the verb refused (secret scan, dirty target, unknown
id) — show the user the CLI's message verbatim and handle it on the card;
never work around a refusal with direct file or git operations.

## Session end

1. `self-learn sentinel release`.
2. Summary: resolved (routed/rejected/graduated), deferred, and what
   remains pending beyond this batch.
3. If **any** verb reported a failed push ("PUSH FAILED — commit kept"),
   run `self-learn push` once and show its result. If it still fails,
   say so loudly — the commits are safe locally.
