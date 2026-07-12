# 03 — Decision register

*Three states. **SETTLED** = decided with rationale; reopens automatically if
its stated inputs change (P10). **OPEN** = genuinely undecided; lean noted.
**V2-GATED** = designed (mostly in gen 1) but not built until an explicit,
observable trigger fires.*

## Settled

| # | Decision | Rationale (inputs) |
|---|---|---|
| S-1 | **Triage-to-canon architecture; no runtime injection layer.** Pending is inert; routed lessons live in natively-loaded surfaces. | E-1 (SessionStart injection structurally wrong), E-6 (preloading hurts), P1/P2. Reopens if Claude Code ships per-skill native memory that changes the delivery calculus (E-9). |
| S-2 | **v1 review surface = Claude Code itself** (`/self-learn:review` + AskUserQuestion cards); CLI is the portable core. | Agent-conversation-in-UI is the expensive half of a standalone app and already exists in-terminal; data layer stays UI-ready. Standalone UI = O-1. |
| S-3 | **v1 supply = explicit `teach` + auto-memory importer + one-shot backlog importer.** No silent capture pipeline in v1.0. | E-2 (base rate), E-7 (auto-memory already captures), P3/P4. |
| S-4 | **Both lesson types flow through one pipeline**: `type: behavior \| knowledge`. | Behavior-only scoping starved gen 1 (E-2: ~90% of real lessons are knowledge); destinations differ, machinery doesn't. |
| S-5 | **Pre-analysis worker = detached `claude -p`** (home-net-capture pattern), coalesced runs, lazy clustering over the pending set. | Proven in-repo; SDK worker is a swap behind the same contract if needed. Clustering-at-analysis replaces eager corroboration infra. |
| S-6 | **Compilers: SKILL.md / CLAUDE.md managed sections, references append, new-skill scaffold (plugin-dev), hook scaffold (hookify pattern).** Diff-first, idempotent, marker-bounded. Hook target: always human-approved diff, never auto-registered. | P8, P9, repo settings.json doctrine. |
| S-7 | **Storage: in-repo, record-per-file, pending/→routed/ dirs; transient state in `~/.cache`.** | E-8 (autosync storm excluded by construction), multi-machine via autosync, znote-compatible format. |
| S-8 | **Schema per `02-schema.md`** — trigger/instruction substance, kind-for-routing, sightings-by-clustering; counters/confidence/classification dropped. | E-2; the filing mutates, the capture doesn't. |
| S-9 | **Notifications: threshold-batched nudges + staleness alarm.** Never per-item. | Notification fatigue = queue death in different clothes (E-3). |
| S-10 | **Immediate path always exists**: `teach --route` captures, analyzes, applies, and commits in one motion. | P3 — the system is useful with the inbox permanently ignored. |
| S-11 | **Language: Python core + bash shims; name: `self-learn`.** | Matches ha-note/cron-claude precedent (carried from gen 1 A4, unchallenged in every review). |
| S-12 | **Append-only substance + supersede; git is history/blame/revert.** | Carried from gen 1 / ha-note; survived all three reviews. |

## Open

| # | Question | Lean |
|---|---|---|
| O-1 | **Standalone graphical UI — when?** | Build only after ≥1 month of real `/self-learn:review` use, and only if the in-terminal flow proves insufficient (clunky triage, browsing needs, analytics wants). The record-per-file layout is the API a UI would read; no migration either way. |
| O-2 | **Auto-memory importer in v1.0 or v1.1?** | v1.0 — it's the largest existing supply and cheap (read a directory, copy records). Downgrade to v1.1 only if the memory-dir format proves unstable. |
| O-3 | **SessionEnd candidate appender — ship at all?** | v1.1 at the earliest, precision-tuned, and only if a month of teach+import volume shows real lessons are still escaping. Never load-bearing (E-11). |
| O-4 | **`/teach` slash wrapper in v1.0?** | Yes if trivial (thin arg-forwarder to the CLI); the CLI path is the contract either way. |
| O-5 | **Prune-on-route for imported auto-memory entries?** | Yes with confirmation — draining MEMORY.md is part of the value (E-7 cap), but deleting the model's own notes should be visible, not silent. |

## V2-gated (designed, not built — triggers are observable facts)

| # | Capability | Gen-1 spec to reuse | Activation trigger |
|---|---|---|---|
| G-1 | Statistical layer: corroboration counts, reputation/outcome signals, decay clocks, quarantine machine | decisions doc §0c/§C8/§E2.2 (archived) | A second regular human user, **or** a measured recurrence (same lesson captured ≥2× after routing), **or** >50 active routed lessons in one host |
| G-2 | Portability: manifest + capability probe + adapter tiers | archived A1/A3 + example TOMLs (the two-repo proof) | A second host repo with a real user wanting self-learn |
| G-3 | Standalone UI (web/TUI) | — (O-1 graduates here if its gate fires) | O-1's condition |
| G-4 | Forensic analysis layer (flag-and-store scorer → LLM drain) | archived §C2 | G-1 active **and** transcript volume worth mining |
| G-5 | znote store backend (vector dedup, DB queries) | archived B2 | Lesson volume where lexical clustering visibly misses merges |

## The register's own rule

When any settled decision's stated inputs change — a platform feature ships,
a gate fires, a review lands — the decision reopens *in this file* with a
dated note. Nothing in this corpus is shielded by its status; that failure
mode has a name now (E-4) and this table is where we watch for it.
