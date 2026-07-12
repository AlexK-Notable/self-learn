# 05 — Evidence: the facts this design stands on

*Each item is something observed, measured, or documented — not designed.
Principles and settled decisions cite these by ID. If one of these facts
changes (platform update, new measurement), the decisions citing it reopen
(P10). Full provenance: znote project `skill-self-improvement`, hub
`cbEi6v8zmbLs7L-FMpMsa`; the four gen-2 review reports summarized in znote
`fKLmvUMb-jVB_u2whGiV3` (2026-07-11: 3× Opus 4.8 blind — framing,
architecture red-team, pre-mortem — + 1× Sonnet 5 mechanics fact-check).*

## From this repo's own history (measured 2026-07-11)

- **E-2 · The base rate.** Of ~58 lessons accumulated in home-assistant's
  GOTCHAS corpus over ~5 weeks of daily expert use, only **~5–7 are
  behavioral directives**; the rest are knowledge facts. The revisions file
  contains **zero instances of a behavioral rule recurring** — the event
  gen 1's measurement loop existed to detect. Projected durable behavioral
  yield: ~1/month across all skills. Any mechanism needing corroboration≥2,
  recurrence, or reputation volume cannot reach signal at this scale.
- **E-3 · Queues die here.** ha-note's promotion queue — *lighter* than any
  approval gate, since unpromoted entries were still usable — was worked
  **exactly once** (all 18 promotions dated 2026-06-15); 10 later entries
  never promoted. Standing triage obligations get one honeymoon session.
- **E-5 · Detached workers rot.** home-network's autonomous capture agent
  left 4 trace logs in 5 weeks, twice racing itself (2026-07-04); this
  repo's CLAUDE.md documents a hook symlink that silently no-op'd for weeks
  after a migration. Background paths need loud staleness detection.
- **E-8 · Per-session repo writes storm autosync.** The inotify watcher
  commits+pushes on any tracked-file change; gen 1's per-session counter
  bumps would have produced a commit per session start and raced the
  detached workers. Mutable state belongs in `~/.cache`.

## From Claude Code's documented mechanics (fact-checked 2026-07-11)

- **E-1 · SessionStart is skill-blind.** No skill is or can be active when a
  SessionStart hook fires; skill-scoped content injected there must preload
  across all skills, and sits at maximal attention distance from its firing
  moment. (Also: hook stdout enters the conversation layer, re-generated
  per session.)
- **E-7 · Auto-memory already captures corrections.** Native, on by default,
  per git repo: Claude discretionarily saves lessons/preferences to
  `~/.claude/projects/<proj>/memory/`; `MEMORY.md` (first 200 lines / 25KB)
  auto-loads every session; deeper topic files load on demand. It is
  machine-local and unmanaged — an inbox with no drain.
- **E-9 · No native per-skill memory.** Skills have no `memory:` frontmatter;
  the only native persistent memory field is on subagents. Per-skill learned
  rules have no platform home beyond editing skill files — the gap
  self-learn fills.
- **E-11 · SessionEnd is best-effort.** 1.5s default timeout, side-effects
  only, undocumented under crash/SIGKILL/terminal-close. Nothing
  load-bearing may depend on it.
- **E-12 · Hooks cannot prompt.** No hook can present an interactive choice;
  the only path is injected text hoping the model calls AskUserQuestion, and
  imperative out-of-band text can trip prompt-injection defenses. Gen 1's
  "one-tap confirm" (C7) was unimplementable as specified.
- **E-13 · Deterministic skill-body injection exists.** SKILL.md supports
  `` !`command` `` render-time substitution — a documented way to inline a
  file into the skill body with zero model discretion. (Available primitive;
  gen 2's managed sections made it unnecessary for delivery, but it remains
  the fallback if managed sections ever prove insufficient.)
- **E-14 · Skill activation has no unified hook.** PreToolUse-on-Skill covers
  model invocation; user-typed `/name` bypasses it (UserPromptExpansion
  fires instead). Another reason delivery rides file content, not hooks.

## From the agentic-engineering evidence base (adversarially verified corpus)

- **E-6 · Preloading hurts; on-demand wins.** Selective skill loading beat
  preloading a corpus by +78% relative (SkillFlow); ≥60% of preloaded skill
  content is non-actionable "attention dilution" (SkillReducer); distractor
  content is a failure axis independent of length (Chroma). Injecting
  all-skills directive lists at session start is the losing pattern;
  loading rules with the skill they govern is the winning one.
- **E-10 · The transcript is a weak sensor, structurally.** Affect and
  re-asking are not reliably lexically detectable; flattened transcripts
  can't distinguish typed from pasted; but error→fix pairs, `interrupted`,
  and per-turn `attributionSkill` are free, reliable structural signals.
  (Banked from gen 1's transcript study — constrains any future appender.)

## From the gen-1 review trail (process facts)

- **E-4 · Sequential lock-in is real.** Gen 1's C-group volume analysis
  invalidated the premises of earlier-LOCKED decisions (B3 injection, B4
  retrieval, E2 quarantine) and the LOCKED status shielded them from
  re-derivation for two further sessions. Hence P10 and the register's
  reopen rule.
- **E-15 · Blind beats leading, 3 for 3.** The leading re-review passed work
  that the same-day blind review found BLOCKING issues in; blind reviews
  produced every material course correction this project has had. Hence
  "blind review before settling" (P10).
