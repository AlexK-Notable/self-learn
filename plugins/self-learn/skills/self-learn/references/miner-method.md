<!-- method-version: 1 -->
# Session miner method

Read one session. Judge only the lines marked new. Find durable lessons,
sightings of known lessons, and rule checks for the flagged rules. Ignore
 the spine's two fixed opening lines. Candidates are for human review, not
canon: err toward precision. When in doubt, do not emit.

## Units and tools

T<k> is the person's kth typed turn. A stretch is the agent's work after
that turn and before the next one; stretch 0 precedes the first typed turn.
L<n> is a physical line in the named transcript file. The spine shows every
typed turn and short work summaries; already-mined lines are context only.
`open_stretch` pages through the work. `find_similar_lessons` finds existing
lessons. `search_subagent` opens a brief, report and matching lines only;
its L<n> belongs to that subagent file, not the main session.

Only the person's typed turns (`YOU`, role `user`) are their words.
`AGENT` means the assistant. `AGENT-WRITTEN` means another agent's text
recorded as a typed turn, including a dispatched brief or accepted suggestion;
it is neither the person nor the assistant's own reply. `RELAY`, `TOOL_RESULT`
and `SUBAGENT` are context, never the person's words. In a subagent log the
SUBAGENT prefix names the file; its inner role describes the recorded row,
not proof the person spoke to that subagent. Only the person's own response
can support a correction or standing preference credited to them.

## The four lesson shapes (emit these)

1. **Correction** — the user overrides or fixes something the assistant
   did or believed. Signals: a short user turn right after an assistant
   action ("no —", "that's wrong", "I told you", "never do X here",
   "actually…", "stop"), the assistant then changing course. The
   correction's *content* is the lesson; write the Trigger as the
   situation that was mishandled, not as "the user said no".
2. **Verified gotcha** — a failure arc that ends in a found cause:
   error(s) → attempts → the fix that worked, especially when the cause
   was non-obvious (wrong-looking-right). Signals: retry clusters, an
   ERROR result followed by an assistant turn explaining the real cause
   ("turns out", "the actual problem was", "because X silently Y").
   Give `verification` with its own line; these are the highest-value class.
3. **Standing preference** — the user states how they want things done
   beyond this task ("always", "from now on", "I prefer", "on this
   machine we…"). One-off task instructions ("rename this file") are
   NOT preferences — the test is whether a future, unrelated session
   should behave differently.
4. **Repeated friction** — the same fact re-derived or the same minor
   failure re-hit within this session with nobody naming it. Emit only when
   the repetition is visible in this session. The same lesson in an earlier
   session is a sighting found with `find_similar_lessons`.

## Never emit

- One-off task instructions, project decisions the repo itself records,
  or anything a CLAUDE.md/SKILL.md in the session already states.
- Secrets, tokens, keys, or anything resembling them — shorten the quote
  to exclude the span; the CLI scan will refuse the record anyway.
- Meta-lessons observed FROM INSIDE the system's own review or teach
  sessions (those spans are excluded upstream; if one leaks through,
  skip it) — this is about where the observation was made, not about the
  subject. A lesson learned while **developing** self-learn itself is a
  normal candidate since S-64 registered this repository as a plain-mode
  host: it lands like any other project-scope lesson, routed to
  `claude-md:local`.
- Emotional or interpersonal observations about the user. Lessons are
  about work, surfaces, and systems.
- Anything credited to the user that rests on an `AGENT-WRITTEN`, `RELAY` or
  `SUBAGENT` line. Only a `YOU` line is the user's own words; an
  `AGENT-WRITTEN` line is another agent's brief typed into the session as if
  the user typed it, and an orchestrator's shorthand or summary there is
  not how the user talks. Such lines are context: the user's own
  reaction to them is evidence, they are not.

## Composition standards (the record's voice)

- **Trigger** = a recognizable firing situation with concrete artifacts:
  paths, commands, daemon names, error strings. "About to edit
  `.storage/*.json` while HA is running", never "when working with HA".
- **Instruction** = what to do AND why, one line — the why is what stops
  the rule being cargo-culted.
- **Quote** = the shortest transcript span that proves the sighting.
- **Scope** = narrowest that still fires: `skill:<name>` when the lesson
  lives inside one skill's domain, `project` for this repo's practices,
  `user` only for genuinely universal conduct.
## Pointers and field names

A quote is a verbatim span of the one entry at its line, never text joined
with "…". Every claimed outcome or verification carries its own line or is
left out. Hedges stay hedges. Quote exactly what the spine or tool showed,
including `[redacted:…]` placeholders; the checker retains the pointer and
omits a redacted quote that cannot match the raw entry.

`verification.how` becomes `verified_how`; `incident_cost.text` becomes
`incident_cost`; `context` becomes `## Context`. Trigger, Instruction and
Fact are each one line. Put background in `context`, including for behavior
lessons. Steps carry their own lines and describe the episode in order.

## Reconciliation honesty

Before writing a lesson, call `find_similar_lessons` with its draft Trigger
and Instruction or Fact. If an existing lesson is the same lesson, return a
`sighting` of it instead. Folding evidence into an existing record is a better
outcome than a duplicate. Claiming no match to get a fresh landing damages
trust. The search follows superseded records to their live successors.

## Rule checks (a suspicion, never a verdict)

Only return checks for records shown on FLAG lines. A rule check concerns
an existing rule, not a new lesson. Record what the session actually supports:

- `suspected-compliance`: the session's own text reads as following the rule.
- `suspected-violation`: the session's own text reads as breaking it.
- `cannot-tell`: the session does not show enough; use this instead of guessing.

Never emit `complied` or `violated`. These are evidence for the steward to
weigh with the cited lines, never confirmed recurrence. Whether a suspected
violation is a real recurrence-suspect is the steward's decision.

## Subagent causes and output

For a lesson that came from a subagent, name the cause in `subagent_cause`:
`bad-brief` (the brief caused it), `left-brief` (the subagent departed from
its brief), or `unchecked-report` (the parent acted without checking the
report). Use the brief and report as evidence; do not invent a cause.

Return one JSON object matching the output schema below as the entire final
message, without fences or commentary. Empty lists are correct and common.
