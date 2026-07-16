# M3 worklist — draining the three open follow-ups (user-run)

*Prepared 2026-07-16 by the M3 build agent. The build was READ-ONLY on the
real ledger, so the drain itself — the milestone's pinned first step
(08 appendix 2026-07-14) — is packaged here as ready-to-run material
instead of executed. Every hook block below is behaviorally proven in
`cli/tests/test_route_hook.py::TestWorklistGuards` (guard denies the
incident command, allows the near-miss, 840-test suite green).*

The three open follow-ups (`self-learn report` lists them):

| Record | Bucket | Current coverage | Upgrade |
|---|---|---|---|
| `lrn-98d42215` | chezmoi | skill-md advisory | Bash guard on `chezmoi cd` |
| `lrn-6883f824` | hypr-doctor | skill-md diagnostic (prevention half lives at user scope, `lrn-d5f6b31b`) | Bash guard on `sudo npm install -g` |
| `lrn-25968266` | project claude-skills | claude-md advisory | Bash guard on uv-project copies carrying `.venv` |

## The flow (per record)

Hook routes are never one-motion: capture → proposal (compile input +
examples) → validate (CLI stamps the script) → route (human approval =
invocation; replay runs first). All §4 judgment calls — over-block
acceptance, supersede-vs-keep — are yours at step 4.

1. **Capture the successor** (fresh session or terminal):

   ```bash
   # chezmoi (escalate: the guard replaces the advisory)
   self-learn teach "guard: chezmoi cd blocks forever non-interactively" \
     --skill chezmoi --type behavior --kind anti-pattern \
     --supersedes lrn-98d42215 \
     --trigger "About to run \`chezmoi cd\` in a non-interactive shell (Claude Code Bash tool, scripts, cron)" \
     --instruction "Deny it — it spawns an interactive child shell and blocks until timeout; use git -C \"\$(chezmoi source-path)\" <cmd> instead"
   ```

   For `lrn-6883f824` the routed record is the *diagnostic* signature —
   don't supersede it. The prevention rule it defers to is the user-scope
   `lrn-d5f6b31b` (in `~/.claude/CLAUDE.md`): supersede THAT
   (`--supersedes lrn-d5f6b31b`, `--user` scope... note: hook scripts for
   user-scoped records land under `plugins/self-learn/hooks/`), then
   `self-learn followup done lrn-6883f824 --note "guard landed as lrn-<new>"`.

   For `lrn-25968266`: `--project` scope from the claude-skills repo,
   `--supersedes lrn-25968266`.

2. **Drop the matching draft proposal** beside the new record:

   ```bash
   cp chezmoi-cd.proposal.yaml \
     ~/.self-learn/skills/chezmoi/proposals/lrn-<newid>.yaml
   self-learn proposal validate lrn-<newid>   # stamps record_sha + script
   ```

   (`sudo-npm-global.proposal.yaml` → `~/.self-learn/user/proposals/` or
   `skills/hypr-doctor/proposals/` depending on the scope you captured;
   `uv-venv-copy.proposal.yaml` → the claude-skills project bucket.)

3. **Inspect** the stamped `script:` in the proposal — those exact bytes
   are what routes (verbatim, M3-2). Tune by editing the `hook:` block and
   re-running `proposal validate` (regeneration is deterministic).

4. **Route** — the verb prints the whole script, replays the examples
   (mismatch aborts), commits ledger then host, and prints the two manual
   steps:

   ```bash
   self-learn route lrn-<newid>          # proposal carries --dest hook
   ./install.sh                          # materializes ~/.claude/hooks/<name>
   # add the printed PreToolUse snippet to ~/.claude/settings.json
   ```

5. **Recompile once at the end** — a supersede-escalation to a different
   surface leaves the old advisory line in its managed section until the
   next compile: `self-learn recompile` drops them; `self-learn --selftest`
   should then be fully green (the new hooks check included).

Rollback any time: hand-remove the settings.json entry for immediate
relief; `self-learn supersede <hook-record> <replacement>` (or graduate)
for the durable retirement — it `git rm`s the script and prints the
un-registration reminder (M3-4).
