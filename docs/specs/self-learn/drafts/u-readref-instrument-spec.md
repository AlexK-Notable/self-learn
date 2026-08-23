# Spec — U-readref: an observable for "a reference-shelf file was actually opened"

Status: **r2 folded — all spec-gate findings closed across two rounds.** Unit
`U-readref`, TaskList #4 (Wave 1 of the cap-rework sequence). Next consumer:
the Sonnet builder, then the code gate (see **§10**).

**Round 1** — blind Opus spec gate: **CHANGES REQUIRED, 2 BLOCKER / 7 MAJOR /
4 NIT**. All thirteen folded; both rulings implemented as written (§4.4 keeps
manual registration; §5.3/§6.5 carry the accepted residual with its
one-directional asymmetry). **Round 2 (delta)** — all 13 certified closed;
**1 new MAJOR + 4 NIT** raised, all folded here. Every gate claim in both
rounds was independently re-verified against this tree before folding.

**Where the r1 findings landed** — B1 §4.1.1 + T8 · B2 §4.1.2 + T9 ·
M1 §4.2-7 + T11 · M2 §6.3 + T6.3/T6.7 · M3 §2.8/§9.4/§8-4 · M4 §2.7/§4.1 ·
M5 §4.2-5 + T10 · M6 §6.7 + §6.5 + T12 · M7 §6.6 + §6.1 + T13 ·
N1 §5.1/T1.2 · N2 §5.2 · N3 §2.4 · N4 T2.5a/T2.5b.

**Where the r2 findings landed** — **M8** §5.2 rows + new **§5.2.1** (the
project-scope key RULING) + **§5.2.2** + §5.3's generalized rule + **T4.6** ·
N5 §9.2 · N6 §4.2-3 + T2.5c · N7 §6.2-7 + T3.8 · N8 §5.2.2 (`ref_target`) and
§6.1/§6.6/T13.2 (`unresolvable_records`). The gate's two *"noted, no finding"*
items are carried **verbatim** into **§10**, each with its discharge.

**The one r2 decision that was mine to make** (§5.2.1): the project-scope
component of `bucket`/`ref_target` is the slug's **8-hex sha256 digest alone**,
never the readable slug — which on this host is a mangled `$HOME` path that
defeats every existing guard.

**Normative parents.** **S-23** (`03-decisions.md:37`) — this unit builds the
measurement S-23 named as its own reopening condition. **S-7**
(`03-decisions.md:18`) — the storage-class ruling whose content discipline
every new telemetry kind inherits. **S-25** (`:39`) is a sibling gap, not a
parent, and is untouched here.

**The ruling this unit exists to serve, supplied with the work order and not
discoverable from the tree:** *"strict at the gate, light at the file —
instruments before ceilings."* This unit is a **precondition for any hard
cap**. It builds an instrument and nothing else. It changes no threshold, no
gate, and no routing behaviour.

**Where prose and the acceptance criteria conflict, the criteria (§7) and the
schema (§5, §6) win.** The prose is rationale; the criteria are the contract.

**Citations.** Every `file:line` below was re-read against this worktree at
**`b316f1e`** and is written *anchor first, line second*
(`telemetry.py::EVENT_KINDS`, currently `telemetry.py:73`). Paths are
repo-relative; the CLI package root is `plugins/self-learn/cli/`, so
`telemetry.py` means
`plugins/self-learn/cli/src/self_learn/telemetry.py`.

**Files this unit may touch.**

| File | Why |
|---|---|
| `cli/src/self_learn/telemetry.py` | one kind added to the closed set; `SCHEMA_VERSION` bump |
| `cli/src/self_learn/refread.py` *(new)* | path→target-key resolution + the emit entry point |
| `cli/src/self_learn/report.py` | the new `reference_shelf` facts block + its text render |
| `cli/src/self_learn/cli.py` (or wherever `telemetry` subcommands are wired) | the `telemetry read-observed` verb |
| `plugins/self-learn/hooks/self-learn-refread.sh` *(new)* | the PostToolUse hook |
| `install.sh` | one `link` line for the new hook |
| `plugins/self-learn/README.md` | the manual-registration snippet for the new hook |
| `cli/tests/` | the tests of §7 |

Anything else is out of scope and must be **reported, not edited**.

---

## 1. Objective

Make "a `references/*.md` file was actually opened" an **observable fact**.

Today it is not. `reference` is the on-demand tier: a lesson routed there is
recorded as resolved, counted as routed, and appears in every report as a
success — while nothing anywhere records whether the file was ever opened.
The shelf that absorbs what the expensive shelves reject is the one shelf
whose effectiveness is entirely unobserved.

Two consequences, both live:

1. **Demand-tier routing claims are unfalsifiable.** "Route it to the cheap
   shelf instead" is an argument that cannot currently be wrong.
2. **Any hard cap stays blocked.** A cap refuses entries on the expensive
   surfaces and relocates them onto the cheap one. Without this instrument
   that is not a saving, it is a **transfer of a measured cost into an
   unmeasured one** — risk moved into the region where failure is silent.

**This unit is doctrine S-23's stated reopening condition.** S-23
(`03-decisions.md:37`, ratified 2026-08-02) ruled against a user-scope
reference surface and closed with, verbatim:

> Reopens if on-demand lookup is ever actually instrumented (campaign
> Checkpoint B) and measured to work.

That condition has never been met, and every subsequent "move it to the cheap
shelf" argument has been made without the measurement S-23 asked for. **This
unit builds the instrument half of that condition. It does not reopen S-23**
— reopening additionally requires the measurement to exist *and be read*, and
that is a later, human-directed step (§8).

The failure mode this instrument is shaped against is the one the ledger has
already recorded twice: `lrn-ea833a5b` (a gate whose "pass" output is
identical to its "cannot see the target" output) and `lrn-6d21607e` (a canary
pointed at a decoy that reports "unchanged" precisely on the runs that
corrupted the real data). **Unread must never render as effective, and
un-instrumented must never render as zero.** §6 makes that structural, not
advisory.

---

## 2. Current behavior (verified)

### 2.1 The closed telemetry kind set has no read event

`telemetry.py::EVENT_KINDS`, currently `telemetry.py:73-86`:

```python
EVENT_KINDS = frozenset(
    {
        "offer-made",
        "offer-declined",
        "capture",
        "card-shown",
        "card-decided",
        "fire",
        "recurrence-suspect",
        "staleness-flag",
        "surface-budget",
        "route",
    }
)
```

Ten kinds; none of them observes a read. Validation is a membership test at
the single emission point — `telemetry.py::spool_event`, currently
`telemetry.py:148-151`:

```python
    if kind not in EVENT_KINDS:
        raise TelemetryError(
            f"unknown event kind {kind!r} — v2 kinds: {sorted(EVENT_KINDS)}"
        )
```

so the set is genuinely closed: an unlisted kind cannot be spooled at all.
`telemetry.py::SCHEMA_VERSION`, currently `telemetry.py:68`, is `2`, and its
comment pins the rule this unit must obey — "Extending the closed event-kind
set is a schema version bump (11 §4.3)."

`telemetry.py::NOTE_KINDS`, currently `telemetry.py:90`, is
`frozenset({"offer-made", "offer-declined"})` — the kinds **the model** may
emit through `telemetry note`. Everything else is code-emitted.

### 2.2 Payload discipline already exists and is enforced

`telemetry.py` module docstring, currently `telemetry.py:16-19`:

> Content discipline (11 §4.4): events carry ids, enums, versions, hashes,
> counts — never lesson body text, quotes, transcript spans, or free text.

Mechanically enforced at `telemetry.py:174-181` — a non-scalar payload value
is refused:

```python
            raise TelemetryError(
                f"event field {key!r} must be a scalar (ids/enums/counts — "
                f"11 §4.4), got {type(value).__name__}"
            )
```

**Note what this does and does not catch.** It refuses a dict or a list. It
does **not** refuse a long string. A hook that passed file content through as
a `str` would spool it and the scalar check would pass. §5.3 and §7-T4 exist
because of exactly this gap.

### 2.3 `report.py` has no reference-shelf block

`report.py::gather`, currently `report.py:250`, returns one facts map
(`report.py:362-394`) whose keys are `generated`, `buckets`, `destinations`,
`routed_live`, `routed_ever`, `superseded_after_routing`, `supersede_rate`,
`graduated`, `rejected`, `open_followups`, `recurrence_suspects`, `deferred`,
`mined`, `telemetry`. `destinations` counts live routed records **by
destination**, so `reference` appears there as a *routing* count — never as a
*use* count. There is no per-target row, no read count, and no field a cap
rework could consume.

`report.py::render_text` (currently `report.py:405`) prints a
`telemetry events on file` line from `events_by_kind`, and — currently
`report.py:489-497` — a block headed:

> Routed rules with no observed activity — NOT dead weight: fire
> observation starts with the M2 miner, and a silently-working rule fires
> without a trace.

That is the honest posture the code takes today about *rules*. This unit
gives the *reference shelf* the observation that block says does not exist.

### 2.4 The reference target of a record is already resolvable

Two pieces already exist and must be reused rather than reinvented.

`ledger_ops.py`, currently `:1830-1835`, records **which** references file a
route landed in:

```python
            # WHICH references file this landed in (audit 2026-07-16
            # BLOCKER 2): ``destination: reference`` alone is lossy, and
            routing["reference_file"] = reference_file
```

`selfcheck.py::_reference_target_for`, currently `selfcheck.py:261-282`,
turns a record into its absolute target file — skill scope via
`skill_dir_for(load_hosts(home), bucket.name) / "references"`, project scope
via `Path(bucket_project_path(bucket.path)) / "references"`, gated on
`record.scope == "project"` with a `None`-host guard
(`selfcheck.py:273-277`), and **returns `None` for any other scope**
(`:278-279`). That `None` is S-23 (2) in code: there is
no user-scope reference surface. `compilers.py::reference_target_path`
(currently `compilers.py:1090-1101`) is the basename→path mapping underneath
it, defaulting to `LEARNINGS.md`.

### 2.5 A hook is a shipped, exercised pattern in this plugin

`plugins/self-learn/hooks/self-learn-pending.sh` is a live SessionStart hook.
Its header carries the pin this unit's design must obey — currently `:7-9`:

> ALL queue semantics come from `self-learn status --json --fast` […] This
> script only formats; it never reimplements queue rules

Install is a symlink, registration is manual. `install.sh:80`:

```sh
link "$P/hooks/self-learn-pending.sh" "$HOOKS_DIR/self-learn-pending.sh"
```

with `HOOKS_DIR="$HOME/.claude/hooks"` (`install.sh:29`) and the next line
saying registration in `~/.claude/settings.json` is **manual**. The script
hard-depends on `jq` and exits 0 when it is absent.

`selfcheck.py::_check_hooks` (currently `selfcheck.py:716`) already flags,
per its own docstring at `:724-726`:

> any settings.json registration referencing a ``self-learn-*`` hook
> whose ``~/.claude/hooks`` symlink is missing or dangling

so a hook script named `self-learn-*` inherits dangling-registration
detection **for free**.

### 2.6 The miner structurally cannot see a reference read — measured

This is the decisive current-behaviour finding, and it was established by
running the system, not by reading it. Full method and raw output: **§9**.

**(a) The digest drops the path.** `miner.py::digest_transcript`, currently
`miner.py:441`, states its own contract:

> Dropped: tool-result bodies and tool-use payloads.

and `miner.py:511-519` implements it — a `tool_use` block becomes
`shape = name` (`:514`), with **only `Bash`** special-cased to carry its
payload (`:515`). A `Read` is therefore digested as the bare string `Read`.

Rendered on a transcript produced for this spec, the parent session's own
`Read` of a marker file digests to exactly:

```
[result L15 Read ok] 1	# parent reference target ⋯ 3
```

Tool name, status, and the first/last line of the *body* (via
`miner.py::_edges`, currently `:380-388`) — **no file path anywhere.** The
miner can see that *a* file was read and what its first line says; it cannot
see *which* file.

**(b) A subagent's read is not in the transcript at all.** Across **227**
transcript files under `~/.claude/projects`, `isSidechain` is present in 226
and its value is `false` in every one; **zero** entries anywhere carry
`isSidechain: true`. In the probe transcript, the subagent's `Read` of
`CHILD_REF.md` appears as **no `tool_use` block of any kind** — the parent
transcript holds only the `Agent` dispatch and the agent's final report text.
This repo's own two-gate pipeline runs its builders and gates as subagents,
so this is not a corner case: it is where much of the reading happens.

**(c) There is no deterministic matcher to extend.** The miner's `fire`
events do not come from a regex. `miner.py:1455-1479` consumes
`parsed["fires"]` — a list produced by the contained `claude -p` reader
model — and gates each row on `RECORD_ID_RE` and record status. The reader is
given **no filesystem tools at all**: `miner.py::READER_DISALLOWED_TOOLS`,
currently `miner.py:574`, is `worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"`.
So "the miner's matcher" as a place to add a rule does not exist; a sentinel
scheme would have to add a new deterministic pass, or trust a model's
self-report.

**(d) Sessions go dark on contact with self-learn.** `digest_transcript`
halts a session permanently on a self-prompt header, and `:489-491` breaks
out of the whole digest at the first `/self-learn:` command tag. A review
session — precisely when a human is looking things up — is off-limits by
design.

### 2.7 A PostToolUse hook sees every read, including a subagent's — measured

Also established by running the system (§9), and independently corroborated
against the published hooks documentation (§9.3).

- A `PostToolUse` hook with matcher `Read` fired **exactly twice** for two
  reads: once for the parent session's `Read`, once for a subagent's `Read`.
- The stdin payload carries `tool_input.file_path` — the absolute path — so
  target identity is directly available, which is precisely what the miner
  lacks (§2.6a).
- The subagent invocation carried two extra top-level keys the parent
  invocation did not: `agent_id` and `agent_type`. **`session_id`,
  `transcript_path`, `cwd` and `prompt_id` were byte-identical between the
  two** — so the *presence of `agent_id`* is the only discriminator, and no
  scheme keyed on ids *differing* will work.
- The payload also carries `tool_response`, and for a `Read` that object
  **contains the entire file body** under `.file.content`. This is the
  central S-7 hazard of this design and §5.3 is written against it.
- A **failed** Read fires a different event, `PostToolUseFailure`, carrying
  `tool_error` instead of `tool_response`. A `PostToolUse` hook therefore
  observes **successful reads only** — which is the semantics this instrument
  wants, and is stated here so it is not mistaken for a gap.

**The cost model, measured (§9.2).** `PostToolUse` is synchronous and the
tool result is withheld from the model until every matching hook exits — a
6 s hook delayed the `tool_result` by 6.05 s. **This hook is on the critical
path of every `Read` in every session.** Measured per-invocation costs on
this host, against a realistic 40 KB payload:

| step | cost | runs on |
|---|---|---|
| `jq`-extract prefilter | **3.06 ms** | every `Read` |
| pure-bash glob prefilter | 1.70 ms | (rejected — §4.3) |
| `self-learn` CLI process (uv wrapper — the only one on PATH) | **105 ms** | only a `references/*.md` read |

The two-stage shape in §4 exists to keep the 105 ms off the common path: a
reference read is rare, an ordinary `Read` is not.

**There is no installed console-script on this host.** `~/bin/self-learn` is a
symlink to `plugins/self-learn/scripts/self-learn`, whose body is
`exec uv run --project "$(dirname "$(readlink -f "$0")")/../cli" self-learn "$@"`,
and `type -a self-learn` finds only that. So every `self-learn` call pays the
`uv run` cost, and the two figures measured for this spec (72 ms warm via
`~/bin/self-learn`, 105.4 ms with an explicit `--project`; the gate re-measured
~80 ms) are the **same wrapper**, not two different install routes. The table
headlines the conservative 105 ms. Secondary but worth stating: that wrapper
executes the **working tree**, so an in-flight edit runs on the critical path
of every reference read.

### 2.8 The registration surface broke on this host — a dated incident, since repaired

**On 2026-08-23, while this spec was being written**, `~/.claude/settings.json`
did not parse. Verified twice, with a positive control:

```
$ python3 -m json.tool ~/.claude/settings.json ; echo rc=$?
Expecting ',' delimiter: line 43 column 16 (char 888)
rc=1
```

Line 42 closed a hook entry with `},` and line 43 opened a bare
`"matcher": "Bash",` directly inside the array — a missing `{`. Claude Code
discards such a file **wholesale and silently**, with no stderr warning, and a
valid hook earlier in the file does not survive it. For the duration of that
breakage every global hook on this host was dead, `self-learn-*` guards
included.

**It has since been repaired and is no longer live.** Re-measured on the same
day, after the fix:

```
$ python3 -m json.tool ~/.claude/settings.json ; echo rc=$?
rc=0
```

Line 43 now opens `{` before `"matcher": "Bash"`, and five `self-learn-*`
registrations resolve — four PreToolUse guards plus `self-learn-pending.sh`,
**none of which carries a `timeout`** (a detail §4.2-5 does not inherit: this
unit sets one explicitly).

**The incident is retained because its argument survives its repair.** A
registration surface that can break by hand-edit, silently, is a permanent
property of this design — not a one-off. An instrument registered there during
such a window records zero reads forever while looking exactly like a shelf
nobody opens; a report printing `0` in that state would be `lrn-ea833a5b`
reproduced inside the very unit built to prevent it. That is why §6.3 gives
the unparseable case **its own named state** rather than folding it into
"nothing registered", and why **`instrumented: false` renders as ABSENT, never
as zero**. Repairing the file was never this unit's work (§8-4).

---

## 3. Chosen observable, and the rejected alternative

**CHOSEN: (a) a PostToolUse `Read` hook emitting a new closed telemetry
kind, `reference-read`, under S-7 ids-only discipline.**

**REJECTED: (b) a sentinel line the nightly transcript miner matches.** It
fails on coverage, on mechanism, and on lag, and only the third is fixable.
On **coverage**, the miner cannot see a subagent's read at all: across 227
transcripts on this host `isSidechain` is never `true`, and in the probe
transcript the subagent's `Read` produced no `tool_use` block whatsoever
(§2.6b) — while this repo's own two-gate pipeline does much of its reading
inside subagents, so the blind spot sits exactly over the traffic that
matters. On **mechanism**, "the miner's matcher" does not exist: `fire`
events come from a contained `claude -p` reader's JSON output
(`miner.py:1455-1479`), so a sentinel scheme would either need a new
deterministic pass or would rest on a model's self-report — and the digest
drops tool-use payloads (`miner.py:441`, `:514`), so even a *parent* read
arrives as the bare token `Read` with no path (§2.6a). A sentinel embedded in
the file's first line *would* survive into `_edges`, but it would be
attributed by **content**, not identity: a partial or offset read, an edited
header, or the 60 000-char digest clip all silently drop it, and the file
would have to carry a marker line that exists only to be observed. On
**lag**, the miner is nightly, and sessions go dark at the first
`/self-learn:` tag (§2.6d) — so review sessions, when lookups actually
happen, are structurally unobservable. Against all of that, the hook's cost
is 3 ms of `jq` on each `Read` (§2.7) and its failure mode is *detectable*
(§6.3), where the miner's failure mode — a silent miss — is the shape this
whole unit exists to eliminate.

**The failure modes, stated as a pair, because the choice turns on their
asymmetry.** A dead hook produces **zero** events; a missing miner match
produces **zero** events. Identical output. What separates them is that a
dead hook is *independently detectable* — the script's presence and its
settings.json registration are both inspectable facts, already partly
covered by `selfcheck.py::_check_hooks` (§2.5) — whereas "the miner did not
match" has no out-of-band witness at all. §6.3 converts that detectability
into a report field, which is what makes the instrument honest rather than
merely present.

---

## 4. New behavior

### 4.1 Shape: prefilter in bash, decide in the CLI

```
Read tool completes
  → PostToolUse hook  hooks/self-learn-refread.sh        (~3 ms, every Read)
      · jq-extract .tool_input.file_path ONLY
      · not a */references/*.md path → exit 0, nothing spawned
  → self-learn telemetry read-observed --path <abs> [...] (~105 ms, rare)
      · resolve <abs> against registered references dirs
      · not a known reference target → emit nothing, exit 0
      · known → spool one `reference-read` event (relative key only)
```

The split follows the pin the sibling hook already states — *"This script
only formats; it never reimplements queue rules"*
(`self-learn-pending.sh:6-8`). Path→target-key resolution needs `hosts.yaml`
and the same mapping `selfcheck.py::_reference_target_for` and
`compilers.py::reference_target_path` already own; reimplementing it in bash
would fork that mapping, which is the defect class
`compilers.py:1096` was written to close.

#### 4.1.1 Path normalization is MANDATORY — the instrument is dead without it

**The path a model reads and the path `hosts.yaml` resolves are different
strings for the same file.** `hosts.py::skill_dir_for` (currently
`hosts.py:546-550`) globs `<skills_root>/plugins/*/skills/<name>`, and this
host's `skills_root` is `/home/komi/repos/claude-skills` — so
`selfcheck.py:272` resolves `skill:home-assistant` to a path under
`repos/claude-skills/…`. But `~/.claude/skills/home-assistant` is a
**symlink** into that tree, so `tool_input.file_path` carries
`/home/komi/.claude/skills/home-assistant/references/LEARNINGS.md`. Measured:

```
both paths exist:            True / True
~/.claude/skills/<name> is a symlink:  True
naive str prefix match:      False
after .resolve() on both:    equal
```

A naive prefix comparison therefore emits **zero events forever**, and §6 would
render `zero_read: true` on a target carrying **15 live reference-routed
records** — indistinguishable from a genuinely unread shelf. That is
`lrn-ea833a5b` reproduced inside the unit built to prevent it.

**Normative:** the comparison MUST apply `Path.resolve()` (equivalently
`os.path.realpath`) to **both** the hook-supplied absolute path **and** every
candidate references directory before comparing, and the emitted key MUST be
derived from the resolved pair. A build that compares unresolved strings is
rejected regardless of which tests pass. §7-T8 is the test.

#### 4.1.2 ONE helper owns the target key — both sides import it

The `ref_target` string is produced on two sides: the **emit** side (absolute path
→ key) and the **aggregate** side (record → `_reference_target_for` → key).
Nothing structural forces them to agree, and a one-character divergence does
not surface as an error — it surfaces as §6.2-4's legitimate "target with
events but no live record" row, i.e. **the defect renders as correct output**.

**Normative:** exactly one exported helper owns the mapping, and it returns
the **components as well as the key**, so no caller ever re-splits the string:

```python
# refread.py — the single owner. Both sides import THIS.
class RefTarget(NamedTuple):
    key: str      # "<scope>:<bucket>/references/<relpath>" — the `ref_target` field
    scope: str    # "skill" | "project"
    bucket: str   # skill name, or the project digest (§5.2)

def resolve_ref_target(home: Path, abs_path: Path | str) -> RefTarget | None:
    """Absolute path -> its RefTarget, or None when the path is not under
    any registered references dir. Applies .resolve() to BOTH the given
    path and every candidate references dir first (§4.1.1)."""
```

**The composite return is deliberate.** §5.2 emits `scope` and `bucket` as
their own fields; a `str`-only helper would force the emit side either to
re-split the key or to re-derive the components — both of which reinstate the
second producer this section exists to remove. The helper computes them once
and hands back all three.

`refread.py` (emit) and `report.py` (aggregate) both call it; neither
re-derives the shape. `report.py` converts a record to an absolute target with
the existing `selfcheck.py::_reference_target_for` (`:261-282`, which returns
an absolute `Path`) and then hands **that path** to `resolve_ref_target`.
§7-T9 is the round-trip test that proves the two sides agree; it is required
because no other enumerated test joins real emit output against real aggregate
output — T3 hand-authors its events, T5 has none, T2 checks the key in
isolation.

### 4.2 The hook script — `plugins/self-learn/hooks/self-learn-refread.sh`

Requirements, all normative:

1. **Never fails a Read.** `exit 0` on every path, including every error
   path. It is on the critical path of every tool call (§2.7).
2. **Never reads `tool_response`.** It extracts exactly one JSON path,
   `.tool_input.file_path`, via `jq -r '.tool_input.file_path // empty'`.
   The file body is never bound to a variable, never echoed, never logged.
   This is the structural half of §5.3 — the content is not *scrubbed*, it is
   never *touched*.
3. **Guards its dependencies** the way the sibling does
   (`self-learn-pending.sh:20-21`) — **all three**, `timeout` included:

   ```sh
   command -v self-learn >/dev/null 2>&1 || exit 0
   command -v jq         >/dev/null 2>&1 || exit 0
   command -v timeout    >/dev/null 2>&1 || exit 0
   ```

   The third is not symmetry: §4.2-5 makes `timeout` load-bearing, and under
   the sibling's `set -euo pipefail` (`self-learn-pending.sh:18`) a missing
   `timeout` binary is a **non-zero exit** — exactly what §4.2-1 forbids, and
   on the critical path of every `Read`. T2.5c is the test.
4. **Prefilters in-shell** with a `case` glob on the extracted path
   (`*/references/*.md`) before spawning anything. A false positive is
   harmless (the CLI resolves authoritatively and emits nothing); a false
   negative is not, so the glob must be at least as wide as every reachable
   references dir.
5. **Backgrounds nothing, and bounds itself from the inside.** The CLI call
   runs in the foreground so the event is durable before the hook exits, and
   it is wrapped in **`timeout 4`** — strictly inside the harness's
   `"timeout": 5` (§4.4). **A timed-out CLI is an ordinary `exit 0` path**,
   not an error path. The inner bound is load-bearing, not belt-and-braces:
   a script the *harness* kills at 5 s can never reach its own `exit 0`, so
   requirement 1's fail-open guarantee would be unreachable exactly when it
   matters, and the spec would be silent on what a killed PostToolUse hook
   does to the Read. The repo already carries this pattern — an external
   `timeout(1)` wrapper as the only reliable bound (`lrn-1dd6163b`). The
   harness `timeout` remains as the outer backstop; the script's own bound is
   what makes requirement 1 true. §7-T10 is the test.
6. Passes through, as flags: `--path` (absolute), `--session`
   (`.session_id`), and `--subagent` **iff the payload has an `agent_id` key
   at all**. Keying on `agent_id` *presence* is required — `session_id`,
   `transcript_path`, `cwd` and `prompt_id` are identical between parent and
   subagent (§2.7), so nothing else can distinguish them.
7. **Never writes to stdout — on any path.** PostToolUse stdout is surfaced
   back into the session, so an instrument that speaks there is talking to the
   model on the critical path of a reference read: it would perturb the very
   behaviour it exists to measure, and it would do so *selectively*, only on
   reads of shelf files. Diagnostics go to stderr or nowhere. This binds every
   path — success, prefilter miss, missing dependency, CLI failure, timeout —
   not merely the deps-missing case T2.5 covers. §7-T11 is the test.

### 4.3 Rejected within the design

- **Pure-bash glob over the whole payload** (1.70 ms, 1.36 ms cheaper): it
  pattern-matches across the file body, so the content is bound to a shell
  variable and a file *containing* the string `/references/x.md` false-fires.
  The 1.36 ms is not worth touching the content at all.
- **Appending the JSONL line from bash.** `telemetry.py:5-9` does say "Any
  process may append events to the SPOOL", so this is permitted, and it
  would remove the 105 ms entirely. Rejected: it forks the target-key mapping
  into bash (§4.1) and hand-builds JSON in a shell script, against the
  `self-learn-pending.sh:6-8` pin.
- **A `PreToolUse` hook.** It fires before the read and cannot know the read
  succeeded; `PostToolUse` fires only on success (§2.7).

### 4.4 Registration

Follows the established convention: `install.sh` gains one `link` line
beside `install.sh:80`, and registration in `~/.claude/settings.json` stays
**manual** and documented in `README.md`:

```json
"PostToolUse": [
  {"matcher": "Read",
   "hooks": [{"type": "command",
              "command": "$HOME/.claude/hooks/self-learn-refread.sh",
              "timeout": 5}]}
]
```

`"Read"` contains only letters, so it takes the **exact-string** matcher
path, not the regex path (§9.3) — it matches `Read` and nothing else.

Naming the script `self-learn-refread.sh` is load-bearing: it brings the
script under the `self-learn-*` prefix that
`selfcheck.py::_check_hooks` (`:724-726`) already scans for dangling
registrations.

**RULED (spec gate r1) — KEEP MANUAL REGISTRATION. Settled, not open.**
Claude Code does support plugin-provided hooks (`hooks/hooks.json` at the
plugin root, or a `hooks` key in `plugin.json`, with `${CLAUDE_PLUGIN_ROOT}`;
§9.3), and r1 routed the choice to the gate on the reasoning that the plugin
route sidesteps the broken-settings.json class (§2.8). **The gate ruled the
datum cuts the opposite way, and the ruling stands.**

A hand-edit silently killing every global hook is an argument for
**detectability**, not for relocation. Relocation does not remove the failure
class — a plugin `hooks/hooks.json` is still a JSON file that can break — it
moves the failure somewhere **nothing in this repo can see**:
`selfcheck._check_hooks` scans `settings.json` commands for the `self-learn-*`
prefix (`selfcheck.py:796-799`), so a plugin-registered hook loses its only
out-of-band witness. That matters more here than anywhere else in the plugin,
because §6.3 derives `instrument_state` from exactly two inspectable facts and
**one of them is the settings.json registration**. Under the plugin route
`instrument_state` would have to read Claude Code's plugin-enablement state —
internal state this repo has no verified reader for — trading a **detectable**
failure for an **unverifiable** one. That inverts §3's own argument, which is
the load-bearing reason option (a) beat option (b) in the first place.

The honest way to absorb the incident is **M2, not migration**: give
`settings-unparseable` its own `instrument_state` (§6.3) so the broken-file
case is *named* rather than laundered into `not-registered`. One enum value
and one test. Migration remains a defensible future unit; coupling it to an
instrument unit is scope creep with a worse failure surface. **§8-11 stays
parked.**

---

## 5. Telemetry kind schema, and S-7 compliance

### 5.1 The kind

`reference-read` joins `telemetry.py::EVENT_KINDS`, and **`SCHEMA_VERSION`
goes `2 → 3`** — required by the comment at `telemetry.py:63-67`
("Extending the closed event-kind set is a schema version bump"). As with the
v1→v2 bump, no consumer filters on the number; the builder must **verify and
state** that, not assume it.

`NOTE_KINDS` is **unchanged**. `reference-read` is code-emitted only, the
same class as `route` (`telemetry.py:70-72`), so `telemetry note
reference-read` must refuse.

### 5.2 The payload

Emitted through `telemetry.spool_quiet` (never `spool_event`) — telemetry
must never break a caller, the rule `telemetry.py:196-199` states and
`verbs.py:2806` follows.

| field | type | domain | why it is an identifier, not content |
|---|---|---|---|
| `ref_target` | str | `<scope>:<bucket>/references/<relpath>` | a **relative** key; never the absolute path, and never a path-derived slug (§5.2.1). Produced ONLY by `refread.resolve_ref_target` (§4.1.2), from `.resolve()`d paths (§4.1.1). Named `ref_target`, not `target`, because `target` is already taken (§5.2.2) |
| `scope` | str | `skill` \| `project` | closed enum; `user` is impossible (§2.4, S-23 (2)) |
| `bucket` | str | skill name, or the project **digest** (§5.2.1) | **new to the schema** — see §5.2.2; no existing kind carries a `bucket` field |
| `subagent` | bool | `true` \| `false` | a boolean |
| `session` | str | Claude Code session uuid | an opaque uuid — not a path and not a span; no existing event carries one, this is the first |

Plus the five fields `spool_event` stamps itself (`telemetry.py:161-172`):
`ts`, `kind`, `actor`, `schema_version`, `nonce`.

#### 5.2.1 The project-scope component is the DIGEST, never the slug — RULED

`Bucket.name` is the bucket **directory** name (`ledger.py:154-156`:
`Bucket(path=p, scope="project", name=p.name)`), and for project scope those
directory names are mangled absolute home paths. All nine on this host:

```
-home-komi-.config-1323c4be
-home-komi-repos-claude-skills-3aaedd49
-home-komi-repos-keyboards-zmk-config-offsetkey-b93b4e47        (9 total)
```

Emitting `Bucket.name` would put `"-home-komi-.config-1323c4be"` into a
**committed, cross-machine-syncing** plane, and **every existing guard misses
it** — measured: T4.2's `/home/` check is `False`, and the repo's own
outgoing-diff scan for `/home/komi` is `False`. `-home-komi-` is neither
string, and T2.7's "no absolute path" does not match a slug. It would pass
every test and the pre-push scan. This is live, not hypothetical: two
project-scope reference-routed records sit under that bucket
(`lrn-b197d06b`, `lrn-be6dca06`).

**RULING: the project-scope component is the slug's 8-hex digest alone.**

```
project scope   ->  project:1323c4be/references/LEARNINGS.md
skill scope     ->  skill:home-assistant/references/LEARNINGS.md
```

The reason this costs nothing is `hosts.py::slug_for`'s own documented
construction (`hosts.py:104-106`):

```python
    resolved = str(Path(path).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return f"{resolved.replace('/', '-')}-{digest}"
```

whose docstring (`hosts.py:97-103`) states that **the digest is not
decoration** — the readable half is *many-to-one* (`/w/a-b` and `/w/a/b` both
render `-w-a-b`, which once cross-homed one project's lessons into another's
canon), and the digest is what makes the slug injective and stable per path.
So the half being dropped is the **ambiguous** half; the half being kept is
the **identity**. Verified with a positive control:
`sha256("/home/komi/.config")[:8] == "1323c4be"`, and the full slug
reproduces exactly.

Against the three requirements: **stable** — a sha256 of the resolved path,
deterministic and per-path by construction; **home-path-free** — a digest
reveals nothing about the path; **joinable** — both sides obtain it from
`resolve_ref_target` (§4.1.2), which derives it the same way from the same
input.

**Skill scope keeps the plain skill name.** A skill name is a public plugin
identifier (`home-assistant`, `testing-methodology`), not a path, so it
carries no host information and stays readable.

**The cost, stated: project rows in the report become opaque.** That is
accepted, and it is bounded — **the report may render the readable slug
alongside the digest**, because `report.py`'s own header (`report.py:5-7`)
says its output is *"derived, regenerated on every run, and committed
nowhere"*. The event is committed and syncs across machines; the report is
neither. **That distinction is the whole rule**: readability belongs to the
ephemeral surface, identity to the durable one.

#### 5.2.2 Two naming corrections this schema must carry

1. **`bucket` is NEW to the closed schema.** An earlier draft justified it as
   *"already carried by `capture`/`route` events"*. **That was false**,
   measured over the tracked plane: 275 lines, whose complete key set is
   `actor basis by destination kind nonce origin outcome overflow reason
   record schema_version scope source target ts variant words` — no `bucket`
   (positive control: `kind` is present). `route` (`verbs.py:2806-2812`)
   carries `record/destination/scope/by/variant`; `capture` (`teach.py:579-581`)
   carries `source/scope/record`. `reference-read` is the **first** kind to
   carry `bucket`, so it inherits no precedent and must justify the field on
   its own — which §5.2.1 does.
2. **The field is `ref_target`, not `target`.** `target` is already a
   `surface-budget` field whose domain is the **destination enum**
   (`verbs.py:2031-2033`: `target=spec.destination`). Reusing the key would
   put two incompatible domains under one name in a shared closed schema, so
   any consumer grouping by `target` without also filtering `kind` would
   conflate a destination with a file. The report's per-target rows use
   `ref_target` too (§6.1), so emit and aggregate name the concept
   identically.

**Example line** (the only shape a test should accept):

```json
{"actor":"host","bucket":"testing-methodology","kind":"reference-read","nonce":"9f2c11ab","schema_version":3,"ref_target":"skill:testing-methodology/references/LEARNINGS.md","scope":"skill","session":"b92e9a90-9f03-4a32-90ce-9f89827417bd","subagent":true,"ts":"2026-08-23T21:44:07Z"}
```

### 5.3 S-7 compliance — the fields deliberately NOT emitted

S-7's content discipline is quoted at `telemetry.py:16-19`: *"events carry
ids, enums, versions, hashes, counts — never lesson body text, quotes,
transcript spans, or free text."* The scalar check at `telemetry.py:174-181`
enforces the *shape* but **not** the *substance* (§2.2): a long string
passes. So the discipline here is a list of exclusions, each with its reason,
and §7-T4 is the test that proves it.

| excluded | why |
|---|---|
| `tool_response` / `.file.content` — **any** part | it is the entire file body. The hook never extracts it (§4.2-2), so it cannot reach the CLI at all |
| `tool_input.file_path` (absolute) | a host path. The CLI resolves it to a relative key and **drops** it |
| **any value DERIVED from a host path, in any encoding** | the governing rule, stated generally on purpose. The earlier wording — *"contains `$HOME`"* — was too narrow: it does not reach `Bucket.name`'s `-home-komi-.config-1323c4be`, which encodes the same path with `/` → `-` and defeats both the `/home/` test and the repo's `/home/komi` pre-push scan (§5.2.1). Read it as: **no field may carry the path, a transform of it, or a substring of it.** A digest of a path is permitted — it is not a transform one can read back |
| `agent_type` | an unbounded, human-authored agent-name vocabulary — free-text-shaped. The boolean `subagent` carries the fact that matters. *Deliberately rejected, not overlooked* |
| `cwd`, `transcript_path` | absolute host paths |
| `prompt_id`, `tool_use_id`, `duration_ms`, `effort`, `permission_mode` | no consumer; `effort`/`duration_ms` are undocumented fields (§9.3) and must not be depended on |
| any line/offset of the read | a transcript span, named in S-7's exclusion list |

**ACCEPTED residual (ruled by the spec gate r1 — accept, reject any gating).**
`telemetry read-observed` is a CLI verb, so a model with Bash could invoke it
and inflate a read count. The exposure is neither new nor closable: every
code-emitted kind is Bash-reachable, and `route`, `capture` and `fire` already
carry it. Closing it for `reference-read` alone would be theatre on a surface
already open ten ways, and every concrete gate available (a PATH check, a
shared token, a hook-only flag) is bypassable by the same Bash that motivates
it **while adding a new way to silently drop real events** — strictly worse.
Keeping `reference-read` out of `NOTE_KINDS` keeps it off the documented model
path, and requiring the path to resolve to a **registered** references file
bounds — but does not close — the surface. Accepted, in the manner of S-24 and
S-25.

**But the residual is NOT the same trust model `telemetry note` carries, and
the difference is one-directional.** `route` and `capture` inflate counts of
things that also leave a **ledger** trace — a record file, a commit — so a
forged event is contradicted by durable state. `reference-read` has no such
counterpart: a forged event is indistinguishable from a real one, and it
inflates precisely the number §6.5 hands to a future cap decision. **Nothing,
however, forges a zero.** The inflation surface runs in one direction only,
which makes a low count strictly better evidence than a high one — a fact
§6.5 turns into a normative clause for this block's only consumer.

---

## 6. The report field

### 6.1 Shape

`report.py::gather` gains one top-level key, `reference_shelf`, beside
`telemetry` (currently `report.py:387`):

```json
"reference_shelf": {
  "instrumented": true,
  "instrument_state": "ok",
  "flush_state": "ok",
  "enumeration_state": "ok",
  "unresolvable_records": 0,
  "unresolvable_record_ids": [],
  "window_days": 30,
  "window_start": "2026-07-24",
  "observation_start": "2026-08-25",
  "targets_total": 3,
  "targets_zero_read": 2,
  "records_on_zero_read_targets": 14,
  "reads_30d_total": 5,
  "targets": [
    {
      "ref_target": "skill:testing-methodology/references/LEARNINGS.md",
      "scope": "skill",
      "bucket": "testing-methodology",
      "records": 14,
      "reads_all_time": 0,
      "reads_30d": 0,
      "read_sessions_30d": 0,
      "subagent_reads_30d": 0,
      "last_read": null,
      "zero_read": true
    }
  ]
}
```

### 6.2 Rules

1. **Aggregation window: 30 days, rolling, ending on the report's own
   `today`** (`gather`'s existing `today` parameter, `report.py:250`). 30 d
   matches the unit already in this file (`pending_over_30d_pct`,
   `report.py:184-188`). `window_start` is emitted so a consumer never has to
   infer it. `reads_all_time` is emitted alongside, unwindowed.
2. **`read_sessions_30d` is the headline rate**, not `reads_30d`. One lookup
   that the model splits over four offset `Read` calls is **one** consultation,
   not four; counting raw events would let a single read inflate the shelf's
   apparent value. Both are emitted; #1 consumes the session count.
3. **`zero_read` is computed on `reads_all_time == 0`**, not on the window. A
   file read once, 60 days ago, is *cold* — the window fields say so — but it
   is not unread, and conflating the two would overstate the alarm.
4. **Target enumeration is ledger-driven, then union'd with events.** The
   list is: every target of a **live** reference-routed record (`status ==
   "routed"`, `superseded_by is None`, `routing.destination == "reference"`),
   resolved with the *existing* `selfcheck.py::_reference_target_for`
   (`:261-282`) — **union** every target that has a `reference-read` event
   (catching a shelf file with reads but no live record). Ledger-driven
   enumeration is what makes §6.4 possible: a target with no events must
   still have a row.
5. **Ordering: zero-read first**, then ascending `read_sessions_30d`, then
   `ref_target`. The signal S-23 fears leads the list; it is never buried.
6. **`records` is the count of live reference-routed records on that
   target** — the size of the bet riding on that file being opened.
7. **`observation_start` is the `ts` of the EARLIEST `reference-read` event in
   the tracked plane, or `null` when none exists** — never `today`, and never
   a proxy for the install date. It answers one question and only that one:
   *how far back can this block see?* A consumer comparing a read count
   against a window longer than `observation_start` is reading absence of
   history, not absence of reads — which is §6.5's measurement gate again, in
   the time dimension. T3.8 tests it.

### 6.3 Not-instrumented is a distinct state, never zero

`instrument_state` is one of `ok` | `script-missing` | `not-registered` |
`settings-unparseable`, derived from two inspectable facts: the hook script
exists and is executable at `$HOME/.claude/hooks/self-learn-refread.sh`, and
`~/.claude/settings.json` carries a `PostToolUse` registration naming it.
`instrumented` is `state == "ok"`.

**All four values are reachable** — the enum has no dangling member.

**When `instrumented` is false, every read-derived field is `null`, never
`0`** — `reads_all_time`, `reads_30d`, `read_sessions_30d`,
`subagent_reads_30d`, `last_read`, `zero_read`, `reads_30d_total`,
`targets_zero_read`, `records_on_zero_read_targets`. The text render says
**ABSENT, not zero**, in those words. `targets`, `records` and
`targets_total` still render — the shelf's contents are known regardless of
whether reads are.

This is the whole point of the unit turned into a data-shape rule.

**An unparseable settings.json is its OWN state, never `not-registered`.**
Reading the file must be failure-tolerant — never an exception, never `ok` —
but it must also not collapse two conditions with **different operator
remedies**: `not-registered` means *add the entry*; `settings-unparseable`
means *repair the JSON*, and carries the far larger fact that **every other
global hook is dead too** (§2.8). Folding them would also contradict an
explicit in-repo rule: `selfcheck.py:690-692` states verbatim that *"a broken
settings.json must FAIL loudly, not read as 'nothing registered'"*, implemented
at `:697-698` and surfaced as a selftest FAIL at `:798-799`. This block
follows that rule rather than inverting it.

### 6.4 Zero-read visibility

A shelf file with zero reads **is the signal S-23 fears** and must be the
most visible thing in this block:

- its row is always present, ordered first (§6.2-5);
- `targets_zero_read` and `records_on_zero_read_targets` are scalars a
  consumer can assert on without walking the list;
- `render_text` **names each zero-read target and its record count** — never
  a bare count, never an omission.

The rule, stated so a builder cannot optimise it away: **a target is omitted
from `targets` only if it does not exist.** "No events" is never a reason to
drop a row. Omitting empty rows is the `lrn-6d21607e` decoy shape — absence
rendering as health.

### 6.5 The consumer contract for unit #1

Unit #1 ("`reference` reported on read-rate") consumes:

- **read-rate for a target** = `targets[i].read_sessions_30d`, over
  `window_days`;
- **the shelf-level alarm** = `targets_zero_read` and
  `records_on_zero_read_targets`;
- **normative (measurement gate):** #1 **must** branch on `instrumented`,
  `flush_state` and `enumeration_state` **first**, and treat
  `instrumented: false`, a non-`ok` `flush_state`, or
  `enumeration_state: "none-enumerable"` as *no measurement*. It must never
  read a `null` as `0`, and must never let an un-instrumented, unflushed, or
  un-enumerable shelf justify a routing or cap decision. A cap that tightened
  because a dead hook reported nothing would be the precise failure this unit
  exists to prevent.
- **normative (directional bias — spec gate r1 ruling (b)):** *a high
  `read_sessions_30d` is weaker evidence than a zero one — the inflation
  surface is one-directional, so a zero read count may justify tightening and
  a high one may never, by itself, justify loosening.* The reason is §5.3's
  asymmetry: a `reference-read` event has no ledger counterpart, so a forged
  or accidental read cannot be cross-checked, while nothing can forge a zero.

`render_json` (`report.py:397`) needs no change — it serialises `gather`'s map
whole.

### 6.6 Zero enumerable targets is its own condition, not a quiet all-clear

`_reference_target_for` returns `None` for user scope **by design**
(`selfcheck.py:278-279`, S-23 (2)) — and this host carries a live user-scope
reference record (`~/.self-learn/user/resolved/lrn-c826137f.md`,
`destination: reference`), so unresolvable targets are an **expected, live**
case, not a hypothetical. Unresolvable-via-`hosts.yaml` targets (unregistered
host, missing skill) are a second such case.

With no resolvable targets the block would otherwise emit
`targets_zero_read: 0` and `records_on_zero_read_targets: 0` — which read as
*"no problem"* when the truth is *"nothing was enumerable"*. That is §6.4's own
omission defect promoted to block level, the `lrn-6d21607e` shape.

**Normative:**

- `enumeration_state` is `ok` | `none-enumerable`, the latter whenever
  `targets_total == 0`. When it is `none-enumerable`, the alarm scalars
  `targets_zero_read` and `records_on_zero_read_targets` are **`null`, not
  `0`**, and the text render states the condition rather than printing zeros.
- Records whose target does **not** resolve are counted in
  `unresolvable_records` and **named** in `unresolvable_record_ids` — never
  silently dropped from the walk. A user-scope reference record is the
  expected member of that list, and naming it is how the operator learns the
  shelf holds records no instrument can ever see.

### 6.7 Which plane is read, and what a failed flush does

**`reference_shelf` is computed from the TRACKED plane only.**
`report.read_events` (`telemetry.py:390`) reads
`<home>/telemetry/*.jsonl` and nothing else; spooled-but-unflushed events are
invisible to it. The `report` verb flushes first — `cli.py:1740-1741`, whose
own comment reads *"report is a flushing verb (11 §4.2) — its numbers include
the spool"* — so in the normal path the two planes agree.

**But that flush is best-effort, and its failure is currently silent.**
`_flush_spool_best_effort` swallows `ScanRefusal` and `OSError` to stderr
(`cli.py:1756-1763`) and `gather` proceeds regardless (`:1742`). So a refused
flush leaves **real reads sitting in the cache spool** while this block renders
`zero_read: true` with `instrumented: true` — a false alarm on the exact scalar
§6.5 makes normative for unit #1, and one that looks identical to a genuinely
unread shelf.

**Normative:** `flush_state` is `ok` | `refused` | `failed` | `not-attempted`,
and it must be **visible in the block**, not merely on stderr. Anything other
than `ok` means the counts are a **lower bound**: the text render says so in
those words, and §6.5 binds #1 to treat a non-`ok` `flush_state` the same way
it treats `instrumented: false` — as no measurement, never as evidence of
disuse. `not-attempted` is the honest value when `gather` is called directly
without a flush, which is what **every test that calls `report.gather()` does**
— so the default must not be `ok`.

**The plumbing is specified, not left to the builder.** `gather` cannot
observe the flush — its signature is `gather(home, *, today=None)`
(`report.py:250`) — and `_flush_spool_best_effort` returns `None`
(`cli.py:1747-1766`). So the outcome must be **passed in**:

1. `_flush_spool_best_effort` returns the outcome it already knows — it
   distinguishes the three cases today at `cli.py:1760` (`ScanRefusal` →
   `refused`), `:1762` (`OSError` → `failed`), and its `else` branch
   (`:1764` → `ok`) — instead of discarding it to stderr.
2. `_cmd_report` (`cli.py:1736-1744`) captures that value and passes it to
   `gather` as a new keyword-only argument, default `"not-attempted"`.
3. `gather` stores it verbatim. It never infers it.

**An implementation that derives `flush_state` by inspecting the spool at
gather time is REJECTED.** A non-empty spool at that moment does not mean this
run's flush failed — a *concurrent session* appending between the flush and
the walk produces a non-empty spool on a perfectly successful run, so the
inferred value would report `refused` on a healthy ledger. The producer knows
the outcome; the reader cannot reconstruct it. Pass it.

---

## 7. Tests

All in `plugins/self-learn/cli/tests/`, new file `test_refread.py` unless
noted. Every test states the mutation it kills — a test that passes against
the broken code is not a test.

### T1 — kind schema validation

| # | Assertion | Kills |
|---|---|---|
| T1.1 | `"reference-read" in telemetry.EVENT_KINDS` | forgetting the registration |
| T1.2 | `telemetry.SCHEMA_VERSION == 3` | the un-bumped set (`telemetry.py:63-67`) |
| T1.3 | `"reference-read" not in telemetry.NOTE_KINDS` | making it model-emittable |
| T1.4 | `telemetry note reference-read` exits non-zero, and no event is spooled | a `NOTE_KINDS` bypass in the verb |
| T1.5 | `spool_event("reference-reads", ...)` still raises `TelemetryError` | a widened/opened kind check |
| T1.6 | a `reference-read` with a **dict** payload value raises (`telemetry.py:174-181`) | the scalar guard being bypassed for this kind |

### T2 — emission fixture

Fixture file: `tests/fixtures/posttooluse_read_reference.json`, a **real**
captured `PostToolUse` payload (§9.1), including its `tool_response.file.content`.

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T2.1 | hook fed the reference-read payload | **exactly one** event; `ref_target`/`scope`/`bucket` correct | a hook that emits nothing, or emits twice |
| T2.2 | hook fed a payload whose `file_path` is an ordinary source file | **zero** events, `rc=0` | a prefilter that fires on every Read |
| T2.3 | payload with an `agent_id` key | `subagent: true` | dropping subagent coverage — the reason (a) was chosen (§3) |
| T2.4 | payload **without** `agent_id`, all other ids identical to T2.3 | `subagent: false` | keying on session/transcript/cwd/prompt ids, which do not differ (§2.7) |
| T2.5a | `jq` absent from `PATH`, **`self-learn` present** | `rc=0`, nothing on stdout, zero events | a build guarding only `self-learn` |
| T2.5b | `self-learn` absent from `PATH`, **`jq` present** | `rc=0`, nothing on stdout, zero events | a build guarding only `jq` |
| T2.5c | **`timeout` absent**, `jq` + `self-learn` both present | `rc=0`, nothing on stdout, zero events | the §4.2-5 wrapper turning a missing binary into the non-zero exit §4.2-1 forbids |
| T2.6 | `--path` naming a `references/*.md` under **no registered host** | zero events, `rc=0` | a CLI that emits on any path shaped like a reference |
| T2.7 | the emitted line contains **no** absolute path | — | leaking `$HOME` (§5.3) |

**T2.1 must carry its positive control**: assert the fixture payload
*itself* contains the reference path, so a fixture that silently stopped
matching cannot read as "correctly emitted nothing" — the
`lrn-ea833a5b` shape.

### T3 — aggregation

Synthetic tracked-plane events + a ledger with known reference-routed records.
**These events are hand-authored, so T3 joins against keys the test itself
wrote** — it can never catch an emit/aggregate divergence. That is T9's job,
and T3 is not a substitute for it.

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T3.1 | 3 events on one target across 2 distinct `session` values, all in-window | `reads_30d == 3`, `read_sessions_30d == 2` | counting raw events as the rate (§6.2-2) |
| T3.2 | one event dated exactly `today - 30d`, one at `today - 31d` | the 30 d one is in-window, the 31 d one is not; `reads_all_time` counts both | an off-by-one window boundary |
| T3.3 | events on two targets | rows are per-target, `reads_30d_total` is their sum | a single global counter |
| T3.4 | 2 of 4 events carry `subagent: true` | `subagent_reads_30d == 2` | dropping the field on aggregation |
| T3.5 | a target read 60 d ago and never since | `zero_read == false`, `reads_30d == 0`, `last_read` set | conflating cold with unread (§6.2-3) |
| T3.6 | a malformed/hand-edited `reference-read` line (missing `ref_target`) | skipped, no crash | a strict parse — `read_events` is documented lenient (`telemetry.py:394-397`) and `recurrence_suspects` (`report.py:218-222`) sets the precedent |
| T3.7 | a target with events but **no** live record | present in `targets`, `records == 0` | ledger-only enumeration (§6.2-4) |
| T3.8 | events dated 12 d and 40 d ago | `observation_start` is the **40 d** event's `ts`; with zero events it is `None` | defaulting it to `today`, the install date, or the window start (§6.2-7) |

### T4 — ids-only scan, proving no content leakage

The load-bearing test. **Positive control first**, per the repo's own rule.

1. Build a payload whose `tool_response.file.content` contains a distinctive
   canary `CANARY-<random hex>`, a secret-shaped literal, and whose
   `tool_input.file_path` is an absolute path under a temp `$HOME`.
2. **T4.0 (positive control):** assert the canary IS present in the payload
   handed to the hook. Without this, T4.1 passes when the fixture is empty.
3. **T4.1:** the canary appears in **no** spooled line.
4. **T4.2:** no spooled line contains the secret-shaped literal, nor `/home/`,
   nor the absolute `file_path`.
5. **T4.3:** the emitted event's key set is **exactly**
   `{ts, kind, actor, schema_version, nonce, ref_target, scope, bucket,
   subagent, session}` — an equality assertion, not a subset one, so a future
   field added without a spec change fails here.
6. **T4.4:** `agent_type` is absent even when the payload carries it (§5.3).
7. **T4.5 (source-level):** the hook script contains no reference to
   `tool_response` — the structural guarantee of §4.2-2, asserted as text.

**T4.6 — the project-scope leg (§5.2.1). Required; T4.1–T4.5 are skill-scope
shape only and cannot see this class.**

8. **T4.6.0 (positive control):** build a **project-scope** fixture whose
   bucket directory is a real mangled slug of the temp `$HOME`
   (`<temp-home-with-dashes>-<8hex>`). Assert the slug **is** present in the
   bucket directory name and that it contains the home segment — so T4.6.1
   cannot pass against a fixture that never had the hazard in it.
9. **T4.6.1:** no spooled line contains **any** home-derived segment — assert
   against a *list*: the temp `$HOME` verbatim, its `/`→`-` transform, the
   literal `-home-`, and the readable half of the slug. Each is a separate
   assertion so a failure names which encoding leaked.
10. **T4.6.2:** the emitted `bucket` is **exactly the 8-hex digest**
    (`^[0-9a-f]{8}$`) and `ref_target` matches
    `^project:[0-9a-f]{8}/references/`.
11. **T4.6.3:** the digest equals `sha256(resolved project path)[:8]` computed
    independently in the test — not read back from `hosts.slug_for`, so a bug
    in the helper cannot make the test agree with itself.
12. **T4.6.4:** the same read via `report.gather` produces a row whose
    `ref_target` equals the emitted one (the §5.2.1 half of T9's round trip,
    at project scope).

Kills: any variant that scrubs content instead of never touching it, any
absolute path **or path-derived slug** in the ledger, and silent field growth.
T4.6 specifically kills the shape that passes T4.2 and the repo's pre-push
scan while still publishing the user's home path.

### T5 — zero-read visibility

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T5.1 | ledger with 1 live reference-routed record, **zero** events, hook installed+registered | a `targets` row for that target with `reads_all_time == 0`, `zero_read == true`; `targets_zero_read == 1`; `records_on_zero_read_targets == 1` | **rendering only targets that have events** — the omission defect (§6.4) |
| T5.2 | same | `render_text` output **names the target path** and its record count | a bare count with no name |
| T5.3 | one zero-read target and one well-read target | the zero-read row is **first** | ordering that buries the signal (§6.2-5) |
| T5.4 | 14 records on one zero-read target | `records_on_zero_read_targets == 14` | counting targets where records were meant |

### T6 — un-instrumented is distinguishable from unread

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T6.1 | hook script absent | `instrumented == false`, `instrument_state == "script-missing"` | a hardcoded `true` |
| T6.2 | script present, **no** settings.json registration | `instrument_state == "not-registered"` | checking only the script |
| T6.3 | settings.json present but **invalid JSON** (the §2.8 incident shape) | `instrument_state == "settings-unparseable"`, **no exception** | a crash, an optimistic `ok`, **or collapsing it into `not-registered`** (§6.3, `selfcheck.py:690-692`) |
| T6.4 | any un-instrumented state | every read-derived field is `None`, **not** `0` | the fail-open that makes a dead hook look like an unused shelf |
| T6.5 | T6.4's text render | contains `ABSENT` and does **not** contain a `0` read count for any target | a render that prints zeros anyway |
| T6.6 | fully instrumented, zero events | `instrumented == true` **and** `zero_read == true` | collapsing the two states into one |
| T6.7 | drive all four `instrument_state` values across four fixtures | each value is reachable; the set of observed values **equals** the documented enum | a dangling enum member no code can produce |

T6 and T5 must both pass **at the same time and stay distinguishable**: T5 is
"the shelf is unread", T6 is "we cannot see the shelf". A build that renders
them identically fails this unit regardless of the other tests.

### T7 — install and selfcheck wiring

| # | Assertion |
|---|---|
| T7.1 | `install.sh` links `hooks/self-learn-refread.sh` into `$HOOKS_DIR` |
| T7.2 | the script is executable and passes `bash -n` |
| T7.3 | a settings.json registration naming `self-learn-refread.sh` with a **dangling** symlink is flagged by `--selftest`'s `hooks` row (§2.5) |
| T7.4 | `README.md` carries the registration snippet **including `"timeout": 5`** |

### T8 — path normalization through a symlink (BLOCKER 1)

The test without which the build ships dead.

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T8.0 | **positive control:** the fixture's symlinked path and its real path are *different strings* and both exist | assertion holds before T8.1 runs | a fixture where the symlink silently is not one, making T8.1 vacuous |
| T8.1 | a skill whose host dir is reached through a **symlink** (`<claude_dir>/skills/<name>` → `<skills_root>/plugins/<p>/skills/<name>`); hook fed a `file_path` **through the symlink** | **one** event, `ref_target` equal to the key computed from the *real* path | comparing unresolved strings — the live `lrn-ea833a5b` shape (§4.1.1) |
| T8.2 | same, but `file_path` given as the **real** path | the **same** `ref_target` string as T8.1 | a key that varies with the route taken to the file |
| T8.3 | a `references/*.md` path containing a `..` segment and a trailing-slash variant | normalizes to the same key | naive string handling |

### T9 — emit→aggregate round trip (BLOCKER 2)

The only test that joins **real** emit output against **real** aggregate
output; every other test authors one side itself.

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T9.1 | route a record to `reference`; resolve it via `selfcheck._reference_target_for`; feed **that exact path** through the hook path; then run `report.gather` | the emitted `ref_target` **equals** the key `gather` computed for that same record, and the target's `records >= 1` with `reads_all_time == 1` | a one-character divergence between the two sides, which otherwise renders as §6.2-4's legitimate "events but no live record" row |
| T9.2 | source-level: `refread.resolve_ref_target` is the **only** definition of the key shape; `report.py` imports it rather than re-deriving, and no caller re-splits `RefTarget.key` to recover `scope`/`bucket` | — | a second copy of the mapping reappearing later |

### T10 — the inner timeout keeps fail-open reachable (MAJOR 5)

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T10.1 | a stub `self-learn` on `PATH` that sleeps well past the bound | hook returns **`rc=0`** within the inner budget (< the harness's 5 s) | delegating the bound to the harness, where a kill makes `exit 0` unreachable (§4.2-5) |
| T10.2 | same | nothing on stdout | a timeout path that prints |
| T10.3 | source-level: the CLI invocation is wrapped in `timeout` | — | the wrapper being dropped later |

### T11 — stdout silence on every path (MAJOR 1)

| # | Stimulus | Expect |
|---|---|---|
| T11.1 | each of: successful reference read · prefilter miss · `jq` missing · `self-learn` missing · CLI non-zero exit · CLI timeout | stdout is **empty** in all six |
| T11.2 | the successful-read case | stderr may carry diagnostics; stdout still empty |

Kills: an instrument that speaks into the session on the critical path of a
reference read, perturbing the behaviour it measures (§4.2-7).

### T12 — flush state is visible (MAJOR 6)

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T12.1 | events in the **spool** only, flush **refused** (`ScanRefusal`) | `flush_state == "refused"`; the text render says the counts are a **lower bound** | a silent swallow (`cli.py:1756-1763`) rendering `zero_read: true` on real reads |
| T12.2 | `report.gather()` called directly, no flush | `flush_state == "not-attempted"` | defaulting to `ok`, which is what every direct-`gather` test would otherwise assert |
| T12.3 | normal `report` verb path with a clean flush | `flush_state == "ok"` and spooled events are counted | reading the tracked plane without flushing |

### T13 — zero enumerable targets (MAJOR 7)

| # | Stimulus | Expect | Kills |
|---|---|---|---|
| T13.1 | a ledger whose **only** reference-routed record is **user scope** (`_reference_target_for` returns `None`) | `targets_total == 0`, `enumeration_state == "none-enumerable"`, and `targets_zero_read` / `records_on_zero_read_targets` are **`None`, not `0`** | zeroed alarm scalars reading as "no problem" when nothing was enumerable |
| T13.2 | same | `unresolvable_records == 1` and the record id appears in `unresolvable_record_ids` | dropping unresolvable records silently from the walk (the names say **records**, because that is what they hold) |
| T13.3 | same | the text render **states the condition** and prints no zero counts | a render that prints zeros anyway |

---

## 8. Out of scope

Non-empty and binding. Each of these must be **reported, not built**.

1. **The cap rework itself (unit #1).** No threshold, no budget signal, no
   refusal behaviour, no change to the existing over-cap WARNING. This unit
   is its precondition, not its first half.
2. **Every routing-gate change (unit #6).** T2/T3/T3a/T4 wording, the tier
   model, the destination enum, `routing-doctrine.md` — untouched.
3. **Reopening S-23.** This unit builds the *instrument*; S-23's condition is
   instrumented **and measured to work**. Amending `03-decisions.md` is a
   later, human-directed step and must not ride this commit.
4. **Repairing `~/.claude/settings.json`.** The 2026-08-23 breakage (§2.8)
   **has already been repaired** and is not a live condition; nothing here is
   parked on it. Stated so no builder treats §2.8 as a work item: it is
   motivation for §6.3's `settings-unparseable` state, and that state is the
   only deliverable it produces. Editing user config is not a builder's call
   in any case.
5. **Instrumenting the other Class-B surfaces** — skill bodies, pathed-rule
   firing, hook fires. Named as siblings so the gate knows they were seen.
6. **`Grep`/`Glob` observation.** A reference file matched by a search is not
   a read. That is S-24's acknowledged residual and stays open.
7. **Backfilling historical reads.** Structurally impossible — §2.6 proves
   the transcripts never carried the fact. `observation_start` exists so the
   absence is legible instead of looking like zero.
8. **`U-pointer`'s reachability emitter**, and any change to
   `selfcheck.py::_check_reach`. This unit *reads* `_reference_target_for`;
   it does not modify it.
9. **The `references/` file format, the compilers, and `reference_target_path`.**
10. **Changing `NOTE_KINDS`, `DECLINE_REASONS`, or any existing kind's
    payload.** Exactly one kind is added.
11. **Migrating the plugin to plugin-provided hooks.** No longer an open
    question: the spec gate **ruled KEEP MANUAL** (§4.4), on the reasoning
    that relocation trades a *detectable* failure for an *unverifiable* one —
    a plugin-registered hook falls outside the `settings.json` scan
    `selfcheck._check_hooks` performs (`selfcheck.py:796-799`), and §6.3's
    `instrument_state` derives one of its two facts from exactly that
    registration. **Stays parked** as a defensible future unit; coupling it to
    an instrument unit is scope creep with a worse failure surface.

---

## 9. Evidence appendix — how §2.6, §2.7 and §2.8 were established

Everything in §2.6–§2.8 was **measured on this host at `b316f1e`**, not
inferred. Reproduce before trusting.

### 9.1 The hook probe

A disposable fixture at `/tmp/hookprobe/`: two marker files, a
`PostToolUse`/`Read` hook appending raw stdin to a log, and a settings file
passed with `--settings` so **no persistent config was modified**. Driven by
one headless run:

```sh
claude -p --settings /tmp/hookprobe/settings.json \
  --permission-mode bypassPermissions --model sonnet \
  '(1) Read /tmp/hookprobe/target/PARENT_REF.md yourself.
   (2) Launch ONE subagent (general-purpose, haiku) to Read
       /tmp/hookprobe/target/CHILD_REF.md.'
```

**Result — 2 hook invocations for 2 reads.** Parent invocation top-level
keys:

```
cwd, duration_ms, effort, hook_event_name, permission_mode, prompt_id,
session_id, tool_input, tool_name, tool_response, tool_use_id, transcript_path
```

Subagent invocation: the same **plus `agent_id`, `agent_type`**; `session_id`,
`transcript_path` and `cwd` byte-identical to the parent's. Both carried
`tool_input: {"file_path": "<abs>"}` and a `tool_response` of the form
`{"type":"text","file":{"filePath":…,"content":"<entire file>",…}}`.

**The same session's transcript, enumerated block by block:**

```
L14 TOOL_USE   name=Read  input={"file_path": ".../PARENT_REF.md"}
L15 TOOL_RESULT ...
L18 TOOL_USE   name=Agent input={...}
L19 TOOL_RESULT -> "The first line of .../CHILD_REF.md is: ..."
```

— **no `Read` tool_use for the child file anywhere.** `isSidechain: true`:
zero occurrences, in this file and in all 227 transcripts under
`~/.claude/projects` (the sweep was re-run with a `./*/` guarded glob after
a bare `*/*.jsonl` returned a false zero — the project directories begin with
`-`, which `ls`/`grep` parse as options).

**`digest_transcript` run on that transcript** returned, for the parent's own
Read:

```
[result L15 Read ok] 1	# parent reference target ⋯ 3
```

Both marker filenames do appear elsewhere in the digest — **only because the
prompt text named them**, which is not a mechanism an instrument can rely on.

### 9.2 The cost measurements

100 invocations each against a 40 173-byte payload; 5 invocations for the CLI:

```
jq-extract prefilter                              3.06 ms/call
pure-bash glob prefilter                          1.70 ms/call
self-learn via ~/bin/self-learn (uv wrapper, warm)  72.0 ms/call
uv run --project … (same wrapper, explicit)        105.4 ms/call
```

The blocking behaviour (tool result withheld until every matching hook exits;
a 6 s hook delayed `tool_result` by 6.05 s; hooks under one matcher run in
parallel) was measured in a separate isolated-config run (§9.3).

### 9.3 Documentation corroboration

An independent agent checked the published Claude Code hooks documentation
and reproduced the behaviour in an isolated `CLAUDE_CONFIG_DIR`. It confirms:
subagent tool calls fire the same hooks and carry `agent_id`/`agent_type`;
`tool_response` is the tool's output (a **structured object** for `Read`, not
the plain string the docs' Bash example shows — parse defensively); a matcher
of only letters/digits/`_`/`-`/spaces/`,`/`|` is an **exact** string, other
characters make it an unanchored JS regex; `PostToolUseFailure` is a separate
event carrying `tool_error`; the default `command` hook timeout is **600 s**;
and plugin-provided hooks are supported via `hooks/hooks.json` at the plugin
root or a `hooks` key in `plugin.json`. Raw captures were left at
`misc/hook-probe-2026-08-23/` (git-ignored).

### 9.4 The settings.json incident (2026-08-23) and its repair

Measured twice while the spec was being drafted, with a positive control on a
known-good JSON file (`plugin.json`, `rc=0`):

```
$ python3 -m json.tool ~/.claude/settings.json ; echo rc=$?
Expecting ',' delimiter: line 43 column 16 (char 888)
rc=1
```

Re-measured the same day, after the file was repaired by someone else:

```
$ python3 -m json.tool ~/.claude/settings.json ; echo rc=$?
rc=0
```

Both readings stand: the breakage was real, and it is over. The spec keeps it
as **motivation for §6.3's `settings-unparseable` state**, not as a live
condition. Repair was **never this unit's work** (§8-4).

---

## 10. Code-gate attention — carried forward from the spec gate

The spec gate's delta review raised two items it filed as *"Also noted, no
finding"* — builder's choices it wanted the **code gate** to see deliberately
rather than discover. Both are reproduced **verbatim** below, each followed by
how this spec discharges it. The code gate should check the build against the
discharge, not merely against the note.

### 10.1 The helper's return shape

> §4.1.2's `target_key` returns `str | None`, but §5.2 emits `scope` and
> `bucket` as separate fields — the emit side must either get them from a
> sibling accessor or re-split the key string, which §4.1.2's own "neither
> re-derives the shape" rule discourages. Builder's choice; flagged so the
> code gate sees it deliberately.

**Discharged in §4.1.2 — and no longer a builder's choice.** The helper is
`refread.resolve_ref_target(home, abs_path) -> RefTarget | None`, where
`RefTarget` is a `NamedTuple` carrying `key`, `scope` and `bucket`. The emit
side reads the three components off one return value; **it neither re-splits
`key` nor re-derives the parts**. T9.2 asserts the no-re-split rule at source
level. A build that returns a bare `str` and parses it back apart fails this
unit even if every other test is green — re-splitting is the second producer
B2 exists to remove, wearing a different hat.

### 10.2 `flush_state`'s plumbing path

> §6.7's `flush_state` has no stated plumbing: `gather(home, *, today=None)`
> (`report.py:250`) cannot observe the flush, and `_flush_spool_best_effort`
> (`cli.py:1747-1766`) returns `None`. The caller must pass the outcome in.
> §6.7's own wording implies this; not a defect, but the code gate should
> reject any implementation that infers `flush_state` by inspecting the spool
> at gather time (a concurrent session's spool write would misreport
> `refused`).

**Discharged in §6.7 — now a three-step normative path.**
`_flush_spool_best_effort` returns the outcome it already distinguishes at
`cli.py:1760`/`:1762`/`:1764`; `_cmd_report` (`cli.py:1736-1744`) captures it
and passes it to `gather` as a keyword-only argument defaulting to
`"not-attempted"`; `gather` stores it verbatim. **Inference from the spool is
explicitly rejected**, for the reason the gate names: a concurrent session's
append makes a healthy run look `refused`. The code gate should read that as a
hard rejection criterion, not a preference.
