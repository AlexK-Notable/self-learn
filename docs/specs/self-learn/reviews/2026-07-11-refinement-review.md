# 2026-07-11 refinement review — findings → draft edits

*Mandate: enhance and refine the gen-2 corpus without changing its
fundamental goals or ambitions. Method: full-corpus read + the
agentic-engineering evidence base + two live environment checks
(`chezmoi managed`, the AskUserQuestion tool schema). Every finding below is
applied as a draft edit in the working tree — review via `git diff`. Nothing
is committed or settled.*

**Reviewer note:** this memo states expected conclusions. Per ground rule 2,
a *blind* re-review of the material items must receive the edited corpus
**without** this file.

## A — Internal contradictions / spec bugs

| # | Finding | Edit |
|---|---|---|
| A1 | `evidence` listed as immutable in the field rules, yet the cluster pass appends to it (schema example line "merged by cluster pass"; worked example merges sightings) | `02-schema.md` §2: `evidence` is append-only-growable; immutability narrowed to `created_at`/`type`/`source`/body |
| A2 | Review card specced five actions; AskUserQuestion allows 2–4 options (verified against live tool schema; "Other" is auto-added) | `01-architecture.md` §3.4 + `00-vision.md` UX: four options (Apply/Discuss/Reject/Defer), Edit via Discuss; diff via option `preview`; bulk via `multiSelect`. New **E-16**. S-2 amended |
| A3 | `deferred` had no semantics (re-presents forever = E-3 in miniature); `routed/` also holds rejected/superseded | `02-schema.md`: `deferred_until` (+30d default) + `deferred_count` (≥2 → suggest reject); `routed/` → `resolved/` everywhere. S-7 amended |
| A4 | "Applies accepted diffs" implied patch-apply; proposals go stale against actively-edited targets | `01-architecture.md` §3.4 + `02-schema.md`: draft diffs are **previews**; compilers apply records, regenerating at apply time. S-6 amended |

## B — Environment-verified gaps

| # | Finding | Edit |
|---|---|---|
| B1 | **Verified:** `~/.claude/CLAUDE.md` is chezmoi-managed → a direct write drifts and the next `chezmoi apply` clobbers the managed section | New **E-17**; compilers table note + failure-mode row (`chezmoi re-add` after write). S-6 amended |
| B2 | Autosync publishes pending records (with session quotes) to the remote seconds after capture, pre-review — the repo's own "committed secret = permanent leak" doctrine applies | Capture-time secret scan in `teach` (refuse or redact+flag); minimal-quote policy; E-8 extended; failure-mode row |
| B3 | Review sessions race the autosync watcher for the commit (Discuss pauses > debounce → generic sync commit steals the semantic one) | Pause sentinel in `~/.cache`, set by `/self-learn:review`, honored by the watcher; failure-mode row |
| B4 | flock is machine-local; cross-machine worker mutations of synced records → rebase conflicts, autosync halt | Proposals become **sibling files** (records untouched between capture and routing) + **one designated analysis host**; cluster merges host-local. S-5/S-7 amended |
| B5 | Import "new entries" undefined → rejected auto-memory entries resurrect; prune covered route but not reject | Dedupe by `evidence.origin` across all records in all statuses; O-5 extended to prune-on-reject (both confirmed, never silent) |
| B6 | "The native memory directory" ambiguous; other repos' project-scoped lessons have no v1 destination | Explicit **v1 territory** statement (`01-architecture.md` §2); O-2 notes the optional other-projects sweep |
| B7 | Worker consumes model-written + imported text with no stated permission bound; staleness alarm had no owner (E-5 class) | Worker runs restricted `--allowedTools` (write surface: proposals + merges); SessionStart hook owns the staleness check (one stat call, no new daemon); manual `settings.json` registration named in M2 |

## C — Enhancements (same goals, better plan)

| # | Finding | Edit |
|---|---|---|
| C1 | The CLI's "small model extracts trigger/instruction" discards the best extractor: the in-session Claude that watched the failure | `teach` gains structured flags; `/teach` + conversational capture is the **primary UX**; small-model fallback = bare terminal only. O-4 upgraded; moved to M1 |
| C2 | Skill scope — the system's namesake — had zero automatic supply (auto-memory feeds project/user only) | New **O-6**: model-prompted teach offers (explicit, human-confirmed, one revocable line) |
| C3 | M1's backlog triage as specced = ~58 inline-analyzed cards in one sitting, mostly re-routing facts into the file they already occupy — honeymoon burn (E-3) | Import flags already-canon knowledge → one bulk-acknowledge card; cards spent on the behavioral minority (E-2: ~5–7) + misfiles. M1 exit (b) reworded |
| C4 | Unbounded queue view is how honeymoons die | Review works bounded batches (default ~10, oldest first), reports remainder |
| C5 | Routed-and-reverted metric needs surgical revert | One commit per routed lesson. S-6 amended; metric annotated |
| C6 | "Compiler keeps sections terse" was aspirational; E-6 (attention dilution) wants mechanics; user scope is the costliest surface (loads everywhere) | Managed-section overflow cap (10 entries/~150 words) + graduation cards (`02-schema.md` §4); narrowest-surface bias in the routing doctrine |
| C7 | **Material.** Append-only-from-birth makes fixing your own 30-second-old typo a supersede ceremony and makes the card's Edit action a P6 violation | Proposed: substance freezes at **routing**; pending bodies freely editable (git versions drafts). **S-8/S-12 reopened — needs blind review before settling** |
| C8 | ha-note keeps appending to GOTCHAS after the one-shot import → supply forks invisibly | New **O-7**: lean = ha-note becomes a `teach --route` alias post-M1 |
| C9 | Single-trial acceptance A/B of a stochastic system; SessionStart hook registration unstated (dead-hook lesson) | Fixture: ≥3 fresh-session provocations (hook fixture: 1); M2 names the settings.json step |

## Materiality

- **Needs blind review before settling (ground rule 2):** C7 (amends
  S-8/S-12). B4's proposals-as-siblings lightly reshapes S-5/S-7 storage and
  could be included in the same blind pass.
- **Everything else** is clarification, hardening, or roadmap sharpening
  within existing settled decisions; the register carries dated amendment
  notes on S-2/S-5/S-6/S-7.

## Explicitly considered and not changed

- The ten principles, the six components, the triage-to-canon architecture,
  the v2 gates, and the no-code-until-ratification rule — no finding
  justified reopening any of them.
- Record id format (8-char), YAML+markdown format, znote compatibility,
  Python+bash implementation choice (S-11) — untouched.
