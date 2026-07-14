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
- **Trials (3 fresh runs, cwd `~/scratch/probe-hyprctl/run{1,2,3}`, scored
  2026-07-13 against the pre-written predicate):**
  - run1: `hyprctl clients -j | jq -e 'any(.[]; .class == $c or .initialClass == $c)'`
    gates the branch → **predicate PASS** (real query).
  - run2: `hyprctl clients -j | jq -r '…address'` → focuses `address:$addr`, launches
    when empty → **predicate PASS** (real query; never consults dispatch exit status).
  - run3: same address-lookup shape as run2 → **predicate PASS**.
- **Verdict: DOES NOT QUALIFY (baseline 3/3 PASS; qualification needs ≥2/3 FAIL).**
  The frontier baseline natively queries window presence via `hyprctl clients -j`
  and never branches on `dispatch focuswindow` exit status — the trap the lesson
  warns about is one the model does not fall into unprompted. Same disqualification
  class as original B and C: the delta a fixture must prove is already baseline
  behavior. B2 (uv-monorepo) and B3 (notify-send) were queued but not yet trialed
  when the probe run ended; they remain open candidates.

---

# Phase 0 round 3 — B2/B3 qualification probes (2026-07-14)

- **Claude Code version:** 2.1.208. **Model:** claude-fable-5 (baseline + orchestrator).
  **Machine:** komi-hypr (CachyOS, kernel 7.1.1-2-cachyos, Hyprland, swaync at
  `/usr/bin/swaync`, notify-send 0.8.8, swaync config `timeout: 10`,
  `timeout-low: 5`, `timeout-critical: 0`).
- **Protocol:** 04 §0 HARDENED gate. Gate 0 = causal fact demonstrated empirically on
  this host before anything else. Gate 1 = absence proof over the PREDICATE BEHAVIOR
  on every loaded surface, greps + exit codes recorded. Trials = fresh `claude -p
  "<provocation>" --permission-mode acceptEdits`, one per dir
  `~/scratch/probe-<name>/run{1,2,3}`, scored on ARTIFACTS (files written), not
  transcript prose; no stream-json (absence re-checks done against the static hook
  files + plugin cache instead — all SessionStart-injected content sources grepped).
  Verified before trials: no `CLAUDE.md` at `~/`, `~/scratch/`, or any probe cwd.

## B2 — uv monorepo test invocation: DOES NOT QUALIFY (killed at gate 0, no trials)

- **Candidate lesson (as sketched):** "self-learn suite must run as
  `cd plugins/self-learn/cli && uv run pytest -q`; there is no root pyproject, so
  repo-root `pytest`/`uv run pytest` fails."
- **Gate-0 empirical demonstration (2026-07-14, this host):**
  - Ground truth: no `pyproject.toml` at repo root, `~/repos/`, or `~/` (checked);
    the only two live in `plugins/cron-claude/` and `plugins/self-learn/cli/`
    (each with its own `.venv`). A user-level pytest exists at `~/.local/bin/pytest`
    (Python 3.14).
  - Correct invocation: `cd plugins/self-learn/cli && uv run pytest -q` →
    **377 passed in 6.82s, exit 0**.
  - Naive repo-root `uv run pytest -q`: uv does NOT error "no project" — it silently
    falls back to the ambient environment and runs `~/.local/bin/pytest` with
    rootdir = repo root, which collects the whole monorepo and dies **loudly**:
    `Interrupted: 28 errors during collection`, exit 2 (ModuleNotFoundError for
    `cron_claude`, `self_learn`, … — every test module errors).
  - Naive bare `pytest` inside `plugins/self-learn/cli` (ambient interpreter, no
    venv): 20 collection errors, exit 2. Also loud.
  - Suspected destructive side effect DISPROVEN: repo-root pytest creates
    `.pytest_cache/` at root, which root `.gitignore` does NOT list — but pytest
    writes `.pytest_cache/.gitignore` containing `*` ("Created by pytest
    automatically"), so git never sees it (demonstrated in a scratch `git init`
    repo: `git status --porcelain` shows nothing for the cache dir;
    `git check-ignore .pytest_cache` exits 1, yet porcelain is clean). Autosync
    cannot commit it. (Housekeeping: the demonstration briefly created
    `.pytest_cache/` at the live repo root; verified git-invisible, then removed.
    Final `git status --porcelain` clean.)
- **Gate-0 verdict: no teeth.** Every naive invocation fails loudly and immediately;
  there is no misleading success and no destructive side effect. The correct
  invocation is one `ls` away (`plugins/self-learn/cli/pyproject.toml` with
  `[tool.pytest.ini_options] testpaths=["tests"]` and a `.venv` sitting next to
  it). A frontier baseline's failure mode is "explores a few seconds, then
  succeeds" — exactly the class the doctrine disqualifies: no binary predicate can
  honestly separate lesson-knowledge from ordinary exploration, so a ≥2/3 baseline
  FAIL is unreachable. Killed per doctrine without burning trials. No reshaped
  same-family candidate survives either: the only genuine hazard hypothesis
  (autosync committing root `.pytest_cache`) is empirically false (above).

## B3 — notify-send action-button hang under swaync: **QUALIFIES (3/3 baseline FAIL)**

- **Lesson under test:** on this host (swaync), `notify-send` with action buttons
  (`-A`/`--action`) and no explicit expire timeout **blocks forever** when the user
  doesn't click: swaync moves the expired popup into the notification center
  without emitting `NotificationClosed`, so the client's wait never ends. Bound the
  wait explicitly — finite `-t <ms>` (client-side cap; returns rc=0 with stderr
  "Wait timeout expired" and EMPTY action output, so branch on output, not rc),
  or `-e`/transient (swaync then closes on popup expiry), or a `timeout(1)` wrapper.
- **Gate-0 empirical demonstration (2026-07-14, live probes, cleaned up after via
  DBus `CloseNotification`):**
  - `notify-send -p -t 3000 "probe"` (no actions): returns in 34 ms, rc 0 —
    fire-and-forget is unaffected.
  - `timeout 30 notify-send -A yes=Yes -A no=No "probe"` (no `-t`): **rc 124 at
    30.005 s** — still blocked 20 s after the 10 s popup timeout; killed
    externally. THE TRAP.
  - `timeout 20 notify-send -p -t 3000 -A yes=Yes -A no=No "probe"`: returns at
    **3.011 s**, rc 0, stderr `Wait timeout expired`, stdout only the id — finite
    `-t` caps the wait client-side.
  - `timeout 25 notify-send -p -e -A yes=Yes -A no=No "probe"`: returns at
    **10.053 s** (= swaync popup timeout), rc 0 — swaync closes transient
    notifications on expiry, so the wait ends.
- **Absence proof (predicate behavior = bound the wait of an action-button
  notification), greps recorded 2026-07-14 before trials:**
  - `grep -nEi 'notify-send|swaync|libnotify|NotificationClosed|transient|expire.time|action button' ~/.claude/CLAUDE.md` → exit 1.
  - same pattern over `~/repos/claude-skills/CLAUDE.md` → exit 0, ONE hit (line 73:
    autosync "stops and `notify-send`s" on rebase conflict) — fire-and-forget
    mention, no wait/action semantics; surface additionally NOT loaded in trials
    (cwd `~/scratch/probe-notify/run{1,2,3}`).
  - `grep -RnEil '…' ~/.claude/skills/` (`-R`, because the skill dirs are symlinks —
    an earlier `-r` sweep false-negatived) → 4 hits, all non-carrying:
    cron-claude SKILL.md:45 (OnFailure notify-send alert, fire-and-forget),
    hypr-doctor SKILL.md + references/recovery-playbook.md (swaync as a systemd
    unit that double-launched), home-network SKILL.md:236,294 ("notify-send fires
    with verdict", fire-and-forget). None mentions actions, `--wait`, timeouts, or
    close semantics; none of these skills triggers on the provocation either.
  - `grep -lE 'notify-send|swaync' ~/.claude/hooks/*` → exit 1.
  - `grep -nEi 'notify-send|swaync|libnotify|notification' ~/.claude/skills/skill-rules.json` → exit 1.
  - `grep -RilE 'notify-send|swaync' ~/.claude/plugins/cache/` (source content for
    SessionStart hook injections: superpowers, remember, MCP-tools) → exit 1.
  - **Absence proof HOLDS** over the predicate behavior on every loaded surface.
- **Pre-registration:** provocation + predicate written to
  `~/scratch/probe-notify/predicate.txt` at 00:26:51 PDT, before run1's artifact
  (00:27:46), run2 (00:28:40), run3 (00:29:24) — mtimes recorded.
- **Provocation (exact, all runs):** `Write a bash script called ask-choice in this
  directory: it takes a question as $1, shows a desktop notification with Yes and
  No action buttons, and prints yes or no to stdout according to which button I
  click. Just write the script — don't run it.`
  Flags: `--permission-mode acceptEdits`. Cwd: `~/scratch/probe-notify/run{1,2,3}`.
- **Predicate (binary, artifact-scored, pre-registered verbatim):** FAIL iff the
  script's action-notification call (notify-send with `-A`/`--action`, or a raw
  D-Bus Notify carrying actions, including any dbus-monitor/gdbus wait loop for
  ActionInvoked) is unbounded on this host — i.e. ALL absent: (a) explicit FINITE
  expire timeout on that call (`-t`/`--expire-time` > 0; `-t 0` counts as absent),
  (b) transient hint (`-e`/`--transient`/equivalent `--hint`), (c) external bound
  (`timeout(1)`, background + timed kill, `read -t`, or any mechanism guaranteeing
  return without user interaction). PASS iff any of (a)/(b)/(c) present. VOID if
  the artifact uses no action-notification at all (zenity/rofi dialog).
- **Trials (scored on `run{1,2,3}/ask-choice` artifacts):**
  - run1 — **FAIL.** `choice="$(notify-send --wait --app-name=ask-choice
    --action=yes=Yes --action=no=No "$question")"` — no `-t`, no `-e`, no external
    bound. Header comment even claims "Exits 1 with no output if the notification
    is dismissed **or times out**" — a timeout return that swaync never delivers.
  - run2 — **FAIL.** `notify-send --urgency=critical --action=yes=Yes
    --action=no=No` — no `-t`/`-e`/bound, and critical urgency maps to swaync's
    `timeout-critical: 0` (popup never expires): the script *deliberately* chose
    the never-returning configuration ("keeps the notification on screen until
    acted on"). Transcript note: the model even identified swaync as the running
    daemon and still produced the unbounded call.
  - run3 — **FAIL.** `notify-send -A yes=Yes -A no=No` — no `-t`/`-e`/bound;
    comment claims return on "dismissed/expired without clicking", which does not
    happen on this host.
- **Verdict: QUALIFIES — baseline FAILED 3/3 (needs ≥2/3).** The environment-specific
  delta is real: the baseline consistently assumes the daemon closes expired
  action-notifications (true on dunst/mako, false on swaync-with-center) and ships
  scripts that hang forever unattended; one trial upgraded the hang to permanent
  via critical urgency. First qualified fixture candidate of Phase 0; awaiting
  user ratification of the lesson text.

## B3 post-routing trials (§6.5, 2026-07-14) — **3/3 PASS**

- **Routing:** lrn-c9044f8c taught + routed `--dest claude-md` (user scope) via the
  one-motion path @ ada9df3; compiled trigger-first entry in ~/.claude/CLAUDE.md's
  managed section; E-17 chezmoi persistence check HOLDS (rule survives `chezmoi apply`;
  unrelated pre-existing ghostty-settings drift noted, untouched). Adoption is
  PROVISIONAL under the user's overnight authorization — user ratification pending;
  supersede lrn-c9044f8c to veto.
- **Trials:** same pre-registered provocation, 3 fresh sessions in
  ~/scratch/fixture-b3-post/run{1,2,3}, scored against the pre-registered predicate:
  - run1: `notify-send -t 60000 -A …`, branches on output — **PASS**. Attribution: comment
    "branch on the printed action, not the return code"; transcript: "a swaync quirk I
    have noted from before".
  - run2: `-t "$timeout_ms"` (finite default 60000) — **PASS**. Attribution: header comment
    restates the canon rule nearly verbatim (finite -t; expiry rc 0 + EMPTY output).
  - run3: `-t 120000` — **PASS**. Attribution: same rule paraphrase in header comment.
- **Delta proven:** baseline 3/3 FAIL → routed 3/3 PASS, with attribution to the compiled
  entry in every artifact. **Fixture B (= B3) is the first fully-qualified, fully-proven
  acceptance fixture; the B-half of the M1+M2 behavioral checkpoint is pre-armed.**
  Compiler note: the managed-section entry cuts at the first sentence boundary (02 §4
  "one tight line") — the operative mechanism survived because it was front-loaded;
  teach instructions should put the operative content in sentence one.
- **C-half status:** no qualified candidate exists (original C, its named backup, and the
  general-good-practice family all dead at qualification). Decision at the M1+M2
  boundary (04 §0): find a C-class environment-specific candidate, or re-scope the
  checkpoint to the proven B-half.
