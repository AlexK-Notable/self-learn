<!-- rubric-version: 1 -->
# Mining rubric — what counts as a durable lesson in a transcript

You are reading structural digests of real work sessions. Your output is
*candidates for human review*, not canon: err toward precision. A missed
lesson costs one review cycle; a flood of noise kills the review habit,
which kills the whole system. **When in doubt, do not emit.**

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
   Mark `verified: true` with how; these are the highest-value class.
3. **Standing preference** — the user states how they want things done
   beyond this task ("always", "from now on", "I prefer", "on this
   machine we…"). One-off task instructions ("rename this file") are
   NOT preferences — the test is whether a future, unrelated session
   should behave differently.
4. **Repeated friction** — the same fact re-derived or the same minor
   failure re-hit across sessions with nobody naming it. Emit only when
   the repetition is visible in the digests you actually hold.

## Never emit

- One-off task instructions, project decisions the repo itself records,
  or anything a CLAUDE.md/SKILL.md in the digest already states.
- Secrets, tokens, keys, or anything resembling them — shorten the quote
  to exclude the span; the CLI scan will refuse the record anyway.
- Meta-lessons about the self-learn system observed in its own review or
  teach sessions (those spans are excluded upstream; if one leaks
  through, skip it).
- Emotional or interpersonal observations about the user. Lessons are
  about work, surfaces, and systems.

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
- **Confidence** = high only for corrections and verified gotchas you
  can quote directly; repeated-friction inferences are medium at best.

## Reconciliation honesty

If a candidate is the same lesson as a ledger-index record, say so in
`match` — folding evidence into an existing record is a *better* outcome
than a duplicate. Claiming no-match to get a fresh landing is the one
behavior that most damages trust in mined records.
