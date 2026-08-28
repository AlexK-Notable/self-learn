# U-corrob — the consumer of the SDK backend's captured `tool_events` and `denials`

Status: **DRAFT r4 — for a BLIND Opus spec gate (delta confirmation).**

**r1 (2026-08-27)** — first draft. **Gate r1: NOT SOUND** — 2 BLOCKER, 5 MAJOR,
7 NIT, 2 DOCS: placement, one dead mutation, four mechanism claims.
**r2 (2026-08-27)** — all 16 r1 findings folded, all verified correct by the
gate. **Gate r2: NOT SOUND** — 2 BLOCKER, 2 MAJOR, 5 NIT, 0 DOCS, **every one
of them introduced by the `M-3`/`B-2` folds themselves**.
**r3 (2026-08-27)** — the four r2 findings and five nits folded. Structural:
the emission discriminator split into **two flags** (`B-1r2`); the reader's
census became a **recursive before/after snapshot** (`M-1r2`, `N-5r2`); the
noise analysis was **re-aimed at the mode that exists at HEAD** with a
**root-cause fixture fix** (`M-2r2`, `B-2r2`). Criteria 31 → 36; mutations
34 → 40. **Gate r3: NOT SOUND** — **0 BLOCKER**, 2 MAJOR, 4 NIT, 1 DOCS; all
nine r2 findings verified folded, and `PIN7`'s armor argument upheld exactly
as written.
**r5 (2026-08-27)** — two gate nits folded post-SOUND r4 (no re-gate, repricing rule 2026-07-26): anchor `A-8` net delta −7; `RunEvidence(root, *, flat)` spelled at every site; absolute home paths scrubbed to `~`.

**r4 (2026-08-27)** — the two r3 majors, four nits and one doc fold. Changed
sections carry **(CORRECTED-r4, gate X-n)**; earlier markers are left in place
so the fold history stays legible. Structural changes, both bounded: the
worker's accepted-path set is narrowed to **paths whose parent is exactly
`stage_dir()`**, mirroring the deliberately FLAT `staged_paths()` and closing
the nested-write false alarm the r3 fixture fix would otherwise have created
(`M-1r3`); and §6.6's printed block is declared **normative at net −7 lines**,
with `test_hy5_numstat_bounds_hold` added to `PIN7` and its margin measured
(`M-2r3`). Criteria 36 → **37**; mutations 40 → **41**. Hardened, not
redesigned.

Authored at `50fa815` in the throwaway worktree
`.claude/worktrees/u-corrob-spec` (branch `u-corrob-spec`). Uncommitted.
Spec only — no product code.

Dispatched as **T2**. **This spec's own recommendation is T1** (§5.7). The
gate independently confirmed T1 holds on the numbers, conditional on `B-1`;
ruling (a) is the resolution that keeps it (§4.0).

**Every number in this document is a command output.** Where something could
not be measured it is said so, by name, in §15.

Reserved numbering: **`S-53`**; **`FW-128`, `FW-129`, `FW-130`, `FW-131`**
(`FW-131` allocated by ruling on `Q-6`). Measured at `50fa815`:
`03-decisions.md` ends at **`S-50`**, `14-forward-work-map.md` ends at
**`FW-121`** — so `S-51`/`S-52` and `FW-122..127` (the siblings', §14) and
this unit's numbers are disjoint from everything allocated.

---

## 0. Reading order and precedence

1. `03-decisions.md` **`S-44`** — capture-now/consume-later, and the
   standing constraint this unit inherits verbatim: *"the filesystem
   diff remains the authority. Tool events are corroboration, never the
   primary record of what the model wrote."* Where this spec and that row
   disagree, **the row wins**.
2. `03-decisions.md` **`S-32`** (attribution is structural, not
   observational), **`S-40`** (the worker burn-in's two-instrument gate),
   **`S-50`** (`serve` is a scheduler of producers; H-5 preserved).
3. `14-forward-work-map.md` **`FW-84`** (the incident that made
   self-report-is-not-provenance a rule), **`FW-106`** (`V-3`: unscrubbed
   tool inputs in `cache_dir()`, retention 20, the scan/scrub obligation
   attaching **at the surfacing boundary**), **`FW-107`** (closed by
   `U-opsfix` `6f85269` — the first, minimal consumer).
4. `13-hosting-and-separation.md` §5/§8 **H-5** — producers commit their
   own writes; no watcher on the ledger repo, ever.
5. `17-invocation-runbook.md` **§5.4** (the worker burn-in gate that
   reads `denials` AND the filesystem diff) and **§10** (`doctor` row
   verdict semantics).
6. The code, in the order §3 and §4 measure it.

**Precedence inside this document:** the criteria (§9) and the mutation
plan (§10) *are* the spec. §§2–8 are the rationale that produced them; on
a conflict, a criterion wins over prose.

---

## 1. Objective, non-objectives, and the `G-1` boundary

### 1.1 Objective

Decide, from the event corpus that actually exists on this host, what —
if anything — should read `SdkOutcome.tool_events` and `SdkOutcome.denials`
beyond `FW-107`'s one line; then build exactly that and close `S-44`'s
consumer clause with a dated amendment.

### 1.2 Non-objectives

1. **Making tool events authoritative for anything.** They corroborate.
   A mismatch between the two instruments is *reported*, never *resolved*
   in the events' favour, and never changes what lands (`S-44`, `FW-84`).
2. **Any new verb.** `U-verbs` is queued separately. This unit adds no
   subcommand. (A `doctor` row or a `report` field would not have been a
   new verb either — and neither is recommended; see §5.4/§5.2.)
3. **Reading a written event-log file back.** Refused by design, not by
   accident: §7 shows it costs a cross-unit armor motion and a scrubber
   that does not exist.
4. **A statistical layer.** See §1.3.
5. **Changing capture.** `FW-106` ruled capture (`V-3`, no design
   change). This unit is downstream of it.
6. **Cache hygiene.** `FW-130` has its own unit (`U-cachelit`, ruling on
   `Q-5`). This unit reads `cache_dir()` and deletes nothing.

### 1.3 The `G-1` boundary — the name collision, stated once *(CORRECTED-r2, gate N-3)*

`03-decisions.md` `G-1` is *"Statistical layer: corroboration counts,
reputation/outcome signals, decay clocks, quarantine machine"*, gated on
*"A second regular human user, **or** a measured recurrence (same lesson
captured >= 2x after routing), **or** >50 active routed lessons in one
host."*

**`G-1`'s "corroboration" is about LESSONS corroborating each other.
This unit's "corroboration" is about two INSTRUMENTS of one invocation
agreeing.** They share a word and nothing else. Nothing in this unit
counts, scores, ages, or quarantines a record.

**r1 measured the wrong quantities here and the gate corrected them.** r1
offered "61 route telemetry events / 139 resolved records"; 139 is a
directory count that includes 35 `superseded`, 21 `rejected` and 10
`deferred`, and the 61 needed a distinctness check. The number that
matches the trigger's own wording is the `status:` census of every record
file under `~/.self-learn`:

```
$ status: census over ~/.self-learn/**/*.md
{'routed': 83, 'superseded': 35, 'rejected': 21, 'deferred': 10, 'pending': 3}
$ telemetry kind=route: 61 events over 61 DISTINCT record ids (0 re-routes)
```

**`G-1`'s third trigger — ">50 active routed lessons in one host" — is MET
as of 2026-08-27, at 83 records with `status: routed`** (61 of them
carrying a `kind: route` telemetry event, no re-routes). **Evaluating it is
a separate design decision, not this unit's**, and `G-1`'s own row names
its precondition: *"evaluate `microsoft/SkillOpt-Sleep` first"*. This spec
proposes nothing from `G-1`'s list.

---

## 2. The corpus, measured

### 2.1 The instrument, stated once *(CORRECTED-r2, gate M-1)*

`worker.cache_dir()` (`worker.py:640`) is
`${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolved home)[:8]>/`.
For this host's live home (`~/.self-learn`, absolute path hashed) that digest is `0f24de4d`,
computed without invoking the CLI (`cache_dir()` calls `mkdir`, and
`~/.self-learn` is read-only for this unit):

```
$ python3 -c "import hashlib;print(hashlib.sha256(b'<absolute ledger home>').hexdigest()[:8])"
0f24de4d
```

Event-log filenames are `f"{surface}.tool-events.{run_id}.jsonl"`
(`invocation_sdk/events.py::_event_log_path`). Retention is
`prune_event_logs`, default 20 per surface
(`invocation_sdk/events.py::_DEFAULT_EVENT_LOGS`).

**Retention runs at session END, not START — r1 had this backwards, and it
is the measurement that decided option (iv).** `invocation_sdk/backend.py`'s
`finally:` block calls `write_event_log(...)` at **`:574`** and then
`prune_event_logs(surface)` at **`:593`**, under the shipped comment at
`:587-592`: *"``E-5``/``F-3``/``MS4`` -- retention now runs at session END,
not START: a STARTING session must never unlink a running session's
in-flight log."*

```
$ git log -S 'retention now runs at session END' --oneline --date=iso
ead58ad 2026-08-27 03:41:26 -0700 feat(sdksession): U-engine Phase 1 …
```

`ead58ad` lands **after** the newest worker event file in the corpus
(2026-08-26). So **at `50fa815` the steady state is exactly `keep` = 20**,
and today's 21 worker files are residue of the pre-`ead58ad` START ordering
which the next worker session prunes away. Under write-then-prune, a
concurrent second session on one surface also lands at <= `keep` (its file
does not exist until it ends), so r1's "one file from a false verdict …
the moment two sessions run concurrently" inference was wrong in both
halves. All counts below are over `~/.cache/self-learn/home-0f24de4d/`.

### 2.2 Per-surface census — 42 files, 128 lines, 70 tool events, 16 denials

```
surface        files   bytes  lines meta tool_events denials   oldest .. newest (mtime)
analyst           12   20952     72   12          44      16   2026-08-19T02:38 .. 2026-08-20T23:26
miner-reader       7   28132     17    7          10       0   2026-08-24T19:24 .. 2026-08-27T21:53
worker            21   32211     37   21          16       0   2026-08-18T21:00 .. 2026-08-25T22:46
worker-repair      2     318      2    2           0       0   2026-08-24T22:20 .. 2026-08-24T22:20
TOTAL             42   81613    128   42          70      16
```

Event kinds: `{'tool_use': 35, 'tool_result': 35}`. **All 35 `tool_use`
events are paired with a `tool_result`; 0 unpaired.** The pairing key is
`tool_use["id"]` == `tool_result["tool_use_id"]` *(CORRECTED-r2, gate N-1 —
r1 said "by `tool_use_id`", which read as if both sides carried that key)*.
Measured key sets: `tool_use ['id','input','kind','name','type']`,
`tool_result ['content','is_error','kind','tool_use_id','type']`. 16 of the
35 results carry `is_error: true`.

`meta` line keys (union over all 42 files):
`['cost_usd','failure','run_id','session_id','surface','turns','type']`.

**Caveat, stated because it bounds every number above:** retention 20 makes
this a ROLLING WINDOW, not the full history. `worker.log` records 46
`run: ok` lines all-time against 21 retained worker event files.

### 2.3 How much of the worker corpus is real

```
surface        session_id kind   files
analyst        real                9      none (failure before a session)   3
miner-reader   real                5      none                              2
worker         fake-session-1     16      real 2      none 3
worker-repair  none                2
```

**16 of the 21 worker event files are `SELF_LEARN_SDK_FAKE` sessions**
(`session_id == "fake-session-1"`, `cost_usd 0.001`, all 2026-08-18/19 —
the U-sdkw rehearsal). **Exactly ONE worker event file in the retained
window carries tool events at all**:
`worker.tool-events.20260826T053809Z-888755.jsonl`
(`session_id 8204916c-…`, `cost_usd 1.8074243`, `turns 9`, `failure null`).

**All 16 fake files carry zero tool events — and that is HISTORY, not HEAD**
*(CORRECTED-r3, gate B-2r2)*. r2 read those 16 files as evidence of a live
zero-event fixture mode and built `COR8`'s check on it. Measured:
`tests/fixtures/fake_claude.py:531-544` — the `shim_script` scenario
**does** emit a `tool_use`/`tool_result` pair (`writes = [op for op in ops
if op[0] == "write"]` / `if writes:` / `target = writes[0][1]` /
`toolu_shim_{n}`), under its own shipped comment *"A `tool_use`/
`tool_result` pair is still emitted (for `EventLog` realism) but never
blocks on `_request_permission`."* The 16 zero-event files are all dated
2026-08-18/19 and **predate that fixture behaviour**. They describe the
corpus, not the code. §5.1a is re-aimed accordingly and `COR8` gets a
fixture that genuinely captures zero events.

### 2.4 Denials — every one of them, and where

```
denials by (surface, source): {('analyst','charter'): 8, ('analyst','sdk-result'): 8}
distinct denied tool names (charter): {'Bash'}
```

**Zero denials on `worker`, `worker-repair`, and `miner-reader` — ever, in
the whole retained corpus.** Every denial in the product's history-on-disk
is on the **analyst**, is `Bash`, and falls inside one 13-minute window on
2026-08-21:

```
analyst run                          tool_use  charter  sdk-result   tools
20260821T061316Z-3828582                    4        1           1   Bash Bash Read Read
20260821T061506Z-3859788                    4        1           1   Bash Read ToolSearch Read
20260821T061648Z-3887903                    1        1           1   Bash
20260821T061804Z-3909179                    3        1           1   Bash ToolSearch Read
20260821T061946Z-3938683                    1        1           1   Bash
20260821T062101Z-3958461                    1        1           1   Bash
20260821T062339Z-4001581                    4        1           1   Bash Read Read ToolSearch
20260821T062555Z-4024453                    4        1           1   Bash ToolSearch Read Read
```

**8 of 8 consecutive analyst runs hit exactly one charter `Bash` denial
each.** The same denial is recorded THREE times per run: once as
`{"source":"charter","tool":"Bash","reason":"self-learn invocation charter:
Bash is outside the permitted surface — denied by default"}`, once as
`{"source":"sdk-result","value":{…"tool_input":{"command":"find ~
-name card-sections.yaml …"}}}` (the SDK's own `permission_denials`,
carrying the full unscrubbed input), and once as the paired
`tool_result`'s `is_error` content, which is the charter's deny message
verbatim.

**Why the writing surfaces show zero — capture is uniform, so the zero is
real** *(NEW in r2, from the gate's own answer)*. Denial capture does not
vary by surface: `invocation_sdk/backend.py:213` wraps every session's
callback the same way —
`can_use_tool = sdk_policy.wrap_can_use_tool(policy.can_use_tool(), events.add_denial)`
— and `sdksession/policy.py::wrap_can_use_tool` (`:114-127`) records **every**
result whose `behavior == "deny"`. So "zero denials on the worker" means
*the charter never denied there*, not *the events were never captured
there*. **Two caveats bound that reading.** (i) 16 of the 21 worker files
are fake-CLI sessions whose forced scenario never routes a write through
`_request_permission` at all (`fake_claude.py`'s own `R2-N3` comment,
`:516-531`), so they could not have produced a denial — note this is a
different fact from "they emit no tool events", which is history rather
than HEAD (§2.3). (ii)
`invocation_sdk/charter.py:211` computes
`hatch_open = containment.default_mode is None and bool(write_globs or write_exact)`
and `:226` returns `PermissionResultAllow()` **before any deny path** when
it is open — i.e. under `SELF_LEARN_ENFORCE_SCOPE=0` on `worker` /
`worker-repair` (`invocation/contract.py:132`, `:142`:
`default_mode="default" if enforce else None`), a run records zero denials
by construction. `miner-reader`'s `default_mode` is hardcoded `"default"`
(`contract.py:150`) and the analyst's write set is empty, so neither
surface can open the hatch.

**A second finding the corpus volunteered.** Of the analyst's **22**
`tool_use` events in that window, **16 results (72.7%) are errors** — the
8 charter `Bash` denials plus **8 `Read` calls returning `File does not
exist. Note: your current working directory is ~/.self-learn.`**
The analyst was hunting for a file that is not there, was denied the tool
that would have found it, and produced its answer anyway. **None of this
reached the operator, who was sitting in front of an attended
`teach --route`.** Carried forward as **`FW-131`** (§13.3).

### 2.5 Has `FW-107`'s line ever printed? No.

```
$ grep -c "charter denial" ~/.cache/self-learn/home-0f24de4d/worker.log
0                                    # rc=1
$ grep -c "^" …/worker.log           # positive control: the file is readable
168
$ grep -o "run: [A-Za-z]*" …/worker.log | sort | uniq -c
      4 run:        2 run: claude   1 run: failed   2 run: FAILED
      3 run: follow 6 run: idle    20 run: invalid  46 run: ok
     18 run: repair 9 run: stage
$ grep -n FAILED …/worker.log
66:2026-08-09T00:44:52Z run: FAILED — 15 eligible, 0 valid proposals (…)
121:2026-08-19T02:19:19Z run: FAILED — 10 eligible, 0 valid proposals (…)
```

Two FAILED runs all-time. The first predates the SDK worker; the second
recorded no denials. **The product's only shipped consumer of `denials`
has never fired outside its own tests.** The `grep -c` above is reported
with its own positive control because a zero from a missing file and a
zero from a clean file are the same output.

### 2.6 The one available agreement datapoint — and it agrees

The single real worker run with tool events wrote **8** `Write`
`tool_use` events, all paired with non-error results, all with
`file_path` under `worker.stage_dir()`, **at 8 distinct paths**:

```
worker run 20260826T053809Z-888755: write-family tool_use inside stage_dir = 8; outside = 0
                                    DISTINCT resolved paths inside = 8
```

`worker.log` for the same run:

```
2026-08-26T05:46:25Z run: stage — 8 file(s) written by the model
```

**8 = 8.** N=1, and it agrees under both the event count and the
distinct-path count — which is why `M-2`'s correction leaves this anchor
untouched. The miner-reader's newest file (the first run under
`self-learn serve`, `20260828T045339Z-1220895000000000`) shows the same
shape at N=1: one `Write` to `…/miner/spool/mine-output.json`, non-error.

Write-family census across the whole corpus:
`{('miner-reader','ok'): 5, ('worker','ok'): 8}` — **13 accepted writes,
0 errored writes, 0 writes outside the granted root, ever.** All five
miner-reader writes are to the SAME path (one per run), which is the
corpus fact that makes `M-2`'s distinct-path rule load-bearing rather than
cosmetic.

### 2.7 What the corpus holds that must never be surfaced unscrubbed

```
$ scan.scan() over all 42 files: 81613 bytes, 0.0057 s, 0 hits
$ occurrences of the literal user home path, by surface
  {'analyst': 39, 'miner-reader': 10, 'worker': 16, 'worker-repair': 0}   total 65
$ lines containing it, by line type
  {'tool_event/tool_use': 31, 'tool_event/tool_result': 22, 'denial/sdk-result': 8}
$ largest single event line: 16200 bytes (miner-reader.tool-events.20260825T022048Z-694390.jsonl)
```

**This is the measurement that decides §5.2.** `scan.scan()`
(`scan.py`, the *only* scrubber in the product — secrets: PEM headers,
`AKIA`, `ghp_`, `xox`-, JWT, credential assignments, high-entropy
base64/hex) returns **0 hits on the entire corpus** while **65
occurrences of the user's home path** sit inside it, on 61 lines, plus
whole proposal bodies embedded verbatim in `Write` inputs (the 16 200-byte
line is one). Running `scan.scan()` at a surfacing boundary would be a
**green light on exactly the content `FW-106` named** — *"file paths
today, whatever a future tool's input carries tomorrow"*. The existing
scrub is a **negative control here, not a solution.**

### 2.8 Retention, and one adjacent finding that is now its own unit *(CORRECTED-r2, gate M-1)*

Retention's steady state at `50fa815` is **`keep` = 20**, not `keep + 1`
(§2.1). The live `worker` surface holds **21**, which is a **true residue**
of the pre-`ead58ad` ordering — the next worker session's end-of-session
prune removes one. A hypothetical `> keep` doctor reading today would
therefore be *correct*, not a false positive; §5.4 no longer rests on that
inference.

Adjacent, measured, and **out of scope with a named owner** — recorded
because it is the directory this unit reads:

```
$ ls -d ~/.cache/self-learn/home-* | wc -l
31269
$ du -sh ~/.cache/self-learn
1.1G    ~/.cache/self-learn
$ find ~/.cache/self-learn -maxdepth 2 -name '*.tool-events.*.jsonl' -printf '%h\n' | sort -u | wc -l
2
```

**31 269 per-home cache namespaces, 1.1 GB**, of which **two** contain any
event log. A sample stray namespace holds `miner/{miner.log, cursors.json,
journal.jsonl, *.lock, miner.last-run}` at ~36 KB — test litter: every
suite run whose `SELF_LEARN_HOME` is a fresh `tmp_path` and whose
`XDG_CACHE_HOME` is *not* redirected makes `cache_dir()` `mkdir` a new
namespace under the operator's real cache. Handed to **`U-cachelit`** via
**`FW-130`** (§13.3), per the ruling on `Q-5`. This unit deletes nothing.

---

## 3. Attribution census — what is authority today, per surface

`S-44` says *"the filesystem diff remains the authority."* `S-32` says
attribution is now **structural, not observational**. Both are true, and
the sentence "the filesystem diff" now means a different concrete thing on
each surface. Measured at `50fa815`:

| Surface | Session kind | Model's write scope | The filesystem-side instrument, by symbol | A real before/after diff? |
|---|---|---|---|---|
| `worker` (round 1) | `invocation.write_session` (`worker.py:3108`) | the stage only — `stage_permission_rules` returns exactly `[f"Edit(/{stage_dir()}/**)"]` (`worker.py:902`), which is **recursive** | `staged_paths()` (`worker.py:887-895`, `ST-b`) — a **deliberately FLAT** `iterdir()` listing of `cache_dir()/worker.stage/`, logged as `run: stage — N file(s) written by the model` (`worker.py:3205`). Its flatness is doctrine (`ST-f`: *"a staged file in a subdirectory is litter"*) and pinned behaviour (`UN1`/`test_h3`), so it must **never** be made recursive — the grant and the census disagree on nesting BY DESIGN, and §6.3's parent-of-stage rule is how the corroborator matches the census rather than the grant *(CORRECTED-r4, gate M-1r3)* | **No.** The stage is emptied by `stage_reset` first (`ST-c`), so the listing *is* the output by construction |
| `worker` (pass 2 / `Rule-Fp`) | same | ledger `proposals/` the model never touched | `snap0 = _proposal_snapshot(home)` (`worker.py:3172`) feeding `Install-1`'s I-b | **Yes** — a genuine before-snapshot |
| `worker` under `SELF_LEARN_STAGE=0` | same | today's shared scope | `_written_since(home, snap0)` (`worker.py:3210`) | **Yes** — the original diff, still live on this leg only |
| `worker-repair` | `write_session`, `write_exact` per eligible path | exactly the round-1 paths being repaired | `touched2` (`worker.py:3305-3316`) — paths in `staged1` whose bytes differ from `snap1_stage` | **Yes** — a real before/after over the stage |
| `miner-reader` | `write_session` (`miner.py:770`) | the spool — `write_globs=(f"{spool_dir}/**",)` (`contract.py:147`) | **a before/after snapshot of `spool_dir()`, recursive, taken at the `out_path` unlink (`miner.py:751`) and again after the session** *(CORRECTED-r3, gates M-1r2/N-5r2; r2 said "every file, read before the sweep", which counted files the model never wrote — see §3.0)*; the sweep at `miner.py:774-777` then deletes anything not `mine-output.json`, and `out_path.is_file()` decides the return | **Yes** — the snapshot pair IS a real before/after diff, the only one on this surface |
| `analyst` | `invocation.**text_session**` (`analyst.py:239`) | **none** — no write tools granted; `ANALYST_ALLOWED_TOOLS` only | **none** — the output is `outcome.stdout`, parsed by `_parse_yaml_map` | **N/A** |

### 3.0 The reader's filesystem census, corrected TWICE *(CORRECTED-r3, gates M-1r2 and N-5r2; supersedes r2's `B-2` fold)*

**r1's version, and why it was dead.** r1 compared the reader's event
census against `1 if out_path.is_file() else 0` and required the
comparison to happen *after* the stray sweep. That clause is a **no-op**:
`miner.py:774-777` (`:773` is the `# Artifact contract:` comment — the
range r2 printed was off by one) is

```python
for path in spool_dir().iterdir():
    if path.name != OUTPUT_BASENAME and path.is_file():
        log(f"run: stray spool artifact {path.name} deleted")
        path.unlink(missing_ok=True)
```

The sweep can never touch `out_path = spool_dir()/OUTPUT_BASENAME`, so
`1 if out_path.is_file() else 0` is bit-identical before and after it, and
r1's mutation could not fire on any fixture.

**r2's version, and why it was worse.** r2 replaced it with *"every file in
`spool_dir()`, counted BEFORE the sweep"*, on the reasoning that a model
writing `mine-output.json` plus two strays wrote three files. **That
counts files the model did not write**, and it is not hypothetical:

- `tests/test_reader_contract.py:869::test_sw3_sweep_deletes_strays_survives_artifact_exact_log_lines`
  plants **two strays into the spool itself, before the run**
  (`stray1.write_text("a")`, `stray2.write_text("b")`), while the reader
  scenario emits exactly ONE accepted `Write` to `mine-output.json`.
  Pre-sweep census 3 vs `len(inside)` 1 → **MISMATCH on a passing test**,
  and `COR7` would have had to *assert that line* to make its mutation
  fire. r2 pinned a false alarm as required behaviour.
- The residue path is live, not theoretical: `_invoke_reader` unlinks
  **only** `out_path`, at `miner.py:751`, and returns **before** the sweep
  whenever `outcome.failure in {"timeout","not-found","os-error",
  "unavailable"}` — the guard is `:771` and the `return None` is `:772`
  *(CORRECTED-r4, gate N-1r3 — r3 cited `:770-771`; `:770` is
  `outcome = invocation.write_session(spec)`)*. Nothing else resets the spool — the only
  `spool_dir()` call sites in the module are `:569` (the definition),
  `:750`, `:764`, `:774` and `:1924`. The retained corpus holds two such
  early-return runs (`miner-reader…20260825T052010Z` `failure:
  "not-found"`, `…20260825T052017Z` `failure: "timeout"`), so a stray
  surviving into a LATER run's census is a path the product has taken.

**r3's version — a before/after snapshot, and it is a real diff.** Take a
listing of `spool_dir()` at `miner.py:751`, immediately after
`out_path.unlink(missing_ok=True)` and before the session; take it again
after the session returns; the filesystem census is **`after − before`**.
Pre-existing residue is in both sets and cancels; only what this session
actually created counts. That is the honest number, and it makes the
miner-reader the one surface in §3's table with a genuine before/after
filesystem diff.

**The walk is RECURSIVE** *(gate `N-5r2`)*. `contract.py:147` grants
`write_globs=(f"{spool_dir}/**",)`, so `spool/sub/x.json` is a **permitted**
write, while `iterdir()` + `is_file()` is one level deep and the sweep
likewise skips directories — pinned by
`test_reader_contract.py:890::test_sw4_directory_in_spool_survives_the_sweep`.
An accepted nested write would otherwise count 1 event against 0 files and
fire a MISMATCH. Both snapshots use `rglob("*")` filtered to files.

`COR7` is rewritten on the snapshot, `COR9` pins the residue case, `COR10`
pins the recursion, and their mutations are re-predicted in §10.

**Three consequences that shape the whole design.**

1. **The analyst has no filesystem side at all.** There is nothing for a
   tool event to corroborate there. Whatever the analyst gets, it is not
   an agreement check — it is denial *visibility* (§5.1b).
2. **On the worker and the miner-reader the filesystem instrument is a
   LISTING of a namespace the producer owns, not a diff of the world.**
   That is `S-32` working as designed. It means the fs side can see
   everything that landed *inside the granted root* and **nothing at
   all** about a write that landed elsewhere — and a write elsewhere is
   precisely the failure `17-invocation-runbook.md` §5.4 calls *"far
   worse"*. The event stream is the only witness of that class.
3. **`snap0` and `_written_since` survive.** "The filesystem diff remains
   the authority" is not a historical sentence: `snap0` is computed on
   every run and `_written_since` is one env var away.

### 3.1 Consumer census — everything that reads them today

```
$ grep -rn "denials\|tool_events" --include=*.py src/self_learn/ \
    | grep -v "events.py"
invocation_sdk/backend.py:70,71   SdkOutcome fields (definition)
invocation_sdk/backend.py:318,319 population from EventLog
invocation_sdk/backend.py:340-342 permission_denials -> add_sdk_permission_denial
worker.py:3066,3086-3088,3109-3111  _invoke_claude's `charter_denials` accumulator
worker.py:3161-3166,3184,3291       the accumulator threaded through both rounds
worker.py:3461-3466                 the FW-107 log line
```

**`tool_events` has NO consumer, anywhere, in any form. `denials` has
exactly one — `FW-107`'s — and it reads only `source == "charter"`, only
on the `worker` surface, only when the run ends FAILED.** `sdk-result`
denials are read by nothing (deliberately: `test_u_opsfix.py::
test_fw107_sdk_result_denials_are_not_charter_denials`, gate `N-3`).

### 3.2 The burn-in gate that was supposed to read them has never run

`17-invocation-runbook.md` §5.4 states the worker gate: *"0 out-of-scope
write attempts (`Outcome.denials` empty AND filesystem diff agrees)"*,
with §5.7 directing results to `docs/specs/self-learn/fixtures/trials.md`.

```
$ grep -n "burn-in\|denial\|out-of-scope" docs/specs/self-learn/fixtures/trials.md
(no matches)
$ heading census: the file's last section is "B3 post-routing trials (§6.5, 2026-07-14)" (397 lines)
```

**`trials.md` contains no burn-in entry for any SDK surface.** The §5.4
gate is a manual procedure, described in prose, with no instrument and no
recorded execution — six days after the last surface went SDK-only. This
is the single strongest argument in this document, and it is the one §5.5
has to beat.

---

## 4. What a consumer may and may not touch — the pins, re-measured *(CORRECTED-r2, gate B-1)*

### 4.0 The blocker, and the placement ruling

r1 put the consumer in `invocation_sdk/`. It never opened
`test_invocation_sdk.py:291`:

```python
def test_pl1_package_contains_exactly_the_six_modules():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    names = {p.name for p in pkg_dir.glob("*.py")}
    assert names == {
        "__init__.py", "backend.py", "charter.py", "lifecycle.py", "events.py", "provider_env.py",
    }
```

A seventh module reddens it, and that file is
`_ARMOR_SHAS["plugins/self-learn/cli/tests/test_invocation_sdk.py"] =
22cecab…` — so r1's placement forced the exact cross-unit armor re-pin r1
itself prices as prohibitive when rejecting option (ii) in §5.2, and which
r1's own `PIN2`/`SCRUB3` forbid. That is the contradiction the gate caught.

**RULED: the module lives at top level, `src/self_learn/corroborate.py`.**
It is also the right home on the merits: the corroborator consumes
**outcomes** — an `SdkOutcome` already returned, and a filesystem census the
caller computed — and is not part of the invocation seam. `PL1` is a
statement about the seam's shape; a consumer of the seam's output does not
belong inside it. Imports become
`from .invocation_sdk.charter import W` and
`from .sdksession.toolpaths import extract_target_path`.

### 4.1 The pin census, re-run against `src/self_learn/corroborate.py`

Method: `shutil.copytree` of `src/self_learn` into a scratch temp dir
(never the worktree), a real probe `corroborate.py` written at top level
with the imports and shape §6.2 specifies, then each pin's own assertion
replicated against the copy. Output verbatim:

```
### PL1  test_pl1_package_contains_exactly_the_six_modules
   invocation_sdk names: ['__init__.py', 'backend.py', 'charter.py', 'events.py', 'lifecycle.py', 'provider_env.py']
   names == expected -> True
### PL3  test_pl3_filesystem_writes_are_enumerated_with_an_exact_count
   fs-call count in invocation_sdk/*.py -> 5 (pin asserts == 5)
   NOTE: PL3 is a root-level glob over invocation_sdk/ ONLY; a top-level module is INVISIBLE to it. probe fs-calls: []
### EV4-a  test_ev4_nothing_in_the_package_reads_a_tool_events_file
   all invocation_sdk/*.py pass the literal rule -> True
   events.py has '.glob(' -> True ; 'read_text' absent -> True
### EV4-b  test_ev4_tool_events_string_confined_to_events_module (rglob over the WHOLE tree)
   violations -> NONE
   corroborate.py 'tool-events' count -> 0
### BND4  test_bnd4_... (sdksession/)
   sdksession/events.py '.glob(' -> True ; 'read_text' absent -> True
   other sdksession modules containing '.jsonl' -> NONE
   NOTE: BND4 globs sdksession/ ONLY; a top-level module is out of its scope.
### POL2  test_pol2_library_contains_zero_tool_name_literals_positive_control
   sdksession tool-name literal hits -> 0 (pin asserts == 0)
   charter.py positive control -> 3 (pin asserts > 0)
   corroborate.py hits -> 0 (imports W, spells no tool name)
   NOTE: POL2 globs sdksession/ ONLY; a top-level module is out of its scope.
### test_lock_invariant.py walker scope
   walker root = Path(gitops.__file__).parent = src/self_learn/ ; iteration = root.glob('*.py') (ROOT-LEVEL)
   corroborate.py IS in the walker's root-level glob -> True
   invocation_sdk/*.py in the walker's glob -> False
### N-2  COR3 positive-control halves
   grep -c file_path invocation_sdk/charter.py -> 0
   grep -c file_path sdksession/toolpaths.py -> 1
   charter.py W literals present -> True
```

**Every pin passes UNEDITED at the top-level path, `PL1` included. No
`_ARMOR_SHAS` entry moves. T1 holds** — the gate's own sizing answer said
T1 holds conditional on `B-1`, and ruling (a) resolves `B-1` with no armor
motion, so nothing in the tier argument moved.

**One consequence of ruling (a) that INVERTS a guard, stated because the
ruling's wording assumed the other placement** *(see §9.5 `UN2`/`UN3` and
the disagreement note in §16)*: at top level the **lock-invariant walker
DOES see `corroborate.py`** (root-level glob over `src/self_learn/`) and
**`PL3` does NOT** (it globs `invocation_sdk/` only). Under r1's placement
it was the reverse. So the new module's own filesystem-write guard is
`test_lock_invariant.py`, not `PL3`; `PL3` stays as the criterion that this
unit adds no write *inside `invocation_sdk/`*. Both are pinned, in `UN2`
and `UN3` respectively.

### 4.2 The four pins that bound a consumer anywhere

**EV4-a — `test_invocation_sdk.py::test_ev4_nothing_in_the_package_reads_a_tool_events_file`**
(`:1883`), in an **armor-sha-pinned file**: for every `invocation_sdk/*.py`,
`"tool-events" not in src or path.name == "events.py"`; and `events.py`
must contain `.glob(` and must **not** contain `read_text`.

**EV4-b — `test_worker_contract.py::test_ev4_tool_events_string_confined_to_events_module`**
(`:1852`), NOT armor-sha-pinned, `rglob`s the whole `src/self_learn/`
tree: `invocation_sdk/events.py` unrestricted; `worker.py` **exactly one**
occurrence which must be the literal
`_EV4_FW107_PINNED_FRAGMENT = 'f"worker*.tool-events.*.jsonl in {cache_dir()}"'`;
**every other module zero** — `corroborate.py` included, since `rglob`
reaches top level.

**BND4 — `test_u_engine.py::test_bnd4_ev4_extended_to_sdksession_nothing_reads_a_log_file_back`**
(`:912`): `sdksession/events.py` has `.glob(` and no `read_text`; no other
`sdksession/*.py` contains `.jsonl`.

**`POL2`** (`test_u_engine.py::test_pol2_library_contains_zero_tool_name_literals_positive_control`)
— `sdksession/*.py` contains **zero** occurrences of the tool-name string
constants, with `invocation_sdk/charter.py` as the positive control (3
hits, measured). **A consumer that must recognise the write family
therefore cannot live in `sdksession/`** — which is why it imports
`charter.W` rather than re-spelling it.

`U-engine`'s `UN3` (*"nothing in this unit reads `tool_events` or
`denials`"*) is `U-engine`'s own discharged criterion, not a standing
prohibition. `S-44` is.

**The rule these pins add up to:** a consumer may read `tool_events` and
`denials` **in memory, off an `SdkOutcome`**, from a module that never
spells the filename convention — and may **not** open a written log.

---

## 5. Option map — each steelmanned, each decided by a measurement

### 5.1a Option (i) — an AGREEMENT CHECK after each writing run

**The design.** After the model window, compare the filesystem-side
census (§3 row by row) against a census of **distinct paths** accepted by
write events on the same `SdkOutcome`; emit a loud line when they
disagree, and a second line when the events report an accepted write
**outside** the granted root. Counts only. Never changes what lands.

**Steelman.** (a) §3.2: the §5.4 burn-in gate is prose with no
instrument and no recorded run; this makes it automatic and per-run.
(b) §3 consequence 2: an accepted write outside the granted root is
structurally invisible to every other instrument in the product — the fs
side lists only the root. (c) `FW-84`'s rule is honoured exactly: the fs
count is named first, the events never override it, and the verdict word
is "MISMATCH", not "unauthorised". (d) The cost anchor is known to the
line (§5.7).

**Against it, honestly.** Zero denials on every writing surface, ever
(§2.4). Zero writes outside a granted root, ever (§2.6). One agreement
datapoint, agreeing (§2.6). This check has never had anything to say.

**The noise mode, re-aimed at the one that exists** *(CORRECTED-r3, gates
B-2r2 and M-2r2; supersedes r2's `M-3` fold)*.

r1 claimed *"the corpus proves the check is cheap and QUIET"*. It does not,
and r2 was right to withdraw that — but r2 named the **wrong mode**. r2
asserted that `shim_script` emits no tool events. Measured, it does
(§2.3): `fake_claude.py:531-544` emits one `tool_use`/`tool_result` pair
whenever the script contains at least one write. So the zero-event
worker run is history, and `sdk_fake_worker` is not a fixture that
produces one.

**The live noise mode is the MULTI-WRITE shim, and it is worse**, because
the guard r2 built does not engage against it.
`tests/test_worker.py:531::test_run_partial_success` sets
`CLAUDE_SHIM_SCRIPT` to `f"{good}\n{bad}"` — two heredoc writes — and the
fixture **performs every write but announces only `writes[0]`**. The run
stages 2 files and reports 1 accepted write, `had_events` is True, and the
corroborator emits
`run: corroboration MISMATCH — stage has 2 file(s), model reported 1 accepted write(s)`
**on a correct, passing test**. Four more multi-write shims exist:
`test_worker.py:604` (`shim_writes` + `touch {dirty}` — **one** write op;
`touch` is a separate op in the shim parser), `:1192` (a proposal plus a
staged merge — **two**, both top-level), `:1221` (a proposal plus a
**nested** `sub/sneaky.yaml` plus a `notes.txt` — **three** write ops but
only **two** files `staged_paths()` can see), and `test_serve.py:217`
(`shim_writes` + `touch` — one). `shim_writes` itself is exactly one write
op (`test_worker.py:314-324`).

**RULED — fix the root cause, do not pin the false alarm.** The fixture's
own shipped comment says the pair exists *"for `EventLog` realism"*;
announcing one of N writes is not realism, it is a fixture bug that would
have made the corroborator look broken. `_scenario_shim_script` emits **one
`tool_use`/`tool_result` pair per write op** (§6.6). `COR11` pins the
fixture behaviour and its mutation restores the announce-only-first bug.

**The fixture fix alone is not sufficient, and r3 missed why**
*(CORRECTED-r4, gate M-1r3)*. `:1221` writes a **nested** file into the
stage, and `staged_paths()` is a deliberately flat `iterdir()`
(`worker.py:887-895`, `ST-b`/`ST-f`) — the run's own log says `run: stage —
2 file(s)`, measured, not 3. So the fixed fixture announces 3 accepted
writes against a census of 2 and the corroborator would fire **a different
false MISMATCH on the same passing test**. The asymmetry is the finding: r3
made the MINER census recursive (`COR10`, because
`write_globs=(f"{spool_dir}/**",)` permits nesting) and left the WORKER
side, whose grant `Edit(/{stage_dir()}/**)` is equally recursive while its
census is flat by doctrine. **RULED: on the worker surface, only accepted
paths whose PARENT IS EXACTLY `stage_dir()` enter the accepted-inside set**
— never make `staged_paths()` recursive, since its flatness is pinned
behaviour (`UN1`/`test_h3`) and the property `:1221`'s own name asserts. A
nested-but-inside-root write is announced and then counted in **neither**
bucket: not `inside` (the census cannot see it), not `outside` (it is not
out of scope). `COR13` pins it; §6.6's table shows all five shims landing
silent under the pair of changes.

**The zero-event case is still real, just rare — and it keeps its own
leg.** An `SdkOutcome` whose `tool_events` is empty (a session that made no
tool calls; measured in the corpus at **20 of 21** worker files and **4 of
12** analyst files — `…093829Z` `exit`, `…133124Z` `exit`, `…133137Z`
`os-error`, `…045046Z` `failure None, turns 1`; the "`failure` set or
`turns: 1`" qualifier holds for all four *(CORRECTED-r4, gate N-2r3 — r3
said 3)*) must not be read as "the model wrote nothing":

```
run: corroboration — no tool events recorded (N file(s) on disk)
```

— and no other action: no MISMATCH, no OUTSIDE line, no status change. A
session with zero captured events is not an instrument, and saying so is
more useful than a false alarm. Pinned as `COR8`, whose fixture is now a
monkeypatched `SdkOutcome(tool_events=())` rather than `sdk_fake_worker`
(`B-2r2`).

**Decided.** **ADOPT, narrow.** The measurement that decides it is §3.2,
not §2.4: a gate that has never been executed is not the same as a gate
that has been executed and found nothing.

### 5.1b Option (i-analyst) — denial VISIBILITY where there is no diff

The analyst has no filesystem side (§3 row 6) and no log sink at all —
`analyst.py:236` passes `log=lambda _msg: None` into its `SessionSpec`,
and `W-h` forbids the analyst carrying operator-visible strings of its
own. So its 8/8 charter denials and its 16-of-22 error rate (§2.4) are
invisible by construction, on the one **attended** surface.

**Decided: ADOPT — `Q-1` RULED YES** *(r2)*. §6.5 carries the wiring, and
`DEN3` carries the leg census the gate demanded (`N-7`).

### 5.2 Option (ii) — SURFACE denials/tool events into `report` or the UI

**Steelman.** The data is real and nothing shows it. `report.py` already
renders a rich text/JSON facts document (`gather`/`render_text`/
`render_json`, 2179 lines) that an operator reads regularly; the review
UI already renders per-record evidence.

**Rejected, on three measurements.**

1. **The scrub does not exist.** §2.7: the product's only scrubber returns
   **0 hits** over a corpus containing **65** occurrences of the user's
   home path and whole proposal bodies verbatim. Reusing it at the
   boundary would be a canary hashing the wrong file — loudest success in
   exactly the case it exists to catch. A real personal-literal scrub is
   NEW code with no implementation to reuse:
   `docs/specs/self-learn/drafts/scrub-personal-literals-spec.md` is a
   **source-tree de-personalisation** spec (`DEFAULT_MEMORY_DIR`, fixtures,
   README), not a runtime redactor — measured by reading it: its §1.1
   subject is `cli.py:81`. `scan.redact()` exists but redacts *secret
   spans*, of which there are none here.
2. **It breaks both EV4 pins in substance.** Surfacing past runs means
   opening written logs. EV4-a forbids `read_text` in the one module
   allowed to name them and asserts "nothing in the package reads a
   tool-events file"; EV4-b confines the literal. Letter-preserving
   workarounds exist (read via `open()`, spell the segment as a
   parameter) and are refused **by name** — the `U-opsfix` gate's `B-1`
   ruling was precisely that a pin must be narrowed honestly, never
   evaded. Doing it properly means re-pinning EV4-a **inside an
   armor-sha-pinned file** (`_ARMOR_SHAS` entry `22cecab…`), i.e. a
   cross-unit armor motion — the same motion §4.0's blocker was about, and
   the reason ruling (a) exists.
3. **The audience.** 128 event lines all-time, 35 of them tool calls, on
   one host with one operator, of which exactly one 13-minute window has
   ever been interesting.

**Owner of the eventual need:** a second consumer — `G-1` or a second
human user. Recorded as **`FW-129`** with that trigger (§13.3).

### 5.3 Option (iii) — PROVENANCE CORROBORATION in the record's decision trace

**Steelman.** `U-schema` landed the decision trace (`gates:` block,
validated by `ledger_ops.py`; `test_decision_trace.py` exists). A
`provenance:` sibling recording "the model reported writing this path"
would put corroboration where a reviewer already looks.

**Rejected, and this one is permanent.**

1. **It inverts `S-44` and re-buys `FW-84`.** The trace lives inside the
   record, in the ledger, in a git repo, pushed to a **public** remote.
   Writing the model's self-report of its own tool calls into the durable
   provenance record is the exact thing `FW-84` cost.
2. **It is the `FW-106` boundary at maximum price.** Event-derived content
   would cross from a local-only cache into a published repo — the one
   direction `FW-106`'s ruling (*"local-only, never committed, never
   synced"*) rests on.
3. **There is nothing left to corroborate.** `S-32`: a staged file is the
   model's own output **by construction**; `Install-1` proves the install.
   A self-report adds no information to a structural proof.
4. **`Schema-1` states the field set exactly once** (`u-schema` spec §0/§3.1,
   *"a schema spec that states its field set twice will drift"*), and the
   validator could not check the new field's value against anything.

### 5.4 Option (iv) — HYGIENE: retention sanity and an event-log `doctor` row *(CORRECTED-r2, gate M-1)*

**Steelman.** `FW-106`'s ruling that unscrubbed inputs may live in the
cache rests on retention actually running. A `doctor` row would watch it.

**r1's deciding measurement was wrong and is withdrawn.** r1 rejected the
row because "a row whose threshold is `keep + 1` is one file from a false
verdict". §2.1 measures the opposite: retention runs at session END since
`ead58ad`, the steady state is exactly `keep` = 20, and today's 21 is a
**true residue** the next session clears. A `> keep` row would have been
*correct* today, not false. **The rejection therefore has to stand on other
grounds, or not at all.**

**Rejected anyway — `Q-2` RULED NO — on three grounds that survive:**

1. **Ownership.** Cache hygiene now has a unit: `U-cachelit` owns `FW-130`
   (ruling on `Q-5`). A retention row here would split one concern across
   two units, and the 1.1 GB finding (§2.8) dwarfs the 81 613-byte one this
   row would watch.
2. **Scale.** The whole event corpus is **81 613 bytes in 42 files**. There
   is no runaway to watch, and an `INFO` row reports what `ls` reports.
3. **Verdict semantics.** The only defensible verdict for a stale prune is
   `WARN`, never `FAIL` (§12) — because `FW-106` ruled the exposure
   acceptable precisely on the ground that these files are local-only,
   never committed, never synced. A row that can only ever `WARN` about a
   condition another unit owns is not worth a `DOCTOR_ROWS` slot that two
   sibling units may also be contending for this cycle (§14).

### 5.5 Option (v) — NOTHING beyond `FW-107`

**Steelman, and it is strong.** Zero denials on the writing surfaces
ever; zero out-of-root writes ever; the one agreement datapoint agrees;
the corpus is 128 lines. On value-per-line, "nothing" wins outright, and
`S-44` could be closed today with a dated amendment saying the consumer
turned out to be one line.

**What defeats it.** §2.5 and §3.2 together: `FW-107`'s line **has never
printed**, and the burn-in gate that was supposed to read `denials` **has
never been recorded as run at all**. Closing `S-44`'s consumer clause on
that basis would be closing it on *never measured*, not on *measured and
found unnecessary* — and it would leave the one failure class the
filesystem instrument structurally cannot see (§3 consequence 2) with no
witness in the product.

**Decided.** REJECTED as the whole answer; **kept as the runner-up**, so a
gate that reads the same evidence and weighs §2.4 above §3.2 can rule the
other way without re-measuring. If it does, §13.2 gives the `S-44`
amendment text for that outcome.

### 5.6 Designs rejected, with the measurement that rejected each

| # | Rejected | The measurement |
|---|---|---|
| R-a | Read a written event log back, anywhere | §4.2 — EV4-a's `read_text` ban inside an armor-sha-pinned file; §5.2 point 2 |
| R-b | Reuse `scan.scan()` as the surfacing scrub | §2.7 — 0 hits over a corpus holding 65 home-path occurrences |
| R-c | An event-derived field in the decision trace | §5.3 — `S-44` inverted, `FW-106` boundary crossed into a public repo, `S-32` makes it redundant |
| R-d | A `doctor` events/retention row *(CORRECTED-r2, gate M-1)* | §5.4 — **not** r1's knife-edge (that inference was wrong): ownership (`U-cachelit`/`FW-130`), 81 613 bytes total, and a row that can only ever `WARN` |
| R-e | A `report` section over event logs | §5.2 point 3 — 128 lines all-time; and `report.py` reads only the ledger today, never `cache_dir()` |
| R-f | Put the consumer in `sdksession/` | §4.2 `POL2` — that package may contain zero tool-name literals; a write-family census needs them |
| R-g | Put the consumer in `invocation_sdk/` *(NEW in r2, gate B-1)* | §4.0 — `test_pl1_package_contains_exactly_the_six_modules` reddens; that file is armor-sha-pinned, so the move costs the very re-pin §5.2 pt 2 prices as prohibitive |
| R-h | Fold the new accumulator into `FW-107`'s `charter_denials` | `test_u_opsfix.py::test_fw107_sdk_result_denials_are_not_charter_denials:275` calls `_invoke_claude(..., charter_denials=…)` directly; folding edits a pinned contract for no gain |
| R-i | A corroboration leg on the REPAIR round | §5.8 |
| R-j | A new telemetry event kind for run outcomes | Measured: telemetry carries `capture/route/fire/surface-budget/recurrence-suspect` only — no run-outcome kind exists, and `u-dismiss` §4.1 already ruled against adding one for an adjacent case |
| R-k | Naming the event-log glob in the new lines | §7 — it would put a SECOND `tool-events` literal in `worker.py` and redden EV4-b |
| R-l | Counting accepted write EVENTS rather than distinct paths *(NEW in r2, gate M-2)* | §6.2 — a `Write` then `Edit` on one staged file is two events for one file in `staged_paths()`; all five miner-reader writes in the corpus target the SAME path |
| R-m | A flat pre-sweep listing of `spool_dir()` as the reader's census *(NEW in r3, gate M-1r2)* | §3.0 — `test_sw3` plants two strays before the run and the reader emits one accepted write: census 3 vs 1, a MISMATCH on a passing test. Residue also survives the `:771-772` early return, which the corpus took twice |
| R-o | Making `staged_paths()` recursive so the worker census matches the grant *(NEW in r4, gate M-1r3)* | §6.2 — its flatness is doctrine (`ST-f`) and pinned behaviour (`UN1`/`test_h3`), and `test_worker.py:1221`'s own name and comments assert that a nested staged write is structurally unreachable. The corroborator adapts to the census; the census does not adapt to the corroborator |
| R-n | Pinning the multi-write false alarm in the fixtures instead of fixing the fixture *(NEW in r3, gate M-2r2)* | §6.6 — the alternative is asserting a `corroboration MISMATCH` line inside five passing tests that are not about corroboration; the fixture's own comment says the pair exists "for `EventLog` realism", and the fix is line-neutral and moves no armor pin (measured) |

### 5.7 RECOMMENDATION and SIZE TIER

**Build the in-memory corroborator at `src/self_learn/corroborate.py`,
wired to the two writing surfaces that have a log sink (`worker` round 1,
`miner-reader`) and to the analyst's denial channel, emitting COUNTS ONLY.
Read no file back. Add no verb, no doctor row, no ledger field, no UI.**

**Size tier: T1 — one blind Opus code gate, no spec gate.** The estimate
is derived from the exact analogue, `FW-107`. **The numstat below is the
FW-107/FW-108 rows of `2bff722..1b7148c` — 5 of that diff's 13 rows**
*(CORRECTED-r2, gate D-2; the other eight are `miner.py 2/19`,
`scripts/suite 0/55`, `tests/test_u_fw100.py 0/138`,
`tests/test_dismiss_suspect.py 60/0` and three doc rows, none of them
FW-107's)*:

```
$ git diff --numstat 2bff722 1b7148c   (5 of 13 rows — the FW-107/FW-108 change)
45   2   cli/src/self_learn/worker.py          <- FW-107: accumulator + threading + line
 6   1   cli/src/self_learn/invocation_sdk/backend.py   <- FW-108
 5   0   cli/src/self_learn/verbs.py
280  0   cli/tests/test_u_opsfix.py            (5 tests: 3 FW-107, 2 FW-108)
84  14   cli/tests/test_worker_contract.py
```

`U-opsfix` shipped **three** findings for **56** added product lines across
three files through **one** blind code gate. U-corrob's product, item by
item, against that anchor:

| Item | Estimate | Anchor |
|---|---|---|
| `src/self_learn/corroborate.py` (new: `RunEvidence`, `observe`, the distinct-path census) | ~70 | `charter.py`'s `_split_trusted_prefix`+`_check_supported` region; `sdksession/toolpaths.py` is 30 lines with docstring |
| `worker.py` — second accumulator, threading, three lines | ~38 | `FW-107` = 45/2 for a comparable change |
| `miner.py` — evidence + mismatch + no-evidence + denial lines | ~28 | `_invoke_reader` already binds `outcome` and already logs |
| `analyst.py` + `teach.py` — accumulator + the print on BOTH branches | ~25 | same accumulator shape |
| `tests/fixtures/fake_claude.py` — one pair per write op (§6.6) | **14 lines → 7, net −7** *(MEASURED, A-8/A-10)* | the block at `:531-544` |
| Docs (`03`, `14`, `17`) | ~45 | §13 |
| **Product total** | **~161 added, ~2 removed, 4 source files + 1 new module** (the fixture edit is test-side, and net −7) | |
| `cli/tests/test_u_corrob.py` (new) | ~360 | `test_u_opsfix.py` = 280 for 5 tests |

**T1 holds.** The gate's independent sizing answer said so conditional on
`B-1`; ruling (a) resolves `B-1` with **no armor motion and no pin edit**
(§4.1), so nothing in the tier argument moved. The two honest
counter-arguments, stated so the gate can rule: it touches `worker.py`
concurrently with two siblings (§14), and it is ~161 product lines against
`U-opsfix`'s 56.

### 5.8 The repair round is OUT, and why

`worker-repair` has the narrowest write scope in the product
(`write_exact` per eligible path) and a genuine before/after filesystem
instrument (`touched2`, §3 row 4) — it looks like the best corroboration
site in the codebase. It is excluded on two measurements:

1. **A known false-mismatch mode.** `touched2` counts paths whose *bytes
   changed*. A repair that rewrites a file with identical content is an
   accepted write on the event side and **zero** on the filesystem side.
   The line would fire on a correct run.
2. **Zero evidence.** `worker-repair` has 2 event files in the corpus,
   both `failure` (`not-found`, `timeout`), **0 tool events** (§2.2).
   Nothing has ever been observed on this surface to design against.

`FW-107`'s existing `charter_denials` accumulator already spans both
rounds and is untouched by this exclusion.

---

## 6. The design

### 6.1 The one rule that makes everything else safe

**No file is ever read back. Every input to this unit is an
`SdkOutcome` field already in memory at the call site, or a filesystem
census the caller already computes.** This is what keeps EV4-a, EV4-b,
BND4, `PL1`, `PL3` and `POL2` green *unedited* (§4.1), and it is what makes
the `FW-106` obligation dischargeable by construction rather than by a
scrubber that does not exist (§8).

### 6.2 `src/self_learn/corroborate.py` — the new module *(CORRECTED-r2, gates B-1, M-2)*

Top level, not `invocation_sdk/` (§4.0). It consumes outcomes; it is not
part of the seam.

```
RunEvidence(root: Path, *, flat: bool)  # caller constructs with its granted root; worker flat=True, reader flat=False
  .seen: bool                           # an outcome was observed at all
  .failure: str | None                  # the last observed outcome's failure
  .events_present: bool                 # the outcome HAS a `tool_events` attribute
  .had_events: bool                     # that attribute held >= 1 event
  .inside: set[str]                     # DISTINCT resolved accepted paths under root
  .outside: set[str]                    # DISTINCT resolved accepted paths elsewhere
  .unresolved: int                      # write-family tool_use with no paired result
  .observe(outcome) -> None             # never raises; tolerates a bare Outcome
  .verdict(fs_count: int) -> str | None # the one line to log, or None
```

**Two flags, not one** *(CORRECTED-r3, gate B-1r2)*. r2 defined a single
`.had_events` and keyed emission on it alone, which made `COR6` ("a bare
`Outcome` emits nothing") and `COR8` ("zero tool events emits the
no-evidence line") demand opposite behaviour on the same input — a bare
`Outcome` with `failure is None` satisfied both antecedents, and no
implementation could turn both green. The discriminator is therefore
**two** facts, because they are two different situations:

| Outcome shape | `events_present` | `had_events` | Emission |
|---|---|---|---|
| a bare `Outcome` — no `tool_events` attribute at all (the `cli`-era shape, and every hand-built stand-in) | `False` | `False` | **nothing** (`COR6`) — the backend did not capture, so there is no instrument and nothing to say about one |
| an `SdkOutcome` whose `tool_events` is `()` | `True` | `False` | **the NO-EVIDENCE line** (`COR8`) — the instrument ran and recorded nothing |
| an `SdkOutcome` with >= 1 event | `True` | `True` | MISMATCH / OUTSIDE per §6.3 rule 3 |

`observe` sets `events_present` from `hasattr(outcome, "tool_events")` and
never from truthiness — the two must not collapse, which is the whole
finding.

- **Write family:** imported from `charter.W`
  (`frozenset({"Write","Edit","NotebookEdit"})`, `charter.py:38`) — **not**
  re-spelled. One definition.
- **Target path:** `sdksession.toolpaths.extract_target_path`, the SAME
  function both charters use to decide (`charter.py` imports it as
  `_extract_target_path`). The corroborator and the policy therefore agree
  on "which key names the path" by construction.
- **Pairing key** *(CORRECTED-r2, gate N-1)*: a `tool_use` is paired with
  the `tool_result` whose `tool_use_id` equals the `tool_use`'s **`id`**.
  The two sides do not share a key name; a literal reading of r1's wording
  would have classified every write as unresolved.
- **ACCEPTED** = a write-family `tool_use` whose paired `tool_result`
  exists and has `is_error` falsy. **UNRESOLVED** = no paired result.
  Basis: §2.2 — 35/35 paired, 16 errored, and the erroring ones are
  exactly the denied/failed calls (§2.4).
- **Counted as DISTINCT RESOLVED PATHS, never as events** *(CORRECTED-r2,
  gate M-2)*. `.inside`/`.outside` are **sets** keyed on the target path
  resolved against `root`. The reason is measured, not hypothetical: the
  worker's grant is `[f"Edit(/{stage_dir()}/**)"]` (`worker.py:902`) over a
  write family that includes both `Write` and `Edit`, so a model that
  writes then edits ONE staged file emits two accepted events for one file
  in `staged_paths()` — a flat listing (`worker.py:887`). r1's event count
  would have fired a MISMATCH on that correct run, which is exactly the
  class §5.8 uses to exclude `worker-repair`. The corpus cannot rule it
  out: all five miner-reader writes target the SAME path, and the only
  multi-write run is N=1 with 8 distinct paths (§2.6), so the 8-vs-8 anchor
  is identical under both rules.
- **Resolution discipline:** the root is resolved ONCE at construction;
  the event's own path string is resolved against it without following its
  final segment — the charter's `P-b` rule (resolve the trusted prefix,
  never the leaf, because the leaf is where a planted symlink rebases the
  expectation).
- **The "inside" predicate is PER SURFACE, and it mirrors that surface's
  filesystem census — not its grant** *(NEW in r4, gate M-1r3)*.
  `RunEvidence(root, *, flat: bool)`:
  - **`flat=True` (the worker):** a path counts as inside iff **its parent
    is exactly `root`**. `staged_paths()` is a flat `iterdir()`
    (`worker.py:887-895`) by doctrine — `ST-f`, *"a staged file in a
    subdirectory is litter"* — and by pinned behaviour (`UN1`/`test_h3`),
    even though the grant `Edit(/{stage_dir()}/**)` is recursive. Matching
    the grant instead of the census is what would fire a MISMATCH on
    `test_worker.py:1221` (§6.6).
  - **`flat=False` (the miner-reader):** a path counts as inside iff it is
    under `root` at any depth, matching the recursive `rglob` census
    §6.4 takes and the equally recursive `{spool_dir}/**` grant.
  - **A nested-but-inside-root write on a `flat=True` surface lands in
    NEITHER set** — not `inside` (the census cannot see it), not `outside`
    (it is not out of scope). It is announced by the model, invisible to
    the filesystem instrument, and therefore not corroborable in either
    direction; the honest answer is to count it nowhere rather than to
    manufacture a disagreement. `ST-f` already calls such a file inert
    litter that the next `stage_reset` clears.
- Import-bounded: **stdlib + `.invocation_sdk.charter` +
  `.sdksession.toolpaths`** only. No `.worker`, no `.miner`, no
  `.invocation_sdk.events`, no `self_learn_ui`.

### 6.3 `worker.py` — round 1

A second keyword-only accumulator on `_invoke_claude`, exactly parallel to
`FW-107`'s and leaving it byte-unchanged (§5.6 R-h):

```
_invoke_claude(..., charter_denials=…, evidence: corroborate.RunEvidence | None = None)
    …
    outcome = invocation.write_session(spec)
    if charter_denials is not None:            # FW-107, byte-unchanged
        …
    if evidence is not None:
        evidence.observe(outcome)
```

`_invoke_claude` still has no `return` statement (`test_invocation.py::
test_wr1_invoke_claude_signature_and_never_raises`, armor-pinned file).

In `run()`, round 1 only, immediately after
`log(f"run: stage — {len(staged1)} file(s) written by the model")`, the
evidence yields **at most one of these two verdict lines**:

```
run: corroboration — no tool events recorded ({fs} file(s) on disk)
run: corroboration MISMATCH — stage has {fs} file(s), model reported {ev} accepted write(s) (filesystem is authority)
```

plus, independently of both:

```
run: {n} accepted write(s) reported OUTSIDE the stage (filesystem is authority; see the event log in {cache_dir()})
```

**Every line takes the `run:` prefix** *(CORRECTED-r3, gate N-2r2 — r2's
no-evidence line began `corroboration:` and broke the log's convention)*.
Measured over the live `worker.log`, every one of its 168 lines starts with
one of four class tokens: **`run:` 84** (timestamped) + **27** more on the
bare `worker run: …` summary line the spawner prints, **`window` 46**,
**`escalation:` 11**. No test forces the wording — `test_h3`, `test_h4`,
`test_sw3` and `test_cp2` all assert by substring — so this is consistency,
not a break; `COR12` pins it so it stays that way.

**The three emission rules, each a criterion.**

1. **Nothing at all** unless `evidence.seen and evidence.failure is None`.
   A timed-out or failed session's accounting is known-incomplete: a write
   can land while its `tool_result` never arrives, so a mismatch on a
   failure is expected, and a line that fires on every timeout trains the
   operator to ignore it. This is orthogonal to `FW-107`'s trigger, which
   is `result.status == "failed"` (a self-learn verdict), not
   `outcome.failure` (a transport verdict) — the two lines can co-fire and
   that is correct.
2. **`events_present` is False ⇒ nothing** (`COR6`); **`events_present` and
   not `had_events` ⇒ the NO-EVIDENCE line and nothing else** (`COR8`)
   *(CORRECTED-r3, gate B-1r2 — r2 keyed this rule on `had_events` alone,
   which contradicted `COR6`)*. No MISMATCH, no OUTSIDE line in either
   case. §6.2's table is the discriminator; §5.1a has the re-aimed
   measurement.
3. **Otherwise** the MISMATCH line iff `len(evidence.inside) != len(staged1)`,
   and the OUTSIDE line iff `evidence.outside` is non-empty — the two are
   independent, so an outside write that exactly offsets a missing inside
   one must not cancel out. **`evidence.inside` on this surface holds only
   paths whose parent is exactly `stage_dir()`** (§6.2's `flat=True`
   predicate, `COR13`) — the corroborator matches `staged_paths()`'s flat
   census, never the recursive grant *(CORRECTED-r4, gate M-1r3)*.

**Counts only.** No path, no content, no tool input (§8). The pointer says
`the event log in {cache_dir()}` and **not** the glob — see §7 R-k. Note
the near-miss trap explicitly: the string `"tool-event log"` would pass
EV4-b (no trailing `s`) and is exactly the kind of cleverness the `B-1`
ruling refuses; do not write it.

### 6.4 `miner.py` — the reader *(CORRECTED-r2, gate B-2)*

`_invoke_reader` already binds `outcome` (`miner.py:770`) and already
logs. One `RunEvidence(root=spool_dir(), flat=False)`, observed on that outcome.

**The filesystem census is a before/after snapshot pair, recursive**
*(CORRECTED-r3, gates M-1r2 and N-5r2 — §3.0 has the full derivation)*:

```python
before = {p for p in spool_dir().rglob("*") if p.is_file()}   # at :751, right after out_path.unlink
...
outcome = invocation.write_session(spec)
after  = {p for p in spool_dir().rglob("*") if p.is_file()}   # before the early return and the sweep
fs_count = len(after - before)
```

`before` is taken at `miner.py:751` so pre-existing residue cancels;
`rglob` so a nested write the charter permits
(`write_globs=(f"{spool_dir}/**",)`) is counted rather than missed. The
same three emission rules as §6.3 apply, with:

```
run: corroboration — no tool events recorded ({fs} artifact(s) in the spool)
run: corroboration MISMATCH — spool has {fs} artifact(s), model reported {ev} accepted write(s) (filesystem is authority)
```

**Plus the `FW-107` pattern, extended.** The miner-reader has no FAILED
line of its own, so a fully-denied reader run is today indistinguishable
from a run that wrote nothing — the identical defect `FW-107` fixed for
the worker:

```
run: {n} charter denial(s) this run ({tools}) — see the event log in {cache_dir()}
```

`{tools}` is the sorted distinct set of denied tool NAMES. A tool name is
policy vocabulary (it appears in the charter's own deny message), not a
tool input — §8 draws that line explicitly.

### 6.5 `analyst.py` + `teach.py` — `Q-1` RULED YES *(CORRECTED-r2, gate N-7)*

`analyze()` gains one keyword-only accumulator (`FW-107` shape: omitting
it preserves today's contract byte-for-byte).

**Measured leg census, because r1 asserted an unmeasured one.** `analyze()`
contains **10 `raise AnalystError` statements** (`analyst.py` lines 177,
189, 246, 249, 259, 261, 264, 303, 309, 322), of which **5 are the
`outcome.failure` legs** (`not-found` `:244`, `timeout` `:247`, `exit`
`:252`, `unavailable` `:260`, `os-error` `:262`). Every one of them
**raises**; none returns.

**Therefore the print must be wired to BOTH branches of `teach.py`'s
`try`.** Measured at `teach.py:683-692`: the call sits inside
`try: proposal = analyst.analyze(...)` whose
`except analyst.AnalystError as exc:` **returns** `_capture_to_pending(...)`
immediately. A fully-denied analyst run is the case most likely to carry
denials AND to raise, so a print on the success branch alone would miss
exactly the run it exists for. The accumulator is caller-owned and is
populated by `analyze()` **before** it raises, so both branches can read
it:

```
teach: analyst hit {n} charter denial(s) this run ({tools}) — see the event log in {cache_dir()}
```

The print lives in `teach.py`, not `analyst.py`, because `W-h` requires
every analyst-path operator string to render through
`invocation.LOG_TEMPLATES["analyst"]` and this is not one of those legs.

### 6.6 `tests/fixtures/fake_claude.py` — one pair per write op *(NEW in r3, gate M-2r2)*

**This is the root-cause fix for §5.1a's live noise mode, and it is
test-side only.** `_scenario_shim_script` performs every write op but
announces only the first (`:531-544`). The edit makes the announcement
match the behaviour:

```python
    writes = [op for op in ops if op[0] == "write"]
    for i, write_op in enumerate(writes, 1):
        target = write_op[1]
        tool_use_id = f"toolu_shim_{n}_{i}"
        emit(assistant_message("", f"u1-{i}", content=[
            {"type": "tool_use", "id": tool_use_id, "name": "Write", "input": {"file_path": target}}]))
        emit(user_tool_result(tool_use_id, f"u2-{i}", content="ok", is_error=False))
```

**The block above is NORMATIVE, and it is net −7 lines, not net zero**
*(CORRECTED-r4, gate M-2r3 — r3 said "six lines rewritten, net zero", which
described a different, line-count-preserving spelling of the same change)*.
It replaces the current 14-line block with 7. It matches the fixture's own
stated intent — the shipped comment says the pair is emitted *"for
`EventLog` realism"* — and it leaves the `R2-N3` bypass untouched: writes
still never route through `_request_permission`, so no charter test changes
behaviour.

**Why the spelling is normative rather than cosmetic: a numstat bound.**
`test_u_sdka.py::test_hy5_numstat_bounds_hold` (`:1994`, `:1999-2021`) caps
this file at `(388, 1)` insertions/deletions, measured **single-ref**
`git diff --numstat 442385d -- <path>` against the working tree, with
`ins -= 2` for the two `SCENARIOS` lines (`:2018-2019`). Measured, all four
variants against that check:

| variant | ins | del | `ins-2` vs cap 388 | lines vs today |
|---|---|---|---|---|
| unedited (control) | 390 | 1 | **388 — exactly at the cap** | +0 |
| **the printed 7-line block** | **383** | **1** | **381 — GREEN, 7 under** | **−7** |
| printed block + the 2-line justification comment | 385 | 1 | 383 — GREEN, 5 under | −5 |
| line-count-preserving 14-line spelling | 390 | 1 | 388 — at the cap; **RED the moment any comment is added** | +0 |

The live tracked command reproduces the control exactly
(`git diff --numstat 442385d -- …/fake_claude.py` → `390 1`), and a
`--no-index` diff of base-vs-working-file returns the same `390 1`, which is
the positive control for the three synthetic variants. **`fake_claude.py`
sits at its cap today**, so any net growth of it by this unit reddens
`test_hy5`; the printed block is the spelling that buys headroom instead of
spending it, and it makes the justification comment affordable. §14 lists
`test_u_sdka.py` as read-only for this unit, so widening the bound is
forbidden by this spec's own hard constraint — the edit has to fit under it.

**Effect on the five multi-write shims**, each of which becomes an AGREEING
run — but only because §6.3's parent-of-stage rule (`COR13`) lands with it
*(CORRECTED-r4, gate M-1r3; r3's table asserted "`:1221` → 3 vs 3", which
the run's own `run: stage — 2 file(s)` line contradicts)*:

| shim | write ops | announced post-fix | accepted-inside (parent == stage) | `staged_paths()` | verdict |
|---|---|---|---|---|---|
| `test_worker.py:531` `test_run_partial_success` | 2, both top-level | 2 | 2 | 2 | silent |
| `:1192` (proposal + staged merge) | 2, both top-level | 2 | 2 | 2 | silent |
| `:1221` `test_unexpected_artifacts_deleted_never_published` | 3 — proposal, `sub/sneaky.yaml` (**nested**), `notes.txt` | 3 | **2** | **2** (measured) | silent **via the parent rule**; without it, 3 vs 2 → false MISMATCH |
| `:604` (proposal + `touch`) | 1 (`touch` is a separate op) | 1 | 1 | 1 | silent |
| `test_serve.py:217` (proposal + `touch`) | 1 | 1 | 1 | 1 | silent |

**No armor pin moves — MEASURED, and this corrects the ruling's premise**
*(disagreement, §16)*. The ruling directed me to "prescribe the re-pin with
its dated one-line justification". There is nothing to re-pin. Replicating
all four legs of `test_worker_contract.py::test_su4b_fake_claude_additive_only`
and `test_u_sdka.py::test_hy3_fake_claude_additions_are_additive` against a
scratch copy carrying this exact edit (anchor A-8, §10.1):

- **leg 1** hashes the runtime-bound source of every **base-commit**
  function against `git show c3b48e7:…` (`BASE_COMMIT` at
  `test_worker_contract.py:74`; the docstring's `89f8ef7` is historical).
  `_scenario_shim_script` **has no base-commit body** — it is a member of
  `_SU4B_SANCTIONED_NEW_FUNCS` (`:693-699`), added by U-cleanup-A — so it
  is not in `base_func_names` and leg 1 never hashes it. Violations after
  the edit: **NONE**.
- **legs 2, 3, 4** constrain top-level function NAMES, `SCENARIOS` KEYS,
  and non-`FunctionDef` top-level statements. The edit changes none of the
  three: `new_names == _SU4B_SANCTIONED_NEW_FUNCS` **True**, `cur - base ==
  {"shim_script"}` **True**, statement dumps **identical**.
- **`test_hy3`** pins ten scenarios in `_HY3_SCENARIO_SHAS`
  (`test_u_sdka.py:1882-1893`) and `shim_script` is **explicitly excluded** —
  the sentence *"not sha-pinned above since it has no base-commit body to
  pin"* lives inside `test_hy3_fake_claude_additions_are_additive`'s own
  `expected_keys` set literal, **not** on the constant *(CORRECTED-r4, gate
  D-1r3 — r3 attributed it to the constant's comment; the substance is
  unchanged)*. HY3 shas changed by the edit: **NONE**; the `SCENARIOS` key
  set is unchanged.
- **`test_hy5_numstat_bounds_hold`** — the one pin r3 missed, and it is a
  numstat bound rather than an armor sha. The printed block leaves it
  **GREEN with 7 lines of headroom** (`381` adjusted against the `388` cap);
  see the table above. `PIN7` now names it.

A dated one-line justification comment still goes **at the edit site**, in
the `test_worker_contract.py:502-506` house style (*"U-corrob 2026-08-27:
one pair per write op — the announce-only-first form made a correct
multi-write run report a corroboration MISMATCH"*), because that is the
project's convention for a sanctioned fixture change. It is a comment, not
an armor motion. `PIN7` asserts the absence of the motion.

---

## 7. EV4 pin coexistence — exact *(CORRECTED-r2, gate B-1)*

| Pin | File | Armor-sha-pinned? | How this unit coexists (all verified in §4.1) |
|---|---|---|---|
| `PL1` `test_pl1_package_contains_exactly_the_six_modules` | `tests/test_invocation_sdk.py:291` | **YES** (`22cecab…`) | Green, **UNEDITED** — `corroborate.py` is at top level, so `invocation_sdk/` still holds exactly six modules. **This is the pin r1 broke.** |
| EV4-a `test_ev4_nothing_in_the_package_reads_a_tool_events_file` | `tests/test_invocation_sdk.py:1883` | **YES** (same file) | Green, **UNEDITED**. `events.py` untouched: `.glob(` stays, `read_text` stays absent. |
| `PL3` `test_pl3_filesystem_writes_are_enumerated_with_an_exact_count` | `tests/test_invocation_sdk.py:331` | **YES** (same file) | Green, **UNEDITED**, count still **5** — this unit adds no write inside `invocation_sdk/`. It does **not** see the top-level module (§4.1); `UN2`'s walker does. |
| EV4-b `test_ev4_tool_events_string_confined_to_events_module` | `tests/test_worker_contract.py:1852` | no | Green, **UNEDITED**. `worker.py` keeps **exactly one** occurrence, still `_EV4_FW107_PINNED_FRAGMENT`. The new lines name no filename (§6.3 / R-k). `corroborate.py` and `miner.py` stay at zero — and EV4-b's `rglob` **does** reach the top level, so this is a real check on the new module, not a vacuous one. |
| BND4 `test_bnd4_…` | `tests/test_u_engine.py:912` | no | Green, **UNEDITED**. `sdksession/` untouched. |
| `POL2` | `tests/test_u_engine.py` | no | Green, unedited — the new module is not in `sdksession/`, and `sdksession/toolpaths.py` gains nothing. |
| `_ARMOR_SHAS` (7 entries) | `tests/test_worker_contract.py:507-515` | — | **No entry changes.** `test_su4a_whole_file_armor_shas` green. |

**The one thing that DOES change is a sentence, not a test.** EV4-a's
name asserts a property this unit narrows: nothing reads a tool-events
**file**, which stays literally true, while something now reads
`tool_events` **in memory**. `S-44` carries the same wording (*"Nothing
reads them"*). **`DOC2` amends `S-44` in place with a dated sentence; the
test keeps its name and its bytes**, because what the test actually
asserts — no file is read back — is still exactly what this unit
guarantees, and re-pinning an armor-sha'd file to change a docstring is
cost with no product.

**Positive control the builder must re-run** (the `U-opsfix` `B-1`
procedure, on a scratch COPY of the source tree, never the worktree):
append a second `"tool-events"` occurrence to a copy of `worker.py` and
confirm EV4-b goes RED; append the same probe to a copy of `miner.py` and
to a copy of `corroborate.py` and confirm both go RED. Without it, a green
EV4-b proves nothing about whether the sweep can see the new module.

---

## 8. The `FW-106` surfacing boundary — discharged by construction

`FW-106` (`V-3`): unscrubbed tool inputs live in `cache_dir()`, retention
20; *"the scan/scrub obligation attaches AT THE SURFACING BOUNDARY, if and
when a consumer surfaces events into the ledger or the UI."*

**This unit surfaces nothing into the ledger or the UI.** It emits, into
`worker.log` and the miner log (both already unscrubbed, local-only,
never committed, never synced — `FW-106`'s own basis) and to the
operator's terminal on `teach --route`:

- **integer counts** derived from event structure, and
- **tool NAMES** (`Write`, `Edit`, `Bash`, `NotebookEdit`), which are
  policy vocabulary already printed verbatim by the charter's own deny
  message.

It emits **no** `tool_input` value, **no** `tool_result` content, **no**
path, and **no** file name.

**That is the scrub design: do not cross the boundary carrying content.**
It is enforceable, and §9's `SCRUB` group enforces it with a canary and a
positive control rather than with a filter that could be wrong. §2.7 is
the reason this is the right shape: the only filter the product has would
have passed 65 home paths.

**If a future unit does surface content**, the obligation it inherits is
unchanged and is now measured for it: a personal-literal redactor does
not exist; `scan.scan()` is a negative control, not a starting point; and
the corpus's largest single line is 16 200 bytes of embedded proposal
body. That is `FW-129`.

---

## 9. Criteria

**Groups: COR (13) · DEN (3) · SCRUB (4) · PIN (7) · UN (5) · DOC (4) ·
SUITE (1) = 37 criteria.** *(r1 had 29; r2's `M-3`/`B-1` folds added `COR8`
and `PIN6`; r3's `M-1r2`/`N-5r2`/`M-2r2`/`N-2r2` folds added `COR9`–`COR12`
and `PIN7`; r4's `M-1r3` fold adds `COR13`.)* Every criterion carries a
mutation id from §10, or the marker **`census-only`** with its reason.

### 9.1 COR — the agreement check

- **COR1** `src/self_learn/corroborate.py` exists at TOP LEVEL and exports
  exactly `RunEvidence`. Its import set is **stdlib +
  `.invocation_sdk.charter` + `.sdksession.toolpaths` only** — no
  `.worker`, no `.miner`, no `.invocation_sdk.events`, no `self_learn_ui`.
  **Check:** an AST test over every `Import`/`ImportFrom`, asserted against
  a literal allowlist (`LIB1`'s shape, `test_u_engine.py`). → **M1**
- **COR2** `observe` pairs `tool_use["id"]` with `tool_result["tool_use_id"]`;
  classifies a write-family use as **accepted** iff its paired result
  exists and `is_error` is falsy, **unresolved** iff unpaired; and records
  **DISTINCT RESOLVED PATHS** in `.inside`/`.outside`, never event counts.
  **Check:** four-case table from the corpus's real shapes (paired-ok,
  paired-error, unpaired) plus the r2 case — **two accepted write events
  on ONE path ⇒ `len(.inside) == 1`**. → **M2, M3**
- **COR3** The write family comes from `charter.W` and the path key from
  `sdksession.toolpaths.extract_target_path`; `corroborate.py` re-spells
  neither. **Check:** AST constant sweep for the tool-name literals and a
  text sweep for the `TARGET_PATH_KEYS` literals, each with its OWN
  positive control *(CORRECTED-r2, gate N-2 — r1 named `charter.py` for
  both halves, and `grep -c file_path invocation_sdk/charter.py` is **0**
  because it imports the keys)*: `charter.py` (3 hits) controls the
  tool-name half; `sdksession/toolpaths.py` (`file_path` count **1**)
  controls the path-key half. → **M4**
- **COR4** The worker emits the MISMATCH line **iff**
  `evidence.seen and evidence.failure is None and evidence.had_events and
  len(evidence.inside) != len(staged1)`. Byte-pinned text (§6.3).
  **Check:** a disagreeing fixture emits it; the **agreeing 8-vs-8 replay
  of the measured run** (§2.6) emits **nothing**. → **M5, M6**
- **COR5** The worker emits the OUTSIDE line **iff** `evidence.outside` is
  non-empty, independently of COR4 — a fixture with one outside write and
  one missing inside write emits **both** lines. → **M7**
- **COR6** *(CORRECTED-r3, gate B-1r2)* Nothing is emitted when
  `outcome.failure` is set, **and nothing when `events_present` is False** —
  an outcome with no `tool_events` ATTRIBUTE at all (a bare `Outcome`), the
  `getattr(..., ())` shape `FW-107` established; `observe` does not raise on
  either. **Check:** a bare-`Outcome` stand-in with `failure=None` produces
  **no** corroboration line of any kind — this is the case `COR8` must NOT
  claim. → **M8, M35**
- **COR7** *(CORRECTED-r3, gate M-1r2)* The miner-reader leg: the
  filesystem census is **`len(after − before)`** over two recursive
  snapshots of `spool_dir()`, `before` taken at `miner.py:751` immediately
  after `out_path.unlink(missing_ok=True)`; MISMATCH iff that count differs
  from `len(evidence.inside)`, same guards as COR4. Byte-pinned text
  (§6.4). → **M9**
- **COR8** *(CORRECTED-r3, gate B-2r2)* When `evidence.seen and failure is
  None` **and `events_present`** but `not had_events` — the attribute
  exists and is empty — exactly the NO-EVIDENCE line is emitted and **no**
  MISMATCH or OUTSIDE line, on both surfaces. **Check:** a monkeypatched
  `SdkOutcome(tool_events=())` in the
  `test_u_opsfix.py::test_fw107_sdk_result_denials_are_not_charter_denials:275`
  shape (r2 named `sdk_fake_worker`, which is **not** a zero-event fixture
  — `fake_claude.py:531-544` emits a pair whenever the script has a write;
  §2.3). → **M10, M35**
- **COR9** *(NEW in r3, gate M-1r2; fixtures split in r4, gate N-3r3)*
  **Spool residue present BEFORE the run never counts.** **Two fixtures,
  because the two mutations fire on different residue shapes** — r3 named
  only the first, and `M40` cannot fire on it:
  - **(a) planted strays** — the
    `test_reader_contract.py:869::test_sw3_…` shape: two strays in
    `spool_dir()` before the run, a reader that writes exactly
    `mine-output.json`. Correct impl: census `after − before` = 1 =
    `len(inside)` → **no line**. This is **`M36`**'s fixture (the flat
    pre-sweep mutant reports 3 vs 1).
  - **(b) a stale `mine-output.json`** left by an earlier run, present
    before this one. Correct impl: the `:751` unlink removes it, so it is
    absent from `before`, the fresh write appears in `after`, census = 1 =
    `len(inside)` → **no line**. This is **`M40`**'s fixture (the
    pre-unlink-snapshot mutant has it in `before`, so the fresh write
    cancels: 0 vs 1). On fixture (a) `M40` cannot fire — correct impl and
    mutant both report 1. → **M36 (a), M40 (b)**
- **COR10** *(NEW in r3, gate N-5r2)* **Both snapshots walk recursively.**
  A nested accepted write (`spool/sub/x.json`, permitted by
  `write_globs=(f"{spool_dir}/**",)`, `contract.py:147`) is counted on the
  filesystem side, so it agrees rather than mismatching. **Check:** a
  fixture writing one nested file emits no line; the
  `test_sw4_directory_in_spool_survives_the_sweep` invariant is unaffected
  (directories are still never counted or swept). → **M37**
- **COR11** *(NEW in r3, gate M-2r2)* **`_scenario_shim_script` emits one
  `tool_use`/`tool_result` pair per write op**, each with a distinct
  `tool_use` id, and still performs every write unconditionally (the
  `R2-N3` bypass is preserved). **Check:** a two-write shim yields exactly
  two paired non-error write events naming both targets, and
  `test_run_partial_success` (`test_worker.py:531`) emits **no**
  corroboration line. → **M38**
- **COR13** *(NEW in r4, gate M-1r3)* **On the worker surface, only accepted
  paths whose PARENT IS EXACTLY `stage_dir()` enter `evidence.inside`**; a
  nested-but-inside-root path enters neither `inside` nor `outside`.
  **Check:** the `test_worker.py:1221::test_unexpected_artifacts_deleted_
  never_published` shape under the §6.6 fixture — a shim writing one flat
  proposal, one nested `sub/sneaky.yaml` and one flat `notes.txt` announces
  **3** accepted writes against `staged_paths()`'s **2**, and the
  corroborator emits **nothing**. Positive control in the same test:
  `staged_paths()` still returns 2 and `test_h3`'s byte-pinned
  `run: stage — N file(s)` line is unchanged, so the criterion is not
  silently making the census recursive. → **M41**
- **COR12** *(NEW in r3, gate N-2r2)* **Every line this unit emits into a
  producer log begins with `run: `** — the convention the live `worker.log`
  holds at 168/168 lines (§6.3). **Check:** capture every new line across
  all fixtures and assert the prefix; positive control — the same
  assertion over an intentionally unprefixed string fails. → **M39**

### 9.2 DEN — denial visibility where there is no FAILED line

- **DEN1** The miner-reader emits the denial line iff its charter-sourced
  denial count is nonzero. `{tools}` is the **sorted distinct** set of
  denied tool names. → **M11**
- **DEN2** `sdk-result` denials count toward **no** line on any surface —
  `FW-107`'s `N-3` filter, extended. **Check:** the
  `test_fw107_sdk_result_denials_are_not_charter_denials` shape,
  replicated per new line with a stand-in `SdkOutcome`. → **M12**
- **DEN3** `analyst.analyze` gains one keyword-only accumulator; omitting
  it leaves every existing caller byte-identical, and all **10** of
  `analyze()`'s `raise AnalystError` legs (5 of them `outcome.failure`
  legs — §6.5) still raise unchanged. **`teach --route` prints the line on
  BOTH branches of its `try`** — the success path and the
  `except analyst.AnalystError` path that returns `_capture_to_pending`.
  → **M13, M14**

### 9.3 SCRUB — the `FW-106` boundary, enforced

- **SCRUB1** **No string this unit emits is derived from a `tool_input`
  value or a `tool_result` content.** **Check:** drive every new emission
  path with events whose `input` (every key) and whose result `content`
  carry the canary literal `ZZCANARYZZ`, and assert the canary appears in
  **no** emitted line. **Positive control in the same test:** the same
  canary placed in the tool NAME *does* appear in the DEN lines. → **M15**
- **SCRUB2** No emitted line contains a filesystem path other than
  `cache_dir()` itself. **Check:** a regex over every captured line for
  `/` runs, allowing only the resolved `cache_dir()` string. → **M16**
- **SCRUB3** Nothing this unit adds or edits reads an event log file back:
  EV4-a, EV4-b, BND4, `PL1`, `PL3`, `POL2` green and **unedited**.
  **Check** *(CORRECTED-r2, gate M-5 — r1 used the fail-open two-ref form)*:
  **single-ref** `git diff 50fa815 -- <path>` (base commit vs the WORKING
  TREE) for each of `tests/test_invocation_sdk.py`, `tests/test_u_engine.py`,
  and `tests/test_worker_contract.py`'s EV4-b region, each expected empty;
  `git status --porcelain -- <path>` as the second reading. The two-ref
  `50fa815..HEAD` form is vacuous against an uncommitted tree — `test_su4a`'s
  own docstring says so verbatim, and this unit ships uncommitted like
  `U-opsfix` did. `test_su4a_whole_file_armor_shas`'s live `read_bytes()`
  hash is the independent control for the four armor-pinned files. → **M17**
- **SCRUB4** `corroborate.py` contains no `read_text`, no `open(`, no
  `.glob(`, no `.jsonl`, and no `tool-events`. **Check:** literal sweep
  with a positive control against `invocation_sdk/events.py`, which has
  three of the five. → **M18**

### 9.4 PIN — armor and confinement

- **PIN1** `worker.py` still contains the literal `tool-events` **exactly
  once**, still `_EV4_FW107_PINNED_FRAGMENT`. → **M19** (MEASURED
  procedure, §7)
- **PIN2** No `_ARMOR_SHAS` entry changes; `test_su4a_whole_file_armor_shas`
  green. **Check:** single-ref `git diff 50fa815 -- <path>` empty for each
  of the seven pinned paths (same correction as SCRUB3). → **M20**
- **PIN3** `FW-107`'s line is byte-unchanged and still fires on the same
  condition: all three `test_u_opsfix.py::test_fw107_*` green,
  **unedited**, including the direct `_invoke_claude(..., charter_denials=[])`
  call at `:275`. → **M21**
- **PIN4** `_invoke_claude` still returns `None` unconditionally (no
  `return` statement): `test_invocation.py::test_wr1_invoke_claude_
  signature_and_never_raises` green, unedited. → **M22**
- **PIN5** `invocation_sdk/charter.py` is byte-unchanged. The new module
  imports from it; the policy does not move. **Check:** single-ref
  `git diff 50fa815 -- …/charter.py` empty. → **M23**
- **PIN6** *(NEW in r2, gate B-1)* `invocation_sdk/` still contains
  **exactly six** modules: `test_pl1_package_contains_exactly_the_six_modules`
  green, unedited. → **M24** (MEASURED, §4.1)
- **PIN7** *(NEW in r3, gate M-2r2; extended in r4, gate M-2r3)* The §6.6
  fixture edit moves **no pin of any kind** — neither an armor sha nor a
  numstat bound. **Six checks, all green and all unedited:**
  `test_su4b_fake_claude_additive_only`'s four legs;
  `test_hy3_fake_claude_additions_are_additive`; and
  **`test_hy5_numstat_bounds_hold`**, whose `fake_claude.py` row is
  `(388, 1)` and which the printed block leaves at `381` adjusted — **7
  lines of headroom**, where the file sits **exactly at the cap** today
  (§6.6's table). `_HY3_SCENARIO_SHAS`, `_SU4B_SANCTIONED_NEW_FUNCS`,
  `_SU4B_SANCTIONED_EDITED_FUNCS`, `_SU4B_SANCTIONED_NEW_SCENARIO_KEYS`,
  `_SU4B_SANCTIONED_NEW_STMT_KEYS` and `test_hy5`'s own `bounds` dict are
  byte-unchanged — **the bound is not widened**. **Check:** single-ref
  `git diff 50fa815 -- tests/test_worker_contract.py tests/test_u_sdka.py`
  shows no change to any of them. → **M38** (its inverse direction: the
  announce-only-first restoration reddens `COR11` while leaving all six
  checks green, which is what proves the fixture body is outside the pinned
  set) 

### 9.5 UN — behaviours that must not move

- **UN1** `run: stage — {n} file(s) written by the model` and the
  `run: FAILED — …` line are byte-unchanged (`test_repair.py::test_h3_*`,
  armor-pinned file, green and unedited). → **M25**
- **UN2** **H-5 — the producers' write paths are byte-identical.**
  **Instrument:** `test_lock_invariant.py`. (a)
  `test_no_entrypoint_reaches_a_mutation_without_a_lock` green; (b) the
  module's exemption map gains **no** new entry — this unit writes no file
  at all; (c) `test_the_exemption_list_cannot_rot` green; (d) the walker's
  own positive control `test_it_catches_a_planted_violation` green, so an
  empty finding is not an empty analysis. **Two mutations, because the
  walker's scope is root-level** *(CORRECTED-r2, gate M-4, with one
  correction to the ruling's premise — see §16)*: the walker parses
  `src/self_learn/*.py`, which at ruling (a)'s placement includes BOTH the
  additive call sites AND `corroborate.py`. → **M26** (plant a write in
  `worker.py`/`miner.py`), **M27** (plant one in `corroborate.py`)
- **UN3** This unit adds **zero** filesystem writes inside
  `invocation_sdk/`: `test_pl3_filesystem_writes_are_enumerated_with_an_exact_count`
  green with its count still **5**. (PL3 is a root-level glob over
  `invocation_sdk/` only and cannot see the new module — `UN2` owns that;
  §4.1.) → **M28**
- **UN4** Nothing this unit builds changes what lands. `worker.run`'s
  `RunResult` (`status`, `proposed`, `committed`, …) is byte-identical on
  every fixture, mismatch fixtures included. **Check:** drive the
  disagreeing fixture and assert the `RunResult` equals the same run's
  result with the evidence accumulator omitted. This is `S-44`'s
  "corroboration, never authority", made a test. → **M29**
- **UN5** `serve` is unaffected: `test_serve.py` green, unedited; no new
  job, no heartbeat field, no schedule change (`S-50`). **Check:**
  single-ref `git diff 50fa815 -- …/serve.py` empty. → **M30**

### 9.6 DOC

- **DOC1** `03-decisions.md` gains **`S-53`** (§13.1), after `S-50`. → **M31**
- **DOC2** `03-decisions.md` **`S-44` is amended in place** with the dated
  consumer-clause sentence (§13.2) — amended, never rewritten. → **M32**
- **DOC3** `14-forward-work-map.md` gains **`FW-128`, `FW-129`, `FW-130`,
  `FW-131`** (§13.3) **and one dated entry** in the running log, per that
  file's own one-entry-per-landing convention (the convention `U-engine`
  was found to have skipped, 14 `:524`). → **M33**
- **DOC4** `17-invocation-runbook.md` §5.4 gains the paragraph of §13.4.
  → **M34**

### 9.7 SUITE

- **S1** `plugins/self-learn/cli/scripts/suite` returns **rc=0**, captured
  **unpiped** (`lrn-ea833a5b`), with the new test module's tests added to
  the pass count and **zero** failures. The UI suite is not touched by this
  unit and is not run. → **`census-only`** — S1 is the aggregate the other
  **40** mutations are observed through; a mutation "of" S1 would just be
  one of them, and inventing a **42nd** would be a tautology
  *(CORRECTED-r4, gate N-4r3 — the numbers track §10's total, 41)*.

---

## 10. Mutation plan

**41 mutations: 1 fully MEASURED (`M24`), 1 PARTIALLY measured (`M19` —
`A-7` covers the `worker.py`/`miner.py` probes; the `corroborate.py` probe
is the builder's), 39 predicted** *(CORRECTED-r3, gate N-4r2 — r2 counted
`M19` as fully measured)*. **1 criterion (`S1`) is `census-only`**, with its
reason stated in §9.7.

### 10.1 Measured anchors (this session, 2026-08-27, at `50fa815`)

| # | Anchor | Result |
|---|---|---|
| A-1 | Worker fs census vs event census on the only real run with events (`20260826T053809Z-888755`) | `staged` 8, accepted-inside 8, **distinct paths 8**, outside 0 — **AGREE** under both the event rule and `M-2`'s path rule. `COR4`'s positive-control fixture. |
| A-2 | `scan.scan()` over the whole 42-file corpus | 81 613 bytes, **0.0057 s**, **0 hits**, against **65** home-path occurrences — the negative control that rejects `R-b` |
| A-3 | `grep -c "charter denial" worker.log` with its own positive control | `0` (rc=1) against 168 readable lines — `FW-107` has never fired |
| A-4 | `tool_use`/`tool_result` pairing across the corpus | 35/35 paired on `id` ↔ `tool_use_id`, 0 unpaired, 16 `is_error` — `COR2`'s basis |
| A-5 | The full pin census against `src/self_learn/corroborate.py` (§4.1) | `PL1` True, `PL3` 5, EV4-a True, EV4-b no violations, BND4 clean, `POL2` 0/3, walker sees the module — **all six pins green unedited**. Also the `M-4` inversion. |
| A-6 | Retention ordering | `backend.py:574` write then `:593` prune, comment at `:587-592`; `git log -S` → `ead58ad 2026-08-27 03:41:26` — steady state `keep`=20, today's 21 is residue |
| A-7 | EV4-b reddens on a second `tool-events` occurrence in a scratch copy of `worker.py`, and on the probe in a copy of `miner.py` | Verified by the `U-opsfix` gate, 2026-08-26 (14 `:522`); **the builder re-runs it, adding a `corroborate.py` copy** (`PIN1`/`M19`) — this is the PARTIALLY-measured one |
| A-8 | The §6.6 fixture edit against all five armor legs, on a scratch copy | `_scenario_shim_script in base_func_names` **False**; leg 1 violations **NONE**; leg 2 `new_names == sanctioned` **True**; leg 3 `cur − base == {"shim_script"}` **True** and every base key still bound to its original `__name__`; leg 4 statement dumps **identical**; `test_hy3` shas changed **NONE**, key set unchanged; net line delta **−7** (14 → 7; the four spellings are `A-10`). `PIN7` holds. |
| A-9 | The `worker.log` line-class census that fixes the `run:` prefix (`COR12`) | `run:` **84** timestamped + **27** bare `worker run: …`, `window` **46**, `escalation:` **11** — 168/168 lines, four classes, no fifth |
| A-10 | The `test_hy5` numstat bound under all four edit spellings (`PIN7`, §6.6) | live tracked `git diff --numstat 442385d -- …/fake_claude.py` → **`390 1`**; `--no-index` control reproduces `390 1`; printed 7-line block → **`383 1`** (adjusted 381 vs cap 388, **7 under**); printed block + the 2-line comment → `385 1` (383, still green); line-preserving spelling → `390 1` (388, at the cap) |

### 10.2 The unit's own mutations

| # | Mutation | Predicted | Criterion |
|---|---|---|---|
| M1 | `corroborate.py` imports `from . import worker` | RED | COR1 |
| M2 | Treat any paired `tool_result` as accepted (drop `is_error`) | RED | COR2 |
| M3 | Count accepted EVENTS instead of distinct paths | RED on the two-events-one-path fixture | COR2 |
| M4 | Inline `("file_path",)` / `"Write"` instead of the imported symbols | RED | COR3 |
| M5 | MISMATCH condition `!=` → `<` | RED on the over-report fixture | COR4 |
| M6 | Make the MISMATCH line **unconditional** (drop the `!=` guard) *(CORRECTED-r2, gate N-5 — r1's "delete an assertion, stay green" demonstrated nothing)* | RED — the agreeing 8-vs-8 fixture's silence assertion fails | COR4 |
| M7 | Guard the OUTSIDE line behind the mismatch condition | RED on the offsetting fixture | COR5 |
| M8 | Remove the `failure is None` guard | RED on the timeout fixture | COR6 |
| M9 | Take the reader's fs census as `out_path` alone, or after the sweep *(CORRECTED-r3: r1's form was dead, r2's fired on a passing test — this is the third form)* | RED on a fixture where the MODEL writes a second spool file: census 1 vs 2 accepted writes | COR7 |
| M10 | Drop the no-events guard (treat an empty `tool_events` as 0 writes) *(CORRECTED-r3, gate B-2r2 — re-predicted against a monkeypatched `SdkOutcome(tool_events=())`, since `sdk_fake_worker` is not a zero-event fixture)* | RED — the zero-event stand-in emits a MISMATCH instead of the no-evidence line | COR8 |
| M11 | Emit `{tools}` unsorted / non-distinct | RED on a two-denial fixture | DEN1 |
| M12 | Drop the `source == "charter"` filter on any new line | RED | DEN2 |
| M13 | Make `analyze`'s new parameter positional | RED at every existing call site | DEN3 |
| M14 | Print the analyst line only on `teach`'s success branch | RED — the `AnalystError` fixture (a denied run that raises) shows no line | DEN3 |
| M15 | Append `extract_target_path(...)` to the OUTSIDE line | RED | SCRUB1 |
| M16 | Emit a stage path in any new line | RED | SCRUB2 |
| M17 | Edit EV4-b's body (widen the worker exemption) | RED — SCRUB3's single-ref diff on `test_worker_contract.py` is non-empty | SCRUB3 |
| M18 | Add a `read_text` call to `corroborate.py` | RED | SCRUB4 |
| M19 | Second `tool-events` occurrence in a scratch copy of `worker.py`; the same probe in copies of `miner.py` and `corroborate.py` | RED (**MEASURED** for the first two, A-7) | PIN1 |
| M20 | Touch any armor-pinned test file | RED — `test_su4a`'s `read_bytes()` hash | PIN2 |
| M21 | Change the `FW-107` line's text | RED — all three `test_fw107_*` | PIN3 |
| M22 | Add a `return` statement to `_invoke_claude` | RED — `test_wr1` | PIN4 |
| M23 | Edit a deny message in `charter.py` | RED — PIN5's single-ref diff non-empty | PIN5 |
| M24 | Place `corroborate.py` in `invocation_sdk/` | RED — `PL1` names ≠ expected (**MEASURED**, §4.1/A-5) | PIN6 |
| M25 | Change the `run: stage — N file(s)` text | RED — `test_repair.py::test_h3_*` | UN1 |
| M26 | Plant a `write_text` in `worker.py` / `miner.py` outside a lock | RED — the walker names an unguarded mutation | UN2 |
| M27 | Plant a `write_text` in `corroborate.py` | RED — the walker's root-level glob reaches it (§4.1) | UN2 |
| M28 | Plant a `write_text` inside `invocation_sdk/` | RED — `PL3`'s exact count 5 → 6 | UN3 |
| M29 | Let a mismatch set `result.status = "failed"` | RED | UN4 |
| M30 | Edit `serve.py` | RED — UN5's single-ref diff non-empty | UN5 |
| M31 | Omit the `S-53` row | RED — DOC1's grep | DOC1 |
| M32 | Leave `S-44` unamended | RED — DOC2's grep for the dated sentence | DOC2 |
| M33 | Omit any one of `FW-128`..`FW-131`, or the dated log entry | RED — DOC3's grep | DOC3 |
| M34 | Omit the §5.4 runbook paragraph | RED — DOC4's grep | DOC4 |
| M35 | Collapse `events_present` into `had_events` (one flag, r2's shape) | RED — **both directions**: the bare-`Outcome` fixture emits a no-evidence line (COR6 red) under one collapse, and the empty-`tool_events` fixture goes silent (COR8 red) under the other. This is `B-1r2` made a test | COR6, COR8 |
| M36 | Drop the `before` snapshot; census the spool flatly, pre-sweep (r2's shape) | RED on the `test_sw3` two-stray fixture: census 3 vs 1 accepted write | COR9 |
| M37 | Snapshot with `iterdir()` instead of `rglob("*")` | RED on the nested-write fixture: a permitted `spool/sub/x.json` counts 1 event against 0 files | COR10 |
| M38 | Restore `_scenario_shim_script`'s announce-only-`writes[0]` form | RED — `COR11`'s two-write assertion and `test_run_partial_success`'s silence assertion. **All five armor legs stay GREEN**, which is `PIN7`'s proof that the body is outside the pinned set | COR11, PIN7 |
| M39 | Emit the no-evidence line without the `run: ` prefix (r2's `corroboration:` form) | RED — `COR12` | COR12 |
| M40 | Take the `before` snapshot BEFORE `out_path.unlink` instead of after (`miner.py:751`) | RED on `COR9`'s fixture **(b)** only — a stale `mine-output.json` sits in `before`, so the fresh write cancels: census 0 vs 1. On fixture (a) it cannot fire | COR9 |
| M41 | Count any accepted path under `stage_dir()` at any depth (drop the parent-of-stage rule, i.e. use the miner's `flat=False` predicate on the worker) | RED — `test_worker.py:1221`'s shape reports 3 accepted vs a flat census of 2 and the MISMATCH line fires on a correct, passing test | COR13 |

### 10.3 Unmutated-test census

Tests that would stay green under **every** mutation above, named so the
gate knows they are load-bearing for something else, not for this unit:
`test_ev5_retention_keeps_only_the_newest_n`,
`test_ev6_prune_never_touches_another_surfaces_files_or_the_logs`
(retention — untouched by design, §5.4), `test_serve.py`'s heartbeat suite
beyond `UN5`'s diff check, and `test_decision_trace.py` (the schema this
unit refuses to extend, §5.3). Each is asserted **green and unedited**, and
none is offered as evidence that this unit works.

---

## 11. IN / OUT

**IN**
1. `src/self_learn/corroborate.py` — `RunEvidence`, the in-memory
   distinct-path write census. **Top level** (§4.0).
2. `worker.py` — a second keyword-only accumulator on `_invoke_claude`;
   up to three log lines after the round-1 stage census.
3. `miner.py` — the same accumulator on `_invoke_reader`; a recursive
   before/after spool snapshot pair (`before` at `:751`), a mismatch line,
   a no-evidence line, a charter-denial line.
4. `analyst.py` + `teach.py` — the accumulator and one printed line on
   **both** branches of `teach`'s `try` (`Q-1` RULED YES).
5. `tests/fixtures/fake_claude.py` — `_scenario_shim_script` emits one
   `tool_use`/`tool_result` pair per write op (§6.6). Test-side, **net −7
   lines** (the printed block is normative), no armor sha moved and
   `test_hy5`'s numstat bound left with 7 lines of headroom (measured,
   `A-8`/`A-10`) *(CORRECTED-r4, gate M-2r3 — r3 said "net zero")*.
6. `cli/tests/test_u_corrob.py` — new.
7. Docs: `03-decisions.md` (`S-53`, `S-44` amendment),
   `14-forward-work-map.md` (`FW-128`..`FW-131` + one dated entry),
   `17-invocation-runbook.md` §5.4.

**OUT — with the owner or the measurement**
1. Reading any written event log — §5.2 point 2, §7. Owner: `FW-129`.
2. Any `report` or UI surface — §5.2. Owner: `FW-129`.
3. Any ledger/decision-trace field — §5.3. **Refused permanently**, not
   deferred.
4. A `doctor` events/retention row — §5.4 (`Q-2` RULED NO).
5. The `worker-repair` corroboration leg — §5.8.
6. `sdk-result` denials as a signal — DEN2 keeps them out.
7. Retention, pruning, or deleting anything in `cache_dir()` — `FW-106`
   ruled capture; this unit is downstream.
8. The 1.1 GB / 31 269-namespace cache litter — `U-cachelit` / `FW-130`
   (`Q-5` RULED).
9. Everything in `G-1` — §1.3, including the now-met third trigger.
10. A new verb — `U-verbs`.

---

## 12. Exit codes and verdict semantics

**This unit changes no exit code and adds no verdict.** Stated as a table
because the absence is the contract:

| Surface | Today | After this unit |
|---|---|---|
| `worker.run` → `RunResult.status` | `ok` / `failed` / `idle` / `busy` / `disabled` / `landed-uncommitted` | **unchanged** — `UN4` pins it. A corroboration mismatch is a log line, never a status |
| `self-learn mine` exit | driven by `MineResult.status` | **unchanged** |
| `teach --route` exit | unchanged; `AnalystError` legs unchanged (all 10 still raise, §6.5) | **unchanged** — `Q-1` adds a printed line only, on both branches |
| `self-learn doctor invocation` | `1` iff any row's verdict is `FAIL`, else `0` (`EXIT_OK`); `EXIT_USAGE = 64` on a wrong subcommand (`cli.py:852-872`) | **unchanged — no row is added** (§5.4) |

For the record, since `Q-2` asked about a row: `provider.VERDICTS` is
`("PASS","WARN","FAIL","SKIP","INFO")` and `DOCTOR_ROWS` has **12**
members ending `…, "orphans", "serve"`. A live run at `50fa815` against a
throwaway copy of the ledger renders **18 verdict rows**, then one
`doctor: ---` separator, then **20** handoff lines — **39 lines total** —
and exits `1` (the `serve` row FAILs because the throwaway cache has no
heartbeat while `self-learn-host.service` is linked) *(CORRECTED-r2, gate
N-4 — r1 said 19 rows; re-measured twice)*:

```
$ env SELF_LEARN_HOME=<copy> XDG_CACHE_HOME=<copy-xdg> SELF_LEARN_MINER=0 \
      SELF_LEARN_MINER_AUTOKICK=0 ~/bin/self-learn doctor invocation
doctor: INFO switches — worker: backend=sdk (default); worker-repair: backend=sdk (default); …
doctor: WARN sdk — sdk=0.2.134 bundled-cli=2.1.226 host-cli=2.1.250 — versions differ
doctor: SKIP orphans — no orphan report hook exported by the sdk backend
doctor: FAIL serve — self-learn-host.service is linked but no heartbeat was ever seen …
rc=1   (verdict rows 18, separators 1, handoff 20, total 39)
```

Had `Q-2` gone the other way, `17-invocation-runbook.md` §10's four-verdict
table is the precedent to match and `_serve_row` (`provider.py:616`) the
shape — and the row would have to be `INFO` or at most `WARN`, **never
`FAIL`**, because `FW-106` ruled the exposure acceptable on the ground
that these files are local-only. That constraint is why §5.4's third
rejection ground stands even though r1's first one did not.

---

## 13. Docs owed at merge

### 13.1 `03-decisions.md` — one new row after `S-50`

> | `S-53` | **The consumer of `tool_events`/`denials` is an IN-MEMORY
> corroborator that emits COUNTS, and nothing else — no file is ever read
> back, nothing reaches the ledger or the UI.** `S-44` reserved the
> consumer for this unit and fixed its constraint: the filesystem diff
> remains the authority. Measured at `50fa815` before deciding: the whole
> retained corpus is **42 files / 128 lines / 70 tool events / 16
> denials**; **every denial in it is on the `analyst`, is `Bash`, and
> falls in one 13-minute window on 2026-08-21** (8 of 8 consecutive runs,
> each recorded three times — charter, `sdk-result`, and the paired
> `tool_result`); `worker`, `worker-repair` and `miner-reader` have
> recorded **zero denials ever**, and capture is uniform across surfaces
> (`backend.py:213`), so that zero means the charter never denied there —
> subject to two caveats, that 16 of 21 worker files are fake sessions
> that never request a permission and that `SELF_LEARN_ENFORCE_SCOPE=0`
> returns ALLOW before any deny path (`charter.py:211`); `FW-107`'s line —
> the product's only shipped consumer — **has never printed** (`grep -c` 0
> against 168 readable `worker.log` lines, with its own positive control);
> and the one real worker run carrying tool events **agreed exactly** with
> the filesystem census (8 staged files, 8 distinct accepted paths, 0
> outside the stage). **What decided the unit was not that evidence but
> its absence elsewhere:** `17-invocation-runbook.md` §5.4's *"0
> out-of-scope write attempts (`denials` empty AND filesystem diff
> agrees)"* gate is prose with no instrument, and `fixtures/trials.md`
> records **no burn-in entry for any SDK surface** — so the check became
> automatic and per-run instead of manual and never-executed. **Four
> consequences are permanent.** **(1)** A mismatch is a LOG LINE, never a
> status: `RunResult` is byte-identical on a mismatching run (`UN4`) —
> corroboration may report, never adjudicate. **(2)** Three counting rules,
> each adopted because the obvious alternative **fires on a correct run** —
> the class that would have made the instrument worthless. Accepted writes
> are counted as **distinct resolved paths**, never as events (a
> `Write`-then-`Edit` on one staged file is two events for one file in a
> flat `staged_paths()` listing). The reader's filesystem side is
> **`after − before`** over two recursive snapshots taken around the
> session, never a flat listing (an existing passing test plants two spool
> strays before the run, and the `:771-772` early return leaves residue the
> corpus has twice produced). And an outcome whose `tool_events` attribute
> exists but is **empty** yields a NO-EVIDENCE line rather than a mismatch,
> while an outcome with **no such attribute** yields nothing at all — two
> flags, because one could not tell those apart. The fourth false-alarm
> source was a **fixture bug**, not a design choice, and was fixed at the
> root: `_scenario_shim_script` performed every write but announced only
> the first, so a correct two-write run reported one. **(3)** Surfacing events into `report`, the UI, or a record is
> REFUSED, not deferred (`FW-129`): the product's only scrubber returns
> **0 hits over the entire corpus while 65 occurrences of the user's home
> path sit inside it**, so reusing it at a boundary would be a green light
> on exactly what `FW-106` named; and reading a written log back would
> require re-pinning an armor-sha'd test file. **(4)** An event-derived
> field in the decision trace is refused permanently — the trace is
> published, and writing the model's self-report of its own tool calls
> into the durable provenance record is precisely what `FW-84` cost;
> `S-32` already proves the same thing structurally. **Placement is part
> of the decision:** the module is `src/self_learn/corroborate.py`, at top
> level, because it consumes OUTCOMES and is not part of the invocation
> seam — and because `invocation_sdk/` is pinned to exactly six modules by
> an armor-sha'd test (`test_pl1_…`), so putting a consumer inside the
> seam would have cost the very armor motion consequence (3) prices as
> prohibitive. | `U-corrob` spec
> (`docs/specs/self-learn/drafts/u-corrob-tool-events-consumer-spec.md`),
> landed in the same commit as the build (same disposition-rule
> obligation as S-24/…/S-50). Recorded 2026-08-27. |

### 13.2 `03-decisions.md` — the `S-44` amendment (append to the row)

> **Amended 2026-08-27 (`U-corrob`, `S-53`):** the consumer clause is
> closed. *"Nothing reads them"* becomes: **exactly one consumer reads
> them, in memory, off the `SdkOutcome` at the call site; no written
> event-log file is ever read back** — which is why
> `test_ev4_nothing_in_the_package_reads_a_tool_events_file` keeps its
> name and its bytes. The standing constraint is unchanged and was
> re-derived rather than assumed: the filesystem diff remains the
> authority, and `UN4` makes it a test (a corroboration mismatch leaves
> `RunResult` byte-identical). The operational consequence this row
> already named — the §5.4 burn-in gate reading `denials` **and** the
> filesystem diff — now has an automatic instrument instead of a manual
> procedure that `fixtures/trials.md` shows was never run.

*(If the gate rules for option (v) — §5.5 — the amendment instead reads:
**"the consumer clause is closed with no second consumer. Measured
2026-08-27 over the whole retained corpus: 16 denials, all on the
attended analyst, all in one 13-minute window; zero on every writing
surface, ever; and the one real worker run agreed exactly with the
filesystem census. `FW-107`'s line is the consumer."** `FW-128` then
becomes the record of the refusal rather than of a build.)*

### 13.3 `14-forward-work-map.md` — four rows

- **`FW-128`** | **The `tool_events`/`denials` consumer: an in-memory
  corroborator emitting counts.** Closes `S-44`'s consumer clause and
  gives `17` §5.4's two-instrument gate an automatic instrument. Corpus,
  `FW-107`'s never-printed line, and the never-run burn-in are the
  evidence; §5.7 is the sizing; `src/self_learn/corroborate.py` is the
  placement and §4.0 is why. | **BUILD** | Landed by `U-corrob`.
- **`FW-129`** | **Surfacing tool events into the ledger, `report`, or the
  UI is REFUSED, with the measurement.** `scan.scan()` — the product's
  only scrubber — returns **0 hits** over the whole 81 613-byte corpus
  while **65** occurrences of the user's home path and whole 16 200-byte
  proposal bodies sit inside it; `scrub-personal-literals-spec.md` is a
  source-tree de-personalisation spec, **not** a runtime redactor, so
  there is nothing to reuse. Reading a written log back additionally
  requires re-pinning `_ARMOR_SHAS["…/test_invocation_sdk.py"]`. | **WATCH**
  | **Trigger:** a second consumer that genuinely needs past-run events
  (`G-1`, or a second human user) **AND** a real personal-literal
  redactor. Until both, the answer is no.
- **`FW-130`** | **`~/.cache/self-learn` holds 31 269 per-home namespaces
  and 1.1 GB, of which two contain any event log.** Measured 2026-08-27
  (and still growing during the spec gate — 31 269 → 31 271 in ~25
  minutes, from unrelated processes). Mechanism: `worker.cache_dir()`
  `mkdir`s a namespace keyed on `sha256(resolved home)[:8]`, so every suite
  run with a fresh `tmp_path` `SELF_LEARN_HOME` and **no** `XDG_CACHE_HOME`
  redirect creates one in the operator's real cache (~36 KB each:
  `miner/{miner.log, cursors.json, journal.jsonl, *.lock}`). | **BUILD** |
  **Owner: `U-cachelit`**, its own T1 unit (ruling on `Q-5`). Two candidate
  directions, and the choice is that unit's: (a) a conftest-level
  `XDG_CACHE_HOME` redirect for every test that resolves a home, or (b) a
  `cache_dir()` that refuses to `mkdir` outside a known-home set. |
- **`FW-131`** | **The analyst runs blind and loud-failing on the one
  ATTENDED surface.** Measured over the only window with analyst tool
  events (2026-08-21, 8 runs): **16 of 22 tool calls (72.7%) errored** — 8
  charter `Bash` denials plus 8 `Read` calls returning `File does not
  exist. Note: your current working directory is ~/.self-learn.`
  The analyst's `SessionSpec` passes `log=lambda _msg: None`
  (`analyst.py:236`), so none of it reaches the operator. **`U-corrob`
  closes the DENIAL half** (`DEN3`: `teach --route` prints a denial count
  and tool names on both branches of its `try`). The missing-file half is
  a prompt/doctrine question — the analyst was hunting for
  `card-sections.yaml` with a tool its charter forbids — and is **not**
  closed here. | **BUILD** | Not scheduled. Belongs with whoever next
  touches `compose_single_prompt` or the routing doctrine. |

### 13.4 `17-invocation-runbook.md` §5.4 — one paragraph

> **Amended 2026-08-27 (`U-corrob`).** The *"denials empty AND filesystem
> diff agrees"* half of this gate is no longer a manual comparison: the
> worker and the miner-reader now emit a `run: corroboration MISMATCH …`
> line whenever the two instruments disagree on a successful run, and a
> separate line whenever the model reports an accepted write outside the
> granted root — counts only, filesystem named first, never a status
> change. Accepted writes are counted as **distinct resolved paths**, not
> events; the reader's filesystem side is a recursive before/after snapshot
> pair, so spool residue from an earlier run never counts; and a session
> whose captured event list is **empty** emits
> `run: corroboration — no tool events recorded (N file(s) on disk)` rather
> than a mismatch — a session with zero events is not an instrument, while
> a transport that captured nothing at all says nothing. **What it
> still does not cover, stated so nobody reads more into it:** it is silent
> on a failed or timed-out session (whose accounting is known-incomplete),
> silent on the repair round (a byte-identical rewrite is an accepted write
> with zero filesystem change), and silent on the analyst's writes (there
> are none — the analyst is a `text_session`; what it gets instead is a
> denial count on `teach --route`). And `fixtures/trials.md` still has no
> burn-in entry for any surface — an automatic instrument is not a
> discharged gate.

---

## 14. Parallel units *(CORRECTED-r2, gate D-1)*

Two siblings are being authored at the same base (`50fa815`), and both
exist on disk as worktrees a reader can open:

- **U-hostmode** (git-optional canon hosts) — `.claude/worktrees/u-hostmode-spec/`,
  numbering `S-51` / `FW-122..124`.
- **U-ancestry** (ancestor canon in routing) — `.claude/worktrees/u-ancestry-spec/`,
  numbering `S-52` / `FW-125..127`.

*(Two further worktrees exist on this host — `u-papercuts`, `u-verbguards` —
and are not this cycle's spec siblings.)*

**The numbering is checkable, and checked:** `03-decisions.md` ends at
**`S-50`** and `14-forward-work-map.md` ends at **`FW-121`** (measured), so
`S-51`/`S-52`, `FW-122..127` and this unit's `S-53`/`FW-128..131` are all
unallocated and mutually disjoint. This unit designs nothing for either
sibling.

| Artefact | U-corrob's footprint | Assumption about the siblings |
|---|---|---|
| `worker.py` | One keyword-only parameter added to `_invoke_claude` (`:3062-3066`), plus ~15 lines inside `run()` immediately after the `run: stage — …` line (`:3205`). **No existing line is edited.** | Both siblings likely touch `worker.py` (host resolution / routing). Textual collisions are near-certain in `run()`; **semantic** collision is not, because U-corrob adds only an additive parameter and additive log lines. **Merge rule: U-corrob rebases onto whichever sibling lands first, never the reverse** — its hunks are additive and re-apply cheaply; a routing change does not. |
| `src/self_learn/corroborate.py` | New file, top level. | Neither sibling is expected to add a top-level module. If one does, `test_lock_invariant.py`'s walker sees both and the exemption map is the shared surface (this unit adds no entry). |
| `provider.py` doctor rows / `DOCTOR_ROWS` | **NONE.** §5.4 recommends against a row and `Q-2` ruled it out. | If either sibling adds a row, `DOCTOR_ROWS`' tuple order is the conflict point (it is a positional literal). U-corrob will not contest it. |
| `03-decisions.md` | `S-53` appended after `S-50`; `S-44` amended in place. | Row numbers are pre-allocated and disjoint; the only collision is the append point in the table — resolve by row number order, not by landing order. |
| `14-forward-work-map.md` | `FW-128`..`FW-131` + one dated entry in the running log. | Same rule. Where three units land dated entries in one session, keep them as three separate dated bullets, not one merged bullet. |
| `17-invocation-runbook.md` | §5.4 only, one paragraph. | U-hostmode plausibly touches §1/§3 (switches, preflight); U-ancestry probably touches nothing here. §5.4 is believed uncontested — checkable now that the worktree paths are named. |
| `miner.py` | `_invoke_reader` (`:738-778`) — one evidence object, a recursive before/after spool snapshot pair (`before` at `:751`), three log lines. | U-ancestry may touch the miner's routing/reconcile phases (`_reconcile_and_land`), not `_invoke_reader`. Assumed disjoint; checkable in `u-ancestry-spec/`. |
| `analyst.py` / `teach.py` | `analyze()`'s signature and one print in both branches at `teach.py:683-692`. | U-ancestry touches routing/destination resolution, which the analyst's *prompt* composes (`compose_single_prompt`). Assumed disjoint; if U-ancestry also edits `teach.py`, U-corrob rebases. |
| `cli/tests/fixtures/fake_claude.py` | `_scenario_shim_script`'s body only (§6.6) — **net −7 lines**, no constant and no other function touched *(CORRECTED-r4, gate M-2r3)*. | Either sibling driving the worker through `sdk_fake_worker` inherits the fixed fixture and needs no change: the extra events are additive and no existing test asserts the event count. If a sibling ALSO edits this file, the collision is inside one function body and resolves textually. |
| `cli/tests/test_worker_contract.py`, `test_invocation_sdk.py`, `test_u_engine.py`, `test_u_sdka.py` | **Read-only, unedited** (EV4-a/b, `PL1`, `PL3`, BND4, `POL2`, `_ARMOR_SHAS`, `_SU4B_*`, `_HY3_SCENARIO_SHAS`). | **This is the one hard constraint U-corrob imposes on its siblings:** if a sibling edits any of these, it must not touch EV4-b, `PL1`, `PL3`, `_ARMOR_SHAS`, or the `fake_claude.py` armor constants — `PIN7` depends on all five being byte-unchanged. |

---

## 15. What could NOT be measured

1. **The full event history.** Retention 20 makes §2 a rolling window
   (`worker.log`: 46 `run: ok` all-time vs 21 retained files). Every
   "ever" in this document means "in the retained corpus".
2. **Whether the analyst's 8 denials cost anything.** The model worked
   around the `Bash` denial and produced its proposals. Whether the
   answers were worse is not recoverable from the event log.
3. **Whether a corroboration mismatch has ever actually occurred.** N=1
   agreeing datapoint (§2.6). The check is specified against a class it
   has never been observed to catch; that is stated in `S-53`, not hidden.
4. **The `cli`-side control.** There is none — `denials` and `tool_events`
   exist only on `SdkOutcome`, and the `cli` backend is deleted
   (`S-49`). Every "before/after" in this unit is sdk-only by construction.
5. **~~Whether the live daemon runs with `SELF_LEARN_ENFORCE_SCOPE=0`.~~
   ANSWERED — NO** *(CORRECTED-r3, gate N-3r2; the inspection was permitted
   and is read-only)*. `~/.config/systemd/user/self-learn-host.service` is a
   symlink to `repos/self-learn/systemd/self-learn-host.service` and sets
   exactly one variable, `Environment=SELF_LEARN_HOME=%h/.self-learn`;
   `systemctl --user show-environment` carries no `SELF_LEARN_*` except
   `SELF_LEARN_UI_MONITOR=DP-2`; and the live daemon's own
   `/proc/<MainPID>/environ` holds `SELF_LEARN_HOME` +
   `SELF_LEARN_UI_MONITOR` and **no `SELF_LEARN_ENFORCE_SCOPE`**. So
   `_enforce_scope()` is True, `default_mode="default"`, `hatch_open` is
   False — **the hatch is CLOSED for every daemon-started run**, and
   §2.4's zero-denial reading stands on clean behaviour, not on the hatch.
   **Residual:** the corpus's worker runs predate the unit (symlinked
   2026-08-27 21:49) and ran from a shell whose environment is not
   recoverable, so the caveat survives for the historical files only.
6. **`FW-130`'s exact mechanism per test.** 31 269 namespaces were counted
   and one was inspected; which test modules create them was not
   enumerated. That is `U-cachelit`'s work.
7. **Repair-round behaviour.** Zero tool events on `worker-repair` in the
   corpus (§2.2). §5.8's false-mismatch mode is reasoned from
   `touched2`'s definition (`worker.py:3305-3316`), not observed.

---

## 16. Questions — rulings received, and one disagreement

All six of r1's open questions were ruled by the orchestrator. Recorded
here with what changed:

- **`Q-1` — the analyst denial line: RULED YES.** §6.5 wires it, `DEN3`
  pins it on **both** branches of `teach`'s `try` (gate `N-7`), and the
  leg census is measured (10 raises, 5 of them `outcome.failure` legs).
- **`Q-2` — a `doctor` hygiene row: RULED NO.** §5.4 is rewritten:
  r1's deciding measurement was wrong (`M-1`) and the rejection now stands
  on ownership, scale, and verdict semantics.
- **`Q-3` — may a mismatch change the run's outcome: NO.** `UN4`.
- **`Q-4` — tier: T1**, and §4.1 shows ruling (a) preserves it.
- **`Q-5` — cache litter: its own T1 unit, `U-cachelit`**, owning `FW-130`.
- **`Q-6` — the analyst finding gets a number: `FW-131`.**

**Disagreement 1 (r2) — UPHELD by the gate, kept as implemented.** The
`M-4` ruling read *"point UN2's mutation at `worker.py`/`miner.py` … keep
UN3/PL3 as the module's own guards."* Under ruling (a) that is backwards:
`test_lock_invariant.py`'s walker globs `src/self_learn/*.py` at **root
level**, so it **does** see `corroborate.py`; `PL3` globs
`invocation_sdk/*.py`, so it **does not**. The gate replicated this through
the real `_Analysis` and found the mechanism *stronger* than this spec
claimed — `_resolve` cannot resolve `evidence.observe(outcome)` (an
attribute call on a local), so `observe` has no callers, is therefore a
ROOT, and an unexempted root carrying an unguarded mutation is exactly what
`test_no_entrypoint_reaches_a_mutation_without_a_lock` asserts against.
Both `M26` and `M27` stand.

**Disagreement 2 (r3) — UPHELD by gate r3, kept as implemented.** The
`M-2r2` ruling's armor premise was wrong and I did not invent the re-pin it
asked for; gate r3 replicated all five legs and confirmed `PIN7` is correct
as written. **One thing r3 and I both missed, and gate r3 caught: the pin
that DOES bind this file is `test_hy5`'s numstat bound, not an armor sha.**
It is folded into `PIN7` and §6.6 with its margin measured (`A-10`).

**Refinement on the `M-2r3` ruling's arithmetic (not a disagreement — the
substance holds).** The ruling gives the margin as *"`383 1` vs cap
`(388, 1)` → 5 lines of slack"*. The assert is
`ins -= 2; assert ins <= max_ins` (`test_u_sdka.py:2018-2020`), so the
printed block's `383` insertions are compared as **381** against **388** —
**7 lines of headroom**, not 5. (5 is what the raw `383` gives against 388
without the `ins -= 2` adjustment the check actually applies.) §6.6 states
both readings so neither can be mistaken for the other. A second, useful
consequence the ruling's framing obscures: because the printed block buys
7 lines, **the prescribed justification comment is affordable** (`385 1` →
383, still 5 under) — it is only the line-count-preserving spelling that
the comment pushes red.

*(r3's original wording of disagreement 2, for the record:)* The ruling says *"`fake_claude.py`
IS armor-pinned — prescribe the re-pin with its dated one-line
justification"*. Measured (`A-8`, §6.6): the §6.6 edit moves **no pin**.
`_scenario_shim_script` is in `_SU4B_SANCTIONED_NEW_FUNCS`
(`test_worker_contract.py:693-699`) and has **no base-commit body**, so
`test_su4b`'s leg 1 — which iterates `base_func_names` — never hashes it;
legs 2/3/4 constrain names, `SCENARIOS` keys and non-function statements,
none of which the edit touches; and `_HY3_SCENARIO_SHAS`
(`test_u_sdka.py:1882-1893`) **explicitly excludes** `shim_script` by its
own comment. All five legs replicated green against a scratch copy carrying
the exact edit. **The file is armor-pinned; this function's body is not.**
I have implemented the ruling's substance — the root-cause fixture fix, and
a dated one-line justification comment at the edit site in the
`test_worker_contract.py:502-506` house style — and replaced the prescribed
armor motion with `PIN7`, which asserts the motion's **absence** and is
reddened from the opposite direction by `M38`. Writing a re-pin that is not
owed would have moved a constant no test required to move, which is the
kind of unforced armor churn the `B-1` precedent exists to prevent.

**One item left for the orchestrator, not a question for the user.**
`FW-131`'s missing-file half (the analyst hunting for `card-sections.yaml`)
has no owning unit. It is named in the row; it is not scheduled.

---

## 17. Revision history

- **r1 (2026-08-27)** — first draft, authored at `50fa815`. Corpus,
  attribution census, consumer census and pin census measured; option map
  decided on those measurements; recommendation narrow-build at T1; six
  questions routed. **Gate r1: NOT SOUND** (2 B, 5 M, 7 N, 2 D) — every
  corpus number reproduced; placement, one dead mutation, and four
  mechanism claims failed.
- **r2 (2026-08-27)** — all 16 findings folded in place, plus the six
  rulings. Structural: module moved to top level (`B-1`); reader census
  redefined as a pre-sweep spool listing (`B-2`); accepted writes counted
  as distinct resolved paths (`M-2`); a no-evidence leg added (`M-3`);
  `UN2`'s instrument re-pointed and doubled (`M-4`); every diff-based
  instrument switched to the single-ref form (`M-5`). Retention mechanism
  restated from `backend.py:574/593` and §5.4 re-derived (`M-1`). Pairing
  key (`N-1`), `COR3`'s split positive controls (`N-2`), `G-1`'s 83-routed
  evidence (`N-3`), 18 doctor rows (`N-4`), `M6`'s replacement control
  (`N-5`), a mutation or a `census-only` reason for every criterion
  (`N-6`), the analyst's both-branch wiring and measured leg count
  (`N-7`), sibling worktree paths (`D-1`), the numstat's 5-of-13 label
  (`D-2`). Criteria 29 → 31; mutations 15 → 34. `FW-131` allocated.
  **Gate r2: NOT SOUND** (2 B, 2 M, 5 N, 0 D) — every r1 finding verified
  folded and correct; all four new findings introduced by the `M-3`/`B-2`
  folds themselves.
- **r3 (2026-08-27)** — the four r2 findings and five nits folded.
  Structural: the emission discriminator splits into `events_present` +
  `had_events`, resolving the `COR6`/`COR8` contradiction (`B-1r2`);
  `COR8`'s fixture becomes a monkeypatched `SdkOutcome(tool_events=())` and
  §2.3/§5.1a are restated — the `shim_script` scenario DOES emit a pair
  (`fake_claude.py:531-544`) and the 16 zero-event corpus files are
  historical (`B-2r2`); the reader's census becomes a recursive
  before/after snapshot pair taken at `miner.py:751`, so planted strays and
  early-return residue cancel (`M-1r2`, `N-5r2`); and the live noise mode —
  the multi-write shim announcing only `writes[0]` — is fixed at the root
  in the fixture rather than pinned as expected noise (`M-2r2`), with the
  armor claim **measured rather than assumed** (§16 disagreement 2). Nits:
  `miner.py:774-777` (`N-1r2`), the `run: ` prefix on every emitted line
  with its 168-line log census (`N-2r2`), §15.5 answered NO from the live
  daemon's environment (`N-3r2`), the measured/partially-measured mutation
  split (`N-4r2`). Criteria 31 → **36** (`COR9`–`COR12`, `PIN7`); mutations
  34 → **40** (`M35`–`M40`; `M9`/`M10` re-predicted). Two new measured
  anchors (`A-8` the armor replication, `A-9` the log-prefix census).
  **Gate r3: NOT SOUND** (0 B, 2 M, 4 N, 1 D) — all nine r2 findings verified
  folded; `PIN7`'s argument upheld; both majors introduced by the r3 folds.
- **r5 (2026-08-27)** — two post-SOUND nits + home-path scrub.
- **r4 (2026-08-27)** — the two r3 majors, four nits and one doc fold.
  Structural: the worker's accepted-inside predicate narrowed to
  **parent == `stage_dir()`** (`COR13`/`M41`), because the r3 fixture fix
  would otherwise have made `test_worker.py:1221` report 3 announced writes
  against a flat census of 2 — one false alarm swapped for another
  (`M-1r3`); and §6.6's printed block declared **normative at net −7**, with
  `test_hy5_numstat_bounds_hold` added to `PIN7` and all four spellings
  measured against its `(388, 1)` cap (`M-2r3`). Nits: `miner.py:771-772`
  (`N-1r3`, two sites), the analyst zero-event count 3 → **4** (`N-2r3`),
  `COR9` split into its two residue fixtures with `M36`/`M40` assigned one
  each (`N-3r3`), `S1`'s stale mutation arithmetic (`N-4r3`). Docs: the
  "no base-commit body to pin" quote re-attributed to `test_hy3`'s
  `expected_keys` body (`D-1r3`). Criteria 36 → **37**; mutations 40 →
  **41**. One new measured anchor (`A-10`, the numstat bound under four
  spellings).
