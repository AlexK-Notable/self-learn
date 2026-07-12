# 00 — Vision: the problem, the experience, the principles

## 1. The problem, stated correctly this time

Gen 1 framed the problem as *"skills don't learn — build a learning loop."*
The evidence (see `05-evidence.md`) showed lessons **are** being learned — by
the user — and hand-folded into canon effectively. What's actually missing is
three narrower things:

1. **Capture friction.** A lesson is cheapest to record the moment it happens,
   mid-flow. Today that means breaking flow to edit a SKILL.md, so most
   lessons evaporate. (The ones that survive do so because the user runs a
   dedicated capture tool, `ha-note` — which proves the pattern and its
   limits: it captures *knowledge*, not *behavior*, and only for one skill.)
2. **No routed home.** A durable lesson belongs in exactly one of a few
   surfaces — a skill's instructions, the project's CLAUDE.md, a reference
   doc, a brand-new skill, or a deterministic hook. Choosing the surface and
   writing the edit is a small design task each time, so it gets deferred, so
   it doesn't happen. There is also no native per-skill memory in Claude Code
   to absorb this by default (evidence E-9).
3. **No curation workflow.** Learnings that *do* accumulate (native
   auto-memory, gotcha journals) pile up uncurated. Auto-memory's index is
   capped and degrades without pruning; journals accrue entries that never
   graduate. Accumulation without a drain is where the value dies —
   empirically: this repo's one promotion queue was worked exactly once
   (evidence E-3).

self-learn is the answer to those three: **frictionless capture into buckets,
agent-prepared triage, and one-tap routing into the surfaces Claude already
loads natively.** It is not a runtime injection layer, not a statistical
learning loop, and not a portability framework — gen 1 designed all three
first, and review killed each for v1 (`05-evidence.md`, E-1/E-2/E-3).

Two distinctions from gen 1 survive intact and matter everywhere:

- **Knowledge vs behavior.** A knowledge lesson is a fact ("HA caches
  `.storage` in memory"); a behavioral lesson is a rule that fires under a
  condition ("when about to edit `.storage`, stop HA first"). Both flow
  through the same pipeline; they differ in record shape and typical
  destination. Gen 1 scoped itself to behavior only, which starved it —
  roughly 90% of real accumulated lessons are knowledge. self-learn takes
  both, deliberately.
- **The trigger is the key.** A behavioral record's most important field is
  its firing condition, written so the model recognizes the moment.

## 2. The experience (the target UX)

> You use Claude Code as you always do. Lessons accumulate into skill-scoped
> and project-scoped buckets — from explicit `teach` commands, from imported
> auto-memory, from imported gotcha backlogs. Each new learning gets
> background-analyzed: a proposed destination, a rationale, and a ready draft
> diff, attached to the record before you ever see it.
>
> When enough is pending (or something has waited too long), you get a quiet
> nudge — a session-start line, a desktop notification. You open
> `/self-learn:review`. Each learning arrives as a card: the lesson, the
> proposal, the diff. You tap **Apply**, or **Discuss** (the agent that
> analyzed it knows skills, hooks, and this repo's conventions — and editing
> the lesson or its diff happens here), or **Reject**, or **Defer**. A batch
> of ten to fifteen items takes a few minutes. The session
> ends with real commits: SKILL.md sections updated, a CLAUDE.md line added,
> maybe a new hook scaffolded for you to approve.
>
> And when a lesson is important *right now*, you don't wait for triage:
> `self-learn teach "…" --route` captures and applies it in one motion.

The review surface is **Claude Code itself** in v1 — the "agents that
understand the underlying systems" are Claude with the plugin-dev, hookify,
and repo-convention skills loaded, which is both free and always current. The
data layer is designed so a standalone graphical UI can be added later without
migration; that timing is an explicit gated decision (`03-decisions.md`, O-1),
not a rejection of the dream.

## 3. The ten principles (each carries its evidence)

P1. **Nothing influences a session before a human routes it.** Pending
    learnings are inert. There is no advisory limbo, no "active but
    unapproved" state. *(Kills gen 1's entire injection-poisoning surface.)*

P2. **Delivery is native loading only.** Routed lessons live in SKILL.md
    (loads at skill activation), CLAUDE.md (loads at session start),
    reference docs (progressive disclosure), or hooks (deterministic). No
    parallel injection channel, ever. *(E-1: SessionStart injection was
    structurally wrong for skill scope; E-6: preloading measurably hurts.)*

P3. **Queues never gate value.** `teach --route` delivers with the inbox
    ignored forever. Buckets are an accumulator, not a gate. *(E-3: the
    repo's own promotion queue was worked once, then never again.)*

P4. **Agents pre-analyze; humans one-tap.** Every pending learning carries a
    proposal + draft diff before triage. Conversation is available on demand,
    never required. *(A queue of decisions survives; a queue of conversations
    dies.)*

P5. **Triage pays in commits.** Every review session ends with visible canon
    diffs applied. Inbox-zero produces `git log` entries, not a cleaned
    list. *(The reward loop ha-note's queue never had.)*

P6. **Append-only substance; mutable state out of the versioned store.**
    Lesson content is never rewritten (supersede instead); lifecycle status
    is small human-triggered metadata; nothing writes to the repo per-session.
    *(E-8: per-session counter writes would storm autosync.)*

P7. **Scale honestly.** No mechanism ships whose signal needs volume this
    deployment lacks. Statistical machinery (corroboration, reputation,
    decay, quarantine) activates only on explicit v2 gates. *(E-2: the
    measurement loop cannot close at ~1 durable behavioral lesson/month.)*

P8. **Prefer platform primitives over parallel systems.** Auto-memory is a
    supply, not a competitor; hookify's pattern is the anti-pattern compiler;
    plugin-dev scaffolds new skills; git is history, blame, and revert.

P9. **Hooks compile only through explicit human diff approval.** A hook is
    executable; no captured text becomes executable without eyes on the
    exact diff. *(The one place gen 1's source-trust caution still binds.)*

P10. **Blind review before settling; re-derive when premises change.** A
     settled decision whose inputs changed is automatically reopened.
     *(E-4: gen 1's LOCKED statuses shielded decisions from a pivot that had
     invalidated them.)*
