---
description: Open the overseer's latest report and its interpretation questions, and record your replies.
argument-hint: (no arguments — always opens the latest report)
---

Open the **overseer's** latest weekly report and, where it raises a
genuinely material interpretation question, talk it through. You are a
**thin caller**: every write is a `self-learn` CLI verb (`overseer open`,
`overseer respond`) — you never edit the ledger, a case, or the user
model yourself, and you never paraphrase what the user says back into
the statement store.

This is not a review session. Nothing here approves a lesson, a route, or
a hook — those are decisions the overseer already made; its own report
separately states what its runner actually did with each one, including
anything refused, partially applied, or not attempted. A receipt records
an attempt and its result — its existence alone is never proof that the
change landed. This conversation is about how the system is reading the
user, never about clearing a queue.

## 1. Get the report

Run `self-learn overseer report`. This is the full document; its text is
always available on request, one command away — print it in full
whenever the user asks to see everything. The conversation itself does
not open with this: what actually reaches the user is the Questions
section alone (step 2), never a recitation of the whole document.

## 2. Open it (displays the questions, records exactly that)

Run `self-learn overseer open`. It prints the report's `Questions for
you` section and, when the committed machine index contains a proposition
the prose omitted, a fallback line naming that proposition and its cases.
Relay the output to the user verbatim, and nothing else from the report
unless they ask. That display is what this step records as a
**presentation** — its `covering` value says whether the decision, its
dependencies, or all of it was shown. It never records a presentation
for a case a question merely cites as supporting evidence, or for
anything from the rest of the report this step did not print; a case id
appearing inside a question is not the same as that case being shown,
and nothing about the report's other sections clears `provisional`. This
step does not ask the user anything yet — "shown" is the only thing it
ever means (never assent).

## 3. Discuss what is actually material, not a checklist

If the command output has no indexed proposition — the machine index is
empty and the report block says "none" — stop here and say so plainly.
When the prose says "none" but the command prints indexed fallback lines,
those lines are the questions: do not discard them because the report and
its committed index disagreed.

Do not walk through every listed question as a compulsory drill. Discuss at
most the first three materially significant questions this week — new evidence that
changed the picture, a reading that would visibly change a future
decision, or something the user would clearly want to weigh in on — and
discuss those. A minor or routine reading is already carried by the
questions you just relayed; it does not need a separate conversational
turn.

For each question you do raise, cover these parts, in your own words but
never skipping one:

1. **What this reading actually is, and its real presentation history.**
   Say what is actually true — do not open with a fixed line. A reading
   never before shown is PROVISIONAL, and you say so plainly; a reading
   shown before and left unanswered, say that and the date; a reading
   shown before with a recorded answer that is now being asked again
   because something changed, say what changed. In every case: held
   since `<date>` because `<…>`; conditions `<…>`. You may discuss the
   *scope* of the user's own earlier words, or of a system reading
   already shown, when a genuine uncertainty about it would change
   future behavior — but never re-ask the user to endorse their own
   words again, and never relabel their words as a system reading.
   Presenting a reading as PROVISIONAL fires only for a system reading
   not yet shown.
2. **The evidence**: the dated statements it rests on, quoted verbatim
   with their scope, and the cases it has affected (ids and a one-line
   outcome each).
3. **What a "yes, look again" actually does**: name the cases that would
   be sent for *reconsideration* — never "undone" or "reversed".
   Reconsideration means the steward or overseer checks the case again
   against the corrected reading; it is not a promise that the outcome
   will change, and staging a reconsideration is not itself proof that
   anything changed — only that case's own later outcome shows that.
4. **The prompt, verbatim**: "Reply in your own words if you'd like to
   say something about this; say how far it applies (this host, this
   repo, everywhere, until `<date>`)." Do not promise that leaving it
   means nothing changes anywhere — only that nothing is recorded about
   your view. The reading itself can still change later for its own
   reasons (a condition it depends on changing, new evidence arriving);
   your silence is simply not one of those reasons.

## 4. Record the reply

Preserve the exact question or proposition that was actually displayed
alongside the answer, so what was asked and what was said stay attached
to each other — the presentation observation from step 2 already carries
the displayed text, and `overseer respond` references the same
proposition, so the two stay linked without anything extra to type. If
the user replies with an actual answer to the proposition — not a
request for clarification, not an explicit decline — call:

```
self-learn overseer respond --proposition <um-id@r> \
  --scope "<user|project:<host>>" --text "<verbatim>" \
  [--as-asked "<question as narrowed in conversation>"]
```

Store the user's words **verbatim** — never paraphrase, never tidy the
grammar, never compress "everywhere, forever" into "user scope". The
scope is exactly what they said, typed as they said it (or the closest
`user`/`project:<host>` value that matches what they said — ask them to
be specific if it is genuinely ambiguous, never guess a scope for them).

A request for explanation ("what does that mean?") is not an answer to the
proposition: explain it and store nothing. An explicit decline ("I'd rather
not say") is also not an answer; record only that disposition with
`self-learn overseer respond --proposition <um-id@r> --decline`, which stores
no statement. If the
decline also says something about future conversation ("don't ask me
this again"), that is worth keeping — record it as a statement against
that future-conversation preference, not against the proposition it was
declined on.

If the user says nothing at all, do **not** call `overseer respond` — the
presentation from step 2 already recorded that this was shown, and that
is the whole of what silence means here (never agreement, never
disagreement). The reading's own entry — its `status`, its `held_since`,
its reasons — is never changed because the user stayed silent; silence
only means no reply was recorded, nothing about the entry itself.

## 5. Close

Summarize, in one line per question actually discussed: answered (and
what was recorded) or left with no statement of the user's recorded
against it — the presentation from step 2 stands, and nothing else about
the entry changed. Do not offer to re-ask an answered question in the
same session. There is no fixed number of report cycles after which an
unanswered question stops appearing — whether it appears again is a
judgment about whether it is still material, made fresh each report,
never an automatic expiry.

## Reading the exit codes honestly

- `overseer report` — `0` printed; `1` refused because no report exists
  yet (the overseer has not had a maiden run, or has not run since) —
  say so plainly; this is not an error to work around, it is the honest
  state.
- `overseer open` / `overseer respond` — `0` displayed/recorded; `1` refused (an
  empty scope, a proposition id that does not resolve, a secret-scan
  hit on the verbatim text — show the CLI's own message, never guess at
  the reason yourself).
