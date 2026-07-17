# self-learn

A capture → triage → route system for lessons learned in Claude Code
sessions. Lessons accumulate inertly in a git-backed ledger
(`~/.self-learn`), a background analyst proposes routings, and a
human-gated review compiles approved lessons into the places future
sessions actually load: SKILL.md managed sections, CLAUDE.md, reference
files, deterministic PreToolUse guard scripts, and new-skill scaffolds.

**This repo is the PRODUCT** — CLI, plugin (skill + commands + hooks),
spec corpus, and the nightly transcript-miner units. It is a tool unto
itself: nothing is committed here except work specific to its own
development. Your lessons live in your ledger; compiled output lands in
your own registered host repos (doc 13 §7.3 D1).

## Layout

```
plugins/self-learn/
  cli/                  the Python CLI (uv project; `uv run pytest -q`)
  skills/self-learn/    SKILL.md + references (routing doctrine, card registry)
  commands/             /self-learn:review, /self-learn:teach
  hooks/                self-learn-pending.sh (SessionStart pending-count line)
  scripts/self-learn    ~/bin shim (readlink -f → uv run against cli/)
docs/specs/self-learn/  the ratified spec corpus (00–13 + fixtures + reviews)
systemd/                self-learn-miner.{service,timer} (nightly mine, 03:40)
install.sh              idempotent live-symlink deploy (five surfaces + units)
```

## Install (this machine's live-symlink model)

```bash
git clone git@github.com:AlexK-Notable/self-learn.git ~/repos/self-learn
cd ~/repos/self-learn && ./install.sh
# then (manual, load-bearing): register hooks in ~/.claude/settings.json
systemctl --user enable --now self-learn-miner.timer
```

The ledger initializes on first use (`self-learn status`); register
canon targets with `self-learn host add <path> [--skills-root]`.

## Development

- Tests: `cd plugins/self-learn/cli && uv run pytest -q`
- Self-check: `self-learn --selftest`
- **No autosync on this repo** (13 §7.3 D3) — commit and push manually.
- The spec corpus in `docs/specs/self-learn/` is the authority; code
  follows it, and substantive changes land with a README revision-log
  entry there. History before 2026-07-17 was extracted from the
  claude-skills monorepo via git-filter-repo (H-6: full provenance
  preserved — `git log --follow` works across the move).
