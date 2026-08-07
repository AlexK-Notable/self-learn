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
`plugins/self-learn/skills/self-learn/references/card-sections.yaml`
(**one existing entry's `instruction` text**, §3.8-D10 — no new key),
`plugins/self-learn/cli/src/self_learn/ledger_ops.py` (**the S-26 flip
only** — one constant and one guard, §3.9), and the CLI test suite.
Anything else is out of scope and is reported, not edited (campaign §3
builder prompt).*

*The `card-sections.yaml` entry is an r2 addition, declared rather than
slipped in: D10's card obligation has to live in the registry, because the
registry is where the section's generation prompt lives and §0.4 forbids a
second copy in the doctrine. The file is **uncontended** — no in-flight
unit lists it (`U-table`: `gates.py`/`ledger_ops.py`/`selfcheck.py`;
`U-demand-user`: `verbs.py`/`ui/models.py`; `U-pointer`:
`compilers.py`/`verbs.py`; `U-refresh`: `verbs.py`/`cli.py`) — and it
ships beside the doctrine, loaded by the same three consumers.*

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
5. **`U-table` is cited by section and rule id, never by line number.**
   Its draft is *in flight* — measured mid-fold: line numbers this spec
   recorded from it in the morning pointed at different content hours
   later, because its author was editing it. Shipped code gets `file:line`
   (it is frozen at a commit); a live sibling draft gets `§3.3 R-SCOPE`,
   which survives its next revision. This is the same defect class as the
   ~208 stale citations, met one step earlier.

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

   Re-measured 2026-08-06 (r2 of this spec) against **D8's example
   record**, so the spec has one example record and not two:

   | `t2.evidence` | result |
   |---|---|
   | `"record names no paths"` (r2's phrase) | **REFUSED** — *"is not contained in the record it claims to quote"* |
   | the record's own Trigger line, verbatim (D8) | ACCEPTED |
   | a near-miss paraphrase of that line (`…for the human` for `…for the user`) | **REFUSED** — same message |
   | `"subagen"` (a true 7-char quote of another record) | REFUSED — under the `_QUOTE_MIN_CHARS` (8) floor |
   | r2's phrase again, with `record_text=None` | ACCEPTED — **positive control: the refusal is containment, not shape** |
   | the near-miss paraphrase, with `record_text=None` | ACCEPTED — same control, second leg |

   A doctrine that repeats r2's phrasing would make the worker emit
   proposals that `proposal_info` (`ledger_ops.py:1809-1820`) rejects on
   the eligibility hot path, so every such record would be re-analyzed on
   every run, forever, with no visible error. **The doctrine must instruct
   verbatim quotes on `no` answers too** — and its own exemplar must obey
   that instruction, which r1's did not (§11, gate BLOCKER 1).

2. **PATHED has no routable surface at skill scope**, so S-23's "at every
   scope" cannot be transcribed as a rule. `_resolve_rules_target` refuses
   any scope outside `{user, project}` (`verbs.py:811-816`, the P-A13
   deferral). **This does not mean T2 goes unasked there** — that was r1's
   answer and it is wrong. `U-table`'s **R-SCOPE** rule (its §3.3, with
   the two-hole analysis at §3.4 and the r2 contradiction at §8-C5) makes a
   skill-scope `t2.answer: yes` derive `PATHED` and render
   `recommendation: defer` + `flags: [no-cheap-surface]` — the same honest
   degradation the user-scope DEMAND corner already gets. U-table's §8-Q1
   rejects the doctrine-side branch in one sentence this spec adopts
   verbatim as its reason: *"a doctrine that stops asking a question is how
   the monoculture was built the first time."* §3.8-D2/D3/D4 carry it.

3. **r2's two "transition rules" (§1.6) are half-dead.** The
   PATHED-before-B10 rule is dead — `U-pathed` merged (`63f5962`), and
   `U-table`'s R-PATHED now renders `recommendation: route`, so a doctrine
   still teaching "defer + `pathed-unbuilt`" would make **every** PATHED
   proposal refuse (its §8-C2). The flag stays valid in the closed set
   (`ledger_ops.py:98-107`) and simply goes unmentioned in the doctrine —
   D7/D11 state the positive rule rather than naming a flag a system
   prompt would then be able to reach for. The
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
| A new `card-sections.yaml` **section key** for the trace | nobody — deliberately | §7-R7: the human-facing render rides the EXISTING required `discuss` section, whose `instruction` this unit edits (§3.8-D10). A new *key* is a new surface with its own test obligations, and campaign §9 names "a unit absorbing an adjacent feature" as a way this loop fails |
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
(ruamel is already a dependency — `ledger_ops.py:156-161` constructs a
`YAML(typ="rt")` for the ledger's round-tripping needs; the roster wants
the **safe** loader, which is a different constructor in the same
library, not the one that citation shows): **41 of 43** yield a usable
description that way, 32/43 by line grab.

**The other two are the reason A3 exists, and they are live today** (F14).
`YAML(typ="safe")` raises `ScannerError: mapping values are not allowed
here` on two shipped skills — an unquoted `: ` inside a plain scalar in
`<skills-root>/plugins/home-network/skills/home-network/SKILL.md`
and `~/.claude/skills/firecrawl-build/SKILL.md`. So the render-never-drop
rule (A3) is not a defensive hypothetical: **it fires on ~5% of this
host's roster on day one**, and a build that `continue`s past a parse
error ships a roster that silently omits two installed skills — including
one whose subject (`home-network`) is exactly the kind of thing T3 exists
to find.

**r1 claimed 43/43 here, and the claim came from a fail-open in the
probe itself.** The r1 measurement's parse helper returned the *exception
message* as the description on `YAMLError`, and its "is the description
usable?" test was a truthiness check — so a non-empty error string counted
as a usable description. That is the same defect shape this section is
about, committed inside the measurement that documents it. Recorded rather
than quietly corrected: a probe needs its own positive control (assert on
a file known to fail), and this one had none.

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
roster T3 is judged against.

**Roster size, and why the figure is format-dependent** (N3). Measured for
the 43-entry roster under *this spec's* row format — `- <name>: <desc>`,
no routability marker: 19,399 B uncapped, 12,612 B at 300, **9,376 B at
200**. The gate re-measured under the marker-carrying format this section
actually pins (`- <name> [routable]: <desc>`) and got 21,348 / 14,599 /
11,385 B — a ~2 KB offset that is entirely the markers. Both are correct;
the oracle is the row format, and the builder should expect the
marker-carrying figures. Campaign §5's rule applies to spec authors too:
state the oracle's own configuration, or the number is a coincidence
someone wrote down. Neither figure changes any decision here — §3.5's
64 KiB ceiling has ~2.5× headroom over the larger one.

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
(`cli/tests/test_worker.py:1077-1094`, which asserts the `§9`/`§10`
references on the assembled prompt; `:845-847` pins template *tokens* —
`destination section`, `contradicts`, and the absence of `existing canon`
— not the §-references, N2).

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
registry 4,599 B, roster **11,385 B** (the capped, marker-carrying figure
the composer actually emits — §3.2). §4-A13 pins a test that the composed
single-record prompt and the doctrine text each stay under 64 KiB — half
the cap, so growth is caught before it truncates.

### 3.6 The roster-sha honesty check

X3 today proves only that the model wrote *a* well-shaped sha or admitted
`unavailable` (`ledger_ops.py:1046-1068`); a fabricated
`sha256:aaaaaaaaaaaa` passes. Both producers hold the real value in
memory, so both close it.

**The check has two legs, not one, and r1 specified only the first**
(F8). X3 accepts `roster_sha: "unavailable"` whenever `t3.answer: no` and
`flags` contains `evidence-gap` — with **no reference to whether a roster
existed**. So a model that never reads a perfectly good roster can write
the three tokens `unavailable` / `no` / `evidence-gap` and satisfy every
check in the system, on every record, forever. That is not a hypothetical
laziness mode: it is the cheapest possible output, it lands everything on
the cheap shelf with an evidence-gap flag, and it is **verbatim the
failure Checkpoint C is instructed to press hardest on** (campaign §4:
*"did we build a new monoculture at the other end?"* — r2's own honest
failure mode). So:

> **Leg A — no fabricated sha.** A trace whose `t3.roster_sha` is a
> well-shaped sha that is not the run's roster sha is refused.
> **Leg B — no false degradation.** A trace claiming `unavailable` when
> the run's roster WAS available is refused, with a message naming the
> real sha. `unavailable` is legal only when the composer itself returned
> `ROSTER_UNAVAILABLE`.

Leg B is what makes the roster ingredient load-bearing rather than
optional. Both legs live at the same two sites:

- **Worker.** `run()` threads the `Roster` from `compose_batch_prompt`
  (`worker.py:1370`) through `_harvest` (`worker.py:1420`) into
  `_validate_written` (`worker.py:880-942`). A proposal failing either leg
  is **deleted and logged** under the existing unattended policy
  (`worker.py:937-940`) — no new policy, one more `ProposalError` raised
  inside the existing `try`.
- **Analyst.** `analyze()` compares the parsed proposal's
  `gates.t3.roster_sha` against the `Roster` it composed and raises
  `AnalystError` on mismatch — the caller then captures the record as a
  normal pending teach and the lesson is never lost (`analyst.py:33-38`).

Deliberately **not** enforced in `_validate_gates`: it performs no
filesystem or run-context I/O by design (U-schema S4,
`ledger_ops.py:826-829`), and the roster is run-scoped state a validator
reading a file on disk months later cannot have.

### 3.7 Containment — and derivation — at the three sites (in two files) this unit now owns

U-schema names six call sites where `validate_proposal` is invoked
positionally, so containment is off, and assigns each to "whichever unit
next holds that file" (`u-schema-decision-trace-spec.md:810-834`). This
unit holds `worker.py` and `analyst.py`; it closes the three sites in
those two files and touches none of the three in `verbs.py`.

**`U-table` hands the same landing site a second keyword** (F1). Its
§8-H1 (`u-table §8-H1`) asks this unit to wire
`worker.py:927` with **`scope=` as well as `record_text=`**, because
`_validate_derivation` runs iff `scope` is supplied
(`u-table §3.5`). Without it, the worker lands
its own output unchecked against the table, and `U-table` §7.4's disclosed
re-analysis loop stays open in exactly the shape it disclosed: a trace
`worker.py:927` accepts and `proposal_info` then refuses makes the record
permanently unanalyzed, silently, forever. Discharging half the handoff
would leave the loop and look like closure — so `scope=` is not optional
here.

| site | today | after |
|---|---|---|
| `worker._validate_written` (`worker.py:927`) | `validate_proposal(data)` | `validate_proposal(data, record_text=Record.from_path(rpath).to_text(), scope=<record>.scope)` |
| `worker.fast_status` (`worker.py:1282`) | `validate_proposal(dict(pdata))` | `record_text=text` — the whole record file it already read at `worker.py:1232` (measured equivalent to `to_text()` on all 35 live records, §3.5). **No `scope=`**: this path never parses a `Record`, and reading `scope` out of its hand-rolled frontmatter map would be a second scope derivation |
| `analyst.analyze` (`analyst.py:244`) | positional | `record_text=record.to_text()`, `scope=record.scope` — the record is the function's own argument |

**The two-line swap `U-table` N1 reports is part of this change**
(`u-table §8-N1`): at `worker.py:927-930` the
validation runs *before* `rpath` is computed, so the record the new
keywords need does not exist yet at the call. Move the `rpath` resolution
(and its `is_file()` refusal) **above** the `validate_proposal` call, then
pass both keywords. A builder who adds the keywords without the swap gets
a `NameError`, which is the good failure; a builder who "fixes" it by
re-reading the record file separately has created a second read of the
same bytes and a second place for them to diverge.

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
tests assert doctrine content and prompt section numbers — **three of
them**, not two (N2): `cli/tests/test_worker.py:850-862` (lint tokens),
`:864-873` (contradiction-check tokens), `:1077-1094` (the assembled
prompt, including the literal `§9`/`§10`). §§5, 5.1,
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
| PATHED | **no routable surface** (`verbs.py:811-816`) → R-SCOPE | `<host>/.claude/rules/<topic>.md` | `<user>/.claude/rules/<topic>.md` |
| SKILL | `SKILL.md` (`verbs.py:930-945`) | — | — |
| DEMAND | `references/LEARNINGS.md` (`verbs.py:1039-1041`) | `<host>/references/…` (`:1042-1044`) | **no routable surface** (`:1045-1050`, S-23) → R-SCOPE |
| ALWAYS | skills-root `CLAUDE.md` (`verbs.py:979-991`) | `<host>/CLAUDE.md` (`:973-978`) | `~/.claude/CLAUDE.md` (`:964-972`) |

**"No routable surface" is a rendering instruction, not a silence
instruction.** Both corners are the same rule — `U-table`'s **R-SCOPE**
(`u-table §3.3 R-SCOPE`): the gate is still asked, the
outcome is still derived honestly, and the *rendering* degrades to
`recommendation: defer` + `flags: [no-cheap-surface]` with the honest
destination left recorded. The table above must carry that sentence, or a
reader takes "no routable surface" as licence to answer the gate `no`.

**D2 — §2 is replaced by the gate procedure.** Ordered G0 → T1 → T2 → T3
(→T3a) → T-N → T4 → E1 → outcome, one subsection each, and each
subsection states four things: *what it asks*, *which prompt ingredient
answers it*, *what evidence the answer requires and from which source*,
and *what to answer when the ingredient is unavailable*. The gate names,
answer domains and required-ness are U-schema's Schema-1
(`u-schema-decision-trace-spec.md:216-296`) — **cited, not restated**, so
the two cannot drift. Six rules the doctrine must add on top:

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
- **Every gate is answered on its merits at every scope — including where
  the winning tier has no routable surface** (B2/R-SCOPE, §3.8-D1). The
  analyst never answers a gate `no` because routing it would fail; that
  failure is the *rendering's* job to express, and hiding it in a gate
  answer is how the monoculture was built the first time
  (`u-table §8-Q1`, §8-Q1).
- **`recommendation` is DERIVED, not chosen** (F5; `U-table` §3.3, *"a
  pure function of (outcome, scope)"*,
  `u-table §3.3`). The analyst writes the value
  the table implies; it does not express a preference there. **The one
  channel for "hold this" is `g0.defer.answer: yes`** — which derives
  `DEFER` and therefore `recommendation: defer` through R-FALL. After
  `U-table` merges, any other analyst-chosen `defer` is a refusal.
- **A `hook` proposal names its fallback in `alternates`** (F3; R-HOOK,
  `u-table §3.3 R-HOOK`): `alternates` must contain the
  destination the load class would have rendered, so the human can take
  the cheaper surface without a re-analysis. This is also the existing §7
  rule ("always include a routable alternate") given a machine-checkable
  form.

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

**Both sharpenings are about the LESSON, never about the scope.** At
skill scope, where PATHED has no routable surface, T2 is asked and
answered exactly as it is anywhere else; a `yes` there derives `PATHED`
and renders `defer` + `no-cheap-surface` (D1, R-SCOPE). The doctrine must
say this in the T2 section itself, because that is where an analyst
looking for permission to skip the question will be reading. Two things
follow that the prose must make explicit: the skill-scope `defer` is the
system reporting a **capability gap** (P-A13 is open, not closed), and it
is therefore not the same event as a lesson the analyst judged unripe.

**D4 — §3 becomes the tier model; the narrowest-surface bias survives as
the within-tier tiebreak only.** Content, with authority:

- PATHED is the primary cheap tier **where it has a surface** (S-23 (1)
  and (2)); at skill scope the tier with a surface is DEMAND (D1's table),
  and a PATHED verdict there degrades rather than disappears (R-SCOPE).
- **PATHED renders `recommendation: route`** (F2; `U-table` R-PATHED,
  `u-table §3.3 R-PATHED`, and its §8-C2: r2 §1.6's
  "defer + `pathed-unbuilt`" rule died when `U-pathed` merged at
  `63f5962`). The doctrine must state the positive rule, not merely omit
  the dead one — absence of the wrong instruction is not presence of the
  right one, and PATHED is the tier S-23 promoted to primary.
- DEMAND shrinks to lessons that are genuinely not file-scoped (S-23 (1)).
- ALWAYS is the expensive tier and is reached only when the record's own
  evidence argues for it (r2 §3's default: no silence marker, no cost
  statement, no caught-immediately statement ⇒ `INDETERMINATE` ⇒ the cheap
  branch).
- **Two corners have no routable surface, and they take ONE rule.** DEMAND
  at user scope and PATHED at skill scope both render
  `recommendation: defer` + flag `no-cheap-surface`, with the honest
  destination recorded — and **never a silent upgrade to ALWAYS**, which
  is the monoculture rebuilt (r2 §1.6's transition rule for the first
  corner, promoted to a standing rule by S-23 (2); generalised to both by
  `U-table`'s R-SCOPE, which names the second corner r2 never did).
  Before deferring, the analyst asks whether
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

**Say plainly where that re-entry bites, or it is prose that cannot move
an outcome — which is campaign §6 item 6's own failure mode** (N9). There
is no Table-1 row for "recurred at ALWAYS": the table reads `e1` only
through `_e1_promote`, which promotes *toward* the loaded tier. The
re-entry therefore acts **entirely through the analyst's `t1` answers** —
it instructs the analyst to attempt the guard construction again, with the
recurrence as new evidence of `cost_bearing`, rather than to re-run T4 and
land on the same shelf. If that attempt succeeds the outcome changes to
`HOOK` by the ordinary table; if it fails, nothing changes and the record
stays where it was. The doctrine must state that mechanism, because a
reader who takes "re-enters at T1" as a table rule will look for a row
that does not exist.

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
card. §5 must also carry the three derived-field rules D2 and D4 state —
`recommendation` is derived (F5), `PATHED` renders `route` (F2), a `hook`
proposal's `alternates` names its load-class fallback (F3) — because §5 is
the section an analyst re-reads while writing the YAML, and a rule that
lives only in the procedure section is a rule the writer has already
scrolled past.

**D8 — §5 ships a worked example that is a RECORD AND A TRACE, both
executed.** *(This is gate BLOCKER 1. r1 shipped the trace alone, and its
exemplar quote was a paraphrase of a real record — the shipped containment
check refuses it. A system prompt's exemplar is its strongest instruction,
so r1's doctrine would have taught, by example, exactly what §1.3 item 1,
D2 bullet 1 and A18 forbid.)*

Three requirements, all load-bearing:

1. **The doctrine ships the example record beside the trace.** Without a
   record, the exemplar's quotes cannot be verbatim *from* anything, and
   A19 has no `record_text=` to pass.
2. **The example record is SYNTHETIC** — invented for the doctrine, with
   no ledger provenance. `routing-doctrine.md` ships in a **public** repo
   (S-19) and the ledger is deliberately severed from it; quoting a real
   lesson into the doctrine would publish ledger content through the back
   door. `lrn-00000000` is its id by convention — an all-zero id is one no
   generator has produced and no reader will mistake for a real lesson.
   **It is a convention, not a guarantee**: `00000000` is a legal 8-hex id
   and nothing refuses it at generation. Adding an exclusion to id
   generation for the sake of an example would be a real rule bought with
   a documentation problem, and is out of scope.
3. **Every quote in the trace is verbatim from that record**, and the
   **whole proposal** — not just the trace — was executed against the
   shipped `validate_proposal` before landing here (§9, 2026-08-06). A
   builder substituting a different pair must execute it the same way and
   say so.

The pair below is the executed one. The record:

```markdown
---
id: lrn-00000000
type: behavior
kind: surface-rule
scope: user
source: teach
status: pending
created_at: '2026-08-06T00:00:00Z'
sightings: 1
---

## Trigger
About to summarise a long command's output for the user instead of showing the tail

## Instruction
Show the last lines verbatim before summarising, because a summary of an
error message drops the one token the user needs to search for.
```

and its proposal — **note both halves of the R-SCOPE rendering**: the
record is user scope and the outcome is `DEMAND`, so `destination` is the
outcome's honest target `reference` **and** the recommendation degrades to
`defer` + `no-cheap-surface`. The `destination` line is not decoration
(r3 D4): the degraded corner is exactly where a model reasons "it can't go
on the cheap shelf here" and writes `claude-md`, which is the monoculture
rebuilt. Measured against the shipped validator: an exemplar with
`destination` **removed** is refused loudly
(*"destination must be one of …, got None"*), but one with `destination:
claude-md` is **ACCEPTED today** — Render-1's derivation check is
`U-table`'s and has not merged yet — so until then the exemplar is the
only thing teaching the right answer:

```yaml
destination: reference
alternates: [claude-md]
recommendation: defer
flags: [no-cheap-surface]
gates:
  g0:
    reject: {answer: no}
    defer:  {answer: no}
    canon:  {answer: no}
  t1:
    attempted: true
    field_shaped:
      answer: no
      evidence: "About to summarise a long command's output for the user instead of showing the tail"
    separable:    {answer: null}
    cost_bearing: {answer: null}
  t2:
    answer: no
    evidence: "About to summarise a long command's output for the user instead of showing the tail"
    match_path: null
  t3: {answer: no, owner: null, scan_terms: [summarise, output], roster_sha: "sha256:0123456789ab"}
  t3a: null
  t4:
    depth_behind_rule: {answer: no, evidence: null}
    conduct_mode:      {answer: no, evidence: null}
    fs: {verdict: INDETERMINATE, evidence: null}
  tn: {answer: no, terms: [], members: [], proposed_name: null}
  e1: {sightings: 1, post_demand_recurrence: false}
  outcome: DEMAND
```

**The doctrine must add one sentence beside it** so the exemplar does not
teach that DEMAND always defers: *at project or skill scope the same
outcome renders `recommendation: route` with `flags: []`; this example
defers because `reference` has no user-scope surface (S-23).*

**D9 — §7 (boundaries) gains four MUST NOTs**, each phrased as an
instruction to the analyst: never claim a scan you did not perform (the
roster in the prompt is the only roster you have); never name a path you
did not receive in the path roster or read at an absolute path; never
write a quote you have not copied from the source named for that leg; and
never hand-write a decision trace for a record you did not analyze — a
record whose gates were never evaluated has **no proposal**, not an
invented one (S-26's honesty constraint, §3.10).

**D10 — §8 (the card contract) gains one sentence**: the `discuss`
section must carry, in plain words, (a) which shelf the trace chose,
(b) the verbatim quote that unlocked it, and (c) **when the recommendation
is `defer`, whether the surface was missing or the analyst judged the
lesson unripe.** (a) and (b) are campaign §7's quote-relevance row plus
U-schema's §3.4 boundary (*"the review card must surface the quote
verbatim, or the human's check has nothing to look at"*); (c) is
`U-table`'s H5 (`u-table §8-H5`): a proposal
deferred by R-SCOPE *looks identical on a destination-only card* to one
the analyst chose to defer, and those call for opposite human moves.
All three ride a section the registry already requires for routing
proposals (`card-sections.yaml`, `discuss`, `required: routing`) rather
than a new registry key (§2, §7-R7).

**Which enumeration wins, stated because §0.4 forbids two** (N10):
`card-sections.yaml`'s `discuss.instruction` is **the** generation prompt
for that section; this D10 sentence is an *addition to* that instruction,
and the builder lands it by editing the registry entry — not by writing a
competing instruction into the doctrine. The doctrine's §8 keeps its
existing role: it says the registry is authoritative and must be loaded
(`routing-doctrine.md:303-312`). If the two ever disagree, the registry
wins, because it is what the surfaces render from.

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
                "— this proposal predates the decision trace (S-26). The next "
                "worker run re-analyzes it; `self-learn worker kick` starts "
                "one. To route it as it stands, pass --dest. A trace is never "
                "hand-written."
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
| `route --dest <d>` — **the form the UI sends whenever a proposal exists** | resolves | **still resolves** (the proposal is never read) |

Three things follow, and the spec states them rather than leaving them to
be discovered:

1. **Pending records self-migrate.** A legacy proposal becomes
   `is_unanalyzed: True`, so the next worker run re-proposes it *with* a
   trace, and the model — not a migration script — produces the gate
   answers. Nothing is fabricated because nothing is conformed in place.
2. **The human's review flow is not wedged — stated as the conditional it
   actually is** (F15). `routes.py:124-130`'s docstring says *"This app's
   `route` argv always carries an explicit `dest`"*, but the code it
   documents is conditional: `argv = ["route", record_id]` then
   `if dest: argv += ["--dest", dest]` (`routes.py:131-134`). The honest
   invariant is **"whenever a proposal exists"** — the hidden field starts
   at the analyst's own scope-corrected destination and never goes empty
   *once there is one*. That covers every legacy card, which is the case
   this section is about, so the conclusion holds: approving a pre-schema
   card still works, exactly as (un)checked as yesterday. **But the
   uncovered branch is not empty**, and r1 wrote it as if it were.

   **What happens in the uncovered branch, measured.** With no `dest`, the
   flip turns the CLI's response from a resolved destination into a
   `ProposalError`. The UI's `_humanize_verb_error` rewrites exactly one
   failure — `verb == "route"` **and** `NO_PROPOSAL_MARKER in stderr`
   (`routes.py:1610-1618`) — and a `ProposalError` carries no such marker,
   so the humanizer returns `None` and the **raw validator text lands in
   the error strip**. That makes the message's wording a UI string, which
   changes what it may say:

   > **The remedy named in the refusal must exist at merge time.** r1's
   > message said *"re-analyze the record (`self-learn proposal refresh
   > <id>`)"* — a verb that **does not exist until Wave 4's `U-refresh`**
   > (`cli.py:521-525` registers `proposal validate` and nothing else;
   > `:1737-1739` prints the usage line for any other subcommand). Telling
   > a human to run a command that argparse rejects is worse than telling
   > them nothing. The message this unit ships names what exists **today**:
   > *"this proposal predates the decision trace (S-26) — the next worker
   > run re-analyzes it; `self-learn worker kick` starts one. To route it
   > as it stands, pass `--dest`."* `worker kick` and `worker run` are both
   > registered (`cli.py:365-368`). When `U-refresh` lands, it may add its
   > verb to this message; the message must never be the only place the
   > verb is assumed to exist.
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

**A3 — an unparseable frontmatter is rendered, never dropped, and the
fixture is shaped like the real failure.** A `SKILL.md` whose frontmatter
carries an **unquoted `: ` inside a plain scalar** — e.g.
`description: Use when: the user asks` — renders a row carrying the
directory name and an explicit marker, and `routable + visible_only`
counts it. Positive control in the same test: a well-formed sibling skill
renders its description normally.
*Absent/broken: a build that `continue`s past the parse error renders one
fewer row and the count assertion fails — which is the point, because a
silently missing skill is an invisible hole in T3's evidence.*

**Use that shape, not "a corrupt leading block"** (F14): the unquoted-`: `
scalar is what `YAML(typ="safe")` actually chokes on across this host's
roster — `ScannerError: mapping values are not allowed here` on
`plugins/home-network/skills/home-network/SKILL.md` and
`~/.claude/skills/firecrawl-build/SKILL.md`. **A3 fires on ~5% of the live
roster on day one**, so it is a live-behaviour criterion, not a defensive
one, and a fixture built from an invented corruption might not reproduce
the parser path the real files take.

**A4 — the unavailable path is real and is coupled to X3.** With no
registered skills root and an empty claude dir, `Roster.sha ==
ledger_ops.ROSTER_UNAVAILABLE` and the text names the reason. **And** a
proposal carrying `t3.roster_sha: "unavailable"` with `t3.answer: yes` is
refused by the shipped validator, while the same trace with `answer: no` +
`flags: [evidence-gap]` is accepted.
*Absent/broken: a build that returns an empty string with a real sha
passes the first leg and fails the second — so both legs are required.
**Leg 2 cannot fail for THIS build** — it exercises U-schema's shipped X3
(`ledger_ops.py:1054-1068`), not anything this unit writes. It is kept as
a regression guard on the coupling, and §9 does not count it among the
criteria that would otherwise be fail-open (N1). The leg that can fail is
leg 1, and A23's Leg B is where the honesty of `unavailable` is actually
enforced.*

**A5 — the sha covers the rendered text.** `Roster.sha ==
sha_anchor(Roster.text)` for a non-empty roster, and mutating one
character of any description changes the sha.
*Absent/broken: a sha derived from paths or mtimes is stable across the
description mutation and fails the second leg.*

### B. Cluster candidates

**A6 — the ranking, the floor and the cap, on a fixture that
discriminates.** The pool must contain, by construction:

(i) two records whose titles share a distinctive rare term;
(ii) a record with **at least six** other records scoring above the floor
     against it;
(iii) a record sharing no tokens with anything;
(iv) **a deliberate score tie** — two candidates whose scores against the
     same record are equal, with the *lower* record id ranked second by a
     score-only sort.

Assertions: for (i) the first row is the sibling, score ≥ 0.20; for (ii)
**exactly 5 rows**, and the same pool with the cap removed yields **6 or
more** — the count is asserted as an equality, not a bound; for (iii) the
literal line `(no cluster candidates above the 0.20 floor)`.
*Absent/broken: "at most 5 rows and none below the floor" — r1's wording —
is satisfied by ZERO rows, so a build that returns nothing passes it and
M7 (remove the cap) survives (F9). The equality plus the cap-removed
control is what makes the cap load-bearing.*

**A7 — determinism, exercised on the tie.** Two calls on the same pool
return byte-identical blocks, including under a shuffled input order,
**and the two tied candidates from A6 (iv) appear in record-id order**.
*Absent/broken: `sorted()` is stable, so a score-only sort differs from a
score-then-id sort ONLY on a tie — without A6 (iv) in the pool, M8 changes
no output and this criterion cannot see it (F10).*

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

**A11 — both execution paths compose the same per-record block.** Assert
in two steps, because both prompt builders return whole prompts and an
extraction step invented by the test would itself be untested (N8):
(a) call `compose_record_block` directly for the record and hold the
result; (b) assert that exact string is `in` the prompt from
`compose_batch_prompt` for a one-record batch **and** `in` the prompt from
`compose_single_prompt` for that record.
*Absent/broken: two divergent implementations differ and fail — and the
campaign's open question ("do the worker and the one-shot analyst behave
the same?") would otherwise stay open by construction. A test that
re-derives the block by slicing the prompt would pass on a build whose two
paths differ, because the slice would be taken from whichever prompt it
was written against.*

**A12 — the worker prompt still carries what it carried, shows the text
containment checks, and instructs the producer.** The assembled prompt
contains the real doctrine's `trigger_recognizable`, `why_present`, `§9`,
`§10`, the card registry, and the rejected-proposal digest, **and** now
contains the roster sha line, a candidate block and a path roster. **And**
for a record whose file bytes differ from `Record.to_text()` (a fixture
with frontmatter ruamel re-renders — e.g. a quoted scalar), the block
contains `to_text()`, not the raw bytes. **And** the prompt header carries
the gate-output contract — matched on the three key names `gates`,
`flags`, `recommendation` appearing in the instruction header, not merely
inside the interpolated doctrine.
*Absent/broken: a rewrite that drops the digest or the registry fails the
first half; a composer that forgets an ingredient fails the second; a
composer that interpolates `entry.path.read_text()` passes both halves on
every record in the live corpus (measured 35/35 identical) and fails only
the third leg — which is why that fixture must be constructed to differ,
not sampled from the ledger. The producer-instruction leg fails on a build
that flips `TRACE_REQUIRED` without telling the model what to emit.*

**Its first half cannot fail for this build** (N1): `test_worker.py:1077-1094`
already asserts the doctrine tokens and `§9`/`§10` on the real assembled
prompt. It is restated here as the regression guard for a rewrite that
drops them, and §9 does not count it as a discriminating criterion.

**A12b — a trace-less proposal is deleted at landing, and a trace-carrying
one lands** (F7). End to end through `worker.run()` with the `claude`
shim: (a) the shim writes a proposal with no `gates`/`flags`/
`recommendation` → after the run the proposal file is **gone**, the run
journal carries the "invalid worker output … deleted" line
(`worker.py:938`), and the record is **still in `pending/`**; (b) control,
same run shape, shim writes a complete trace → the proposal file **exists**
and `is_unanalyzed` is `False`.
*Absent/broken: without leg (b) the criterion passes on a build where the
worker deletes EVERY proposal — which is precisely the wedge S-26 names
(`TRACE_REQUIRED` on, producer not instructed, queue silently yields
nothing forever). Leg (a) alone cannot tell "the flip works" from "the
pipeline is dead".*

**A13 — the argv-bound prompts stay under half the 128 KiB cap.** The
doctrine text and the composed single-record prompt for a worst-case
record (200-line record, 43-entry roster, 5 candidates) are each < 64 KiB.
*Absent/broken: a doctrine that grows past the ceiling fails here rather
than truncating an analyst invocation in production. **This is an alarm,
not a control** (N1): today's largest composed input is the **11,385 B**
roster the composer emits — the 21,348 B figure is the *uncapped* roster,
which no prompt ever carries — so a worst-case single-record prompt sits
around 20 KB against a 64 KiB ceiling, and it cannot fail for this
build. It is
here to fire on a later doctrine that grows unattended, and §9 does not
count it among the discriminating criteria.*

### D. The doctrine

Assertions are made against the **real shipped file**
(`worker.package_skill_refs() / "routing-doctrine.md"`), in the CLI suite,
beside the **three** tests that already do this (`test_worker.py:850-862`,
`:864-873`, `:1077-1094`).

**A14 — the gate sequence is present and ordered.** The file contains the
gate labels `G0`, `T1`, `T2`, `T3`, `T3a`, `T-N`, `T4`, `E1`, and their
first occurrences appear in that order. **Match on word boundaries**
(`re.search(r"\bT3\b", …)`), not substrings: `T3` is a substring of `T3a`,
so a naive `text.index("T3")` finds whichever comes first and an ordering
leg built on it can pass while the sections are transposed (N4).
*Absent/broken: a doctrine that mentions the gates in prose but out of
order fails the ordering leg; one that omits a gate fails presence.*

**A15 — the two T2 sharpenings are present, each with its authority, and
T2 is asked at every scope.** The T2 section contains the timing question
(matched on the exact tokens `first contact` and `Read`) and the
search-only question (`Grep`, `Glob`), the file cites `S-24`, **and** the
T2 section states that a skill-scope `yes` renders `defer` +
`no-cheap-surface` rather than going unasked (matched on
`no-cheap-surface` within the T2 section's span).
*Absent/broken: a doctrine carrying only the r1 question ("does it only
matter for certain files?") fails the first two legs; r1's own answer —
"skill scope answers T2 no" — fails the third, which is what makes B2's
fix visible to a test rather than only to a reader.*

**A16 — the escalation rule is present with its evidence.** Matched on
exact tokens, the way A18 and A20 do (N5): the file contains **`guard`**
and **`prominence`** within the escalation paragraph's span (D5's rule is
"a GUARD, not more prose … not fixed by more prominence"), and the
literal record id **`lrn-ea833a5b`**.
*Absent/broken: a doctrine that says "escalate" without naming the guard,
or without the corpus evidence, fails. Without pinned tokens the criterion
is a reader's judgment call, which is not a test.*

**A17 — the tier model is stated per scope, and both no-surface corners
carry the R-SCOPE rendering.** Matched on exact tokens (N5), and **on the
phrasing D1 mandates, not on r1's**: the tier table's `PATHED` × skill
row and its `DEMAND` × user row each contain **`no routable surface`**;
the table or the sentence beneath it contains **`R-SCOPE`**; and the file
cites **`S-23`** for the user-scope corner.
*Absent/broken: a doctrine repeating "PATHED at every scope" carries
neither token and fails — the case §1.3 item 2 measured. **The token
matters more than it looks**: r1's A17 asserted the word "unavailable",
which D1 no longer permits, so a doctrine written exactly to D1 would have
failed this criterion spuriously and a builder would have "fixed" the
doctrine back toward the wording B2 exists to remove.*

**A18 — the trace is described as mandatory, the quote rule is
unambiguous, and the three derived-field rules are present.** Matched on
exact tokens, the way A20 does (N5): the file contains `gates`, `flags`
and `recommendation` in a required-ness sentence; the phrase
`including on` + `no` answers (the verbatim-on-negatives rule); a
statement that TARGET-sourced quotes are not machine-checked; **and** the
three F2/F3/F5 rules — `recommendation` described as derived (token:
`derived`), PATHED rendering `route`, and a `hook` proposal's
`alternates` carrying its fallback.
*Absent/broken: a doctrine that repeats r2's "record names no paths"
phrasing fails the quote leg (§4-A19 catches it a second way); one that
lets the analyst choose `recommendation` fails the derived leg, and would
otherwise ship a doctrine every `U-table` derivation check refuses.*

**A19 — the doctrine's worked example validates, and the check can fail.**
The example RECORD and the example PROPOSAL are both extracted from the
shipped doctrine (§3.8-D8 requires both). The record is written to a temp
file and parsed with `Record.from_path`; the proposal is parsed and passed
to **`validate_proposal(proposal, record_text=<that record>.to_text())`**
— the whole proposal, not the `gates` block alone, so the `destination`
and `alternates` D4 added are covered by the criterion that exists to
protect the exemplar — without error. **Positive control in the same
test**: the same call with one `evidence` value replaced by a near-miss
paraphrase must raise `ProposalError`.
*Absent/broken: r1's A19 could not fail — D8 shipped no record, so a
builder passes `record_text=None`, containment does not run, and even
r2's `"record names no paths"` is ACCEPTED (measured; that is what made
M22 inert as well). The control is what proves `record_text=` was
supplied at all: if it is `None`, the paraphrase leg passes and the test
fails.*

**A20 — the deletions, each with a positive control.** The file does not
contain `chezmoi`, does not contain `autosync`, does not contain
`pathed-unbuilt`, **and does not contain the old routing map** — asserted
on a §2-unique token, `behavior / anti-pattern`
(`routing-doctrine.md:29`), because that is the deletion whose survival
leaves two competing routing procedures in one system prompt (F12).
Positive control in the same test: it *does* contain the secret-scan rule
(match **case-insensitively**, or on the live capitalisation `No secrets`
— `routing-doctrine.md:128`; a case-sensitive `no secrets` fails
spuriously, N5), `S-23`, and `PATHED` — so an empty or truncated file
cannot pass.
*Absent/broken: a zero-byte doctrine passes every "does not contain"
assertion and fails every positive control — which is precisely why the
controls are in the same test.*

### E. The flip and the trace producers

**A21 — the flip refuses a trace-less proposal, key by key, and the flag
is what does it.** Four legs, because the guard names three keys and a
one-key test cannot see the other two (F6):
(a) no `gates`/`flags`/`recommendation` at all → refused, and
`is_unanalyzed` for its record becomes `True`;
(b) valid `gates` + `recommendation`, **`flags` absent** → refused;
(c) valid `gates` + `flags`, **`recommendation` absent** → refused;
(d) **positive control**: with `TRACE_REQUIRED` monkeypatched to `False`,
the (a) proposal is accepted and `is_unanalyzed` is `False`.
*Absent/broken: without (b) and (c), M15 ("require only `gates`") survives
and builder decision 8 — all three keys, `flags: []` written explicitly —
is pinned by nothing. Without (d), any unrelated schema error satisfies
the refusal legs.*

**A22 — no verb accepts gate values.** A search of the CLI argument
surface (`cli.py`) finds no `--gates`, `--set-gate`, `--outcome` or
`--flag` option. Positive control: the same search finds `--dest` and
`--note`, which do exist.
*Absent/broken: without the control the search passes on a typo'd path or
an empty file — the fail-open class `lrn-ea833a5b` names. **This criterion
is vacuously true today** (N1): none of those options exists, so it cannot
fail for this build. It is here as the standing guard on §3.10's MUST NOT
for when `U-refresh` adds verbs to this surface, and §9 does not count it
among the discriminating criteria.*

**A23 — roster-sha honesty, both legs, both paths.** *Leg A (fabricated
sha)*: (a) worker — a model-written proposal whose `gates.t3.roster_sha`
is well-shaped but is not the run's roster sha is deleted and logged, and
the record stays pending; (b) analyst — the same mismatch raises
`AnalystError`. *Leg B (false degradation, F8)*: with a **non-empty**
roster composed for the run, a proposal claiming
`roster_sha: "unavailable"` + `t3.answer: no` + `flags: [evidence-gap]` —
a trace the shipped X3 accepts — is (c) deleted by the worker and
(d) raises `AnalystError`. Positive control for both legs: the same
proposals carrying the run's real sha survive; and with the composer
genuinely returning `ROSTER_UNAVAILABLE` (no skills root, empty claude
dir), the `unavailable` trace **is** accepted.
*Absent/broken: a build with only Leg A passes (a)/(b) and fails (c)/(d) —
and a build with neither passes every X3-shaped assertion while letting a
model that never reads the roster satisfy the whole system, which is the
Checkpoint-C failure this unit is supposed to make impossible.*

**A24 — containment AND derivation are on at the sites this unit owns.**
A proposal carrying a fabricated RECORD quote is (a) deleted by
`_validate_written` rather than landed, (b) raises `AnalystError` from
`analyst.analyze`, and (c) makes `worker.fast_status` report the record as
NOT fresh — the third site (`worker.py:1282`), which nothing else asserts
(F11). **And** (d): once `U-table` has merged, a proposal whose
`gates.outcome` does not follow from its answers is deleted at landing —
the `scope=` half of `U-table`'s H1 (§3.7), asserted with a trace that is
containment-clean so only the derivation can be refusing it.
Positive control for each: the same proposal with a true quote and a
coherent outcome survives.
*Absent/broken: with containment off, the fabricated proposal lands and
only fails later, invisibly, as a permanently-unanalyzed record — so this
criterion must assert at the producer, not on the next `list`. Without
(c), removing `record_text=` from `fast_status` survives every other
criterion. Without (d), §3.7 discharges half of H1 and `U-table` §7.4's
loop stays open while looking closed.*

**A25 — suite and types.** Baselines **re-measured 2026-08-06 on master
`07d8c08`** (code-identical to this branch's base; the campaign §4a table
predates six merges and its numbers are stale — F13). CLI: **1379 passed,
5 skipped, 0 failed**, rc=0 captured unpiped; *there is no tolerated
failure in the CLI suite*. UI, run because the doctrine is compiled into
the pane (`ui/.../doctrine.py:79-126`): **1149 passed, 1 failed
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
— the one tolerated row), 0 skipped**, staged with **both**
`XDG_CACHE_HOME` and `PLAYWRIGHT_BROWSERS_PATH` exported (campaign §4a).
`pyright` clean. Both numbers were produced by this spec's author running
both suites, not copied from the playbook.
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
| M14 | Set `TRACE_REQUIRED = False` | A21a |
| M15 | Require only `gates`, not `flags`/`recommendation` | A21b + A21c |
| M16 | Skip the roster-sha comparison in `_validate_written` | A23a |
| M17 | Skip it in `analyst.analyze` | A23b |
| M18 | Revert `record_text=` to a positional call at `worker.py:927` | A24a |
| M19 | Revert it at `analyst.py:244` | A24b |
| M20 | Delete the T2 search-only paragraph from the doctrine | A15 |
| M21 | Restore the word "chezmoi" to the doctrine | A20 |
| M22 | Replace the doctrine's worked trace with r2's `"record names no paths"` t2 evidence | A19 |
| M23 | Interpolate `entry.path.read_text()` instead of `Record.to_text()` in the record block | A12 (third leg only) |
| M24 | Accept `ROSTER_UNAVAILABLE` unconditionally (drop Leg B) | A23c + A23d |
| M25 | Drop the producer instruction from the prompt header | A12 (fourth leg) |
| M26 | Drop `scope=` from the `worker.py:927` call, keeping `record_text=` | A24d |
| M27 | Revert `record_text=` at `worker.py:1282` (`fast_status`) | A24c |
| M28 | Reorder the doctrine so T3 precedes T2 (N6: r1 mutated only three doctrine criteria; A14/A16/A17/A18 had none) | A14 |
| M29 | Delete `lrn-ea833a5b` from the doctrine's escalation paragraph | A16 |
| M30 | Restore "PATHED at every scope" in place of the per-scope table | A17 |
| M31 | Delete "including on `no` answers" from the doctrine's quote rule | A18 |
| M32 | Delete the old `behavior / anti-pattern` routing map back into §2 | A20 |

**M12's limit, stated rather than papered over** (N7): a builder who
*copy-pastes* `compose_record_block`'s body into a second private function
for the analyst path still passes A11, because the two blocks are
byte-identical on the day they are written. A11 catches divergence, not
duplication. The guard against duplication is review, plus the fact that
§3.1 names one function and the campaign's own history (FW-48's
hand-copied `_canon_excerpt`) is the argument: this exact shape has drifted
in this exact file before. No criterion is invented to chase it.

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
3. **Description cap = 200 chars**; measured 11,385 B for the 43-entry
   roster in the pinned marker-carrying row format (14,599 at 300, 21,348
   uncapped) — see §3.2 on why the r1 figures were ~2 KB lower.
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

**R6 — a visible-only skill can still be a record's scope, and the
self-learn skill itself is one of them.** A ledger bucket named
`skills/<name>` for a skill outside the registered skills root will fail
at route time (`hosts.py:551-566`), regardless of what the trace says.
**This is live on this host, not hypothetical** (N12): the roster's
visible-only class includes **`self-learn`** —
`~/.claude/skills/self-learn` symlinks into the **product repo's** own
`plugins/self-learn/skills/self-learn`, which is not under the registered
skills root. So a lesson captured at scope
`skill:self-learn` — an entirely plausible thing for this project to
teach itself — would produce a bucket whose `skill-md` routes cannot
resolve. The roster's routability marker and D2's rule keep the *analyst*
from proposing it; they cannot repair a bucket that already exists.
Surfacing that is a `selfcheck` concern, not a composer one — recorded
here, not built.

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

## 8. Interface reconciliation with `U-table` — RESOLVED IN r2

**r1 wrote this section blind**: `U-table`'s spec was in flight
concurrently and no draft existed in `docs/specs/self-learn/drafts/`
(checked twice, 2026-08-06). **r2 reconciles it against the real draft**,
read at
`.claude/worktrees/agent-af31e5da100a196ef/docs/specs/self-learn/drafts/u-table-decision-table-spec.md`
for interface facts only. Each assumption below now carries its verdict.
Where the draft differs from what r1 assumed, **the table wins and this
spec changed** — the rule r1 stated for itself, applied.

1. **CONFIRMED — `gates.py` exposes the table as a pure module** and the
   ordering is r2 §1.5's (G0 exits, then HOOK, then the load class):
   Table-1, `u-table §3.1 Table-1`. The doctrine
   describes that ordering in prose (D2); the table remains the referee.
   *(One correction U-table found and this spec inherits: r2 §1.5's
   published table CRASHES on traces the shipped validator accepts —
   `TypeError`, 3,456 of 97,920 enumerated pairs, all `t2: no` / `t3: yes`
   / `tn ≠ yes` / `t4: null` at a mismatched scope, §8-C1. The doctrine
   must not reproduce r2's code listing as if it were the table.)*
2. **CONFIRMED — the check is wired inside `validate_proposal` in
   `ledger_ops.py`**, gated on a new keyword-only `scope=`
   (`u-table §3.5`). `ledger_ops.py` is
   therefore shared with this unit's flip (§3.9), so **`U-table` merges
   first and this unit rebases onto it.** The flip stays one constant plus
   one guard so the rebase is trivial.
3. **CONFIRMED, and r1 was incomplete.** Render-1
   (`u-table §3.3 Render-1`) matches r1's assumed map —
   **plus two rules r1 omitted and D2/D4/D7 now carry**: R-HOOK requires
   `alternates` to contain the load class's destination (F3), and
   `recommendation` is a **derived** field, not a chosen one (F5).
   *(Two more r2 corrections inherited: r2's "destination hook ⇔ t1 all
   yes" is not an iff — a `g0` leg fires first (§8-C3); and r2's NEW_SKILL
   `alternates` requirement is unsatisfiable because `tn.answer: yes`
   forces `t4: null` (§8-C4). The doctrine must teach neither.)*
4. **STILL OPEN, narrowed.** R-FALL requires `already_canon: true` for
   `GRADUATE` (`u-table §3.3 R-FALL`), so the coupling **is**
   enforced in that direction. What remains unstated is
   `already_canon_reason`, which the doctrine asks for and no rule
   requires. Doctrine-only; harmless; recorded so nobody reads the
   doctrine's request as a validator guarantee.
5. **CONFIRMED — R-SCOPE renders `defer` + `no-cheap-surface`**
   (`u-table §3.3 R-SCOPE`), exactly as D4 states.
   **This is the highest-consequence agreement in this list**: measured
   2026-08-06, the live queue is **32 records with deferred hidden — 29
   user, 3 project** (35 pending files: 31 user, 3 project, 1 skill). r1
   said "10 of 12", a figure inherited from r2's 2026-07-27 snapshot and
   stale by ~3× (F4). Nearly the whole queue is user scope, so a
   disagreement here would have refused nearly every proposal the first
   worker run wrote.
6. **CONFIRMED — `pathed-unbuilt` is vestigial, and the positive rule
   matters more than its absence** (F2). `U-table` §8-C2 states that r2's
   PATHED transition rule is dead and that **PATHED now renders
   `recommendation: route`**; a doctrine still teaching r2's "defer +
   `pathed-unbuilt`" would make **every** PATHED proposal refuse — on the
   tier S-23 promoted to primary. The flag stays valid in Set-F (U-schema
   owns that set); D4 states the positive rule and D11 keeps the token out
   of the file.
7. **RESOLVED AGAINST r1 — this was gate BLOCKER 2.** r1 offered two
   branches; `U-table` took the one r1 did not assume. R-SCOPE special-cases
   scope (`u-table §3.4`, §8-C5): a skill-scope
   `t2.answer: yes` derives `PATHED` and renders `defer` +
   `no-cheap-surface`. It rejects the doctrine-side branch explicitly
   (u-table §6-BD10). **D2/D3/D4 and A15 changed to match**, and A17's
   match tokens were re-pinned to D1's `no routable surface` phrasing (r3
   D2 — A16/A17 were byte-unchanged in r2, and A17's r1 wording would have
   failed against a compliant doctrine); r1's "keep skill-scope T2
   answering `no`" is withdrawn. The underlying
   question — close P-A13 or keep degrading — is `U-table`'s Q1 to route,
   not this unit's to decide.
8. **CONFIRMED as unowned.** `U-table` §7.1 leaves `e1` honesty to a
   future unit and its H4 requires **both halves together**
   (`u-table §8-H4`) — `sightings` against the
   record *and* `post_demand_recurrence` against `recurrences[]`, because
   splitting them "produces a check that reads as closure and is not." No
   composer change either way: the record's frontmatter is already in the
   prompt.

**One handoff flows the other way and is discharged in §3.7**: `U-table`'s
H1 asks this unit to wire `worker.py:927` with `record_text=` **and**
`scope=`, after swapping the two lines at `:927-928` (its N1). §3.7 and
A24(d) carry it; M26 mutates it.

---

## 9. Test obligations from campaign §5, and what was executed for this spec

**Every gate-shaped check ships with a positive control.** Applied at
A1–A25. **Which of them can actually fail for THIS build is a separate
question, and r1 answered it wrongly** (N1): the criteria that
discriminate are **A20** (doctrine deletions — a truncated file fails the
controls), **A21** (the flip — the `TRACE_REQUIRED=False` control is the
only thing that can distinguish the flip from an unrelated schema error),
**A19** (the worked example — with no `record_text=` it silently cannot
fail, which is what r1 shipped), and **A23 Leg B** (false degradation —
nothing else in the system refuses it). Three that are kept but are
*regression guards*, not discriminators, and are labelled so in place:
**A4 leg 2** (exercises U-schema's shipped X3 — r1 wrongly counted it),
**A12's first half** (duplicates `test_worker.py:1077-1094`), **A22**
(vacuously true until `U-refresh` adds verbs), and **A13** (an alarm with
~2.5× headroom).

**Never read an exit code downstream of a pipe.** Suite and pyright runs
capture `rc` unpiped or read the tool's own pass/fail line (campaign §5;
`lrn-ea833a5b`). Both baselines in A25 were captured that way for r2.

**Algorithms pinned in prose were executed** (campaign §5's rule, added
after a spec shipped an untested matcher). Probes are read-only against
copies, with `SELF_LEARN_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`,
`SELF_LEARN_CLAUDE_DIR` and `SELF_LEARN_TRANSCRIPTS_DIR` redirected to
`/tmp/u-composer-scratch/`, each asserting
`realpath(self_learn.__file__)` is under this worktree before measuring:

| probe | what it established | oracle / preconditions |
|---|---|---|
| roster enumeration | 10 root + 43 user SKILL.md; realpath union 43 vs naive 53; 33 of 43 not under the registered root | the live host's skills root + `~/.claude/skills`, 2026-08-06 |
| roster parsing | 11/43 descriptions are block scalars (line grab yields `"|"` for all 11); **41/43** parse under the safe loader, the other 2 raise `ScannerError` on an unquoted `: ` in a plain scalar | `ruamel.yaml.YAML(typ="safe")` over the leading block. **r1 reported 43/43 from a probe whose own error path returned the exception message as the description** — a truthy string that its usability check accepted (§3.2). Re-run in r2 with an explicit exception branch |
| roster size | 21,348 B uncapped / 14,599 at 300 / **11,385 at 200** | **format-dependent**: measured on the pinned row format including the `[routable]` / `[visible only …]` marker. r1's 19,399 / 12,612 / 9,376 were the same 43 skills without markers (N3) |
| candidate ranking | Jaccard 0.6 → 0/35; Jaccard 0.2 → 3/35; shared≥3 → 33/35 with a 12.4 KB block; IDF-cosine floor 0.20 → 6/35, 8 rows, all six top-1 pairs genuine | pool = 35 pending + 31 routed from a **copy** of the live ledger; oracle = human read of every surviving pair; `_tokens`/`record_title` as shipped |
| the flip | the five-surface before/after table in §3.9 | shipped `_validate_gates`/`proposal_info`/`_resolve_destination` in this worktree |
| prompt-vs-containment text | flattened raw file text == flattened `Record.to_text()` on 35/35 live pending records; 105 sampled 80-char raw windows all contained in `to_text()` (0 misses) | `_flatten_quote` as shipped, over a **copy** of the live ledger |
| **D8's example pair** (r2; extended in r3) | the shipped record+trace validate together; a near-miss paraphrase of one quote is REFUSED; r2's `"record names no paths"` is REFUSED; both are ACCEPTED with `record_text=None`. **r3**: the FULL proposal (with `destination: reference` + `alternates`) validates through `validate_proposal`; the same proposal with `destination` removed is REFUSED, with a bogus `alternates` REFUSED — and with `destination: claude-md` **ACCEPTED**, because Render-1's derivation check is `U-table`'s and has not merged | shipped `validate_proposal` / `_validate_gates` + `Record.from_path`. The `record_text=None` legs are the control that proves containment — not shape — is what refuses the paraphrases; the `claude-md` leg is what makes the exemplar's `destination` line load-bearing rather than decorative |
| **queue composition** (new in r2) | 35 pending files (31 user / 3 project / 1 skill); **live queue with deferred hidden: 32 — 29 user / 3 project** | shipped `discover_buckets` + `queue()` over a copy, so the "deferred hidden" rule is the product's, not the probe's (F4) |
| **suite baselines** (new in r2) | CLI 1379 passed / 5 skipped / 0 failed, rc=0; UI 1149 passed / 1 failed / 0 skipped | run by this spec's author on master `07d8c08`, rc captured unpiped, UI staged with both `XDG_CACHE_HOME` and `PLAYWRIGHT_BROWSERS_PATH` (F13) |

**The 51 resolved records are `U-table`'s regression fixtures**, not this
unit's (campaign §5) — but note that the candidate ranking above was
calibrated against 31 of them, so a `U-table` run that disagrees with a
human routing on one of those records is a finding for that unit, not
evidence against this ranking.

**The pair harness is the campaign's falsifier** and is `U-pairs`. Until
it runs, A11 (both paths compose the same block) is the strongest claim
this unit can make about path parity.

---

## 10. Questions r1 raised, and their dispositions

*r1 raised five. **The gate ruled on all five**, so they are recorded here
as decisions with their reasons — not as questions a builder could reopen.
Only Q1 remains routable, and it is routed with a trigger (Checkpoint A).*

**Q1 — DECIDED: keep defer + `no-cheap-surface`; do not re-ask now; route
at Checkpoint A.** S-23 (2) made "no user-scope on-demand shelf"
permanent, and the live queue is **29 of 32 user scope** (F4; r1 said "10
of 12", a figure inherited from r2's 2026-07-27 snapshot). So a user-scope
lesson that is not file-scoped, not hook-shaped, not owned by a skill, and
whose record carries no silence/cost evidence has **no cheap surface at
all**. The doctrine keeps `recommendation: defer` + flag
`no-cheap-surface`, never a silent upgrade to ALWAYS — the move the human
already made by hand (`lrn-547d8eb6`), and the one that keeps the deferred
pile visible as the evidence Checkpoint A needs. **"Defer forever" is
itself a monoculture** and Checkpoint C is instructed to hunt exactly that
("did we build a new monoculture at the other end?"), so this is a
deferral with a trigger, not a settlement: the question goes to the user
**at Checkpoint A, with the routing measurements in hand**, on the
precedent O-10 set for the Model-B question.

**What changed about the cost of reversing it** (F16): with `U-table`
merged, this is no longer a doctrine-only posture. R-SCOPE makes
`defer` + `no-cheap-surface` **validator-enforced** for both no-surface
corners, so a Checkpoint-A decision to route these ALWAYS instead would
cost `gates.py` + `ledger_ops.py` + the doctrine, not a prompt edit.
Nothing is foreclosed — the *price* changed, and the human should know
that when the question is put.

**Q2 — CLOSED by reconciliation.** Seven of r1's eight assumptions
survived contact with the real `U-table` draft; assumption 7 did not, and
its correction is B2. See §8, which now carries a verdict per assumption
instead of a hypothesis.

**Q3 — DECIDED: the containment closure lands here.** It is U-schema's own
handoff to whoever next holds the file
(`u-schema-decision-trace-spec.md:826-834`), this unit holds both files,
and `U-table`'s §3.5 census independently reaches the same place by
listing `worker.py:927` / `:1282` / `analyst.py:244` as unchanged-and-
handed-on. Shipping the fabrication surface and the fabrication
opportunity in one commit is the point; splitting them would put the
producer of quotes in one unit and the check on quotes in another.
**Scope grew by one keyword** since r1: `scope=` rides the same call
(F1/§3.7).

**Q4 — DECIDED: constant + docstring; no telemetry.** The zero-candidate
state is legible in-band — every affected record's block carries the
literal `(no cluster candidates above the 0.20 floor)`, so a drifted
calibration is visible in the prompt the run actually sent, which is a
better record than a counter. Adding `telemetry.py` to the file set for a
signal already present in the artifact is scope the unit does not need.

**Q5 — DECIDED: keep the 64 KiB ceiling; do not split the doctrine.**
"One file, three loaders" is load-bearing and verified, not aspirational:
`analyst.doctrine_path()` resolves it through `worker.package_skill_refs()`
(`analyst.py:110-116`) and `ui/.../doctrine.py:79-126` compiles the same
file for the pane. A split doctrine is a forked doctrine waiting to
happen. The ceiling is an **alarm** rather than a control (N1, A13):
today's inputs sit at ~2.5× headroom, so it exists to fire on a later
doctrine that grows unattended.

---

## 11. Revision history

- **r1, 2026-08-06** — first draft, for the blind spec gate. Written
  against merged `U-marker`/`U-marker-ui`/`U-analyst`/`U-schema`/`U-reach`/
  `U-recur`/`U-pathed`/`U-grad-ui`; `U-table` spec in flight with no draft
  on disk (§8). Carries S-26's flip and migration surface, S-23's tier
  reordering, S-24's search-only sharpening, campaign §6 items 5 and 6,
  and FW-43's two stale-premise repairs.
- **r2, 2026-08-06** — fold round after the blind gate returned **NOT
  SOUND (2 BLOCKER / 16 FOLD / 12 NOTE)**. The gate re-executed nearly
  every r1 measurement and reproduced it; three diverged and r2 carries
  the corrections.

  **Both blockers closed.** *B1* — r1's worked trace shipped **without a
  record**, and its exemplar quote was a paraphrase of `lrn-5d0c592a` that
  the shipped containment check refuses; A19 and M22 were therefore both
  inert (with no `record_text=`, even r2's `"record names no paths"` was
  accepted). D8 now ships a **synthetic** example record beside the trace
  (synthetic because the doctrine is public and the ledger is severed from
  it), every quote verbatim from it, executed with a fabricated-quote
  control; A19 gains that control and M22 bites. *B2* — the real `U-table`
  draft resolved r1's §8 assumption 7 **against** r1: R-SCOPE asks T2
  honestly at skill scope and degrades the *rendering* to `defer` +
  `no-cheap-surface`, and its §8-Q1 rejects the doctrine-side branch r1
  chose. D2/D3/D4 and A15 changed; §8 became a reconciliation with a
  verdict per assumption.

  **All sixteen folds landed.** Substance: F7 (producer-instruction
  assertion + an end-to-end deletion-path criterion, A12b), F8 (the
  roster-sha escape hatch — `unavailable` is now refused when a roster
  *was* available, A23 Leg B), F15 (the UI `--dest` invariant restated as
  the conditional it is, and the refusal message re-pointed at
  `self-learn worker kick`, which exists, instead of `proposal refresh`,
  which does not until Wave 4). Interface: F1 (`scope=` + the `:927/:928`
  swap, discharging all of `U-table` H1), F2/F3/F5 (PATHED renders
  `route`; HOOK names its fallback in `alternates`; `recommendation` is
  derived, not chosen), F16. Measurement: F4 (queue is 29/32 user scope,
  not 10/12), F13 (baselines re-measured by this author: CLI 1379/5/0, UI
  1149 passed/1 tolerated failure/0 skipped), F14 (roster parses **41/43**,
  not 43/43 — and r1's claim came from a fail-open in its own probe, whose
  error path returned the exception message as a "description"; A3's
  fixture is reshaped to the real failure). Criteria: F6, F9, F10, F11,
  F12.

  **Notes folded**: N1 (§9 now separates discriminating criteria from
  regression guards), N2, N3 (roster bytes labelled format-dependent, with
  both formats' figures), N4, N5, N6 (five doctrine mutations added,
  M28–M32), N7, N8, N9, N10, N12. N11 was an endorsement and is kept.

  **Two things r2 changed that the gate did not ask for**, both disclosed
  rather than slipped in: `card-sections.yaml` joins the file list for one
  `instruction` edit (N10 forced the choice — the card obligation has to
  live in the registry, and §0.4 forbids a second copy), and every
  citation into the in-flight `U-table` draft became a section/rule id
  after its line numbers were measured moving mid-fold (§0.5).
- **r3, 2026-08-06** — delta verdict **SOUND, cleared for build** (the
  build still waits on `U-table`'s merge). Five bounded substitutions,
  nothing else. **D1**: two stale copies of the N3 number corrected —
  §3.5's size ceiling and A13's headroom sentence now both use the
  **11,385 B** figure the composer actually emits, not the uncapped
  21,348. **D2**: the "A15/A17 changed" claim corrected to "A15 changed"
  in §8 and §11, and A16/A17 given pinned match tokens — A17's r1 wording
  ("unavailable") would have failed *spuriously* against a doctrine
  written exactly to D1's mandated "no routable surface … → R-SCOPE", i.e.
  the criterion would have pushed a builder back toward the phrasing B2
  exists to remove. **D3**: the last surviving line citation into the
  in-flight `U-table` draft replaced with `u-table §6-BD10`, per this
  spec's own §0.5. **D4**: the D8 exemplar gains `destination: reference`
  + `alternates`, re-executed through the full `validate_proposal` — and
  the probe found that a *wrong* destination (`claude-md`) is **accepted
  today**, because Render-1's derivation check is `U-table`'s and has not
  merged, which makes the exemplar the only thing teaching the right
  answer in the degraded corner. **D5**: the `lrn-00000000` claim softened
  from "no real record id can collide" to a stated convention, with the
  honest note that `00000000` is a legal 8-hex id; no generation-side
  exclusion was added (out of scope, and it would buy a real rule with a
  documentation problem). A19 was re-pointed from `_validate_gates` to
  `validate_proposal` so the fields D4 added are actually covered —
  disclosed here as part of D4 rather than as a sixth change.
