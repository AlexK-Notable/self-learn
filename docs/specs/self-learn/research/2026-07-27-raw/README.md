# Raw subagent output — 2026-07-27 routing/pin investigation

**This directory is not corpus. Nothing in it is verified, ratified, or
binding.**

These are the verbatim final reports of nine subagents, preserved because
some of them contain measurements that cannot be reconstructed — in
particular `analyst-probe-runs.jsonl`, the 38 raw live analyst outputs.

## How to use this directory

Two consolidated records sit above this directory, and each has a raw file
here backing it:

- [`../2026-07-27-routing-monoculture-and-pin-audit.md`](../2026-07-27-routing-monoculture-and-pin-audit.md)
  — the investigation (backs everything except `status-review.md`).
- [`../2026-07-27-status-review.md`](../2026-07-27-status-review.md) — the
  evening status review (backs `status-review.md`).

Read the relevant one **first**. Those documents are the findings records:
each carries the orchestrator's
independent re-verification, marks every claim **[V]** verified / **[R]**
reported / **[U]** user ruling, and states what the investigation does *not*
establish.

Come here only for detail the findings record summarises — a full rationale,
an experiment's raw runs, a per-file table. **When this directory and the
findings record disagree, the findings record wins**, because its claims were
re-checked and these were not.

## Why the warning is not boilerplate

§5 of the findings record documents how this project's most consequential
routing defect came about: an agent wrote an assertion, cited a spec section
that does not contain it, and every later agent treated it as settled law.
The destination it closed off was used zero times in 28 routings.

These files are exactly that hazard in bulk — ~4,500 lines of confident,
well-formatted agent prose, sitting inside a spec corpus, where a future
agent doing a `grep` will find them. Some of their claims are wrong; at
least one was corrected by measurement during the session (two agents
disagreed about whether an excerpt bug was live, and one had generalised
from a single file).

So: **do not cite these files as a reason to build or not build anything.**
An item graduates by becoming an FW row, a spec, or an `03` decision — never
by being quoted from here.

## Contents

| File | Agent | Model |
|---|---|---|
| `project-survey.md` | Bird's-eye survey of surfaces, trajectory, neglect | Fable |
| `monoculture-structural.md` | Routing code + UI reachability | Opus |
| `monoculture-prompt.md` | The doctrine as the analyst's system prompt | Opus |
| `analyst-probe.md` | 38 sandboxed live analyst spawns | Opus |
| `analyst-probe-runs.jsonl` | The 38 raw runs — **primary measurement data** | — |
| `reference-control-group.md` | Why one bucket escaped the monoculture | Sonnet |
| `new-skill-mechanism.md` | Does new-skill creation work, and at what scope | Opus |
| `pin-audit.md` | Pin provenance and consequence accounting | Opus |
| `cache-detritus.md` | The 1.1 GB test-cache leak | Opus |
| `status-review.md` | Independent status review (evening; neutrally prompted) | Fable |

Models per `03` S-18. Every agent ran ledger-read-only, with no mutating
verbs, and left both repo trees clean.
