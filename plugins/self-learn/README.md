# self-learn — plugin README

Git-backed lesson ledger: capture durable session lessons, triage them in
bounded review sessions, route them into canon by explicit human verbs.
The loaded surface is `skills/self-learn/SKILL.md` (kept tight — E-6);
this README holds install detail, the offer-line setup, environment, and
troubleshooting. Design corpus: `docs/specs/self-learn/`.

## Install

From the repo root:

```bash
./install.sh
```

Idempotent; what it deploys for this plugin (live symlinks — edits in the
repo are live next session, never `claude plugin install` on this machine):

| Runtime path | → repo source | Purpose |
|---|---|---|
| `~/.claude/skills/self-learn` | `plugins/self-learn/skills/self-learn/` | native skill activation |
| `~/.claude/commands/self-learn` | `plugins/self-learn/commands/` | `/self-learn:teach`, `/self-learn:review` |
| `~/bin/self-learn` | `plugins/self-learn/scripts/self-learn` | the CLI (uv wrapper over `cli/`) |

`install.sh` also runs `uv sync` for `plugins/self-learn/cli/`. Verify the
install with:

```bash
self-learn --selftest
```

## The offer line (S-15) — a documented install step

The capture loop starts with Claude *offering* to record a lesson. That
behavior comes from one paragraph in `~/.claude/CLAUDE.md` — which is
**chezmoi-managed**: edit it through chezmoi (see the `chezmoi` skill),
never the target file directly, or the next `chezmoi apply` reverts it.

```bash
chezmoi edit ~/.claude/CLAUDE.md   # add the paragraph below, then:
chezmoi apply
cd $(chezmoi source-path) && git add -A && git commit -m "add self-learn offer line" && git push
```

Paste this text exactly (load-bearing spec — 08 §1; revocable by deleting
the paragraph):

```
When I correct a mistake you made, or state a rule/preference that should change how you work beyond this task, offer once and briefly to capture it (`self-learn teach`). Offer only for durable lessons — corrections of wrong behavior, standing preferences, gotchas that will recur — never for one-off task instructions. Several serious corrections in one session each deserve an offer.
```

## M2 note — SessionStart hook (not yet)

M1 has no worker and no hooks. When M2 lands, its SessionStart staleness
check will need **manual registration in `~/.claude/settings.json`**
(install.sh symlinks hook scripts but never edits settings.json — it is
load-bearing and stays manual, per the repo's per-plugin-hooks convention).

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `SELF_LEARN_HOME` | `~/repos/claude-skills` | ledger repo root; all buckets resolve under it |
| `SELF_LEARN_ANALYST_MODEL` | `claude-sonnet-5` | model for the one-shot `teach --route` analyst |
| `SELF_LEARN_ANALYST_TIMEOUT` | `120` | analyst timeout, seconds |
| `SELF_LEARN_MEMORY_DIR` | `~/.claude/projects/-home-komi-repos-claude-skills/memory` | `import --memory` / `prune-memory` default dir |

## Troubleshooting

- **Secret scan refusal** (`secret scan: N hits — refusing this write`):
  rephrase/shorten the quoted material, or use `--redact` on capture
  surfaces (writes `[redacted:<rule>]` + `redacted: true`). There is
  deliberately **no bypass flag** in v1.
- **`PUSH FAILED — commit kept`** (exit 3): the resolution committed
  locally; run `self-learn push` (rebase-retry built in). A rebase
  conflict (exit 4) stops loudly — resolve by hand, never auto-resolved.
- **Stale sentinel** (`~/.cache/claude-skills/self-learn/autosync-pause`
  older than 2 h): ignorable — semantics ride the file's mtime, both sides
  ignore a stale one and either may delete it.
- **`--selftest` FAIL markers** naming a file: that target has ≥1 routed
  record but a missing/broken managed-section marker pair — restore the
  pair (or re-run `route` for a fresh target; the compiler bootstraps
  markers at EOF on first route).
- **Record edited directly** (outside CLI verbs, e.g. during a review
  Discuss tangent): finish with `self-learn proposal validate <id>` —
  exit 0 stamps the proposal, 1 = schema problem (file left intact),
  2 = secret-scan hit (redact before the card can complete).
