# 07 — Review UI: the resident TUI (recorded vision)

*User-specified direction, 2026-07-12. This is the **destination surface**
for adjudication — recorded now so that v1 (the `/self-learn:review`
scaffolding) is built as a skin over substrate the TUI will reuse, never as
the place where mechanics live. Gated at G-3; prerequisite is M2 (worker
proposals are this UI's fuel). O-1 and S-2 point here.*

## 1. The interaction model: attend-at-convenience

The operating intuition: **participation scales with the user's control
over *when* they adjudicate.** Two failure modes bracket the design, and
both are rejected:

- **The popup treadmill** — modal, per-item, respond-now notifications the
  user *must* clear. Notification fatigue is queue death in different
  clothes (S-9's original rationale).
- **The invisible backlog** — a queue with no ambient presence, remembered
  only during a review ritual. That is ha-note's grave (E-3).

Between them: **a list the user can attend to whenever convenient, kept
ambiently visible by informative — never demanding — notifications.** Each
notification carries the new event *and* the standing aggregate:

> *“An agent has proposed an update to home-assistant. 4 pending decisions
> from 1 skill and 2 projects outstanding.”*

Clicking it deep-links into the TUI at that decision. Ignoring it costs
nothing — the count rides along on the next one. Notifications fire per
**worker run**, not per record (the worker already coalesces, so bursts
arrive as “3 new proposals; 7 outstanding” — natural rate limiting with no
extra machinery).

Volume framing: this is designed for **heavy work use** — multiple
concurrent Claude Code instances per day feeding learnings from several
projects — not for E-2's casual-solo floor (~1–5/month). The measured E-2
rate is a fact about one person's light use of one repo; the interaction
model must stay pleasant when several proposals arrive per day from
different producers. Many producers, one adjudication surface.

## 2. The surfaces

- **Front page** — the bucket walk: detected projects and skills with
  accumulated learnings (pending count, oldest age, per bucket). This is a
  directory listing of the ledger (`02-schema.md` §3); no serving layer.
- **Bucket page** — pending items grouped by **proposed destination**
  (hooks · skill updates · CLAUDE.md updates · references · new-skill).
  The category is the analyst's *suggestion* (proposal.destination),
  presented as overridable, and homogeneous groups collapse into one bulk
  decision (the backlog's already-canon collapse; six popups from one
  import must not become six detail pages).
- **Detail page** — one decision, fully explained: the initial finding
  (record Trigger/Instruction + evidence quotes), the change (diff
  preview, with the preview-honesty note — compilers regenerate from the
  record at apply time), why it's suggested (proposal.rationale +
  alternates), provenance (source, sightings, teacher at team scale).
- **Actions** — **Approve / Deny / Iterate / Defer** (defer keeps its
  `deferred_until`/`deferred_count` semantics — “not now” must not mean
  “forever”), plus graduate where applicable. Any resolution may carry an
  optional **note** — the user's *why*, written once into
  `resolution_note` (`02-schema.md` §2) and echoed in the resolving
  commit. Notes are also fuel: the M2 worker's rejected-proposal digest
  reads them, so a note on a denial teaches the analyst *why* that class
  of proposal loses.

## 3. The embedded adjudication agent (the in-window pane)

“Iterate” opens an agent pane **inside the TUI** — no new Claude Code
terminal per decision. The resident window is the point: notification →
click → decide → leave it open as the standing window into the learning
system. Design rules:

- **Fresh session per adjudication, stable shared prefix.** Each Iterate
  spawns a small agent session seeded from the files (record + proposal
  + target canon excerpt). *(Amended 2026-07-12, G-3 design — 09 §4.1:
  "Agent SDK session" generalized to an engine-abstracted agent session
  — `claude -p` stream-json subprocess by default, Agent SDK as the
  specced alternative. Empirical grounding: the CLI's streaming
  and fallback capabilities were verified live —
  `research/2026-07-12-agent-sdk-verification.md`. *(Corrected
  2026-07-12: that memo's API-key-only auth note was disproven by
  empirical test — both engines ride the same credential chain,
  subscription included; `research/2026-07-12-sdk-auth-empirical-test.md`.
  The engine default stands on capability + uniformity, 09 §4.1 as
  corrected.)* The invariants in
  this bullet are engine-independent and unchanged.)* The **system
  prompt — the adjudication doctrine: routing map, repo conventions,
  what the agent may and may not do — is deliberately stable and
  shared**, byte-stable so it caches whenever the API's cache window
  allows. *(Amended 2026-07-12: the original "pays the doctrine's tokens
  once per 20–30 minute burst" overstated it — the API's default cache
  TTL is 5 minutes; caching is opportunistic economics, never a design
  dependency — 09 §4.2.)* Per-item context is appended after the cached
  prefix, never interleaved into it. (The doctrine document is
  single-sourced with the worker's analyst prompt — one routing
  doctrine; the pane's charter appendix rides beside it, 09 §4.2.)
- **The agent iterates; only the human's button routes (P1).** The pane's
  agent may edit the pending record (legal pre-routing, S-8), regenerate
  the proposal and diff, answer questions about the target canon. It holds
  no path to `route` — approval is the TUI action, which calls the CLI
  verb. Same trust geometry as the worker: proposer ≠ approver, by
  construction.
- **Outcomes land in the ledger, not in the pane.** An Iterate that
  improves a proposal writes files; the TUI re-reads them. Any concurrent
  surface (a Claude Code session running `/self-learn:review`, a teammate
  at team scale) stays coherent because the files are the only truth.

## 4. Contracts v1/M2 must honor (the don't-subvert list)

1. **The CLI owns all resolution mechanics** (S-2 note, 2026-07-12):
   `route` / `reject` / `defer` / `graduate` are CLI verbs that own
   compile+commit, sentinel set/heartbeat/release, self-push, and `--note`
   capture. `/self-learn:review` is a thin caller. If routing logic ever
   lives in the slash command's prompt, the TUI inherits nothing.
2. **`--json` on the read verbs** — the TUI parses structures, not
   human-formatted text.
3. **Notification payload carries record ids** from M2 day one — the
   deep-link contract exists before the TUI does. (Concretely: the ids
   ride the CLI's per-run event log, `08-build-plan.md` §7.1;
   `notify-send` renders only the human string — amended 2026-07-12.)
4. **The sentinel scopes to mutation windows, never window lifetime.** A
   resident TUI open all day must not hold the autosync pause all day; the
   pause wraps the apply flow (CLI-managed), and the heartbeat/TTL
   semantics are unchanged.
5. **Proposals precompute** (M2 worker) — the one-glance detail page and
   the aggregate notification line both presuppose analysis already done.
6. **`resolution_note` exists from M1** — the notes corpus and the habit
   must predate the UI that displays them.

## 5. Non-goals

- **Not a fix for review avoidance.** The capture-time immediate path
  (`teach --route`), O-6 offers, and the escalation nudges remain the
  system's floor; the TUI lowers the cost of attending the list, it does
  not make attendance optional-forever safe. Queue-health metrics
  (04-roadmap) still apply and still trigger the design conversation if
  they rot.
- **No approval bypass through the pane.** However good the embedded agent
  gets, the human gate is not delegated to it (P1; E-18).
- **Not a monitoring platform.** A status strip (worker last-run,
  staleness alarm, queue health) is in scope; dashboards, charts, and
  modeled scores are not (counted-not-modeled, 04-roadmap).
