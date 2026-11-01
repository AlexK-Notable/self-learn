---
description: Open the overseer's latest report and its questions, and record your replies.
argument-hint: (no arguments — always opens the latest report)
---

Open the **overseer's** latest weekly report and talk through the
questions it puts to the user. Every question is an **ask**: a decision
or fact only the user has (its id is `q-<slug>`, and it comes with its own
text and a line saying what the answer changes). Asks come in two kinds,
and `overseer open` labels each one:

- **Decided in their stead** (`done in your stead without waiting (your
  answer can change it)`): the overseer acted on its **default** in the run
  that asked, so this ask is not waiting for an answer; the user's answer,
  whenever it comes, can overturn what the default decided.
- **Needs you** (`needs you; meanwhile`): only the user can settle it — a
  change to their system outside self-learn, writing into another repo's
  history (registering a host), spending money, sudo, or a conflict between
  two things they said. It **does wait** for them: it stays open until they
  answer or the overseer's weekly check finds it no longer matters. The
  line after the label is what holds meanwhile (nothing on their system
  changed, nothing spent, nothing registered; for a conflict, the newer
  statement holds). Such an ask usually offers **options**, and one that
  carries a **plan** (the change or spend it would carry out) is decided
  only by choosing one of its options (§ "Answering an ask with options"
  below).

The overseer no longer asks the user to confirm its **readings**
of them; a reading question can appear only from an index written before
that change (its id is a user-model proposition, `um-<4 hex>@r<revision>`).
You are a
**thin caller**: every write is a `self-learn` CLI verb (`overseer open`,
`overseer respond`) — you never edit the ledger, a case, the skills
registry, or the user model yourself, and you never paraphrase what the
user says back into the statement store.

**The inbox is where these questions live.** Every ask is also an item in
self-learn's inbox, the page the tray icon opens
(`self-learn-ui-open --page /inbox`): the question in plain words, why it
needs the user, what holds meanwhile or what the default already did, the
evidence, one-click answers for its options, a reply box, and a read-only
agent to ask about it. In a terminal, `self-learn attention` lists the
same items (`--json` gives each item's `att-…` id, with the ask's `q-` id
as its `subject`) and `self-learn attention packet <item> --json` prints
one in full. This command is the in-conversation way to the same
questions, for when the user brings the overseer up in a session; point
them to the inbox when they would rather read it there. A stead ask is
not waiting on them in either place; a needs-you ask is, until they
answer it.

This is not a review session. Nothing here approves a lesson, a route, or
a hook — those are decisions the overseer (or, since S-72, the steward:
always-loaded lines under the combined test, hooks, moving a placed lesson,
a rule's own globs; since E3b both rewrite lessons' words with `replace`,
each case accounting for every idea of the old text) already made; its own report
separately states what its runner actually did with each one, including
anything refused, partially applied, or not attempted. A receipt records
an attempt and its result — its existence alone is never proof that the
change landed. This conversation is about how the system is reading the
user, never about clearing a queue.

**When a week could not finish.** A failure that is not a judgment on the
merits — the model call failed, timed out, hit the turn bound, produced
output that would not validate, a git write failed or half-landed, or a
line was refused because its target file had edits self-learn did not make
(`target-busy`) — is retried by a later run as a fresh attempt, on any day,
until the week is done; a decision refused on its merits is never retried.
*(2026-09-27)* An overloaded API, a rate limit, a server or network error
is retried once at once, inside the same attempt; a model or Claude Code
version the call cannot run with, or an authentication failure, holds the
run without counting an attempt; a login hold is the one popup, and any
other cause is an inbox item. A timed-out
phase B that had written its files is checked and what passes is applied,
and the week's next attempt reuses a phase A already made for the same
cases. One decided case the case writer refuses, or one sheet without its
case, is refused alone and named under "Refused / could not do"; the rest
of the run goes on.
Each line under "Refused / could not do" ends with its kind in brackets
(`[git]`, `[target-busy]`, `[bad-line]`, ...): the first two are the
retried kinds, and a run left with one of them stays unfinished until the
retry lands or the cap below closes it. After
`runs.attempt_cap` (default 3) failed attempts the week is closed so the
next one can start, and what the overseer could not settle arrives here as
a question in its report, carrying the real failure reason
(`03-decisions.md` S-68). Relay such a question as what it is — work the
system could not complete, a system concern in the sense of step 3, never
a decision waiting on your approval. A parked case whose reason was
`attempts-exhausted` is the same shape one level down: nothing was wrong
with the lesson, the machinery failed three times, and the overseer decides
the lesson itself with the recorded failure reason as its evidence.

## 1. Get the report

Run `self-learn overseer report`. This is the full document; its text is
always available on request, one command away — print it in full
whenever the user asks to see everything. The conversation itself does
not open with this: what actually reaches the user is the Questions
section alone (step 2), never a recitation of the whole document.

## 2. Open it (displays the questions, records exactly that)

Run `self-learn overseer open`. It prints the report's `Questions for
you` section with EVERY indexed question — there is no count limit — and,
when the committed machine index contains a proposition the prose omitted,
a fallback line naming that proposition and its cases. An ask is printed
from the index as `- <q-id>: <text>` followed by `  why: <why>` and,
for a stead ask, `  done in your stead without waiting (your answer can
change it): <default>`, or, for a needs-you ask, `  needs you; meanwhile:
<what holds until they answer>`.
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

The command shows no skills: the overseer writes, renames and retires the
skills self-learn owns on its own, and the report lists what it did (its
`[new skill]`, `[skill changed]`, `[skill renamed]` and `[skill retired]`
lines). Never present a skill to the user or ask them about one.

## 3. Discuss them in order of consequence, for as long as the user wants

If the command output has no indexed question — the machine index is
empty and the report block says "none" — stop here and say so plainly.
When the prose says "none" but the command prints indexed fallback lines,
those lines are the questions: do not discard them because the report and
its committed index disagreed.

Every question was shown in step 2. Discuss them most consequential first
(the overseer already ordered them that way; follow its order unless the
user asks otherwise), one at a time, with no fixed number: the user may
stop whenever they like, and whatever was not discussed stays shown and
unanswered — nothing more.

**For a stead ask** (`done in your stead`), relay its text as the
question, say in one sentence what the answer changes (its `why`), say
what the overseer already did in their stead (its default), and name the
cases it came from. Make it plain that this one is not waiting on them:
the default stands unless they answer otherwise. Do not restate it as a
reading of the user or ask for approval of anything; it is a decision or
fact only the user has. If they answer, record it with step 4's command
using the ask's `q-` id; the steward then re-decides the lessons the
default decided, against their words.

**For a needs-you ask** (`needs you; meanwhile`), relay its text and its
`why`, and say plainly that it **is** waiting for them: nothing has been
done, and the "meanwhile" line is what holds until they decide. Then
offer its options: `self-learn attention --json` lists them on the item
whose `subject` is the ask's `q-` id (with the overseer's recommended
one marked), and `self-learn attention packet <item> --json` adds the
recommendation's reasoning, the plan and the evidence. The inbox shows
all of this on one page, with one-click answers.

**Answering an ask with options.** An ask that carries a plan is decided
**only by choosing one of its options**; words alone are recorded and
leave it open. So when the user answers such an ask:

- In the inbox: one click on the option (the easiest route; offer it).
- From this session: put their words in a file and run
  `self-learn attention answer <att-id> --option <opt-id> --ref
  transcript:<session>#L<n> --text-file <file>` with `--note "<why>"`
  (the ref is the line they typed; the words stay theirs, recorded
  `agent` because you relayed them). An option whose effect is `approve`
  or `register` also needs their **typed yes**, proved from this
  session's transcript: ask in one plain chat message (not a clickable
  choice) that names the item's `att-…` id and the option's label, for
  example "Approve «Yes, add the binding» on att-3f9a1c0b2d4e? Type yes to
  do it.", and answer straight after they type a plain yes. An option
  marked `confirm`, and every `register` option, also needs `--confirm`
  (their typed yes is that confirmation); without it the command asks
  once more and records nothing (exit 3). Without the typed-yes proof the
  command records nothing (exit 64) and says what was missing; the inbox
  click is then the route.
- If they answered in words only and you record them with `overseer
  respond`, the words are kept and the overseer reads them, but an ask
  with a plan **stays open**: tell them so, and point them to the inbox
  to choose the option.

An ask without a plan (including a conflict ask) is answered by their
words alone, recorded with step 4's command.

**When the user objects to a skill** (unprompted: nothing here asks), do
what they said with `self-learn skill veto <name> [--rename-to <new>]`
(bans the name for ever; a live skill under it is renamed by the next
overseer run, or at once with `--rename-to`), `self-learn skill rename
<old> <new>`, or `self-learn skill retire <name>` (with lessons still in
it, this records a request the next overseer run carries out). From your
shell each runs under the user's standing grant with `--note "<why>"`.

An ask whose printed block has a line "a plain yes registers: …" asks the
user to register a repository as a canon host; one with "a plain yes does:
switch … to … mode" asks to switch a registered host's mode. Either happens
in `overseer respond` itself, for a bare yes the person typed. From your (an
agent's) shell the command finds your own session from `$CLAUDE_CODE_SESSION_ID`
(add nothing; a shell without that variable needs `--session <the session id
the person typed the yes in>`, and a `--session` naming another session is
refused). It reads that session's transcript and acts only when the LAST
thing the person typed there is a plain yes (not an AskUserQuestion click, not
an earlier yes, not words typed after it) AND your own chat message between
their previous message and that yes names the question's `q-` id, the path
and the mode, and no other registration question. So ask one registration at
a time, in plain chat, not as a clickable choice, and name all three in the
one message you ask with, for example: "Register /srv/app as a project host in
plain mode (q-app-register)? Type yes to do it." If the person asks something
back, restate the whole question before asking for the yes again. Pass the
answer to this one question straight away, before the person types anything
else. When the check fails the command records NOTHING and the question stays
open; it says what was missing. Then run the `self-learn host add …` /
`host set-mode …` line the error names yourself with `--note "<why>"`: from
an agent's shell a host command runs under the user's standing grant
(`self-learn grant list`), recorded as yours, not theirs. Then answer again
(what is already done is left as it is). Asking again the way above is the
other route; never hand the person a command to run. A yes
that carries a condition ("yes, but git mode") is not a plain yes: record it
in their words and let the overseer read it.

**Correcting a reading the user brings up themselves.** The report's User
model section lists the overseer's readings of the user and is not a
question. When the user says one of them is wrong, record their words as a
statement answering that reading, anchored to the line they typed (you
captured it, so it is recorded `agent`; the words stay theirs through the
ref, and an agent's shell may not pass `human`):
`self-learn statement add --verbatim "<their words>" --ref
transcript:<session>#L<line> --recorded-by agent --answers-kind
proposition --answers-ref <um-id>@r<revision>`. The next overseer run reads
it and acts on it.

**For a reading** (only from an index written before readings stopped being
asked), cover these parts, in your own words but never skipping
one:

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
3. **What a reply actually does**: it is recorded in the user's own
   words as a correction of the reading, and nothing is sent back when
   they reply (`overseer respond` reports `reconsidered=0`). The
   overseer reads the correction at its next run, looks at the
   decisions that list the reading, and may reconsider any that rested
   on it; name those cases as the ones it will look at, and promise no
   reconsideration — never "undone" or "reversed". A reconsideration is
   not a promise that the outcome will change; only that case's own
   later outcome shows that.
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
the user replies with an actual answer to the question — not a
request for clarification, not an explicit decline — call:

```
self-learn overseer respond --proposition <um-id@r | q-id> \
  --scope "<user|project:<host>>" --text "<verbatim>" \
  [--as-asked "<question as narrowed in conversation>"] \
  [--session <session-id>]   # only in a shell without $CLAUDE_CODE_SESSION_ID, for a host-registration yes
```

`--proposition` takes either kind's id exactly as `overseer open` printed
it. An answer to an ask is stored as a statement answering that question
(`answers.kind: question`), and the overseer reads it on its next run.

Store the user's words **verbatim** — never paraphrase, never tidy the
grammar, never compress "everywhere, forever" into "user scope". The
scope is exactly what they said, typed as they said it (or the closest
`user`/`project:<host>` value that matches what they said — ask them to
be specific if it is genuinely ambiguous, never guess a scope for them).

A request for explanation ("what does that mean?") is not an answer to the
proposition: explain it and store nothing. An explicit decline ("I'd rather
not say") is also not an answer; record only that disposition with
`self-learn overseer respond --proposition <um-id@r | q-id> --decline`, which stores
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
  yet (the overseer has not run on this ledger) —
  say so plainly; this is not an error to work around, it is the honest
  state.
- `overseer open` / `overseer respond` — `0` displayed/recorded; `1` refused (an
  empty scope, a proposition id that does not resolve, a secret-scan
  hit on the verbatim text — show the CLI's own message, never guess at
  the reason yourself).
