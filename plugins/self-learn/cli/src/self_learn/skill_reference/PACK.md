# Anthropic skill authoring reference

Version: `anthropic-2026-11-15`. Read: 2026-11-15.

## Scope and precedence

This pack grounds every self-learn skill draft, rewrite and reorganisation. It targets Claude Code, not API uploads. Requirements R01–R07 are checked by the template, except preserved registered names and carried keys: existing user settings win and conflicts are notes. Guidance G01–G07 is advisory. The checker uses labelled heuristics for wording, token estimates and contents lists; it does not judge meaning. The model must also read the guidance and available native examples.

The template retains additional self-learn policies (no executable files, safe paths, managed blocks, collision/veto checks and permission-bearing keys). Those are local policy, not invented Anthropic requirements. New license and compatibility fields are safe descriptive fields. Registered non-allowlisted keys, plus existing license/compatibility, remain immutable.

Sources disagree: Claude Code permits absent frontmatter; the portable format requires it. Use both fields for new skills. Ignore the older help article's 200-character description cap in favor of the documented 1,024. No upload is performed, so the API's 30 MB upload and 20-skills-per-request limits do not constrain these local writes. Bare angle brackets are a native-validator portability note; XML tags remain refused. The nested self-learn stamp is a deliberate Claude Code map, not a claim of upload portability.

## Rules

### R01 — required fields

Include a first-line YAML block with name and nonempty description.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview.md (read 2026-11-15). Short quote: “Required fields:”.

### R02 — name limits

Use 1–64 lowercase ASCII letters, digits or hyphens. Do not include anthropic or claude.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview.md (read 2026-11-15). Short quote: “Maximum 64 characters”.

### R03 — name shape

Match the folder name; no leading, trailing or doubled hyphens.

Source: https://agentskills.io/specification.md (read 2026-11-15). Short quote: “Must match the parent directory name”.

### R04 — reserved folders

Do not name a skill synced. Claude Code also reserves anthropic-skills outside plugins.

Source: https://code.claude.com/docs/en/skills.md (read 2026-11-15). Short quote: “Reserved name `synced`”.

### R05 — description limits

Use at most 1,024 characters and no XML tags in name or description.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview.md (read 2026-11-15). Short quote: “Cannot contain XML tags”.

### R06 — compatibility limit

If present, compatibility is a string of at most 500 characters.

Source: https://agentskills.io/specification.md (read 2026-11-15). Short quote: “Max 500 characters.”.

### R07 — reference depth

Link every supporting reference directly from SKILL.md with relative forward-slash paths. Avoid chains that require reading another reference to discover a file. The self-learn template additionally confines references to references/*.md.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md (read 2026-11-15). Short quote: “Keep references one level deep”.

### R08 — portability note

The portable format has six fields: name, description, license, compatibility, metadata, allowed-tools. Its metadata values are strings. Claude Code accepts more keys and free-form maps; self-learn targets Claude Code and keeps its own nested provenance map. Report portability differences as notes, not refusals.

Source: https://agentskills.io/specification.md (read 2026-11-15). Short quote: “A map from string keys to string values”.

### G01 — description guidance

Describe both the capability and when to invoke it. Name concrete user contexts and useful exclusions. Prefer third-person task wording plus Use when; do not mechanically rewrite a good description to satisfy a phrase detector.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md (read 2026-11-15). Short quote: “Be specific and include key terms”.

### G02 — length guidance

Aim below 500 lines and roughly 5,000 tokens in SKILL.md. These are targets, not rejection thresholds; split conditional detail when it helps.

Source: https://agentskills.io/specification.md (read 2026-11-15). Short quote: “Instructions (< 5000 tokens recommended)”.

### G03 — navigation guidance

Say when to read each linked reference. Add contents lists to references over 100 lines.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md (read 2026-11-15). Short quote: “include a table of contents at the top”.

### G04 — instruction guidance

Keep domain-specific corrections, procedures and concrete examples. Explain reasons; choose defaults and match rigidity to the cost of mistakes. Avoid generic explanations, volatile facts and unexplained constants.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md (read 2026-11-15). Short quote: “Only add context Claude doesn't already have.”.

### G05 — native creator guidance

Preserve the original name on an update. Keep a skill general enough for similar tasks; explain why constraints matter. Use the installed skill-creator as an example, without executing its model-based evaluation scripts during automated upkeep.

Source: https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md (read 2026-11-15). Short quote: “Preserve the original name.”.

### G06 — evaluation guidance

Before expanding a skill, identify real failures and representative tasks. Evaluate invocation separately from output quality, compare fresh sessions with and without the skill, and inspect traces. Static checks cannot establish either outcome.

Source: https://code.claude.com/docs/en/skills.md (read 2026-11-15). Short quote: “measure separately whether Claude invokes it”.

### G07 — script guidance

Bundled scripts suit repeated deterministic work; distinguish running a script from reading its source and verify dependencies. Self-learn currently writes Markdown-only skills; this reference does not authorize executable deployment.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md (read 2026-11-15). Short quote: “Prefer scripts for deterministic operations:”.

## Checker rule ids

R01: skill-md-missing, frontmatter-*, name-missing, description-empty. R02: name-not-kebab, name-too-long, name-reserved-word. R03: name-hyphens, name-dir-mismatch. R04: name-synced (anthropic-skills is also caught by name-reserved-word). R05: description-too-long, name-xml-tag, description-xml-tag. R06: compatibility-limit. R07: file-nested, reference-not-linked. R08: metadata-string-values (note). Guidance: guidance-description-trigger, guidance-description-person, guidance-angle-brackets, guidance-body-tokens, guidance-reference-contents, body-long-lines; description-long-words remains a local readability target. carried-reference-conflict is a note about preserved user settings.

## Native examples and refresh

No examples are redistributed in this package. At runtime EXAMPLES.md lists available native skill-creator and manifest-attributed Anthropic synced skills, including restricted examples only from installed local copies. Override SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT or SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT to choose roots; defaults are below SELF_LEARN_CLAUDE_DIR. Absent examples are simply omitted. Staged copies contain prose and license text only, are secret-scanned, and never execute scripts.

Read with `self-learn skill reference show`. Inspect a draft using `self-learn skill reference check NAME-OR-PATH`. `status` is offline; `status --fetch` compares all source hashes using plain HTTP and records the observation in the per-ledger XDG cache. Exit 0 means every source was unchanged; exit 1 means changed or unreachable. A missing cached observation is unknown, not proof of freshness.

To refresh, re-gather the named pages and native examples, review semantic changes and licenses, update this pack and sources.yaml using normalize()/digest(), bump VERSION and READ_DATE together with the manifest, add corresponding checker tests, and land a code/spec revision. Never have a weekly model silently replace the reference. Hash normalization is NFC Unicode plus collapsed whitespace over Markdown endpoints; no dates or substantive content are removed.
