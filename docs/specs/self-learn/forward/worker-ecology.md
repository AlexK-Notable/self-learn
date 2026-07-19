# Forward theme H — Worker ecology: the community and its culture

*Companion to `../14-forward-work-map.md` §2 (FW-31…FW-36). Dated
2026-07-18, from the user's direction: worker-domain boundary ruled
"(c)-ish" — pin the three-domain boundary now, build the portfolio
worker only when the digest is spec'd — plus "think about the cross
connection between these potential workers… like a community with a
culture." This doc records the ecology design and the user's feature
re-ranking of the same day. Everything here shapes future specs; it
pins nothing normative and graduates through the normal gates.*

## 1. The census (what exists today)

Four model-running workers, verified against code/units 2026-07-18:
the **analyst** (`worker kick|run` — detached, kick-triggered,
coalesced, append-only; owns routing proposals + merge clustering +
reads the rejection digest), the **miner** (nightly timer; transcript
→ candidates + episode briefs + run journal), the **pane agent**
(interactive SDK session; discusses, edits pending, proposes verbs),
and the **one-shot analyst** (inline `teach --route` mode — culturally
a mode of the analyst, same doctrine, same brief-consumption). Not
workers: UI server, SessionStart hook, notifier, watchdog (no model).

## 2. The epistemic map

Each worker occupies a distinct position in time and knowledge:

| Worker | Cadence | Uniquely knows |
|---|---|---|
| Pane agent | real-time | **why the human decides** — hears judgment articulated live |
| Analyst | minutes-after-capture | the fit of one lesson against its destination canon |
| Miner | nightly | **behavior in the wild** — the only observer of actual sessions, including how existing canon performed |
| Auditor (future) | ~monthly | **patterns across time** — the whole ledger + telemetry + journals at once |

Two structural findings:

- **The miner is the community's field reporter and currently
  discards its best observations.** Transcripts contain recurrence
  evidence, fire evidence, and contradiction sightings about *routed*
  canon; the miner reads them anyway. Field reports (telemetry
  appends: "saw lrn-X followed / violated / conflicted, span ref")
  become its co-equal second product — and they solve the receipts
  digest's fire-attribution problem for every lesson that appears in
  mined sessions (the CLAUDE.md-scope attribution gap closes to the
  extent sessions are mined).
- **The pane agent is the ethnographer and its field notes
  evaporate.** Articulated routing judgment in chat survives only as
  a resolution note. The pane drafts **doctrine amendment proposals**
  ("articulated twice — proposed doctrine note attached"), human-
  gated like everything else. This is FW-30's doctrine editing
  approached from the observation side: the system codifies how the
  user routes, through propose-and-gate.

## 3. The cadence ladder as communication architecture

Information flows **down-cadence as compression** (live reasoning →
notes/drafts; transcripts → field reports; a month of everything →
the auditor's synthesis) and **back up-cadence as compiled briefs** —
small versioned files fast workers load at activation:

- Auditor → analyst: portfolio-level routing bias ("user-claude-md at
  8/10 entries — prefer narrower when defensible"; "class-level
  rejection patterns beyond the raw digest").
- Auditor → miner: precision feedback ("these candidate classes never
  survive review"; canary recall results as a standing score-free
  count).
- Auditor → human: the receipts digest — the same synthesis,
  human-rendered.

**The economy that justifies (c)-ish**: digest and briefs are ONE
job — one monthly read over one data set with two renderings. When
the digest is spec'd (FW-33), the briefs channel specs with it. The
auditor is best positioned to inform everyone *because it is
slowest*: low frequency makes its outputs stable, cheap context
rather than churn.

## 4. The culture's constitution (rules for all channels)

1. **Workers inform proposals; only the human amends the
   constitution.** Field reports, briefs, and doctrine drafts shape
   what is *proposed*, never what lands — the rejection digest's
   trust geometry generalized. Proposer ≠ approver at community
   level.
2. **All channels are files in git.** No hidden worker-to-worker
   state; every brief/report/draft is versioned and human-auditable.
   The culture has no oral tradition.
3. **Briefs carry counts and examples, never scores.**
   Counted-not-modeled applies to what workers tell each other.
4. **Workers have attention budgets.** P2 applies to agents: briefs
   get byte caps, and the auditor's job includes pruning its own
   stale advice.

**No fifth worker emerges.** The pressure points resolve into
expanded job descriptions — miner + field reporter, pane + doctrine
drafter, auditor = historian-synthesizer (born when FW-33 builds),
analyst = the culture's primary consumer. What was missing was the
channels, not a member.

## 5. The ruled worker-domain boundary ((c)-ish, user, 2026-07-18)

- **Per-record judgment** (analyst): trigger/why lint (FW-31),
  destination-bounded contradiction check (FW-32) — ride the
  proposal pass; no new process.
- **Transcript intake** (miner): near-miss visibility (FW-34,
  mostly rendering over the existing journal), field reports
  (FW-36), canaries (enhancement inside FW-34).
- **Portfolio synthesis** (auditor): digest + briefs + one-time
  why-audit of existing canon (FW-33) — **not built until the digest
  is spec'd**; the boundary is pinned now so nothing accretes onto
  the wrong worker in the meantime.
- Review fast lane (FW-35) is not worker work — UI/CLI stakes
  tiering; lives in the ui-ux theme.

## 6. Implementation pointers (collected 2026-07-18, while context was hot)

File:line anchors for the eventual spec authors — verified against
master the day this doc was written; re-verify before building, drift
is expected:

- **FW-31/32 (analyst riders)**: the rejection-digest pattern to
  imitate is `worker.py:483 _digest()` (CLI-built, injected into the
  prompt at the `{digest}` slot ~line 602/641 — lint and contradiction
  context ride the same assembly). Destination-section text for the
  contradiction check comes via the Y-20 read-only path:
  `verbs._resolve_target(check_dirty=False)` + `compilers.
  compile_managed_text` (see `verbs.py` ~1123, `SURFACE_FILL_CAPPED_
  DESTINATIONS`) — never a second parser.
- **FW-34 (near-miss surface)**: journal machinery is `miner.py:130
  journal_path()`, `:1135 _journal()`, `:1142 read_journal(limit)`;
  the render feed is `mine status --json` (cli.py ~528) — the UI
  consumes that, per the no-server-derivation rule.
- **FW-36 field reports**: land as telemetry appends (11 §4's
  actor-scoped plane, `telemetry.py`) written by the miner run —
  compose alongside the existing journal write, never a new plane.
- **FW-36 doctrine drafts**: the pane engine is `engine/sdk.py` (tool
  schema precedent: `propose_verb`), the charter is
  `engine/charter.py`; the doctrine file both drafts target is
  `plugins/self-learn/skills/self-learn/references/
  routing-doctrine.md` — drafts are *proposals beside it*, never
  edits to it.
- **UI JS invariants (FW-17's harness, and anyone touching app.js)**:
  `static/app.js` — `clickAction():54`, `ensureRowSelected():114`,
  `ensureContentFocus():135`, the reload-defer predicate block
  ~310–383 (leg (a) `[data-verb-error]` check at :336; the settle/
  error listener list incl. `htmx:swapError` at :383).

## 7. The user's feature re-ranking (2026-07-18, recorded)

**Upranked**: receipts digest, miner near-miss visibility, review
fast lane, trigger lint, why-audit, contradiction check.
**Downranked**: challenge verb (deferred — revisit with FW-33's
annoyance-to-correction context); cold-read audit (conditionally
superseded: if trigger lint (FW-31) ships, cold-read is redundant at
entry level; revisit only if portfolio-level dead weight persists in
digests).
