**Writing a lesson**

A lesson has two readers. The first is an agent in the middle of some other task, at the moment the lesson
fires. It reads only the loaded text: the Trigger and the Instruction (or the Fact). In a CLAUDE.md file that
text is read in every session, so every word costs something every time. The second reader is whoever
maintains the lesson later: the steward, the overseer, or the user. That reader sees the whole record.

The loaded text is the core of the lesson, not its background. Write it for the first reader. Keep what
changes what the agent does at that moment: the situation it is in, what to do, and the reason that stops the
rule being misapplied. If the agent is likely to try something that does not work, saying so belongs here too
("changing paths does not help"). Of each clause, ask: would an agent at this moment act differently without
it? If not, it belongs to the second reader.

Give the second reader everything else, and as much of it as you like: the background, the story of what
happened and what was tried, your fuller reasoning. That goes under `## Context`, or in a note attached to
the lesson. How the lesson was checked goes in `verified_how`; what the mistake cost in `incident_cost`; the
versions it depends on in `env`; the quote that proves it in the evidence. None of this is ever loaded, and
none of it is lost: whoever maintains the lesson reads it.

Short is a result, not a target. There is no word limit. A lesson that is a whole procedure, a format, or
several steps of judgment may need more words; then ask whether it belongs in a skill instead of a line. Each
of Trigger, Instruction and Fact is one line: a second line is not loaded.

Make the Trigger a situation the agent can recognise from inside it: name the file, the command, the error
text, what the user says. Do not start it with "When"; the line adds that word. Keep the user's own words
exactly when they are the point, and quote them; never put your paraphrase in quote marks.

When you rewrite an existing lesson, account for every idea in the old text: still loaded, moved to Context
or a field, or dropped. A dropped idea needs a reason (wrong, out of date, or said by another lesson you name).
