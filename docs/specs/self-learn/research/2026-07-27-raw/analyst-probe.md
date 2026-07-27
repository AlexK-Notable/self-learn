# Empirical probe of the `self-learn` routing analyst

Date: 2026-07-26. Target: `analyst.analyze(home, record)` in
`/home/komi/repos/self-learn/plugins/self-learn/cli/src/self_learn/analyst.py`.
Model under test: `claude-sonnet-5` (the shipped `DEFAULT_ANALYST_MODEL`).

Budget: **38 of 40** analyst spawns used. 2 unspent. Plus 1 non-analyst
auth probe (`claude -p 'Reply with exactly: PROBE_OK'`) during rig setup.

---

## 0. Headline

The two most load-bearing results, stated up front because they invert
the question the probe was commissioned to answer:

1. **`hook` is structurally unreachable through `analyst.analyze()`.**
   Not "rarely chosen" — *impossible to return*. `analyze()` builds its
   proposal dict from a fixed key set (`destination`, `alternates`,
   `rationale`, `model`, `analyzed_at`, `record_sha`, plus
   `variant`/`rules_topic`/`rules_paths`) and **never copies the model's
   `hook:` or `examples:` keys**, while `validate_proposal` *requires*
   them for `destination: hook`. Every `hook` answer therefore becomes a
   `ProposalError` → `AnalystError`. Proven twice: by a stubbed control
   feeding a full doctrine-§5.1-compliant hook block (still fails), and
   by 12 live runs.

2. **On the real record `lrn-74b8e65a`, the model's modal answer is
   `hook`, at every sightings level including 1.** 13 of 38 spawns
   emitted `destination: hook`; all 13 were destroyed by (1). The
   "monoculture" on this record is not the model preferring `claude-md`
   — it is the pipeline deleting the model's actual first choice and the
   caller falling back to a plain pending capture.

Every other destination is alive and easy to elicit: `new-skill` 8/8
under favourable framing, `skill-md` 6/6, `reference` 3/3, `claude-md`
8/8 under its own conditions.

---

## 1. Harness design

### 1.1 What is actually executed

The harness runs the **real `analyst.analyze()`** — same argv, same
doctrine file, same one-shot parse, same `validate_proposal` — and wraps
`analyst.subprocess.run` so that the raw `CompletedProcess` is captured
even for spawns whose proposals `analyze()` then rejects. This is the
critical property: **`analyze()` discards the model's raw output on
failure**, so measuring only its return value would have made the entire
headline finding invisible. Files:

- `…/scratchpad/probe/harness.py` — the patched runner + JSONL logger
- `…/scratchpad/probe/exp.py` — condition definitions
- `…/scratchpad/probe/control.py` — the zero-cost positive control
- `…/scratchpad/probe/tally.py` — the tally
- `…/scratchpad/probe/runs.jsonl` — **every run, machine-readable**
- `…/scratchpad/probe/raw_appendix.md` — every run's raw stdout, verbatim

Two deliberate harness deviations from `analyze()`, both documented:

- The patched `run` injects `cwd=` (per-condition). `analyze()` passes no
  `cwd` and inherits the caller's — equivalent to having launched the
  process from that directory. Needed for Experiment 4.
- `SELF_LEARN_ANALYST_TIMEOUT=300` instead of the production default 120,
  with **wall-clock duration recorded for every run** so production
  timeout behaviour is still measurable. Result: max observed duration
  **40.1 s**; **0 of 38 runs would have timed out at the production 120 s**.
  Timeouts are not a contributor to anything observed here.

### 1.2 Sandbox

All runs under
`/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/`
with `env -i` and only: `PATH`, `HOME=$SB/home`, `XDG_CACHE_HOME=$SB/cache`,
`XDG_RUNTIME_DIR=$SB/runtime`, `SELF_LEARN_HOME=$SB/ledger`,
`SELF_LEARN_CLAUDE_DIR=$SB/claudedir`, `SELF_LEARN_TRANSCRIPTS_DIR=$SB/transcripts`,
`SELF_LEARN_ANALYST_TIMEOUT`.

**One necessary exception, flagged.** A bare sandbox `HOME` breaks
authentication — verified empirically, the first probe returned
`Not logged in · Please run /login` (rc=1). Fix: a **symlink only** of
`/home/komi/.claude/.credentials.json` into `$SB/home/.claude/`. No copy
of the secret at rest, nothing else from the real `~/.claude` present.

**Consequence to keep in mind when generalising:** the spawned analyst
sees a clean HOME — **no `~/.claude/CLAUDE.md`, no `settings.json`, no
local plugins**. In production the analyst inherits the user's real
global CLAUDE.md as system context. So these results characterise the
analyst as a near-pure function of *doctrine + record + cwd*, which is
the cleaner instrument, but is not byte-identical to production context.
(Account-level MCP connectors *did* still load — `mcp-logs-*` dirs appear
in the sandbox cache — so the spawn is not free of ambient context.)

### 1.3 State-safety verification (post-hoc, all passed)

| Check | Baseline | After 38 runs |
|---|---|---|
| `~/.cache/self-learn/home-*` dirs | 31033 | **31033** (no new dirs) |
| `~/.self-learn/user/pending/lrn-74b8e65a.md` md5 | `8374069e…` | **`8374069e…`** |
| Any `~/.self-learn` file modified in last 2h | — | **none** |
| `git status --porcelain` | clean | **clean** |

The record was copied out and never touched. No `self-learn` verb was
run. No `sudo`, no `chezmoi`.

### 1.4 Positive control

**Two layers, because one is not enough.**

**Layer A — zero API calls (`control.py`).** Replaces the `claude` spawn
with a stub emitting canned YAML, then runs the *real* `analyze()`. This
proves the rig can report every destination and is not silently
funnelling everything to `claude-md`:

| Canned model output | `analyze()` result |
|---|---|
| `destination: claude-md` | ✅ returns `claude-md` |
| `destination: skill-md` | ✅ returns `skill-md` |
| `destination: reference` | ✅ returns `reference` |
| `destination: new-skill` | ✅ returns `new-skill` |
| `destination: hook` (bare) | ❌ `AnalystError: a hook proposal carries the structured compile input` |
| **`destination: hook` + FULL doctrine-§5.1 `hook:`/`examples:` block** | ❌ **same `AnalystError`** |
| fenced ```` ```yaml ```` block | ✅ returns `claude-md` (fence stripping works) |
| prose only, no YAML | ❌ `AnalystError: analyst output is not a YAML mapping (got str)` |
| `claude-md` + `variant: rules` + topic + paths | ✅ returns `claude-md` with variant fields intact |

The sixth row is the finding. A model that does *everything the doctrine
asks of a hook proposal* still cannot produce one through `analyze()`.

**Layer B — live spawns.** The rig reported four distinct destinations
from real API calls: `claude-md` (8), `new-skill` (8), `skill-md` (6),
`reference` (3). An "always claude-md" reading of this rig is therefore
not available; when a condition is 3/3 `claude-md` it is because the
model said so.

---

## 2. Results — raw distribution

N = 38 live spawns. **"model-emitted"** is parsed from raw stdout;
**"`analyze()` returns"** is what production would actually receive.

| Condition | N | Model-emitted destination | `analyze()` returns |
|---|---|---|---|
| E1-sightings**1** | 3 | hook=2, claude-md=1 | AnalystError=2, claude-md=1 |
| E1-sightings**3** | 3 | hook=3 | AnalystError=3 |
| E1-sightings**5** | 3 | hook=2, claude-md=1 | AnalystError=2, claude-md=1 |
| E1-sightings**10** | 3 | hook=3 | AnalystError=3 |
| E2-f1 methodology (6-stage BTRFS recovery) | 2 | new-skill=2 | new-skill=2 |
| E2-f2 cluster (7 sibling plotter lessons) | 2 | new-skill=2 | new-skill=2 |
| E2-f3 project doc (release workflow) | 2 | new-skill=2 | new-skill=2 |
| E2-f4 explicit (9 entries, cap pressure) | 2 | new-skill=2 | new-skill=2 |
| E3-scope-**project** | 3 | hook=3 | AnalystError=3 |
| E3-scope-**skill** (`skill:shell-safety`) | 3 | skill-md=3 | skill-md=3 |
| E4-**bare** (no skill in cwd) | 3 | claude-md=3 | claude-md=3 |
| E4-**decoy** (unrelated skill in cwd) | 3 | claude-md=3 | claude-md=3 |
| E4-**skill-visible** (owning skill in cwd) | 3 | skill-md=3 | skill-md=3 |
| E5-knowledge @ skill scope, skill visible | 3 | reference=3 | reference=3 |

**Totals, model-emitted:** hook **13**, claude-md **8**, new-skill **8**,
skill-md **6**, reference **3**.
**Totals, `analyze()` returns:** FAIL **13**, claude-md **8**, new-skill
**8**, skill-md **6**, reference **3**.

**Failures — 13 of 38 (34%), every one silent in production:**

| Failure mode | N |
|---|---|
| `analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message}` | **12** |
| `analyst output is not valid YAML: mapping values are not allowed here` | **1** |
| timeout | 0 |
| non-zero subprocess exit | 0 (**every** failing run had `rc=0`) |

---

## 3. Experiment 1 — the escalation promise

**Manipulation.** `~/.self-learn/user/pending/lrn-74b8e65a.md` copied out
(original never touched, md5 re-verified after). `sightings:` set to 1, 3,
5, 10. Byte-identity verified: `diff` of the four files with the
sightings value masked is empty. 3 runs per level, 12 spawns.

**Result. Sightings never moved the destination — because the
destination was already `hook` at sightings = 1.**

- sightings 1 → hook 2/3, claude-md 1/3
- sightings 3 → hook 3/3
- sightings 5 → hook 2/3, claude-md 1/3
- sightings 10 → hook 3/3

10 of 12 emitted `hook`. There is no monotone trend and no threshold; the
1/3 claude-md answers at s1 and s5 are sampling noise around a
hook-dominant distribution, not a low-sightings regime. **The `sightings`
field is not a routing lever for this record.**

**Verdict on "escalate to hook only if this recurs": false twice over.**

- *Descriptively false* — the analyst does not withhold `hook` pending
  recurrence. It proposes `hook` on the first sighting, with rationales
  that never mention sightings and instead cite doctrine §2 directly
  (*"mechanical, tool-detectable command shape … a deterministic guard
  beats advisory text"*). Only one run mentioned the count at all
  (s10 #3: *"across 10 recurring sightings"*), and it reached the same
  destination as s1.
- *Mechanically false* — recurrence cannot deliver `hook` later either.
  §0(1) means no number of sightings can make `analyze()` return `hook`.
  A proposal that promises escalation-on-recurrence is promising a
  transition the code cannot perform.

**The over-block was named unprompted.** Several hook rationales
volunteered the §5.1 over-block ("the guard would over-block any
deliberately-unquoted word-splitting loop, which is legitimate but
rare"). The model is following the doctrine closely — including parts the
prompt template does not ask for. It is the *template* (which lists only
`destination`/`alternates`/`rationale`/`variant`/`rules_topic`/`rules_paths`)
that stops it emitting the `hook:` block — and per the control, emitting
it would not have helped anyway.

**Second, independent silent-failure mode found here.** E1-sightings3 #2
failed on YAML parse: the model wrote an unquoted rationale containing
`` `kind: anti-pattern` ``, and the colon-space broke the mapping. The
prompt template shows `rationale: <one sentence>` **unquoted**, so any
rationale containing `": "` kills the single parse attempt. 1 of 38 runs
(2.6%) died this way. There is no reprompt.

---

## 4. Experiment 2 — is `new-skill` reachable?

**Manipulation.** Four independently-constructed records engineered as
ideal `new-skill` cases, 2 runs each, 8 spawns:

- **f1** — `knowledge`/user, a six-stage BTRFS snapshot-chain recovery
  methodology with per-stage preconditions, commands and rollbacks.
- **f2** — `knowledge`/user, an explicit *cluster*: seven sibling lessons
  about a pen plotter, named by id, with "no existing skill covers this".
- **f3** — `knowledge`/project, a long multi-surface release workflow
  (happy path, artifact table, signing, staged rollout, rollback,
  glossary, troubleshooting).
- **f4** — `knowledge`/user, nine accumulated beekeeping entries stated
  to be occupying 9 of the user CLAUDE.md section's 10-entry cap.

**Result: 8/8 `new-skill`. Every framing, both runs, no failures, no
variance.** Median duration 12 s — the fastest, most confident condition
in the whole probe.

**Verdict: `new-skill` is not a dead destination.** The hypothesis that
the analyst cannot or will not select it is **ruled out** by 8/8. Its
absence from the historical record (0 of 28) is a property of the *record
population* — the queue apparently contains no rich multi-part
methodology clusters — or of a different routing path, not a property of
this analyst. Note the asymmetry with `hook`: `new-skill` also "compiles
at M3 with extra human steps" (doctrine §7), yet `validate_proposal`
imposes no extra required fields on it, so it survives `analyze()` intact.

---

## 5. Experiment 3 — does scope determine destination?

**Manipulation.** Base record body byte-identical; only `scope:` varied.
`diff` with the scope line masked is empty. 3 runs per arm; the `user`
arm is E1-sightings1, reused (same file, same content).

| scope | N | model-emitted | `analyze()` returns |
|---|---|---|---|
| `user` | 3 | hook=2, claude-md=1 | AnalystError=2, claude-md=1 |
| `project` | 3 | hook=3 | AnalystError=3 |
| `skill:shell-safety` | 3 | **skill-md=3** | **skill-md=3** |

**Verdict: scope is decisive at skill scope, and inert between user and
project.**

- Flipping to skill scope flipped the destination **3/3**, cleanly and
  fast (14–24 s vs 28–40 s for the hook-emitting arms). Doctrine §2's
  "the default for `behavior` records with skill scope" is being applied
  literally.
- user vs project produced **no** difference: both hook-dominant, and
  neither ever emitted a scope-appropriate `claude-md` variant. The
  observed production pattern "user scope ⇒ `claude-md`" is **not**
  reproduced here as a model behaviour. What actually happens at user and
  project scope for this record is *`hook`, then an exception.*
- Note what this does to the `variant` machinery: **zero of 38 runs
  emitted `variant: rules` or `variant: local`**, including the project
  and user arms of a lesson whose trigger is a command shape. The A2
  variant fields are offered by the prompt and, in this sample, never used.

---

## 6. Experiment 4 — information availability

**Manipulation.** One record (`widget-sync` push/reconcile surface-rule,
`scope: user`, byte-identical across arms) run against three different
working directories. Only the filesystem differs.

| cwd | N | result |
|---|---|---|
| `work_e4_bare` — empty | 3 | **claude-md 3/3** |
| `work_e4_decoy` — `.claude/skills/beekeeping/SKILL.md` (unrelated) | 3 | **claude-md 3/3** |
| `work_e4_skill` — `.claude/skills/widget-sync/SKILL.md` + `references/LEARNINGS.md` | 3 | **skill-md 3/3** |

**Verdict: information availability determines the destination, and the
"no existing skill owns this" rationale is true and load-bearing, not a
rationalisation.** Perfect 3/3 separation, and the rationales prove the
model actually read the tree rather than pattern-matching:

- bare: *"No existing skill owns widget-sync, and the surface-rule kind's
  default (skill-md) has no skill home, so the narrowest surface that
  still fires … is user-level claude-md"*
- skill-visible: *"the existing widget-sync skill already triggers on
  (reconcile, push/pull queue, revision stale)"* — **quoting the
  `description:` frontmatter of the SKILL.md I planted**, which it could
  only have obtained by opening the file.

**The decoy arm is what makes this conclusive.** A `.claude/skills/` tree
containing an unrelated skill did **not** flip the destination (3/3
claude-md). The model is discriminating on *ownership*, not on the mere
presence of skills. So this is not "the model can't see the alternatives"
— it sees them, evaluates fit, and rejects a non-owner.

**Corollary.** The analyst's answer is a function of its **cwd**, which
`analyze()` never sets — it inherits the caller's. The same record routed
from a repo with an owning skill and from `$HOME` will get different
destinations, deterministically. That is an uncontrolled input in
production.

---

## 7. Experiment 5 (spare budget) — is `reference` reachable?

**Manipulation.** `type: knowledge`, `scope: skill:widget-sync`, a bulky
eleven-code exit-status table explicitly framed as lookup material, run
with the owning skill visible. 3 spawns.

**Result: `reference` 3/3.** Fastest condition measured (5.1–7.1 s).
Doctrine §2's "`knowledge`, skill scope → `reference` … `skill-md` only
when the fact must be present at activation" applied exactly.

---

## 8. What the data rules out

**Ruled out (with run counts):**

- ❌ **"`new-skill` is effectively dead / unreachable."** 8/8 across 4
  independent framings. Refuted.
- ❌ **"The analyst can't see the alternatives, so its 'no skill owns
  this' rationales are vacuous."** E4: 3/3 flip when an owning skill is
  present, 3/3 no-flip on a decoy skill, with verbatim quotation of the
  planted SKILL.md description. Refuted; the rationale is accurate.
- ❌ **"The model prefers `claude-md` for user-scope behaviour records."**
  On the real record, 10/12 emissions at user scope were `hook`. Refuted
  for this record class.
- ❌ **"Sightings escalates the destination."** 12 runs across 4 levels,
  no movement; hook already modal at sightings=1. Refuted.
- ❌ **"The monoculture is situational — these particular lessons just
  happened to suit `claude-md`."** The base record does *not* suit
  claude-md in the model's judgment; it suits `hook`, and `hook` cannot
  be returned. Structural, not situational.
- ❌ **"Timeouts / flaky spawns explain the missing destinations."**
  0/38 timeouts, 0/38 non-zero exits, max duration 40 s against a 120 s
  production budget. Refuted.
- ❌ **"Scope determines destination mechanically across the board."**
  Partly refuted: decisive at skill scope (3/3), **inert** between user
  and project (both hook-dominant, 6/6 hook).

**Supported (with run counts):**

- ✅ **`hook` is unreachable through `analyze()` by construction** —
  stub control including a fully compliant §5.1 block, plus 12/12 live
  hook emissions destroyed.
- ✅ **34% of spawns (13/38) failed, every one with subprocess `rc=0`
  and no timeout** — i.e. invisible to any check that watches exit status
  or wall clock.
- ✅ **cwd is an uncontrolled routing input** (E4, 9 runs, 3 arms).
- ✅ **The unquoted-`rationale` YAML hazard is live** — 1/38, with no
  reprompt to recover it.

**Not tested (budget/scope):**

- The path that produced the 9 pending user-scope `claude-md` proposals.
  Those come from the M2 worker / `/self-learn:review` inline analysis,
  **not** from `analyst.analyze()`. Everything above is about the bare
  `teach --route` analyst only. Whether the worker path also drops
  `hook:` blocks is **untested and is the single highest-value follow-up**
  — it decides whether §0(1) explains the historical 3 `hook` routes and
  the 10 `claude-md` ones, or only the bare-`--route` path.
- Models other than `claude-sonnet-5`.
- Production context (real `~/.claude/CLAUDE.md` present) — see §1.2.
- `variant: rules` / `local` elicitation: never observed in 38 runs, but
  no condition was designed to force it.
- 2 spawns of the 40-call budget remain unspent.

---

## 9. Code references

- `plugins/self-learn/cli/src/self_learn/analyst.py:85-102` —
  `_PROMPT_TEMPLATE`. Lists **only** destination / alternates / rationale
  / variant / rules_topic / rules_paths. Never mentions the `hook:` block
  that doctrine §5.1 requires, and shows `rationale:` unquoted.
- `plugins/self-learn/cli/src/self_learn/analyst.py:195-211` — the
  proposal dict. Fixed key set + the three variant keys. **`hook` and
  `examples` are never carried over from `parsed`.** This is the defect.
- `plugins/self-learn/cli/src/self_learn/ledger_ops.py:426-454` —
  `_validate_hook_extension`, which requires `hook: {tools, path_regex,
  deny_message}` whenever `destination == "hook"`. Together with the line
  above, this makes `hook` a guaranteed `AnalystError`.
- `plugins/self-learn/cli/src/self_learn/analyst.py:166` — `analyze()`
  accepts `home` and **never uses it**.
- `plugins/self-learn/cli/src/self_learn/analyst.py:181-184` —
  `subprocess.run` with no `cwd`; the analyst's filesystem view is the
  caller's cwd (see §6).
- `plugins/self-learn/skills/self-learn/references/routing-doctrine.md`
  — 434 lines, passed whole as `--append-system-prompt`. Contains **no
  mention of `sightings`** anywhere; there is no escalation-on-recurrence
  rule in doctrine for the analyst to follow.

---

## Appendix — every run, verbatim

Machine-readable: `…/scratchpad/probe/runs.jsonl` (38 rows, each with
condition, run index, scope, sightings, cwd, duration, rc, raw stdout,
raw stderr, and the parsed/failed outcome).

Human-readable, all 38 raw model outputs: `…/scratchpad/probe/raw_appendix.md`.
### E1-sightings1 run 1

- scope `user` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 23.7s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: the mistake is a mechanical, tool-detectable command shape (unquoted variable as a for-in loop source under zsh) that a PreToolUse guard on Bash can catch deterministically, which beats advisory text for a silent-no-op failure mode.
```

### E1-sightings1 run 2

- scope `user` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 28.0s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['hook']`

```yaml
```yaml
destination: claude-md
alternates: [hook]
rationale: environment-specific zsh word-splitting gotcha applies to any Bash-tool shell loop across all sessions/skills on this host, and recognizing "does this variable actually need splitting" takes judgment, so advisory user-level guidance beats a blanket command-shape hook that would over-block legitimate single-token loops.
```
```

### E1-sightings1 run 3

- scope `user` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 14.2s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: the failure mode is a mechanical, regex-detectable command shape (unquoted `$VAR` inside a `for ... in` loop under the Bash tool), so a deterministic guard catches it before a silent no-op ships, stronger than advisory prose in a rarely-consulted user rule.
```

### E1-sightings3 run 1

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 40.1s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: this is a mechanical, tool-detectable command shape (unquoted variable used as a for-loop iterator in a Bash command) — a regex guard on the Bash tool_input.command is a stronger, deterministic catch than advisory text recalled from memory each session.
```

### E1-sightings3 run 2

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 23.7s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst output is not valid YAML: mapping values are not allowed here
  in "<unicode string>", line 3, column 27:
    rationale: This is a `kind: anti-pattern` record with a me ... 
                              ^ (line: 3)

```yaml
destination: hook
alternates: [claude-md]
rationale: This is a `kind: anti-pattern` record with a mechanical, tool-detectable command shape (an unquoted variable after `in` in a Bash `for` loop) — a deterministic PreToolUse guard on the Bash tool_input.command catches it more reliably than advisory prose, with plain user-scope claude-md as the fallback since the rule applies host-wide and isn't skill-specific.
```

### E1-sightings3 run 3

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 29.9s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: Anti-pattern is mechanical and tool-detectable via a regex on the Bash command string (unquoted `$VAR` in a `for … in` loop), making a deterministic guard stronger than advisory text for this host-specific zsh gotcha.
```

### E1-sightings5 run 1

- scope `user` | sightings `5` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 31.6s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: The mistake is mechanical and command-shape detectable (unquoted `$VAR` in a `for ... in` loop on this zsh host), so a PreToolUse regex guard on the Bash command catches it before the silent no-op happens, which is stronger than advisory prose the model must remember to apply.
```

### E1-sightings5 run 2

- scope `user` | sightings `5` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 30.1s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['hook']`
- variant fields: `{'variant': 'rules', 'rules_topic': 'shell-quoting'}`

```yaml
destination: claude-md
alternates: [hook]
rationale: This is a general Bash-tool shell-quoting quirk tied to this host's zsh runtime, not scoped to any single skill, and the loop-shape regex can't reliably distinguish an unsafe multi-token unquoted expansion from a benign single-token one, so a narrow rules file beats a hook or a fat CLAUDE.md.
variant: rules
rules_topic: shell-quoting
```

### E1-sightings5 run 3

- scope `user` | sightings `5` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 17.1s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
```yaml
destination: hook
alternates: [claude-md]
rationale: the anti-pattern is a mechanical, regex-detectable command shape (unquoted-variable for-loop under a Bash tool call) so a deterministic guard on Bash tool_input.command outperforms advisory prose that could be silently skipped.
```
```

### E1-sightings10 run 1

- scope `user` | sightings `10` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 27.6s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: The trigger is a mechanical, tool-detectable command shape (unquoted `for X in $VAR` loop in a Bash-tool call on this zsh host), which the doctrine's hook criterion explicitly favors over advisory text; a PreToolUse guard on Bash matching an unquoted-variable for-loop can catch this deterministically, with plain user-scope claude-md as the fallback advisory alternate given the over-block risk (legitimate single-token or intentionally-unsplit loops would also match).
```

### E1-sightings10 run 2

- scope `user` | sightings `10` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 35.7s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: This is a mechanical, tool-detectable command shape (unquoted `for x in $VAR` loop in a Bash-tool command under zsh) where a deterministic guard catching the pattern beats advisory prose, since the failure mode is a silent no-op that's easy to miss.
```

### E1-sightings10 run 3

- scope `user` | sightings `10` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 33.1s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md, skill-md]
rationale: The anti-pattern is a mechanical, tool-detectable command shape (unquoted variable in a `for` loop under zsh) that silently no-ops rather than erroring, so a deterministic Bash-command guard catches it more reliably than advisory prose across 10 recurring sightings.
```

### E2-f1_methodology run 1

- scope `user` | sightings `4` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 12.0s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
```yaml
destination: new-skill
alternates: [claude-md]
rationale: No existing skill covers filesystem/BTRFS recovery and this is a six-stage procedure with a decision tree and stage transcripts far too large for any managed section, so it wants its own skill with reference files.
```
```

### E2-f1_methodology run 2

- scope `user` | sightings `4` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 10.4s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
destination: new-skill
alternates: [claude-md]
rationale: A six-stage, multi-thousand-word body of practice with its own decision tree, glossary, and stage-by-stage command transcripts needs its own skill (with reference files for the transcripts) rather than a managed section, and no existing skill covers filesystem recovery to receive it as a reference append.
```

### E2-f2_cluster run 1

- scope `user` | sightings `7` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 8.3s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
destination: new-skill
alternates: [claude-md]
rationale: seven verified, coherent plotter lessons (handshake, coordinate flip, calibration, truncation modes, registration jig, move reordering, stall recovery) form a manual-shaped domain with no existing skill home, and the two already in CLAUDE.md are actively diluting it — exactly the cluster §2/§7 reserve for new-skill.
```

### E2-f2_cluster run 2

- scope `user` | sightings `7` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 9.3s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md', 'reference']`

```yaml
destination: new-skill
alternates: [claude-md, reference]
rationale: seven verified plotter lessons form a coherent manual (quick reference, calibration, troubleshooting) with no existing skill home, and scattering them in user CLAUDE.md is already diluting it.
```

### E2-f3_project_doc run 1

- scope `project` | sightings `5` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 11.7s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
destination: new-skill
alternates: [claude-md]
rationale: this is a long on-demand procedure (commands, artifact table, signing, rollout gates, rollback, troubleshooting) with no existing skill to own it and no firing moment to justify always-loaded project instructions.
```

### E2-f3_project_doc run 2

- scope `project` | sightings `5` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 11.8s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `[]`

```yaml
destination: new-skill
alternates: []
rationale: This is a long, on-demand, multi-section procedure (happy path, artifacts, signing, staged rollout, rollback, glossary, troubleshooting) that no existing skill covers and that the record itself says must not live in always-loaded project instructions, so it should be scaffolded as its own release-process skill.
```

### E2-f4_explicit run 1

- scope `user` | sightings `9` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 14.0s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
destination: new-skill
alternates: [claude-md]
rationale: nine beekeeping-equipment knowledge entries have filled the user-scope managed section to its cap while never firing in a coding session, and no existing skill or references file covers apiculture, so the narrowest-surface bias calls for scaffolding a dedicated skill (with its own references/LEARNINGS.md) rather than continuing to pay the always-loaded cost.
```

### E2-f4_explicit run 2

- scope `user` | sightings `9` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 13.7s | subprocess rc=0
- `analyze()` returned: new-skill
- alternates: `['claude-md']`

```yaml
destination: new-skill
alternates: [claude-md]
rationale: nine knowledge entries form a single tight domain (beekeeping-equipment maintenance) that never fires in general coding sessions yet is eating the user-scope entry cap, so scaffolding a dedicated skill (with its own references/LEARNINGS.md) is the narrowest surface that still fires — no existing skill or references file can absorb them today.
```

### E3-scope-project run 1

- scope `project` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 30.2s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
```yaml
destination: hook
alternates: [skill-md, claude-md]
rationale: the mistake is a mechanical, tool-detectable command shape (unquoted-variable for-loop under zsh) that a PreToolUse guard on Bash can catch deterministically, stronger than advisory prose.
```
```

### E3-scope-project run 2

- scope `project` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 39.3s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: The mistake is a mechanical, regex-detectable Bash command shape (`for x in $VAR` with an unquoted, non-array variable) that fails silently under zsh, so a deterministic pre-exec guard is more reliable than advisory prose; note the guard would over-block any deliberately-unquoted word-splitting loop, which is legitimate but rare.
```

### E3-scope-project run 3

- scope `project` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 31.0s | subprocess rc=0
- `analyze()` returned: **AnalystError** — analyst proposal invalid: a hook proposal carries the structured compile input — hook: {tools, path_regex, deny_message} (02 §1 hook extension)

```yaml
destination: hook
alternates: [claude-md]
rationale: Kind is anti-pattern with a mechanical, tool-detectable command shape (unquoted `for x in $VAR` loop in a Bash-tool command run under zsh), which the doctrine says favors a deterministic guard over advisory prose, though the guard will need to accept a documented over-block for cases where the variable is already a single safe token or a `$(...)`-array expansion.
```

### E3-scope-skill run 1

- scope `skill:shell-safety` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 14.7s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['hook']`

```yaml
destination: skill-md
alternates: [hook]
rationale: Recognizing "unquoted var holds multiple tokens for iteration" needs judgment a regex-only hook would false-positive on, and skill:shell-safety already exists as the natural home for this rule.
```

### E3-scope-skill run 2

- scope `skill:shell-safety` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 15.5s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['hook']`

```yaml
destination: skill-md
alternates: [hook]
rationale: Anti-pattern is skill-scoped (shell-safety) and recognizing it requires understanding shell semantics/context rather than a purely mechanical, safely-blockable command pattern, so a loaded skill-md rule fits better than a hook that would risk over-blocking valid unquoted-variable usage.
```

### E3-scope-skill run 3

- scope `skill:shell-safety` | sightings `1` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work` | 24.2s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['hook']`

```yaml
destination: skill-md
alternates: [hook]
rationale: Recognizing when a shell variable holds multiple space-separated tokens (vs. a single value) requires judgment a regex guard can't reliably make without heavy false positives, so this fits skill-md's shell-safety rules better than a hook.
```

### E4-bare run 1

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_bare` | 22.1s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['skill-md', 'hook']`

```yaml
destination: claude-md
alternates: [skill-md, hook]
rationale: it's a user-scope surface-rule with no identified owning skill for the widget-sync tool, and the trigger is a command shape rather than a file path, so plain user CLAUDE.md is the narrowest surface that still fires whenever widget-sync is invoked.
```

### E4-bare run 2

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_bare` | 24.0s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['hook', 'skill-md']`

```yaml
destination: claude-md
alternates: [hook, skill-md]
rationale: No existing skill owns widget-sync, and the surface-rule kind's default (skill-md) has no skill home, so the narrowest surface that still fires for this user-scope, environment-specific rule is user-level claude-md; hook is a plausible alternate given the command-shape trigger but can't reliably track whether reconcile already ran this session.
```

### E4-bare run 3

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_bare` | 20.5s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['skill-md', 'hook']`

```yaml
destination: claude-md
alternates: [skill-md, hook]
rationale: Surface-rule with scope user and no owning skill for the widget-sync CLI, so it must fire in every session regardless of project — user-scope CLAUDE.md is the narrowest surface that still fires; hook is a weaker fit since detecting "reconcile ran earlier this session" needs session judgment, not a pure command-shape match.
```

### E4-decoy-skill run 1

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_decoy` | 23.2s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['skill-md']`

```yaml
destination: claude-md
alternates: [skill-md]
rationale: Scope is user with no path trigger and no existing widget-sync skill to host a skill-md rule, so the narrowest surface that still fires for every widget-sync invocation is user-level CLAUDE.md.
```

### E4-decoy-skill run 2

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_decoy` | 22.5s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['skill-md', 'hook']`

```yaml
destination: claude-md
alternates: [skill-md, hook]
rationale: user-scope CLI workflow gotcha with no owning skill to host a skill-md rule, and the trigger is a command pattern rather than a file path, so it's a standing user rule, not a pathed variant.
```

### E4-decoy-skill run 3

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_decoy` | 12.1s | subprocess rc=0
- `analyze()` returned: claude-md
- alternates: `['hook', 'skill-md']`
- variant fields: `{'variant': 'rules', 'rules_topic': 'widget-sync'}`

```yaml
destination: claude-md
alternates: [hook, skill-md]
rationale: Surface-rule behavior scoped to the user's own CLI tool (widget-sync) with no owning skill, so it belongs in a user-level rules topic rather than the flat CLAUDE.md or a hook that can't easily track session-reconcile state.
variant: rules
rules_topic: widget-sync
```

### E4-skill-visible run 1

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 16.8s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['hook', 'claude-md']`

```yaml
destination: skill-md
alternates: [hook, claude-md]
rationale: this is a surface-rule tied entirely to the widget-sync CLI, and an owning widget-sync skill already exists, so skill-md is the narrowest surface that fires whenever that skill activates rather than loading globally via user CLAUDE.md.
```

### E4-skill-visible run 2

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 10.0s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['claude-md']`

```yaml
destination: skill-md
alternates: [claude-md]
rationale: The widget-sync skill exists specifically for push/pull/reconcile queue operations, making it the narrowest surface that still fires whenever this exact trigger occurs.
```

### E4-skill-visible run 3

- scope `user` | sightings `3` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 6.2s | subprocess rc=0
- `analyze()` returned: skill-md
- alternates: `['claude-md']`

```yaml
destination: skill-md
alternates: [claude-md]
rationale: This is a widget-sync-specific surface-rule that the existing widget-sync skill already triggers on (reconcile, push/pull queue, revision stale), so it belongs in that skill's SKILL.md rather than the more expensive always-loaded user CLAUDE.md.
```

### E5-knowledge-skillscope run 1

- scope `skill:widget-sync` | sightings `2` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 5.2s | subprocess rc=0
- `analyze()` returned: reference
- alternates: `['skill-md']`

```yaml
destination: reference
alternates: [skill-md]
rationale: exit-code lookup table is skill-scoped knowledge needed only after something has already gone wrong, not at every activation, so it belongs in widget-sync's references/LEARNINGS.md rather than SKILL.md.
```

### E5-knowledge-skillscope run 2

- scope `skill:widget-sync` | sightings `2` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 7.1s | subprocess rc=0
- `analyze()` returned: reference
- alternates: `['skill-md']`

```yaml
destination: reference
alternates: [skill-md]
rationale: exit-code lookup table is skill-scoped knowledge needed only after something has already gone wrong, not at every activation, so it belongs in the widget-sync skill's references/LEARNINGS.md rather than its always-loaded SKILL.md.
```

### E5-knowledge-skillscope run 3

- scope `skill:widget-sync` | sightings `2` | cwd `/tmp/claude-1000/-home-komi-repos-self-learn/e18d1662-ac1a-46f3-88d1-aac653c5adaa/scratchpad/probe/work_e4_skill` | 5.1s | subprocess rc=0
- `analyze()` returned: reference
- alternates: `['skill-md']`

```yaml
destination: reference
alternates: [skill-md]
rationale: Exit-code table is lookup material for when something has already gone wrong, not needed at every widget-sync activation, so it belongs in the skill's references/LEARNINGS.md rather than its always-loaded SKILL.md.
```

