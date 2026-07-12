# 03 — Decision register

*Three states. **SETTLED** = decided with rationale; reopens automatically if
its stated inputs change (P10). **OPEN** = genuinely undecided; lean noted.
**V2-GATED** = designed (mostly in gen 1) but not built until an explicit,
observable trigger fires.*

## Settled

| # | Decision | Rationale (inputs) |
|---|---|---|
| S-1 | **Triage-to-canon architecture; no runtime injection layer.** Pending is inert; routed lessons live in natively-loaded surfaces. | E-1 (SessionStart injection structurally wrong), E-6 (preloading hurts), P1/P2. Reopens if Claude Code ships per-skill native memory that changes the delivery calculus (E-9). |
| S-2 | **v1 review surface = Claude Code itself** (`/self-learn:review` + AskUserQuestion cards); CLI is the portable core. | Agent-conversation-in-UI is the expensive half of a standalone app and already exists in-terminal; data layer stays UI-ready. Standalone UI = O-1. *Amended 2026-07-11:* cards are four options max — Apply/Discuss/Reject/Defer, Edit via Discuss — per AskUserQuestion's hard limit (E-16); diffs render via option `preview`; bulk ops via `multiSelect`; review works a bounded batch (default ~10), sets a TTL'd+heartbeated autosync pause sentinel, and **self-pushes its commits** (the sync's clean-tree branch never pushes — blind re-review 2026-07-12). |
| S-3 | **v1 supply = explicit `teach` + auto-memory importer + one-shot backlog importer.** No silent capture pipeline in v1.0. | E-2 (base rate), E-7 (auto-memory already captures), P3/P4. |
| S-4 | **Both lesson types flow through one pipeline**: `type: behavior \| knowledge`. | Behavior-only scoping starved gen 1 (E-2: ~90% of real lessons are knowledge); destinations differ, machinery doesn't. |
| S-5 | **Pre-analysis worker = detached `claude -p`** (home-net-capture pattern), coalesced runs, lazy clustering over the pending set. | Proven in-repo; SDK worker is a swap behind the same contract if needed. Clustering-at-analysis replaces eager corroboration infra. *Amended 2026-07-11:* proposals are sibling files (pending records untouched by analysis). *Re-amended 2026-07-12 (blind re-review):* **the worker is fully append-only — merges included.** Clustering emits `proposals/merge-*.yaml`; the human collapses clusters at review. Record mutation, the designated-host rule, and the claim marker are all removed — any machine may run the worker; `--allowedTools` write surface = new proposal files only. |
| S-6 | **Compilers: SKILL.md / CLAUDE.md managed sections, references append, new-skill scaffold (plugin-dev), hook scaffold (hookify pattern).** Diff-first, idempotent, marker-bounded. Hook target: always human-approved diff, never auto-registered. | P8, P9, repo settings.json doctrine. *Amended 2026-07-11:* draft diffs are **previews** — compilers apply records, regenerating output at apply time (staleness harmless by construction); **one commit per routed lesson** (surgical revert; the routed-and-reverted metric needs it); the user-scope compiler is chezmoi-aware (E-17); managed sections carry a mechanical overflow cap (`02-schema.md` §4). *Re-amended 2026-07-12 (blind re-review):* correction of a routed lesson = **supersede + recompile** — whole-section regeneration makes per-lesson `git revert` unsound; per-lesson commits are kept for attribution, with the record id in the commit *message* as the record→commit link (a commit's own hash can't live in a file it contains); the user-scope compiler must also **commit+push the dotfiles repo** (`chezmoi re-add` alone is same-machine-only); graduation's owning verb is `self-learn graduate <id>`. |
| S-7 | **Storage: in-repo, record-per-file, pending/→resolved/ dirs; transient state in `~/.cache`.** | E-8 (autosync storm excluded by construction), multi-machine via autosync, znote-compatible format. *Amended 2026-07-11:* `routed/` renamed `resolved/` (it also holds rejected/superseded); `proposals/` holds the full worker analysis, not just diffs; `teach` secret-scans captures (autosync publishes pending records pre-review); deferral gains `deferred_until`/`deferred_count` semantics. |
| S-8 | **Schema per `02-schema.md`** — trigger/instruction substance, kind-for-routing, sightings-set-at-collapse; counters/confidence/classification dropped. **Substance freezes at routing, not capture.** | Reopened 2026-07-11; **settled 2026-07-12 — blind-adjudicated ADOPT** (the old capture-freeze contradicted the Edit-in-Discuss flow, the cluster pass, and the evidence note; pending is inert per P1, so nothing downstream trusts pre-routing content; git versions drafts). Rider adopted with it: the secret scan runs on **every** record-body write, not just `teach`. `superseded_by ∈ {null, id, canon}` formally defined (`02` §2). |
| S-9 | **Notifications: threshold-batched nudges + staleness alarm.** Never per-item. | Notification fatigue = queue death in different clothes (E-3). |
| S-10 | **Immediate path always exists**: `teach --route` captures, analyzes, applies, and commits in one motion. | P3 — the system is useful with the inbox permanently ignored. |
| S-11 | **Language: Python core + bash shims; name: `self-learn`.** | Matches ha-note/cron-claude precedent (carried from gen 1 A4, unchallenged in every review). |
| S-12 | **Append-only substance from routing onward + supersede; git is history/blame.** | Carried from gen 1 / ha-note. Reopened 2026-07-11; **settled 2026-07-12 with S-8** (freeze-at-routing). Supersede-and-recompile is the only correction path for *routed* records — per-lesson `git revert` is explicitly NOT a correction mechanism against regenerating sections (blind re-review 2026-07-12). |

## Open

| # | Question | Lean |
|---|---|---|
| O-1 | **Standalone graphical UI — when?** | Build only after ≥1 month of real `/self-learn:review` use, and only if the in-terminal flow proves insufficient (clunky triage, browsing needs, analytics wants). The record-per-file layout is the API a UI would read; no migration either way. |
| O-2 | **Auto-memory importer in v1.0 or v1.1?** | v1.0 — it's the largest existing supply and cheap (read a directory, copy records). Downgrade to v1.1 only if the memory-dir format proves unstable. Dedupe by `evidence.origin` across all records in all statuses (rejects must not resurrect). Open extension: sweep *other* projects' memory dirs for skill-/user-scoped entries (project-scoped-elsewhere stays out until G-2 — see the v1 territory statement, `01-architecture.md` §2). |
| O-3 | **SessionEnd candidate appender — ship at all?** | v1.1 at the earliest, precision-tuned, and only if a month of teach+import volume shows real lessons are still escaping. Never load-bearing (E-11). |
| O-4 | **`/teach` slash wrapper in v1.0?** | Yes — and more than a thin forwarder: it is the **primary capture UX**. In-session Claude (holding the transcript that contains the failure) composes trigger/instruction/evidence and calls the CLI with structured flags; the CLI's small-model well-forming is the bare-terminal fallback only. The CLI path remains the contract. |
| O-5 | **Prune-on-route for imported auto-memory entries?** | Yes with confirmation — and extended to **prune-on-reject**: a rejected imported entry otherwise sits in MEMORY.md eating the cap (E-7) forever. Both visible, never silent. |
| O-6 | **Model-prompted teach offers — ship in v1.0?** | Lean yes: a one-line standing instruction ("when the user corrects a mistake or states a durable preference while a skill is active, *offer* `self-learn teach`"). Still explicit, human-confirmed capture — S-3's rationale intact — and the only automatic supply the **skill** scope has (auto-memory feeds project/user only). Revocable in one line if it over-offers. |
| O-7 | **ha-note's fate after the backlog import?** | The GOTCHAS journal keeps growing via ha-note post-import — two capture channels for one skill, one invisible to triage. Lean: once M1 proves the path, ha-note becomes a thin alias for `teach --skill home-assistant --route` (destination: reference append); until then it keeps working and the backlog importer stays honestly one-shot. |

## V2-gated (designed, not built — triggers are observable facts)

| # | Capability | Gen-1 spec to reuse | Activation trigger |
|---|---|---|---|
| G-1 | Statistical layer: corroboration counts, reputation/outcome signals, decay clocks, quarantine machine | decisions doc §0c/§C8/§E2.2 (archived); **evaluate microsoft/SkillOpt-Sleep first** — transcript-harvest → replay-gated skill edits, Claude Code backend, shipping since 2026-07 (SOTA survey) — before building anything bespoke | A second regular human user, **or** a measured recurrence (same lesson captured ≥2× after routing), **or** >50 active routed lessons in one host |
| G-2 | Portability: manifest + capability probe + adapter tiers | archived A1/A3 + example TOMLs (the two-repo proof) | A second host repo with a real user wanting self-learn |
| G-3 | Standalone UI (web/TUI) | — (O-1 graduates here if its gate fires) | O-1's condition |
| G-4 | Forensic analysis layer (flag-and-store scorer → LLM drain) | archived §C2 | G-1 active **and** transcript volume worth mining |
| G-5 | znote store backend (vector dedup, DB queries) | archived B2 | Lesson volume where lexical clustering visibly misses merges |
| G-6 | Staleness revalidation: compiler/`--selftest` checks each routed lesson's referenced target (file, path, device, behavior) still exists, flagging stale canon for supersession | Copilot Memory's citation-revalidation + expiry pattern (E-21) — gate-the-read as a *complement* to our gate-the-write, not a replacement | First routed lesson observed stale in live canon, **or** a shared-repo deployment (`06-horizon.md` Stage 2 — team velocity makes canon rot faster than one person notices) |

*Horizon note (2026-07-12):* the planning horizon is **team scale** — a
shared artifact repo with ~5–6 regular users (`06-horizon.md`). That makes
G-1 and G-2 *destinations with unfired triggers*, not speculative options.
The triggers themselves are unchanged: the horizon informs design headroom,
it does not pre-fire gates.

## The register's own rule

When any settled decision's stated inputs change — a platform feature ships,
a gate fires, a review lands — the decision reopens *in this file* with a
dated note. Nothing in this corpus is shielded by its status; that failure
mode has a name now (E-4) and this table is where we watch for it.
