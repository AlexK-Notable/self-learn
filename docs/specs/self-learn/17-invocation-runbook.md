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

## 1. The one switch that is left

*Rewritten 2026-08-25 (U-cleanup, `03-decisions.md` `S-49`). This
section used to describe TWO switches — `backend` (per surface, `cli`
or `sdk`) and `provider` (install-wide, `anthropic` or `bedrock`). The
`cli` invocation backend is now RETIRED: `CliBackend`,
`invocation/cli.py`, the argv builders and settings writers are
deleted, `KNOWN_BACKENDS == ("sdk",)`, and every surface runs on the
Agent SDK unconditionally. There is nothing left to flip a surface
BETWEEN — `backend` is no longer a real switch, it is a single-valued
constant with a refusal wired to its old alternative.*

Self-learn invokes a model on **four surfaces**, all of them on the
Agent SDK. One switch remains live:

| Switch | Scope | Values | Default |
|---|---|---|---|
| `provider` | **install-wide** | `anthropic` · `bedrock` | `anthropic` |

`backend` still exists as an env selector / `config.yaml` key **for one
purpose only: naming the refusal.** Setting `SELF_LEARN_BACKEND[_<SELECTOR>]`
or `invocation.backend[_<surface>]` to `cli` does not select a second
transport — there is none — it makes that surface refuse to run at all,
loudly, through `BackendUnavailable`. The doctor's `switches` row
renders this as `backend=REFUSED (cli retired) (<source>)`, never as an
accepted `backend=cli`. Setting it to anything else unknown (a typo, a
stray capital) folds silently to `sdk`, same as it always has for an
unrecognized value (`SEL5`). **The only working values now are `sdk` and
unset**, and both produce the same behavior — there is no live
distinction left between "pinned to sdk" and "on the default" beyond
what the doctor's `source` column reports for provenance.

`provider=bedrock` no longer has a `backend=cli` staged-rollout carve-out
to worry about (`S-36`'s "silently inert under `cli`" caveat no longer
applies — every surface's own default is already `sdk`); the doctor's
`rollout` row still catches the one way a Bedrock configuration can go
fully inert today — every surface explicitly refused (§3).

The four surfaces, and the three selector names that address them:

| Surface | What it is | Env selector | `config.yaml` key |
|---|---|---|---|
| `worker` | the pre-analysis worker's batch invocation | `WORKER` | `backend_worker` |
| `worker-repair` | the same worker's repair round | `WORKER` (**shared — not independently settable by environment**) | `backend_worker-repair` (**independently settable by config**) |
| `miner-reader` | the nightly transcript miner's reader | `MINER` (**not `MINER_READER`**) | `backend_miner-reader` |
| `analyst` | the one-shot `teach --route` analyst | `ANALYST` | `backend_analyst` |

## 2. The `[sdk]` extra is no longer optional

*Rewritten 2026-08-25 (U-cleanup, `S-49`, which amends `S-43`).
`claude_agent_sdk` used to be an optional dependency a `cli`-only
machine paid nothing for. There is no `cli`-only machine left to protect
— every surface runs on the SDK — so `claude-agent-sdk` is now a hard
dependency of `self-learn-cli`, and a normal `install.sh` run (or `uv
sync --project plugins/self-learn/cli`, no extra flags) brings it in.
The `[sdk]` extra is **retained as an empty alias** so an existing
`pip install 'self-learn-cli[sdk]'` in a script or a runbook keeps
working; it installs nothing beyond what the bare package now installs
unconditionally.*

There is nothing to install before you flip a surface, because there is
no longer a surface to flip between two transports. If `self-learn
doctor invocation`'s `sdk` row ever reports the SDK package as
unimportable on a normal install, that is a broken install, not a
missing optional extra — reinstall rather than reaching for `--extra sdk`.

**One side effect survives unchanged, so it is not a surprise:** now
that `claude_agent_sdk` is importable on every install, `self-learn
--selftest` spawns one real `claude --version` child process **on every
run**, because the selftest's `invocation` check runs the same preflight
the doctor does. This is sanctioned and bounded (`timeout=10`, one
process, three exception classes skip it), and it is the documented
behavior of `FW-94`. There is no install path left that spawns nothing.

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
| `rollout` | SKIP under `anthropic`. Under `bedrock`: FAIL only if **every surface has been explicitly pinned to `cli` and is therefore refused** (`backend=REFUSED (cli retired)`) — the Bedrock configuration then does nothing, because there is no un-refused surface left for it to reach. PASS if no surface is refused, per-surface INFO for the normal mixed state. *(2026-08-25: this state is now RARE rather than the default — every surface's own default is already `sdk`, so hitting it requires actively refusing every one of the four, not simply "not having flipped anything yet.")* |
| `consistency` | Emitted **only** when something is wrong: a `bedrock` surface with no region, or one whose model id is an Anthropic alias. No row means no problem. |
| `region` / `credentials` / `models` / `env` | Bedrock-side checks; SKIP wholesale under `anthropic`. `credentials` is **presence-only** and reports WARN, never FAIL, when it finds nothing — it cannot see an EC2 instance role (`FW-90`). |
| `orphans` | Today always SKIP. It is a reserved extension point, **not** an orphan census — see §5.3. |

A healthy all-defaults machine looks like this (*re-captured 2026-08-25,
post-U-cleanup, `anthropic` install — the `switches` row is the part
that changed; every surface now resolves `sdk` because there is nothing
else left to resolve*):

```
doctor: INFO switches — worker: backend=sdk (default); worker-repair: backend=sdk (default); miner-reader: backend=sdk (default); analyst: backend=sdk (default)
doctor: INFO provider — provider=anthropic (default)
doctor: PASS config — no unknown provider config keys
doctor: WARN sdk — sdk=0.2.134 bundled-cli=2.1.226 host-cli=2.1.235 — versions differ
doctor: SKIP rollout — provider=anthropic — rollout state not applicable
...
doctor: SKIP orphans — no orphan report hook exported by the sdk backend
```

That `WARN sdk` row example (bundled-vs-host `claude` CLI version drift)
predates this rewrite and is kept because the shape is still accurate —
it is normal on a machine that updates its Claude Code install
independently of the SDK's bundled copy, and does not block anything.
There is no `cli` session left to compare a divergent one against; a
large gap is worth investigating on its own terms now.

**Reading the `switches` row is a skill; here is the whole of it.** Each
surface prints `backend=<value> (<source>)`, where `<value>` is `sdk` or
`REFUSED (cli retired)` — nothing else is possible post-U-cleanup. The
source is the rung that answered: `env:SELF_LEARN_BACKEND_ANALYST`,
`config:backend_worker`, `default`, and so on.

> **The tell for a rejected UNKNOWN value: a source that names an env
> var or a config key, next to a value of `sdk` you did not ask for.**
> An unknown backend value (`SDK`, `Sdk`, `agent-sdk`, a typo) folds
> silently to `sdk` (`SEL5`) — the only working value, so this is now
> harmless rather than a downgrade, but the doctor still does **not**
> warn about it. **The tell for a NAMED refusal is louder and different:**
> `backend=REFUSED (cli retired) (<source>)` — that is not silent, and it
> is not a value the doctor folds away; it means the surface will not
> run at all until you remove whatever set it. Values are lowercase
> `sdk`, exactly, or the literal string `cli` if you want the refusal.

An **empty** value is different again: it means "no answer" and falls
through to the next rung, silently and legitimately. With one trap, in
§7.

## 4. The provider switch, if you are going to Bedrock

*§§4.1–4.3 retired 2026-08-25 (U-cleanup, `S-49`).* This section used to
walk through flipping a surface's `backend` between `cli` and `sdk` —
which shell an env var reaches (§4.1), the env-var form (§4.2), and the
`config.yaml` form (§4.3). None of that has a live target left: there is
one backend, every surface already runs on it, and a `backend`/
`backend_<surface>` setting now only ever does one of two things —
select `sdk` (a no-op, since that is already every surface's only
possible value) or select `cli` (a refusal, §1). If you are debugging why
a surface behaves the way it does, the `provider` switch below is the
only one left with two live values to reason about.

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

One thing to know before you do this — reduced from two 2026-08-25
(U-cleanup): the model-vs-backend pairing trap it used to name required
a `cli` surface to exist. It no longer can, so `provider.bedrock.models.*`
is read by every surface unconditionally, and the three model variables
below are only ever a fallback when `provider=anthropic`:

1. **The `provider.bedrock.models.*` entries need a `provider=bedrock`
   AND a model entry for the surface you want them to govern** — an
   entry-less surface under `provider=bedrock` falls back to its own
   model variable, an Anthropic alias, which the `consistency` row below
   will FAIL on. The three variables, spelled out because guessing a
   fourth is exactly what used to be trap 1: **`SELF_LEARN_WORKER_MODEL`**
   (which also governs the repair round — there is no separate repair
   variable), **`SELF_LEARN_MINER_MODEL`**, **`SELF_LEARN_ANALYST_MODEL`**;
   all default to `claude-sonnet-5`.
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
  `SELF_LEARN_INVOKE_TIMEOUT_SECS` or the miner reader's
  `SELF_LEARN_READER_TIMEOUT_SECS` (added 2026-08-26, U-fw100 — FW-100's
  env-override half) — or an unreachable
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
- **The reader session's timeout is env-overridable too** (added
  2026-08-26, U-fw100): `SELF_LEARN_READER_TIMEOUT_SECS`, default 900s,
  same parsing as the worker's `SELF_LEARN_INVOKE_TIMEOUT_SECS` (§5.1).

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

**Amended 2026-08-27 (`U-corrob`).** The "denials empty AND filesystem diff agrees" half of this gate is no longer a manual comparison: the worker and the miner-reader now emit a `run: corroboration MISMATCH …` line whenever the two instruments disagree on a successful run, and a separate line whenever the model reports an accepted write outside the granted root — counts only, filesystem named first, never a status change. Accepted writes are counted as **distinct resolved paths**, not events; the reader's filesystem side is a recursive before/after snapshot pair, so spool residue from an earlier run never counts; and a session whose captured event list is **empty** emits `run: corroboration — no tool events recorded (N file(s) on disk)` rather than a mismatch — a session with zero events is not an instrument, while a transport that captured nothing at all says nothing. **What it still does not cover, stated so nobody reads more into it:** it is silent on a failed or timed-out session (whose accounting is known-incomplete), silent on the repair round (a byte-identical rewrite is an accepted write with zero filesystem change), and silent on the analyst's writes (there are none — the analyst is a `text_session`). **The analyst's denials are no longer silent** (coordinator ruling, 2026-08-28, `DEN3`): `analyze()` gained a keyword-only `charter_denials` accumulator (`FW-107`'s shape) and `teach --route` prints the denial-count line on both branches of its `try` — the same line, whether the run lands or raises. `test_u_sdka.py::test_hy5_numstat_bounds_hold`'s `analyst.py` row, which blocked the first attempt at zero headroom, was re-pinned to the measured `(22, 20)` (armor bookkeeping, not a design constraint — `FW-131`). And `fixtures/trials.md` still has no burn-in entry for any surface — an automatic instrument is not a discharged gate.

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

### 5.6 The end of the road — what deleting the `cli` path required (past tense — it happened)

*Rewritten to past tense 2026-08-25 (U-cleanup, `S-49`). §5.6 used to be
a forward-looking checklist; the deletion it described has landed.*

A burn-in passing does not by itself retire the subprocess path — the
plan reserved that for a final unit (`U-cleanup`) and originally gated it
on five conditions, verbatim: *"U-cleanup preconditions: 14 consecutive
all-sdk days, criteria met, Tier-3 caught nothing, config.yaml
committed, decision row dated."* **The precondition changed under the
decision, and the change is recorded rather than hidden:** on 2026-08-24
the user waived the 14-day soak — *"as long as we have decent test
coverage, then skip the soak; 2 weeks is crazy-town"* — and replaced it
with a measured coverage census (`S-49`, spec §3). What the census found
and what it cost, for anyone auditing the retirement later:

1. **The soak was waived, not completed.** There is no 14-consecutive-day
   production record behind this deletion; there is one production
   datapoint (the first SDK miner run, 2026-08-24 19:20–19:24 PDT, "ok —
   7 landed", 4 m 07 s, 586 MB peak, 0 orphans) and a test-coverage
   argument instead.
2. **Criteria met** — every per-surface gate in §5.1–§5.4, plus the
   cross-cutting pair, as they stood before the waiver.
3. **The T3 armor was migrated, not merely "caught nothing."** The
   original condition assumed T3 (the bash-shim suite) would stay frozen
   and green until deletion. Measured instead: T3 was **142** tests, not
   the plan's 88, and ≈90% of them are worker/repair/attribution
   behaviour tests rather than transport tests — so U-cleanup-A migrated
   them onto the SDK fake CLI rather than freezing and then discarding
   them, and U-cleanup-B deleted only what had no SDK-side counterpart.
   The one real, priced loss: `test_worker_contract.py::
   test_fl2_byte_identity_and_provenance[sdk]`'s cross-backend log-line
   comparison (the differential the two backends' rendering had to
   match on timeout/not-found/unavailable) — replaced by a byte-pin over
   every row of all three template sets, captured while `CliBackend`
   still existed.
4. **`config.yaml` committed** — unchanged as a condition; still the
   right check before trusting a flip's provenance in old history.
5. **The dated decision row** is `S-49` (`03-decisions.md`).

All five are now history, not a checklist to satisfy — `CliBackend`,
`invocation/cli.py`, the three argv builders and the two settings
writers are deleted, `KNOWN_BACKENDS == ("sdk",)`, and `S-39`'s first
consequence (*"the default at every rung stays `cli` until a surface
passes its burn-in"*) is structurally impossible now: there is no `cli`
default left for anything to stay at.

### 5.7 Where results go

Record each burn-in's measurements in `fixtures/trials.md` (the CLI-side
trial log, per `15-orchestration-runbook.md` §1 step 6), and amend §5 of
this document in place with what was actually measurable. A gate that
turned out to be unmeasurable should be rewritten here, not quietly
skipped.

### 5.8 Phase 2 (`serve`) burn-in

`serve` schedules the same producers §5.2 and §5.4 already gate — it
does not add a new producer, so it does not need a new pass/fail
instrument. What it adds is a second *trigger* for the mine job (the
scheduler's own clock, instead of a verb's watchdog or the systemd
timer), and the one thing that trigger could plausibly change is how
much a night's run finds.

- **Recorded before merge (this criterion): candidate volume per night
  within ±1σ of the pre-`serve` nights** — the same instrument §5.2
  already prescribes for the `cli`→`sdk` flip, re-pointed at the
  before/after of adopting `serve` as the scheduler instead of the
  timer. **Collecting it is operator work after the merge**, same as
  the rest of §5 (per §7.4 trap S2C: the burn-in gate is *recording the
  observable*, not *having already observed it* — a criterion can be
  SOUND with the number still unmeasured, because the measurement needs
  a running system this document does not have).
- Nothing else in `serve`'s own behavior is burn-in material: it is
  serial with the same job bodies (`miner.run`, `worker.run`,
  unmodified), the heartbeat and the doctor `serve` row are structural
  facts a test already pins (`test_serve.py`), and H-5 (producers
  commit their own writes) is unchanged by construction — `serve`
  never stages, commits, or pushes.

## 6. Rollback

*Rewritten 2026-08-25 (U-cleanup, `S-49`). Everything below this line
used to be true and no longer is — kept, struck through in spirit but
not in fact, so an operator who remembers the old procedure does not
try it and get confused by the result.*

**Rollback is no longer an environment variable. It is a revert.** There
is no `cli` backend left to set `SELF_LEARN_BACKEND[_<SELECTOR>]` back
to — `CliBackend`, `invocation/cli.py`, the argv builders and settings
writers are deleted from the package you have installed. Setting
`SELF_LEARN_BACKEND_ANALYST=cli` (or any selector) today does not roll
anything back: it makes that surface **refuse to run**, reported through
the doctor's `switches` row as `backend=REFUSED (cli retired) (<source>)`
and through the surface's own log as `Outcome(failure="unavailable")`.
That is a new failure mode, not the old rollback — do not reach for it
expecting the pre-U-cleanup behavior back.

**The actual rollback path, if the Agent SDK transport is broken for
you:**

1. **Identify the last commit before `U-cleanup-B` landed** (the decision
   row `S-49` names the build; `git log --oneline -- plugins/self-learn/cli`
   in the *product* repository, not the ledger, finds it — **but not
   always**: measured 2026-08-26, the merge `163a93e` that `S-49` names is
   absent from that path-filtered log, because history simplification
   hides a merge that is tree-identical to its parent for this path. Use
   `git log --oneline --full-history -- plugins/self-learn/cli`, or take
   the commit immediately preceding the U-cleanup-B commit in the simplified
   log — for this path the two trees are identical, `d704aeb` ≡ `163a93e`)
   and reinstall that revision — `git checkout <sha> -- plugins/self-learn/cli
   && uv sync --project plugins/self-learn/cli`. `uv sync` restores
   `claude-agent-sdk` through the `dev` dependency group, NOT the `[sdk]`
   extra — a `pip install .` or `uv sync --no-dev` will not pull the SDK;
   for an extras-driven install use `--extra sdk` / `pip install
   'self-learn-cli[sdk]'`. Then restart every running surface (the systemd
   units, any shell session with `teach --route` in flight).
2. **This is a real revert, not a flag flip.** It changes which code
   runs, not which value an existing switch reads. Test it before relying
   on it in an incident — the same way you would test reverting any other
   dependency. *Measured 2026-08-26 (FW-116 dry-run, throwaway worktree):
   the revert is clean, `config.py` is byte-identical across U-cleanup so a
   post-cleanup `config.yaml` (Bedrock provider keys included) parses under
   pre-cleanup code with zero warnings, both suites stay green at the
   reverted state, and the roll-forward returns `pyproject.toml`/`uv.lock`
   byte-identical.* To test: run the CLI suite with
   `plugins/self-learn/cli/scripts/suite` (parallel batches, host env
   scrubbed, exit codes captured unpiped — the one sanctioned runner); run
   the UI suite from *inside* `plugins/self-learn/ui` (`cd plugins/self-learn/ui
   && uv run pytest`) — `--project` does not change pytest's cwd, and from
   the repo root the bare module name `support.py` collides across the two
   test trees and breaks UI collection.
3. **`provider` is unaffected.** Rolling back the invocation backend does
   not touch `provider=bedrock`/`anthropic`; that switch still works
   exactly as §4 describes on either side of the revert.

4. **If you rehearse this against a COPY of the ledger, disarm the miner
   first.** Every CLI verb except `mine` and `init` — `doctor` included —
   ticks the background-miner watchdog and spawns a real detached `mine`
   run when the ledger's last completed mine is more than 24 h old (miner.py
   `SELF_LEARN_MINER_AUTOKICK`). Set `SELF_LEARN_MINER_AUTOKICK=0` (or
   `SELF_LEARN_MINER=0` to disable runs entirely) before the first command
   against the copy, and strip the copy's `origin` remote. Measured
   2026-08-26: the dry-run's first `doctor` call landed five real commits in
   the copy before this was noticed. **This trap matters more once `serve`
   exists** (item 5 below) — `serve` is a SECOND thing that can mine a
   ledger copy, on its own schedule, independently of any verb you run by
   hand.

### 6.1 U-engine Phase 2 (`serve`) rollback

Rollback is a revert, same as above — `serve` (`cli/src/self_learn/
serve.py`) and its call sites are ordinary product code, not a switch.

5. **Revert Phase 2 before Phase 1**, if both need undoing — Phase 2
   (`self-learn serve`, the `serve` CLI verb, the `doctor` `serve` row,
   the reduced watchdog in `miner.maybe_kick`) is built on Phase 1 (the
   `sdksession` library); reverting Phase 1 first leaves Phase 2's code
   importing a library that no longer exists.
6. **Re-enable `self-learn-miner.timer`** when reverting Phase 2 — with
   `serve` gone, nothing else fires the nightly mine pass. **Run
   `./install.sh` first, then enable — not bare `enable`.** If the
   timer was ever taken down with `systemctl --user disable --now
   self-learn-miner.timer`, `disable` on a *linked* unit deletes the
   symlink itself, and a linked unit has no package to restore it from
   — a bare `systemctl --user enable --now self-learn-miner.timer` at
   that point fails with "Unit file does not exist" (measured
   2026-08-27). `./install.sh` re-links the timer unit
   (`install.sh` line 103, the `link "$REPO/systemd/self-learn-
   miner.timer" "$UNIT_DIR/self-learn-miner.timer"` call — line 102 is
   the sibling `.service` link, not the timer) and runs `daemon-reload`
   (line 104) before printing the enable line — run it, then enable:
   `systemctl --user enable --now self-learn-miner.timer`. The watchdog's
   reduced disposition (`miner.maybe_kick`'s poke leg) reverts along with
   the rest of `miner.py`'s Phase 2 edit, so the pre-Phase-2 any-verb
   spawn behaviour returns automatically once the code is reverted.
7. **Neither phase touches either `pyproject.toml`.** Unlike the
   U-cleanup revert (item 1 above), nothing about `claude-agent-sdk`'s
   installation changes on either side of a Phase 1 or Phase 2 revert —
   a plain `git checkout <sha> -- plugins/self-learn/cli` (or `.../ui`
   for Phase 1B) is sufficient, no `uv sync` extras juggling.
8. **Test the same way §6's own procedure already prescribes**:
   `plugins/self-learn/cli/scripts/suite` (foreground, from the repo
   root) and the UI suite from *inside* `plugins/self-learn/ui`.

**One caveat that survives the rewrite unchanged.** If you opened the
incident hatch `SELF_LEARN_ENFORCE_SCOPE=0`, close it — see §7. That
hatch's sdk-vs-host-settings semantics are unrelated to which backend is
installed.

### 6.2 U-hostmode rollback

*(Gate r2-M1, strengthened at gate r3-D6: no forward code change can
close this — `MODE10` hardens the new `hosts.yaml` parser, and after a
revert the new parser is gone.)* Reverting this unit leaves any
`mode: plain` **projects** entry silently re-read as a **git** host: the
reverted parser accepts `{path, mode}` and drops the `mode` key
(`hosts.py:150-155`); only a `skills_root` MAPPING raises `HostsError`.
**The hazard is a silent resumption of host commits into a directory the
user chose to keep repo-less, not a crash** — so this revert is not safe
to perform blind. Three numbered steps, in order:

9. **`self-learn host list`** and note every host whose mode reads
   `plain` — `MODE11` is why that column exists (a registry with no
   plain entries needs none of the following, and reverting is a plain
   `git checkout`).
10. **For each plain host, either `git init` it** — making the reverted
    code's git-mode assumption true — **or `self-learn host remove`
    it.** Do this BEFORE reverting: the reverted code has no `--mode`
    flag to make the choice explicit again afterward.
11. **Commit or delete the `<home>/compiled/*.yaml` files, then revert,
    Phase 2 before Phase 1** (same ordering rule as item 5 above, if this
    unit ever grows its own Phase 2). These files are inert to the
    reverted code — nothing in it reads them — **but they are also
    UNSWEPT by it**: the revert takes `compiled/*.yaml` out of
    `_RECONCILABLE`, so any uncommitted record file becomes exactly the
    H-5-corollary orphan `13-hosting-and-separation.md` §4 item 4/§5
    exists to prevent — "committed by nobody, ever … until a clone
    deletes it."

## 7. Traps, all measured

Each of these was reproduced on a real install while this document was
written. *Re-verified against U-cleanup's collapsed `KNOWN_BACKENDS ==
("sdk",)` 2026-08-25 — three of the original seven were DEFUSED by the
same collapse that retired `cli` (noted where it happened, not silently
dropped: a trap that stops mattering is still worth one line saying so).*

1. **`SELF_LEARN_BACKEND_MINER_READER` is not a variable.** The surface
   is named `miner-reader`; the selector is `MINER`. Setting
   `SELF_LEARN_BACKEND_MINER_READER=sdk` does **nothing at all** — no
   warning, exit 0, the surface resolves via its own default (`sdk`),
   exactly as if you had set nothing. Use `SELF_LEARN_BACKEND_MINER`.
2. **`worker-repair` cannot be split by environment, only by config.**
   `SELF_LEARN_BACKEND_WORKER` moves the batch invocation and the repair
   round together. `config.yaml`'s `backend_worker-repair` moves the
   repair round alone. With only one working value left, this now
   matters for **refusal scope**, not backend choice: pinning
   `SELF_LEARN_BACKEND_WORKER=cli` refuses the repair round too; only
   `config.yaml`'s `backend_worker-repair` key can refuse one without the
   other.
3. **DEFUSED (was live under two backends):** a mis-cased value used to
   silently downgrade you to `cli`. `SELF_LEARN_BACKEND=SDK` now folds
   to the only working value, `sdk`, the same as every other unknown
   string (`SEL5`) — harmless, though still worth lowercasing on
   principle, since a `cli` value (correctly cased) is a refusal, not a
   downgrade.
4. **NEUTERED (was live under two backends):** an empty per-surface
   config key still does not fall through to the general one — that part
   of the mechanism is unchanged — but it no longer pins the surface to
   anything dangerous. Given `backend_analyst: ""` alongside `backend:
   sdk`, the analyst resolves to `sdk` via its own per-surface default
   (source `default`), same value as the other three surfaces (source
   `config:backend`) — a provenance difference in the doctor's `source`
   column, not a behavior difference. Still delete keys you do not want
   rather than blank them; the doctor cannot tell you which one you did.
5. **RETIRED — see §4.** A `provider.bedrock.models.*` entry used to be
   inert on a surface still resolved to `cli`; there is no such surface
   left, so this entry is now read unconditionally by every surface once
   `provider=bedrock` is set.
6. **`SELF_LEARN_ENFORCE_SCOPE=0` grants more than "writes."** The hatch
   exists for an incident: it drops the enforcement key from the
   worker's permission scope. Because every surface is now the SDK
   transport, there are no host-level Claude settings in play at all
   (that is the isolation) — the charter takes the open hatch as
   **unconditional approval for every tool that is not on the deny
   list** — the allow returns at rung 2 of the callback, *before* the
   write-family path check ever runs, so it is not scoped to writes. The
   deny list still holds (`Bash`, `Edit`, `Task`, `WebFetch`,
   `WebSearch`, `NotebookEdit` stay denied); everything else is waved
   through. One mitigation worth knowing: the hatch only opens for a
   containment that actually has a write scope, so the **analyst surface
   and the degraded worker containment can never open it** (both have
   empty write sets). *(Retired comparison: this used to be phrased
   "wider on `sdk` than on `cli`," `FW-88` — there is no `cli` left to be
   narrower, so the comparison is gone but the underlying breadth is
   not.)* Open it deliberately, for a bounded incident window, and close
   it in the same session.
7. **Pointing `SELF_LEARN_HOME` at a fresh directory can kick off a
   miner catch-up run.** The 24-hour watchdog fires opportunistically on
   any verb except `mine` and `init` when the last run is stale, and a brand-new home has no last
   run. Harmless against a scratch directory with no ledger repo, but do
   not do it casually against a real one you were only planning to
   inspect.

## 8. When something is wrong

*Rows touching the retired `backend` switch updated 2026-08-25
(U-cleanup, `S-49`).*

| Symptom | First read | Likely cause |
|---|---|---|
| A surface reports `REFUSED` / `Outcome(failure="unavailable")` instead of running | `switches` row's **source** column | `backend=REFUSED (cli retired) (<source>)` — something set that surface's selector (or the coarse `SELF_LEARN_BACKEND`, or a `config.yaml` key) to `cli`. Unset it; §1. There is no partial state to debug further — a `cli` selection is refused everywhere, identically |
| `the "sdk" invocation backend is not built yet` | §2 | `claude_agent_sdk` is not importable in the environment that ran the surface — a genuinely broken/stale install (it is a hard dependency now, so this should not happen on a normal install). Reinstall rather than reaching for an extra flag |
| `doctor` exits 1 | the `FAIL` rows | `rollout` FAIL = Bedrock configured but every surface is refused (§3's `rollout` row). `consistency` FAIL = a `bedrock` surface missing a region or carrying an Anthropic alias. `region` FAIL = no region resolved |
| `WARN sdk … versions differ` | §3 | normal on a host that updates Claude Code independently |
| `WARN credentials — no mechanism found` | `FW-90` | the credential probe is presence-only and never probes IMDS, so an EC2 instance role reads as "nothing found". WARN by design, never FAIL |
| A `config.yaml` edit did not reach the nightly miner or a UI-kicked worker | §4.1 *(retired numbering — the fact survives: `systemd --user` units do not inherit your login shell's environment; both shipped units pin `SELF_LEARN_HOME` and nothing else)* | you exported an env var instead of editing `config.yaml`; the timer/service does not see your shell |
| A leaked `claude` process after a run | §5.3 | an orphan. Log line + `pgrep`; it counts against the miner/worker burn-in gates recorded in §5 |

## 9. Change control

This file follows `forward/platform-drift.md` §4: an engine swap, a
default move, or a new switch gets its dated note here **and** in
`03-decisions.md`. A flip performed without updating §5's measured
results is a flip nobody can audit later. The corpus has already paid
once for a migration that shipped without its documentation
(`drafts/u-docs-truth-sweep-spec.md` §3.1 counts the cost: 42 sites
swept, 12 measured false); this file exists so the flips do not repeat
it.

**2026-08-25 (U-cleanup-B, `03-decisions.md` `S-49`):** the `cli`
invocation backend is retired — `CliBackend`, `invocation/cli.py`, the
argv builders, the settings writers and the `SessionSpec` cli closures
are deleted from the package; `KNOWN_BACKENDS == ("sdk",)`. This is an
engine-removal, not a default move — there was no "other" default left
to move to. Sections §1, §2, §4 (former §§4.1–4.3), §5.6, §6, and §7
traps 1/3/4/5/6 are updated in this same commit to describe the
one-backend world; §5.1–§5.5, §5.7, and §7 traps 2/7 are unchanged
because their subject (per-surface burn-in gates, the systemd-env fact,
the miner catch-up watchdog) never depended on a second transport
existing.

**2026-08-27 (U-engine Phase 2, `03-decisions.md` `S-50` / `14-forward-
work-map.md` `FW-118`–`FW-121`):** a new switch — `self-learn serve`,
a long-lived host process that schedules the nightly mine and its
worker follow-on in place of the per-verb any-command watchdog and (on
hosts that adopt it) `self-learn-miner.timer`. §5.8, §6.1, and §10 are
added in this same commit; §5.2's watchdog description and §3 of
`12-transcript-miner.md` describe the two supported topologies (`serve`-
scheduled and timer-scheduled) rather than picking one, since adopting
`serve` is a per-host deployment choice, not a code default.

## 10. `serve`

`self-learn serve` is a long-lived scheduler, not a new producer. It
starts the same `miner.run` / `worker.run` your terminal already calls
by hand or `self-learn-miner.timer` already calls nightly — on its own
clock, in-process, one job at a time. It never stages, commits, or
pushes on a producer's behalf (H-5 unchanged); each job it starts still
takes its own lock and commits under its own pinned subject.

**Starting and stopping it.** `self-learn serve` runs in the foreground
until it receives `SIGTERM`/`SIGINT`, at which point it finishes its
current tick and exits 0 — there is no separate "stop" verb. Three
supervisor shapes are supported:

- **systemd (Linux, the primary shape):** `systemd/self-learn-host.service`
  (`Type=simple`, `Restart=on-failure`, `RestartSec=5`,
  `ExecStart=%h/bin/self-learn serve`). `install.sh` links the unit
  file into `~/.config/systemd/user/` (or `$XDG_CONFIG_HOME/systemd/user/`
  if that variable is set — U-servehermetic, 2026-08-27, aligning
  `install.sh`'s `UNIT_DIR` with `serve.unit_dir()`'s own resolution) and
  reloads the daemon, but does
  **not** enable or start it — enabling a long-lived host process on a
  live ledger is a deployment decision the installer does not make for
  you. Enable it yourself when you're ready:
  `systemctl --user enable --now self-learn-host.service`.
- **launchd (macOS) or another init system:** no shipped unit yet —
  wrap `self-learn serve` the way you would any other long-lived
  foreground process for that supervisor (a `launchd` plist with
  `KeepAlive`, a `runit`/`s6` service directory, etc.); the process
  itself has no systemd dependency.
- **A plain terminal / `tmux`/`screen` session:** `self-learn serve`
  with no supervisor at all — fine for trying it out, not for unattended
  operation (nothing restarts it if it dies or the terminal closes).

**The heartbeat and doctor's four verdicts.** `serve` writes into its
cache directory (`XDG_CACHE_HOME`-namespaced by ledger, never the ledger
repo itself: `NOT_REPO_TRUTH` in `test_lock_invariant.py`) and nowhere
else — three files, corrected 2026-08-27 (gate r1 M-1): the heartbeat
itself (`serve.heartbeat`: tick time, pid, next scheduled job), a poke
flag (`serve.poke`, §5.3's watchdog handoff — a separate file so a
verb's write and `serve`'s own tick never race each other), and the
day's jittered mine-target (`serve.schedule`, so a restart mid-day does
not recompute a different one). `doctor`'s `serve` row reads the
heartbeat and never calls `systemctl`; it reports one of four verdicts:

| Configured (unit linked)? | Heartbeat state | Verdict |
|---|---|---|
| No | — (no heartbeat expected) | `SKIP` |
| Yes | No heartbeat file | `FAIL` |
| Yes | Fresh (within the tick interval) | `PASS` |
| Yes | Stale (older than the tick interval) | `FAIL` |

**(AMENDED 2026-08-27, U-servehermetic):** "unit linked" is checked by
looking for `self-learn-host.service` under `serve.unit_dir()`, resolved
`SELF_LEARN_SERVE_UNIT_DIR` (explicit override) -> else
`$XDG_CONFIG_HOME/systemd/user` if `XDG_CONFIG_HOME` is set -> else the
real `~/.config/systemd/user`. The `XDG_CONFIG_HOME` leg is new: before
it existed, a test session on any host that had linked the reference
unit read that REAL unit as "configured" with no heartbeat ever written
into the (correctly hermetic) test cache — 18 tests failed the day this
host's unit was linked, none of them touching `serve` on purpose.
`install.sh` evaluates the same `XDG_CONFIG_HOME` rule in the INVOKING
shell's environment at link time, while the systemd user manager
evaluates it independently, in its own environment, whenever it later
reads the unit search path — normally identical, since both usually
inherit the same login environment, but `systemctl --user show-
environment` is what shows the manager's actual view if the two ever
diverge.

The stale-heartbeat `FAIL` is deliberately **LOUD even when `serve` is
dead** — `doctor` is reading a file `serve` last wrote while it was
alive, so a crashed or hung `serve` shows up the next time anyone runs
`doctor`, without needing `serve` itself to still be running to report
its own death.

**Do not run the timer and `serve` as rival schedulers** unless you
mean the timer as a poke. If both `self-learn-miner.timer` and
`self-learn serve` are enabled at once, `doctor` downgrades a would-be
`PASS` on the `serve` row to `WARN` (corrected 2026-08-27, gate r1
D-6: only a `PASS` downgrades — a stale or absent heartbeat with both
enabled still reports `FAIL`, exactly as it would with only `serve`
enabled; a dead `serve` is not made less dead by the timer also being
on). The `WARN` reads: a redundant-but-harmless configuration, not a
broken one — `miner.maybe_kick`'s watchdog checks `serve`'s heartbeat
LAST (corrected 2026-08-27, gate r2 B-1': the disabled/staleness/
cooldown/busy checks all run first, unchanged from before this unit —
a poke fires only where a spawn would have), and when it is fresh, that
would-be spawn turns into a poke (`serve.request_poke`) that makes
`serve` run its next job immediately on its own next tick, instead of
the verb spawning a second detached `mine` process. So a stray timer
firing next to a healthy `serve` degrades to "ran a little earlier than
`serve` would have", not a race between two real miners.

**The reduced watchdog's two legs.** Every CLI verb except `mine` and
`init` still ticks `miner.maybe_kick` on a stale ledger, but its
disposition now has exactly two shapes: **poke** `serve` when its
heartbeat is fresh (above), or **fall back to today's behavior**
(`SELF_LEARN_MINER_AUTOKICK`-gated detached spawn) when it is not — i.e.
no `serve` configured, or `serve` configured but its heartbeat is
stale or absent. The watchdog never blocks on `serve`'s liveness or
tries to start it; a dead `serve` is `doctor`'s problem to surface
loudly, not a verb's problem to route around silently.

## 11. Host modes

*(Added by `U-hostmode`, Phase 1. See `03-decisions.md` `S-51` and
`13-hosting-and-separation.md` §4 item 5 for the full decision text and
mechanism; this section is the operator-facing summary.)*

**What `--mode plain` does and does not do.** A registered host's mode
is set once, at `self-learn host add --mode git|plain <path>`. A
**`plain`** host gets NO commit, NO push, and NO off-machine backup of
its own file, ever, from self-learn — every write lands on disk
uncommitted, and publishing it (or not) is entirely the operator's own
call. It still gets everything else: the managed section compiles and
writes exactly like a `git` host, `--selftest` and `recompile` both work
identically on it (see below), and the compile record still protects it
against a silent regeneration over a hand edit. A **`git`** host (the
default, and every host registered before this unit) is unchanged:
self-learn commits and pushes canon there exactly as it always has.

`host add --mode plain` prints the consent line naming what plain mode
does NOT do, at registration time — read it once; it does not repeat on
every route.

**How to change a host's mode.** The mode is set ONCE and never flips in
place — `self-learn host remove <path>` followed by
`self-learn host add --mode <new-mode> <path>` is the only path from one
to the other. This is deliberate (a silent mode flip mid-flight is a
worse hazard than the two extra commands).

**The `.self-learn-host` marker.** A plain host is gated at registration
and at every route by a `.self-learn-host` marker file the registering
verb writes at the host's root — the structural analogue of `.git` for a
host that has none. `host remove` leaves this marker in place (removing
it would silently invalidate a re-add): the bucket and its records are
untouched by `host remove`, only the compile gate closes.

**`recompile --adopt`, and when to reach for it.** When the compile
record's region verdict for a target reads `edited` (a hand edit inside
the managed markers, on either mode) or `unknown provenance` (a plain
host's target already carries content self-learn has no record of yet),
the next route or recompile against that target REFUSES, naming this
repair: `self-learn recompile --adopt <target>` re-records the on-disk
region as authoritative — it changes no bytes on disk, only the ledger's
own record of what is "clean" going forward. There is no `--force`
anywhere in this path, by design: adopting is the one human decision the
refusal names, never a way to skip it.

**`--selftest` and `recompile` work identically on both modes** — this
is the first thing an operator will assume they do not, and it is worth
stating explicitly: the drift check (`(lrn-…)` entry markers vs. the
ledger's routed records) was never a git check, and `recompile`'s repair
is the same compile, byte for byte, whichever mode the target host is
in. Only the *gate* differs by mode — `git status` for a `git` host, the
compile record for a `plain` one.

**One sentence on user scope, because it is easy to conflate with a
different repo that happens to share a name:** `~/.claude/CLAUDE.md` —
the user-scope canon target — is not in any git repository and has not
been since chezmoi's retirement (measured 2026-08-27:
`git -C ~/.claude rev-parse` exits 128). The local git repo in
`~/.config` is a different thing: `~/.config` is a registered
**project** host, and its `CLAUDE.md` is project-scope canon. Both
statements are true; they are about different files.
