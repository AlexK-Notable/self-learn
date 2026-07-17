# Design brief — agentic chat panes on Bucket and Detail (feedback round 1, item 7)

**Status: DESIGN INPUT, not a spec amendment.** The change this brief
scopes touches the pane charter and the human-decision contract's
mechanism (07/09: "agent iterates, only the human routes"), so it takes
the standing treatment: this brief → dated 09 §4 amendments → blind
review of the amendments → build. Nothing here authorizes code.

## The directive (user's words, 2026-07-17 walkthrough)

A chat window on the Bucket page AND per-record. The agent must be
system-aware — "the contexts it should be ready to talk to me about
(my buckets, the lesson, routing, etc.)" — and must be able to ACT:
"shouldn't just be a chat bot. if i tell it to route to a different
bucket, for example, it should be able to do that."

## Invariant treatment — refine, don't repeal

"Only the human routes" survives intact if the pane agent can PROPOSE a
verb but never execute one. A typed instruction in chat is a valid
decision channel; the agent is the executor's *hand*, and the existing
arm/confirm spine is the consent mechanism already built for exactly
this shape:

1. The user types an instruction ("route this to hypr-doctor as a
   hook").
2. The agent calls a new charter-exposed tool (working name
   `propose_verb`) with the verb + parameters.
3. The server renders the EXISTING armed action-bar fragment — the same
   `.../action/arm` state machine every button and hotkey already goes
   through. The armed bar shows verb, record, destination, note.
4. The human confirms (Enter) or cancels (any key). Confirm runs the
   verb through the same runner, same secret-scan/refusal path, same
   interrupt-first rule.

Properties preserved by construction: server-rendered arm state (no new
client state machine), verb runner as the single mutation seam, CLI
refusals rendering verbatim, the scan path, Y-9 rendering of the armed
summary, and the audit property that every mutation is one CLI verb
invocation.

## What needs spec work (the amendment's scope)

- **(a) Charter expansion.** Which verbs are proposable
  (route/reject/defer/graduate; host-add joins per the Y-11 amendment
  of this date; merge-collapse?), and the tool mechanism: `propose_verb`
  surfaced via the charter callback — never Bash, never a second CLI
  path. The charter's deny-list for resolution verbs changes from
  "deny" to "deny execution, allow proposal" — the amendment must state
  the new denial boundary precisely.
- **(b) Bucket-level pane variant.** Context injection: the bucket's
  record list (leading texts + ids as metadata), cluster/bulk state,
  deferred set. Which record an ambiguous instruction binds to is the
  agent's clarifying-question problem, never a guess — doctrine §8
  register applies.
- **(c) System-context prompt.** The pane system prompt grows a
  surface-model section (what buckets exist, what the verbs do, what
  the user sees) so "talk to me about my buckets/routing" works without
  the agent rediscovering the system every session. Compiled like the
  doctrine (cache + mtime), never inlined per-request.
- **(d) Serialization.** Today: ONE pane, verbs serialized,
  interrupt-first at verb dispatch. The amendment must pick: does a
  bucket pane and a record pane coexist (two sessions), or does the
  bucket pane subsume record context when drilling in? Default posture:
  keep ONE live session globally (the existing armed-prompt takeover
  flow generalizes); revisit only if it feels cramped in use.
- **(e) Proposal rendering vs the pane transcript.** The armed bar
  renders in the action-bar region, not inside the transcript — the
  transcript logs that a proposal was made (pane_tool event), the bar
  carries the consent. SSE envelope may need a `pane_proposal` type.

## Explicitly out of scope for the amendment

- Agent-executed verbs with post-hoc undo (repeals the invariant).
- Auto-confirm timers, "trusted verb" lists, or any consent bypass.
- Cross-bucket batch instructions ("route everything older than 30d")
  in v1 — each proposal renders one armed bar, one confirm.

## Sizing

This is G-3's second act — charter + prompt authoring + bucket pane +
proposal plumbing + tests (T-B charter matrix grows a proposal row).
Expect a full spec→review→build cycle, not a polish batch.
