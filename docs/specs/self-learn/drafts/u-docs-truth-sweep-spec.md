# Spec — U-docs: the docs-truth sweep and the operator runbook

Status: **r4 — CLEARED FOR BUILD.** r3 delta gate: **SOUND — 0 BLOCKER /
0 MAJOR / 3 NOTE**, every r3 landing verified by execution; all three
NOTEs were bounded text corrections, so the round closed under the
ratified verdict-repricing rule and **no further spec gate follows** —
the builder-verifier checks these folds downstream. r1 was written blind
against master `89f8ef7`; r2 folded the orchestrator's supply against the
primary source; r3 folded the blind gate; r4 folds the delta gate.

**Three rounds, one defect class, each a level further up.** r1 wrote an
inventory of other documents' false claims and made one of its own
(`Sub-1`'s anchor, editorially normalized, resolving to nothing). r3's
re-check of that fix found a *second* anchor defect the gate had missed
(`Sub-18` matching twice). r4 then found the defect was in **the check**:
`E-18b`'s raw-grep column had been measured against short probe fragments
rather than the real anchors, so it reported a confident number about
strings the spec does not contain. The fix was never "look harder" — it
was to make the check fail on **≠ 1** rather than 0, to copy anchors
instead of quoting them, and finally to **delete the figure that could
only mislead** (`§0.6`, `E-18b`, `E-18c`). A sweep that corrects other
documents has to hold itself to the standard it is imposing, including
when the thing that is wrong is its own instrument. Unit `U-docs`,
**Wave 2**
of the approved Agent-SDK migration — one of four parallel Wave-2 units
alongside `U-sdka` (analyst flip), `U-sdkr` (miner reader) and `U-sdkw`
(worker). This is a **docs-only** unit: zero product code, zero test
code, zero fixture edits.

**The unit in one sentence.** Make the numbered corpus tell the truth
about how this codebase invokes a model — by naming every site that
asserts something about model invocation, classifying each against the
shipped code, substituting only the clauses that are false, landing the
decision rows the migration already owes, and writing the operator
runbook the surface flips cannot safely happen without.

**Why a docs unit gets a blind gate at all.** `15-orchestration-runbook.md`
§1 says docs-only status maintenance is orchestrator-direct and ungated,
and that *"anything that pins behavior gates."* This unit pins behavior:
the runbook (§3.4) tells an operator which environment variable to set,
in which shell, to move a production surface onto a different model
transport, and states which gates must pass before that is allowed. A
wrong line there is a production incident, not a typo. The gate is
therefore a **reader-verifier**: every claim below carries a `how to
check` row in §5, and the gate executes them.

**Base commit:** `89f8ef7` (master — the `U-fake` merge, "Wave 1
complete"). Every line number, quoted string and measured output in this
document was read or executed at that commit. **Line numbers are not
stable** — §0.3 states the location rule that survives a re-numbering.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `docs/specs/self-learn/17-invocation-runbook.md` | **NEW.** The operator runbook. Full text is Appendix A; the builder copies it verbatim. Location decision + the number collision: `D-1`. |
| `docs/specs/self-learn/03-decisions.md` | Eight new rows: `S-34`, `S-35` (reserved by `U-seam` §7.5 and never landed — backfill ratified 2026-08-19), `S-39`–`S-44` (§3.3). One dated amendment to `S-5` (`Sub-3`). Nothing else in the file changes. |
| `docs/specs/self-learn/01-architecture.md` | Two sites: §3.3's opening clause (`Sub-1`, appended clause) and its "Restricted permissions" bullet (`Sub-2`, replaced clause). |
| `docs/specs/self-learn/08-build-plan.md` | Four sites: `Sub-4` (§1 `teach --route` row), `Sub-5` (the worker run-sequence timeout), `Sub-6` (the worker-invocation flag-set pin), `Sub-7` (§7.3 M2 acceptance (a′)). |
| `docs/specs/self-learn/11-telemetry-and-lifecycle.md` | One site: §4.2's worker-telemetry bullet (`Sub-8`). |
| `docs/specs/self-learn/12-transcript-miner.md` | Four sites: `Sub-9` (§2 Phase-2 containment paragraph), `Sub-10` (§6 Q5 mechanism note), `Sub-11` (§9 T-M2 row — **two clauses**: the containment parenthetical and the artifact-filename contract), `Sub-21` (§5 znote-declined bullet). This file carries the same tool-surface misconception in **three** places; all three are corrected here. |
| `docs/specs/self-learn/13-hosting-and-separation.md` | One site: the lock-checker narrowness note (`Sub-12`, appended clause). |
| `docs/specs/self-learn/forward/platform-drift.md` | Four sites: `Sub-13` (preamble scope), `Sub-14` (§1 heading + exposure list), `Sub-15` (§3 exposure bullet). |
| `docs/specs/self-learn/14-forward-work-map.md` | Three new rows (`FW-95`, `FW-96`, `FW-97` — §3.5), plus a dated bullet in the file's own change log. Existing rows are not edited. |
| `docs/specs/self-learn/README.md` | Three edits: the status header (`Sub-16`), one new reading-order row for doc 17 (`Sub-17`), one appended revision-log entry (`Sub-18`). |
| `README.md` (repo root) | Two edits: one install line naming the `[sdk]` extra (`Sub-19`), one short "Invocation backend" subsection pointing at doc 17 (`Sub-20`). |

**Files this unit may NOT touch — enumerated, not implied.**
`00-vision.md`, `02-schema.md`, `04-roadmap.md`, `05-evidence.md`,
`06-horizon.md`, `07-review-ui.md`, `09-surface-spec.md`,
`10-surface-build-plan.md`, `15-orchestration-runbook.md`,
`records-index.md`, everything under `drafts/` except this file,
`research/`, `feedback/`, `fixtures/`, `reviews/`, and **every file
under `plugins/`** — source, tests, fixtures, `pyproject.toml`,
lockfiles. §7.1 records the sites in those files that were judged and
deliberately left, so a later reader can tell "looked at and kept" from
"never looked at."

`reviews/` is **not read** by this unit's author (blind-gate
discipline). §8 `X-2` records the one obligation that could not be
discharged because its only source lives there.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (the verification table) ARE the
   spec.** Everything else is rationale. Where prose and a criterion
   disagree, the criterion wins and the prose is the defect.
2. Every substitution is defined **once**, in §3.2, with its `before`
   and `after` bytes. A second statement of the same substitution
   anywhere is a bug in this document.
3. **Sites are located by file + section + a distinctive quoted
   substring, never by bare line number.** Line numbers appear in §3.1
   only as a convenience for the builder and are explicitly declared
   non-normative: the corpus's own history shows every one of these
   files gaining and losing lines between units. If a quoted substring
   does not match at build time, the builder stops and reports — it
   does not go hunting.
4. This unit **never edits a dated record.** §1.2 `Rule A` states the
   rule and §7.1 lists the dated sites it protects.
5. **Anchors are byte-exact, and the check fails on ≠ 1, not on 0.**
   An anchor in §3.2 is copied from the file verbatim — backticks, bold
   markers, punctuation — with **no editorial normalization**; the r2
   gate caught `Sub-1` transcribed without its backticks and with its
   bold marker moved, which resolved to nothing while looking like a
   quotation. Match with `grep -F` (literal), never a regex: several
   anchors contain `*`, `[`, `(` and backticks. Resolution must be
   **exactly one** — `Sub-18`'s r2 anchor matched *twice* (two
   same-dated log entries), which is as unusable as zero.
6. **Anchors are given with their line wraps removed, and the resolver
   MUST normalize whitespace before matching.** These documents are
   hard-wrapped at ~72 columns and most anchors sit inside indented
   bullets, so an anchor of more than a few words spans a newline *and*
   picks up continuation indentation. The prescription, exactly:
   **replace every newline with a space, collapse runs of whitespace to
   one, then match literally** (`tr '\n' ' ' | tr -s ' '`, then
   `grep -F`). Both halves are required — measured (`E-18b`): newline
   substitution *alone* still fails `Sub-2`, because the wrap lands
   before a two-space bullet indent.
   **No raw-grep count is quoted anywhere in this document, deliberately.**
   Whether a given anchor happens to survive an un-normalized `grep` is
   an accident of where the wrap fell, it varies per anchor, and stating
   it invites a builder to raw-grep, get zero, and halt under §0.3 on a
   perfectly good anchor. The only supported answer is: **every anchor
   resolves exactly once under the normalization above.**

---

## 1. Why this unit exists

### 1.1 The corpus has a standing rule, and this migration broke it

`forward/platform-drift.md` §4, "The theme's one standing rule":

> Platform drift responses are **never** absorbed silently into builds:
> any SDK bump, engine swap, format hedge, or destination addition gets
> its dated note in the register or the relevant spec — the same P10
> change-control the corpus already runs. Drift handled quietly is how a
> system stops matching its own documentation, and this corpus's value
> *is* that match.

Wave 0 and Wave 1 shipped an **engine swap**: `U-seam` put every
`claude` spawn in the CLI behind one package, `U-sdk` added a second
backend over `claude_agent_sdk`, `U-bedrock` added an orthogonal
provider switch and a doctor, `U-fake` tiered the harness for a Wave-2
contract test. Four units, four merges, and in the numbered corpus the
only trace is `14-forward-work-map.md`'s rows `FW-86`–`FW-94` and
`03-decisions.md`'s `S-36`–`S-38`. **Measured** (`E-6`, §9): not one of
`01`, `08`, `11`, `12`, `13` or either `README` mentions the invocation
seam or the backend switch **anywhere**; every one of them still
describes model invocation as a `claude -p` subprocess, and several
describe a containment mechanism that has not been the shipped mechanism
since 2026-07-15. *(Precise at r3: the specs `README` and the root
`README` do say "Agent SDK" — but only about the **G-3 pane engine**, in
dated 2026-07-12 log entries and the UI's own env-var table. Not one
mention concerns the CLI's invocation layer, which is the claim `E-6`'s
result column already made and this sentence now matches.)*

The register carries its own version of the same rule
(`03-decisions.md`, "The register's own rule"): *"When any settled
decision's stated inputs change … the decision reopens in this file with
a dated note."* `S-5`'s stated rationale is *"SDK worker is a swap
behind the same contract if needed"* — a hypothetical that has since
been built. It has no dated note.

And `U-seam`'s own files-may-touch table (`drafts/u-seam-invocation-seam-spec.md`
§"Files this unit may touch") lists `03-decisions.md` with the footprint
*"New rows `S-34`, `S-35` (§7.5), landing in the same commit as the
build."* **Measured** (`E-1`): the register runs `S-33` → `S-36`. The
two rows never landed. That is the migration's clearest documentation
defect and this unit's first obligation.

### 1.2 The classification rule, and why there are four buckets not three

Every enumerated site gets exactly one verdict. The verdicts are defined
here, once:

| Verdict | Definition | Action rule |
|---|---|---|
| **NOW FALSE** | The text asserts something untrue of master `89f8ef7` **as it stands today**, with every switch at its shipped default (`backend=cli`, `provider=anthropic`). A reader who acted on it would act wrongly *now*, not after some future flip. | `Rule B` |
| **STALE-BUT-HARMLESS** | True today under the shipped defaults, but names one transport as *the* transport. A reader is misled about architecture, not about behavior. | `Rule C` |
| **STILL TRUE** | Unaffected by Waves 0–1, or a dated record of something that was true when it was written. | `Rule D` — leave, and record in §7.1 that it was judged. |
| **MISSING** | Not a false statement but an **absence**: a row the corpus owes and does not have, or an operator-facing fact with no home. | `Rule E` |

The three buckets the brief asked for cannot classify an absence — a
missing `S-34` is neither false nor stale nor true — so **MISSING** is
declared as the honest fourth rather than forced into one of the three.
Both tallies are reported in §3.1.

**The four action rules, defined once:**

- **`Rule A` — history is never edited.** A dated entry is a record:
  revision-log bullets, `*Amended <date>:*` clauses, verification-log
  entries, task-DAG rows describing what a task did. These get **no
  edit, ever**, even when superseded. Superseding them is what the new
  dated clause is for. This rule outranks every other rule in this
  document; where a false clause sits *inside* a dated record, the
  correction goes in a new dated clause elsewhere and the record is left
  alone.
- **`Rule B` — replace in place, and date the replacement.** A live
  false clause is replaced with the true one and the sentence gains a
  trailing `*(corrected 2026-08-19, U-docs: …)*` marker naming what was
  wrong. The false bytes do not survive, because a skimmer who reads
  only the first clause must not be misled; the marker is what keeps the
  change auditable.
- **`Rule C` — append, do not replace.** A true-but-transport-bound
  clause keeps its bytes and gains an `*Amended 2026-08-19 (U-docs):*`
  clause in the corpus's existing idiom. Nothing shipped is unsaid; one
  more thing is said.
- **`Rule D` — leave, and record the judgment.** §7.1.
- **`Rule E` — add the missing thing.** §3.3 (decision rows), §3.4
  (runbook), §3.5 (forward rows), `Sub-17`/`Sub-19`/`Sub-20`.

### 1.3 What this unit is not

It is not a rewrite of the corpus, not a back-fill of the README's
26-day revision-log gap (`E-7`; recorded as `FW-97`, not attempted), not
a re-litigation of any shipped design, and **not a flip**. No surface's
default moves. The runbook describes how a flip is done and what must
hold first; performing one is `U-sdka`'s and the burn-in's work, under
the operator's hand.

It is also not a source-comment sweep. `analyst.py`'s module docstring,
`worker.py`'s `build_argv` docstring and `systemd/self-learn-miner.service`'s
header all describe `claude -p` as the transport; all three are outside
the brief's inventory scope and are recorded in §7.1 with owners rather
than silently fixed.

---

## 2. What binds this design from outside it

Shipped, currently-green facts. Each removes an option this unit might
otherwise take.

- **`B-1` — the corpus declares itself historical.**
  `docs/specs/self-learn/README.md` (preamble): *"Treat it as a
  historical and design record of the product, not as a specification of
  the shipped product's present behavior; where the two disagree, the
  code and its own tests are authoritative."* This is why the sweep is
  **bounded substitution, not rewrite**: the corpus is not obliged to
  narrate the present, only to stop asserting falsehoods as live pins.
  It is also why `Rule A` exists.
- **`B-2` — `08-build-plan.md` is execution authority.** The README's
  reading-order row calls it *"Execution authority for the build:
  pinned interface contracts …"* A false *pin* there is qualitatively
  worse than a stale sentence in `01`, because a future builder is
  instructed to implement it. This is why three of the four `08` sites
  are `Rule B` replacements and only one is `Rule C`.
- **`B-3` — the ledger is agent-read-only and pushes are manual (`S-17`
  D3).** The runbook may instruct the operator to edit
  `<ledger-home>/config.yaml`; it may not instruct any agent to, and it
  must not tell anyone to add an auto-push anywhere.
- **`B-4` — the repo is PUBLIC (`S-19`).** No absolute home paths, no
  credentials, no real record ids. The runbook uses `<ledger-home>` and
  `lrn-00000000` placeholders throughout. `S-37` binds harder still: no
  credential value may appear in `config.yaml` or in any example of it.
- **`B-5` — `S-36`: `provider` is install-wide and orthogonal to
  `backend`; under `backend=cli` a `bedrock` provider is silently inert
  BY DESIGN.** The runbook must present two switches, not one, and must
  not describe the inert combination as an error — `FW-89` names the
  doctor's `rollout` row as the intended detector and names *this unit's
  runbook* as the owner of the one-line mitigation.
- **`B-6` — `FW-88` assigns this runbook a second obligation**: document
  `SELF_LEARN_ENFORCE_SCOPE=0` as **sdk-semantics-only**, i.e. that the
  incident hatch is wider on the sdk path than on the cli path on a host
  with stricter global settings.
- **`B-7` — `FW-94` is a WATCH row whose whole purpose is that an
  operator can find out why `--selftest` spawns a process.** If the
  runbook does not carry it, the row has no reader.
- **`B-8` — the systemd user manager does not inherit the shell's
  environment.** Both shipped units say so in their own comments
  (`systemd/self-learn-miner.service`, `systemd/self-learn-ui.service`:
  *"the systemd user manager does not inherit the shell's env — pin the
  ledger home explicitly so the unit and the shell agree"*), and both
  pin `SELF_LEARN_HOME` and nothing else. This is the single most
  consequential operational fact in the runbook and it constrains the
  flip instructions absolutely (§3.4, `RB-4`).
- **`B-9` — `15-orchestration-runbook.md` §1 step 7** makes a README
  revision-log entry part of round-close. This unit appends exactly one.

---

## 3. The change

### 3.1 `Inv-1` — the inventory (NORMATIVE, and this unit's evidence)

Every site in `docs/specs/self-learn/*.md`, `docs/specs/self-learn/forward/*.md`
and the repo-root `README.md` that mentions `claude -p`, a subprocess
model invocation, `build_argv`, an `--allowedTools`/`--disallowedTools`/
`--settings` containment claim, or the Agent SDK. Located by section +
quoted substring per `§0.3`; the line column is a build convenience and
is **non-normative**.

| # | File · section | Line @ `89f8ef7` | Current text (quoted) | Verdict | Action |
|---|---|---|---|---|---|
| `I-1` | `01-architecture.md` §3.3 | 164–167 | *"When a learning lands (teach without `` `--route` ``, or import), a **detached `` `claude -p` `` worker** (the proven home-net-capture pattern: `` `setsid` ``, flock, survives the session) analyzes it and writes the proposal — destination, rationale, draft diff, model, timestamp — to `` `proposals/lrn-<id>.yaml` ``"* — **note the bold opens before "detached", not after it**, and `--route` is backticked | STALE | `Sub-1` (C) |
| `I-2` | `01-architecture.md` §3.3, "Restricted permissions" | 186–189 | *"The worker runs `claude -p` with `--allowedTools` limited to reading the repo and writing new files under `.self-learn/**/proposals/`."* | **NOW FALSE** | `Sub-2` (B) |
| `I-3` | `03-decisions.md` `S-5` | 16 | *"**Pre-analysis worker = detached `claude -p`** … SDK worker is a swap behind the same contract if needed."* | STALE | `Sub-3` (C) |
| `I-4` | `03-decisions.md`, register body | — | rows `S-34` and `S-35` are **absent**; `U-seam` §7.5 + its files-may-touch table both oblige them | **MISSING** | §3.3 (E) |
| `I-5` | `03-decisions.md` `S-22` | 35 | verbatim user quote containing *"just spawn `claude -p` instances"* | STILL TRUE | `Rule D` |
| `I-6` | `04-roadmap.md` M2 scope | 206 | *"coalesced, flock'd per machine, restricted `--allowedTools`"* | STALE | `Rule D` (§7.1-a) |
| `I-7` | `07-review-ui.md` §1 pane bullet | 110–124 | *"`claude -p` stream-json subprocess by default, Agent SDK as the specced alternative"* — inside a dated amendment chain that the **same bullet** then reverses at 118–124 (*"restored the Agent SDK as the default engine"*) | STILL TRUE (self-correcting record) | `Rule A`/`D` (§7.1-b) |
| `I-8` | `08-build-plan.md` §1 `teach --route` row | 84 | *"bare-terminal `--route` without `--dest` runs a one-shot `claude -p` analyst against the doctrine file"* | STALE | `Sub-4` (C) |
| `I-9` | `08-build-plan.md` T8 | 217 | *"path spawns `claude -p` with the doctrine file (restricted tools) to produce the proposal, then applies."* | STALE | `Rule D` (§7.1-c: task-DAG record) |
| `I-10` | `08-build-plan.md`, Worker run sequence, step (3) | 367 | *"one `timeout 15m claude -p` invocation covering the batch + cluster pass"* | **NOW FALSE** — `worker.INVOKE_TIMEOUT_SECS = 30 * 60` | `Sub-5` (B) |
| `I-11` | `08-build-plan.md`, "Worker `claude -p` invocation" row | 368 | *"**Literal flag set, verified against the live CLI at T13 start** … `--allowedTools "Read,Grep,Glob,Write(<HOME>/plugins/**/.self-learn/proposals/**),Write(<HOME>/.self-learn/proposals/**)"`"* | **NOW FALSE** | `Sub-6` (B) |
| `I-12` | `08-build-plan.md` T13 tests | 391 | *"asserts the literal `--allowedTools` value and absence of Bash/Edit"* | STILL TRUE | `Rule D` |
| `I-13` | `08-build-plan.md` §7.3 (a′) | 436–437 | *"a real `claude -p` run under the pinned `--allowedTools`, instructed to write outside `proposals/`, is refused"* | **NOW FALSE** | `Sub-7` (B) |
| `I-14` | `08-build-plan.md`, analyst flag list | 575 | *"`--append-system-prompt`, `--allowedTools Read,Grep,Glob`, model"* | STILL TRUE | `Rule D` |
| `I-15` | `08-build-plan.md`, 2026-07-15 log entry | 757–774 | the live-CLI verification record, incl. the `Edit(//<home>/…/proposals/**)` rules | STILL TRUE (dated record) | `Rule A` |
| `I-16` | `08-build-plan.md` §… test summary | 714 | *"pins (no Bash/Edit)"* | STILL TRUE | `Rule D` |
| `I-17` | `09-surface-spec.md` | 570, 2146 | *"server render only, never a `claude -p` call"* | STILL TRUE | `Rule D` |
| `I-18` | `09-surface-spec.md` §4.1 engine table | 693 | *"`sdk` engine — `claude-agent-sdk` (Python) — **default**"* | STILL TRUE | `Rule D` |
| `I-19` | `11-telemetry-and-lifecycle.md` §4.2 | 222–224 | *"The M2 worker's `claude -p` analysis pass **never writes telemetry** — its `--allowedTools` write surface stays proposals-only (S-5/E-18 unchanged)."* | **NOW FALSE** (mechanism and scope; the property survives) | `Sub-8` (B) |
| `I-20` | `12-transcript-miner.md` §2 Phase 2 | 110–115 | *"One `claude -p` per run … Containment is the M2 worker posture verbatim: `--allowedTools "Read,Grep,Glob"`, the same disallow list, and a settings file granting the `Edit(//…)` rule family over the miner spool directory only"* | **NOW FALSE** (two of three clauses) | `Sub-9` (B) |
| `I-21` | `12-transcript-miner.md` §6 Q5 | 386–387 | *"a CLI verb that spawns its own contained `claude -p` internally"* | STALE | `Sub-10` (C) |
| `I-22` | `12-transcript-miner.md` §9 T-M2 | 461–463 | *"worker-posture `claude -p` (allowed Read/Grep/Glob; settings-file Edit rule family over the miner spool only; …)"* | **NOW FALSE** | `Sub-11` (B) |
| `I-42` | `12-transcript-miner.md` §9 T-M2 — **the same bullet as `I-22`**, two lines below it | 465–466 | *"artifact contract: one `mine-<runid>.json`, schema-validated, stray spool files deleted"* | **NOW FALSE** — the miner writes **one fixed name**, `miner.OUTPUT_BASENAME = "mine-output.json"`; `run_id` (a `uuid4().hex[:8]`) appears only in log lines and `MineResult`, never in a filename. Worse: the "stray spool files deleted" half is what makes the falsehood *operational* — a file actually named `mine-<runid>.json` would be swept as litter by `_invoke_reader`'s own stray sweep | `Sub-11` (B, extended) |
| `I-23` | `12-transcript-miner.md` §… cost aside | 513 | *"already spent the digest-read tokens in the one Phase-2 `claude -p`"* | STALE | `Rule D` (§7.1-d) |
| `I-24` | `12-transcript-miner.md` §5 | 266–267 | *"widening the miner's tool surface beyond Read/Grep/Glob weakens the containment posture that was live-verified on 2026-07-15"* | **STALE** *(regraded at r3)* — the **conclusion** is right (widening weakens containment) but the **premise is the same misconception `Sub-9`/`Sub-11` correct**: "beyond Read/Grep/Glob" presumes the reader *has* those tools. It does not — they are in `READER_DISALLOWED_TOOLS`. Left alone, doc 12 teaches the false tool surface in a **third** place after the two this unit already fixes | `Sub-21` (C) |
| `I-25` | `12-transcript-miner.md` §12.2 | 693 | *"reader containment (Read/Grep/Glob-less) is untouched"* | STILL TRUE — and it is the clause `I-20`/`I-22` contradict | `Rule D` |
| `I-26` | `12-transcript-miner.md` §3 | 178 | *"**Trigger: nightly `cron-claude` timer** (the house scheduler)"* — contradicted by the same file's §6 Q5 (*"a plain systemd user timer … not literally a cron-claude job"*) and by `systemd/self-learn-miner.timer` | **NOW FALSE** — but **out of this unit's mandate** (scheduling, not invocation) | `Rule D` + `FW-96` |
| `I-27` | `13-hosting-and-separation.md` §7.2 | 355–357 | *"The model's own writes (the worker's `claude -p`, `cwd=home`) can never be lock-guarded and are unfixable by AST"* | STALE | `Sub-12` (C) |
| `I-28` | `14-forward-work-map.md` `FW-86`…`FW-94` | 141–149 | the seam/SDK/provider residual rows | STILL TRUE | `Rule D` (this unit appends, never edits) |
| `I-29` | `forward/platform-drift.md` preamble | 5 | *"the Agent SDK (the pane engine)"* | **NOW FALSE** (scope) | `Sub-13` (B) |
| `I-30` | `forward/platform-drift.md` §1 heading | 13 | *"## 1. FW-23 — Agent SDK drift (the pane engine's ground)"* | **NOW FALSE** (scope) | `Sub-14` (B) |
| `I-31` | `forward/platform-drift.md` §1 exposure list | 15–23 | *"**Exposure, ranked**: (a) the pane engine …"* | STALE | `Sub-14` (C, same edit) |
| `I-32` | `forward/platform-drift.md` §1 fallback | 28–31 | *"the specced alternative engine (CLI `claude -p` stream-json subprocess …) is the standing fallback"* | STILL TRUE (UI pane; `cli` engine remains specced-not-built, root `README.md`) | `Rule D` |
| `I-33` | `forward/platform-drift.md` §3 exposure | 68–71 | *"`claude -p` flag surface (worker, miner, launcher all shell to it; the bundle-exclusion contingency adds the PATH-claude preflight, FW-14 …)"* | **STALE** *(regraded at r3 — at the shipped defaults all three surfaces DO shell to it; the clause is transport-bound, not false)* | `Sub-15` (**C**, was B) |
| `I-34` | `forward/platform-drift.md` §4 | 87–94 | the standing rule quoted in §1.1 | STILL TRUE | `Rule D` |
| `I-35` | `docs/specs/self-learn/README.md` status header | 5–11 | *"· **next phase: packaging** (`research/2026-07-18-sdk-bundle-exclusion.md`)"* — no mention of the Agent-SDK migration | **NOW FALSE** | `Sub-16` (B) |
| `I-36` | `docs/specs/self-learn/README.md` reading order | 31–54 | table ends at `15-orchestration-runbook.md`; no row for doc 17 | **MISSING** | `Sub-17` (E) |
| `I-37` | `docs/specs/self-learn/README.md`, 2026-07-15 entry | 480–495 | *"one contained claude -p reader driven by a versioned mining rubric"* | STILL TRUE (dated record) | `Rule A` |
| `I-38` | `docs/specs/self-learn/README.md` revision log | tail | last entry is **2026-07-24**; ~26 days and roughly two dozen shipped units unrecorded (`E-7`) | **MISSING** | `Sub-18` (one entry) + `FW-97` (the backlog) |
| `I-39` | root `README.md` §Install | 62–70 | `install.sh` → `uv sync --project …/cli` with no mention of the `[sdk]` extra | **MISSING** | `Sub-19` (E) |
| `I-40` | root `README.md` §Environment variables | 136–146 | UI-scoped table; no invocation-backend or provider variable anywhere in the file | **MISSING** | `Sub-20` (E) |
| `I-41` | root `README.md` §Pane engine note | 146, 150–157 | *(description, not a quote)* the `SELF_LEARN_PANE_ENGINE` env-table row documenting `sdk` as the default and `cli` as specced-but-unbuilt, plus the prose describing the pane's `claude-agent-sdk` session and its permission charter | STILL TRUE — these describe the **UI pane engine**, a separate seam with its own default, untouched by Waves 0–1 | `Rule D` |

**Tallies** *(restated at r3; three rows moved and one was added — see
the arithmetic note below)*. **42 sites enumerated.**
**NOW FALSE: 12** (`I-2`, `I-10`, `I-11`, `I-13`, `I-19`, `I-20`,
`I-22`, `I-26`, `I-29`, `I-30`, `I-35`, `I-42`) — of which `I-26` is out
of mandate and corrected by an `FW` row rather than an edit, leaving
**11 corrected here**.
**STALE-BUT-HARMLESS: 11** (`I-1`, `I-3`, `I-6`, `I-8`, `I-9`, `I-21`,
`I-23`, `I-24`, `I-27`, `I-31`, `I-33`) — of which 8 are amended and 3
left as records.
**STILL TRUE: 14** (`I-5`, `I-7`, `I-12`, `I-14`, `I-15`, `I-16`,
`I-17`, `I-18`, `I-25`, `I-28`, `I-32`, `I-34`, `I-37`, `I-41`).
**MISSING: 5** (`I-4`, `I-36`, `I-38`, `I-39`, `I-40`).
12 + 11 + 14 + 5 = 42.

**Arithmetic note, stated because the r2 gate projected a different
figure.** The gate's `NOTE-1` directed a retally of **12/9 → 11/10** on
the strength of `I-33`'s regrade alone. Two of its other findings move
rows in the same table: `MAJOR-1` **adds** `I-42` as NOW FALSE (+1), and
`MAJOR-5` regrades `I-24` STILL TRUE → STALE (−1 true, +1 stale). Folding
all three together, NOW FALSE lands back at **12** (−`I-33`, +`I-42`),
STALE at **11**, STILL TRUE at **14**, over **42** rows. The gate's
instruction is applied in full; the projected number was computed before
its own siblings were folded, and the number is restated here rather
than silently carried.

**The falsehoods are older than this migration.** **Eight of the twelve**
(`I-2`, `I-11`, `I-13`, `I-19`, `I-20`, `I-22`, `I-26`, `I-42`) were
false before any SDK code existed — made so by `U-repair`, `U-attrib`,
the 2026-07-15 containment audit, or, in `I-42`'s case, by an
implementation that simply never adopted the filename its own build-plan
row specified. Waves 0–1 did not create most of this debt; they made it
worth paying, because a runbook that tells an operator to flip a surface
is only as safe as the containment description the corpus carries.

### 3.2 `Sub-1` … `Sub-21` — the substitutions (NORMATIVE)

Each row gives the exact clause to find and the exact bytes to leave.
Nothing outside the quoted `before` is touched. Where a `before` spans a
sentence, the surrounding sentence is preserved verbatim.

---

**`Sub-1`** · `01-architecture.md` §3.3 · `Rule C` (append)

*Anchor, byte-exact from the file — the backticks around `--route` and
the bold opening before "detached" are part of it:*

```
When a learning lands (teach without `--route`, or import), a **detached
```

*That line is unique in the file. Append the following as a new sentence
at the **end of the paragraph it opens** — i.e. after* ``(`02-schema.md` §1).`` *:*

> *Amended 2026-08-19 (U-docs, Waves 0–1 of the Agent-SDK migration):*
> the worker's model invocation now runs through the **invocation seam**
> (`self_learn/invocation/`), whose backend is selectable per surface —
> `cli` (a `claude -p` subprocess, the shipped default at every rung) or
> `sdk` (an in-process `claude_agent_sdk` session). The transport is a
> configuration choice; everything else in this section — detachment,
> `setsid`, flock, append-only, proposer≠approver — is backend-independent
> and unchanged. Operator procedure: `17-invocation-runbook.md`.

**`Sub-2`** · `01-architecture.md` §3.3, "Restricted permissions" bullet ·
`Rule B` (replace)

*Before* (the clause after the bold lead-in):

> The worker runs `claude -p` with `--allowedTools` limited to reading
> the repo and writing new files under `.self-learn/**/proposals/`.

*After:*

> The worker's invocation grants **read tools only** through
> `--allowedTools` (`Read,Grep,Glob` — `worker.ALLOWED_TOOLS`) and denies
> `Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch` outright
> (`worker.DISALLOWED_TOOLS`); the **write** scope is a separate,
> narrower grant carried by the per-run settings file
> (`worker.write_settings_file`), and since `U-attrib` (`S-32`) that
> grant names an **exclusive stage** the model alone writes and the
> worker alone reads — never the ledger's `proposals/` directories, into
> which the worker itself installs validated output under the commit
> lock. *(corrected 2026-08-19, U-docs: the live CLI's `--allowedTools`
> cannot express a path scope at all — measured 2026-07-15, `08` revision
> log — so the old sentence named the wrong flag for the write grant, and
> named a directory `S-32` had already moved away from. The **property**
> the sentence was written to assert — no Bash, no Edit tool, no write
> path to any record — is unchanged and now holds on both backends,
> since the same `Containment` data drives the settings file on the `cli`
> path and the `can_use_tool` charter on the `sdk` path.)*

**`Sub-3`** · `03-decisions.md` `S-5` · `Rule C` (append to the Decision
cell, after the existing re-amendment)

> *Amended 2026-08-19 (U-docs, per the register's own rule — this row's
> stated input changed):* the rationale's conditional — *"SDK worker is a
> swap behind the same contract if needed"* — **has been built.** The
> contract is `S-34`'s invocation seam and the swap is `S-35`'s backend
> selector. `S-5` is unchanged as a decision: the worker is still a
> detached, coalesced, append-only pre-analysis pass, and its default
> transport is still a `claude -p` subprocess. What changed is that
> "detached `claude -p`" is now the **default**, not the definition.

**`Sub-4`** · `08-build-plan.md` §1, `teach --route` row · `Rule C`
(append inside the cell)

> *Amended 2026-08-19 (U-docs):* the one-shot analyst's transport is the
> `analyst` surface of the invocation seam; `claude -p` is its
> `backend=cli` default. `U-sdka` (Wave 2) flips this surface first —
> `17-invocation-runbook.md`.

**`Sub-5`** · `08-build-plan.md`, Worker run sequence, step (3) ·
`Rule B` (replace)

*Before:* `one `timeout 15m claude -p` invocation covering the batch + cluster pass`

*After:* ``one bounded model invocation covering the batch + cluster pass — `worker.invoke_timeout_secs()`, default `INVOKE_TIMEOUT_SECS = 30 * 60` and env-overridable via `SELF_LEARN_INVOKE_TIMEOUT_SECS`, through the invocation seam's `worker` surface`` *(corrected 2026-08-19, U-docs: the 15 m figure was raised to 30 m by `U-repair`, `FW-83`; the transport is now backend-selectable per `S-35`)*

**`Sub-6`** · `08-build-plan.md`, "Worker `claude -p` invocation" row ·
`Rule B` (replace the flag literal only; every other clause in this long
cell — model default, prompt ingredients, `record_sha` stamping,
normalization — is preserved verbatim)

*Before:* the parenthetical claiming the literal flag set, i.e. the
substring beginning `**Literal flag set, verified against the live CLI
at T13 start**` through the closing quote of
`Write(<HOME>/.self-learn/proposals/**)"`.

*After:*

> **Flag set — the PROPERTY is the pin; the literal lives in
> `worker.build_argv` and is re-read there, never transcribed here.** The
> property: read tools only (`--allowedTools "Read,Grep,Glob"`), an
> explicit deny list (`--disallowedTools
> "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"`), the write scope
> carried by `--settings <cache>/worker.settings.json` and nothing else,
> and `--strict-mcp-config`. *(corrected 2026-08-19, U-docs. The literal
> this row used to carry — `--allowedTools "…Write(<HOME>/…/proposals/**)"`
> — was disproved against the live CLI on 2026-07-15 and superseded by
> this file's own revision-log entry of that date; it was then superseded
> a second time by `U-attrib` (`S-32`), which repointed the write grant
> at an exclusive stage. A transcribed literal in this row has now been
> wrong twice and is not transcribed a third time. Under `S-35` the flag
> set is additionally **backend-conditional**: it is what the `cli`
> backend emits; the `sdk` backend consumes the same `Containment` data
> as Python objects and emits no argv at all.)*

**`Sub-7`** · `08-build-plan.md` §7.3 (a′) · `Rule B` (replace)

*Before:* `a real `claude -p` run under the pinned `--allowedTools`, instructed to write outside `proposals/`, is refused`

*After:* ``a real model invocation under the shipped containment, instructed to write outside its granted scope, is refused`` *(corrected 2026-08-19, U-docs: the refusal is enforced by the `--settings` file's `permissions.allow` rules plus `permissions.defaultMode`, not by `--allowedTools`, and since `S-32` the granted scope is the stage rather than `proposals/`. The criterion's point is unchanged and is now **stronger**, because it is the only check that can catch a containment that does not do what is believed — on either backend.)*

**`Sub-8`** · `11-telemetry-and-lifecycle.md` §4.2 · `Rule B` (replace
the em-dash clause; the bullet's first assertion is kept verbatim)

*Before:* `— its `--allowedTools` write surface stays proposals-only (S-5/E-18 unchanged).`

*After:* `— it holds no write path to the telemetry plane on either backend: `--allowedTools` grants read tools only, and the write grant (settings file on `cli`, charter on `sdk`) names the worker's exclusive stage and nothing else (S-5/E-18 unchanged; `S-32`).` *(corrected 2026-08-19, U-docs: `--allowedTools` never carried the write surface, and the scope is the stage, not `proposals/`. The bullet's claim — the analysis pass never writes telemetry — is unaffected and is now enforced by two mechanisms instead of one.)*

**`Sub-9`** · `12-transcript-miner.md` §2 "Phase 2" · `Rule B` (replace
the two false clauses; the settings-file clause is kept)

*Before:*

> One `claude -p` per run over batched digests (batch cap by digest
> bytes; unread files stay behind the cursor for the next run).
> Containment is the M2 worker posture verbatim: `--allowedTools
> "Read,Grep,Glob"`, the same disallow list, and a settings file granting
> the `Edit(//…)` rule family over the miner spool directory only (the
> live-verified syntax, 08 appendix 2026-07-15).

*After:*

> One model invocation per run over batched digests (batch cap by digest
> bytes; unread files stay behind the cursor for the next run) — the
> `miner-reader` surface of the invocation seam, `claude -p` by default.
> Containment is the worker posture **tightened, not copied**: the reader
> gets **no filesystem read tools at all** — `build_reader_argv` emits no
> `--allowedTools` flag, and `READER_DISALLOWED_TOOLS` is the worker's
> deny list **plus `Read,Grep,Glob`** — because the reader's entire
> evidence base rides in the prompt and transcript digests are
> attacker-influenceable text (audit 2026-07-15, injection hardening).
> Write stays available only through the settings file's `Edit(//…)` rule
> family, scoped to the cache spool (the live-verified syntax, 08
> appendix 2026-07-15). *(corrected 2026-08-19, U-docs: "the M2 worker
> posture verbatim" was wrong in the direction that matters — the reader
> is stricter, not equal — and this file already said so at §12.2
> ("reader containment (Read/Grep/Glob-less) is untouched"); the two
> statements contradicted each other and the code sides with §12.2.)*

**`Sub-10`** · `12-transcript-miner.md` §6 Q5 · `Rule C` (append to the
mechanism-note sentence)

> *Amended 2026-08-19 (U-docs):* "its own contained `claude -p`" is now
> "its own contained model invocation through the seam's `miner-reader`
> surface"; `claude -p` is the default backend. Note for operators: because
> the miner runs from a **systemd user timer**, and the user manager does
> not inherit a login shell's environment, a `SELF_LEARN_BACKEND_MINER`
> exported in a terminal **does not reach the nightly run** —
> `17-invocation-runbook.md` §4.

**`Sub-11`** · `12-transcript-miner.md` §9 T-M2 row · `Rule B` · **two
replacements in one bullet** (`I-22` and `I-42`)

*Before (a), the parenthetical's first clause:* `worker-posture `claude -p` (allowed Read/Grep/Glob; settings-file Edit rule family over the miner spool only; timeout; `SELF_LEARN_MINER_MODEL` default claude-sonnet-5)`

*After (a):* `reader invocation through the seam's `miner-reader` surface (**no** filesystem read tools — the worker deny list plus `Read,Grep,Glob`; settings-file Edit rule family over the miner spool only; timeout; `SELF_LEARN_MINER_MODEL` default claude-sonnet-5)` *(corrected 2026-08-19, U-docs — same defect as §2's Phase-2 paragraph; see `Sub-9`)*

*Before (b), the artifact clause two lines below:* `artifact contract: one `mine-<runid>.json`, schema-validated, stray spool files deleted`

*After (b):* `artifact contract: one file at a FIXED name — `mine-output.json` (`miner.OUTPUT_BASENAME`) — schema-validated, every other spool file deleted as litter` *(corrected 2026-08-19, U-docs: the run id is a `uuid4().hex[:8]` that appears only in log lines and `MineResult`, never in a filename. The old text was not merely stale — a file actually named `mine-<runid>.json` would be **swept by the very sweep the same clause describes**, so following it produced an artifact the miner deletes.)*

**Why both live in one `Sub`:** they are two clauses of the same bullet,
and splitting them would let a builder apply one and leave the other —
which is how `I-42` survived `Inv-1`'s first pass in the first place
(r1 read the bullet for its containment claim and stopped there).

**`Sub-21`** · `12-transcript-miner.md` §5, the znote-declined bullet ·
`Rule C` (append to clause (3), after *"live-verified on 2026-07-15"*)

> *Amended 2026-08-19 (U-docs):* read "beyond Read/Grep/Glob" as "beyond
> the reader's tool surface, which is **empty**" — those three are in
> `READER_DISALLOWED_TOOLS`, not granted (see §2's Phase-2 paragraph as
> corrected, and `Sub-9`). The argument is unaffected and in fact
> stronger: granting the miner an MCP tool surface would not widen a
> narrow grant, it would **create** one where none exists.

**`Sub-12`** · `13-hosting-and-separation.md` §7.2 · `Rule C` (append
after the sentence)

> *Amended 2026-08-19 (U-docs):* still true of the model's own writes on
> either backend — but since `U-attrib` (`S-32`) those writes land in an
> exclusive **stage**, and the **install** from stage into the ledger
> runs inside the worker under the commit lock. The unguardable window is
> now the stage, which no other producer reads, rather than the ledger
> itself; `reconcile` remains the answer for anything that escapes.

**`Sub-13`** · `forward/platform-drift.md` preamble · `Rule B` (replace)

*Before:* `the Agent SDK (the pane engine)`

*After:* `the Agent SDK (the G-3 pane engine **and, since Wave 1 of the Agent-SDK migration, the CLI's optional invocation backend** — `S-34`/`S-35`)` *(corrected 2026-08-19, U-docs: the exposure is no longer confined to the UI package)*

**`Sub-14`** · `forward/platform-drift.md` §1 · `Rule B` on the heading +
`Rule C` on the exposure list

*Heading before:* `## 1. FW-23 — Agent SDK drift (the pane engine's ground)`
*Heading after:* `## 1. FW-23 — Agent SDK drift (the pane engine's ground — and, since Wave 1, the CLI's too)`

*Append to the end of the "Exposure, ranked" paragraph:*

> *Amended 2026-08-19 (U-docs):* a **fourth** exposure now sits beside
> (a)–(c) and is ranked with them: **(d) the CLI's `sdk` invocation
> backend** — `claude_agent_sdk` is a declared optional dependency of
> `self-learn-cli` (`[sdk]` extra, pinned `>=0.2.116,<0.3`), and the
> backend depends on `ClaudeAgentOptions` field names, `setting_sources`
> isolation, the `can_use_tool` callback, and `ResultMessage`'s
> `total_cost_usd`/`num_turns`/`session_id` attributes. The protocol is
> unchanged and now covers two consumers: pin, re-run the probe battery
> on any bump, and — new — run `self-learn doctor invocation`, whose
> `sdk` row reports the resolved SDK version alongside the bundled and
> host `claude` CLI versions and WARNs when they diverge. The standing
> fallback for the CLI side is the same shape as the pane's: every rung's
> default is `cli`, so a broken SDK is an unset environment variable
> away from irrelevant (`17-invocation-runbook.md` §6).

**`Sub-15`** · `forward/platform-drift.md` §3 exposure bullet · `Rule C`
(append; the original parenthetical keeps its bytes)

*Append at the end of the bullet, before §3's "**Protocol**" sentence:*

> *Amended 2026-08-19 (U-docs):* the "all shell to it" half is now
> **conditional** for three of those callers — the worker, miner and
> analyst reach the CLI through the invocation seam and shell to it
> **only under `backend=cli`**, which is every rung's default (`S-35`),
> so the sentence is true today and stops being true one environment
> variable at a time. The launcher's own use is untouched by that
> migration and was not audited here. Separately, **FW-14's PATH-claude
> preflight has landed**: `self-learn doctor invocation`'s `sdk` row
> resolves the host `claude` (PATH, or `SELF_LEARN_SDK_CLI_PATH`) and
> reports its version beside the SDK's bundled one, WARNing on skew —
> the version-visibility hook this bullet listed as a contingency is
> shipped.

*(Regraded from `Rule B` at r3: the clause is transport-bound, not
false, and `Rule C` is what this document's own §1.2 prescribes for
that. Replacing bytes that are still accurate at the shipped defaults
would have been the sweep overreaching.)*

**`Sub-16`** · `docs/specs/self-learn/README.md` status header ·
`Rule B` (replace the trailing phase clause)

*Before:* `· **next phase: packaging** (`research/2026-07-18-sdk-bundle-exclusion.md`)`

*After:* `· **Agent-SDK migration Waves 0–1 SHIPPED 2026-08-09/19** (invocation seam → `SdkBackend` → provider/Bedrock contract + `doctor invocation` → test tiering; `S-34`–`S-42`, `17-invocation-runbook.md`) · **next: Wave 2 — the analyst flip (`U-sdka`) and the per-surface burn-ins**; packaging (`research/2026-07-18-sdk-bundle-exclusion.md`) is queued behind it` *(corrected 2026-08-19, U-docs: the header named a phase that did not happen next and omitted the four units that did)*

**`Sub-17`** · `docs/specs/self-learn/README.md` reading-order table ·
`Rule E` (one new row, immediately after the `15-orchestration-runbook.md`
row)

> \| `17-invocation-runbook.md` \| **The operator runbook for the two
> invocation switches** (`backend` per surface, `provider` install-wide):
> the doctor preflight ritual, the flip and rollback one-liners with
> their measured traps, the per-surface burn-in gates, and the
> instrument gaps those gates inherit — written so an operator can flip
> a surface, watch it, and put it back without reading a spec \|

**`Sub-18`** · `docs/specs/self-learn/README.md` revision log ·
`Rule E` (one appended bullet, in the log's existing
`- **<date> — <title>.** <prose>` format)

*Insertion point, stated by position rather than by a date string — the
log carries **two** 2026-07-24 entries (`E-18` measured it; a date
anchor is ambiguous here). Append after the **final** bullet of the file,
the one whose last line is* `source-available by design. The ledger's private posture is unchanged.` *(the file's last line at `89f8ef7`). The new bullet is the file's new last line.*

> - **2026-08-19 — docs-truth sweep + the operator runbook (U-docs,
>   Wave 2).** The Agent-SDK migration's Waves 0–1 shipped four units
>   (`U-seam`, `U-sdk`, `U-bedrock`, `U-fake`) without a single numbered
>   doc recording them, against `forward/platform-drift.md` §4's standing
>   rule that an engine swap is never absorbed silently. This unit swept
>   the numbered corpus for every claim about model invocation — 42 sites
>   enumerated, 12 measured NOW FALSE, 11 stale, 14 still true, 5 missing —
>   corrected 11 of the 12 by bounded substitution (`I-26`, a scheduling
>   claim, was out of mandate and became `FW-96`), landed the eight
>   decision rows the migration owed (`S-34`/`S-35`, reserved by `U-seam`
>   §7.5 and never written; plus `S-39`–`S-44`, which give the 2026-08-09
>   user rulings their first in-repo record), and wrote
>   `17-invocation-runbook.md`. **Eight of the twelve falsehoods predate
>   the migration** — `U-repair`, `U-attrib` and the 2026-07-15
>   containment audit each moved the shipped mechanism without moving the
>   corpus, and one clause described an artifact filename the
>   implementation never adopted. Full inventory, per-site substitutions
>   and the gate's verification table:
>   `drafts/u-docs-truth-sweep-spec.md`.

**`Sub-19`** · root `README.md` §Install, "Full install" block ·
`Rule E` (one new paragraph, placed **immediately after the
live-symlink paragraph** — the one beginning ``` `install.sh` is a
**live-symlink** deploy ``` — and **before** the paragraph beginning
*"The ledger needs a git repo at `$SELF_LEARN_HOME`"*. Not directly
after the code block: the live-symlink paragraph is about that block and
must stay adjacent to it.)

> **If you intend to run any surface on the `sdk` invocation backend**,
> install the CLI's optional extra as well — `install.sh` does not
> (`uv sync --project plugins/self-learn/cli` installs the base
> dependency set only), so a surface flipped to `sdk` without it refuses
> at invocation time with *the "sdk" invocation backend is not built yet*.
> `uv sync --project plugins/self-learn/cli --extra sdk`, or
> `pip install 'self-learn-cli[sdk]'`. See
> `docs/specs/self-learn/17-invocation-runbook.md`.

**`Sub-20`** · root `README.md` · `Rule E` (one new subsection, placed
**after** `### Pane engine note` and before `### Browser notes`, so the
UI-scoped environment table above it is not implied to cover it)

> ### Invocation backend (CLI surfaces)
>
> The three CLI surfaces that invoke a model — the pre-analysis worker
> (and its repair round), the transcript miner's reader, and the
> `teach --route` analyst — run behind one seam whose backend is
> selectable per surface: `cli` (a `claude -p` subprocess) or `sdk` (an
> in-process `claude_agent_sdk` session). **Every surface defaults to
> `cli`**; nothing is flipped by installing. A second, orthogonal,
> install-wide switch selects the `provider` (`anthropic` or `bedrock`).
>
> Check what is resolved on this machine with `self-learn doctor
> invocation`. The full procedure — flip and rollback one-liners, the
> measured traps, the per-surface burn-in gates — is
> `docs/specs/self-learn/17-invocation-runbook.md`. These switches are
> deliberately absent from the environment table above: that table is
> the UI's.

### 3.3 `Dec-1` — the decision rows (NORMATIVE)

Eight rows, appended to `03-decisions.md`'s Settled table in numeric
order. `S-34` and `S-35` are inserted **in sequence** between `S-33` and
`S-36`, closing the gap the register currently shows; `S-39`–`S-44` are
appended after `S-38`.

**The `S-34`/`S-35` backfill is ratified as in scope for this unit**
(orchestrator, 2026-08-19). Their obliged content is named in `U-seam`'s
own may-touch table and §7.5, on master — the builder reads it there,
not from this spec's paraphrase, and `DR2` is the check that the
expansion below does not exceed what §7.5 reserved.

**`S-39`–`S-44` all cite one out-of-repo source**,
`~/.claude/plans/indexed-kindling-lightning.md` — the migration plan the
user approved in plan mode on 2026-08-09. It is durable and quotable but
it is not in this repository, which is why `E-1`'s corpus search found
nothing and why these rows exist at all. Every quotation below was read
from that file at this spec's r2 fold; where a row quotes it, the quote
is verbatim and marked as such.

---

**`S-34`**

> \| S-34 \| **The invocation seam exists: one package (`self_learn/invocation/`)
> behind which every `claude` process spawn in the CLI lives.** Four
> surfaces (`worker`, `worker-repair`, `miner-reader`, `analyst`), three
> call sites (`worker._invoke_claude`, `miner._invoke_reader`,
> `analyst.analyze`), two operations (`write_session` — the model writes
> files, stdout is never parsed; `text_session` — the analyst's, where
> stdout *is* the result). Containment is **data** (`Containment`), not a
> flag string: the same object renders to the `cli` backend's
> settings-file permission rules and argv flags, and to the `sdk`
> backend's `can_use_tool` charter, so the boundary cannot drift between
> transports. **Neither seam operation raises** — every failure becomes
> an `Outcome` — with exactly one deliberate exception, and it is on
> `text_session`: a bare `OSError` from a `CliBackend` on the **analyst**
> surface still escapes, preserved byte-for-byte by `U-seam` and owned by
> `FW-87`/`U-sdka`. **`write_session` has no such leg on any surface** —
> the analyst is the only operation that can leak an `OSError` and the
> analyst never calls `write_session` (`registry.py`'s own docstring:
> *"that surface never reaches `write_session`"*). `Containment` enforces
> nothing itself; it
> describes what the settings file and the charter enforce. \| `U-seam`
> spec §3.2/§3.3/§3.10 and §7.5
> (`docs/specs/self-learn/drafts/u-seam-invocation-seam-spec.md`),
> reserved there for this register and landed 2026-08-19 by `U-docs`
> rather than by `U-seam`'s own build — see `S-42`. \|

**`S-35`**

> \| S-35 \| **Backend selection is a five-rung precedence chain, per
> surface, fail-closed to `cli`.** In order, first hit wins:
> `SELF_LEARN_BACKEND_<SELECTOR>` (env) → `SELF_LEARN_BACKEND` (env) →
> `<ledger-home>/config.yaml`'s `invocation.backend_<surface>` →
> `invocation.backend` → the built-in default `"cli"`. Three selectors
> cover four surfaces (`WORKER` serves both `worker` and `worker-repair`;
> `MINER` serves `miner-reader`; `ANALYST` serves `analyst`), so the
> repair round is never independently configurable **by environment** —
> though it is by config key, whose suffix is the surface literal
> (`backend_worker-repair`). An empty or unset value at a rung is "no
> answer" and falls through **silently**; an *unknown* value is not — it
> warns once on stderr and resolves `cli`. The `config.yaml` in question
> is the same committed ledger file `S-10`'s `one_motion_route:` lives
> in: policy that changes which transport executes belongs in git
> history, synced and revocable by commit. Resolution reads that file
> because every surface passes the ledger home as its session `cwd`. \|
> `U-seam` spec §3.7 and §7.5; shipped at
> `invocation/registry.py::backend_for` and `config.py::invocation_backend`.
> Operator-facing procedure: `17-invocation-runbook.md`. Landed
> 2026-08-19 by `U-docs` — see `S-42`. \|

**`S-39`**

> \| S-39 \| **The model transport is a switchable backend, not a fixed
> property of the product** — the Agent SDK sits behind the same seam as
> the `claude -p` subprocess, and either may serve any surface. Two
> consequences bind future work: (1) **the default at every rung stays
> `cli` until a surface passes its burn-in** (`S-40`) — shipping the
> capability is not shipping the flip, and `U-sdk` explicitly declined to
> move any default; (2) **anything that describes invocation must
> describe it as backend-conditional**, which is the standing obligation
> `forward/platform-drift.md` §4 already imposed on engine swaps and
> which Waves 0–1 did not discharge (this unit's whole §3.1 inventory is
> the measured cost of that miss). \| **User ruling 2026-08-09**, ruling 2
> of four in the approved migration plan, verbatim: *"**Cutover:**
> switchable backend. The CLI subprocess path is retained verbatim behind
> a config switch; CLI stays default until burn-in passes; a final
> cleanup unit deletes it. Under `backend=cli`, behavior stays
> byte-identical."* The three rulings it shipped with, same date and same
> binding force: **sequencing** — the three paused campaign units land
> first, because `U-attrib` rewrites the very `worker.py` layers this
> migration replaces; **Bedrock** — *"no live testing possible. Ship the
> configuration surface, contract tests against a fake, and a preflight
> `doctor` that validates config/env/credential shape without any API
> call"* (which is exactly what `S-36`/`S-37` record as built);
> **parallelisation** — disjoint-surface units as concurrent two-gate
> pipelines under `S-18`'s model split. **Provenance note, stated because
> this corpus treats an absent quote as a signal** (the convention `S-23`
> set): the ruling record is **durable but out-of-repo**, at
> `~/.claude/plans/indexed-kindling-lightning.md` §"User rulings
> (binding, 2026-08-09)" — approved by the user in plan mode. Nothing
> inside this repository quotes it; every in-repo artifact refers to it
> only as *"the approved Agent-SDK migration"* (`U-seam`, `U-sdk`,
> `U-bedrock` and `U-fake` spec preambles; `14-forward-work-map.md`'s
> 2026-08-09 entry). This row is therefore the ruling's **first in-repo
> record**; the plan file is authority over it, and **the user's own
> wording outranks both.** \|

**`S-40`**

> \| S-40 \| **The flip order is analyst → miner → worker, one surface at
> a time, each gated by a per-surface burn-in.** The order is
> attended-first: the analyst runs synchronously in front of a human who
> typed `teach --route` and sees its output immediately; the miner runs
> unattended on a nightly timer; the worker runs unattended **and
> commits to the ledger**, so it is last and its burn-in is the only one
> that includes a repair round, a commit and a push. A mixed install —
> some surfaces `sdk`, some `cli` — is the **normal intermediate state**
> of this rollout and must never be reported as an error (`S-36`,
> `FW-89`); the doctor renders it as per-surface INFO and reserves FAIL
> for a *wholly* inert configuration. The burn-in gates themselves are
> recorded in `17-invocation-runbook.md` §5, which is their first
> home in this repository. \| Order stated in `S-36`, `FW-89`, and
> `U-bedrock` spec §3.5 (*"The rollout flips surfaces one at a time in
> the order analyst → miner → worker; `provider` is install-wide
> (`D-2`)"*), with the rationale at that spec's **`D-2`** (§6, builder
> decisions) and **`Q-2`** (§10, values questions — *"Mixed backend flips
> already deliver attended-analyst-first, so per-surface provider buys
> nothing and doubles the precedence matrix"*). Flip order and its
> reason are the approved migration plan's, §"Rollout / burn-in /
> rollback": *"attended-first; the analyst flip is also the F3 security
> fix; worker last — it commits to the ledger."* Gate criteria from the
> same section — **an out-of-repo artifact**, which is why this row and
> the runbook exist. `U-sdk` spec §7.3 `R-6` names the owner it was
> waiting for: *"no burn-in evidence exists for any surface … Owner: the
> post-merge burn-in unit."* \|

**`S-41`**

> \| S-41 \| **Defects found on a surface that Wave 2 will rewrite are
> preserved, not fixed in place — the "wait for the flip" disposition —
> and each one names the flip that closes it.** The worked case is
> `analyst.analyze`'s missing bare-`OSError` leg: `U-seam`'s charter was
> byte-identity under `backend=cli`, so the not-caught behavior was
> pinned as existing behavior (`T-c`, `TR4`) rather than silently
> changed, and the obligation was handed forward — *"the SDK flip
> dissolves the subprocess layer but not the obligation — the error
> contract must catch into `AnalystError` on BOTH backends so
> capture-to-pending holds regardless of the switch"* (`FW-87`).
> **The disposition's headline case is a security hole, not an error
> leg.** The plan records it as finding **F3** and rules on it verbatim:
> *"**F3 (analyst containment hole)**: the teach-route session's tools
> fall through to the host's `bypassPermissions` default today. User
> ruling: **wait for the SDK flip** — no CLI-side carve-out; the analyst
> flips FIRST and its hardening (deny-list, deny-all-writes callback,
> strict MCP, isolation) rides that flip."* That is why the analyst is
> first in `S-40`'s order and not merely the easiest surface: **the first
> flip is also the security fix.** The plan's own scout table says the
> analyst's containment is the *"WEAKEST"* of the three — allow-list
> only, no settings file, no deny list, no `--strict-mcp-config`. The
> rule generalizes past both cases: a unit whose contract is *no
> observable change* may not fix what it finds, even when what it finds
> is a hole, and the correct move is a dated forward row naming the
> closing unit — never a silent fix, never a forgotten defect.
> **Closure:** `U-sdka` (Wave 2) owns both — `FW-87`'s error leg with a
> test on each backend, and F3's hardening riding the flip itself. \|
> `~/.claude/plans/indexed-kindling-lightning.md` §"User rulings recorded
> during planning (2026-08-09)" and its §"Verified facts" scout table;
> `U-seam` spec §7.3 `R-1` and §"This unit changes no behavior" (*"A
> builder who finds themselves fixing a defect they discovered on the way
> has left this unit's mandate and must stop and report"*);
> `14-forward-work-map.md` `FW-87`. \|

**`S-42`**

> \| S-42 \| **A spec that reserves a register row owes the row at ITS
> OWN merge; when that does not happen, the row is written by whoever
> next notices — with the delay recorded.** `U-seam`'s files-may-touch
> table listed `03-decisions.md` with the footprint *"New rows `S-34`,
> `S-35` (§7.5), landing in the same commit as the build"*; the build
> merged (`e2e63a2`, 2026-08-09) and the rows did not land. **Measured**
> at `89f8ef7`: the register ran `S-33` → `S-36` for ten days, so the
> two decisions the entire migration rests on — the seam and the backend
> selector — were undocumented in the register while three further units
> built on them. The same class of gap accounts for four of the five
> `MISSING` rows in this unit's inventory. Standing consequence: the
> disposition-rule discipline this corpus already applies to accepted
> residuals (*"an undeclared residual is one a later agent re-opens as a
> bug"* — the campaign playbook §1, cited by `S-24`…`S-33`) **applies
> equally to reserved register rows**, and a round-close is not complete
> while one is outstanding. \| `U-seam` spec §"Files this unit may touch"
> and §7.5, against the register's measured state at `89f8ef7`. Recorded
> 2026-08-19 by `U-docs`, which lands `S-34`/`S-35` late rather than
> leaving them unwritten. \|

**`S-43`**

> \| S-43 \| **`claude-agent-sdk` ships as an OPTIONAL EXTRA
> (`self-learn-cli[sdk]`), never a hard dependency.** The bundle is
> ~252 MB; a machine that never leaves `backend=cli` pays none of it.
> The cost of the choice is one failure mode, and it is made clean rather
> than removed: a surface resolved to `sdk` on an install without the
> extra raises `BackendUnavailable`, whose message **names the install
> command** — the refusal is a byte-pinned two-line string, not a
> traceback. Two consequences the corpus must carry: (1) `install.sh`
> does **not** install the extra, so "flip a surface" is a two-step
> operation on a default install and the runbook says so before it gives
> any flip instruction; (2) the extra's presence changes steady-state
> behavior — `--selftest` spawns a real `claude --version` per run once
> `claude_agent_sdk` is importable (`FW-94`). \| `~/.claude/plans/indexed-kindling-lightning.md`
> §"User rulings recorded during planning (2026-08-09)", adopted designer
> recommendation, verbatim: *"`claude-agent-sdk` ships as an **optional
> extra** (`self-learn-cli[sdk]`), not a hard dep (252 MB bundle;
> cli-backend machines pay nothing; registry raises a clean
> `BackendUnavailable` naming the install command)."* Shipped at
> `plugins/self-learn/cli/pyproject.toml`
> (`sdk = ["claude-agent-sdk>=0.2.116,<0.3"]`) and
> `invocation/registry.py::_SDK_UNAVAILABLE_MESSAGE`. Recorded 2026-08-19
> by `U-docs`. \|

**`S-44`**

> \| S-44 \| **Attribution is capture-now, consume-later: the SDK
> backend's `tool_events` and `denials` are captured from day one and
> deliberately have no consumer yet.** `SdkOutcome` carries both as
> frozen tuples, populated from the charter callback's own denials and
> from `ResultMessage.permission_denials`, and written to a per-run event
> log. **Nothing reads them.** That is the decision, not an oversight:
> the consumer is a post-burn-in unit (`U-corrob`), and building it now
> would mean re-editing `U-attrib`'s freshly-landed `_harvest` — the
> exact churn `S-32`'s structural-attribution design was written to stop.
> **The standing constraint on that future unit, stated here so it is not
> rediscovered as a question: the filesystem diff remains the
> authority.** Tool events are corroboration, never the primary record of
> what the model wrote — a model's self-report of its own tool calls is
> not evidence of provenance, which is the whole lesson `FW-84` cost.
> Operational consequence today: the worker burn-in's *0 out-of-scope
> writes* gate reads `denials` **and** the filesystem diff, and the two
> must agree (`S-40`). \| `~/.claude/plans/indexed-kindling-lightning.md`
> §"User rulings recorded during planning (2026-08-09)", the **"Adopted
> designer recommendations"** bullet — the same bullet `S-43` quotes,
> whose second sentence is this one — verbatim:
> *"Attribution: SDK `tool_events`/`denials` **fields captured now**,
> consumer is post-burn-in U-corrob (avoids re-editing U-attrib's fresh
> `_harvest`)"*. The *filesystem-diff-stays-authority* half comes from a
> different section of the same file — §"Units, DAG, schedule", the
> **"Burn-in → Wave 3"** bullet (a bolded bullet label, not a heading):
> *"**U-corrob** (attribution consumer; filesystem diff stays
> authority)"*. Shipped at
> `invocation_sdk/backend.py::SdkOutcome` and
> `invocation_sdk/events.py` (`add_denial`, `add_sdk_permission_denial`,
> `add_tool_use`, `add_tool_result`, `write_event_log`). Recorded
> 2026-08-19 by `U-docs`. \|

**Numbering note for the builder.** The register's Settled table
currently ends `… S-33 | S-36 | S-37 | S-38`. `S-34`/`S-35` go **in the
gap**, in order, so the sequence reads contiguously afterwards.
`S-39`–`S-44` are appended after `S-38`. No existing row is renumbered —
`S-36`, `S-37` and `S-38` are cited by name from `U-bedrock`'s spec and
`FW-93`, and renumbering them would break those citations.

### 3.4 `RB-1` — the runbook (NORMATIVE)

**Location: `docs/specs/self-learn/17-invocation-runbook.md`.**
Full content is **Appendix A**; the builder copies it verbatim, changing
nothing but the date line if the build lands on a different day.

`D-1` records the decision and its alternatives. In brief: `15` is the
only existing runbook and is explicitly **agent-facing** (*"how the agent
rounds actually run"*, addressed to orchestrators, builders and
reviewers); an operator runbook is a different document for a different
reader, and the corpus has none. The number **16 is taken** —
`drafts/16-ecology-spec.md` titles itself `# 16 — Worker-ecology
channels & the portfolio auditor` and is referenced as *"doc-16
candidate"* in the README's revision log — so this document takes **17**
and the gap at 16 is deliberate, not an off-by-one. `D-1` also records
the reversal path, because the choice is cheap to undo.

**The runbook's own scope fence, stated here so the gate can check the
appendix against it:** it covers the two switches, the doctor ritual, the
flip and rollback mechanics, the burn-in gates, and the traps. It does
**not** duplicate `U-bedrock`'s doctor design, does not explain the SDK
backend's internals, does not tell anyone to flip anything today, and
does not contain a credential, a path under a real home directory, or a
real record id.

### 3.5 `Fwd-1` — the forward rows this unit lands (NORMATIVE)

Appended to `14-forward-work-map.md`'s table after `FW-94`, plus one
dated bullet in that file's own change log. No existing row is edited.

**`FW-95`** — *type* **BUILD**

> **The `cost ≤ 1.5× cli baseline` burn-in gate has no instrument on the
> `cli` side of the comparison.** `Outcome` (`invocation/contract.py`)
> carries `ok, rc, stdout, detail, failure, exc` and no cost or turn
> field; only `SdkOutcome` (`invocation_sdk/backend.py`) adds `cost_usd`,
> `turns`, `session_id`, populated from `ResultMessage`'s
> `total_cost_usd`/`num_turns`. **`CliBackend` never returns an
> `SdkOutcome` and has no code path that would populate either field**,
> so the `cli` baseline the cross-cutting gate compares against cannot
> come from this product. Consequence: as written, the gate is
> half-measurable — the `sdk` side self-reports, the `cli` side does not
> — and the "isolation should be CHEAPER" heuristic (`setting_sources=[]`
> + `settings=None` mean the sdk session loads no settings file and no
> CLAUDE.md, so its input token count should be *lower* than the cli
> child's, which inherits the host's) inherits the same gap. The runbook
> (`17` §5.5) states the two substitutes available today — an external
> control run of `claude -p --output-format json` capturing
> `total_cost_usd`, or the provider's own usage reporting for the window
> — and states plainly that neither is built. Found by `U-docs` while
> writing the burn-in section; not fixable by a docs unit.
> **Resolution direction, ruled 2026-08-19: the denominator comes from
> the operator's own billing surface (the API console's usage for the
> window), NOT from the product** — so the gate is executable today by an
> operator, and no code is owed for the ratio itself. What remains open
> is the *method*: console-window comparison is coarse (it cannot
> attribute cost to a surface), and a per-run figure would need either
> `CliBackend` reading `--output-format json`'s `total_cost_usd` or an
> external control run. *Action:* pick the method and write it into `17`
> §5.5 **before the first burn-in closes** — a ratio whose measurement
> was decided afterwards is a ratio nobody trusts. Owner: the
> post-burn-in recalibration unit `U-sdk` §7.3 `R-7` already names, if a
> code-side figure is wanted; otherwise the first burn-in itself closes
> this row by recording what it actually measured.

**`FW-96`** — *type* **BUILD**

> **`12-transcript-miner.md` contradicts itself on the miner's
> scheduler.** §3 says *"**Trigger: nightly `cron-claude` timer** (the
> house scheduler)"*; §6 Q5 says *"the schedule is a plain systemd user
> timer executing `self-learn mine run` — not literally a cron-claude
> job"*; the shipped artifact is `systemd/self-learn-miner.timer` +
> `self-learn-miner.service`, so §6 Q5 is right and §3 is stale. Found by
> `U-docs`'s inventory sweep (`I-26`) and left uncorrected **because it
> is out of that unit's mandate** — a scheduling claim, not an invocation
> claim — and correcting it silently under an invocation-layer scope
> fence is exactly the smuggling the two-gate discipline exists to
> prevent. *Action:* one-clause substitution in §3 with a dated marker,
> by whichever unit next has doc 12 in its may-touch table. Trivial,
> docs-only, no behavior change.

**`FW-97`** — *type* **WATCH**

> **`docs/specs/self-learn/README.md`'s revision log is ~26 days and
> roughly two dozen shipped units stale.** Its last entry before this
> unit's is **2026-07-24**; between then and `89f8ef7` the repo shipped
> (at least) `U-repair`, `U-attrib`, `U-pointer`, `U-cursorhold`,
> `U-forcefail`, `U-seam`, `U-sdk`, `U-bedrock` and `U-fake`, none of
> them logged. `15-orchestration-runbook.md` §1 step 7 makes the entry
> part of round-close, so the gap is a **process** miss, not a docs
> backlog: the log is the corpus's index into its own history, and an
> unlogged unit is one a future reader cannot find from the front door.
> `U-docs` appended its own entry (`Sub-18`) and **deliberately did not
> back-fill the others** — reconstructing nine round-closes from git
> history and spec drafts would produce a plausible narrative rather than
> a record, which is the opposite of what the log is for. *Action:* the
> honest fix is one entry per unit written by whoever still remembers the
> round, or an explicit dated note in the log declaring the gap and
> pointing at `records-index.md` and the git log instead. Decide which;
> do not silently reconstruct.

### 3.6 What this unit deliberately does not do

- **No numbered doc is rewritten.** **Twenty-one** bounded substitutions
  (`Sub-1`…`Sub-21`), carrying **23 operations**: **eleven** replace a
  clause (`Rule B`), **eight** append one (`Rule C`), **four** add
  something absent (`Rule E`). The count exceeds 21 because two
  substitutions do two things each — `Sub-14` replaces
  `platform-drift.md` §1's heading *and* appends to that section's
  exposure list, and `Sub-11` replaces **two** clauses of one T-M2
  bullet (the containment parenthetical and the artifact-filename
  contract). Both are single edits to a single region, deliberately not
  split: splitting `Sub-11` is how `I-42` went unnoticed at r1.
- **No dated record is edited** (`Rule A`), including the two that are
  now superseded (`I-15`, `I-37`).
- **No surface's default backend moves**, no `config.yaml` is written,
  no `install.sh` behavior changes. `Sub-19` documents the extra; it does
  not install it.
- **No source comment or systemd unit comment is touched**, though three
  of them describe `claude -p` as *the* transport (§7.1-e).
- **No `records-index.md` row.** That file indexes review records,
  research memos and trial-log sections; a numbered corpus doc is none of
  those, and the reading-order table (`Sub-17`) is where a numbered doc
  is indexed.

---

## 4. Acceptance criteria

Twenty criteria: `IV` 4 + `SB` 5 + `DR` 5 + `RB` 4 + `HY` 2. Every one
is checkable by reading files in this repository; none requires running
the test suite, because this unit changes no code. `§5` gives the gate
the command or read for each.

### IV — the inventory

- **`IV1`** — every row of `Inv-1`'s table resolves. For a row whose
  "current text" column carries a **quotation**, the quoted substring
  must be present in the named file at `89f8ef7`, in the named section,
  under `§0.6`'s whitespace normalization. A handful of rows carry a
  **description** instead of a quotation — marked *(description, not a
  quote)* — because the site is a table row or a multi-paragraph region
  that no single substring represents; those resolve if the named
  section exists and contains what the description says. A quotation
  that cannot be found is a defect in this spec, not a licence to
  search.
- **`IV2`** — the four tallies sum to the row count, and each verdict's
  membership list in §3.1 matches the table's `Verdict` column exactly.
- **`IV3`** — every `NOW FALSE` verdict is falsified against **shipped
  code or a shipped artifact**, not against another document: the
  falsifier for each is named in §5's table and is a symbol, a constant,
  or a file the gate can read.
- **`IV4`** — completeness, **scoped so that it can fail for the right
  reason.** The gate re-runs the two greps in §5 over the brief's scope
  (`docs/specs/self-learn/*.md`, `docs/specs/self-learn/forward/*.md`,
  root `README.md`) and diffs the hit set against `Inv-1`. The criterion
  is: **no hit is unaccounted for.** A hit is accounted for if it is
  either (a) a row in `Inv-1`, or (b) inside one of the files/regions
  §7.1 records as judged-and-left, which are, enumerated here so the
  check is mechanical rather than a matter of taste:
  **`09-surface-spec.md` and `10-surface-build-plan.md` in full**
  (§7.1-f — UI pane engine, a different seam), **`records-index.md`**
  (an index of record filenames, not a claim about anything),
  **`forward/packaging.md`** (SDK bundle-exclusion research, packaging
  scope), and **any hit inside a dated record** protected by `Rule A`.
  **For doc 14 that last leg is two named sections, not a judgment
  call** — `## 6a. Dated dispositions` and `## 6b. Dated additions log`.
  Both are dated logs; a hit inside either is a record, not a finding.
  *(Named explicitly for the builder-verifier: the delta gate's first
  mechanization of this criterion enumerated only §6a and produced one
  spurious hit at `14:320` — a `--strict-mcp-config` mention inside a
  §6b additions entry. Two headings, not one.)*
  **An unaccounted-for hit is a BLOCKER**; a hit inside (b) is not a
  finding and must not be reported as one. *(Scoped at r3: the r1 wording
  — "no site … is absent from `Inv-1`" — made every deliberate exclusion
  and every accurate dated row a BLOCKER, ~20 of them. A criterion that
  fires on correct work is not strict, it is broken, and it would have
  buried the one real miss (`I-42`) in noise.)*

### SB — the substitutions

- **`SB1`** — every `Sub-n` names a `before` string that occurs
  **exactly once** in its target file **under whitespace normalization**
  (`§0.6`), and an `after` string that differs from it. A `before` with
  two occurrences is a defect in this spec; a `before` with zero raw-grep
  occurrences is **not**, until it has also been checked unwrapped.
- **`SB2`** — every `Rule B` substitution's `after` string contains a
  dated `*(corrected 2026-08-19, U-docs: …)*` marker naming what was
  wrong; every `Rule C` substitution's `after` contains
  `*Amended 2026-08-19 (U-docs…)*`. No substitution silently changes
  meaning.
- **`SB3`** — no `Sub-n` targets a dated record. The gate checks each
  target against §7.1's protected-site list and against the file's own
  revision-log/amendment markers.
- **`SB4`** — after the build, the eleven `NOW FALSE` clauses corrected
  here are absent from their files, and the **fourteen** `STILL TRUE`
  sites are byte-identical to `89f8ef7`
  (`I-24` left that set at r3 — §3.1's tally is the register for this
  figure, and a criterion restating it must move with it).
  `git diff 89f8ef7..HEAD -- docs/ README.md`
  touches only the files in the may-touch table.
- **`SB5`** — `git diff 89f8ef7..HEAD -- plugins/` is **empty**. Not one
  byte of product code, test code, fixture, `pyproject.toml` or lockfile
  moves. This is the criterion the whole unit is built to satisfy.

### DR — the decision rows

- **`DR1`** — `03-decisions.md`'s Settled table contains `S-34` and
  `S-35` positioned between `S-33` and `S-36`, and `S-39`–`S-44` after
  `S-38`. No existing row's number changes; `S-36`/`S-37`/`S-38` are
  byte-identical apart from nothing.
- **`DR2`** — `S-34` and `S-35` say what `U-seam` §7.5 reserved them to
  say, and no more: `S-34` covers the seam's existence, its surface/call-site/
  operation counts and the never-raises rule; `S-35` covers precedence and
  fail-closed. A row asserting something §7.5 did not reserve is a defect.
- **`DR3`** — every row's Rationale cell cites at least one artifact a
  reader can open. For `S-39`–`S-44` that artifact is
  `~/.claude/plans/indexed-kindling-lightning.md`, and **every quotation
  attributed to it must match that file byte for byte** — the gate opens
  the file and diffs. `S-39`'s provenance note must also survive: the
  record is durable but out-of-repo, this row is the first in-repo one,
  and the user's own wording outranks both. A quotation that does not
  appear in the plan file is a BLOCKER.
- **`DR4`** — `S-41` quotes the plan's F3 ruling verbatim and states
  the consequence that follows from it: the analyst is first in `S-40`'s
  order **because the first flip is the security fix**, not because it is
  the easiest surface. A version of `S-41` that records only `FW-87`'s
  error leg and drops the containment hole is incomplete.
- **`DR5`** — `S-43` and `S-44` are checkable against shipped code, not
  only against the plan: `S-43` against `pyproject.toml`'s extra and
  `registry.py::_SDK_UNAVAILABLE_MESSAGE`, `S-44` against
  `SdkOutcome.tool_events`/`.denials` and `events.py`. `S-44` must state
  the *filesystem-diff-stays-authority* constraint on `U-corrob`; a row
  that records the capture without the constraint invites the next unit
  to treat a model's self-report as provenance, which is the failure
  `FW-84` already cost this project once.

### RB — the runbook

- **`RB1`** — `docs/specs/self-learn/17-invocation-runbook.md` exists and
  is byte-identical to Appendix A apart from its date line.
- **`RB2`** — every operator-typed string in it is verified: the four
  environment-variable spellings, the five `config.yaml` key spellings,
  the doctor command, the selftest command, and the two install commands
  each appear in §5's verification table with a code or measured
  falsifier. **An unverified command in a runbook is a BLOCKER.**
- **`RB3`** — the runbook carries all four obligations assigned to it by
  existing forward rows: `FW-89` (run the doctor after any `provider` or
  `backend` change), `FW-88` (`SELF_LEARN_ENFORCE_SCOPE=0` is
  sdk-semantics-only and wider there), `FW-94` (`--selftest` spawns
  `claude --version` on `[sdk]`-extra installs), and `U-sdk` §7.3 `R-6`'s
  burn-in obligation. Each is traceable to a named section of Appendix A.
  It must additionally carry the plan's own two: the per-surface gates
  **as written** (§5.1–§5.5, quoted, with any unbuilt instrument named
  rather than softened) and `U-cleanup`'s five preconditions (§5.6). A
  runbook that states a gate without stating that its instrument does not
  exist is worse than one that omits the gate, because it reads as
  measurable.
- **`RB4`** — the runbook states the systemd-inheritance constraint
  (`B-8`) **before** it gives any environment-variable flip instruction
  for the miner or worker surfaces, and states plainly that for those two
  surfaces `config.yaml` is the only flip that reaches every launch path.
  An operator who reads §4 top to bottom cannot flip the miner wrongly.

### HY — hygiene

- **`HY1`** — public-repo hygiene holds across every file this unit
  writes: no absolute path under a real home directory, no credential or
  credential-shaped literal, no real ledger record id (placeholders are
  `<ledger-home>`, `<surface>`, `lrn-00000000`). The grep is in §5.
  **One deliberate tilde path is exempt and must survive:** `S-39`–`S-44`
  cite `~/.claude/plans/indexed-kindling-lightning.md` as the ruling
  record. It is a tilde path, not an absolute one; it names a filename
  and no content beyond what the rows quote; and the corpus already
  carries `~/.self-learn` and `~/.claude/CLAUDE.md` by the same
  convention. Removing it would leave the rows uncitable, which is worse.
- **`HY2`** — no file under `docs/specs/self-learn/reviews/` is read,
  cited, or quoted by this spec, by the runbook, or by any decision row.
  *Naming the directory to declare the fence is not a citation.* The
  check is a **property, not a count**: every occurrence of the string in
  this document is either a fence declaration or a disclosure of what
  could not be checked because of the fence, and **none names a file
  inside the directory** — no `reviews/<something>.md` path appears
  anywhere. The one obligation that would have required reading it is
  disclosed instead (§8 `X-2`, `S-41`, `DR4`). *(r4: this criterion
  briefly hardcoded an occurrence count — "eight", corrected by the gate
  to six, and stale again at seven within the same round's own edits. A
  criterion that counts strings in the document that contains it goes
  wrong on every subsequent edit, which is precisely the defect class
  this unit exists to sweep. The property is what was ever meant; the
  number was never load-bearing.)*

---

## 5. Verification table — claim → how the gate checks it

There is **no mutation plan**: nothing executable changes, so nothing can
be reddened. This table replaces it. Every row is a claim this document
makes, and the exact read or command that falsifies it. The gate runs
them from the repo root at the build's HEAD.

| # | Claim | How to check | Falsified if |
|---|---|---|---|
| `V1` | `03-decisions.md` had no `S-34`/`S-35` at `89f8ef7` | `git show 89f8ef7:docs/specs/self-learn/03-decisions.md \| grep -c 'S-34\|S-35'` | non-zero |
| `V2` | `U-seam` reserved those rows | read `drafts/u-seam-invocation-seam-spec.md` §7.5 + its files-may-touch row for `03-decisions.md` | either absent |
| `V3` | `I-2`: `--allowedTools` carries no write scope | read `worker.py::ALLOWED_TOOLS` (`"Read,Grep,Glob"`) and the `#:` comment above it | the constant contains `Write` or `Edit` |
| `V4` | `I-2`: the write grant names the stage, not `proposals/` | read `worker.py::write_settings_file` → `stage_permission_rules` → `stage_dir()` | the default (stage-enabled) branch emits a `proposals/` glob |
| `V5` | `I-10`: the worker timeout is 30 min, not 15 | `grep -n '^INVOKE_TIMEOUT_SECS' plugins/self-learn/cli/src/self_learn/worker.py` → `30 * 60` | value is `15 * 60` |
| `V6` | `I-11`: the shipped worker argv | read `worker.py::build_argv` — `--allowedTools ALLOWED_TOOLS`, `--disallowedTools DISALLOWED_TOOLS`, `--settings`, `--strict-mcp-config`; no `Write(` anywhere | a `Write(` glob appears in argv |
| `V7` | `I-20`/`I-22`: the miner reader gets **no** read tools | read `miner.py::READER_DISALLOWED_TOOLS` (`worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"`) and `build_reader_argv` (no `--allowedTools` element) | `--allowedTools` appears, or the deny list omits `Read` |
| `V8` | `I-20`/`I-22`: doc 12 already contradicts itself | read `12-transcript-miner.md` §12.2 *"reader containment (Read/Grep/Glob-less) is untouched"* against §2 Phase 2 | §12.2's clause absent |
| `V9` | `I-26`: the miner's scheduler is systemd, not cron-claude | `ls systemd/` + read `self-learn-miner.service`'s `ExecStart` | no systemd unit exists |
| `V10` | `S-35`: the five rungs and their order | read `invocation/registry.py::backend_for` | the order differs |
| `V11` | `S-35`: three selectors, four surfaces | read `invocation/contract.py::SURFACES` and `SELECTOR_FOR_SURFACE` | four distinct selectors, or different names |
| `V12` | `S-35`: the config keys | read `config.py::invocation_backend` — `for key in (f"backend_{surface}", "backend")` under section `"invocation"` | different key construction |
| `V13` | Runbook: `SELF_LEARN_BACKEND_ANALYST=sdk` reaches the analyst surface | `SELF_LEARN_BACKEND_ANALYST=sdk self-learn doctor invocation \| head -1` | the `switches` row does not read `analyst: backend=sdk (env:SELF_LEARN_BACKEND_ANALYST)` |
| `V14` | Runbook: `SELF_LEARN_BACKEND_MINER` — not `…_MINER_READER` — is the miner's selector | run both; compare `switches` rows | `…_MINER_READER` has any effect, or `…_MINER` has none |
| `V15` | Runbook: `SELF_LEARN_BACKEND_WORKER` moves **both** worker surfaces | `SELF_LEARN_BACKEND_WORKER=sdk self-learn doctor invocation \| head -1` | `worker-repair` stays `cli` |
| `V16` | Runbook: an unknown value folds to `cli` **silently in the doctor** | `SELF_LEARN_BACKEND=SDK self-learn doctor invocation 2>&1 >/dev/null` → empty; stdout's `switches` row → `backend=cli (env:SELF_LEARN_BACKEND)` | a warning is printed, or the row reads `sdk` |
| `V17` | Runbook: an **empty** per-surface config key shadows the general key | scratch home with `invocation:\n  backend_analyst: ""\n  backend: sdk` → `switches` shows `analyst: backend=cli (default)` and the other three `sdk` | analyst reads `sdk` |
| `V18` | Runbook: `worker-repair` **is** independently settable by config | scratch home with `invocation:\n  backend_worker-repair: sdk` | `worker` also flips, or `worker-repair` does not |
| `V19` | Runbook: `install.sh` does not install the `[sdk]` extra | `grep -n 'uv sync' install.sh` → `uv sync --project '$P/cli' -q` | `--extra sdk` present |
| `V20` | Runbook: the extra's name and pin | read `plugins/self-learn/cli/pyproject.toml` `[project.optional-dependencies]` → `sdk = ["claude-agent-sdk>=0.2.116,<0.3"]`, `[project] name = "self-learn-cli"` | either differs from the `pip install 'self-learn-cli[sdk]'` the runbook prints |
| `V21` | Runbook: the `BackendUnavailable` bytes | read `invocation/registry.py::_SDK_UNAVAILABLE_MESSAGE` | the runbook's quotation differs |
| `V22` | `FW-95`: `Outcome` has no cost field; `SdkOutcome` does | read `invocation/contract.py::Outcome` and `invocation_sdk/backend.py::SdkOutcome` | `Outcome` carries `cost_usd` or `turns` |
| `V23` | `FW-95`: isolation means no settings are loaded | read `invocation_sdk/backend.py::options_kwargs` → `setting_sources: []`, `settings: None` | either differs |
| `V24` | Runbook: the doctor's row set and verdict vocabulary | read `provider.py::DOCTOR_ROWS` and `VERDICTS`; compare to §3 of Appendix A | any row name or verdict differs |
| `V25` | Runbook: the `orphans` row is a hard SKIP today | read `provider.py::_orphan_report_row` | it can return a non-SKIP verdict without a new export |
| `V26` | Runbook: orphan evidence is log lines, not the doctor | read `invocation_sdk/lifecycle.py::sweep_orphans`'s **six** `log(...)` templates (killed-stale, no-live-process, could-not-corroborate, cmdline-mismatch, not-stale, malformed-sidecar) | fewer or more than six, or any template differing from `17` §5.3's list |
| `V27` | `FW-94`: the selftest spawn is gated on the extra | read `selfcheck.py::run_selftest` → `_check_invocation` → `provider.preflight` → `_sdk_row` → `_host_cli_version` | the spawn is unconditional, or absent |
| `V28` | Runbook: the selftest reports **8** checks | read `selfcheck.py::run_selftest`'s `results` list | length ≠ 8 |
| `V29` | `B-8`: systemd units pin only `SELF_LEARN_HOME` | read `systemd/self-learn-miner.service` and `self-learn-ui.service` | either sets a backend or provider variable |
| `V30` | `HY1`: hygiene | `grep -nEi 'bearer [A-Za-z0-9_-]{8,}\|api[_-]?key\|secret\|password\|PRIVATE KEY\|ghp_\|/home/[a-z]' docs/specs/self-learn/17-invocation-runbook.md docs/specs/self-learn/drafts/u-docs-truth-sweep-spec.md` | any hit that is not a documented placeholder |
| `V31` | `IV4`: completeness | re-run the two greps below, then subtract `Inv-1`'s rows **and** `IV4`'s enumerated (b)-set — 09, 10, `records-index.md`, `forward/packaging.md`, and `Rule A` dated records, **which in doc 14 means both `## 6a. Dated dispositions` and `## 6b. Dated additions log`** | a hit remains after both subtractions (gate-measured baseline: **0 of 69**, with both planted sites caught) |
| `V32` | `SB5`: no code moved | `git diff --stat 89f8ef7..HEAD -- plugins/` | non-empty |
| `V33` | Runbook: the two timeout variables are spelled **differently** | read `worker.py::invoke_timeout_secs` (`SELF_LEARN_INVOKE_TIMEOUT_SECS`) and `analyst.py::_timeout` (`SELF_LEARN_ANALYST_TIMEOUT`, no `_SECS`) | either spelling in `17` §5.1 / `Sub-5` differs from the source |
| `V34` | Runbook: the provider env vars | read `provider.py` — `SELF_LEARN_PROVIDER`, `SELF_LEARN_BEDROCK_REGION`, `SELF_LEARN_BEDROCK_PROFILE`, `SELF_LEARN_SDK_CLI_PATH` | any spelling in `17` §4.4 differs |
| `V35` | Runbook: the doctor's exit code | read `cli.py::_cmd_doctor` — 1 iff any row's verdict is `FAIL` | it exits non-zero on WARN, or always 0 |

**The two completeness greps (`V31`), stated once so the gate runs the
same ones this spec ran:**

```
grep -rn 'claude -p\|subprocess\|Popen\|build_argv\|allowedTools\|disallowedTools\|--settings\|strict-mcp' \
  docs/specs/self-learn/*.md docs/specs/self-learn/forward/*.md README.md
grep -rni 'invocation seam\|SdkBackend\|CliBackend\|backend=sdk\|invocation backend\|claude_agent_sdk\|Agent SDK' \
  docs/specs/self-learn/*.md docs/specs/self-learn/forward/*.md README.md
```

**Positive control on `V31` itself** (`P-1`): before trusting an empty
diff, the gate must confirm the greps *can* hit — run the first grep with
`docs/specs/self-learn/03-decisions.md` alone and confirm it returns the
`S-5` and `S-22` lines. A grep that returns nothing because it is aimed
at the wrong path reads identically to a grep that returns nothing
because the sweep is complete, and that failure mode is the one this
project has already been bitten by.

---

## 6. Builder decisions, made here rather than left open

- **`D-1` — the runbook is `17-invocation-runbook.md`.** Four options
  were priced. **(a) A new numbered doc at 16** — rejected:
  `drafts/16-ecology-spec.md` titles itself `# 16 — Worker-ecology
  channels & the portfolio auditor` in its own H1 and is called the
  *"doc-16 candidate"* in the README's revision log; taking 16 would
  either collide or require renumbering another unit's draft, which is
  not this unit's to do. **(b) Append to `15`** — rejected on audience:
  15 is *"how the agent rounds actually run"*, addressed to
  orchestrators, builders and blind reviewers, and an operator procedure
  buried inside it would be found by nobody who needs it. **(c) An
  unnumbered doc** (precedent: `records-index.md`) — rejected because
  numbered docs are the corpus's reading order, and a procedure the
  flips depend on belongs in the reading order; `15` is itself a
  numbered runbook, so the precedent points the other way. **(d) 17,
  leaving 16 reserved** — **adopted.** The gap is deliberate and this
  decision records why, so a later reader does not read it as an
  off-by-one. **RATIFIED by the orchestrator, 2026-08-19** — the
  16-is-taken reasoning was accepted and the gap is to be recorded as
  deliberate, which §3.4 and the file's own header do. **Reversal path,
  retained because the call stays cheap to undo:** if the ecology draft
  is ever retired, renaming this file to `16-` touches exactly two lines
  (the H1 and the README reading-order row) plus any cross-references,
  which at this build are the six added by this unit.
- **`D-2` — corrections are dated in place, never silently applied.**
  Every substitution carries a marker (`SB2`). The cost is visual noise
  in six documents; the benefit is that the next reader can tell a
  correction from an original claim, which is precisely the property the
  corpus lost when Waves 0–1 shipped unrecorded.
- **`D-3` — the eleven `NOW FALSE` clauses are replaced, not
  annotated.** An appended "actually this is wrong now" leaves the false
  bytes as the first thing a skimmer reads. `Rule A` still protects every
  dated record, so nothing historical is lost: `08`'s 2026-07-15 entry
  keeps the literal that `Sub-6` removes from the live pin.
- **`D-4` — `S-39` states the ruling without quoting it.** The
  alternative — writing a plausible sentence in the user's voice — was
  rejected outright. This corpus has a convention for exactly this case
  (`S-23`'s provenance note) and it is followed: say that the decision
  was the user's, say what was decided, say that no verbatim record
  exists, and say that the user's own wording outranks the row.
- **`D-5` — the burn-in gates go in the runbook, not the register.**
  `S-40` names the order and the gating principle; the gate *criteria*
  are operational detail that will be tuned by the first burn-in's own
  evidence, and a register row is the wrong place for a number that is
  expected to move. The runbook says where measured results are
  recorded (`17` §5.7) so the tuning has a paper trail.
- **`D-6` — `I-26` is not fixed here.** It is measurably false and it is
  one clause. It is also a *scheduling* claim, and this unit's fence is
  the invocation layer. Fixing it would be the cheap kind of scope creep
  that makes a scope fence meaningless; `FW-96` costs one row and keeps
  the fence honest.
- **`D-7` — the README revision-log backlog is not back-filled.**
  `Sub-18` adds this unit's entry only. Reconstructing nine round-closes
  from git history would produce a narrative, not a record; `FW-97` puts
  the choice in front of whoever still remembers them.

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Sites judged and deliberately left

Named, not implied — so a later reader can tell "looked at and kept"
from "never looked at" (the same reasoning `U-seam` §7.1 `O-a` records).

- **(a) `04-roadmap.md:206`** (`I-6`) — *"restricted `--allowedTools`"*
  inside M2's scope description. Left: the roadmap records what a
  milestone's scope *was*, and M2 did ship with a restricted
  `--allowedTools`. Correcting a milestone's historical scope statement
  would be editing a record by another name.
- **(b) `07-review-ui.md:110–124`** (`I-7`) — the `claude -p`-default
  clause. Left: it sits inside a dated amendment chain that the *same
  bullet* reverses eight lines later (*"the user's binding V3 **restored
  the Agent SDK as the default engine**"*). It is a correct record of a
  reversal, and it concerns the **UI pane engine** — a different seam
  from this unit's, in a package `U-seam` §7.2 explicitly refused to
  touch.
- **(c) `08-build-plan.md:217`** (`I-9`) — T8's task description. Left:
  the M1 task DAG records what each task built.
- **(d) `12-transcript-miner.md:513`** (`I-23`) — *"the one Phase-2
  `claude -p`"* inside a token-cost argument. Left: the argument is about
  paying for digest reads once, and it holds identically on both
  backends; the transport noun is incidental to it.
- **(e) Source and unit-file comments — three sites, outside the brief's
  inventory scope, all describing `claude -p` as *the* transport:**
  `analyst.py`'s module docstring (*"spawns a ONE-SHOT `claude -p`
  analyst"* plus a transcribed flag block), `worker.py::build_argv`'s
  docstring, and `systemd/self-learn-miner.service`'s comment (*"The run
  spawns a contained `claude -p` reader"*). Left because this unit's
  fence is documentation under `docs/` plus the root README, and because
  `analyst.py`'s docstring is inside the exact function `U-sdka` is
  about to rewrite — correcting it here would collide with a parallel
  unit. **Owner:** `U-sdka` for the analyst docstring; the systemd
  comment and `build_argv`'s docstring are unowned and small enough to
  ride any later unit that opens those files. Recorded rather than
  smuggled.
- **(f) `09-surface-spec.md` / `10-surface-build-plan.md` in their
  entirety.** Every SDK and subprocess mention in them concerns the UI's
  pane engine, which is a separate seam with a separate default and a
  separate spec. `U-seam` §7.2 refused to touch that package's code; this
  unit refuses to touch its documents, for the same reason — the two
  ship independently and a shared narrative would imply a shared
  contract that does not exist.

### 7.2 Residuals this unit accepts, with owners

- **`R-1` — the corpus will drift again, and this unit builds no guard
  against it.** Nothing here prevents the next unit from changing a
  containment mechanism without touching doc 01, and the greps in §5
  are run by a human-directed gate, not by CI. A lint that fails when a
  containment constant changes without a corresponding doc edit is
  conceivable and is **not built**: it would need to know which prose
  sentence describes which constant, which is the hard half. Accepted,
  not deferred — the honest instrument is
  `forward/platform-drift.md` §4's standing rule plus round-close
  discipline, and `S-42` is this unit's attempt to give that rule teeth
  for reserved register rows specifically.
- **`R-2` — the burn-in gates are transcribed from an out-of-repo plan
  and have never been executed.** `17` §5 is their first in-repo form and
  quotes the plan verbatim per surface, but no surface has been flipped,
  so no gate has been tried — and a gate that has never run may prove
  unmeasurable. Two already are: the cost denominator (`FW-95`, now with
  a ruled direction) and the plan's *"scripted pgrep via doctor"*, whose
  hook is unexported (`V25`). Accepted: the alternative is not writing
  them down, which is strictly worse, and the two gaps are named in place
  rather than softened. **Owner:** the first burn-in, which should amend
  §5 in place with what it actually measured.
- **`R-3` — the doctor cannot tell an operator that their backend value
  was rejected.** Measured (`V16`): `provider.py::resolve_backend_name`
  is a second, deliberately **silent** transcription of the precedence
  chain (`Rs-b`: *"never prints, for any input"*, because `registry.py`
  warns at invocation time and a second copy would double-print). So a
  typo'd `SELF_LEARN_BACKEND=SDK` shows in the doctor as `backend=cli
  (env:SELF_LEARN_BACKEND)` with no diagnostic; the operator learns at
  the next real invocation. The runbook teaches the tell — **a
  `switches` row that names an env or config source but reports `cli` is
  a rejected value** — because that is all a docs unit can do. **Owner:**
  unowned; a future unit could give the doctor a validation-only warning
  without breaking `Rs-b`'s no-double-print rule, since the doctor is not
  an invocation.

### 7.3 Handed to `03-decisions.md` and `14-forward-work-map.md`

Rows `S-34`, `S-35`, `S-39`, `S-40`, `S-41`, `S-42` (§3.3) and `FW-95`,
`FW-96`, `FW-97` (§3.5), all landing in the same commit as the build —
the disposition rule `S-24`…`S-33` established, applied to a unit whose
entire output *is* documentation.

---

## 8. Conflicts between the brief and current master

Flagged, not silently resolved.

**`X-1` — RESOLVED. `U-docs` is the plan's own name; the repo simply
does not carry it yet.** `14-forward-work-map.md` `FW-89` says *"Owner:
the docs unit's runbook"* and `U-bedrock`'s spec says *"the docs unit"*
in three places; **no occurrence of the string `U-docs` exists anywhere
in the repository** (measured, `E-4`). It does exist in the approved
plan, which names this unit in its Wave-2 line: *"**U-docs** (docs-truth
sweep of every `claude -p` mention + 03-decisions rows incl. dated F3/F4
findings + runbook flip/rollback one-liners)"*. The name is therefore
ratified, not invented here, and this spec uses it in every marker it
writes.

**`X-2` — RESOLVED, and one half of it was a label with no referent.**
The brief named *"the F3 wait-for-the-flip ruling"* and *"the F4-class
findings the campaign recorded."*

**F3 is real and the r1 inference was correct.** The plan records it
under that exact label — the analyst's tools falling through to the
host's `bypassPermissions` default — with the user's wait-for-the-flip
ruling attached. `S-41` now quotes it verbatim instead of inferring it,
and carries the consequence r1 could not see: the analyst is first in the
flip order *because* the first flip is the security fix.

**F4 has no referent.** The string appears in the plan exactly once, in
the line that scopes this very unit — *"03-decisions rows incl. dated
F3/F4 findings"* — and no finding named F4 is defined anywhere in it.
The label was a scoping shorthand that over-promised, and the honest
disposition is to **drop it** rather than manufacture a row to fill the
slot. What the slot should have carried, and now does, are the plan's
other two dated planning decisions: `S-43` (the optional extra) and
`S-44` (capture-now-consume-later attribution). Both are quoted from the
plan and independently checkable against shipped code (`DR5`).

The r1 measurement stands and is why the confusion was possible:
`F3`/`F4` are **per-round finding labels, not stable identifiers**
(`E-5`) — the strings appear across `01`, `02`, `09`, `10` and four
drafts, meaning something different each time. Nothing in this fold
required reading `reviews/`, and nothing did.

**`X-3` — RESOLVED: the burn-in gates now have a source, and Appendix A
§5 is a transcription of it.** Measured at r1 (`E-3`): the criteria
appear in no file inside the repository; `U-sdk` §7.3 `R-6` says only
*"no burn-in evidence exists for any surface … Owner: the post-merge
burn-in unit."* They live in the approved plan's §"Rollout / burn-in /
rollback", which Appendix A §5 now quotes verbatim per surface, with the
plan cited as the authority. **The plan wins on any divergence** and the
appendix is the defect. Two places where the transcription is *more*
than the plan, both flagged in the runbook rather than smuggled: the
plan's *"0 orphans at 09:00 (scripted pgrep via doctor)"* names an
instrument that is not exported yet (the doctor's `orphans` row is a hard
SKIP, `V25`), and the cost gate's `cli` denominator is not
product-measurable (`FW-95`).

**`X-6` — the plan's stated SDK pin and the shipped one differ, and the
shipped one appears to be right.** The plan's risk register prescribes
*"range-pin `>=0.2.121,<0.3`"* for version skew; `pyproject.toml` ships
`sdk = ["claude-agent-sdk>=0.2.116,<0.3"]`. The plan's own parenthetical
in the same sentence explains the discrepancy — *"(UI already pins
`>=0.2.116,<0.3` and depends on the CLI package by path — an exact pin
would fight the resolver …)"* — so the shipped floor is consistent with
the plan's reasoning even though it is not the plan's number. **This
unit does not resolve it and does not touch the pin** (`SB5`: no code
moves). `Sub-14` quotes the *shipped* pin, verified from
`pyproject.toml`, never the plan's. Flagged for the orchestrator because
a risk mitigation that shipped at a different value than its register
says is worth one deliberate glance.

**`X-4` — "the cli baseline" in the cross-cutting cost gate presumes an
instrument that does not exist.** See `FW-95`. Recorded here because it
is a conflict between the brief's gate and shipped code, not a design
choice this unit made.

**`X-5` — the brief says "no mutation rows (docs unit)"; house style
expects a mutation plan.** Resolved by §5: a verification table the gate
executes, with a declared positive control (`P-1`) on the one check
whose empty result would otherwise be indistinguishable from a
mis-aimed command.

---

## 9. What was executed, and against what oracle

Measurements taken while writing this spec, at `89f8ef7`, in a clean
worktree. A gate that cannot reproduce these should stop.

| # | Measurement | Command / read | Result |
|---|---|---|---|
| `E-1` | `S-34`/`S-35` are absent from the register | `grep -rn 'S-34\|S-35' docs/specs/self-learn/ --include='*.md'` (excluding `reviews/`) | **3 hits, all in `drafts/u-seam-invocation-seam-spec.md`** (lines 62, 1835, 1837). Zero in `03-decisions.md`; the Settled table runs `S-33` → `S-36`. |
| `E-2` | The live doctor on this host, all defaults | `self-learn doctor invocation` | **17 rows + a 20-field handoff block**, rc 0. `switches`: all four surfaces `backend=cli (default)`. `provider=anthropic (default)`. **`WARN sdk — sdk=0.2.134 bundled-cli=2.1.226 host-cli=2.1.235 — versions differ`** — i.e. the `[sdk]` extra IS installed here, so `FW-94`'s per-run `claude --version` spawn is live on this machine. `rollout`, `region`, `credentials`, `models` all SKIP under `provider=anthropic`; `orphans` SKIP. No `consistency` row is emitted when there are no consistency failures. |
| `E-3` | Burn-in gate criteria are not in the repo | search of the numbered docs, `drafts/`, `forward/`, `research/`, `feedback/`, both READMEs and the git log | **NOT FOUND.** Only `U-sdk` §7.3 `R-6`'s deferral to *"the post-merge burn-in unit."* |
| `E-4` | The unit name `U-docs` is not in the repo | repo-wide grep | **0 hits.** The rows that reference it say *"the docs unit"*. |
| `E-5` | `F3`/`F4` are per-round labels, not identifiers | grep for `\bF3\b` and `\bF4\b` across the readable corpus | **~20 hits each**, each a different finding in a different round (`01` §…, `02` §…, `09`, `10`, `u-schema`, `u-fake`). No Wave-0/1 occurrence outside `reviews/`. |
| `E-6` | No numbered doc mentions the seam | the second grep in §5 over `docs/specs/self-learn/*.md` + `forward/*.md` + root `README.md` | the only hits describing the CLI's invocation layer are `14-forward-work-map.md`'s `FW-86`–`FW-94` and `03-decisions.md`'s `S-36`–`S-38`. `01`, `08`, `11`, `12`, `13`: **zero**. |
| `E-7` | README revision-log currency | `grep -n '^- \*\*2026-08' docs/specs/self-learn/README.md` | **0 hits.** Last entry 2026-07-24; the file's status header still reads *"next phase: packaging"*. |
| `E-8` | `SELF_LEARN_BACKEND_ANALYST=sdk` works | `SELF_LEARN_BACKEND_ANALYST=sdk self-learn doctor invocation \| head -1` | `… analyst: backend=sdk (env:SELF_LEARN_BACKEND_ANALYST)`; the other three unchanged. |
| `E-9` | `SELF_LEARN_BACKEND_MINER=sdk` works; `…_MINER_READER` is a **silent no-op** | both, compared | `MINER` → `miner-reader: backend=sdk (env:SELF_LEARN_BACKEND_MINER)`. `MINER_READER` → **all four surfaces `cli (default)`**, no warning, rc 0. The obvious guess fails silently. |
| `E-10` | `SELF_LEARN_BACKEND_WORKER` moves both worker surfaces | same | `worker:` and `worker-repair:` both `backend=sdk (env:SELF_LEARN_BACKEND_WORKER)`. |
| `E-11` | An unknown value folds to `cli` with **no doctor diagnostic** | `SELF_LEARN_BACKEND=SDK self-learn doctor invocation 2>&1 >/dev/null` | **empty stderr**, rc 0; stdout's `switches` row reads `backend=cli (env:SELF_LEARN_BACKEND)` for all four. The source/value mismatch is the only tell (`R-3`). |
| `E-12` | `config.yaml`'s general key | scratch `SELF_LEARN_HOME` with `invocation:\n  backend: sdk` | all four → `backend=sdk (config:backend)`. |
| `E-13` | An **empty** per-surface key shadows the general key | scratch home with `backend_analyst: ""` + `backend: sdk` | worker/worker-repair/miner-reader → `sdk (config:backend)`; **analyst → `cli (default)`** — and the source reads `default`, not the key that caused it. |
| `E-14` | `worker-repair` **is** independently settable by config | scratch home with `backend_worker-repair: sdk` | `worker-repair: backend=sdk (config:backend_worker-repair)`; `worker` stays `cli (default)`. The env/config asymmetry is real in both directions. |
| `E-15` | Pointing `SELF_LEARN_HOME` at a fresh directory kicks the miner | the `E-12` run's first line | `miner: catch-up run spawned (>24h)` — the 24-hour watchdog fires on a home with no `last-run`. No process survived (`pgrep -af 'mine run'` → none) and nothing was written to the scratch home beyond the `config.yaml` placed there, but the runbook carries the caution (`17` §7). |
| `E-16` | `install.sh` does not install the extra | `grep -n 'uv sync' install.sh` | `run "uv sync --project '$P/cli' -q"` — no `--extra sdk`. |
| `E-17` | The systemd units carry no backend env | read both unit files | each pins `Environment=SELF_LEARN_HOME=%h/.self-learn` and nothing else, with the comment *"the systemd user manager does not inherit the shell's env"*. |
| `E-18` | **`SB1` self-check, r2 form — SUPERSEDED, and it missed a real defect** | `grep -c` per anchor, then `tr '\n' ' '` for the misses | r2 reported "18 of 20 raw, all 20 unwrapped". **The r2 gate falsified it**: `Sub-1`'s anchor resolved 0 raw *and* 0 unwrapped, because the anchor had been transcribed with editorial normalization — the file backticks `` `--route` `` and opens its bold **before** "detached", and r2's quote did neither. A check that reports a clean pass while one of its inputs was never in the file is worth exactly nothing; `E-18b` replaces it. |
| `E-18b` | **`SB1` re-run at r3 — the resolution result stands; its raw-vs-unwrapped split was measuring the wrong strings** | one script over all 22 anchors (20 `Sub-n` + `Sub-11`'s two clauses), failing anything ≠ 1 | **22/22 resolve exactly once** under normalization — reproduced independently by the delta gate. **The same run also reported "19 match raw", and that figure was wrong**: the script tested short *probe fragments* chosen to fit on one line, not the actual §3.2 `before` strings. Re-measured at r4 against the real anchors: **nine** fail an un-normalized `grep` — `Sub-2`, `Sub-7`, `Sub-8`, `Sub-9`, `Sub-11a`, `Sub-11b`, `Sub-12`, `Sub-15`, `Sub-16`. The raw column is therefore **deleted from `§0.6` rather than corrected** (that item states why). **Two anchor defects were caught by this check across two rounds** — `Sub-1` (0 matches, editorial normalization) and `Sub-18` (2 matches, duplicate date) — **and a third was in the check itself**, which is the more useful lesson: a measurement that quietly substitutes an easier input for the real one reports a clean number about nothing. Same failure shape as the two anchors, one level up. |
| `E-18c` | **The normalization recipe is two steps, not one** | `tr '\n' ' '` alone vs `tr '\n' ' ' \| tr -s ' '`, against `Sub-2`'s anchor in `01-architecture.md` | newline substitution alone: **0 matches**; with the whitespace squeeze: **1**. The wrap falls immediately before a two-space bullet indent, so the joined text carries three spaces where the anchor has one. `§0.6` prescribes both steps because of this measurement — a resolver doing only the first halts on a valid anchor. |
| `E-19` | Timeout variable spellings differ between surfaces | read `worker.py::invoke_timeout_secs` and `analyst.py::_timeout` | worker: `SELF_LEARN_INVOKE_TIMEOUT_SECS`; analyst: `SELF_LEARN_ANALYST_TIMEOUT` — **no `_SECS` suffix**. Caught while drafting `17` §5.1, which had guessed the symmetric spelling. |

**Measured at the r2 fold**, once the plan's location was supplied. `E-3`
and `E-4` above are unchanged and were never wrong — they measured the
**repository**, and the plan is not in it.

| # | Measurement | Command / read | Result |
|---|---|---|---|
| `E-20` | The ruling record exists, out-of-repo | read `~/.claude/plans/indexed-kindling-lightning.md` (282 lines, dated 2026-08-09) | §"User rulings (binding, 2026-08-09)" carries four numbered rulings; §"User rulings recorded during planning" carries the F3 ruling and the two adopted designer recommendations; §"Rollout / burn-in / rollback" carries the flip order, the per-surface gates, the cross-cutting pair, the rollback doctrine and `U-cleanup`'s five preconditions. **Every quotation in `S-39`–`S-44` and `17` §5 was taken from this file, not from a summary of it.** |
| `E-21` | **"F4" has no referent** | grep the plan for `F4` | **1 hit**, in the plan's own Wave-2 line scoping this unit: *"03-decisions rows incl. dated F3/F4 findings"*. No finding named F4 is defined anywhere in the file. `F3` by contrast has its own titled ruling. The label was scoping shorthand that over-promised; `X-2` records the disposition. |
| `E-22` | The worker gate's `denials` instrument is real, and sdk-only | read `invocation_sdk/backend.py::SdkOutcome` and `invocation_sdk/events.py` | `SdkOutcome.denials: tuple[dict[str, Any], ...] = ()` and `.tool_events`, populated from the charter callback (`add_denial`) and `ResultMessage.permission_denials` (`add_sdk_permission_denial`), persisted by `write_event_log`. **`Outcome` itself has neither**, so the gate's `denials` half has no `cli` control — which is why the plan pairs it with the filesystem diff (`17` §5.4). |
| `E-23` | Plan-vs-shipped divergence on the SDK pin | plan §"Top risks" vs `pyproject.toml` | plan prescribes `>=0.2.121,<0.3`; shipped is `>=0.2.116,<0.3`. The plan's own parenthetical in the same sentence gives the reason the shipped floor is lower (the UI pins `>=0.2.116,<0.3` and depends on the CLI by path). Flagged as `X-6`; **not touched** — `SB5` forbids it and this unit has no mandate over a dependency pin. |

**Not measured, and therefore not claimed:** that any surface behaves
correctly under `backend=sdk` in a real run. No flip was performed and no
model was invoked by this unit. Every `sdk` observation above is a
**resolution** — what the selector chain answers — not an execution.
`self-learn --selftest` was likewise **not run** (it exercises capture,
compiler, marker and sentinel checks against the live ledger, which this
unit holds read-only); its 8-check count and its `invocation` row wording
are read from `selfcheck.py::run_selftest`, not observed.

---

## 10. Revision history

| Rev | Change |
|---|---|
| r1 | Initial draft, written blind against `89f8ef7`. 41 sites inventoried (§3.1), 20 substitutions specified (§3.2), 6 decision rows (§3.3), 1 new numbered doc (Appendix A), 3 forward rows (§3.5). 5 conflicts flagged (§8), 3 residuals accepted (§7.2). One brief deliverable **not** produced and disclosed as such (`X-2`). |
| r4 | **r3 delta gate: SOUND — 0 BLOCKER / 0 MAJOR / 3 NOTE.** The gate verified all 14 r3 landings by execution: it reproduced the `Sub-18` double-match and confirmed the positional replacement unique-and-final, mechanized the scoped `IV4`/`V31` (**0 of 69 unaccounted** on the real corpus, both planted sites caught), verified the retally row by row including the shipping figures, re-ran all 22 anchors under its own independent `grep -F`, and checked `I-42`'s replacement text against `miner.py` down to the mine-status verb's dispatch line. Closed under the repricing rule — no further spec round; the builder-verifier checks these downstream. Folded: `SB4`'s STILL-TRUE figure 15 → **14** (`I-24` left that set at r3); `HY2`'s `reviews/` occurrence count 8 → **6**; `S-44`'s locator aligned to its real home (§"Units, DAG, schedule", the **"Burn-in → Wave 3"** bullet — a bolded bullet label, not a heading). **The third NOTE found a defect in this spec's own instrument**: `§0.6`/`E-18b`'s "19 match raw" was measured against short probe fragments, not the actual §3.2 anchors — re-measured, **nine** anchors fail an un-normalized grep, not three. Taking the gate's simpler option, the raw-vs-unwrapped split is **deleted** rather than corrected: whether an anchor survives an un-normalized grep is an accident of where the wrap fell, and quoting any such figure invites a builder to raw-grep, get zero on a valid anchor, and halt under §0.3. `§0.6` now states only the normalization requirement — and states it as **two steps**, because `E-18c` measured that newline substitution alone still fails `Sub-2` (the wrap lands before a bullet indent). Also carried in for the builder-verifier: `IV4`'s dated-record leg now **names doc 14's two log sections** (`§6a`, `§6b`), the gate's own first mechanization having missed `§6b` and produced one spurious hit at `14:320`. |
| r3 | **r2 blind gate: NOT SOUND — 1 BLOCKER / 5 MAJOR / 8 NOTE. All 14 folded.** The gate executed the verification table (32/33 PASS), re-measured all four traps live, and byte-verified every plan quotation. **`BLOCKER-1`**: `Sub-1`'s anchor did not exist — transcribed with editorial normalization (backticks stripped from `` `--route` ``, bold marker moved), resolving 0 raw *and* 0 unwrapped while looking like a quotation. Anchor and `I-1`'s quote corrected byte-exact; `§0.5` rewritten to require byte-exactness, `grep -F`, and **exactly-one** resolution; `E-18` re-run as **`E-18b`** over all 22 anchors — **22/22 resolve once**, and the re-run caught a *second* defect the gate had not seen (`Sub-18`'s date anchor matched **twice**; insertion point restated by position). **`MAJOR-1`**: `Appendix A` §5.2 told operators to look for `mine-<runid>.json`, which the miner never writes and would in fact **delete as litter** — traced to a NOW-FALSE clause in the same T-M2 bullet `Sub-11` already edits, missed by `Inv-1`. Added as **`I-42`**, carried in `Sub-11` as a second replacement, and §5.2 rewritten to a log/status signal. **`MAJOR-2`**: §5.6's Tier-3 gloss was wrong in both halves — per `U-fake`'s `Tiers-1`, T2 is the `["cli","sdk"]` contract suite and T3 is the frozen byte-identity armor, and **no tier invokes a real `claude`**. **`MAJOR-3`**: `IV4`/`V31` would have raised ~20 BLOCKERs on deliberate exclusions; scoped to "unaccounted-for hits" with the exclusion set enumerated in the criterion. **`MAJOR-4`**: `S-34` misattributed the `OSError` escape to `write_session`; corrected to `text_session`/the analyst leg, quoting `registry.py`'s own docstring. **`MAJOR-5`**: `I-24` regraded STILL TRUE → STALE — its "beyond Read/Grep/Glob" premise is the same misconception `Sub-9`/`Sub-11` correct — and given **`Sub-21`**. NOTEs: `I-33` regraded NOW FALSE → STALE with `Sub-15` converted B → C; trap 6 widened (the hatch allows **every** non-denied tool at rung 2, before the write check, and cannot open at all on empty-write-set containments); §1.1's "at all" made precise; §4.4's model placeholder replaced by the three real spellings; two citation locators fixed (`S-40` → `D-2`/`Q-2`, `S-44` → the "Adopted designer recommendations" bullet); `V26` five → six log templates; `Sub-19`'s insertion point named relative to the live-symlink paragraph; `I-41` marked a description with `IV1` scoped accordingly. **Tallies restated: 42 sites, 12 / 11 / 14 / 5** — the gate's projected 11/10 was computed before its own siblings folded; arithmetic note added in §3.1 rather than the divergence being carried silently. |
| r2 | **Orchestrator supply + rulings folded, 2026-08-19.** The 2026-08-09 ruling record was located out-of-repo (`~/.claude/plans/indexed-kindling-lightning.md`) and **read directly rather than folded from the summary** — `E-20`–`E-23`. Changes: `X-1`, `X-2` and `X-3` all move to **RESOLVED**; `X-6` added (a plan-vs-shipped SDK pin divergence, flagged not fixed). `S-39` now quotes ruling 2 verbatim and names the other three rulings, replacing r1's "no verbatim record exists". `S-41`'s label mapping is **confirmed, not inferred**, and the row gains the substance r1 could not see — F3 is a *containment hole*, so the analyst is first because the first flip is the security fix. **F4 is dropped**: `E-21` measured it as a one-hit scoping shorthand in the plan's own line about this unit, with no finding behind it; the slot is filled instead by two new rows quoted from the plan and checkable against code — `S-43` (optional extra) and `S-44` (capture-now-consume-later, with the filesystem-diff-stays-authority constraint on `U-corrob`). Register total 6 → **8 rows**; `DR5` added, criteria 19 → 20. `17` §5 restated as a **verbatim transcription** of the plan's gates with the two instrument gaps named in place, plus a new §5.6 carrying `U-cleanup`'s five preconditions. `FW-95` gains its ruled resolution direction (the denominator is the operator's billing surface, not the product). `D-1`'s doc-17 choice ratified. |

---

---

# Appendix A — `docs/specs/self-learn/17-invocation-runbook.md`, in full

*The builder creates this file with exactly the content below.*

---

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
   any verb when the last run is stale, and a brand-new home has no last
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
