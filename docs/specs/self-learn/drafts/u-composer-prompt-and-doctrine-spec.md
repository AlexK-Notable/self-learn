# Spec — U-composer: the shared prompt composer, the doctrine rewrite, and the mandatory decision trace

*Authored 2026-08-06 for the r2 routing campaign
(`docs/specs/self-learn/forward/r2-routing-campaign.md` §2, row
`U-composer`; `14-forward-work-map.md` FW-43). This is the MILESTONE unit:
per the campaign's own wave plan (§2 "Wave plan", last paragraph),
**nothing routes differently until this lands.** Checkpoint A (§4) runs
immediately after it.*

*Files this unit may touch:
`plugins/self-learn/cli/src/self_learn/worker.py`,
`plugins/self-learn/cli/src/self_learn/analyst.py`,
`plugins/self-learn/skills/self-learn/references/routing-doctrine.md`,
`plugins/self-learn/cli/src/self_learn/ledger_ops.py` (**the S-26 flip
only** — one constant and one guard, §3.9), and the CLI test suite.
Anything else is out of scope and is reported, not edited (campaign §3
builder prompt).*

---

## 0. Reading order and precedence

1. **Acceptance criteria (§4) are the contract.** Where this document's
   prose and §4 disagree, §4 wins (campaign §3 builder prompt).
2. **Shipped code is the referee for what exists today.** Every `file:line`
   below was read in this worktree on 2026-08-06. Where a cited design
   document (`misc/routing-procedure-r2.md`, hereafter **r2**) disagrees
   with shipped code, the code wins and this spec says so explicitly —
   §1.3 lists three such disagreements, one of which would wedge the
   pipeline if transcribed from r2 unaltered.
3. **Normative authority** stays with `03-decisions.md` (S-18, S-21,
   S-22, S-23, S-24, S-25, **S-26**, O-10). The campaign playbook is
   practice; r2 is a design reference, not a pin.
4. **One enumeration per fact.** Where another document already owns a
   list (U-schema's Schema-1 field table; U-pathed's §2 register), this
   spec points at it and does not restate it. A second copy of a list is
   how ~208 citations went stale here.

---

## 1. The defect

### 1.1 The analyst is asked to choose without being given anything to choose from

The measured monoculture (campaign §4 Checkpoint C baseline, re-counted
2026-07-27): user scope 7 `claude-md` + 1 `hook`; project 5 + 1; skill 14
`reference` (all one skill) + 3 `skill-md` + 1 `hook`. The audit's finding
was not model bias — at user scope there was exactly one legal
destination, so the rationale prose was theatre.

Waves 1–2 fixed the plumbing under that finding: the excerpt marker
(`U-marker`, `c7b1f14`), the analyst's field-dropping rebuild
(`U-analyst`, `9c95e9e`), the decision-trace schema and its validator
(`U-schema`, `176eee6`), pathed emission (`U-pathed`, `63f5962`),
reachability (`U-reach`, `17aa06c`). **None of it changes what the analyst
is asked.** Today the analyst is asked exactly this:

> `worker.py:600-609` — *"Follow the routing doctrine exactly — including
> §5 …, §8 …, §9 … and §10 …"*
>
> `analyst.py:86-87` — *"Choose the routing destination for the lesson
> record below, following the routing doctrine in your system prompt
> (narrowest-surface bias)."*

and the doctrine it is pointed at still teaches the pre-r2 model: a
routing map keyed on `type`/`kind`/`scope`
(`routing-doctrine.md:25-39`), one tiebreak ("prefer the narrowest
surface that still fires", `:84-120`), and a cost claim resting on
chezmoi (`:124-127`), which was retired 2026-07-24. There is no gate
sequence, no evidence obligation, and no instruction to emit the trace
`U-schema` shipped a validator for. So the trace fields are *validatable*
and *never produced*: FW-62 measured that **none of the 20 live pending
proposals carries a `gates:` trace.**

### 1.2 The prompt withholds three of r2's five ingredients on one path and four on the other

r2 §0's architectural move — *"every input a gate needs that CAN be
computed deterministically is computed by the CLI and placed IN the
prompt"* — is unbuilt. `worker._compose_prompt` (`worker.py:636-666`)
supplies three things: the record text, the bucket/record paths, and the
candidate-target canon excerpt (`worker.py:546-588`). It does not supply
the skill roster (T3), the cluster candidates (T-N), or the absolute-path
roster. `analyst._PROMPT_TEMPLATE` (`analyst.py:85-102`) supplies only the
record text — not even the canon excerpt — so the two execution paths ask
different questions of the same doctrine, which is the open question the
campaign's falsifier (`U-pairs`) exists to answer and cannot answer while
the inputs differ.

Consequences that are not hypothetical:

- **T3 has no roster, so its honesty rule cannot be satisfied.** U-schema
  ships X3 (`ledger_ops.py:1046-1068`): `t3.roster_sha` must be
  `sha256:<12hex>` or the literal `"unavailable"`, and `"unavailable"`
  forces `t3.answer: no` plus flag `evidence-gap`. With no composer,
  every honest proposal must claim `unavailable` — i.e. the gate that was
  supposed to answer "does a skill already own this?" is structurally
  degraded on every run.
- **T-N has no candidate list**, so the cluster judgment is a scan the
  model claims to have done — the exact class of unverifiable assertion
  r2 §0 inverted the dataflow to remove.

### 1.3 Three places where transcribing r2 would ship a defect

Each was **executed**, not reasoned about. The probes were scratch scripts
run against copies under a redirected `SELF_LEARN_HOME`; they are
deliberately not committed — one of them reads a full copy of the ledger,
which is severed from this public repo. What is durable is §9's table:
each measurement with its oracle and its preconditions, which is what an
equivalence claim actually needs (campaign §5).

1. **r2 §2's suggested T2 evidence is refused by the shipped validator.**
   r2 tells the analyst a `t2.answer: no` may be evidenced by the phrase
   *"record names no paths"*. `_check_evidence`
   (`ledger_ops.py:753-785`) containment-checks every RECORD-sourced
   quote. Measured against the shipped validator with a real record:

   | `t2.evidence` | result |
   |---|---|
   | `"record names no paths"` (r2's phrase) | **REFUSED** — *"is not contained in the record it claims to quote"* |
   | `"About to spawn a subagent in a multi-agent workflow."` (a real quote) | ACCEPTED |
   | `"subagen"` (a true 7-char quote) | REFUSED — under the `_QUOTE_MIN_CHARS` (8) floor |
   | r2's phrase again, with `record_text=None` | ACCEPTED — **positive control: the refusal is containment, not something else** |

   A doctrine that repeats r2's phrasing would make the worker emit
   proposals that `proposal_info` (`ledger_ops.py:1809-1820`) rejects on
   the eligibility hot path, so every such record would be re-analyzed on
   every run, forever, with no visible error. **The doctrine must instruct
   verbatim quotes on `no` answers too.**

2. **PATHED is not available at skill scope**, so S-23's "at every scope"
   cannot be transcribed as a rule. `_resolve_rules_target` refuses any
   scope outside `{user, project}` (`verbs.py:811-816`, the P-A13
   deferral). At skill scope the cheap tier is DEMAND
   (`references/LEARNINGS.md`), which is exactly where the 14 stranded
   records live and which `U-pointer` makes reachable. §3.8's tier table
   states availability per scope instead of repeating the slogan.

3. **r2's two "transition rules" (§1.6) are half-dead.** The
   PATHED-before-B10 rule is dead — `U-pathed` merged (`63f5962`), so the
   `pathed-unbuilt` flag must never be emitted again (it stays in the
   closed set `ledger_ops.py:98-107`; the doctrine forbids its use). The
   DEMAND-at-user-scope rule is *no longer transitional*: S-23 (2) made
   "no user-scope reference file" permanent, so what r2 wrote as a
   stopgap is now the standing rule. §3.8-D4 states it as such, and §10
   Q1 routes the one values question that survives it.

---

## 2. The seam, and what this unit does not own

**What lands here:** the composer (worker.py + analyst.py), the doctrine
rewrite, the S-26 flip (one constant + one guard in ledger_ops.py), and
the containment closures U-schema handed to whoever next holds
`worker.py`/`analyst.py` (`u-schema-decision-trace-spec.md:826-834`:
*"Closing any one site is a one-line `record_text=` add, owned by
whichever unit next holds that file"*).

**What does not land here, and why:**

| Not built here | Owner | Why not |
|---|---|---|
| `gates.py` + recompute-and-refuse | `U-table` | Campaign §2 assigns it; this unit's build waits on its merge (§8) |
| `proposal refresh` / `proposal audit` verbs | `U-refresh` | Campaign §2 assigns `proposal refresh`; `cli.py`/`verbs.py` are contended with `U-demand-user`/`U-pointer`. **Their contract is pinned here** (§3.10) because S-26 makes this spec own the migration surface — defining is not building |
| The pointer line + reference-route recompile | `U-pointer` | Campaign §2 |
| The UI destination menu | `U-demand-user` | Campaign §2 as re-scoped by S-23 |
| A new `card-sections.yaml` section for the trace | nobody — deliberately | §7-R7: the human-facing render rides the EXISTING required `discuss` section (§3.8-D10). A new registry key is a new surface with its own test obligations, and campaign §9 names "a unit absorbing an adjacent feature" as a way this loop fails |
| The discriminant-pair harness | `U-pairs` | Campaign §2; it is the falsifier for every judgment this unit's doctrine bounds |

---

## 3. The change

### 3.1 The composer's shape — one module, five ingredients, two prompt forms

All composer code lands in `worker.py` as **public** functions;
`analyst.py` imports them, exactly as it already imports
`package_skill_refs` (`analyst.py:114`). No new module: r2 B6 says
"factor `_compose_prompt`'s per-record block into a function both call",
and the campaign's file column for this unit is `worker.py, analyst.py,
routing-doctrine.md` — a new module would silently widen the unit's file
set and its merge surface.

```python
@dataclass(frozen=True)
class Roster:
    text: str            # the rendered block the model sees, verbatim
    sha: str             # sha_anchor(text) — or ledger_ops.ROSTER_UNAVAILABLE
    routable: int        # entries under the registered skills root
    visible_only: int    # entries visible but not routable (§3.2)

@dataclass(frozen=True)
class Candidate:
    record_id: str
    status: str          # "pending" | "routed"
    score: float
    title: str

def skill_roster(home: Path) -> Roster
def cluster_candidates(home: Path, batch: list[QueueEntry]) -> dict[str, list[Candidate]]
def path_roster(home: Path, entry: QueueEntry) -> str
def compose_record_block(home, entry, *, roster, candidates) -> str
def compose_batch_prompt(home, batch) -> tuple[str, Roster]   # replaces _compose_prompt
def compose_single_prompt(home, entry) -> tuple[str, Roster]  # the analyst's form
```

Both prompt builders **return the `Roster`** so the caller that later
validates model output can compare `gates.t3.roster_sha` against the
roster actually composed for that run (§3.6). No cache file: `run()`
composes (`worker.py:1370`) and validates (`worker.py:1420` →
`_validate_written`) in the same process, so an on-disk artifact would add
a staleness surface and a second source of truth for no gain. *(r2 §1.4
item 8 suggests storing it in the cache dir; rejected here for that
reason, and the rejection is recorded so a later reader does not "fix" it
back.)*

### 3.2 Ingredient 1 — the skill roster (T3)

**Sources, in order.** (a) `hosts.skills_root/plugins/*/skills/*/SKILL.md`
(`hosts.py:546-567` is the existing resolver for one skill; the roster
globs the same shape); (b) `<claude_dir>/skills/*/SKILL.md`, where
`claude_dir` is `selfcheck.claude_runtime_dir()` (`selfcheck.py:716-720`
— `SELF_LEARN_CLAUDE_DIR` or `~/.claude`). **Import it, never re-derive
it**: it is a shared *value* derivation, the class the codebase requires
be imported rather than copied (`ui/src/self_learn_ui/doctrine.py:25-29`
states that rule for the sibling case). Import it **lazily inside the
function**, matching the existing precedent at `worker.py:467`, so
`worker` never gains a module-scope edge to `selfcheck` (which imports
`verbs`, `selfcheck.py:96`).

**Dedupe by `Path.resolve()`.** Measured on this host 2026-08-06: 10
SKILL.md files under the registered skills root, 43 under
`~/.claude/skills`, naive union 53, **realpath union 43** — i.e. all 10
root skills are double-listed through symlinks. A roster that lists a
skill twice invites a "two skills own this" answer that is an artifact of
the filesystem.

**Parse frontmatter with YAML, never by line.** Measured: **11 of the 43
descriptions are YAML block scalars** (`description: |`), and a
line-based `description:` grab returns the literal `"|"` for all eleven.
`"|"` is non-empty, so a "did we get a description?" check passes while
the entry carries nothing — this project's signature defect shape. Parse
the leading `---`-delimited block with `ruamel.yaml.YAML(typ="safe")`
(already a dependency, `ledger_ops.py:156-161`): 43/43 yield a usable
description that way, 32/43 by line grab.

**Routability is part of the entry, not a footnote.** 33 of the 43
rostered skills on this host are NOT under the registered skills root
(they are plugin installs symlinked from `~/.agents/skills/`). A `skill-md`
route to one of them fails at route time — `_resolve_target` calls
`_hosts_skill_dir` (`verbs.py:936`), which raises `HostsError` for a skill
that is not `plugins/*/skills/<name>` under the root (`hosts.py:551-566`).
So each row renders one of:

```
- <name> [routable]: <description, one line, ≤200 chars>
- <name> [visible only — not under the registered skills root]: <description…>
```

and the doctrine pins the rule (§3.8-D2): **T3 may name an owner only
from the routable rows.** A visible-only skill that looks like the owner
is a *fact for the human* — stated in `rationale` and the card, exactly
as the doctrine already handles an unregistered ancestor project
(`routing-doctrine.md:117-120`) — never a `t3.answer: yes`.

**Rendering rules.** Sorted by name (frontmatter `name:`, else the
directory name); description flattened to one line and capped at **200
characters** with a trailing `…`; an entry whose frontmatter will not
parse is rendered as `- <dir name> [routable] (frontmatter unparseable)`
— **never dropped**, because a dropped skill is an invisible hole in the
roster T3 is judged against. Measured sizes for the 43-entry roster:
19,399 B uncapped, 12,612 B at 300, **9,376 B at 200**.

**The unavailable path.** Iff zero entries render, `Roster.text` is the
single line `(skill roster unavailable — no registered skills root and no
readable user skills dir)` and `Roster.sha` is
`ledger_ops.ROSTER_UNAVAILABLE` — **imported, never re-spelled**
(`ledger_ops.py:136-138`). The prompt states the sha verbatim so the model
copies it; X3 then forces `t3.answer: no` + `evidence-gap`
(`ledger_ops.py:1054-1068`).

**The sha covers what the model saw**: `sha_anchor(Roster.text)`
(`normalize.py:57-60`), not a digest of paths or mtimes.

### 3.3 Ingredient 2 — cluster candidates (T-N)

**r2's suggestion does not survive measurement, and this is the reason
this section pins a different algorithm.** r2 §0 item 4 says to extend
`_recurrence_suspects` (`worker.py:988-1062`) to emit "the pending+resolved
records sharing ≥N trigger tokens". Measured against a copy of the live
ledger (35 pending × 31 routed-resolved = 66 records, this host,
2026-08-06), using the shipped `_tokens` (`worker.py:982-985`) and
`record_title` (`ledger_ops.py:1838-1849`):

| basis | records with ≥1 candidate | largest list | total rows |
|---|---|---|---|
| Jaccard ≥ 0.60 (`SUSPECT_JACCARD`, `worker.py:102`) | **0 / 35** | 0 | 0 |
| Jaccard ≥ 0.20 | 3 / 35 | 1 | 3 |
| shared tokens ≥ 3 | 33 / 35 | **39** | 656 (one block = 12.4 KB) |
| shared tokens ≥ 2 | 35 / 35 | 51 | 1185 |

Both of r2's readings fail: the suspect threshold yields an always-empty
ingredient, and a shared-token count yields a queue dump. So:

**Pinned algorithm — IDF-cosine over trigger-title tokens, floor, rank
cap.** Pool = every pending record in every bucket plus every resolved
record with `status == "routed"`. For token set `T(r) = _tokens(record_title(r))`
over a pool of `N` records with document frequency `df(t)`:

```
idf(t) = ln(N / df(t))
score(a, b) = Σ_{t ∈ T(a)∩T(b)} idf(t)
              ────────────────────────────────────────────
              sqrt( Σ_{t ∈ T(a)} idf(t) · Σ_{t ∈ T(b)} idf(t) )
```

Keep candidates with `score ≥ 0.20` (`CANDIDATE_SCORE_FLOOR`), take the
top **5** (`CANDIDATE_CAP`), ties broken by record id ascending so the
block is deterministic. Render:

```
- lrn-74b8e65a [routed] (0.43): Writing a Bash-tool shell loop that iterates over several file…
```

with the title truncated at 120 characters; an empty list renders the
explicit line `(no cluster candidates above the 0.20 floor)` — **never an
omitted block**, because a missing block and an empty block read
identically to a model and only one of them is a fact.

**What the floor was calibrated on, and the oracle.** At floor 0.20, 6 of
35 pending records keep a candidate (8 rows total across the whole
queue). The oracle was a human read of every surviving top-1 pair; all six
are genuine subject matches, including a three-member family the corpus
really has:

| score | pair |
|---|---|
| 0.70 | `lrn-4323466d` ↔ `lrn-5d0c592a` (subagent model choice — the known `--supersedes` refinement pair) |
| 0.43 | `lrn-fc481dcb` ↔ `lrn-74b8e65a` (zsh word-splitting) |
| 0.39 | `lrn-547d8eb6` ↔ `lrn-74b8e65a` (same family — three records) |
| 0.26 | `lrn-96008965` ↔ `lrn-dd9489b2` (sudo/global npm) |
| 0.20 | `lrn-a229a2b5` ↔ `lrn-b44c89e1` (Claude Code plugin/agent enablement) |

**Preconditions, stated because an equivalence claim without them is a
coincidence someone wrote down** (campaign §5): titles are the first line
of `## Trigger`/`## Fact` only; `_tokens` lowercases, splits on
non-alphanumerics and drops tokens of ≤2 characters; IDF is computed over
the 66-record pool of the same run, so the constant is calibrated on one
corpus on one host and will drift as the corpus grows. Two consequences
are therefore pinned: the **score is rendered in the prompt** (a bad
calibration is visible, not silent), and the doctrine says the list is a
*ranking*, never evidence of clustering by itself (§3.8-D2, T-N).

**Cost.** Worst-case block measured at 780 B per record; a full
15-record batch (`BATCH_CAP`, `worker.py:90`) is ≤ 12 KB pre-floor and
~2 KB at the floor.

**`_recurrence_suspects` is not modified.** It is a telemetry producer
with its own dedupe key and its own basis string
(`worker.py:1018-1029`), and `U-recur` has just landed changes around
that channel (`9a782c7`). The candidate ranking is a second, read-only
consumer of the same `_tokens`; sharing the token function is the
single-definition rule, sharing the threshold would fuse two unrelated
calibrations.

### 3.4 Ingredient 3 — the absolute-path roster

One block per record, absolute paths only (both execution paths allow
`Read,Grep,Glob` — `worker.py:277`, `analyst.py:78` — and absolute reads
are cwd-independent, which is what r2 §2's "residual tool use is for
spot-verification" rests on):

```
ledger home        : /home/…/.self-learn
bucket             : …/skills/home-assistant
record file        : …/pending/lrn-….md
proposals dir      : …/proposals
skills root        : /home/…/repos/claude-skills        | (none registered)
host repo          : …                                   | (user scope has no host repo)
ALWAYS target      : …/CLAUDE.md                         | (unresolvable — <reason>)
PATHED rules dir   : …/.claude/rules                     | (unavailable at skill scope — P-A13)
DEMAND target      : …/references/LEARNINGS.md           | (unavailable at user scope — S-23)
```

**Resolution is pure path arithmetic, never `_resolve_target`.** The
route-time resolver runs registry gates and dirty checks and raises
`VerbError` (`verbs.py:901-1062`); calling it from a prompt composer would
make prompt assembly fail because a host repo happened to be dirty. The
composer mirrors `canon_excerpt`'s existing approach — hosts lookup plus
path join, with a sentinel string on failure (`worker.py:566-577` shows
the three sentinels already in use). **Every unresolvable slot renders an
explicit sentinel naming the reason; no slot is ever omitted.**

The two "unavailable" reasons are cited from shipped code, not from a
slogan: user-scope DEMAND is refused at `verbs.py:1045-1050`; skill-scope
PATHED at `verbs.py:811-816`.

### 3.5 The two prompt forms

**Batch (worker).** `compose_batch_prompt` keeps everything
`_compose_prompt` composes today — the rejected-proposal digest
(`worker.py:485-543`), the doctrine and the card registry
(`worker.py:637-650`), and per record the record text, bucket path, record
path and canon excerpt (`worker.py:651-660`) — and adds the roster **once
per prompt** (with its sha stated verbatim) plus, per record, the
candidate block and the path roster. The instruction header gains the
gate-output contract: write `gates:`, `flags:`, `recommendation:` on every
proposal, and the §-references it already carries (§5, §8, §9, §10 —
`worker.py:603-609`) stay, because two tests assert them
(`cli/tests/test_worker.py:1077-1095`, `:845-847`).

**Single (analyst).** `compose_single_prompt` produces the same per-record
block for one record, with the roster inline; the doctrine continues to
ride `--append-system-prompt` (`analyst.py:133-145`), so the analyst's
prompt does not carry the doctrine twice. `analyst.analyze` derives the
`QueueEntry` from the record it is handed via `find_record_path(home,
record.id)` (`ledger_ops.py` export list, `:59`), whose parent's parent is
the bucket dir — the same arithmetic `QueueEntry.bucket_dir` performs
(`ledger_ops.py:1741-1743`).

**The record text in the block is `Record.to_text()`, not the file's raw
bytes.** Today the block interpolates `entry.path.read_text()`
(`worker.py:657`) while containment checks quotes against
`Record.from_path(...).to_text()` (`ledger_ops.py:1410-1414`), which
re-renders the frontmatter through ruamel. Those are two different strings
by construction, and a quote the model copies faithfully out of the prompt
can therefore be refused as "not contained in the record it claims to
quote" — a silent, self-inflicted false refusal on the one gate this unit
exists to feed. **Measured on all 35 live pending records: flattened raw
and flattened `to_text()` are identical (35/35), and 105 sampled 80-char
windows of raw text are all contained in `to_text()` (0 misses)** — so the
change is a no-op on today's corpus and a guarantee for the next record
whose frontmatter ruamel re-renders differently. Show the model the exact
string the validator will check.

**Size ceiling.** The worker's prompt rides **stdin** precisely because a
single argv element caps at 128 KiB (`worker.py:313-317`). The analyst's
prompt and doctrine ride **argv** (`analyst.py:135-145`), so each is
subject to that cap. Measured inputs today: doctrine 25,390 B, card
registry 4,599 B, roster 9,376 B. §4-A13 pins a test that the composed
single-record prompt and the doctrine text each stay under 64 KiB — half
the cap, so growth is caught before it truncates.

### 3.6 The roster-sha honesty check

X3 today proves only that the model wrote *a* well-shaped sha or admitted
`unavailable` (`ledger_ops.py:1046-1068`); a fabricated
`sha256:aaaaaaaaaaaa` passes. Both producers hold the real value in
memory, so both close it:

- **Worker.** `run()` threads the `Roster` from `compose_batch_prompt`
  (`worker.py:1370`) through `_harvest` (`worker.py:1420`) into
  `_validate_written` (`worker.py:880-942`). A proposal whose
  `gates.t3.roster_sha` is neither the run's roster sha nor
  `ROSTER_UNAVAILABLE`-with-X3-satisfied is **deleted and logged** under
  the existing unattended policy (`worker.py:937-940`) — no new policy,
  one more `ProposalError` raised inside the existing `try`.
- **Analyst.** `analyze()` compares the parsed proposal's
  `gates.t3.roster_sha` against the `Roster` it composed and raises
  `AnalystError` on mismatch — the caller then captures the record as a
  normal pending teach and the lesson is never lost (`analyst.py:33-38`).

Deliberately **not** enforced in `_validate_gates`: it performs no
filesystem or run-context I/O by design (U-schema S4,
`ledger_ops.py:826-829`), and the roster is run-scoped state a validator
reading a file on disk months later cannot have.

### 3.7 Containment at the three sites (in two files) this unit now owns

U-schema names six call sites where `validate_proposal` is invoked
positionally, so containment is off, and assigns each to "whichever unit
next holds that file" (`u-schema-decision-trace-spec.md:810-834`). This
unit holds `worker.py` and `analyst.py`; it closes the three sites in
those two files and touches none of the three in `verbs.py`:

| site | today | after |
|---|---|---|
| `worker._validate_written` (`worker.py:927`) | `validate_proposal(data)` | `record_text=Record.from_path(rpath).to_text()` — the record is already located two lines below (`:928-930`) |
| `worker.fast_status` (`worker.py:1282`) | `validate_proposal(dict(pdata))` | `record_text=text` — the whole record file it already read at `worker.py:1232` (measured equivalent to `to_text()` on all 35 live records, §3.5) |
| `analyst.analyze` (`analyst.py:244`) | positional | `record_text=record.to_text()` — the record is the function's own argument |

**Why this is closure and not creep:** `analyst.analyze` is *the
producer* — "where a fabricated quote first arrives from the model, before
any other site ever sees it" (`u-schema-decision-trace-spec.md:791-794`)
— and this unit is the one that makes the model emit quotes at all.
Leaving it open would mean shipping the fabrication surface and the
fabrication opportunity in the same commit. Without it the failure is
silent-and-cyclic rather than loud: `proposal_info` re-validates with the
record text on the eligibility hot path (`ledger_ops.py:1809-1820`), so a
fabricated quote makes the record permanently unanalyzed and re-proposed
on every worker run, with nothing printed anywhere.

### 3.8 The doctrine rewrite

**Numbering is load-bearing and does not change.** `worker._PROMPT_TEMPLATE`
addresses the doctrine by section number (`worker.py:603-609`) and two
tests assert doctrine content and prompt section numbers
(`cli/tests/test_worker.py:850-862`, `:864-873`, `:1077-1095`). §§5, 5.1,
6, 7, 8, 9, 10 keep their numbers and their subject. §§1–4 are rewritten
in place; §2a is folded into §2's T2 except for its `variant: local`
case, which survives as §2a.

The builder writes the prose. The following are the **normative content
requirements**, each with the authority it rests on; §4-A14…A21 turn them
into assertions.

**D1 — §1 becomes the shelf model, with a per-scope availability table.**
The `destination` enum stays exactly five (`ledger_ops.py:77-78`); the
tiers are a *rendering* of it. The table must state, per scope, which
tier exists and where it lands:

| tier | skill:X | project | user |
|---|---|---|---|
| HOOK | plugin `hooks/` | `<skills-root>/hooks/self-learn/` | same |
| PATHED | **not available** (`verbs.py:811-816`) | `<host>/.claude/rules/<topic>.md` | `<user>/.claude/rules/<topic>.md` |
| SKILL | `SKILL.md` (`verbs.py:930-945`) | — | — |
| DEMAND | `references/LEARNINGS.md` (`verbs.py:1039-1041`) | `<host>/references/…` (`:1042-1044`) | **refused** (`:1045-1050`, S-23) |
| ALWAYS | skills-root `CLAUDE.md` (`verbs.py:979-991`) | `<host>/CLAUDE.md` (`:973-978`) | `~/.claude/CLAUDE.md` (`:964-972`) |

**D2 — §2 is replaced by the gate procedure.** Ordered G0 → T1 → T2 → T3
(→T3a) → T-N → T4 → E1 → outcome, one subsection each, and each
subsection states four things: *what it asks*, *which prompt ingredient
answers it*, *what evidence the answer requires and from which source*,
and *what to answer when the ingredient is unavailable*. The gate names,
answer domains and required-ness are U-schema's Schema-1
(`u-schema-decision-trace-spec.md:216-296`) — **cited, not restated**, so
the two cannot drift. Three rules the doctrine must add on top:

- **Every `evidence:` value is a verbatim quote from its named source —
  on `no` answers too.** Paraphrase is refused (§1.3 item 1, measured),
  and quotes shorter than 8 flattened characters are refused
  (`ledger_ops.py:131-134`).
- **T3 answers over the routable roster rows only** (§3.2), and a roster
  that reads `unavailable` forces `no` + `evidence-gap`.
- **T-N answers over the supplied candidate list**; the list is a ranking,
  an empty list means `no` with empty members, and the analyst may add a
  member it found itself (the validator checks id shape either way,
  `ledger_ops.py:1127-1134`).

**D3 — T2 carries both sharpenings, each as a question the analyst must
answer before answering T2 `yes`.**

1. *Timing* (campaign §6 item 5; S-23's rider, `03-decisions.md` S-23
   final paragraph): a pathed rule fires on first **Read** of a matching
   file, so ask whether the lesson's trigger fires **at or after** first
   contact with those files. "Before choosing a fixture strategy,
   remember X" is file-shaped and still served badly, because the
   decision is made before any matching file is opened.
2. *Search-only workflows* (S-24, `03-decisions.md`): ask whether the work
   that trips this lesson will actually **open** a matching file or only
   `Grep`/`Glob` it. Injection never fires for a search-only workflow, and
   nothing in self-learn can observe that — S-24 accepts it as a residual
   and assigns this doctrine question as its only mitigation. A lesson
   about grepping conventions is the case PATHED cannot serve.

**D4 — §3 becomes the tier model; the narrowest-surface bias survives as
the within-tier tiebreak only.** Content, with authority:

- PATHED is the primary cheap tier **where it exists** (S-23 (1) and (2));
  at skill scope the cheap tier is DEMAND (D1's table).
- DEMAND shrinks to lessons that are genuinely not file-scoped (S-23 (1)).
- ALWAYS is the expensive tier and is reached only when the record's own
  evidence argues for it (r2 §3's default: no silence marker, no cost
  statement, no caught-immediately statement ⇒ `INDETERMINATE` ⇒ the cheap
  branch).
- **DEMAND at user scope has no surface.** The rendering is
  `recommendation: defer` + flag `no-cheap-surface`, with the honest
  destination recorded — and **never a silent upgrade to ALWAYS**, which
  is the monoculture rebuilt (r2 §1.6's transition rule, promoted to a
  standing rule by S-23 (2)). Before deferring, the analyst asks whether
  the trigger's artifacts live in one repo; if so it flags
  `rehome-suggested` and says so in the card, because at project scope
  the same lesson has a cheap surface (doctrine §3's existing
  ancestor-project clause, `routing-doctrine.md:100-120`). **§10 Q1
  routes the values question this leaves open.**
- The narrowest-surface bias keeps its ranking sentence but loses its
  chezmoi ground (D6) and stops being the *only* tiebreak: it decides
  between two surfaces **inside one tier**, after the gates have chosen
  the tier.

**D5 — §3 carries the escalation rule** (campaign §6 item 6): when a
lesson already at the ALWAYS tier keeps recurring, the escalation is a
**GUARD, not more prose** — text that has failed at maximum prominence is
not fixed by more prominence. The evidence is in the corpus and must be
named: `lrn-ea833a5b` is routed to user `CLAUDE.md`, the most expensive
tier there is, and was violated twice (2026-07-26, 2026-07-27 — campaign
§7's recurrence row). Operationally: a record whose `e1` shows recurrence
against an ALWAYS routing re-enters at **T1**, not at T4.

**D6 — §4's two stale premises are replaced** (FW-43, the row this unit
carries):

- `:124-127` (chezmoi) — chezmoi was retired 2026-07-24 and nothing is
  chezmoi-managed. What survives is the *reason user scope is expensive*:
  `~/.claude/CLAUDE.md` loads in every session of every project. State
  that on its own merits.
- `:128-131` (*"Records, proposals, and canon are autosynced to a remote
  within seconds"*) — contradicted by S-17/D3: **pushes are manual**;
  verbs commit, the human pushes. **Keep the no-secrets rule** and
  restate its real ground: a secret in a record is committed by the verb
  that writes it and enters git history immediately, history is expensive
  to purge, and the ledger is synced across machines. The CLI's scan will
  refuse or flag what you miss; do not rely on it.

**D7 — §5 gains the trace as a MANDATORY part of the output contract.**
The three keys, their shapes and their enums are U-schema's (Schema-1,
Set-F/R/O/V; `ledger_ops.py:88-129`) — cited, not restated. What §5 must
add in its own words: the trace is now required on every proposal (S-26);
`flags: []` is written explicitly when there are no flags, so "no flags"
is an assertion rather than an omission; the flag list §5 shows the
analyst is the **seven live flags only** — `pathed-unbuilt` is omitted
entirely rather than named-and-forbidden, because naming a flag in a
system prompt is how it gets used, and the closed set is enforced by the
validator regardless (`ledger_ops.py:98-107`, `:836-840`); and the two
quote sources differ in what the
machine can check — RECORD quotes are containment-checked, **TARGET
quotes are not checked at all today**
(`u-schema-decision-trace-spec.md:719-744`). Say the second half out loud:
the analyst must write TARGET quotes as honestly as if they were checked,
because the only reader who can catch a false one is the human on the
card.

**D8 — §5's worked example is an EXECUTED trace, not a hand-written one.**
The example trace in the doctrine must be one that validates against the
shipped `_validate_gates`. The one below was run through it on 2026-08-06
(§9 probe 4) and accepted; the builder may substitute another only by
executing it the same way.

```yaml
recommendation: route
flags: []
gates:
  g0:
    reject: {answer: no}
    defer:  {answer: no}
    canon:  {answer: no}
  t1:
    attempted: true
    field_shaped: {answer: no, evidence: "About to spawn a subagent in a multi-agent workflow."}
    separable:    {answer: null}
    cost_bearing: {answer: null}
  t2: {answer: no, evidence: "About to spawn a subagent in a multi-agent workflow.", match_path: null}
  t3: {answer: no, owner: null, scan_terms: [subagent, model], roster_sha: "sha256:0123456789ab"}
  t3a: null
  t4:
    depth_behind_rule: {answer: no, evidence: null}
    conduct_mode:      {answer: no, evidence: null}
    fs: {verdict: INDETERMINATE, evidence: null}
  tn: {answer: no, terms: [], members: [], proposed_name: null}
  e1: {sightings: 1, post_demand_recurrence: false}
  outcome: DEMAND
```

**D9 — §7 (boundaries) gains four MUST NOTs**, each phrased as an
instruction to the analyst: never claim a scan you did not perform (the
roster in the prompt is the only roster you have); never name a path you
did not receive in the path roster or read at an absolute path; never
write a quote you have not copied from the source named for that leg; and
never hand-write a decision trace for a record you did not analyze — a
record whose gates were never evaluated has **no proposal**, not an
invented one (S-26's honesty constraint, §3.10).

**D10 — §8 (the card contract) gains one sentence**: the `discuss`
section must carry, in plain words, which shelf the trace chose and the
verbatim quote that unlocked it. This is the standing UI obligation from
campaign §7's quote-relevance row and U-schema's §3.4 boundary
(*"the review card must surface the quote verbatim, or the human's check
has nothing to look at"*), discharged through a section the registry
already requires for routing proposals
(`card-sections.yaml`, `discuss`, `required: routing`) rather than a new
registry key (§2, §7-R7).

**D11 — what must be gone, and gone means unmentioned.** After the
rewrite the file must not contain the word `chezmoi`, the word `autosync`,
the `type`/`kind`/`scope` routing map as the routing procedure, or the
token `pathed-unbuilt`. **Not even to say they are retired**: this file is
a system prompt, not a changelog, and a retired premise mentioned in a
prompt is a premise a model can still act on. The history belongs in this
spec and in `03-decisions.md`. §4-A20 asserts each absence with a positive
control.

### 3.9 The S-26 flip — one flag, one guard, and its measured blast radius

S-26 (`03-decisions.md`) rules that the trace fields go from optional to
MANDATORY riding this unit, and that the flip does **not** wait for the
pending queue to drain. Concretely:

```python
#: S-26: the decision trace is MANDATORY. Flipped with U-composer, the
#: unit that makes the analyst emit traces by construction — flipping
#: before a producer exists would refuse every proposal and wedge the
#: worker pipeline (S-26's own "binding constraint is the producer").
TRACE_REQUIRED = True
```

and, as the first statement in `_validate_gates` (`ledger_ops.py:819`):

```python
if TRACE_REQUIRED:
    for key in ("gates", "flags", "recommendation"):
        if data.get(key) is None:
            raise ProposalError(
                f"proposal is missing the required decision-trace key {key!r} "
                "(S-26) — re-analyze the record (`self-learn proposal refresh "
                "<id>`); a trace is never hand-written"
            )
```

**All three keys, not just `gates`.** S-26 names all three; requiring
`flags` costs one line in the producer (`flags: []`) and converts "no
flags" from an omission into an assertion, which is the same distinction
this project has already paid to learn elsewhere.

**Where it takes effect:** everywhere, because every proposal-reading path
funnels through `validate_proposal` → `_validate_gates`
(`ledger_ops.py:1309`). One flag, one guard, no per-caller posture — the
inverted-permissions shape FW-62 found (strict on the machine path,
lenient on the human path) is exactly what a per-caller flip would
recreate.

**Blast radius — measured, not predicted** (§9 probe 3; a scratch ledger,
never `~/.self-learn`, with one proposal in the exact pre-schema shape
FW-62 measured on all 20 live pending proposals):

| surface | before the flip | after the flip |
|---|---|---|
| `validate_proposal(legacy, record_text=…)` | ACCEPTED | REFUSED, naming the missing key |
| `proposal_info` | `proposal_fresh: True` | `proposal_fresh: False`; `destination` still surfaced |
| `is_unanalyzed` | `False` | **`True`** → the next worker run re-analyzes it |
| `route` with no `--dest` (`verbs.py:537-558`) | resolves | refuses with the message |
| `route --dest <d>` — **the review UI's only form** | resolves | **still resolves** (the proposal is never read) |

Three things follow, and the spec states them rather than leaving them to
be discovered:

1. **Pending records self-migrate.** A legacy proposal becomes
   `is_unanalyzed: True`, so the next worker run re-proposes it *with* a
   trace, and the model — not a migration script — produces the gate
   answers. Nothing is fabricated because nothing is conformed in place.
2. **The human's review flow is not wedged.** The UI always sends an
   explicit `--dest` and says so in its own code
   (`ui/.../routes.py:124-130`: *"This app's `route` argv always carries
   an explicit `dest`"*, emitted at `:131-134`). Approving a legacy card
   still works; it is exactly as (un)checked as it was yesterday.
3. **The producer side is enforced by deletion, not by hope.** A model
   proposal missing the trace fails `_validate_written` and is deleted and
   logged under the existing unattended policy (`worker.py:937-940`).

**Ordering within the merge.** The flip must land **with or immediately
after** the composer and doctrine in the same merge (S-26: "landing with
or immediately after its merge"), never before — a flip without a
producer refuses every proposal the worker writes.

### 3.10 The migration verb surface (what S-26 makes this spec own)

S-26 gives migration two inherited constraints: **the ledger is
agent-read-only, so migration mutates records only via CLI verbs under
user supervision**, and **migrated content must never fabricate traces —
a record whose gates were never evaluated gets an honest absent-with-reason
form, never invented values.** This section defines the surface; the
build belongs to `U-refresh` (§2).

**The honest absent form is the absence of a proposal, not a proposal
that says "absent".** A trace is a record of an evaluation; a record whose
gates were never evaluated has nothing to record. The reason is carried by
the withdrawal (verb output, commit message, telemetry), not by an
invented field. A `trace_absent: <reason>` escape hatch was considered and
**rejected**: it is a field the analyst could also write, so it would
become the fail-open the flip exists to close, and it would need its own
closed reason enum to be checkable at all.

**Verb 1 — `self-learn proposal audit [--json]` (read-only census).**
For every pending record, one row: `complete` (trace present and valid),
`absent` (no trace), `invalid:<reason>` (trace present, refused), or
`none` (no proposal sibling). Totals per bucket and overall. Writes
nothing, mutates nothing, exits 0 on every input — it is a census, not a
gate. **It is the migration's positive control**: run before the flip it
must report the live count of `absent` (today: every pending proposal per
FW-62), and after migration 0. A census that cannot distinguish "no
records" from "all clean" is worthless, so the row count leads the output
line (the same discipline `_check_reach` follows, `selfcheck.py:378-383`).

**Verb 2 — `self-learn proposal refresh <id> | --traceless | --all`
(withdraw, so the worker re-analyzes).** Validates, in order: the record
resolves and is `pending`; a proposal sibling exists; for `--traceless`,
that sibling's trace is absent or invalid (a complete trace is skipped
unless `<id>` names it explicitly); the ledger has no uncommitted changes
to the paths it will touch. Then it `git rm`s the sibling(s), prints what
it removed and why, and commits with the reason in the message. It
**never writes trace content, and takes no gate values as input.**

**The MUST NOT that makes the honesty constraint checkable:** no CLI verb
anywhere accepts gate values as arguments — no `--gates`, no `--set-gate`,
no `--outcome`, no `--flag`. The only writers of a `gates:` mapping are
the two analysis producers (the worker's model output and
`analyst.analyze`). §4-A22 asserts this by grep, with a positive control.

**Supervision.** Both verbs are human-invoked. A migration workflow's
agents may READ the ledger and may *propose* invocations; they do not
write ledger files directly (S-17/D2: the ledger is its own repo, and
agent write access to it is not a thing this system grants). The user's
sanction in S-26 covers a multi-agent workflow driving these verbs — not
agents editing records.

---

## 4. Acceptance criteria

**These criteria are the contract.** For each, the line in *italics* is
what the check reports when its target is absent or broken — the
project's signature defect is a check whose absent-target output equals
its pass output (campaign §5), and any criterion whose italic line reads
"pass" is a defect in this spec, not in the build.

### A. The roster

**A1 — the roster is composed from both sources and deduped by realpath.**
With a scratch skills root holding `plugins/p/skills/alpha/SKILL.md` and a
scratch claude dir whose `skills/alpha` is a **symlink** to that same
directory plus a real `skills/beta`, `skill_roster(home).text` contains
exactly one `alpha` row and one `beta` row, and `routable == 1`,
`visible_only == 1`.
*Absent/broken: a build that skips the dedupe renders two `alpha` rows and
fails the "exactly one" assertion; a build that reads only the skills root
renders no `beta` row and fails `visible_only == 1`.*

**A2 — a block-scalar description survives (the measured fail-open).**
A `SKILL.md` whose frontmatter is `description: |` followed by an indented
paragraph renders that paragraph's text in its row; the row does **not**
contain a bare `|`. Positive control in the same test: a plain
`description: text` skill renders too, so the assertion cannot pass
because nothing rendered.
*Absent/broken: a line-grab implementation renders `- alpha [routable]: |`
and fails both legs. Measured motivation: 11 of 43 live skills.*

**A3 — an unparseable frontmatter is rendered, never dropped.** A
`SKILL.md` with a corrupt leading block renders a row carrying the
directory name and an explicit marker, and `routable + visible_only`
counts it.
*Absent/broken: a build that `continue`s past the parse error renders one
fewer row and the count assertion fails — which is the point, because a
silently missing skill is an invisible hole in T3's evidence.*

**A4 — the unavailable path is real and is coupled to X3.** With no
registered skills root and an empty claude dir, `Roster.sha ==
ledger_ops.ROSTER_UNAVAILABLE` and the text names the reason. **And** a
proposal carrying `t3.roster_sha: "unavailable"` with `t3.answer: yes` is
refused by the shipped validator, while the same trace with `answer: no` +
`flags: [evidence-gap]` is accepted.
*Absent/broken: a build that returns an empty string with a real sha
passes the first leg and fails the second — so both legs are required.*

**A5 — the sha covers the rendered text.** `Roster.sha ==
sha_anchor(Roster.text)` for a non-empty roster, and mutating one
character of any description changes the sha.
*Absent/broken: a sha derived from paths or mtimes is stable across the
description mutation and fails the second leg.*

### B. Cluster candidates

**A6 — the ranking, the floor and the cap, on a fixture that discriminates.**
A pool containing (i) two records whose titles share a distinctive rare
term, (ii) six records sharing only common terms, and (iii) one record
sharing nothing, yields: for (i) a list whose first row is the sibling with
a score ≥ 0.20; for (ii) at most 5 rows and none below the floor; for (iii)
the literal line `(no cluster candidates above the 0.20 floor)`.
*Absent/broken: a build with no floor returns rows for (iii) and fails; a
build with no cap returns 6 rows for (ii) and fails; a build that omits
the block entirely for (iii) fails the literal-line assertion.*

**A7 — determinism.** Two calls on the same pool return byte-identical
blocks, including under a shuffled input order.
*Absent/broken: a set-ordered or dict-ordered implementation differs
across runs and fails.*

**A8 — the score is rendered.** Every candidate row contains its score to
two decimals.
*Absent/broken: a row without a score passes every other criterion while
making a mis-calibrated floor invisible — which is why this is its own
criterion.*

### C. The path roster and the per-record block

**A9 — every slot is present, and unresolvable slots carry a reason.**
For a user-scope record in a home with no registered skills root: the
block contains a `skills root` line reading `(none registered)`, a
`DEMAND target` line naming S-23, and a `PATHED rules dir` line resolving
to the user rules dir. For a skill-scope record: the `PATHED` line reads
the P-A13 unavailability and the `DEMAND` line resolves.
*Absent/broken: a build that omits unresolvable slots fails the presence
assertions — a missing line and an unavailable line must not read the
same.*

**A10 — composing a prompt never raises because a host repo is dirty.**
With the project host's `CLAUDE.md` modified and uncommitted,
`compose_batch_prompt` returns a prompt.
*Absent/broken: a build that resolves targets via `_resolve_target` raises
`VerbError` and the test errors — the exact failure this criterion
exists to prevent.*

**A11 — both execution paths compose the same per-record block.** The
per-record block from `compose_batch_prompt` for a one-record batch and
from `compose_single_prompt` for that record are byte-identical.
*Absent/broken: two divergent implementations differ and fail — and the
campaign's open question ("do the worker and the one-shot analyst behave
the same?") would otherwise stay open by construction.*

**A12 — the worker prompt still carries what it carried, and shows the
text containment checks.** The assembled prompt contains the real
doctrine's `trigger_recognizable`, `why_present`, `§9`, `§10`, the card
registry, and the rejected-proposal digest, **and** now contains the
roster sha line, a candidate block and a path roster. **And** for a record
whose file bytes differ from `Record.to_text()` (a fixture with
frontmatter ruamel re-renders — e.g. a quoted scalar), the block contains
`to_text()`, not the raw bytes.
*Absent/broken: a rewrite that drops the digest or the registry fails the
first half; a composer that forgets an ingredient fails the second; a
composer that interpolates `entry.path.read_text()` passes both halves on
every record in the live corpus (measured 35/35 identical) and fails only
the third leg — which is why that fixture must be constructed to differ,
not sampled from the ledger.*

**A13 — the argv-bound prompts stay under half the 128 KiB cap.** The
doctrine text and the composed single-record prompt for a worst-case
record (200-line record, 43-entry roster, 5 candidates) are each < 64 KiB.
*Absent/broken: a doctrine that grows past the ceiling fails here rather
than truncating an analyst invocation in production.*

### D. The doctrine

Assertions are made against the **real shipped file**
(`worker.package_skill_refs() / "routing-doctrine.md"`), in the CLI suite,
beside the two tests that already do this (`test_worker.py:850-873`).

**A14 — the gate sequence is present and ordered.** The file contains the
gate labels `G0`, `T1`, `T2`, `T3`, `T3a`, `T-N`, `T4`, `E1`, and their
first occurrences appear in that order.
*Absent/broken: a doctrine that mentions the gates in prose but out of
order fails the ordering leg; one that omits a gate fails presence.*

**A15 — the two T2 sharpenings are present, each with its authority.**
The T2 section contains the timing question (matched on "first contact"
and "Read") and the search-only question (matched on "Grep" and "Glob"),
and the file cites `S-24`.
*Absent/broken: a doctrine carrying only the r1 question ("does it only
matter for certain files?") fails both legs.*

**A16 — the escalation rule is present with its evidence.** The file
contains the guard-not-prose rule and names `lrn-ea833a5b`.
*Absent/broken: a doctrine that says "escalate" without naming the guard,
or without the corpus evidence, fails.*

**A17 — the tier model is stated per scope, with both refusals.** The file
states that PATHED is unavailable at skill scope and that DEMAND is
refused at user scope, and cites S-23 for the second.
*Absent/broken: a doctrine repeating "PATHED at every scope" fails the
first leg — the case §1.3 item 2 measured.*

**A18 — the trace is described as mandatory and the quote rule is
unambiguous.** The file states that `gates`, `flags` and `recommendation`
are required, that every `evidence` value is a verbatim quote **including
on `no` answers**, and that TARGET-sourced quotes are not machine-checked.
*Absent/broken: a doctrine that repeats r2's "record names no paths"
phrasing fails; §4-A19 catches it a second way.*

**A19 — the doctrine's worked trace validates.** The YAML example in §5 is
extracted from the shipped doctrine, parsed, and passed to
`_validate_gates(..., record_text=<the doctrine's own example record>)`
without error.
*Absent/broken: an example that would be refused in production fails here
— the failure mode that makes a doctrine teach an unroutable form.*

**A20 — the deletions, each with a positive control.** The file does not
contain `chezmoi`, does not contain `autosync`, and does not contain
`pathed-unbuilt`. Positive control in the same test: it *does* contain
`no secrets`/secret-scan text, `S-23`, and `PATHED` — so an empty or
truncated file cannot pass.
*Absent/broken: a zero-byte doctrine passes every "does not contain"
assertion and fails every positive control — which is precisely why the
controls are in the same test.*

### E. The flip and the trace producers

**A21 — the flip refuses a trace-less proposal, and the flag is what does
it.** A pre-schema proposal (no `gates`/`flags`/`recommendation`) is
refused by `validate_proposal`, and `is_unanalyzed` for its record becomes
`True`. Positive control in the same test: with `TRACE_REQUIRED`
monkeypatched to `False`, the identical proposal is accepted and
`is_unanalyzed` is `False`.
*Absent/broken: without the control, any unrelated schema error would
satisfy the refusal leg; with it, only the flip can.*

**A22 — no verb accepts gate values.** A search of the CLI argument
surface (`cli.py`) finds no `--gates`, `--set-gate`, `--outcome` or
`--flag` option. Positive control: the same search finds `--dest` and
`--note`, which do exist.
*Absent/broken: without the control the search passes on a typo'd path or
an empty file — the fail-open class `lrn-ea833a5b` names.*

**A23 — roster-sha honesty, both paths.** (a) Worker: a model-written
proposal whose `gates.t3.roster_sha` is well-shaped but is not the run's
roster sha is deleted and logged, and the record stays pending. (b)
Analyst: the same mismatch raises `AnalystError`. Positive control in each:
the same proposal carrying the run's real sha survives.
*Absent/broken: a build that only shape-checks passes the control legs and
fails the mismatch legs.*

**A24 — containment is on at the three sites this unit owns.** A proposal
carrying a fabricated RECORD quote is (a) deleted by `_validate_written`
rather than landed, and (b) raises `AnalystError` from `analyst.analyze`.
Positive control: the same proposal with a true quote survives both.
*Absent/broken: with containment off, the fabricated proposal lands and
only fails later, invisibly, as a permanently-unanalyzed record — so this
criterion must assert at the producer, not on the next `list`.*

**A25 — suite and types.** CLI suite green against its own baseline
(**1266 passed, 5 skipped, 0 failed** — campaign §4a; *there is no
tolerated failure in the CLI suite*), plus this unit's new tests. UI suite
run too, because the doctrine is compiled into the pane
(`ui/.../doctrine.py:79-126`): baseline **1107 passed, 1 failed
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`),
0 skipped**, staged with **both** `XDG_CACHE_HOME` and
`PLAYWRIGHT_BROWSERS_PATH` exported (campaign §4a). `pyright` clean.
*Absent/broken: read the FAILED lines and confirm the UI skip count is
zero — a suite that cannot see Chromium reports skips, not failures, and
is indistinguishable from a clean run by exit code (campaign §4a).*

---

## 5. Mutation plan

For each load-bearing behaviour, the one-line production edit that must
make exactly the named test fail. Run the sweep with
`PYTHONDONTWRITEBYTECODE=1` and a cleared `__pycache__`, from absolute
paths, after machine-checking `realpath(self_learn.__file__)` — campaign
§3 records all three ways this instrument has lied here.

| # | Mutation | Must redden |
|---|---|---|
| M1 | Drop the `Path.resolve()` dedupe in `skill_roster` | A1 |
| M2 | Replace the YAML frontmatter parse with a `description:` line grab | A2 |
| M3 | `continue` past an unparseable `SKILL.md` | A3 |
| M4 | Return a real sha instead of `ROSTER_UNAVAILABLE` for an empty roster | A4 |
| M5 | Compute the roster sha over the source paths instead of the rendered text | A5 |
| M6 | Remove the `CANDIDATE_SCORE_FLOOR` test (keep the cap) | A6 |
| M7 | Remove the `CANDIDATE_CAP` slice (keep the floor) | A6 |
| M8 | Sort candidates by score only, dropping the id tiebreak | A7 |
| M9 | Render candidate rows without the score | A8 |
| M10 | Omit an unresolvable path-roster slot instead of rendering its sentinel | A9 |
| M11 | Resolve ALWAYS/DEMAND targets via `_resolve_target` | A10 |
| M12 | Give the analyst path its own per-record block builder | A11 |
| M13 | Drop the digest (or the registry) from the batch prompt | A12 |
| M14 | Set `TRACE_REQUIRED = False` | A21 |
| M15 | Require only `gates`, not `flags`/`recommendation` | A21 (the flags leg) |
| M16 | Skip the roster-sha comparison in `_validate_written` | A23a |
| M17 | Skip it in `analyst.analyze` | A23b |
| M18 | Revert `record_text=` to a positional call at `worker.py:927` | A24a |
| M19 | Revert it at `analyst.py:244` | A24b |
| M20 | Delete the T2 search-only paragraph from the doctrine | A15 |
| M21 | Restore the word "chezmoi" to the doctrine | A20 |
| M22 | Replace the doctrine's worked trace with r2's `"record names no paths"` t2 evidence | A19 |
| M23 | Interpolate `entry.path.read_text()` instead of `Record.to_text()` in the record block | A12 (third leg only) |

**Reviewers are invited to invent mutations this table does not list**
(campaign §3). Two suggested starting points, both places where a wrong
implementation would still look right: a roster that renders
`visible_only` rows *without* the marker (A1's counts still pass if the
marker is the only thing missing — check the marker text explicitly), and
a candidate block that applies the floor to the *sum* rather than each
candidate.

---

## 6. Builder decisions, made here rather than left open

1. **Composer lives in `worker.py`, not a new module** — §3.1.
2. **`claude_runtime_dir` is imported lazily from `selfcheck`** — §3.2;
   the value derivation is shared, the import edge is not wanted at module
   scope.
3. **Description cap = 200 chars**; measured 9,376 B for the 43-entry
   roster (12,612 at 300, 19,399 uncapped).
4. **Candidate floor = 0.20, cap = 5**, both named module constants whose
   docstrings carry the measurement and its date — a bare `0.2` in a
   comparison is a number a later reader cannot audit.
5. **The roster is composed once per prompt**, not once per record: T3's
   question is identical across a batch and the sha must be too.
6. **`_recurrence_suspects` is not touched** — §3.3.
7. **No cache artifact for the roster** — §3.1.
8. **All three trace keys required, `flags: []` written explicitly** —
   §3.9.
9. **The migration verbs are specified, not built** — §2, §3.10.
10. **No new `card-sections.yaml` key** — §2, D10.
11. **Doctrine section numbers are preserved** — §3.8 preamble.
12. **Sentinels, never omissions**, for every unresolvable ingredient
    (roster, candidates, path slots, canon excerpt) — the existing
    `canon_excerpt` sentinels (`worker.py:566-577`) are the precedent.
13. **The prompt shows `Record.to_text()`**, the string containment
    checks — §3.5, measured a no-op on the current corpus.
14. **`TRACE_REQUIRED` is read as a module global at call time**, inside
    `_validate_gates`, not bound at import — otherwise A21's positive
    control (monkeypatch to `False`) cannot exercise the flag, and a
    control that cannot move the outcome is not a control.

---

## 7. Out of scope, and the residuals this unit accepts

Declared explicitly, in the S-24/S-25 pattern, so a later agent does not
re-open them as bugs.

**R1 — the judgment residue is unchanged.** T1 `field_shaped`/`separable`,
T3 ownership, T-N artifact class, and the `fs`/`conduct_mode` verdicts stay
model judgments (r2 §8 item 1). This unit bounds their *inputs* — a hashed
roster, a supplied candidate list, quote-gated verdicts — it does not make
routing deterministic. `U-pairs` measures the residue; until it runs, "the
procedure works" is a claim.

**R2 — cluster candidates rank titles, not meaning.** A record whose
trigger title shares no tokens with its true sibling gets an empty list
and T-N answers `no` — the cheap direction, re-checked on every run
because the whole queue is re-composed each time. The floor is calibrated
on one 66-record corpus on one host (§3.3); the score is rendered so a
drifted calibration is visible rather than silent. **Not a defect to fix
by widening the floor without a fresh measurement** — widening was tried
at the shared-token bases and measured a queue dump.

**R3 — TARGET-sourced quotes remain uncontained.** `gates.g0.canon`,
`gates.t3a.depth_behind_rule`, `gates.t4.depth_behind_rule` are
shape-checked only (`u-schema-decision-trace-spec.md:719-744`, with its
reasons). The doctrine tells the analyst to write them as if checked and
tells the human they are not. Closing this needs filesystem I/O in a
validator that is I/O-free by design; it is not this unit's to close.

**R4 — the roster-sha check proves exposure, not attention.** It proves
the model was given *this* roster; it cannot prove the model read it.
`U-pairs`' T3 pair is the only instrument that can.

**R5 — the flip does not force the migration to finish.** Legacy
proposals become visibly stale and are re-analyzed opportunistically by
the worker; nothing compels a human to run `proposal audit`. The census
verb is the instrument, and it does not exist until `U-refresh` lands.
Accepted deliberately: S-26 ruled progress outranks capturing the
backlog.

**R6 — a visible-only skill can still be a record's scope.** A ledger
bucket named `skills/<name>` for a skill outside the registered skills
root will fail at route time (`hosts.py:551-566`), regardless of what the
trace says. The roster's routability marker and D2's rule keep the
*analyst* from proposing it; they cannot repair a bucket that already
exists. Surfacing that is a `selfcheck` concern, not a composer one —
recorded here, not built.

**R7 — the trace has no dedicated card section.** Its human-facing render
rides `discuss` (D10). If a later UI unit adds a `shelf` registry key, the
doctrine sentence D10 pins is the thing to move — the registry is
generic (`ui/.../models.py:449-452`), so the change is data plus one
doctrine edit.

**Handoffs, named with their change rather than silently assumed:**

- `U-table` must not restate the outcome enum (`TRACE_OUTCOMES`,
  `ledger_ops.py:116-126`) — U-schema §8-O1 already pins that.
- `U-refresh` inherits §3.10's two verb contracts verbatim, including the
  census's positive-control obligation.
- `U-pairs` inherits the roster and candidate ingredients as fixtures: a
  yes-shaped and no-shaped record per judgment gate, run against both
  execution paths, is only meaningful now that both paths compose the same
  block (A11).
- `U-pointer` unchanged: this unit's doctrine states that DEMAND targets
  become reachable via the pointer; it emits nothing.

---

## 8. Interface assumptions about `U-table` — FLAGGED FOR THE GATE

**`U-table`'s spec was in flight concurrently with this one and no draft
existed in `docs/specs/self-learn/drafts/` when this was written
(checked 2026-08-06, twice: at the start and immediately before commit).**
Every assumption this spec makes about the decision table is listed here
so the gate can verify each against the real `U-table` draft rather than
discovering a mismatch at build time. **If any assumption is false, the
correction lands in this spec's doctrine section (D2/D4) and its acceptance
criteria — not in `gates.py`.**

1. **`gates.py::expected_outcome(trace, scope) -> str` exists**, is pure,
   and implements r2 §1.5's ordering (G0 exits, then HOOK, then the load
   class). The doctrine describes that ordering in prose (D2); if the
   table's order differs, **the table wins** and the doctrine is corrected.
2. **The recompute-and-refuse check is wired inside `validate_proposal`
   in `ledger_ops.py`** (r2 §1.4 item 3 / B5). This is the file this unit
   also edits for the flip (§3.9), so **`U-table` must merge first** and
   this unit rebases onto it. The flip is one constant plus one guard at
   the top of `_validate_gates`, deliberately small so the rebase is
   trivial.
3. **The rendering map (r2 §1.6) is enforced by `U-table`, not here.**
   This spec assumes `outcome: PATHED` ⇒ `destination: claude-md` +
   `variant: rules` + non-empty `rules_paths`; `ALWAYS` ⇒ plain
   `claude-md`; `SKILL` ⇒ `skill-md`; `DEMAND` ⇒ `reference`; `NEW_SKILL`
   ⇒ `new-skill`; `HOOK` ⇒ `hook`.
4. **`outcome: GRADUATE` couples to the existing `already_canon` field.**
   This spec's doctrine tells the analyst to write `already_canon: true` +
   `already_canon_reason` alongside `recommendation: graduate` when
   `g0.canon.answer == yes`. **Unknown: whether `U-table` enforces that
   coupling.** If it does not, the coupling is doctrine-only and a
   proposal that omits `already_canon` still validates — say so at the
   gate rather than assuming.
5. **DEMAND at user scope renders `recommendation: defer` + flag
   `no-cheap-surface`** (D4). If `U-table` renders something else, every
   user-scope cheap proposal will fail the derivation check — **this is
   the highest-consequence assumption in this list**, because 10 of the 12
   pending records are user scope.
6. **`pathed-unbuilt` is never emitted** (`U-pathed` shipped). The flag
   remains in the closed set for schema stability; this spec assumes
   `U-table` neither requires nor emits it.
7. **PATHED at skill scope.** The table's T2 row returns `PATHED` from
   `t2.answer == "yes"` without consulting scope (r2 §1.5). Since skill
   scope has no pathed surface (§1.3 item 2), one of two things must be
   true: either the doctrine keeps skill-scope T2 answering `no` (this
   spec's assumption, D2/D3), or `U-table` special-cases scope. **If
   `U-table` special-cases it, D2's instruction must change to match.**
8. **`e1` cross-checks.** U-schema left `e1.sightings` unverified against
   the record and named `U-table` as a possible owner
   (`u-schema-decision-trace-spec.md:750-754`). Either way the composer
   already supplies the record's frontmatter, so no composer change
   follows; noted so the gate can confirm.

---

## 9. Test obligations from campaign §5, and what was executed for this spec

**Every gate-shaped check ships with a positive control.** Applied at
A1–A24; the four that would otherwise be fail-open are A4 (unavailable
roster), A20 (doctrine deletions), A21 (the flip), A22 (the verb-surface
grep), and each carries its control in the same test.

**Never read an exit code downstream of a pipe.** Suite and pyright runs
capture `rc` unpiped or read the tool's own pass/fail line (campaign §5;
`lrn-ea833a5b`).

**Algorithms pinned in prose were executed** (campaign §5's rule, added
after a spec shipped an untested matcher). Four probes, all read-only
against copies, all with `SELF_LEARN_HOME`, `XDG_CACHE_HOME`,
`XDG_RUNTIME_DIR`, `SELF_LEARN_CLAUDE_DIR` and
`SELF_LEARN_TRANSCRIPTS_DIR` redirected to `/tmp/u-composer-scratch/`, and
each asserting `realpath(self_learn.__file__)` is under this worktree
before measuring:

| probe | what it established | oracle / preconditions |
|---|---|---|
| roster enumeration | 10 root + 43 user SKILL.md; realpath union 43 vs naive 53; sizes 19,399 / 12,612 / 9,376 B | the live host's skills root + `~/.claude/skills`, 2026-08-06 |
| roster parsing | 11/43 descriptions are block scalars; line grab yields `"|"` for all 11, YAML parse yields 43/43 | `ruamel.yaml.YAML(typ="safe")` over the leading block as the oracle |
| candidate ranking | Jaccard 0.6 → 0/35; Jaccard 0.2 → 3/35; shared≥3 → 33/35 with a 12.4 KB block; IDF-cosine floor 0.20 → 6/35, 8 rows, all six top-1 pairs genuine | pool = 35 pending + 31 routed from a **copy** of the live ledger; oracle = human read of every surviving pair; `_tokens`/`record_title` as shipped |
| the flip | the five-surface before/after table in §3.9; the doctrine's worked trace validates; r2's `"record names no paths"` is refused while a real quote is accepted, with containment-off as the control | shipped `_validate_gates`/`proposal_info`/`_resolve_destination` in this worktree |
| prompt-vs-containment text | flattened raw file text == flattened `Record.to_text()` on 35/35 live pending records; 105 sampled 80-char raw windows all contained in `to_text()` (0 misses) — so §3.5's change is a no-op today and a guarantee tomorrow | `_flatten_quote` as shipped, over a **copy** of the live ledger |

**The 51 resolved records are `U-table`'s regression fixtures**, not this
unit's (campaign §5) — but note that the candidate ranking above was
calibrated against 31 of them, so a `U-table` run that disagrees with a
human routing on one of those records is a finding for that unit, not
evidence against this ranking.

**The pair harness is the campaign's falsifier** and is `U-pairs`. Until
it runs, A11 (both paths compose the same block) is the strongest claim
this unit can make about path parity.

---

## 10. Open questions for the gate

**Q1 (values — route to the user; do not guess).** S-23 (2) made "no
user-scope on-demand shelf" permanent, and 10 of the 12 pending records
are user scope. So a user-scope lesson that is not file-scoped, not
hook-shaped, not owned by a skill, and whose record carries no
silence/cost evidence has **no cheap surface at all**. This spec's
doctrine (D4) keeps r2's rule — `recommendation: defer` + flag
`no-cheap-surface`, never a silent upgrade to ALWAYS — because that is the
move the human already made by hand (`lrn-547d8eb6`) and because the
deferred pile is the evidence Checkpoint A needs. **But "defer forever" is
itself a monoculture**, and Checkpoint C is explicitly instructed to look
for exactly that ("did we build a new monoculture at the other end?").
The question for the user: *when a user-scope lesson has no cheap surface,
should the analyst defer it with the flag (recommended, status quo), route
it ALWAYS with the flag, or push harder on re-homing it to project scope?*
Recommendation: keep defer + flag through Checkpoint A, then decide with
the measured distribution in hand — O-10 already sets that precedent for
the Model-B question.

**Q2 (interface).** All eight assumptions in §8, especially #5
(DEMAND-at-user-scope rendering) and #7 (PATHED at skill scope). These
need reconciling against the `U-table` draft before build.

**Q3 (scope).** Is closing containment at `analyst.analyze` and
`worker._validate_written` (§3.7) accepted as the handoff U-schema
assigned, or should it be split into its own unit? This spec argues
handoff — the producer of quotes and the checker of quotes shipping in one
commit — but it is three lines in two files this unit already edits, and a
gate may reasonably want it separated.

**Q4 (calibration).** `CANDIDATE_SCORE_FLOOR = 0.20` is calibrated on one
66-record corpus. Is a named constant with its measurement in the
docstring sufficient, or should the composer emit a telemetry note when a
run produces zero candidates across the whole batch (which would be the
first signal the calibration has drifted)? This spec chose the constant
alone, to keep the unit at its declared size.

**Q5 (doctrine size).** The rewrite grows a file that is injected into
every worker prompt and every analyst invocation (25,390 B today; the gate
procedure plausibly adds 40–60%). A13 pins a 64 KiB ceiling. Is a ceiling
the right instrument, or should the doctrine be split into a core the
prompt carries and an appendix the analyst may `Read` on demand? This spec
chose the ceiling: a split doctrine is a forked doctrine waiting to
happen, and the "one file, three loaders" pin (`analyst.py:20-24`) is
load-bearing.

---

## 11. Revision history

- **r1, 2026-08-06** — first draft, for the blind spec gate. Written
  against merged `U-marker`/`U-marker-ui`/`U-analyst`/`U-schema`/`U-reach`/
  `U-recur`/`U-pathed`/`U-grad-ui`; `U-table` spec in flight with no draft
  on disk (§8). Carries S-26's flip and migration surface, S-23's tier
  reordering, S-24's search-only sharpening, campaign §6 items 5 and 6,
  and FW-43's two stale-premise repairs.
