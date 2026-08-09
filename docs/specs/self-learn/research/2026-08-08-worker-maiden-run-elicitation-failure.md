# 2026-08-08 — the worker's maiden run under S-26: the timeout is secondary, elicitation is primary

**Status: measured.** Every number here was produced tonight by controlled
runs on the live host; nothing is inferred from reading code alone. Raw
artifacts (the composed prompt, replay stdout, pre-validation proposal
files, watcher log) are preserved LOCALLY in
`misc/evidence-2026-08-08-worker-maiden/` — that directory contains real
ledger content and is git-excluded; it must never be committed.

## Headline

The first `self-learn worker run` after the S-26 flip (traces mandatory)
failed, and the obvious diagnosis — the 900 s `claude` timeout
(`worker.py INVOKE_TIMEOUT_SECS`) — is real but SECONDARY. A controlled
replay of the exact batch prompt with no effective time limit produced
**2 valid proposals out of 15** under the run's own validator. The
primary defect: **the batch analyst cannot reliably emit traces that
satisfy the S-26 schema's conditional requirements**, and the unattended
pipeline gives it no second chance — output is deleted (correctly, per
S-26's no-fabrication policy) and the retry loop re-runs the same prompt
blind, at ~15 Sonnet-minutes per ~25-minute cycle.

## Chronology (log times UTC; host is PDT = UTC-7)

1. **00:29:51Z** — user-kicked run, batch of 15 (32 eligible, cap
   `BATCH_CAP = 15`, 17 leftover → `worker.dirty` kept). `claude` call
   **timed out at 900 s with zero proposal files written**. Run FAILED,
   0 landed; follow-on window auto-spawned.
2. **00:44:52Z** — follow-on window (600 s coalesce sleep, call started
   ~00:54:52Z). Finished **~857 s** — 43 s under the wall:
   `run: ok — 3 proposal(s), 0 merge, 12 invalid deleted`.
   Deletion breakdown: **5 orphans** (`no pending record` — a concurrent
   attended review session resolved those records mid-run; correct
   sweep, pure confound) + **7 schema-invalid traces** (4×
   `gates.t1.field_shaped.answer must be 'yes' or 'no', got None`, 3×
   `gates.t4.depth_behind_rule.evidence is required here and is
   missing`). Net live yield: **3 valid of the 10 still-pending**.
3. **01:09:12Z** — next follow-on spawned; killed by the user's decision
   at ~01:12Z before its coalesce sleep expired (blind-retry loop, see
   §"Why the loop is unproductive"). `worker.dirty` remains set —
   honest: work remains.

## Controlled measurements

- **Prompt size** (read-only `compose_batch_prompt` on the real ledger):
  **231,443 bytes ≈ 57.5 k tokens** for the 15-record batch. Well inside
  context; the size is not the defect.
- **Permission/startup probe**: a `claude -p` with the worker's exact
  argv shape (same model, `--allowedTools Read,Grep,Glob`, same
  disallowed list, settings file with the `Edit(//…/proposals/**)`
  rule family) against a scratch home wrote its target file in **8 s
  total**. The T13-pinned Edit-family Write scoping is INTACT on claude
  CLI 2.1.226; MCP/startup hang is ruled out.
- **Unbounded replay**: the real batch prompt, path-rewritten onto a
  scratch clone of the ledger (never the real one), same model and tool
  grants, no effective timeout: completed in **745 s (12 m 25 s)**,
  wrote 15 trace-bearing proposal files.
- **Replay validation**: running the run's own `_validate_written`
  over those 15 files: **2 valid, 13 deleted**. Unhurried quality is no
  better than wall-pressured quality — **time pressure is exonerated as
  the cause of the trace defects.**

## The failure catalog (both runs, by validator refusal)

| Validator refusal | replay | live |
|---|---|---|
| `t4.depth_behind_rule.target` must be non-empty when answer is yes | 7 | — |
| `t4.depth_behind_rule.evidence` required and missing | — | 3 |
| `t4.fs.verdict` must be SILENT/COSTLY/LOUD_CHEAP/INDETERMINATE, got None | 3 | — |
| `t1.field_shaped.answer` must be yes/no, got None | — | 4 |
| `t3.scan_terms` must be null when answer is yes | 1 | — |
| containment: quote not found in the record (paraphrase) | 1 | — |
| (orphans — record resolved by concurrent attended session) | — | 5 |

Every schema refusal is a **conditional** requirement — a field whose
required-ness depends on another field's value. The analyst fills the
unconditional fields fine. Which records survive is a lottery on these
conditionals: `lrn-74d0b52b` failed in the replay and passed live;
`lrn-566216a6` passed in the replay. Two independent runs over the same
records produced different survivor sets.

## Why the loop is unproductive

Deleted output produces **no feedback** to the next attempt: the
follow-on re-sends the same prompt to the same model, which makes
substantially the same conditional-field mistakes. Meanwhile the
follow-on chain has **no failure backoff** — a failed run keeps
`worker.dirty` set and unconditionally spawns a successor
(`worker.py:2101`), so a persistent failure burns a full `claude` call
every ~25 minutes indefinitely.

The decisive contrast: the ATTENDED path already contains the missing
mechanism. `proposal validate` **reports** refusals to a session that
fixes and re-validates (review.md's Discuss loop) — and it drained
records tonight, including ones the unattended path had just failed.
The unattended path deletes and retries blind. The asymmetry, not the
timeout, is the product gap.

## Candidate fix scope (for the spec author — evidence-ranked, not binding)

1. **Elicitation contract**: the composed prompt's trace-schema section
   and worked example do not force the conditional requirements the
   validator enforces. State each conditional explicitly at the point
   of output; make the worked example exercise the yes-branches
   (`t4` yes with `target`+`evidence`, `fs.verdict` enum, `scan_terms`
   null-when-yes).
2. **One bounded unattended repair round**: on validation failure,
   re-invoke the model once with the failed files + the validator's
   exact refusal lines, scoped to fixing those fields without changing
   judgments; delete only what still fails. This mirrors the attended
   loop; S-26's no-fabrication policy is preserved (the repair sees the
   record and the refusal, and final deletion remains the backstop).
3. **Timeout headroom**: measured 745–857 s against a 900 s cap for a
   15-record batch — a coin flip by design. Raise the cap and/or lower
   `BATCH_CAP`; note quality did NOT improve unhurried, so batch-size
   reduction is a throughput/latency lever here, not a quality lever.
4. **Follow-on failure backoff**: consecutive-failure counter; stop or
   decay the chain instead of retrying blind forever.
5. Hygiene, cheap: `--strict-mcp-config` on the analyst argv (the
   analyst needs no MCP; today it inherits the user's servers).

## Confounds, honestly

A human review session ran concurrently from ~17:50 PDT: it resolved 5
of the live batch's records mid-run (the orphan sweeps above) and its
resolutions moved the pending set between measurements. The replay and
the probe are unconfounded (scratch-isolated). Live-run counts other
than the timeout and the refusal reasons should not be quoted without
this caveat.
