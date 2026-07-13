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
- **Fixture C: DOES NOT QUALIFY (original).** Baseline failed 0/3 valid trials (required ≥2/3 FAIL);
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

---

# Phase 0 round 2 — replacement probes (2026-07-13)

- **Claude Code version:** 2.1.207. **Machine:** komi-hypr (CachyOS, kernel 7.1.1-2-cachyos).
- **Gate:** 04 §0 HARDENED — (1) absence proof over the PREDICATE BEHAVIOR on every
  surface loaded during the trial, (2) ≥3 fresh-session baselines with ≥2 FAIL against
  (3) a binary predicate written BEFORE the trials. Predicates below were committed to
  this file before any trial ran (file mtime precedes first transcript mtime).
- **Protocol:** fresh `claude -p` per trial, cwd in `~/scratch/probe-*` (verified: no
  CLAUDE.md at `~/CLAUDE.md`, `~/scratch/`, or any probe cwd; only `~/.claude/CLAUDE.md`
  loads). Transcripts: `~/scratch/self-learn-trials/*.jsonl` (stream-json, `--verbose`).
  Evaluation via jq/grep only.

## C-backup — registry-write-batching (home-assistant): DEAD ON ARRIVAL, no trials run

- **Candidate lesson:** `plugins/home-assistant/skills/home-assistant/references/GOTCHAS.md`
  ("New entities lag the on-disk registry (HA debounces saves)" — confirm via
  `GET /api/states/<id>`, not the disk snapshot). Confirmed present in GOTCHAS.md
  (unloaded reference) and correctly absent from the SKILL.md body *as a fact*.
- **Draft predicate (recorded for the record, never armed):** PASS iff the stated
  diagnostic plan's verification mechanism for "was the entity created?" is a live
  API/state query (`GET /api/states/<id>`, `ha-api get states/<id>`, WS equivalent);
  FAIL iff the plan treats the on-disk `.storage` registry / inventory snapshot as
  ground truth for existence (declares the entity missing/failed from the disk view alone).
- **Absence proof over the predicate BEHAVIOR: FAILS.** The attribution gate requires
  the home-assistant skill to activate, which loads the SKILL.md body — and the body
  teaches the predicate behavior verbatim:
  - line 28: "**Read the inventory for orientation**, not for ground truth"
  - line 31: "It is a **snapshot** — the user edits HA in the web UI constantly,
    and those edits are invisible until regenerated."
  - lines 44-48: "For an entity's *live* state … or to **confirm a change took**,
    query HA live via the **API** (the snapshot omits volatile state by design). …
    Prefer the **`ha-api`** helper … `ha-api get states/<id>`"
- **Verdict: DOES NOT QUALIFY (gate 1).** Same flaw class that killed original C:
  the *causal fact* (write debouncing) is absent, but the *behavior the predicate
  scores* (verify existence via live API, don't trust the disk snapshot) is carried
  by the loaded SKILL.md body. With the skill active the predicate cannot isolate
  the lesson. Per the hardened gate this is reported instead of trialed.

## B-replacement candidate B1 — hyprctl focus-vs-launch trap

- **Lesson under test:** on this host, `hyprctl dispatch focuswindow <target>` on an
  absent window prints "No such window found" to stdout and **exits 0** (empirically
  demonstrated 2026-07-13) — so branching on dispatch exit status silently never launches.
- **Absence proof (predicate behavior = detect window presence via a real query, not
  dispatch exit status): HOLDS.** grep `focuswindow|hyprctl clients` over
  `~/.claude/CLAUDE.md`, `~/repos/claude-skills/CLAUDE.md`, the entire runtime skills
  tree `~/.claude/skills/` (all activatable SKILL.md bodies incl. hypr-doctor),
  `~/.claude/hooks/*.sh`, `mcp-tools-injection.ts`, `skill-rules.json` → NO matches
  (grep exit 1 on every surface). Per-trial hook_response outputs re-checked in
  transcripts after each run.
- **Provocation (exact, all runs):** `Write a bash script called focus-or-launch that
  takes a window class and a command: if a window of that class exists on my Hyprland
  session, focus it; otherwise launch the command. Just write the script.`
  Flags: `--permission-mode acceptEdits --verbose --output-format stream-json`.
  Cwd: `~/scratch/probe-hyprctl/run{1,2,3}` (one fresh empty dir per run).
- **Predicate (binary, written before trials):** PASS iff the script's presence
  detection is a real query — `hyprctl clients` (any format) / `hyprctl clients -j`
  + jq/grep for the class — used to decide the focus-vs-launch branch. FAIL iff the
  script branches on the exit status of `hyprctl dispatch focuswindow` (e.g.
  `if hyprctl dispatch focuswindow … ; then … else launch`) or otherwise assumes
  dispatch fails/errors on an absent window (including parsing nothing and treating
  dispatch success as focus success).
