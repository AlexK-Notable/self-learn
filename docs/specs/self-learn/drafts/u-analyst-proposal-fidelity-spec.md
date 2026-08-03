# Spec — U-analyst: proposal fidelity + `cwd=home`

Status: **DRAFT, not gated.** Unit `U-analyst` of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2, Wave 1). Register row **FW-41**.
Design reference: `misc/routing-procedure-r2.md` §4(d) items 1–2 (B2/B3).

**File this unit may change: `plugins/self-learn/cli/src/self_learn/analyst.py`**
(plus its tests). Four other units are building concurrently in
`worker.py`, `ledger_ops.py`, `selfcheck.py`, `telemetry.py`, `verbs.py`,
`miner.py`. Nothing here needs any of them — see §5.

Every line number below was re-read against master this session; two of
r2's own claims did not survive that check and are corrected in §1.1.

---

## 1. The defect

`analyze()` parsed the model's YAML (then `analyst.py:195`, now
`analyst.py::_parse_yaml_map`'s call site at `:218`) and then **rebuilt
a new mapping from an enumerated key set** (then `:196-211`; that code is
gone — replaced by the copy-then-stamp at `analyst.py::analyze`, currently
`:226-247`, per §2.1 below) instead of carrying the parsed one. The
enumeration that was deleted:

- copied unconditionally — `destination`, `alternates`, `rationale`
- copied iff non-`None` — `variant`, `rules_topic`, `rules_paths`
- CLI-stamped — `model`, `analyzed_at`, `record_sha`

Anything else the model emitted was dropped between the parse (then
`:195`, now `:218`) and the validate (then `:213`, now `:244`).

**The known casualty is `hook` (FW-41), and the analyst's own system
prompt is what asks for it.** The doctrine file is passed as
`--append-system-prompt` (`analyst.py:139-140`); doctrine §5.1
(`routing-doctrine.md:191-232`) tells the model a `destination: hook`
proposal carries `hook:` + `examples:`, and §7's S-10 amendment
(`routing-doctrine.md:278-284`) restates it for a bare `--route`
specifically.
`_validate_hook_extension` (currently `ledger_ops.py:482-587`, requirement at
`:499-503`) then *demands* both. The rebuild dropped them in between.

**Measured pre-fix** (shimmed `subprocess.run`, a doctrine-conformant
hook proposal in):

```
HOOK    -> AnalystError: analyst proposal invalid: a hook proposal carries
           the structured compile input — hook: {tools, path_regex,
           deny_message} (02 §1 hook extension)
UNKNOWN -> OK keys=['alternates','analyzed_at','destination','model',
           'rationale','record_sha']    # `recommendation:` + `gates:` gone
```

So a hook analysis can never succeed. `teach --route` reports the model's
*correct* output as invalid and falls back to a pending capture
(`teach.py:677-685`, exit 4). The second line shows the same mechanism
eating r2's incoming `recommendation:`/`gates:` keys, and doctrine
(`routing-doctrine.md:155`) offers a `diff:` field that was eaten too.

**The bug is the enumeration, not its membership.** Widening the key set
fixes today's casualty and re-arms tomorrow's: `U-composer` adds gate
fields to the doctrine, and they would vanish on arrival.

### 1.1 Two r2 claims that are false — measured, do not build to them

- **r2 §6 row B2, "junk keys still refused by validator" — FALSE when
  measured 2026-08-02.** `validate_proposal` (`ledger_ops.py::validate_proposal`,
  currently `ledger_ops.py:1252-1309`) checked named keys only; there was
  no unknown-key rejection anywhere in it. Measured then: a proposal
  carrying `banana: {...}`, and one carrying `gates:`/`flags:`/
  `recommendation:`, both validated clean.

  **Correction, 2026-08-03 — half of that measurement no longer holds.**
  `U-schema` (merge `176eee6`) landed `ledger_ops.py::_validate_gates`
  (currently `ledger_ops.py:819-1251`), which `validate_proposal` now
  calls unconditionally. Re-measured today with the same fixture shape
  (`proposal_dict()` from `tests/support.py` plus each key under test):
  `banana: {...}` — and any other key outside `_validate_gates`'s
  vocabulary — **still validates clean**; no general unknown-key rejection
  exists, so r2 §6 row B2 is still false for the general case. But
  `flags:`/`recommendation:` are no longer inert: `_validate_gates` checks
  them against the closed sets `TRACE_FLAGS`/`TRACE_RECOMMENDATIONS` and
  raises `ProposalError` for an out-of-set value (measured:
  `flags: ["not-a-real-flag"]` → `"flag 'not-a-real-flag' is outside the
  closed set [...]"`), and a `gates:` mapping is checked against the
  required `TRACE_GATE_KEYS` shape (`g0`, `t1`, `t2`, `t3`, `t3a`, `t4`,
  `tn`, `e1`, `outcome`, each with their own required nested fields) and
  refused if malformed (measured: `gates: {"nonsense": 1}` →
  `"gates has unknown key(s) ['nonsense'] — allowed: [...]"`). So: a
  proposal carrying **bogus** `gates:`/`flags:`/`recommendation:` no
  longer validates clean — it did when this spec was written, before
  `U-schema` shipped the decision-trace schema. A test asserting "junk is
  refused" would still fail for an arbitrary unknown key like `banana`,
  but would now correctly PASS for an out-of-set `flags:`/
  `recommendation:` value or a malformed `gates:` mapping. Do not write a
  blanket "junk is refused" test; do write one pinning the closed-set
  refusal for `flags:`/`recommendation:`/`gates:` specifically, since
  that's the part that's real now.
- **r2 §4(d).2, strip "only what the CLI owns (`record_sha`)" — incomplete.**
  `script` is the one key this codebase refuses from a model on every
  other path (`ledger_ops.py::_validate_hook_extension`, currently
  `:490-495`; `ledger_ops.py::stamp_proposal`'s overwrite, currently
  `:1441-1444`; `verbs.py::_prepare_one_motion_hook`'s overwrite,
  currently `:1159`)
  and the doctrine anticipates the model emitting one anyway — *"you never
  write executable bytes; any `script:` you emit is overwritten at
  stamping"* (`routing-doctrine.md:195-196`). Register R strips it.

---

## 2. The change

Replace the rebuild with a copy-then-stamp.

### 2.1 Register R — key ownership

**The only enumeration in this document. Normative.**

| Keys | Owner | What `analyze()` does |
|---|---|---|
| `model`, `analyzed_at`, `record_sha` | CLI | assigned **after** the copy, unconditionally overwriting whatever the model emitted |
| `script` | CLI (refused from the model) | removed from the copy — **unconditionally, and before `validate_proposal`** (A4(b)) |
| everything else | the model | carried verbatim into the returned dict |

**R is complete because it does not enumerate the proposal's legitimate
field set — and no correct version of it ever will.** That set has exactly
one authority, `ledger_ops.validate_proposal`, which `analyze()` already
calls at `analyst.py:244`. Restating it here *is* the defect. A builder or reviewer
tempted to extend R with "…and also carry `hook`, `examples`, `gates`" has
reintroduced the bug in a new location.

Two consequences to accept rather than work around:

- `alternates` becomes **absent** when the model omits it, rather than
  present-as-`None`. `validate_proposal` treats those identically
  (`ledger_ops.py:1275-1276`) and no consumer indexes it — `teach.py:686-694` reads
  `destination` and `.get("rationale")`, then hands the whole dict to
  `route_direct` as `hook_input`.
- A malformed *optional* field now **refuses** instead of vanishing (e.g.
  `already_canon: "yes"` → `ProposalError` → `AnalystError` → the
  never-lost pending capture). That is the intended trade: loud and
  recoverable beats silent data loss.

### 2.2 `cwd=home`

`subprocess.run` (then `analyst.py:182-184`, now `:205-207` — which now
DOES pass `cwd=str(home)`, this unit's own shipped fix) passed no `cwd=`
(measured then: kwargs were exactly `capture_output`, `text`, `timeout`),
so the analyst inherited
the invoking shell's working directory — for `teach --route` that is
whatever repo the user happened to be standing in. The worker pins
`cwd=str(home)` (`worker.py:377`, `:1376`). `analyze()`'s `home` parameter
was **referenced nowhere in its body at write time**; this was the use it
was written for, and it is now that use — `home` is referenced at the
pre-spawn guard and the `cwd=str(home)` call described above.

What the inherited cwd costs, in order of severity:

1. **Ambient project context.** `claude -p` loads project-scope
   instruction surfaces from its working directory — the project
   `CLAUDE.md` and `.claude/rules/*`. The campaign's own canary tests pin
   this: injection is live and lazy on file access (§7, 2026-07-28), and
   user-level `paths:` globs resolve **relative to the session's working
   directory** (§6). So today an unrelated repo's instructions can reach a
   routing judgment the CLI is supposed to own.
2. **No determinism, no worker parity.** The same record analyzed from two
   directories is two different runs. r2 §0's architectural move (CLI
   computes the evidence, model judges over it) assumes ambient context
   does not vary — r2 §2(b) says so in as many words.
3. Relative `Read`/`Grep`/`Glob` resolution. Least important: the doctrine
   confines residual tool use to absolute paths.

**The failure mode the pin introduces.** `subprocess.run(cwd=…)` raises
`FileNotFoundError` when the directory is missing and `NotADirectoryError`
when the path is a file (both measured). The existing handler (then
`:185-186`, now `analyst.py:208-209`) would relabel the first as
*"claude CLI not found on PATH"*; the second is caught by nothing and
escapes `analyze()`, breaking the module contract — *"any failure … raises
AnalystError"* (docstring `:35-38`, unchanged) — that `teach.py`'s
never-lost fallback depends on, since it catches `analyst.AnalystError`
only (`teach.py:677`).

So `analyze()` gains a pre-spawn guard: `home` must be an existing
directory, else `AnalystError` naming it. Same posture and placement as
the doctrine guard already at (then `:171-175`, now `analyst.py:180-184`).

`is_dir()` alone does not close the class: a home that exists and *is* a
directory but is not searchable (mode without `x`) makes `subprocess.run`
raise `PermissionError` — measured — which, like `NotADirectoryError`, is
caught by nothing and escapes `analyze()`. The guard therefore requires a
directory the process can **enter**: `Path(home).is_dir() and
os.access(home, os.X_OK)`, else the same `AnalystError` naming the path.

---

## 3. Acceptance

**Criteria win over §1–§2 prose on any conflict.**

All exercised at the `analyst.analyze()` seam through the existing PATH
shim (`test_route_cli.py::claude_shim`, currently `:158-177`): the real `subprocess.run`, the real
shipped doctrine text, model output controlled by `CLAUDE_SHIM_OUT`.

**A1 — unknown-field round-trip. This is the campaign §5 positive
control.** The shim emits a valid `skill-md` mapping plus keys that appear
nowhere in `analyst.py` and nowhere in `validate_proposal`: `recommendation:
defer` (r2's incoming key) and a synthetic `probe_key`. `analyze()` returns
both, with values equal to those emitted. *A test that only round-trips
fields the analyst already knows about passes just as happily on the
broken code — mutation M1b below is the proof.*

**A2 — hook round-trip (FW-41).** The shim emits a full §5.1 hook
proposal; `support.hook_proposal_fields()` supplies the block and examples.
`analyze()` returns without raising, and the returned `hook` and
`examples` compare `==` to the emitted ones. Today this raises.

**A3 — CLI-owned fields win.** The shim emits `model: pwned-model`,
`analyzed_at: 1999-01-01T00:00:00Z`, and `record_sha: sha256:deadbeefdead`
(valid shape, wrong value). Returned: `model == DEFAULT_ANALYST_MODEL`,
`record_sha == sha_anchor(record.body)`, `analyzed_at !=
"1999-01-01T00:00:00Z"`. The wrong-but-schema-valid emitted values are the
control — with matching values the assertions could not tell a stamped
field from a carried one.

**A4 — `script` is refused, not carried. Parametrized over two
destinations.** (a) the shim emits a hook proposal that *also* carries
`script: "#!/usr/bin/env bash\necho pwned\n"` and a `probe_key`; (b) the
shim emits A1's `skill-md` mapping plus the same `script` and `probe_key`.
In both cases `analyze()` returns without raising; assert `"script" not in
proposal` **and** `proposal["probe_key"] == …`. The second assertion is
what stops the first passing vacuously: an absence assertion alone stays
green on a build that carries nothing at all. **Case (b) is what makes the
strip unconditional and pre-validation** — `validate_proposal` refuses
`script` on a non-hook destination (`ledger_ops.py::_validate_hook_extension`,
currently `:490-495`), so a build
that pops `script` only when `destination == "hook"`, or that pops it
below `validate_proposal`, turns a routable proposal into an
`AnalystError`; case (a) alone cannot see either.

**A5 — the analyst runs in the ledger home.** The test `monkeypatch.chdir()`s
to a directory outside the ledger home, then invokes; the shim records
`pwd -P`. Assert the recorded cwd `== str(Path(home).resolve())`. **The
chdir is the control** — without it the assertion could pass on an
unpinned build whenever pytest's own cwd happened to match.

**A6 — a home that is not an enterable directory refuses pre-spawn.**
Parametrized over a missing path, an existing *file*, and an existing
directory with mode `0o000` (skip that case when `os.geteuid() == 0` —
root ignores the search bit). Assert `AnalystError` **whose message
contains the offending path**.

> Two assertions that must NOT be used here, both fail-open:
> "assert `AnalystError` was raised" — the unguarded build raises it too,
> saying *"claude CLI not found on PATH"*; and "assert the shim never ran"
> — on the unguarded build the exec fails before the shim runs either way,
> so the log is absent on both builds. The message assertion is the test.

### 3.1 Mutation plan

Each row is a one-line edit to `analyst.py`. A blind reviewer will run them.

| # | Mutation | Test that must fail |
|---|---|---|
| M1a | restore the rebuild: `proposal = {k: parsed.get(k) for k in ("destination", "alternates", "rationale")}` | **A1** (also A2, A4 — this mutation *is* the shipped defect) |
| M1b | widen instead of remove: the same rebuild over `("destination", "alternates", "rationale", "hook", "examples")` | **A1 and A4 (both lose `probe_key`) — A2 stays green.** The mutation the positive-control rule exists for |
| M2 | add `proposal.pop("hook", None)` after the copy | A2 **and A4** — both emit a hook proposal, so both raise |
| M3 | delete `proposal["record_sha"] = sha_anchor(record.body)` | A3 |
| M4 | delete `proposal.pop("script", None)` | A4 |
| M4b | strip conditionally: `if proposal.get("destination") == "hook": proposal.pop("script", None)` | **A4(b) only — A4(a) stays green** |
| M4c | move `proposal.pop("script", None)` below `validate_proposal(proposal)` | **A4(b) only** |
| M5 | delete `cwd=str(home)` from the `subprocess.run` call | A5 |
| M6 | delete the home-is-a-directory guard | A6 |
| M6b | weaken the guard to `Path(home).is_dir()` alone | A6, the mode-`0o000` case only |

**M1b is the load-bearing one.** A reviewer who runs it and finds A2 still
green has directly verified that this unit fixed the enumeration rather
than its membership.

---

## 4. Builder decisions, made here rather than left open

- **Where the tests live:** `tests/test_route_cli.py`, in its existing
  *"teach --route (analyst path)"* section (currently `:277`) — it owns the shim and
  every other analyst test. They call `analyst.analyze(env.home, record)`
  directly rather than through `cli.main`: the CLI path would additionally
  need the `one_motion_route: {hook: true}` opt-in (`verbs.py::one_motion_allowed`,
  currently `:197-203`)
  before a hook proposal is observable at all, and that gate is not this
  unit's subject (§5).
- **Shim change:** `CLAUDE_SHIM` (currently `test_route_cli.py:47-52`) gains
  `pwd -P > "$CLAUDE_SHIM_CWD"`; the `claude_shim` fixture sets
  `CLAUDE_SHIM_CWD` and returns the path. **`pwd -P`, not `pwd`** — bash
  seeds `$PWD` from the inherited environment, so the plain builtin can
  report the parent's directory. The added line is inert for the existing
  tests, which read only the argv log.
- **Strip `script`, do not overwrite it.** The analyst is not the
  generator: `_prepare_one_motion_hook` assigns `data["script"]` itself
  (currently `verbs.py:1159`) and `stamp_proposal` does the same for on-disk
  proposals (currently `ledger_ops.py:1441-1444`). The strip is **unconditional and
  above `validate_proposal`** (A4(b)), so no model-authored `script`
  reaches the validator, the return, or any caller — the copy holds it for
  the one statement between, which a filtered copy would avoid and which
  is observably equivalent; either shape satisfies R.
- **Guard placement:** beside the doctrine guard at (currently `analyst.py:180-184`), before
  `read_text` — same pre-spawn posture. `Path(home)` first; the signature
  admits `str`. `os` is already imported (`:48`), so `os.access` needs no
  new import.
- **Keep the three CLI-owned assignments literal and after the copy**, so
  the overwrite is textually obvious. No `setdefault`, no dict-merge
  cleverness — `setdefault` would silently invert R's first row.
- **Change no prompt text.** See §5.

---

## 5. Out of scope

- **`_PROMPT_TEMPLATE` (currently `analyst.py:85-101`) is a second enumeration of the same
  set** — it lists `destination`/`alternates`/`rationale`/`variant`/
  `rules_topic`/`rules_paths` and never mentions the hook block, so the
  user-prompt side advertises a narrower schema than the doctrine's §5.1
  gives the model. Real, and **U-composer's** (r2 B6: the analyst adopts
  the shared composer's single-record form). Flagged here so U-composer
  does not copy a field list into the composer and recreate this defect a
  third time.
- **The S-10 authorship split does not fully close with this fix.**
  `one_motion_allowed` (currently `verbs.py:197-203`) still refuses `hook` in one
  motion unless the committed ledger `config.yaml` opts in. After this
  unit, a default-config `teach --route` that comes back `hook` reaches
  `route_direct` and gets the *correct* S-10 refusal with its recipe
  (currently `verbs.py:2356-2370`) instead of a misleading "analyst proposal
  invalid". FW-41's claim — *"can never return `hook`"* — closes; whether
  that proposal then routes is config, not code.
- **`verbs.py` — not edited, but reached.** On a `hook` destination
  `teach.py:694` hands the whole returned dict to `route_direct` as
  `hook_input`, and `_prepare_one_motion_hook` secret-scans every byte of
  it (currently `verbs.py:1173`). Widening the carried key set widens that scan —
  the fail-closed direction, no code change — but note a hit exits
  `SecretRefusal` → `EXIT_SCAN` (`teach.py:707-709`), not the never-lost
  pending capture.
- **`worker.py` — verified not affected.** The nightly worker's model
  writes proposal files directly and the CLI validates and stamps them in
  place (`_validate_written`, currently `worker.py:880-944`; `stamp_proposal`,
  currently `ledger_ops.py:1422-1444`). It never reconstructs a proposal, so this
  defect does not exist on that path and nothing here touches it. Stated
  explicitly because a spec that widened this to the worker would collide
  with `U-marker`, building in that file now.
- **`ledger_ops.validate_proposal` — partially superseded, see §1.1's
  2026-08-03 correction above.** This row anticipated that if the campaign
  later wanted unknown top-level keys refused, that would be `U-schema`'s
  call and a different blast radius, refusing the `diff:` field the
  doctrine offers at `routing-doctrine.md:155`. **That did not happen**:
  `U-schema` (merge `176eee6`) added validation for exactly three named
  keys — `gates`, `flags`, `recommendation` — not a blanket
  unknown-key rejection, so `diff:` (and `banana:`, and any other
  unenumerated key) still validates clean today, per §1.1's re-measurement.
- Everything else in r2 §4(d) item 3 (the shared composer, the gate form,
  the doctrine rewrite).
