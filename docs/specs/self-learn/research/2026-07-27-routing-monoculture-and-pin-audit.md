# Research — routing monoculture, delivery hole, and the pin-provenance audit

*2026-07-27. Six parallel investigations run at the user's direction after
they asked why every lesson they had ever seen routed to a CLAUDE.md file.
Orchestrated main-session; findings re-verified independently by the
orchestrator before entry here.*

**What this document is:** a findings record. Every claim carries a
provenance mark and, where verified, the command or file:line that settles
it.

**What this document is NOT — read this before citing it:** it is not a
spec, not a decision, and not authority. Nothing here is ratified. No
future agent may cite a finding in this file as a reason a thing must be
built, or must not be. This caution is not boilerplate: §5 of this very
document records that the project's largest routing defect originated as an
agent-authored assertion that a later agent cited as settled law. A findings
record that becomes law reproduces the exact failure it documents. Items
graduate by becoming an FW row, a spec, or a `03` decision — never by being
quoted from here.

## 0. Provenance key

| Mark | Meaning |
|---|---|
| **[V]** | Verified by the orchestrator in-session, independently of the agent that reported it. Evidence given inline. |
| **[R]** | Reported by a subagent, plausible, **not** independently re-verified. Treat as a lead. |
| **[U]** | A user ruling made this session, quoted verbatim. |

Where a **[V]** check could have failed open, the positive control that
proves it discriminates is stated with it. Several findings below were
initially mis-assessed by the orchestrator precisely because a check
returned empty for the wrong reason; see §10.

## 1. Method

Six subagents, source-blind to each other, each required to cite `file:line`
and to mark what it could not verify. Models per S-18: Opus for the five
analytical/diagnostic agents, Sonnet for the corpus-comparison agent.
Constraints applied to every agent: ledger read-only, no mutating verbs, no
`sudo`, no `chezmoi`, repo tree left clean, all six env vars redirected for
any test run.

1. Project survey (bird's-eye: surfaces, trajectory, under-developed areas)
2. Monoculture — structural lens (routing code, UI reachability)
3. Monoculture — prompt lens (the doctrine as the analyst's system prompt)
4. Empirical analyst probe (38 sandboxed live analyst spawns)
5. `reference`-routing control group (the one bucket that escaped)
6. Pin provenance and consequence audit
7. Cache-detritus diagnosis

Two agents disagreed on one finding (§6); the orchestrator settled it by
measurement rather than by preferring a report.

## 2. The monoculture is structural, not a model preference

**[V] At user scope the system offers exactly one destination.**
`ui/src/self_learn_ui/models.py:101` — `"user": ("claude-md",)`, a
one-element tuple. `models.py:88` —
`PARAMETER_FREE_DESTINATIONS = ("skill-md", "claude-md", "reference")`, so
`new-skill` and `hook` are outside the UI destination cycle at every scope.

**[V] The CLI enforces the same shape twice.**
`cli/src/self_learn/verbs.py:836-840` refuses `skill-md` unless scope starts
with `skill:`. `verbs.py:950-955` refuses `reference` at user scope by name.

**[V] The refusal's stated justification has expired.** `verbs.py:950-955`
reads *"the user host is the chezmoi-managed CLAUDE.md, it has no references
dir (doc 13 §2)"*. Chezmoi was retired on this host 2026-07-24. The premise
is dead; the refusal is not. The same stale premise appears in the analyst's
system prompt at `references/routing-doctrine.md:124-127`, where it is used
to *inflate* the cost of user scope. **[R]** `drafts/fast-lane-spec.md:39`
inherited it as the ground for an invariant.

**[V] The doctrine contradicts itself on this exact axis.**
`routing-doctrine.md:84-93` (§3, "the one standing tiebreak"):

> **Prefer the narrowest surface that still fires.** `~/.claude/CLAUDE.md`
> loads in every session of every project — user scope is the most expensive
> destination in the system. […] Loaded-surface budget is the scarce
> resource: managed sections cap at 10 entries / ~150 words […]

And `routing-doctrine.md:36-39` (§2, the operative routing table):

> - **knowledge, skill scope** → `reference` or `skill-md` section.
> - **knowledge, project/user scope** → `claude-md` (or project docs).

The doctrine names user-scope CLAUDE.md the most expensive destination in
the system, instructs the model to always prefer the narrowest surface, and
then routes all user-scope knowledge there because no cheaper user-scope
surface exists. **The narrowest-surface bias has nothing to bite on at user
scope.**

**[V] The consequence in the live ledger.** 11 pending records (13 files in
`pending/`, two carrying `status: deferred`). All **9** user-scope pending
propose `claude-md`; the 2 hypr-doctor pending propose `skill-md`.
Historically 28 routed: 14 `reference` (all `skills/home-assistant`), 10
`claude-md` (5 user, 5 project), 3 `hook`, 1 `skill-md`, **0 `new-skill`**.

**[V] `routing.by` is not a signal.** `verbs.py:2325` hardcodes
`"by": "human"` unconditionally on the route path. A second writer exists
(`ledger_ops.py:816`, taking `by` as a parameter) but no caller passes it.
The field reads `human` on all 28 routed records and cannot discriminate
between analyst-chosen and human-chosen routings. **Any future analysis
keyed on this field is measuring a constant.**

**[R] The rationales are judgement-shaped prose over a forced choice.**
8 of 10 user-scope proposal rationales contain a variant of *"user-scope
claude-md is the narrowest surface that still fires"* — §3's anti-CLAUDE.md
rule repurposed as a pro-CLAUDE.md argument, a superlative asserted over a
set of one. The analyst is never told its option set is a singleton, so it
reconstructs a justification each time. This is why the review cards read as
considered decisions.

### 2a. The control group

**[R]** `skills/home-assistant` routed to `reference` 14 times — the only
bucket that escaped. Split verdict: on **magnitude** it is an artefact (13
of the 14 share `source: backlog` and one identical `created_at`, a single
bulk import of a hand-maintained journal only that skill had). On
**mechanism** it survives the discount: `lrn-e2e4026b` was a live
`teach`-sourced knowledge record routed to `reference` a day before the
import, through a different pipeline; and the two `type: knowledge` records
that occurred outside skill scope (`lrn-2fd0cdd7` user, `lrn-56e5aa0a`
project) both went to `claude-md`. Same content type, different scope,
different destination.

**[V]** `routing-doctrine.md:21` defines `reference` as "append to the
skill's `references/LEARNINGS.md` (or another **existing** references file,
named explicitly)" — bold in the original. Structurally unavailable outside
skill scope, and unavailable for anything that does not already exist.

## 3. `reference` routes but does not deliver — highest severity

**[V] Half the routed corpus was written into a file nothing points at.**
`compilers.py:compile_reference` appends to `references/LEARNINGS.md` and
writes no pointer, index entry, or SKILL.md reference anywhere.

Measured: a case-insensitive search for `LEARNINGS` across the entire
`plugins/home-assistant/` tree returns **exactly one file — `LEARNINGS.md`
itself**. Positive control: the same search for `GOTCHAS` (a
hand-maintained file known to be cross-referenced) returns **8 files**. The
search discriminates; the pointer is absent.

14 of 28 routings — 50% of everything ever routed — went to this
destination. Progressive disclosure without an index entry is not
progressive disclosure. **P2 is unsatisfied for half the corpus.**

This is a *missing* pin, not a bad one: no document records a decision that
`reference` should or should not maintain a pointer. It was never asked.

**[R] The mechanism that hid it.** `routing-doctrine.md:133` invites the
analyst to name an existing references file, but no proposal field exists to
carry the name, and `verbs.py:510-516` passes `None` — so it fails silently
into the default. The doctrine flags this exact schema gap for `rehome`
("do not invent one") and not for `reference`.

**[R] It is about to be industrialised.** `drafts/fast-lane-spec.md:50`
tiers `reference` as **FAST**, justified as an *"unloaded surface… affects
zero activations"* — accurate, and the reason the tiering is wrong. With
~90% of real lessons being `knowledge` (E-2) and the narrowest-surface bias
steering them, throughput would rise while delivery stayed flat, and **no
existing metric distinguishes "routed" from "loadable"**. Cheapest guard: a
selftest asserting reference targets are reachable from a loaded surface. It
would fail 14 times today.

## 4. `analyst.analyze()` can never return `hook`

**[V] A serializer silently discards the model's answer.** `analyst.py`'s
`analyze()` rebuilds the proposal from a fixed key set — `destination`,
`alternates`, `rationale`, `model`, `analyzed_at`, `record_sha` — plus only
`variant`, `rules_topic`, `rules_paths`. The model's `hook:` and `examples:`
keys are never copied. `ledger_ops.py:426-454` then *requires* exactly those
fields for `destination: hook`. Model answers `hook` → evidence dropped →
validator rejects for missing evidence → `AnalystError` → caller falls back
to a plain pending capture ("the lesson is never lost").

**[R] Measured cost.** Of 38 sandboxed live analyst runs, **13 failed
(34%), every one with subprocess `rc=0` and zero timeouts**; 12 were this
defect, 1 a YAML parse death from an unquoted `rationale` containing a
colon. There is one parse attempt and no reprompt. On one user-scope
behaviour record the model answered `hook` **10 times out of 12** across
sightings 1/3/5/10 — every answer discarded invisibly.

**[V] Scope of the defect — it does NOT explain the pending queue.** The
nightly worker does not share it: `worker.py:279-293` grants the model
`Edit(/<home>/*/proposals/**)` and the model **writes proposal files
directly**; the CLI validates and stamps rather than rebuilding a dict, so
`hook:` blocks survive. The 9 pending user-scope proposals came from the
worker path and remain explained by §2. **Two independent defects, not one.**

**[R]** This silently implements a per-authorship split of the one-motion
hook gate that the user explicitly considered and rejected (`03` S-10 scope
ruling: *"when the flag flips and opens the gate, it opens it fully…
Considered and rejected: splitting the knob per authorship"*). It is a bug
against a quoted user ruling — to be fixed, not adjudicated.

**[R] An uncontrolled production input.** `analyze()` passes no `cwd` to
`subprocess.run`, and the probe measured that the destination depends on
what is visible in the working tree (§8). Routing therefore depends on the
caller's working directory.

## 5. Pin provenance

**[V] The naming pin's citation is fabricated.** `08-build-plan.md:469`
justifies "a `new-skill` proposal never names the skill" as *"the confirmed
§4 human call"*. §4 (lines 264–283) contains no such row. Positive control:
the same line range does contain `Guard predicate`, so the check can see
content — the cited row simply does not exist. **[R]** It entered as a rider
on `4be6d2b`, a commit about hook schemas, replacing honest prior text; two
tests now assert the refusal and repeat the citation.

**[V] The user's own account, this session:** the pin *"didn't come from me.
it came from an agent."*

**[R] The quote-convention instrument: high precision, near-zero recall.**
48 verbatim user utterances catalogued across the corpus; exactly **one**
fabricated user ruling exists in the whole corpus and the project's own
blind gate caught it (`reviews/2026-07-18-deep-specs.md:70`). So a quote is
dispositive. Absence is not: agent authorship is the baseline (367 commits —
Fable 255, Opus 31, Opus 4.8 11, Sonnet 3, unattributed 67), and rulings
captured via `AskUserQuestion` return option selections rather than prose,
making them **structurally unquotable**
(`research/2026-07-12-adjudication-surface-problem-space.md:168-176`).

**[R] The instrument's dangerous failure mode runs backwards.**
`11-telemetry-and-lifecycle.md:3` quotes the user genuinely — *"review them
yourself and answer the questions you would ask me"* — but that authorises a
**delegation**. Of the six answers at `README.md:384-408`, Q1–Q5 are agent
self-answers and only Q6 is the user's. The row is Settled/Ratified at
`03-decisions.md:28`. The quote makes it look *more* grounded than an
unquoted row.

**[R] What actually discriminates: per-file commit history.** Of the three
agent system prompts, `routing-doctrine.md` has 11 commits with 1 traceable
to a user touchpoint; **`mining-rubric.md` and `pane-charter.md` have one
commit each, ever, and zero user touchpoints.**

**[R] Agent-authored pins that are good, recorded so the finding is not
misread as "agent pins are bad":** `allowed_tools=[]` / `setting_sources=[]`
(empirically doc-falsifying, and a large cache-token saving); the
adversarial render path with `default-src 'none'`; no Bash/Task/web/MCP
structurally absent from the pane; `Edit`-not-`Write` on records (the
resurrection vector); the new-skill collision rule refusing to inject into a
foreign authored SKILL.md; hook replay-before-commit; the bounded
contradiction check that refuses to overclaim; the miner's self-mining halt.

**[R] Rows whose Settled status is broader than the user's actual input** —
flagged so they are neither reopened casually nor cited as user authority:
S-16, S-14/S-15, S-19 (publication is the user's; FSL-over-MIT and
CLA-over-DCO reasoning is agent), S-20.

**[R] Two narrowings of explicit user requests**, surfaced for the user, not
recommended for reversal: a pane agent that *acts* (`09:1652`) became one
that may only propose; *"potentially autonomous review, are goals"*
(`12:347`) became M-1's *"No exception, no flag."*

## 6. The excerpt marker never matches

**[V]** `worker.py:572-574` searches lines for `"SELF-LEARN:BEGIN"` /
`"SELF-LEARN:END"`. `compilers.py:84-85` writes
`<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->`
and `<!-- self-learn:end -->`. Real files confirm lowercase. The search can
never match; for any target ≥200 lines the analyst receives `lines[:60]`
instead of the managed section, leaving `already_canon` and the
contradiction check structurally blind.

**Two agents disagreed on whether this fires; settled by measurement.**
`~/.claude/CLAUDE.md` is 54 lines, so the excerpt path is not taken.
`~/.config/CLAUDE.md` is **703 lines**, so it is — that bucket's analyst is
blind today. The agent that called it dormant had generalised from the one
file it inspected.

## 7. Managed-section caps: the reported axis is not the binding one

**[V] Measured with the compiler's own rule:**

| target | entries | words |
|---|---|---|
| `~/.claude/CLAUDE.md` | 5 / 10 | **506 / 150 — 337%** |
| `~/.config/CLAUDE.md` | 1 / 10 | 80 / 150 |

`compilers.py:88-89` sets `DEFAULT_MAX_ENTRIES = 10`,
`DEFAULT_MAX_WORDS = 150`; over-cap applies anyway with a flag
(`compilers.py:32-36`). **[R]** The UI's budget line leads with the
non-binding axis — *"already holds 5 of its 10 entries"* — so a reviewer
reads headroom while the binding axis sits at 3.4× over. **[R]** Telemetry
shows 6 `overflow: true` events while `14-forward-work-map.md:135` still
lists the over-cap → FW-6 flow as dormant.

## 8. What the empirical probe rules out

**[R]** 38 live sandboxed `analyze()` spawns; harness ran the real function
with a two-layer positive control (stubbed spawn proving four distinct
destinations round-trip; live spawns producing four distinct destinations).

| theory | verdict | N |
|---|---|---|
| `new-skill` is unreachable / dead | **false** — 8/8 across four framings | 8 |
| Analyst cannot see alternatives, so "no skill owns this" is vacuous | **false** — flips 3/3 to `skill-md` when an owning skill is planted, quoting its `description:` verbatim; a *decoy* unrelated skill does not move it | 9 |
| Recurrence escalates to `hook` | **fiction** — no movement across sightings 1/3/5/10; the doctrine never mentions `sightings` at all | 12 |
| Timeouts/flakiness explain the distribution | **false** — 0/38 timeouts, 0/38 non-zero exits (max duration 40.1 s vs the 120 s production timeout) | 38 |

**[R]** `variant: rules` and `variant: local` were emitted **0 times in 38
runs** — the model does not reach for them unprompted. Combined with **[V]**
0 uses across 12 `claude-md` routings (6 of them after the feature shipped),
the cheapest proposed opening of the funnel is not one the analyst will take
without a prompt change.

**Untested:** whether the worker path shows the same distribution; other
models; production context with the real global CLAUDE.md present.

## 9. `new-skill`: the compiler works, the path to it does not

**[R] End to end in a sandbox the scaffold is real**: `route --dest
new-skill:<name>` rc=0 → real `install.sh` symlinks it into
`~/.claude/skills/` → SKILL.md reads back → `claude plugin validate .` rc=0.
`install.sh` discovery is `jq -r '.plugins[].name'` plus a directory test;
`plugin.json` is never read.

**[V] Scope is not a parameter.** The new-skill branch of `_resolve_target`
(`verbs.py:898-922`) contains **zero** references to `scope`, while the
`claude-md` branch immediately above it (`verbs.py:869-896`) branches three
ways on it. **[R]** A project-scope record routed to `new-skill` lands in
the global skills root with the project's `.claude/skills/` untouched;
pointing `skills_root` at `~/.claude` yields
`~/.claude/plugins/<n>/skills/<n>/SKILL.md`, not the user-skill path — no
path-hack workaround exists.

**[V] The defect was seen and documented** —
`drafts/c1-portability-defects-spec.md:638-639`: *"`new-skill`'s missing
scope gate (`verbs.py:605-648`) — a real latent defect, unrelated to
portability. Named so a reviewer knows it was seen."* This is the healthy
counter-shape to §5's fabricated citation: seen, declined, recorded. (The
cited line range has since drifted; the branch is now at 898-941.)

**[R] On a fresh machine the destination is unreachable**: refuses without a
registered skills root, then refuses again without a pre-existing
`.claude-plugin/marketplace.json`, and `host add --skills-root --init` does
not close it (`--init` does `git init` plus an empty commit). A human must
hand-author a manifest. An independent contributor to 0-of-28.

**[R] Human-only steps that remain**: the name (§5); running `install.sh`
(self-learn never invokes it, and the post-note is unconditional prose —
deleting `install.sh` still prints "run ./install.sh", rc=0); prose
enrichment (`description:` is auto-seeded from the first lesson's trigger,
which is the activation signal). The scaffold also writes no
`skill-rules.fragment.json`, so a scaffolded skill is never registered with
this host's activation-nudge hook.

## 10. The test suite leaks into the user's real cache

**[V] Measured:** `~/.cache/self-learn` holds **31,033** `home-*`
directories totalling **1.1 GB**; **7,254 created on 2026-07-26** alone,
newest leak at 19:44. One directory (`home-0f24de4d`) is live production
state.

**[V] The mechanism.** `cli/.../worker.py:112-127` — `cache_dir()` computes
`${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolve_home())[:8]>`
and **mkdirs it as a side effect of resolving the path**, so even a
read-only query leaves a directory behind; the name varies with
`SELF_LEARN_HOME`, so a unique ledger home per test mints a unique
namespace. `ui/.../ledger.py:115-116` —
`full_env = dict(env if env is not None else os.environ)` pins only
`SELF_LEARN_HOME` and inherits the real environment otherwise; multiple
call sites omit `env=`.

**[V] The asymmetry.** `cli/tests/conftest.py:13` has an **autouse** fixture
setting `XDG_CACHE_HOME`. The UI package's `redirected_xdg` is a plain
`@pytest.fixture` — opt-in, used by 3 of 46 files — and the UI package's
only autouse fixture (`_client_contexts`) redirects nothing.

**[R] Reproduced with a validated negative control**: 101 leaked dirs from
`test_routes.py` alone, **176 from one full UI suite run**, and **0 from the
full CLI suite**. 31,033 ≈ 176 dirs × ~176 suite runs since 07-15.
Production is unaffected (the systemd unit pins `SELF_LEARN_HOME`).

**[R] Proposed fix**: add to `ui/tests/conftest.py` the autouse fixture it
never grew, mirroring `cli/tests/conftest.py:13-35`; and make `_invoke_json`'s
`env` parameter **required** so the type checker enumerates the call sites.
Silent inheritance of ambient environment is the defect. Cleanup of the
existing 1.1 GB is a separate, user-owned action and must follow the fix or
it refills at ~176 per run.

## 11. Capabilities that exist in code and have never been exercised

The "never fired" signature is what surfaced most of the above. **[V]**
unless noted.

- `new-skill` — 0 proposals, 0 routings in 28.
- `variant: rules` / `variant: local` — 0 of 12 `claude-md` routings, 6 of
  them after the feature shipped.
- **[R]** `already_canon: true` — 0 of 26 proposals.
- **[R]** Contradiction edges — 0 ever written.
- **[R]** Miner `folded` / `recurrences` — 0 across 14 runs.
- **[R]** Lint negatives — `trigger_recognizable: no` 0, `why_present:
  false` 0 across 15 proposals carrying lint.
- **[R]** No telemetry event kind exists for route, reject, defer, or
  graduate. Observed kinds: `capture`, `surface-budget`, `fire`,
  `offer-declined`.
- **[R]** True graduation from a compiled section — exactly one, ever.

## 12. User rulings made this session (verbatim — these ARE ratified)

Recorded here per the convention §5 validates: a user ruling is quoted, not
paraphrased. These should graduate into `03-decisions.md` as their
implementing units are specced.

1. **Analyst may name the skill.** *"the analyst should be able to name the
   skill for presentation to the user. the user gets to decide if they'll
   keep the name, change the name, or route to another surface."* Reverses
   the §5 pin. **[V]** The single load-bearing code blocker is
   `verbs.py:510-517`, where `_Destination`'s qualifier slot is a hardcoded
   `None` beside `variant` / `rules_topic` / `rules_paths`, which all pass
   through. **[R]** Three of four parts already exist as dead code:
   `validate_proposal` accepts and round-trips `new_skill`; the review UI
   already renders it (`models.py:1275-1287`, tested); the pane grammar
   already matches `new-skill:.+` (`proposals.py:98-99`).
   **Left unsettled by the ruling** — (a) is the model's name trusted like
   `rationale`, or CLI-regenerated like hook `script` bytes? (b) the "change
   the name" leg has **no UI**: the action bar has a destination cycle key,
   not a text field.

2. **Loosen the funnels.** *"we need to assess all of the prompting and the
   mechanics around said prompting and loosen some of the restrictions we
   place around the agents, both structurally and programatically. they need
   some freedom of movement in order to get this job done. that's not the
   same as saying just spawn claude -p instances and have them run around
   and do whatever they want. i like the harness we're building here, and
   the structure it provides. we just need to assess the funnels we're
   creating."*

3. **Pins need provenance accounting.** *"the pin that led to the analysts
   not naming skills issue didn't come from me. it came from an agent. maybe
   part of what we do now is review the pins and get an accounting of the
   consequences of said pins. we can predict, to some extent, future
   problems based on the shape the pins take and the context they create for
   the analyst, miner, and in-gui iterators."*

4. **Push is autonomous** after a successful iteration/implementation/testing
   loop. Conditions live in the repo's git-excluded `CLAUDE.local.md`.
   Supersedes the prior "pushes are manual" operating posture for the
   orchestrator; **D3's no-autosync invariant is untouched** — this is a
   human-authorised push step, not automation.

## 13. Open values questions — for the user, not for an agent

1. **What should `reference` do?** Either `compile_reference` maintains a
   pointer from a loaded surface, or `reference` stops being described as a
   delivery destination. 14 lessons are currently undelivered (§3).
2. **Should user scope get a cheap surface at all**, and if so which — a
   `reference` analog, or `variant: rules` promoted and prompted for (§2, §8)?
3. **Model-authored name: trusted or regenerated?** (§12.1a)
4. Whether to reverse either narrowing in §5's last paragraph.

## 14. What this document does not establish

- It does not establish that the historical 14/10/3/1/0 distribution is 28
  independent model choices. It is not (§2a).
- It does not establish that the worker path shares the `hook` defect. It
  does not (§4), but the worker's *own* distribution under controlled
  conditions is untested.
- It does not diagnose which individual tests leak (§10), nor was the
  proposed fix applied or verified.
- **[R]** marks throughout are leads, not findings. Several **[V]** items
  below were nearly mis-reported by the orchestrator when a check returned
  empty for the wrong reason — a `grep` for "most expensive" failed only
  because the phrase wraps a line, and a pending count was wrong because
  files in `pending/` were counted without reading `status:`. Both are the
  fail-open shape the ledger already knows as `lrn-ea833a5b`. Any re-check
  of this document should carry its own positive control.

## 15. Raw material

The six subagent reports are preserved verbatim under
[`2026-07-27-raw/`](2026-07-27-raw/) — including the probe's 38 raw model
outputs, which are measurements that cannot be reconstructed. **That
directory is raw agent output, not corpus**: see its README before reading
or citing anything in it.
