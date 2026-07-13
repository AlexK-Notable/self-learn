---
description: Capture a durable lesson from this session into the self-learn ledger (human-confirmed, one record per lesson).
argument-hint: [what to capture, e.g. "the .storage gotcha" | --skill <name> | --project | --user]
---

Capture a lesson from the **current conversation** into the self-learn
ledger. You watched the failure happen — you hold the transcript, the
error, and the session id — so *you* compose the record; the CLI is only
the substrate you call. You compose and confirm; the `self-learn` CLI
scans, writes, and (only if explicitly asked) routes. Nothing here edits
canon, records, or git directly.

$ARGUMENTS may name the lesson to capture, or a scope flag to pass
through. If it is empty, find the lesson yourself in step 1.

## 1. Identify the durable lesson

Scan the recent conversation for the thing worth keeping: a **correction**
the user made to your behavior, a **standing preference** they stated, or
a **gotcha** that will recur. Durable means it changes how future sessions
should work — a one-off task instruction is not a lesson; say so and stop
rather than capture noise.

**One lesson per record.** If the conversation holds two distinct lessons,
compose two records and make two CLI calls — never cram them into one.

## 2. Compose the record, in the record's own voice

Write for the future session that will load this, not as meta-commentary
about this conversation ("Stop the HA container first", not "the user said
to stop the container").

- **Type** — `behavior` (a rule about doing) or `knowledge` (a fact).
  - behavior → compose **Trigger** (the firing condition, written so a
    model recognizes the moment: concrete paths, commands, situations) +
    **Instruction** (what to do, carrying the *why*). Pick `--kind`:
    `anti-pattern` (a mistake to prevent), `surface-rule` (a rule about a
    specific surface — the default), or `reasoning-pattern`.
  - knowledge → compose **Fact** + optional **Context**.
- **Scope** — `--skill <name>` if the lesson belongs to a skill that was
  active or under discussion; `--project` for this repo; `--user` only
  for genuinely universal conduct. Prefer the narrowest scope that still
  fires. Honor a scope given in $ARGUMENTS.
- **Evidence** — the best *short* quote from the transcript that proves
  the sighting (the shortest span that does — never a transcript dump,
  never anything that could contain a secret), plus the current session
  id. Pass them as `--quote` + `--session` (they go together; if you do
  not know the session id, omit both and fold the evidence into the
  Instruction/Context text instead).
- **Supersession** — if this lesson *corrects* an already-routed record
  you know of, add `--supersedes <lrn-id>`.

## 3. Echo and confirm — never silently capture

Show the user exactly what you are about to store — type, kind, scope,
Trigger/Instruction (or Fact/Context), evidence quote — and ask for
confirmation. Explicit, human-confirmed capture is a hard rule: if the
user does not confirm (or corrects the composition), revise or drop it.
Capture nothing they haven't seen.

## 4. Call the CLI with structured flags

One confirmed lesson = one call:

```bash
self-learn teach --skill home-assistant \
  --type behavior --kind anti-pattern \
  --trigger "About to edit a .storage/*.json file while Home Assistant is running" \
  --instruction "Stop the HA container first — HA caches .storage in memory and rewrites it on shutdown, so a live edit is silently clobbered" \
  --quote "never edit .storage while HA is running" --session <session-id>
```

(knowledge records: `--fact` / `--context` instead of
`--trigger` / `--instruction`; no `--kind`.)

The record lands in `pending/` for later review — that is the default and
usually the right end state. **Offer `--route --dest <target>` in the same
motion only when the destination is obvious** (e.g. the user explicitly
said "add that to the skill" → `--route --dest skill-md`). `--route`
applies and commits immediately with no confirmation prompt — the
invocation *is* the approval, so only add it when the user's words already
approved the destination. `--dest` takes `skill-md | claude-md |
reference[:<file>]`. When in doubt, let it land pending.

## 5. Read the exit honestly

- **0** — created (or routed). Report the record id line the CLI printed.
- **2** — usage/validation error; nothing was written. Fix the flags and retry.
- **3** — the secret scan refused: something in the composed text (usually
  the quote) looks like a credential. Tell the user which span tripped it
  (the CLI printed span + rule), then either **shorten/rephrase the quote**
  and retry, or re-run with `--redact` to store it with the span replaced.
  There is no bypass flag — that is deliberate.
- **4** — (only with `--route` and no `--dest`) the one-shot analyst
  failed; the record was **safely captured to pending/** as a normal
  teach. Nothing is lost — say so.

Do not go beyond the capture: no editing of SKILL.md/CLAUDE.md, no git
commands, no routing decisions of your own. Routing belongs to
`/self-learn:review` and the CLI verbs.
