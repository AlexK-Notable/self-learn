# 2026-07-12 implementability review — gaps that would mislead implementation sub-agents

*Two passes, run independently after ratification: the orchestrator's own
start-to-finish read, and one independent Fable reviewer given the corpus
WITHOUT `reviews/*` and without the orchestrator's findings, mandated to find
gaps that would cause mistakes by literal-minded builders following the docs
alone (the durable-plan requirement: executable with or without a top-tier
orchestrator). The reviewer ground-truthed environment claims against the
live main repo before reporting. All dispositions are folded into the corpus
(dated edits) and into `08-build-plan.md`, which pins every interface below.
Like its siblings, this memo is withheld from future blind reviewers.*

## Environment claims verified (all true)

E-17 chezmoi management of `~/.claude/CLAUDE.md` · sync's clean-tree branch
never pushes (`bin/claude-skills-sync`) · no sentinel logic exists today ·
fixture A's premise (`.storage` rule in loaded SKILL.md body) · fixture C's
premise (`data.host` lesson only in `references/GOTCHAS.md`) · `ha-note
--promoted` exists · auto-memory dir + MEMORY.md exist · the watcher's
EXCLUDE regex does **not** exclude `.self-learn/` (records sync, as intended)
· E-16's AskUserQuestion limits re-verified against the live tool schema
2026-07-12 (4 options max; previews single-select only).

## Blockers (a doc-only builder builds the wrong thing or gets stuck)

- **G-1 packaging omission** — nowhere says where self-learn's code lives or
  how it deploys (plugin dir, marketplace entry, install.sh symlinks, slash
  command namespace). → pinned in 04-M1 + 08 §1.
- **G-2 sentinel contract unwritten** — a two-repo interface (CLI produces,
  main-repo sync consumes) with no path, format, heartbeat mechanism, TTL
  semantics, or check location; the two sides are explicitly separate
  deliverables and each side's own test would pass while the pair silently
  fails. → pinned in 02 §3 + 08 §1.
- **G-3 markerless-target behavior** — no target file has markers today, so
  the very first route hits an unspecified case; `--selftest`'s "fail loud
  when markers missing" reads as the opposite of bootstrap. → bootstrap rule
  in 02 §4.
- **G-4 `route` verb input unspecified** — M1 has no worker and "inline
  analysis" never said whether it writes proposal files; as documented the
  CLI verb can't stand alone, steering a builder into putting routing logic
  in the slash command's prompt (exactly what 07 §4-1 forbids). → M1 inline
  analysis writes the same proposal siblings; `route` always reads them,
  `--dest` overrides (01 §3.4, 04-M1).
- **G-5 already-canon flag criterion** — "flags entries whose substance
  already lives in loaded canon" naively flags 100% of a reference-doc
  import, including the behavioral minority exit criterion (b) depends on.
  → criterion pinned: `type: knowledge` AND source file is itself canon;
  behavioral entries never bulk-flagged; judgment recorded in the proposal
  sibling; wrong flag costs one de-selectable card (01 §3.2).
- **G-6 S-14 vs M3 contradiction** — S-14 ships the auto-memory importer in
  "v1.0" (with "mid-M1" fallback language) while 04 placed it in M3, titled
  "v1.1"; no version↔milestone mapping existed. → v1.0 = M1+M2, v1.1 = M3+;
  importer moved to M1 (04, S-14 note).

## Risks (plausible wrong turns, folded)

- **G-7 secret scan unspecified** (tool, refuse-vs-redact rule, no override
  semantics) → pinned in 08 §1: built-in regex set; refuse by default
  showing the span; `--redact` substitutes and flags; no bypass in v1.
- **G-8 `superseded_by` overload** — merge-collapse losers aren't
  *corrective* supersessions → corrective reading applies only to
  previously-routed records (02 §2).
- **G-9 sentinel scope drift** (01 "for its duration" vs 07 "mutation
  windows") → explicit `sentinel hold|release` subcommands; slash review
  wraps its batch, TUI wraps apply flows, verbs self-hold when bare;
  heartbeat = every mutating invocation re-touches (no daemon) (01 §3.4).
- **G-10 third autosync writer** — home-network capture prompts commit+push
  this repo directly, bypassing the sentinel. Ground truth: they `git add`
  only their own reference files, so they cannot sweep mid-review
  `.self-learn` state → accepted residual, documented (04-M1, 08 §5).
- **G-11 resolution commit conventions** — only `route`'s message format
  existed; rejections would ride anonymous autosync commits and starve the
  M2 digest → every resolution verb commits, formats pinned (02 §2); push
  failure loud, review-end retries.
- **G-12 chezmoi failure paths** → compiler checks `chezmoi diff` first;
  aborts user-scope routes on pre-existing drift or a dirty dotfiles repo;
  dotfiles push failure is loud (08 §5).
- **G-13 `teach --route` interactivity** → prints the diff, applies without
  prompting (invocation is the approval); no confirm gate (01 §3.2).
- **G-14 offer-line placement/wording** → `~/.claude/CLAUDE.md` via chezmoi,
  a documented install step; exact wording pinned in 08 §1 (the filter words
  are load-bearing spec).
- **G-15 proposal lifecycle** → resolution `git rm`s proposal siblings; the
  digest reads `resolved/` + commit messages, never proposal files (02 §3).
- **G-16 dedupe-key stability** → `evidence.origin` format pinned:
  path#anchor or path#sha256:<12> of normalized entry text; never line
  numbers (02 §2).

Nits folded: `--selftest`'s worker check marked M2-conditional (G-17); id
charset = 8 lowercase hex (G-18); `--json` shapes stubbed in 08 (G-19);
E-16 re-verified (G-20, above); exit criteria tagged [auto]/[protocol]
(G-21, 04).

## Judgment calls that cannot be spec'd away (routed in 08 §4)

Destination choice · already-canon equivalence · cluster same-lesson calls ·
O-6 significance filter · secret-scan gray zones · reject-vs-route and
graduation timing · fixture provocation authoring.

## Verdicts and process note

Reviewer verdict: *"M1 as written is not yet executable unattended by a
mid-tier agent — but it is close, and the distance is six small spec
patches, not a redesign… expect the builder to invent all six interfaces —
and the sentinel and packaging inventions in particular would be invented
differently on the two sides of the main-repo/worktree split."*

Convergence: the two passes independently found the same six blockers
(packaging, sentinel, markers, route input, already-canon, S-14/M3) and the
same core risks (scanner, commit conventions, offer placement,
`superseded_by` overload); the reviewer additionally surfaced G-10, G-12,
G-13, G-15, G-16 with ground truth the orchestrator hadn't gathered.
Independent-verification-over-trusting-the-advocate: now 7-for-7.
