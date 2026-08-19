# 17 — Invocation runbook: flipping, watching, and putting back the model transport

*Authored 2026-08-19 (U-docs, Wave 2 of the Agent-SDK migration). This
is the **operator's** document — the reader is a human at a terminal with
this software installed, not an agent running a build round (that is
`15-orchestration-runbook.md`). Test of done: an operator who has never
read a spec can flip one surface, tell whether it worked, watch it for a
week against written gates, and put it back — from this document alone.*

*Normative authority stays with `03-decisions.md` (`S-34`, `S-35`,
`S-36`, `S-39`, `S-40`) and the unit specs under `drafts/`. This file is
the practice, not the policy. Where it disagrees with the code, the code
wins and this file is the defect — report it.*

## 1. The two switches

Self-learn invokes a model on **four surfaces**. Two switches decide how.

| Switch | Scope | Values | Default |
|---|---|---|---|
| `backend` | **per surface** | `cli` (a `claude -p` subprocess) · `sdk` (an in-process `claude_agent_sdk` session) | `cli`, at every rung, on every surface |
| `provider` | **install-wide** | `anthropic` · `bedrock` | `anthropic` |

They are orthogonal. `backend=sdk` with `provider=anthropic` is a normal,
supported configuration — it is the one every flip in this migration
produces. `provider=bedrock` **requires** `backend=sdk` to do anything at
all: under `backend=cli` a Bedrock configuration is silently inert **by
design** (`S-36`), because a staged rollout means some surfaces are still
on `cli` while others are not. That is not a bug and the software will
not warn you about it per-invocation; the doctor's `rollout` row is what
catches a configuration that is inert *everywhere*.

The four surfaces, and the three selector names that address them:

| Surface | What it is | Env selector | `config.yaml` key |
|---|---|---|---|
| `worker` | the pre-analysis worker's batch invocation | `WORKER` | `backend_worker` |
| `worker-repair` | the same worker's repair round | `WORKER` (**shared — not independently settable by environment**) | `backend_worker-repair` (**independently settable by config**) |
| `miner-reader` | the nightly transcript miner's reader | `MINER` (**not `MINER_READER`**) | `backend_miner-reader` |
| `analyst` | the one-shot `teach --route` analyst | `ANALYST` | `backend_analyst` |

## 2. Before you flip anything: install the extra

The `sdk` backend needs an optional dependency that a normal install does
**not** bring in. `install.sh` runs `uv sync --project
plugins/self-learn/cli` with no extras.

```
uv sync --project plugins/self-learn/cli --extra sdk
# or, for a pip-installed copy:
pip install 'self-learn-cli[sdk]'
```

Without it, a surface flipped to `sdk` refuses at invocation time with:

```
the "sdk" invocation backend is not built yet — install it with:
    pip install 'self-learn-cli[sdk]'
```

That refusal is a clean failure, not a crash — the surface reports
`unavailable` and the run ends — but it is a wasted run. Install first.

**Side effect of installing the extra, so it is not a surprise:** once
`claude_agent_sdk` is importable, `self-learn --selftest` spawns one real
`claude --version` child process **on every run**, because the selftest's
`invocation` check runs the same preflight the doctor does. This is
sanctioned and bounded (`timeout=10`, one process, three exception
classes skip it), and it is the documented behavior of `FW-94`. Installs
without the extra spawn nothing.

## 3. The preflight ritual — run this before and after every change

```
self-learn doctor invocation
```

**Run it twice: once before you touch anything, once after.** Diff the
two. That is the ritual; everything below is how to read the output.
`FW-89` assigns this document one line and this is it: *run
`self-learn doctor invocation` after any `provider` or `backend`
change.*

The command prints one line per check, `doctor: <VERDICT> <row> — <detail>`,
then a `doctor: ---` separator and a handoff block of flat
`field = value` pairs. Verdicts are `PASS`, `WARN`, `FAIL`, `SKIP`,
`INFO`. **Exit code is 1 if any row FAILs, 0 otherwise.**

The rows, in the order they print:

| Row | What it tells you |
|---|---|
| `switches` | **The one you came for.** One INFO line naming every surface's resolved backend *and the rung that decided it*. |
| `provider` | Resolved provider and its source. |
| `config` | Whether `config.yaml`'s `provider:` section contains keys the software does not know. |
| `sdk` | Whether `claude_agent_sdk` is importable, its version, and the bundled vs host `claude` CLI versions. WARN when they diverge. |
| `rollout` | SKIP under `anthropic`. Under `bedrock`: FAIL if *every* surface is still `cli` (the configuration does nothing at all), PASS if all four are `sdk`, per-surface INFO for the normal mixed state. |
| `consistency` | Emitted **only** when something is wrong: a `bedrock`+`sdk` surface with no region, or one whose model id is an Anthropic alias. No row means no problem. |
| `region` / `credentials` / `models` / `env` | Bedrock-side checks; SKIP wholesale under `anthropic`. `credentials` is **presence-only** and reports WARN, never FAIL, when it finds nothing — it cannot see an EC2 instance role (`FW-90`). |
| `orphans` | Today always SKIP. It is a reserved extension point, **not** an orphan census — see §5.3. |

A healthy all-defaults machine looks like this (real output, an
`anthropic` install with the `[sdk]` extra present):

```
doctor: INFO switches — worker: backend=cli (default); worker-repair: backend=cli (default); miner-reader: backend=cli (default); analyst: backend=cli (default)
doctor: INFO provider — provider=anthropic (default)
doctor: PASS config — no unknown provider config keys
doctor: WARN sdk — sdk=0.2.134 bundled-cli=2.1.226 host-cli=2.1.235 — versions differ
doctor: SKIP rollout — provider=anthropic — rollout state not applicable
...
doctor: SKIP orphans — no orphan report hook exported by the sdk backend
```

That `WARN sdk` is normal on a machine that updates its Claude Code
install independently of the SDK's bundled copy. It is worth knowing
about — a large gap is the first thing to suspect when an `sdk` session
behaves differently from a `cli` one — but it does not block a flip.

**Reading the `switches` row is a skill; here is the whole of it.** Each
surface prints `backend=<value> (<source>)`. The source is the rung that
answered: `env:SELF_LEARN_BACKEND_ANALYST`, `config:backend_worker`,
`default`, and so on.

> **The tell for a rejected value: a source that names an env var or a
> config key, next to a value of `cli`.** An unknown backend value
> (`SDK`, `Sdk`, `agent-sdk`, a typo) is folded to `cli`. The doctor does
> **not** warn about this — deliberately, because the real invocation
> path already warns and a second copy would double-print — so the
> mismatch between "you clearly set something" and "the answer is the
> default value" is your only signal here. Values are lowercase `cli` or
> `sdk`, exactly.

An **empty** value is different again: it means "no answer" and falls
through to the next rung, silently and legitimately. With one trap, in
§7.

## 4. Flipping a surface

### 4.1 Read this before you type an export

**A `systemd --user` unit does not inherit your login shell's
environment.** Both shipped units say so in their own comments and both
pin `SELF_LEARN_HOME` and nothing else. The consequence is not subtle:

> **For the miner and the worker, an environment variable exported in
> your terminal will not reach the run that matters.** The nightly miner
> is started by `self-learn-miner.timer`. A worker kicked from the web UI
> is started by `self-learn-ui.service`. Neither sees your shell.
> **For those two surfaces, `config.yaml` is the only flip that reaches
> every launch path.**

Environment variables are the right tool for the **analyst** (which runs
in the shell where you typed `teach --route`) and for a **worker you run
by hand** in that same shell. They are the wrong tool for anything on a
timer.

### 4.2 Environment flips — one shell, one surface

```sh
# analyst — the Wave-2 flip target, and the one an env var suits
SELF_LEARN_BACKEND_ANALYST=sdk self-learn teach --route ...

# for a whole shell session
export SELF_LEARN_BACKEND_ANALYST=sdk

# miner reader — note the selector is MINER, not MINER_READER
export SELF_LEARN_BACKEND_MINER=sdk

# worker — moves the batch invocation AND its repair round together
export SELF_LEARN_BACKEND_WORKER=sdk

# everything at once (the coarse rung; per-surface vars still win over it)
export SELF_LEARN_BACKEND=sdk
```

Verify every one of these with `self-learn doctor invocation` in the same
shell. If the `switches` row does not name the variable you just set as
the source, it did not take.

### 4.3 Config flips — the durable kind

Edit `<ledger-home>/config.yaml` — the same committed file `S-10`'s
`one_motion_route:` lives in. It is a git repository the operator commits
and pushes; putting the transport decision there means it is versioned,
synced and revocable by commit.

```yaml
invocation:
  backend_analyst: sdk          # one surface
  backend_miner-reader: sdk     # note the hyphen — the key is the surface name
  backend_worker: sdk
  backend_worker-repair: sdk    # settable here even though the env var cannot split it
  backend: sdk                  # coarse fallback for any surface without its own key
```

Commit it. Then run the doctor and confirm each `switches` entry reads
`(config:backend_<surface>)` or `(config:backend)`.

**Never put a credential in this file.** Not an access key, not a secret,
not a session token, not a path to one expecting it to be read. `S-37`
makes this absolute: every credential check this software performs is
presence-only, and the file is committed to a git repository.

### 4.4 The provider switch, if you are going to Bedrock

```yaml
provider:
  name: bedrock
  bedrock:
    region: <aws-region>
    profile: <aws-profile-name>     # a NAME, never a credential
    models:
      worker: <bedrock-model-or-inference-profile-id>
      miner: <bedrock-model-or-inference-profile-id>
      analyst: <bedrock-model-or-inference-profile-id>
```

or by environment: `SELF_LEARN_PROVIDER`, `SELF_LEARN_BEDROCK_REGION`,
`SELF_LEARN_BEDROCK_PROFILE`.

Two things to know before you do this:

1. **The `provider.bedrock.models.*` entries are read only by the `sdk`
   backend.** A surface still on `cli` emits whatever its own model
   variable says — an Anthropic alias — regardless of what you put here.
   The three variables, spelled out because guessing a fourth is exactly
   trap 1: **`SELF_LEARN_WORKER_MODEL`** (which also governs the repair
   round — there is no separate repair variable),
   **`SELF_LEARN_MINER_MODEL`**, **`SELF_LEARN_ANALYST_MODEL`**; all
   default to `claude-sonnet-5`. Flip the surface and set the model
   together, or the model setting does nothing.
2. **Run the doctor.** Under `provider=bedrock`, the `consistency` row
   will FAIL loudly on the two mistakes that matter (no region; an
   Anthropic alias where a Bedrock id belongs), and `rollout` will FAIL
   if you configured Bedrock and forgot to flip any surface at all. The
   whole failure class beyond that — IAM denials, model access not
   granted, region not enabled, throttling — **cannot** be reached
   without a live call (`FW-92`). The handoff block at the bottom of the
   doctor's output is what you paste into a support conversation when one
   of those bites.

## 5. Burn-in — what must hold before a surface's flip becomes the default

**Nothing here is automatic.** No default moves because a gate passed;
moving a default is a deliberate act, and these are the conditions for
taking it.

The gates below are transcribed from the approved migration plan
(2026-08-09); this document is their first written form in the
repository, so **if the plan's wording differs, the plan wins and this
section is the defect.** Where a gate names an instrument that does not
exist yet, that is said here rather than quietly softened.

The order is fixed: **analyst → miner → worker** (`S-40`) — the plan's
reason, verbatim: *"attended-first; the analyst flip is also the F3
security fix; worker last — it commits to the ledger."* The middle
clause is the one people forget: **the analyst flip is not a trial run,
it is a security fix**, because today that surface's tools fall through
to the host's own permission default (`S-41`).

### 5.1 Analyst

Plan text: *"analyst = 10 clean attended routes + injected-timeout lands
in pending + trace shape unchanged vs CLI control."*

Remember what else this flip carries: it is the F3 hardening — deny-list,
deny-all-writes callback, strict MCP, isolation — arriving on a surface
that today has none of them (`S-41`). Watch it accordingly.

- **10 clean attended routes.** Ten real `teach --route` runs on the
  `sdk` backend that produce a proposal the human accepts, with no
  traceback and no lost capture.
- **An injected timeout lands in `pending/`.** Force a timeout (a
  deliberately tiny `SELF_LEARN_ANALYST_TIMEOUT` — seconds, no `_SECS`
  suffix on this one, unlike the worker's
  `SELF_LEARN_INVOKE_TIMEOUT_SECS` — or an unreachable
  transport) and confirm the lesson you typed is **captured to
  `pending/`** rather than lost to a traceback. This is the leg
  `FW-87`/`S-41` exists for: the error contract must catch into
  `AnalystError` on **both** backends. Do this one first; it is the leg
  most likely to be wrong.
- **Trace shape matches a `cli` control.** Run the same record through
  both backends and diff the two proposal files. The decision-trace
  fields (`gates:`, `flags:`, `recommendation:`) must be present and
  schema-valid on both. Content will differ — it is a model — but shape
  must not.

### 5.2 Miner

Plan text: *"miner = 5 clean nightly cycles + 0 orphans at 09:00
(scripted pgrep via doctor) + volume ±1σ."*

- **5 clean nightly cycles** on `sdk`, back to back. What "clean" looks
  like from outside: the run's own log line reports a completed pass and
  a landed artifact, and `self-learn mine status` shows the run
  recorded with a fresh `last-run`. (Do **not** go looking for a
  per-run artifact filename — the miner writes one fixed
  `mine-output.json` into the spool and **deletes everything else there
  as litter**, so an artifact census tells you nothing about which run
  produced it. The run id lives in the log, not on disk.)
- **0 orphans, checked at 09:00** — i.e. hours after the nightly run has
  finished, so anything still alive is genuinely leaked rather than
  merely in flight. The plan says *"scripted pgrep via doctor"*; **that
  hook does not exist yet** — see §5.3.
- **Volume within ±1σ of the `cli` baseline.** Candidate counts per
  night, compared against the preceding `cli` nights. A miner that
  suddenly finds half as much has changed behavior, not just transport.

### 5.3 How to measure "0 orphans" today, since the doctor cannot

The plan's instrument is a scripted `pgrep` surfaced through the doctor.
**It is not built.** The doctor's `orphans` row prints `SKIP — no orphan
report hook exported by the sdk backend` and will keep doing so until
something exports `invocation_sdk.orphan_report`; the row is a reserved
slot, not a census. Until it exists, measure the same fact by hand — the
plan's intent (nothing of ours is still running at 09:00) is what the
gate is for, and these two checks establish it:

1. **Log lines.** The SDK backend sweeps a recorded child pid before
   every connect and logs one line per outcome. Grep the worker/miner log
   for `run: sdk backend: orphan sweep for` — the six outcomes are
   `killed stale pid N`, `found no live process at pid N`, `could not
   corroborate pid N`, `declined (pid N cmdline mismatch)`, `declined
   (pid N not stale)`, `declined (malformed sidecar)`. A clean night
   logs **nothing at all** (the sweep
   is silent when there is no sidecar to sweep). A `killed stale pid`
   line means a previous run leaked a child — that is an orphan, and it
   counts against the gate.
2. **Process census.** After a run completes, `pgrep -af claude` should
   show nothing belonging to self-learn. Do this at a moment when no
   interactive Claude Code session is open, or you will count your own.

### 5.4 Worker

Plan text: *"worker = 5 clean unattended mine→worker cycles incl. ≥1
repair round + 0 out-of-scope write attempts (`Outcome.denials` empty AND
filesystem diff agrees) + clean commit/push."*

- **5 clean unattended mine→worker cycles**, including **at least one
  repair round** (the repair invocation is a separate surface with a
  separately narrowed permission scope; a burn-in that never exercises it
  has not tested half the worker).
- **0 out-of-scope write *attempts*** — note "attempts", not "writes.
  The gate is deliberately **two instruments that must agree**:
  `SdkOutcome.denials` is empty (nothing was refused, so nothing was
  even tried), **and** the filesystem diff agrees (nothing landed outside
  the granted stage). Either alone is insufficient, and they fail
  differently: a denial with a clean diff means the containment worked
  and something tried anyway — worth investigating, not ignoring; a clean
  denials list with a dirty diff means the containment did **not** see
  the write, which is far worse. **The filesystem diff is the
  authority** (`S-44`): `denials` is the model's own accounting, and a
  self-report is corroboration, never provenance.
- **Note the asymmetry**: `denials` exists only on `SdkOutcome`. The
  `cli` backend returns a bare `Outcome` and has no such field, so this
  half of the gate has no `cli` control — which is precisely why the plan
  pairs it with the filesystem diff, the half that works identically on
  both backends.
- **A clean commit and push.** The worker's own commit lands and the
  operator's push succeeds — no half-written state, no
  `landed-uncommitted`.

### 5.5 Cross-cutting — and the honest gap in it

Plan text: *"Cross-cutting: cost ≤ 1.5× CLI baseline, and isolation
should make runs CHEAPER — if not, settings loaded and isolation is fake
(the single most informative signal)."*

- **Cost ≤ 1.5× the `cli` baseline**, and — the plan's own words, *"the
  single most informative signal"* — **isolation should make `sdk`
  CHEAPER, not dearer.** The
  SDK session runs with `setting_sources=[]` and `settings=None`, which
  means it loads **no** settings file and **no** CLAUDE.md; the `cli`
  child inherits the host's. Fewer input tokens should follow. **If the
  `sdk` path is not cheaper, the most likely explanation is that the
  isolation is not real — that settings are being loaded after all — and
  that is worth stopping for.** Treat a cost surprise as an isolation
  bug until proven otherwise.
- **The gap, stated plainly: there is no `cli`-side cost instrument in
  this product.** The `sdk` backend records `cost_usd` and `turns` on its
  outcome; the `cli` backend records neither and has no code path that
  would. **Ruled 2026-08-19: the denominator comes from the operator's
  own billing surface — the API console's usage for the window — not
  from the product.** So the measurement is: read the console for a
  comparable `cli` window, read it again for the `sdk` window, compare.
  An external control run of `claude -p --output-format json` capturing
  `total_cost_usd` is the finer-grained alternative if a per-run number
  is wanted. Tracked as `FW-95`; **settle the method before the first
  burn-in closes**, because a ratio argued about after the fact is a
  ratio nobody trusts.

### 5.6 The end of the road — what deleting the `cli` path requires

A burn-in that passes does not retire the subprocess path. The plan
reserves that for a final unit (`U-cleanup`) and gates it on five
conditions, verbatim: *"U-cleanup preconditions: 14 consecutive all-sdk
days, criteria met, Tier-3 caught nothing, config.yaml committed,
decision row dated."*

Read as an operator checklist:

1. **14 consecutive all-sdk days.** Not fourteen days since the first
   flip — fourteen with *every* surface on `sdk` and none rolled back.
2. **Criteria met** — every per-surface gate in §5.1–§5.4, plus the
   cross-cutting pair.
3. **Tier-3 caught nothing.** Per the tier table (`U-fake` `Tiers-1`),
   **T3 is the existing bash-shim suite, frozen — byte-identity
   regression armor for the `cli` path**, kept unchanged precisely until
   the cleanup unit deletes that path. "T3 caught nothing" therefore
   means: over the 14 days, no T3 test went red, i.e. the `cli` path
   never regressed while nobody was using it. It is a check that the
   thing you are about to delete was still healthy when you deleted it.
   **T3 is not the cross-backend contract suite** — that is **T2**
   (parametrized over `["cli", "sdk"]`) — and **no tier invokes a real
   `claude`**: T2 runs the bash shim against the SDK fake CLI, T1 runs
   the in-process `FakeBackend`. Nothing in the tier stack is evidence
   about live behavior; the burn-in gates above are.
4. **`config.yaml` committed** — the flip is in the ledger's git history,
   not living in somebody's shell profile. This is the condition most
   likely to be quietly false; check it with `git log` in the ledger, not
   from memory.
5. **A dated decision row** in `03-decisions.md` recording the retirement.

Until all five hold, the `cli` path stays, and `S-39` keeps its first
consequence: **the default at every rung stays `cli` until a surface
passes its burn-in.**

### 5.7 Where results go

Record each burn-in's measurements in `fixtures/trials.md` (the CLI-side
trial log, per `15-orchestration-runbook.md` §1 step 6), and amend §5 of
this document in place with what was actually measurable. A gate that
turned out to be unmeasurable should be rewritten here, not quietly
skipped.

## 6. Rollback

**Rollback is an environment variable, and it takes effect on the next
invocation.** There is no code change, no reinstall, no migration, no
state to unwind. Every rung's default is `cli`, so removing your setting
is itself the rollback.

```sh
# the surgical form — put one surface back
export SELF_LEARN_BACKEND_ANALYST=cli

# the blunt form — put everything back, overriding any config.yaml
export SELF_LEARN_BACKEND=cli
```

For a config-driven flip, delete or flip the key in
`<ledger-home>/config.yaml` and commit. Remember §4.1: for the miner and
the worker, the config file is what the timer reads, so **an env-var
rollback in your shell does not roll back the nightly run.** If you need
the nightly run stopped *now*, the env var will not do it — edit the
config, or disable the timer (`systemctl --user stop
self-learn-miner.timer`).

Confirm with the doctor. Then the next invocation of that surface uses
`cli`; an invocation already in flight is not affected either way.

**One rollback caveat that is not a rollback.** If you opened the
incident hatch `SELF_LEARN_ENFORCE_SCOPE=0` while on `sdk`, close it
too — see §7.

## 7. Traps, all measured

Each of these was reproduced on a real install while this document was
written. None of them produces an error message.

1. **`SELF_LEARN_BACKEND_MINER_READER` is not a variable.** The surface
   is named `miner-reader`; the selector is `MINER`. Setting
   `SELF_LEARN_BACKEND_MINER_READER=sdk` does **nothing at all** — no
   warning, exit 0, all four surfaces still `cli`. Use
   `SELF_LEARN_BACKEND_MINER`.
2. **`worker-repair` cannot be split by environment, only by config.**
   `SELF_LEARN_BACKEND_WORKER` moves the batch invocation and the repair
   round together. `config.yaml`'s `backend_worker-repair` moves the
   repair round alone. If you want them different, use the config file.
3. **A mis-cased value is silently downgraded.** `SELF_LEARN_BACKEND=SDK`
   resolves to `cli`, and the doctor prints no warning (§3's tell is your
   only signal). Lowercase, always.
4. **An empty per-surface config key does not fall through to the
   general one — it pins that surface to `cli`.** Given
   `backend_analyst: ""` alongside `backend: sdk`, the other three
   surfaces get `sdk` and the analyst gets `cli`, reported as source
   `default`. There is no way to see from the doctor's output that the
   empty key caused it. Delete keys you do not want; do not blank them.
5. **A `provider.bedrock.models.*` entry is inert on a `cli` surface.**
   Set the model and flip the surface in the same change, or the model
   setting silently does nothing.
6. **`SELF_LEARN_ENFORCE_SCOPE=0` is wider on `sdk` than on `cli` — and
   wider than "writes" even there.** The hatch exists for an incident: it
   drops the enforcement key from the worker's permission scope. On the
   `cli` path, what happens next is decided by the **host's own** Claude
   settings. On the `sdk` path there are no host settings in play at all
   (that is the isolation), so the charter takes the open hatch as
   **unconditional approval for every tool that is not on the deny
   list** — the allow returns at rung 2 of the callback, *before* the
   write-family path check ever runs, so it is not scoped to writes.
   The deny list still holds (`Bash`, `Edit`, `Task`, `WebFetch`,
   `WebSearch`, `NotebookEdit` stay denied); everything else is waved
   through. Two mitigations worth knowing: the hatch only opens for a
   containment that actually has a write scope, so the **analyst surface
   and the degraded worker containment can never open it** (both have
   empty write sets); and on a host whose global settings are strict, the
   `sdk` hatch is **wider than the `cli` hatch would have been**
   (`FW-88`). Treat this variable as sdk-semantics-only: open it
   deliberately, for a bounded incident window, and close it in the same
   session.
7. **Pointing `SELF_LEARN_HOME` at a fresh directory can kick off a
   miner catch-up run.** The 24-hour watchdog fires opportunistically on
   any verb except `mine` and `init` when the last run is stale, and a brand-new home has no last
   run. Harmless against a scratch directory with no ledger repo, but do
   not do it casually against a real one you were only planning to
   inspect.

## 8. When something is wrong

| Symptom | First read | Likely cause |
|---|---|---|
| A surface you flipped still says `cli` | `switches` row's **source** column | source names your variable → the value was rejected (case? typo?). Source says `default` → your variable is not in this process's environment (systemd? a different shell? an empty config key?) |
| `the "sdk" invocation backend is not built yet` | §2 | the `[sdk]` extra is not installed in the environment that ran the surface |
| `doctor` exits 1 | the `FAIL` rows | `rollout` FAIL = Bedrock configured, nothing flipped. `consistency` FAIL = a `bedrock`+`sdk` surface missing a region or carrying an Anthropic alias. `region` FAIL = no region resolved |
| `WARN sdk … versions differ` | §3 | normal on a host that updates Claude Code independently; investigate only if `sdk` and `cli` runs behave differently |
| `WARN credentials — no mechanism found` | `FW-90` | the credential probe is presence-only and never probes IMDS, so an EC2 instance role reads as "nothing found". WARN by design, never FAIL |
| The nightly miner did not flip | §4.1 | you exported an env var; the timer does not see it. Use `config.yaml` |
| A leaked `claude` process after an `sdk` run | §5.3 | an orphan. Log line + `pgrep`; it counts against the miner/worker burn-in |

## 9. Change control

This file follows `forward/platform-drift.md` §4: an engine swap, a
default move, or a new switch gets its dated note here **and** in
`03-decisions.md`. A flip performed without updating §5's measured
results is a flip nobody can audit later. The corpus has already paid
once for a migration that shipped without its documentation
(`drafts/u-docs-truth-sweep-spec.md` §3.1 counts the cost: 42 sites
swept, 12 measured false); this file exists so the flips do not repeat
it.
