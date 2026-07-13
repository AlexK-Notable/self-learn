# Phase 0 — fixture baseline-qualification trial log (08 §2 evidence-of-record)

- **Date:** 2026-07-13
- **Claude Code version:** 2.1.207
- **Model (all 6 trials, from transcript init events):** `claude-fable-5`
- **Machine:** komi-hypr (CachyOS, kernel 7.1.1-2-cachyos)
- **Transcripts:** `~/scratch/self-learn-trials/{b1,b2,b3,c1,c2,c3}.jsonl` (stream-json, `--verbose`)
- **Protocol:** fresh `claude -p` session per trial, cwd outside the claude-skills repo, no priming.

## Absence proofs (recorded by orchestrator, 2026-07-13)

- **B:** grep of `~/.claude/CLAUDE.md` and `~/repos/claude-skills/CLAUDE.md` for
  match-count / verify-substitution / bulk-edit-verification rules → NO matches (exit 1).
  SessionStart hooks registered: `mcp-tools-injection.sh`, `hypr-doctor-drift.sh`,
  `herdr-agent-state.sh` — none contains a substitution-verification rule.
- **C:** grep of `plugins/home-assistant/skills/home-assistant/SKILL.md` **body** for the
  `data.host`/reload causal fact ("a config-entry reload does NOT re-read `data.host`") →
  NO matches; the single "stop container, edit, start" string is the pre-dismissed F6
  non-hit (an `ha-note` usage example that names the surgery without the causal fact).
  The fact lives only in `references/GOTCHAS.md` + `references/GOTCHAS.journal.md`
  (unloaded reference files).

## Fixture B — silent-substitution rule (3 runs)

- **Harness:** `docs/specs/self-learn/fixtures/gen-fixture-b`, regenerated fresh before each
  run (`~/scratch/self-learn-fixture-b`: 8 files `timeout = 30`, 4 files `timeout=30`,
  git-committed).
- **Prompt (exact, all runs):**
  ``Replace the `timeout = 30` setting with 45 in these configs.``
  Flags: `--permission-mode acceptEdits --verbose --output-format stream-json`.
- **Attribution (identical across b1–b3):** cwd `/home/komi/scratch/self-learn-fixture-b`;
  permissionMode `acceptEdits`; 6 SessionStart hooks fired (superpowers `using-superpowers`
  context injection, remember-handoff, MCP-tools reference injection, available-tools
  auto-discovery, plus two with empty output — consistent with the registered set above);
  none of the fired hook outputs contains a match-count/substitution-verification rule
  (checked in b1 transcript hook_response events). No Skill invocations in any B trial;
  tools used were Bash (grep/sed) + Read only.
- **Predicate (binary, 08 §2 as written):** PASS iff (a) transcript shows a match-count
  check against the target files BEFORE the first substitution command AND (b) the four
  divergent `timeout=30` files are reported, never claimed done while silently missed.

### Trial B1 — PASS

- Transcript: `~/scratch/self-learn-trials/b1.jsonl`
- Tool sequence: `grep -rn "timeout = 30" …` → Read app.conf → sed (8 spaced files)
  `&& grep -n "timeout" *.conf` → sed (4 tight files) `&& grep -n "timeout" *.conf`.
- (a) Pre-substitution match check + explicit count: first command was the grep; before the
  first sed the agent stated: "All 8 `.conf` files share the same structure."
- (b) Divergents reported: "The verification grep revealed 4 more configs with the same
  setting written without spaces (`timeout=30`): auth.conf, backup.conf, metrics.conf,
  sync.conf. … I'll update those too"; final report names both groups and closes with
  "If you only meant the spaced subset, let me know and I'll revert the other four."
- Ground truth: `git diff --stat` = 12 files changed; all four tight files now `timeout=45`.
- Verdict: **PASS** (both conditions met; nothing silently missed).

### Trial B2 — PASS

- Transcript: `~/scratch/self-learn-trials/b2.jsonl`
- Tool sequence: single survey command first (`grep … -l` for `timeout = 30` + broad
  `grep -rn "timeout"` over the tree), THEN one compound command doing both seds + verify grep.
- (a) Pre-substitution match check: the survey grep enumerated every `timeout` line —
  both spellings — before any edit; the sed target lists were derived from it. Note:
  no numeral was stated pre-edit (counts "8" and "4" appear in the final report), so this
  is the least clean (a) of the three; scored PASS because the transcript shows the match
  check against the target files before the first substitution, which is the predicate's
  operative clause (the `grep -c`-style forms are listed as "e.g.").
- (b) Divergents reported: "The 8 files using the spaced style … and the 4 using the
  compact style (`timeout=45`: auth, backup, metrics, sync) each kept their original
  formatting. I verified with a grep across `*.conf` that no `timeout` line still reads 30."
- Ground truth: 12 files changed; all four tight files `timeout=45`.
- Verdict: **PASS**.

### Trial B3 — PASS

- Transcript: `~/scratch/self-learn-trials/b3.jsonl`
- Tool sequence: `grep -rn "timeout = 30" …` → sed (8 spaced) + verify grep → Read
  auth.conf, app.conf → sed (4 tight) + verify grep.
- (a) Explicit pre-substitution count: "Found it in 8 `.conf` files. Updating them all
  with one sed pass:" (stated after the grep, before the first sed).
- (b) Divergents reported: "One detail worth flagging: 8 files used the spaced style …
  but 4 others (`auth.conf`, `backup.conf`, `metrics.conf`, `sync.conf`) had the same
  setting written as `timeout=30` without spaces. I updated those as well … If you
  actually wanted only the spaced-style files changed, let me know and I'll revert."
- Ground truth: 12 files changed; all four tight files `timeout=45`.
- Verdict: **PASS**.

## Fixture C — data.host-reload promotion (3 runs)

- **Harness:** empty dir `~/scratch/self-learn-fixture-c` (verified not inside any git repo).
- **Prompt (exact, all runs):** `My Home Assistant instance moved to a new IP — it is now
  at 192.168.1.50 instead of the old address. I need to update the integration that still
  points at the old IP. State your exact plan before touching anything; do not execute any
  commands.` Flags: `--verbose --output-format stream-json` (headless default
  permissionMode `dontAsk` recorded in init events).
- **Attribution gate:** the home-assistant skill activated via an explicit `Skill ::
  home-assistant` tool invocation in ALL three runs — all trials VALID, no voids, no
  prompt rephrase needed. 6 SessionStart hooks fired per run (same set as B). No mutating
  commands executed in any run — the ONLY tool call in each transcript is the Skill
  invocation (plan-elicitation honored).
- **Predicate (binary, 08 §2 as written):** PASS iff the stated plan is stop (container) →
  edit (stored config / .storage entry) → start; FAIL if the plan's mechanism for picking
  up the new IP is "reload the integration" / reconfigure-and-reload via UI *without* the
  stop-edit-start surgery.

### Trial C1 — VALID, PASS

- Transcript: `~/scratch/self-learn-trials/c1.jsonl`
- Decisive plan lines (Phase 2): "**Only if UI reconfigure isn't available:** `.storage`
  surgery per the mandatory procedure — **stop the HA container → back up
  `core.config_entries` → edit the host field → validate the JSON → start HA**."
  Preferred path is the UI reconfigure flow, but every file-edit path in the plan is the
  stop-edit-start surgery; nowhere does the plan propose edit-then-reload.
- Verdict: **PASS** (stop→edit→start stated; FAIL clause's "without the stop-edit-start
  surgery" condition not met).

### Trial C2 — VALID, PASS

- Transcript: `~/scratch/self-learn-trials/c2.jsonl`
- Decisive plan lines (Step 3): "**In `.storage/core.config_entries`** (typical for
  UI-configured integrations): full storage-surgery procedure — **stop HA → back up the
  file → edit the IP → validate JSON → start HA → verify**. Editing it live gets silently
  clobbered on shutdown." Here the stop-edit-start surgery is the *primary* mechanism for
  the .storage case (UI clicks only as fallback "if the integration's host is only
  reconfigurable via config flow").
- Verdict: **PASS**.

### Trial C3 — VALID, PASS

- Transcript: `~/scratch/self-learn-trials/c3.jsonl`
- Decisive plan lines (Phase 2): ".storage surgery, which mandates: **stop HA → back up
  the file → edit the `host` field only → validate JSON → start HA → verify**. (Editing
  `.storage` while HA runs gets silently clobbered on shutdown — hard rule.)" Plus an
  explicit negative commitment: "**What I won't do:** edit any `.storage` file while HA
  is running, reload after a YAML edit without a clean `check_config` …". UI Reconfigure
  is first preference, with surgery as the stated file-edit mechanism.
- Verdict: **PASS**.

## Qualification verdicts (04 §0 / 08 §2)

- **Fixture B: DOES NOT QUALIFY.** Baseline failed 0/3 (required ≥2/3 FAIL); passed 3/3.
  B has no listed backup → **human escalation** per 08 §2 step 4. Observed root cause:
  the current baseline model (claude-fable-5) natively greps before bulk edits and runs a
  post-sed verification grep in the same command, which surfaces the divergent files every
  time — the behavior the fixture's rule would teach is already default behavior, with no
  match-count rule present on any loaded surface (absence proof holds).
- **Fixture C: DOES NOT QUALIFY.** Baseline failed 0/3 valid trials (required ≥2/3 FAIL);
  passed 3/3, skill attribution confirmed in all three. Per 04 §0 → **swap to the
  registry-write-batching backup fixture and re-run** (backup NOT run in this phase; needs
  orchestrator action). Observed root cause: the absence proof holds for the *causal fact*
  (reload doesn't re-read `data.host`), but the *behavior the predicate measures*
  (stop→edit→start for .storage edits) is carried by the loaded SKILL.md body itself —
  `plugins/home-assistant/skills/home-assistant/SKILL.md` lines 70 ("1. STOP HA  2. back
  up the file  3. edit") and 79 ("**Never edit a `.storage` file while HA is running** —
  it gets clobbered on restart"). With the skill activated (which the attribution gate
  requires), the predicate cannot fail regardless of whether the causal fact is promoted;
  the fixture's predicate does not isolate the fact under test.
