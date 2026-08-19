# Spec — U-bedrock: the provider surface (Bedrock as configuration and contract)

Status: **r4 — CLEARED FOR BUILD.** Two gate rounds, 22 findings, all
folded. r2 blind gate: **NOT SOUND — 1 BLOCKER / 6 MAJOR / 8 NOTE**;
r3 delta gate: **0 BLOCKER / 1 MAJOR / 6 NOTE**, with fourteen of the
fifteen r3 folds verified clean and several judged **stronger than the
gate's own remedies** (`Doc-0`/`DC15`, `In-d`/`In-b`/`IN5`, `A-0` row 2,
`BK1`'s measured cells, `M19`'s re-aim). Every r4 finding arrived with a
fully-specified remedy and no builder latitude, so the round closed under
the ratified **verdict-repricing rule**: this is the last spec round and
**the code gate downstream verifies the r4 folds**.

**Both rounds found the same shape, and it is worth naming.** r3's
`D-18` established that *a correct mid-rollout install must not be
scolded*. r4's single MAJOR found the one row that had not been taught
it: the `models` row FAILed a `cli` surface for correctly resolving an
Anthropic alias — the value `Mod-3`/`MD4` **require** it to resolve
there. The fold's own principle, one row short. `Doc-i` gates it; `M27`
is the standing guard.

**No factual claim in this spec was ever overturned.** Both gates
reproduced every measurement — `E1`'s string counts, `E5`'s three id
shapes, the `Outcome` shape, `HY2`'s forbidden set, the SDK env-merge
order, both bounded-edit numstats — and r3 re-measured `E11` with a
fourth case of its own (finer-key-nonempty → honored), confirming the
asymmetry cells. All 22 findings were **contract gaps, not errors of
fact**, which is the shape a blind gate is for.

Three of them changed the design rather than its wording:

- **BLOCKER-1** — r2 pinned a **real, copy-pasteable** Bedrock id as
  `DC6`'s negative control, contradicting its own `D-6`. The fixture is
  now `us.anthropic.claude-example-v0:0`, and `D-6`'s "anywhere" is
  narrowed to the surfaces that actually matter (`Id-1a`).
- **MAJOR-2** — `session_env` was **reachable in a type-illegal state**
  (`bedrock` + `cli` + `region=None`) precisely because r2's own `D-18`
  made that combination legitimate. `A-0` row 2 makes the function total.
- **MAJOR-3** — the never-lost conversion **had no owner in product
  code**, so `RT3`–`RT5` were satisfiable by a test double constructing
  the very `Outcome` they asserted. `In-d` gives it a home; `RT3`–`RT5`
  now drive the real backend.

`EV1`'s leak guard was found **triple-covered** and is unchanged.

**Base commit:** `c2669a9` (master — *"chore: sync ui/uv.lock metadata for
the CLI's new [sdk] extra (U-seam follow-through)"*). Every symbol quoted
in this document was read at that commit. `U-seam` (Wave 0) is merged:
`src/self_learn/invocation/` exists and is the seam this unit plugs into.

**Unit `U-bedrock`, Wave 1** of the approved Agent-SDK migration. Wave-1
merge order is **U-sdk → U-bedrock → U-fake**. This spec is written
*before* U-sdk exists, so §3.9's integration contract is stated
**abstractly** and its one wiring call lands at **this unit's build**,
against post-U-sdk master.

**The unit in one sentence.** Add a second, orthogonal switch —
`provider` (`anthropic` | `bedrock`) — as **pure configuration, pure
functions, and one read-only diagnostic**, such that (a) no secret can
enter the ledger, (b) a misconfiguration is refused loudly instead of
producing an opaque model error, and (c) the first real Bedrock failure —
IAM, model access, region enablement — which **no test on this host can
ever reach**, is diagnosable from one command's output.

**This unit makes NO live call and cannot.** This host has no AWS
credentials, no `~/.aws`, and no `AWS_*` in the environment (measured,
`E6`). Nothing here is verified against a live Bedrock endpoint, and the
spec says so wherever it matters rather than implying coverage it does
not have. A builder who finds themselves needing credentials to satisfy a
criterion has left this unit's mandate and must stop and report.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/provider.py` | **NEW.** Complete PUBLIC symbol table (NOTE-8): `PROVIDERS`, `DEFAULT_PROVIDER`, `ProviderResolution`, `ProviderRefused`, `Row`, `resolve`, `resolve_backend_name`, `model_for`, `MODEL_KEY_FOR_SURFACE`, `session_env`, `BEDROCK_ENV_KEYS`, `SMALL_FAST_ENV_VAR`, `BEDROCK_ALIAS_RE`, `preflight`, `DOCTOR_ROWS`, `VERDICTS`. **Root level, not under `invocation/`** — see `P-a`. **Plus one private helper `cli.py` reaches across the module boundary for (code-gate NOTE, fold 2026-08-19): `_handoff_fields(home, rows)`** — `Doc-d`'s handoff-block field builder, called from `_cmd_doctor` with the `rows` `preflight` already computed, precisely so `sdk-version`/`cli-version.*` are read back OUT of those rows (`DC10`'s exactly-once subprocess discipline) rather than recomputed; `credential-mechanisms` is the one field it recomputes fresh via `_credential_mechanisms` rather than parsing the `credentials` row's rendered text, which is a second (cheap, presence-only, non-subprocess, non-network) file-probe per run, not a second subprocess — accepted as-is rather than restructured. |
| `plugins/self-learn/cli/src/self_learn/config.py` | Extend only: `PROVIDER_KEYS`, `provider_setting`, `provider_unknown_keys`, and two names added to `__all__`. `one_motion_enabled` and `invocation_backend` are untouched. |
| `plugins/self-learn/cli/src/self_learn/cli.py` | The `doctor` parser group (`§3.8`), `_cmd_doctor`, and **one** dispatch line. Nothing else. |
| `plugins/self-learn/cli/src/self_learn/selfcheck.py` | `_check_invocation` (new) and **one** row appended to `run_selftest`'s `results` list. |
| `plugins/self-learn/cli/tests/test_provider.py` | **NEW.** `PR`, `BK`, `MD`, `EV`, `NS`, `RT`, `IN`, `HY` criteria land here. |
| `plugins/self-learn/cli/tests/test_doctor_invocation.py` | **NEW.** `DC` criteria land here. |
| `plugins/self-learn/cli/tests/test_lock_invariant.py` | **BOUNDED REGISTRATION EDIT — exactly one line.** One new `_ARGV_FOR` key, `"_cmd_doctor"` (`B-4`). Any other changed line fails `SU2`. |
| `plugins/self-learn/cli/tests/test_selftest.py` | **BOUNDED COUNT EDIT — exactly two lines.** `"all 7 checks green"` → `"all 8 checks green"` at both sites (`B-5`). Any other changed line fails `SU2`. |
| *U-sdk's backend module* (symbol not knowable at spec time) | **BOUNDED WIRING EDIT.** The body of U-sdk's ONE documented provider-env extension point, and nothing else (§3.9, `IN1`–`IN4`). |
| `plugins/self-learn/cli/tests/test_invocation_sdk.py` | **RATIFIED POST-BUILD BOUNDED EDIT — 33 insertions / 7 deletions** (`S-38`). Not sanctioned at spec-write time; added when wiring `IN3`/`Int-1` broke two U-sdk criteria whose premise the wiring itself falsified (`OP11`'s argv-sourced `options.model`, `OP13`'s two-flag closed read set). The code gate adjudicated the rewrite correct on the merits and ratified it as a fifth bounded path. Any other changed line in this file fails the restated `SU2`. |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-36`, `S-37` (§7.5), `S-38` (the ratification above), in the build commit. |
| `docs/specs/self-learn/14-forward-work-map.md` | New rows for §7.3's residuals, plus the now-void U-sdk `A-4` (§3.5's model row: "`options.model` can never be `None`"), in the build commit. |

**No other existing test file may be edited, and the three named above
may be edited only in the ways named.** That is the restated criterion
`SU2` (`S-38`). `worker.py`, `miner.py`, `analyst.py`, `registry.py`,
`contract.py`, `cli.py`'s invocation module, `fake.py` and
`tests/test_invocation.py` are **not** in this table and are not
touched. `plugins/self-learn/ui/**` is untouched (`SU5`).

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced
   by name thereafter. A second definition anywhere in this document is a
   bug in this document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number.
4. Read before this document: `docs/specs/self-learn/drafts/u-seam-invocation-seam-spec.md`
   §3.2 (`Surf-1`), §3.7 (`Reg-1`), §3.6 (`Log-1`); then
   `src/self_learn/invocation/contract.py` and `registry.py`, and
   `config.py`'s `invocation_backend`. This spec quotes them but does not
   reproduce them.
5. **Facts this unit could not verify are in §7.5, the verify-at-build
   ledger, not in §3.** A statement in §3 is one that was measured (§9)
   or is this unit's own construction. If §3 and §7.5 ever appear to
   cover the same fact, §7.5 is the open question and §3 is provisional
   on it.

---

## 1. Why this unit exists

### 1.1 What is true today

There is **one** provider. `worker.build_argv`, `miner.build_reader_argv`
and `analyst.build_argv` each emit `--model <alias>` where the alias comes
from `worker.worker_model()`, `miner.miner_model()` and `analyst._model()`
— all three of the shape
`os.environ.get("SELF_LEARN_<X>_MODEL") or DEFAULT_<X>_MODEL`, with all
three defaults being the string `"claude-sonnet-5"`. Nothing in the CLI
package mentions Bedrock, AWS, or a provider: a repo-wide grep for
`bedrock|Bedrock|SELF_LEARN_PROVIDER|SELF_LEARN_BEDROCK` over
`src/` and `tests/` returns **nothing** (`E4`).

### 1.2 What Bedrock needs, and what it must never be given

Claude Code reaches Bedrock through **process environment**, not argv:
the shipped CLI binary (2.1.226) contains the literals
`CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION`, `AWS_DEFAULT_REGION`,
`AWS_PROFILE`, `AWS_BEARER_TOKEN_BEDROCK`, `ANTHROPIC_BEDROCK_BASE_URL`,
`CLAUDE_CODE_SKIP_BEDROCK_AUTH`, `ANTHROPIC_SMALL_FAST_MODEL` and
`ANTHROPIC_DEFAULT_HAIKU_MODEL` (`E1`). Credentials themselves are **not**
among the things this project supplies: they come from the standard AWS
chain, which the child process inherits.

That last sentence is the whole security design. `~/.self-learn` is a
**git repository the operator commits and pushes**. A design in which any
credential-shaped value can reach `config.yaml` is a design that
eventually commits a secret. So:

> **`SEC-1` (NORMATIVE).** No value this unit reads from `config.yaml` or
> writes to any file may be a credential. Every credential check is
> **presence-only**: the code learns *that* a mechanism exists, never
> *what* it contains. No credential value is read into a variable, and
> nothing derived from one is printed. Criteria `NS1`–`NS5`.

### 1.3 Why a doctor, and not more tests

Everything a test on this host can check about Bedrock is a **string
transformation**. Whether the account has `bedrock:InvokeModel`, whether
the model is enabled in the region, whether the inference profile exists
— none of it is reachable from here, and all of it is where a real
Bedrock rollout actually fails. The doctor is not a nicety attached to
the feature; **it is the only instrument that can observe the failure
class this unit's tests structurally cannot**, and its output is
specified (§3.8) to be pasteable to an AWS administrator who has never
seen this project.

### 1.4 What this unit is not

It is not an `SdkBackend` (that is U-sdk). It is not a live Bedrock
integration — see the header. **It ships no real Bedrock model id in any
default, fixture, or example a user could copy into configuration**
(`D-6`; measured ids quoted as provenance in `E5`/`Id-1a` are evidence,
not configuration). It does not touch the three call sites, the seam's
registry, or the containment data.

---

## 2. What binds this design from outside it

Shipped, currently-green facts. Each removes an option this unit might
otherwise take. A builder who trips one has a red suite, not a
discussion.

**`B-1` — `worker`, `miner` and `analyst` all import `invocation` at
module scope.** Measured: `worker.py` has `from . import invocation,
sentinel, telemetry`; `miner.py` has `from . import gitops, invocation,
sentinel, telemetry, worker`; `analyst.py` has `from . import
invocation`. Therefore **any module that `invocation/` imports at module
scope must not import `worker`, `miner` or `analyst` at module scope**,
or the import graph closes into a cycle. This is what decides `P-a`
(where `provider.py` lives) and `M-c` (deferred delegation imports).

**`B-2` — U-seam's `I-a`/`HY2` forbid `invocation/**` from importing
`worker`, `miner`, `analyst`, `verbs`, `teach` or `ledger_ops`, and
`HY2`'s AST scan is a shipped criterion in `test_invocation.py`**, which
this unit may not edit. `model_for` must delegate to `worker.worker_model`
et al. (a plan requirement). A provider module placed *inside*
`invocation/` therefore cannot satisfy the plan. `P-a` resolves this.

**`B-3` — `config.invocation_backend(home, surface)` returns
`(key, value)`, and `registry.backend_for` never exposes the resolved
backend's NAME.** `backend_for` returns a `Backend` object, or **raises**
`BackendUnavailable` for `"sdk"`. There is no `backend_name_for`. Since
`registry.py` is **not** in this unit's may-touch table, everything that
needs the resolved backend **name** per surface — the `switches` row, the
`rollout` row's four-state verdict (`Doc-f`), and `Rs-c`'s sdk-leg gate —
cannot read the registry's answer directly. `§3.5` resolves this by
**re-deriving** the chain, and `BK1`–`BK4` force the two derivations to
agree.

**`B-4` — `test_lock_invariant.py`'s `_ARGV_FOR` is a fail-closed
registry of every `_cmd_*` in `cli.py`.** `_cmd_functions()` enumerates
`cli` module attributes starting with `_cmd_`, and
`test_every_cmd_surface_is_covered` fails with *"new dispatch surface(s)
with no argv in `_ARGV_FOR`"* for any that is missing. **A new
`_cmd_doctor` therefore REQUIRES a one-line registration in that file.**
This is a registration, not a weakening — and `SU2` bounds it to exactly
that one line.

**`B-5` — `test_selftest.py` pins the selftest row COUNT as a byte
string, twice.** Both `test_selftest_reports_seven_checks_criterion_12`
and the FW-66 decode-safety test assert `"all 7 checks green" in out`.
Adding an eighth row to `run_selftest`'s `results` list **necessarily**
changes both. `SU2` bounds the edit to those two strings; the test
*function name* containing "seven" goes stale and is residual `R-5`.

**`B-6` — the fail-closed lock census (`NOT_REPO_TRUTH`) is root-level
and cares only about filesystem WRITES.** `MODULES = {p.stem for p in
SRC.glob("*.py")}` and `for path in sorted(root.glob("*.py")):` — so
`provider.py` at root **is** inside the census, while `invocation/**` is
not. `provider.py` and the doctor never write to the filesystem
(`HY3`), so **no `NOT_REPO_TRUTH` entry is required or permitted**; an
entry would be a false claim about a function that writes nothing.

**`B-7` — the `sdk` extra is declared but NOT installed in the CLI
venv.** `pyproject.toml` carries
`sdk = ["claude-agent-sdk>=0.2.116,<0.3"]` (U-seam's `R-b`), and
`plugins/self-learn/cli/.venv/**/claude_agent_sdk` **does not exist**
(`E3`). Every CLI-suite run therefore sees the SDK as *not importable*.
Consequence, normative: **the SDK-version probe must be a pure function
of an injected importer** (`§3.8`, `DC4`), or its skew branch is
unreachable by any test in this package.

**`B-8` — `SELECTOR_FOR_SURFACE` already exists in
`invocation/contract.py`** and maps the four surfaces onto the three
selector names `WORKER`, `WORKER`, `MINER`, `ANALYST`. It is the exact
map `model_for` needs for `SELF_LEARN_{WORKER,MINER,ANALYST}_MODEL`.
`Mod-1` **reuses it by import**; re-spelling it here would be a second
definition of a shipped set.

**`B-9` — the baseline.** Measured on `c2669a9` (§9): CLI suite **1716
collected, 1711 passed, 5 skipped, 0 failed**, 178.25 s. Whole-`src`
pyright: **50 errors**. UI suite not run (untouched).

---

## 3. The change

### 3.1 `P-a` — where the provider module lives, and why (NORMATIVE)

`plugins/self-learn/cli/src/self_learn/provider.py` — **root level, a
sibling of `worker.py`, not a member of the `invocation/` package.**

Three forces decide this and they all point the same way:

- `model_for` must call `worker.worker_model()` / `miner.miner_model()` /
  `analyst._model()` under `provider=anthropic` (the delegation
  requirement). Inside `invocation/` that import is forbidden by U-seam's
  `I-a`, enforced by `HY2`, in a test file this unit may not edit
  (`B-2`).
- U-sdk's backend, which lives inside `invocation/`, will import this
  module. Root placement means the import is `from .. import provider` —
  crossing *out* of the package, which `HY2`'s six-name list does not
  forbid — rather than an in-package module that reaches `worker`.
- The lock census sees root-level modules (`B-6`), so `provider.py` is
  **inside** the project's fail-closed write audit rather than in the
  blind spot U-seam had to patch with its own `HY4`. Being audited is
  the better side of that trade for a module that must never write.

**`P-b` — the delegation imports are DEFERRED (NORMATIVE).**
`provider.py` may not import `worker`, `miner` or `analyst` at module
scope. Those three imports live **inside `model_for`'s body**. `B-1`
gives the reason: `worker` → `invocation` → (U-sdk) `..provider` →
`worker` is a cycle, and a module-scope import closes it at interpreter
start. Criterion `HY1`; mutation `M20`.

### 3.2 `Prov-1` — the provider switch (NORMATIVE)

```python
PROVIDERS = ("anthropic", "bedrock")
DEFAULT_PROVIDER = "anthropic"
```

Three rungs, **first hit wins**, mirroring U-seam's chain shape but
shorter because a provider is **install-wide, not per-surface** (`D-2`):

| Rung | Source | Example |
|---|---|---|
| 1 | `SELF_LEARN_PROVIDER` env | `SELF_LEARN_PROVIDER=bedrock` |
| 2 | `config.yaml` → `provider.name` | `provider: {name: bedrock}` |
| 3 | built-in default | `"anthropic"` |

**`Pv-a`** An **empty or unset** value at a rung is "no answer" and falls
through **silently**. Identical to U-seam's `R-a`, for the identical
reason: a stray `export SELF_LEARN_PROVIDER=` must not print a warning on
every invocation. Criterion `PR3`.

**`Pv-b` — fail-closed on an unknown value, toward `anthropic`.**
Anything not in `PROVIDERS` at any rung **warns once on stderr** and
resolves to **`"anthropic"`** — never to `bedrock`, never to the next
rung. `anthropic` is the shipped, tested path; falling to it is the same
direction U-seam's registry falls (`§3.7.2`), and for the same reason.

Two byte-pinned spellings, because the sources differ in kind — this is
U-seam's `R-c` rule applied unchanged:

```
self-learn: unknown provider {value!r} in SELF_LEARN_PROVIDER — using "anthropic"
self-learn: config.yaml ignored — provider.name must be one of anthropic, bedrock; got {value!r} — using "anthropic"
```

The second is emitted **by calling `config._warn(...)`**, never by
re-spelling the prefix — one register, one owner for an operator-facing
string. `_warn` stays private. Criterion `PR4`; mutations `M2`, `M3`.

### 3.3 `Key-1` — the config surface, defined once (NORMATIVE)

`config.py` gains one closed, whitelisted key set:

```python
PROVIDER_KEYS = (
    "name",
    "bedrock.region",
    "bedrock.profile",
    "bedrock.models.worker",
    "bedrock.models.miner",
    "bedrock.models.analyst",
    "bedrock.models.small_fast",
)
```

rendered in `config.yaml` as:

```yaml
provider:
  name: bedrock
  bedrock:
    region: us-east-1
    profile: sandbox-profile
    models:
      worker: <a Bedrock model id or inference-profile id>
      miner: <…>
      analyst: <…>
      small_fast: <…>
```

**`K-a` — every value in this set is a NON-SECRET.** A region name, a
profile *name*, and model ids are all safe to commit. There is
deliberately no key for an access key, a secret key, a session token, a
bearer token, or a credential file's contents, and `NS1` asserts the set
is exactly the seven above so a later addition cannot slip a secret in
unnoticed.

**`K-b` — one reader, returning `(key, value)`.**

```python
def provider_setting(home: Path | str, key: str) -> tuple[str, str] | None
```

`key` must be a member of `PROVIDER_KEYS`; anything else raises
`ValueError` (a programming error, never operator input). It follows
`invocation_backend`'s discipline **case for case**, over the dotted
path:

| Input | Result |
|---|---|
| missing file | `None`, silent |
| empty file (YAML loads to `None`) | `None`, silent |
| unparseable (`YAMLError`/`OSError`/`UnicodeDecodeError`) | `_warn` + `None` |
| top level not a mapping | `_warn` + `None` |
| `provider` section absent | `None`, silent |
| any segment of the dotted path present but not a mapping | `_warn` + `None` |
| leaf absent | `None`, silent |
| leaf present but not a `str` | `_warn` + `None` |

It does **not** validate the value (not against `PROVIDERS`, not against
model-id shapes). Those judgements, and their warnings, belong to
`provider.py` and the doctor, so there is exactly one place where each
rule is decided. Criterion `PR1`.

**`K-c` — a typo must not be silent.**

```python
def provider_unknown_keys(home: Path | str) -> list[str]
```

returns the sorted dotted paths present under `provider:` that are **not**
in `PROVIDER_KEYS`, ignoring nothing. A presence-only design otherwise
hides the single most common operator failure — *"I set
`provider.bedrock.regoin` and nothing happened"* — behind a silent
default. It never warns by itself; the doctor renders it as one WARN row.
Criterion `PR2`; mutation `M4`.

**`K-d`** `config.__all__` gains exactly `"PROVIDER_KEYS"`,
`"provider_setting"` and `"provider_unknown_keys"` and becomes
`["CONFIG_BASENAME", "PROVIDER_KEYS", "config_path", "invocation_backend",
"one_motion_enabled", "provider_setting", "provider_unknown_keys"]`.
Criterion `PR1`'s last leg.

### 3.4 `Env-1` — the environment overrides, defined once (NORMATIVE)

| Setting | Env var | Config key |
|---|---|---|
| provider | `SELF_LEARN_PROVIDER` | `name` |
| region | `SELF_LEARN_BEDROCK_REGION` | `bedrock.region` |
| profile | `SELF_LEARN_BEDROCK_PROFILE` | `bedrock.profile` |
| SDK cli path | `SELF_LEARN_SDK_CLI_PATH` | *(none)* |
| worker model | `SELF_LEARN_WORKER_MODEL` | `bedrock.models.worker` |
| miner model | `SELF_LEARN_MINER_MODEL` | `bedrock.models.miner` |
| analyst model | `SELF_LEARN_ANALYST_MODEL` | `bedrock.models.analyst` |
| small-fast model | *(none — see `E-a`)* | `bedrock.models.small_fast` |

**`E-a` — the small-fast model is config-only, deliberately.** The
approved plan's env list is closed at four names, and the three model env
vars it *does* name are the three that already ship. Inventing a fifth
(`SELF_LEARN_SMALL_FAST_MODEL`) would add an operator-visible surface no
plan reviewed. The cost is that the small-fast model can only be set in
`config.yaml`; the doctor names that exact key when it is unset under
`provider=bedrock` (`§3.8`, the `models` row), so the cost is
*diagnosed*, not hidden. `D-8`.

**`E-b` — `SELF_LEARN_SDK_CLI_PATH` is resolution, not assembly.** It is
**not** an `options.env` key. It resolves to
`ProviderResolution.cli_path`, which U-sdk's extension point places on
`ClaudeAgentOptions.cli_path` (a real field, measured at SDK 0.2.121,
`E2`). It is listed here because it is an operator switch with the same
precedence discipline, not because it is provider environment.
Criterion `PR6`; `IN3`.

### 3.5 `Res-1` — resolution, and the re-derived backend name (NORMATIVE)

```python
@dataclass(frozen=True)
class ProviderResolution:
    surface: str
    provider: str                 # a member of PROVIDERS
    provider_source: str          # "env:SELF_LEARN_PROVIDER" | "config:provider.name" | "default"
    backend: str                  # a member of registry.KNOWN_BACKENDS
    backend_source: str           # "env:SELF_LEARN_BACKEND_WORKER" | "config:backend_miner-reader" | "default"
    region: str | None
    region_source: str | None
    profile: str | None
    profile_source: str | None
    cli_path: str | None
    cli_path_source: str | None
    refusal: str | None           # non-None ⇒ every consumer must refuse

def resolve(home: Path | str, surface: str) -> ProviderResolution
```

**`Rs-a` — `resolve_backend_name` is a SECOND, INDEPENDENT transcription
of U-seam's five-rung chain, and that is the point.**

```python
def resolve_backend_name(home: Path | str, surface: str) -> tuple[str, str]
```

returns `(name, source)`. It walks U-seam `§3.7.1`'s rungs — the
per-selector env var, the global env var, `config.invocation_backend`'s
two config rungs, then `"cli"` — and applies the same fail-closed rule
(a value outside `registry.KNOWN_BACKENDS` resolves to `"cli"`).

Why re-derive rather than ask: `registry.backend_for` returns a *Backend
object* and **raises** for `"sdk"` (`B-3`), so it cannot report a name;
and `registry.py` is outside this unit's file surface. The duplication is
therefore forced — and, following U-seam's own twin-witness discipline,
it is turned into evidence rather than tolerated as debt: `BK1` runs both
derivations over a matrix of environments and requires them to agree,
under the mapping *raises `BackendUnavailable` ⇔ `"sdk"`; returns a
`CliBackend` ⇔ `"cli"`*.

**`Rs-a1` — the empty-value rule is ASYMMETRIC between the env rungs and
the config rungs, and the shipped behavior IS the contract (NORMATIVE;
r3, MAJOR-4).** U-seam's `R-a` says an empty value is "no answer" and
falls through. That is true of the **env** rungs and **not** of the
**config** rungs, because the two are implemented in different places
with different notions of "answered":

| Rung kind | Mechanism | Empty value behaves as |
|---|---|---|
| env (1, 2) | `registry.backend_for` reads each var and tests truthiness, so `""` falls to the **next rung** | fall-through |
| config (3, 4) | `config.invocation_backend` returns the **first PRESENT key** — `backend_<surface>: ""` is present, so it returns `("backend_<surface>", "")` and the coarser `backend` key is **never consulted**; the registry then sees a falsy value and drops to the built-in default | **chain-terminating** |

Measured (`E11`): `SELF_LEARN_BACKEND_WORKER=""` + `SELF_LEARN_BACKEND=sdk`
resolves **sdk**; `backend_worker: ""` + `backend: "sdk"` resolves
**cli**; and with `backend_worker` absent the same config resolves
**sdk**, which is the positive control proving the config rung works and
the difference is genuinely the empty value.

**This is deliberate shipped semantics, not a bug this unit fixes.**
Writing an empty *config* key is an explicit act in a file the operator
edits and commits — reading it as "this surface takes the default,
stop looking" is defensible, and `registry.py` is outside this unit's
file surface in any case (`B-3`). What matters here is that a
re-derivation which treats the two rung kinds alike is **wrong in one
direction or the other no matter which rule it picks**, and nothing in
r2's `BK1` matrix would have caught it. `BK1` now names both cells with
their measured expectations.

**`Rs-b` — `resolve_backend_name` is SILENT.** It emits nothing on
stderr, ever — not for an unknown value, not for a bad config. U-seam's
registry already warns on the same inputs at the same moment, and a
second copy of that warning would double-print on every invocation. The
doctor reports the unknown value as its own row instead. Criterion `BK3`;
mutation `M6`.

**`Rs-c` — `REFUSALS`, gated to the SDK leg, in this fixed order
(NORMATIVE).**

> **Refusals are evaluated ONLY when `provider == "bedrock"` **and**
> `backend == "sdk"`. Under every other combination —
> `provider == "anthropic"` at any backend, and `provider == "bedrock"`
> at a **non-sdk** backend — `refusal is None`, unconditionally.**

| # | Cause | Fires when (given `provider=="bedrock"` and `backend=="sdk"`) |
|---|---|---|
| 1 | `bedrock-needs-region` | `region is None` |
| 2 | `bedrock-model-is-alias` | `model_for(surface)` matches `^claude-` (`Id-1`) |

`resolve` carries the **first** applicable cause; `preflight` (§3.8)
reports **all** that fire, one row each.

**`Rs-c1` — why `provider=bedrock` + `backend=cli` is NOT a refusal
(RULED, `D-18`).** It is a **legitimate intermediate state of the
approved staged rollout**. The rollout flips surfaces one at a time in
the order analyst → miner → worker; `provider` is install-wide (`D-2`),
so from the first flip until the last, *some* surfaces necessarily
resolve `backend=cli` while `provider=bedrock`. A refusal — or even a
warning — on that combination would fire on **every invocation of every
clean rollout**, which does not protect anybody and does train an
operator to stop reading warnings. The forgot-to-flip trap is real, but
its unambiguous signature is the **wholly-inert** config (`Doc-f`), not
the mixed one, and the doctor is where it is caught.

Consequence, stated so no reader has to infer it: **under
`backend=cli` the provider configuration is inert, silently, by
design.** Residual `R-1` records it with this rationale and its owner.

`session_env` is reached only from the SDK leg, so it never sees a
cli-backed resolution in practice; it remains a pure function of whatever
resolution it is handed. Criterion `RT1`; mutations `M7`, `M7b`.

**`Rs-d` — the refusal string's two pinned tokens.** The full string
embeds runtime values (surface, source, model id) and so is not
byte-pinnable end to end. Two tokens are pinned instead, and both are
asserted:

- it **starts with** `refused-config: `
- it **contains** `self-learn doctor invocation`

Shape, for cause 1:

```
refused-config: provider=bedrock resolved no region — surface "analyst", backend "sdk"; set provider.bedrock.region or SELF_LEARN_BEDROCK_REGION, then run `self-learn doctor invocation`
```

The prefix exists so the condition is greppable in a worker log with no
knowledge of this spec; the pointer exists because a refusal that does
not name its own diagnostic is a dead end. Criterion `RT2`; mutation
`M8`.

### 3.6 `Mod-1` — `model_for`, and delegation as construction (NORMATIVE)

```python
def model_for(surface: str, *, home: Path | str) -> str
```

Three rungs, **first hit wins**:

| Rung | Source |
|---|---|
| 1 | `os.environ[f"SELF_LEARN_{SELECTOR_FOR_SURFACE[surface]}_MODEL"]`, **verbatim**, under **either** provider |
| 2 | `config.provider_setting(home, f"bedrock.models.{MODEL_KEY_FOR_SURFACE[surface]}")` — **only** when `provider == "bedrock"` |
| 3 | the surface's shipped default function (`Mod-2`), **called** |

`SELECTOR_FOR_SURFACE` is **imported from `invocation.contract`** (`B-8`),
not re-spelled. The one new map:

```python
MODEL_KEY_FOR_SURFACE = {
    "worker": "worker", "worker-repair": "worker",
    "miner-reader": "miner", "analyst": "analyst",
}
```

`worker-repair` shares the worker's model because both worker invocations
share **one** argv builder (`worker.build_argv`, pinned by the shipped
`test_repair.py::test_f2_both_invocations_share_one_argv_builder`); a
repair round on a different model is a state nobody should have to reason
about. Criterion `MD5`.

**`Mod-2` — rung 3 CALLS the shipped functions; it does not copy their
values.**

| Surface | Rung-3 delegate |
|---|---|
| `worker`, `worker-repair` | `worker.worker_model()` |
| `miner-reader` | `miner.miner_model()` |
| `analyst` | `analyst._model()` |

imported **inside the function body** (`P-b`). This is what makes
CLI-path identity hold *by construction* rather than by coincidence:
under `provider=anthropic`, `model_for(s, home=h)` is
`<delegate>()` with at most a redundant rung-1 read in front of it, so it
**cannot** drift from what `build_argv` emits.

**And it is falsifiable, which is the part that matters.** `MD1`
monkeypatches `worker.worker_model` to return a sentinel and requires
`model_for("worker", home=h)` to return that sentinel. A build that
copies `DEFAULT_WORKER_MODEL` — or re-spells `"claude-sonnet-5"` — is
indistinguishable from the correct build under every other criterion and
fails only this one. Mutation `M9`.

**`Mod-3` — under `provider=bedrock` with no rung-1 and no rung-2 value,
rung 3 still answers, and its answer is deliberately WRONG-LOOKING.** It
returns an Anthropic alias, which `Id-1`'s guard names precisely
(*"Anthropic alias, not a Bedrock id"*) and which raises `Rs-c`'s
**Cause 2** (`bedrock-model-is-alias`).
The considered alternative — shipping default Bedrock model ids — is
**refused**: model availability is per-account, per-region and
per-enablement, this unit cannot verify a single id (§7.5), and a wrong
default would fail at the API with an opaque message instead of at the
doctor with an exact one. **This unit ships no REAL Bedrock model id in
any default, fixture, or example a user could copy into configuration**
(`D-6`, as narrowed at r3 — the two placeholders `Id-1b`/`Id-1c` name are
deliberately unusable, and `MD6` is what enforces the boundary).
Criterion `MD4`.

### 3.7 `Asm-1` — environment assembly (NORMATIVE)

```python
BEDROCK_ENV_KEYS: tuple[str, ...] = (
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    SMALL_FAST_ENV_VAR,
)

def session_env(resolution: ProviderResolution, *, home: Path | str) -> dict[str, str]
```

**`A-0` — the total rule, evaluated IN THIS ORDER (NORMATIVE; r3, MAJOR-2).**

| # | Condition | Result |
|---|---|---|
| 1 | `resolution.provider != "bedrock"` | `{}` — **exactly**, no keys at all |
| 2 | `resolution.backend != "sdk"` | `{}` — **exactly**, no keys at all |
| 3 | `resolution.refusal is not None` | raises `ProviderRefused(resolution.refusal)` |
| 4 | otherwise | the dict below |

**Row 2 is the r3 addition and it is what makes the function total.**
Before it, a `provider=bedrock` + `backend=cli` resolution — the
legitimate mid-rollout state (`Rs-c1`) — fell through rows 1 and 3
(`refusal is None` there, by `Rs-c`'s gating) into row 4, where
`resolution.region` may be `None` and would have been written into a
`dict[str, str]` as a non-string. **The type was reachable and illegal.**
Row 2 removes the reachability at its source rather than patching row 4
with a region check.

And it says the right thing: **provider variables do not apply to the CLI
transport.** That is the same fact `Doc-f`'s INFO line renders as
*"backend=cli — provider does not apply"*, now stated once in the
assembly function and once in the doctor's output, with the doctor's line
being the rendering of this rule rather than a second claim.

Criterion `EV1`'s non-sdk leg; mutation `M24`.

```
CLAUDE_CODE_USE_BEDROCK = "1"
AWS_REGION              = resolution.region      # both, always (row 4 only)
AWS_DEFAULT_REGION      = resolution.region      # both, always (row 4 only)
AWS_PROFILE             = resolution.profile     # omitted when None
<SMALL_FAST_ENV_VAR>    = config small_fast      # omitted when None
```

**`A-a` — both region variables are set, always, ON THE SDK LEG.** Scoped
to `A-0` row 4: by the time that row is reached, provider is `bedrock`,
backend is `sdk`, and `region` is a non-`None` `str` (row 3 already
refused `bedrock-needs-region`). Within that row the pair is
unconditional — either both are set to the same value or neither is.
The two names are read by different layers of the AWS tooling stack and
this unit does not know which one the CLI's SDK path consults (§7.5
`VB-2`); setting one is a coin flip, setting both is free and correct
under either answer. Criterion `EV2`; mutation `M11`.

**`A-b` — `SMALL_FAST_ENV_VAR` is ONE module constant, written as a
literal exactly once.** Measured: CLI 2.1.226 contains **both**
`ANTHROPIC_SMALL_FAST_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` (`E1`),
so the correct name is a genuine open question and is `VB-1` in the
verify-at-build ledger. Confining it to one constant makes the answer a
one-line edit. Criterion `EV3` asserts the string literal appears exactly
once in `provider.py` and nowhere else in `src/`; mutation `M12`.

**`A-c` — the model does NOT travel in `options.env`.** The per-surface
model reaches the SDK as `ClaudeAgentOptions.model` (a real field,
`E2`), fed by `model_for`. Only the small-fast model has no options field
and therefore must be an env var. Stating this is what keeps a builder
from "helpfully" adding `ANTHROPIC_MODEL` to the dict, where it would
silently outrank `options.model`. Criterion `EV4`; mutation `M13`.

**`A-d` — `os.environ` is NEVER written (NORMATIVE).** Not by
`session_env`, not by `resolve`, not by `model_for`, not by `preflight`,
not by the doctor, not by the selftest row. The assembled dict is
**returned**, and its only destination is `options.env`. Two independent
witnesses:

- **runtime** (`EV5`): snapshot `dict(os.environ)`, drive the whole
  surface — `resolve`, `model_for`, `session_env`, `preflight`, and
  `cli.main(["doctor", "invocation"])` — snapshot again, require
  equality;
- **static** (`HY2`): an AST scan of `provider.py` for `os.environ[...] =`,
  `os.environ.update(`, `os.environ.setdefault(`, `os.environ.pop(`,
  `os.putenv(`, `os.unsetenv(`.

Mutation `M10` must redden at least the runtime witness. Two witnesses,
because the AST form can be walked past by an alias and the runtime form
can be walked past by a write-then-restore.

**`A-e` — the anthropic leg is EMPTY, and the leak test is guarded
against vacuity.** `EV1` asserts **both**:

1. `set(session_env(anthropic_resolution).keys()) & set(BEDROCK_ENV_KEYS) == set()`, and
2. `set(session_env(bedrock_resolution).keys()) >= {"CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION"}`.

Leg 2 is not decoration. Without it, an implementation that returns `{}`
unconditionally — the single most likely wiring bug — passes leg 1
perfectly. The same lesson U-seam learned at `CN1`: *"every element
satisfies X"* is vacuously true of the empty set. Mutation `M14` is the
leak; mutation `M15` is the always-empty build, and only leg 2 catches
it.

**`A-f` — inheritance is real, and the doctor is the answer to it.**
Measured in the SDK's transport (`E2`): the child's environment is
`{**os.environ (minus CLAUDECODE), "CLAUDE_CODE_ENTRYPOINT": …,
**options.env, "CLAUDE_AGENT_SDK_VERSION": …}`. So an **ambient**
`CLAUDE_CODE_USE_BEDROCK=1` in the operator's shell reaches the child on
the *anthropic* leg too, and `options.env = {}` does not and cannot
prevent it. This unit does **not** neutralize it (writing
`CLAUDE_CODE_USE_BEDROCK=0` would be a guess about the CLI's truthiness
parsing — `VB-3`); it **reports** it, as a WARN row naming every ambient
`BEDROCK_ENV_KEYS` member found in `os.environ` while
`provider=anthropic`. Criterion `DC7`; `D-9`.

### 3.8 `Doc-1` — the doctor (NORMATIVE)

```
self-learn doctor invocation
```

**`Doc-0` — `preflight` computes, the command prints, and NOTHING
computes twice (NORMATIVE; r3, MAJOR-5).**

```python
@dataclass(frozen=True)
class Row:
    name: str                 # a member of DOCTOR_ROWS
    verdict: str              # a member of VERDICTS
    detail: str
    surface: str | None = None   # set iff the row is per-surface (Doc-b)
    cause: str | None = None     # set iff the row is per-cause (Doc-b)

def preflight(home: Path | str) -> list[Row]
```

Three obligations, each pinned:

1. **`preflight` returns the COMPLETE list of rows and PRINTS NOTHING.**
   Not to stdout, not to stderr. It is the single source of every verdict
   in this unit.
2. **`_cmd_doctor` is a thin printer.** It calls `preflight(home)`,
   renders each `Row` through the one line template of `Doc-b`, prints
   the `Doc-d` handoff block, and returns `1 if any row.verdict == "FAIL"
   else 0`. It computes **no verdict of its own** and calls no probe
   directly.
3. **The selftest row is computed programmatically**, never by parsing
   text: `selfcheck._check_invocation` calls `preflight(home)` and its
   `ok` is `not any(r.verdict == "FAIL" for r in preflight(home))`
   (`DC11`).

**Why this is a contract and not an implementation note.** Without it,
`DC8`'s AST scan ("the doctor's call graph contains no `os.kill` …") has
no named entry point to walk, `DC11`'s selftest `ok` could drift from
what the command prints, and every `DC` criterion would have to drive the
argparse surface to observe a verdict — making the rows testable only
through their rendering. With it, the rows are data, the printer is
trivial, and the two can be checked separately. Criterion `DC15`;
mutation `M25`.

`doctor` is a subcommand **group** (like `mine`, `worker`, `host`) with
one verb today, so a second doctor can join without another top-level
name. A bare `self-learn doctor` prints the group's help to stderr and
returns `EXIT_USAGE` (64), matching `cli.py`'s shipped pattern.

**`Doc-a` — it never calls any API, of any kind, with ONE enumerated
local-process exception (NORMATIVE; restated at r3 for MAJOR-1).**

> **No network call of any kind.** No Bedrock call, no STS call, no
> `aws` spawn, no IMDS probe — `169.254.169.254` is a network call and
> `Cred-1`'s one deliberately-unprobed mechanism. **No model
> invocation**: the doctor never starts a `claude` session, never sends a
> prompt, and never reads a response.
>
> **Exactly one subprocess is permitted, and only from the `sdk` row:**
>
> ```
> [<resolved host claude path>, "--version"]
> ```
>
> — argv **byte-pinned to those two elements** (argv[0] is the resolved
> path, argv[1] is exactly `--version`, and `len(argv) == 2`), run with
> `capture_output=True, text=True`, a **bounded `timeout=10`**, and
> `FileNotFoundError` / `OSError` / `TimeoutExpired` each caught and
> rendered as a **SKIP** with the reason. Its output is parsed
> **minimally**: the first whitespace-delimited token of stdout, and
> nothing else. **No other subprocess may be spawned from any doctor
> path.**

**Why the carve-out, and why it does not weaken the guarantee.** The skew
WARN's entire point is **bundled-CLI vs HOST-CLI** — the approved plan
names both, and the host version is obtainable no other way: it is a
property of a binary on `PATH`, not of any importable module. Without it
the row can compare the bundled version only against itself, which is a
row that cannot fail. `claude --version` **spawns a local process and
calls no API** — it prints a version string and exits — so the
never-calls-any-API property is preserved exactly; what is relaxed is a
*proxy* for it (never spawn anything) that was stricter than the property
it stood for. The live skew this row exists to catch is real on this
machine today: bundled `2.1.212` vs host `2.1.226` (`E3`).

**Path resolution** is `shutil.which("claude")`, honoring
`SELF_LEARN_SDK_CLI_PATH` when set (that path is used directly, not
re-resolved). `shutil.which` reads `PATH` and stats candidates; it writes
nothing, which is all `HY3` forbids (`HY3` was narrowed at r3 for exactly
this — see `Hy-a`). An unresolvable path is a **SKIP**, never a FAIL.

Criteria `DC10` (nothing else spawns, nothing reaches the network) and
`DC13` (the argv is byte-pinned and the failure legs degrade to SKIP).
Mutations `M18`, `M23`.

**`Hy-a` — the no-write property is about WRITES, and the guard is scoped
to write primitives (NORMATIVE; r3 narrowing).** `provider.py` and the
doctor **read** the filesystem by necessity: `Cred-1` stats credential
files and tests one section header, the SSO-cache probe lists a
directory, `Doc-a` resolves a binary on `PATH`, and `config.py` reads
`config.yaml`. What they must never do is **write**. `HY3`'s AST scan is
therefore a ban on write primitives (its list is in `HY3`), not on
`shutil.` or `open(` wholesale — r2's broader ban would have forbidden
the reads the unit's own criteria require, which is a guard forbidding
its own design. The reads are bounded independently and more precisely by
`NS4` (nothing beyond the section boolean; SSO entries counted, never
opened), `NS5` (no file or directory created anywhere) and `DC10` (no
spawn beyond `Doc-a`'s one argv, no socket).

**`Doc-b` — the rows are a closed set, in this order.**

```python
DOCTOR_ROWS = ("switches", "provider", "config", "sdk", "rollout",
               "consistency", "region", "credentials", "models", "env",
               "orphans")
VERDICTS = ("PASS", "WARN", "FAIL", "SKIP", "INFO")
```

**Line count (NOTE-6 fold): one line per row — UNLESS this table's
"Lines" column says otherwise.** A row marked *per-surface* emits one
line per member of `SURFACES` (four); a row marked *per-cause* emits one
line per firing cause and none when none fire. Every line, whatever its
row, has the shape `doctor: {verdict} {row} — {detail}`. Exit code is
**1 if any line is FAIL, else 0** — WARN, SKIP and INFO do not fail the
command. `DC1`'s "appears exactly once" assertion is over **rows**, not
lines, and reads this column.

| Row | Lines | Reports |
|---|---|---|
| `switches` | 1 | all four surfaces' resolved backend **and the rung that answered** (`Rs-a`'s `source`) |
| `provider` | 1 | the resolved provider and its rung |
| `config` | 1 | `provider_unknown_keys` (`K-c`) — WARN when non-empty, naming each |
| `sdk` | 1 | `claude_agent_sdk.__version__`, its bundled CLI version, the host CLI version (`Doc-a`'s one subprocess) — **WARN on skew**, SKIP when not importable or unresolvable |
| `rollout` | 1, or **per-surface** in the mixed state | `Doc-f` |
| `consistency` | **per-cause** | every `Rs-c` cause that fires, FAIL. **Evaluated only for surfaces whose backend is `sdk`** |
| `region` | 1 | the resolved region and its rung; which env vars it will become (`A-a`) |
| `credentials` | 1 | every `Cred-1` mechanism found, **named**, presence only. Verdict by `Doc-g` |
| `models` | **per-surface** | the id `model_for` returns, its rung, and its `Id-1` verdict **gated by `Doc-i`**; plus one `small_fast` line |
| `env` | **per-surface** | `Doc-h` — the assembled key list, or the reason there is none |
| `orphans` | 1 | U-sdk's orphan/pid-sidecar report (`Doc-e`) |

**`Doc-h` — the `env` row is PER-SURFACE and CATCHES `ProviderRefused`
(NORMATIVE; r3, MAJOR-2).** `session_env` is a function of a
**per-surface** resolution, so a single `env` row could only ever have
described one surface while implying it described the install. Four
lines, one per surface, each of exactly one of these three shapes:

| Surface state | Verdict | Line |
|---|---|---|
| `session_env` returned a non-empty dict | **PASS** | the **sorted KEY list**, values rendered `<redacted>` |
| `session_env` returned `{}` because `A-0` row 2 (`backend != "sdk"`, `provider=bedrock`) | **SKIP** | `provider does not apply` |
| `session_env` returned `{}` because `A-0` row 1 (`provider=anthropic`) | **PASS** (no ambient `BEDROCK_ENV_KEYS` member set) or **WARN** (naming the ambient key) | `provider=anthropic`, or the ambient-key warning |
| `session_env` raised `ProviderRefused` (`A-0` row 3) | **FAIL** | the refusal string as the detail |

> **NOTE (fold, code gate, 2026-08-19): the row above for `A-0` row 1
> reads PASS/WARN, not the single SKIP this table originally said.**
> `DC7` (§4) is the actual, binding criterion — it explicitly requires
> PASS-when-no-ambient-key and WARN-when-an-ambient-`BEDROCK_ENV_KEYS`-
> member-is-set under `provider=anthropic`, so a stray, un-neutralized
> `CLAUDE_CODE_USE_BEDROCK=1` (or similar) left in the operator's shell
> is surfaced rather than silently ignored. Per §0, the criterion wins
> and this prose was the defect; do not "fix" the shipped PASS/WARN
> behavior back to SKIP to match an out-of-date table.

> **The doctor CATCHES `ProviderRefused` and renders it. It never
> propagates.** A diagnostic whose job is to explain a misconfiguration
> must not die of the misconfiguration — and `EV6` deliberately makes
> `session_env` raise, so the doctor is the one caller obliged to handle
> it. The refusal text is already operator-facing and already carries
> `Rs-d`'s pointer, so rendering it verbatim is the whole handling.

Criteria `DC14` (both the per-surface split and the catch); mutations
`M24`, `M26`.

**`Doc-i` — the `models` row's `Id-1` FAIL is GATED TO `sdk` SURFACES
(NORMATIVE; r4, MAJOR-A).** `Id-1`'s alias FAIL answers the question
*"will this id work on Bedrock?"*. That question is **only asked of a
surface whose backend is `sdk`**. On a `cli` surface the id goes to the
CLI transport, where an Anthropic alias is **the correct value** —
`Mod-3` and `MD4` positively *require* `model_for` to return it there.

| Surface state | Verdict | Line |
|---|---|---|
| `provider=bedrock`, `backend=sdk` | `Id-1`'s verdict — **FAIL** on an alias, WARN on an unrecognized shape, PASS otherwise | the id, its rung, the verdict |
| `provider=bedrock`, `backend != "sdk"` | **INFO** | the id, its rung, and `backend=cli — Anthropic alias is correct here; provider does not apply` |
| `provider=anthropic` | **SKIP** | `provider=anthropic — Bedrock id shapes not applicable` |

**Why this is the fold's own principle, one row short.** `A-0` row 2 and
`Doc-f`'s INFO line already say *provider does not apply on a cli
surface*; the `models` row was the one place still judging a cli surface
by Bedrock's rules. Ungated, on a **correct** mid-rollout install —
provider install-wide (`D-2`), analyst flipped, worker still on `cli` —
the worker's correctly-resolved alias FAILs, the command exits 1, and
`DC11` turns **the selftest red on a healthy state**. That is `D-18`'s
warn-blindness failure arriving through a third door.

**And the second-order harm is worse than the first.** `DC3`'s
twice-run FAIL-free mixed leg would still have to pass — so its fixture
would have had to configure **Bedrock ids for cli surfaces**, a state no
healthy rollout ever has. The criterion would have gone green against a
fixture that misrepresents the very state it exists to certify. A
fixture bent to satisfy a wrong verdict is worse than the wrong verdict,
because it also destroys the evidence.

Criteria `DC6` (gating asserted per surface), `DC12`/`DC16`'s mixed
fixture (Bedrock ids configured **only** for flipped surfaces ⇒
FAIL-free); mutation `M27`.

**`Doc-g` — the `credentials` row's verdict is WARN, never FAIL, and the
reason is in the line (NOTE-7 fold).** Under `provider=bedrock` with at
least one `sdk` surface and **no** mechanism found, the verdict is
**WARN** with the detail *"no mechanism found (IMDS not probed — see
`R-4`)"*. **`Doc-g` owns this operator-facing line**; `R-4` references it
rather than restating it (NOTE-c).

*(NOTE-b: r3's string said "IMDS **and container roles** not probed",
which is false at the moment it renders — `Cred-1` **does** probe the
container mechanism via `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` /
`_FULL_URI`. A row whose whole job is to name what it could not see must
not name something it did see. "and container roles" is struck.)*

**It is WARN because the probe is provably incomplete.** `Cred-1`
deliberately does not reach IMDS (that is a network call, `Doc-a`), so on
EC2 or ECS with an instance role the doctor sees nothing while
credentials in fact resolve. **A check that cannot distinguish "absent"
from "invisible to me" must not FAIL** — it would be a false FAIL on a
correct install, which is the same warn-blindness failure `D-18` refused
in the rollout row, arriving through a different door.

**This is also what keeps `DC3`'s mixed leg coherent.** That leg asserts
the *absence* of any FAIL on a healthy mixed rollout; a FAILing
credentials row would make the assertion depend on whether the test host
happens to have AWS credentials. `DC3` therefore runs its mixed leg
**twice — once with a seeded credential mechanism and once with none —
and requires FAIL-free in both**, which makes this WARN decision
load-bearing rather than incidental. Criterion `DC16`.

**`Doc-f` — the `rollout` row: FAIL the wholly-inert config, INFO the
mixed one (RULED, `D-18`).** The staged rollout flips surfaces one at a
time, so a mixed `provider=bedrock` install is normal and must not be
scolded. Exactly one shape is unambiguously wrong:

| State | Verdict | Line |
|---|---|---|
| `provider=bedrock` and **all four** surfaces resolve `backend=cli` | **FAIL** | *"provider=bedrock but every surface resolves backend=cli — the provider configuration does nothing. Flip at least one surface to backend=sdk, or set provider=anthropic."* |
| `provider=bedrock`, **some** surfaces `sdk` | **INFO**, one line per surface | `worker: backend=cli — provider does not apply` / `analyst: backend=sdk provider=bedrock — [checks]`, where `[checks]` is that surface's `region`/`models`/`env` verdicts |
| `provider=bedrock`, **all** surfaces `sdk` | **PASS** | the four surfaces named |
| `provider=anthropic` | **SKIP** | *"provider=anthropic — rollout state not applicable"* |

**The FAIL is deliberately narrow and the INFO is deliberately loud.** A
doctor that FAILed the mixed state would fire on every invocation of
every clean rollout, and an operator who learns to ignore one FAIL has
learned to ignore all of them. Criteria `DC3` (verdicts), `DC12` (the
INFO lines' per-surface accuracy); mutations `M7`, `M7b`.

**`Doc-c` — the default posture can never FAIL (NORMATIVE).** On a home
with no `config.yaml` and no relevant environment — `provider=anthropic`,
every surface `backend=cli`, SDK not installed — **every row is PASS or
SKIP, and the command exits 0.** This is not a nicety: the doctor feeds a
`--selftest` row that every existing user runs, and a FAIL on the shipped
default would turn the whole selftest red for a feature nobody enabled.
Criterion `DC1`; mutation `M16` (make the SDK-missing row an
unconditional FAIL) must redden it.

**`Doc-d` — the handoff block.** After the rows, a separator line
`doctor: ---`, then one `doctor: handoff: <field> = <value>` line per
field, in this fixed set: `provider`, `backend.<surface>` ×4, `region`,
`profile`, `credential-mechanisms`, `model.<surface>` ×4,
`model.small_fast`, `env-keys.<surface>` ×4, `sdk-version`,
`cli-version.bundled`, `cli-version.host`. This block is what gets pasted
to an AWS administrator who has never seen this project: it names the
region, the profile *name*, the mechanism, and the exact model ids —
everything an IAM/model-access diagnosis needs, and **no value from any
credential probe** (`NS3`). Criterion `DC9`; mutation `M17`.

**`Doc-d0` — every handoff field has a DEFINED value on every path
(NOTE-f).** The block's field set is fixed, so each field needs a value
even when its source did not run. Two fields can be sourceless:

| Field | When | Placeholder |
|---|---|---|
| `cli-version.host` | the `sdk` row SKIPped, so `Doc-a`'s subprocess never ran — **which is every install without the SDK, i.e. the shipped default** | `(not probed — sdk row skipped)` |
| `cli-version.bundled` | the SDK is not importable | `(not probed — sdk not installed)` |

Without this, `DC9`'s fixed-field assertion has no defined subject on the
zero-spawn path — the commonest path there is. Every other field always
resolves (a provider, four backends, and four model ids always exist;
region/profile render `(unset)`).

**Operational note, not a criterion:** "the shipped default" above is a
statement about an install **without** the `[sdk]` extra. On any install
**with** it (`claude_agent_sdk` importable), the zero-spawn path does not
apply at all — `_sdk_row` reaches `Doc-a`'s one permitted subprocess
(`[<resolved claude>, "--version"]`) on **every** `self-learn doctor
invocation` run, and therefore on every `self-learn --selftest` run too
(`DC11` wires the same `preflight` into the selftest's `invocation` row).
This is new, sanctioned-but-real per-run behavior that did not exist
before U-sdk shipped `SdkBackend` and this unit wired the doctor into
`--selftest`: a host that installed the `[sdk]` extra now spawns a real
`claude --version` child process on every selftest invocation, where none
ran before. Recorded so this is read as a decision, not an accident — see
`14-forward-work-map.md`'s corresponding row.

**`Doc-d1` — the key-list rendering is stated ONCE, in `Doc-h`
(NOTE-8).** `env-keys.<surface>` carries **exactly what `Doc-h`'s PASS
line carries** for that surface — the sorted key list with values
rendered `<redacted>` — and where that surface has no assembled
environment it carries `Doc-h`'s SKIP reason verbatim. r2 stated the
"sorted keys, values redacted" contract in both places, which is two
owners for one fact; `Doc-h` is the owner and this line is a reference to
it. `DC9` asserts the equality between the two renderings rather than
re-deriving the expected text.

**`Doc-e` — the orphan row consumes an OPTIONAL hook and never acts.**
U-sdk owns the pid-sidecar design; this unit does not know its shape at
spec time. The doctor calls U-sdk's exported report function if it is
importable and renders its result; if the symbol or the module is absent,
the row is **SKIP**. The row is **report-only**: `HY3`'s AST scan asserts
the doctor path contains no `os.kill`, `os.killpg`, `signal.`,
`.unlink(`, `.write_text(`, `.rmdir(` or `shutil.rmtree`. A diagnostic
that reaps processes is a diagnostic an operator will be afraid to run.
Criterion `DC8`; residual `R-6`.

**`Cred-1` — the credential mechanisms, presence-only (NORMATIVE).**
Every row names *which* mechanism was found. No probe opens a credential
file for its contents, and no value is stored or printed.

| Mechanism | Probe (presence only) | Never |
|---|---|---|
| `env-static` | `AWS_ACCESS_KEY_ID` in `os.environ`; separately `AWS_SECRET_ACCESS_KEY` | read either value |
| `env-session` | `AWS_SESSION_TOKEN` in `os.environ` | read the value |
| `env-bedrock-key` | `AWS_BEARER_TOKEN_BEDROCK` in `os.environ` | read the value |
| `profile-file` | `AWS_SHARED_CREDENTIALS_FILE` or `~/.aws/credentials` `.is_file()`; `AWS_CONFIG_FILE` or `~/.aws/config` `.is_file()`; **whether a section header naming the resolved profile exists** | print any line, or anything after the `]` |
| `sso-cache` | `~/.aws/sso/cache/` is a dir; **count** of `*.json` entries | open any of them |
| `container` | `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` or `AWS_CONTAINER_CREDENTIALS_FULL_URI` present | read either value |
| `web-identity` | `AWS_WEB_IDENTITY_TOKEN_FILE` present **and** the named path `.is_file()` | read the token file |
| `imds` | **not probed** — reaching the instance metadata service is a network call, forbidden by `Doc-a` | — |

The profile-section probe is the one that touches a credential file's
bytes. It is bounded to a **boolean**: does a line equal to
`[<profile>]` (or `[profile <profile>]` in `config`) exist. Nothing after
the closing bracket is examined, matched, stored or printed. Criterion
`NS2`; mutation `M19`.

**`Id-1` — model-id shapes: one FAIL guard, and advisory hints
(NORMATIVE).**

```python
BEDROCK_ALIAS_RE = r"^claude-"       # the FAIL
```

A model id matching `BEDROCK_ALIAS_RE` under `provider=bedrock` is
**FAIL**, with the message *"Anthropic alias, not a Bedrock id"*.
Everything else is at most a **WARN**, because the shape is genuinely not
uniform.

**`Id-1a` — MEASUREMENT PROVENANCE, not configuration examples
(BLOCKER-1 fold).** The three id shapes below were **extracted from the
shipped CLI binary's string table** at 2.1.226 (`E5`) and are quoted here
as *evidence that the shape is non-uniform*. **They are not defaults, not
fixtures, and not examples to copy into `config.yaml`** — `D-6`'s ban
covers exactly that use and does not cover citing a measurement.
Criterion `MD6` enforces the boundary: no real id may appear in
`provider.py` or in either new test file.

```
<vendor-prefixed>.claude-3-5-haiku-20241022-v1:0   ← prefix . vendor . model - date - vN : M
<vendor-prefixed>.claude-opus-4-6-v1               ← no :M
<vendor-prefixed>.claude-sonnet-5                  ← no version segment at all
```

*(The `us.anthropic.` prefix is elided above precisely so this block
cannot be pasted anywhere and work; the unelided strings live in `E5`,
which is labelled as binary-string provenance.)*

A regex strict enough to validate the first would **false-FAIL** the
third, which is a shipped id. So the hint set is advisory:

| # | Hint | Matches |
|---|---|---|
| 1 | `^arn:aws[a-z-]*:bedrock:` | an ARN (inference profile or foundation model) |
| 2 | `^(us|eu|apac|us-gov|global)\.[a-z0-9-]+\.` | a regional inference-profile id |
| 3 | `^[a-z0-9-]+\.[a-z0-9-]+` | a bare foundation-model id (`vendor.model`) |

None matching → **WARN** *"unrecognized Bedrock id shape"*, never FAIL.

**`Id-1b` — the guard's specificity, asserted in both directions with a
NON-REAL fixture (`DC6`).** The literal `claude-sonnet-5` FAILs; the
prefixed id **`us.anthropic.claude-example-v0:0`** — which contains
`claude-` but is not anchored at it — does **not**. That fixture is
deliberately **not a real Bedrock id**: it preserves the control's entire
purpose (anchored, not substring) while being unusable if pasted into a
config, which a real id would not be. Mutation `M5` removes the guard;
`M5b` widens it to an unanchored `claude-` and must redden the
negative-control leg.

**`Id-1c` — the ARN fixture.** The ARN hint is exercised with
`arn:aws:bedrock:us-east-1:000000000000:inference-profile/example-profile`
— account id `000000000000`, which is not a valid AWS account and is
marked as a placeholder in the test's own comment.

### 3.9 `Int-1` — the integration contract with U-sdk (NORMATIVE, abstract)

U-sdk ships an `SdkBackend` with **one documented extension point** where
provider environment enters `options.env`. Its symbol is not knowable
when this spec is written and **is not guessed here**.

**At this unit's build**, against post-U-sdk master, the builder:

1. **Reads U-sdk's spec and code and names the extension point in the
   build report** — module, symbol, signature, **quoted verbatim**.
2. Wires **three assignments plus the guarded-call shape** (`In-d`)
   there:
   - `options.env` ← `provider.session_env(res, home=home)`
   - `options.model` ← `provider.model_for(spec.surface, home=home)`
   - `options.cli_path` ← `res.cli_path` when it is not `None`
   where `res = provider.resolve(home, spec.surface)`.
3. Touches **nothing else** in U-sdk's files.

**`In-d` — the ProviderRefused → Outcome conversion OWNS A HOME, and it
is the extension point (NORMATIVE; r3, MAJOR-3).** r2 specified the
refusal *shape* (`In-c`) and the never-lost *consequences* (`RT3`–`RT5`)
but named no line of product code that performs the conversion. A hop
with no owner is a hop no mutation can target and no criterion can
observe except through a test double that performs the conversion
itself — which is the test asserting its own fixture.

The owner is here. Stated abstractly, because U-sdk's symbol is not
knowable at spec time:

> **The provider call at the extension point is WRAPPED.** In the
> session-build path, `provider.session_env(...)` (and the `resolve` /
> `model_for` calls feeding it) are enclosed by a handler that catches
> **`ProviderRefused`** and returns
> `Outcome(ok=False, rc=None, stdout="", detail=str(exc),
> failure="unavailable", exc=exc)` — `In-c`'s Outcome, built from the
> refusal's own text so `Rs-d`'s two pinned tokens survive into
> `Outcome.detail`. **No session is started, no transport is reached,
> and nothing propagates out of the backend.** The handler catches
> `ProviderRefused` **only** — every other exception keeps whatever
> behavior U-sdk gave it.

`In-a`'s stop-and-report stands over this too: if U-sdk's real extension
point cannot express a guarded call in its body (for instance because it
is a pure data hook with no control flow), the builder **stops and
reports** rather than relocating the conversion somewhere this spec did
not specify.

**`In-b` — the criteria observe the WIRING, not the source, and not a
double.** `IN1`–`IN5` **and `RT3`–`RT5`** drive a **real `SdkBackend`
with the TRANSPORT faked** — the same shape `IN4` already required — and
assert on what the real product code produced. Two things are therefore
forbidden in these criteria, and named so a builder cannot reach for
them by accident:

- **grepping U-sdk's source** for `session_env(` — that proves the call
  was typed, not that it runs;
- **any test double that constructs the refusal `Outcome` itself** — a
  `FakeBackend` scripted to return `failure="unavailable"` satisfies
  every assertion about the never-lost path while the product code that
  was supposed to build that `Outcome` does not exist. `M8b` is the
  mutation that separates the two, and it can only redden if the
  conversion is real product code with a real home.

**`In-c` — the refusal path is U-seam's `unavailable`, not a new failure
kind.** The plan describes `Outcome(ok=False, status="refused-config")`.
`Outcome` has no `status` field, and `FAILURE_KINDS` is
`("exit", "timeout", "not-found", "os-error", "unavailable")` — both live
in `invocation/contract.py`, which this unit may not touch, and adding a
sixth kind would require editing `analyst.analyze`'s dispatch table too
(`W-h`), which it also may not touch. So:

> **A provider refusal surfaces as
> `Outcome(ok=False, rc=None, stdout="", detail=<Rs-d's string>,
> failure="unavailable")`.**

This is not a workaround, it is the better shape, and it buys the
never-lost property **with no edit to any call site**:

| Surface | What already happens on `failure="unavailable"` | Result |
|---|---|---|
| `worker`, `worker-repair` | logs the `unavailable` template, returns `None`, run continues and harvests | record survives |
| `miner-reader` | returns `None` **before** the stray sweep (`W-c`) | spool preserved |
| `analyst` | `analyze` raises `AnalystError` (U-seam `W-h`'s `unavailable` row) → `teach.py`'s `except analyst.AnalystError` → capture-to-pending, **exit 4** (`EXIT_ANALYST`, pinned by the shipped `test_round3_fixes.py`: `assert teach_mod.EXIT_SCAN == 3 and teach_mod.EXIT_ANALYST == 4`) | record captured, not lost |

`Rs-d`'s `refused-config: ` prefix is what keeps the two causes
distinguishable in a log even though they share a failure kind.
Criteria `RT3`, `RT4`; mutation `M8b` (the refusal raises instead of
returning an `Outcome`) must redden `RT4`.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`tests/test_provider.py` unless it says otherwise; the `DC` group lands
in `tests/test_doctor_invocation.py`. **61 criteria**, in ten groups:
`SU` 5, `PR` 6, `BK` 4, `MD` 6, `EV` 6, `NS` 5, `DC` 16, `RT` 5, `IN` 5,
`HY` 3.

**Arithmetic checked**: a whole-file grep for the criterion bullet
pattern (`^- \*\*\`<GROUP><N>\`` ) returns **61**, and the per-group
counts above are that grep's own `uniq -c` output — no prose bullet
elsewhere in this document matches the pattern.

**All fixtures use obviously-fake placeholders** — profile
`sandbox-profile`, model id `us.anthropic.example-model-v0:0`, credential
value `not-a-real-key-DO-NOT-USE`. No fixture may contain a
copy-pasteable real Bedrock model id (`D-6`), and none may contain
anything credential-shaped.

### SU — the suite and the bounded edits

- **`SU1`** The CLI suite at `plugins/self-learn/cli` collects **1716**
  tests and reports **1711 passed, 5 skipped, 0 failed** — the `c2669a9`
  baseline (`B-9`) — *plus* the new tests. A collected count below 1716,
  any failure, or a sixth skip fails this criterion.
  *Instrument criterion.*
- **`SU2`** (restated post-build, `S-38`) `git diff --name-only <base>..HEAD -- plugins/self-learn/cli/tests/`
  names **exactly five** paths: the two new test files,
  `test_lock_invariant.py`, `test_selftest.py`, and
  `test_invocation_sdk.py`. And
  `git diff --numstat <base>..HEAD -- tests/test_lock_invariant.py tests/test_selftest.py tests/test_invocation_sdk.py`
  shows **1 insertion / 0 deletions** for the first,
  **2 insertions / 2 deletions** for the second, and **33 insertions /
  7 deletions** for the third. Any other shape means an existing test
  was edited to pass rather than registered — or, for the third path,
  edited beyond the ratified `OP11`/`OP13` rewrite.
  *Instrument criterion.*
- **`SU3`** *(restated at r3, NOTE-3 — as POSITIVE assertions, not "the
  census passes")* Three things, each asserted directly:
  1. `"_cmd_doctor" in test_lock_invariant._cmd_functions()` — the
     command really is a `_cmd_*` dispatch surface;
  2. `"_cmd_doctor" in test_lock_invariant._ARGV_FOR` **and** its value
     is `[["doctor", "invocation"]]` — it is really parametrized, with a
     real argv rather than a `None` exemption;
  3. `TestEveryCommandSurvivesAHeldLock` drives that argv to a clean
     exit against a real held commit lock, leaving nothing staged.

  **Why not "the census passes".** `test_every_cmd_surface_is_covered`
  computes `set(_cmd_functions()) - set(_ARGV_FOR)` — it fails on a
  *missing* key and is **blind to a stale one**. Under `M21` (the command
  renamed to `_doctor_cmd` to dodge the census) the `_ARGV_FOR` entry
  simply becomes stale, the subtraction stays empty, and the census goes
  right on passing while the doctor is no longer audited under a held
  lock at all. Only leg 1 sees that.
- **`SU4`** `test_selftest.py`'s two count assertions read
  `"all 8 checks green"` and pass, and the FW-66 decode-safety test's
  per-check loop still finds `PASS` for all seven original checks.
- **`SU5`** `git diff --name-only` names no path under
  `plugins/self-learn/ui/`. *Instrument criterion.*

### PR — provider resolution and the config reader

- **`PR1`** `config.provider_setting` satisfies every row of `K-b`'s
  table, for at least three distinct keys spanning all three nesting
  depths (`name`, `bedrock.region`, `bedrock.models.worker`); a key
  outside `PROVIDER_KEYS` raises `ValueError`; and `config.__all__` is
  exactly `K-d`'s seven names.
- **`PR2`** `config.provider_unknown_keys` returns the sorted dotted
  paths not in `PROVIDER_KEYS`, for a config carrying both a misspelled
  scalar (`bedrock.regoin`) and a misspelled section (`bedrok`), and
  returns `[]` for a fully-valid config **and** for a missing file.
- **`PR3`** The three-rung provider chain (`Prov-1`) resolves correctly
  rung by rung, each rung shadows the one below it, and an **empty
  string** at either configurable rung falls through **silently** — no
  stderr byte.
- **`PR4`** An unknown provider value at each configurable rung resolves
  to `"anthropic"` and emits `Pv-b`'s byte-exact warning for that rung.
  It does **not** fall through to the next rung: with
  `SELF_LEARN_PROVIDER=bogus` and `config.yaml` naming `bedrock`, the
  result is `anthropic`. The config-flavored spelling is emitted
  **through `config._warn`** — asserted by monkeypatching `config._warn`
  and requiring it to have been called, so a duplicated prefix literal
  fails even though the bytes match.
- **`PR5`** `resolve()` populates every `*_source` field with a value
  naming the rung that answered, from the closed vocabulary
  `{"env:<VAR>", "config:<key>", "default"}`, for provider, backend,
  region, profile and cli-path — each checked at a rung where it differs
  from the others'.
- **`PR6`** `SELF_LEARN_BEDROCK_REGION`, `SELF_LEARN_BEDROCK_PROFILE` and
  `SELF_LEARN_SDK_CLI_PATH` each override their config counterpart
  (cli-path has none), and each is absent from `session_env`'s output
  as a key (`E-b`: `SELF_LEARN_SDK_CLI_PATH` reaches `cli_path`, not the
  env).

### BK — the re-derived backend name

- **`BK1`** Over a matrix of **at least 14** environments — each of the
  four surfaces × {rung-1 env, rung-2 env, rung-3 config, rung-4 config,
  default}, plus an unknown value, plus an empty value, **plus the two
  empty-value shadowing cells of `Rs-a1`, named explicitly** —
  `resolve_backend_name(home, surface)[0]` agrees with
  `registry.backend_for(surface, home=home)` under the mapping *raises
  `BackendUnavailable` ⇔ `"sdk"`; returns a `CliBackend` ⇔ `"cli"`*.
  **The comparison operand is obtained by calling `backend_for`**, never
  by re-reading the same env var the derivation read.

  The two mandated cells, with their **measured** expected values
  (`E11`) — a re-derivation that treats both rungs alike gets one of them
  wrong whichever way it guesses:

  | Cell | Setup | Expected |
  |---|---|---|
  | env-empty-shadowing | `SELF_LEARN_BACKEND_WORKER=""` **and** `SELF_LEARN_BACKEND=sdk` | **`sdk`** — the empty env rung falls through |
  | config-empty-shadowing | `invocation.backend_worker: ""` **and** `invocation.backend: "sdk"` | **`cli`** — the config rung does **not** fall through |
  | *(positive control)* | `invocation.backend_worker` **absent**, `invocation.backend: "sdk"` | **`sdk`** — proves the config rung is reachable at all, so the cell above is measuring the empty-value rule and not a broken fixture |
- **`BK2`** The selector mapping holds in the re-derivation:
  `SELF_LEARN_BACKEND_WORKER` governs `worker-repair`, and
  `SELF_LEARN_BACKEND_MINER` does not.
- **`BK3`** `resolve_backend_name` writes **nothing** to stderr for any
  input in `BK1`'s matrix, including the unknown-value case — while
  `backend_for` on the same input **does** warn. Both halves asserted, so
  a build that simply never warns anywhere also fails.
- **`BK4`** `resolve_backend_name` returns a `source` naming the exact
  rung, and for the config rungs the exact key `config.invocation_backend`
  matched (`backend_<surface>` vs `backend`) — not a hardcoded
  per-surface key.

### MD — model_for

- **`MD1`** Under `provider=anthropic`, monkeypatching
  `worker.worker_model` / `miner.miner_model` / `analyst._model` to
  return distinct sentinels makes `model_for` return those sentinels for
  the four surfaces. **This is the delegation criterion**; a build that
  copies the default string passes everything else and fails here.
- **`MD2`** `SELF_LEARN_{WORKER,MINER,ANALYST}_MODEL` wins **verbatim**
  under **both** providers — including a value that would trip `Id-1`'s
  alias guard, which is returned unchanged (the guard is the doctor's
  judgement, not `model_for`'s).
- **`MD3`** Under `provider=bedrock`, rung 2 answers from
  `provider.bedrock.models.<key>` for each of worker/miner/analyst, and
  is shadowed by rung 1.
- **`MD4`** Under `provider=bedrock` with neither rung 1 nor rung 2 set,
  `model_for` returns the delegate's value (an Anthropic alias) — it does
  **not** raise, does not return `None`, and does not invent an id.
- **`MD5`** `model_for("worker-repair")` equals `model_for("worker")`
  under all three rungs, and `MODEL_KEY_FOR_SURFACE` is total over
  `invocation.contract.SURFACES`. The selector map is **the imported
  one**: a test asserts `provider.SELECTOR_FOR_SURFACE is
  invocation.contract.SELECTOR_FOR_SURFACE`.
- **`MD6`** *(the `D-6` enforcement point, sharpened at r3)* No string
  literal matching `claude-` appears in `provider.py` (the delegates own
  the defaults, and `BEDROCK_ALIAS_RE` is a *pattern*, asserted
  separately as the one permitted occurrence). And **no real Bedrock
  model id appears in either new test file**: every model-id literal in
  the two files must either contain `example`, or be a bare
  `claude-`-prefixed alias used deliberately as the alias fixture. A
  source scan asserts this over both files, with the failure message
  naming `D-6` and the offending literal. The measured ids of `E5` live
  in **this document** as provenance and in no `.py` file at all.

### EV — environment assembly

- **`EV1`** `A-e`'s two legs plus `A-0`'s non-sdk leg, all in the same
  test:
  - **anthropic** (`A-0` row 1) — key set disjoint from
    `BEDROCK_ENV_KEYS`;
  - **bedrock + non-sdk backend** (`A-0` row 2) — `session_env` returns
    **`{}` exactly**, asserted for a resolution whose `region` is `None`
    *and* one whose region is set, so the result does not depend on
    whether a region happened to resolve. **This is the leg that makes
    the function total**: before `A-0` row 2 this input reached the
    assembly branch with `region=None` and produced a non-`str` value in
    a `dict[str, str]`;
  - **bedrock + sdk** (`A-0` row 4) — key set contains
    `CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION` and `AWS_DEFAULT_REGION`.

  The third leg is the vacuity guard for the first two (`A-e`): without
  it, an implementation returning `{}` unconditionally passes both
  disjointness assertions.
- **`EV2`** The bedrock leg sets `AWS_REGION` and `AWS_DEFAULT_REGION` to
  **the same** resolved region, and both are present whenever either is.
- **`EV3`** `AWS_PROFILE` is present **iff** a profile resolved, and the
  small-fast key is present **iff** `bedrock.models.small_fast` is set —
  each asserted in both directions. The `SMALL_FAST_ENV_VAR` string
  literal occurs **exactly once** across `src/self_learn/` (a source
  scan), so `VB-1`'s answer is a one-line edit.
- **`EV4`** `session_env`'s key set is a **subset of
  `BEDROCK_ENV_KEYS`** on every input — so a key added without being
  declared fails — and contains no key matching `ANTHROPIC_MODEL`,
  `ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_SESSION_TOKEN` or `AWS_BEARER_TOKEN_BEDROCK` (`A-c`, `SEC-1`).
- **`EV5`** `A-d`'s runtime witness: `dict(os.environ)` is byte-identical
  before and after driving `resolve`, `model_for`, `session_env`,
  `preflight` and `cli.main(["doctor", "invocation"])` under
  `provider=bedrock` with every switch set.
- **`EV6`** `session_env` raises `ProviderRefused` when handed a
  resolution carrying a refusal, and the exception's `str()` **is**
  `resolution.refusal` — so an SdkBackend that ignores the refusal and
  asks for env anyway cannot obtain env.

### NS — no secret, ever

- **`NS1`** `config.PROVIDER_KEYS` is exactly `Key-1`'s seven entries —
  asserted as an equality against a literal tuple in the test, so an
  eighth key is a deliberate, reviewed act.
- **`NS2`** With a scratch `AWS_SHARED_CREDENTIALS_FILE` containing
  `[sandbox-profile]` and `aws_secret_access_key = not-a-real-key-DO-NOT-USE`,
  the credential probe reports the `profile-file` mechanism **and the
  profile name is present**, while the string
  `not-a-real-key-DO-NOT-USE` appears **nowhere** in the probe's return
  value.
- **`NS3`** The **entire** stdout+stderr of `cli.main(["doctor",
  "invocation"])`, run with every credential mechanism seeded with
  fake values (env vars, credentials file, config file, SSO cache
  entries, web-identity token file), contains **none** of those values.
  Asserted per seeded value, each named in the failure message.
  **Positive control in the same test:** the profile *name*
  `sandbox-profile` and the region **are** present — so a doctor that
  printed nothing at all could not pass.
- **`NS4`** No file under `~/.aws` (or the scratch redirections of it) is
  opened for anything but the profile-section boolean: the test
  monkeypatches `Path.read_text` / `open` on the credential paths and
  asserts the SSO-cache `*.json` entries are **counted, never opened**.
- **`NS5`** The doctor writes no file and creates no directory:
  a `tmp_path`-rooted `SELF_LEARN_HOME`, `XDG_CACHE_HOME` and
  `XDG_RUNTIME_DIR` are byte-identical (recursive listing + content
  hashes) before and after the run.

### DC — the doctor

- **`DC1`** `Doc-c`: on a pristine home with no `config.yaml` and no
  relevant env, `cli.main(["doctor", "invocation"])` returns **0** and
  emits **zero** `FAIL` rows. Every one of `DOCTOR_ROWS` appears exactly
  once, in `Doc-b`'s order.
- **`DC2`** The `switches` row names all four surfaces with their
  resolved backend **and the rung that answered**, and changes when a
  rung changes — driven at three different rungs.
- **`DC3`** `Doc-f`'s four verdict states, each driven independently:
  wholly-inert (`provider=bedrock`, all four surfaces `cli`) → **FAIL**;
  mixed (at least one `sdk`, at least one `cli`) → **no FAIL row
  anywhere in the output** and exit 0; all-`sdk` → PASS; `anthropic` →
  SKIP regardless of backend. **The mixed leg is the anti-cry-wolf
  control** and asserts the *absence* of `FAIL` across the whole run, not
  merely the `rollout` row's own verdict — a build that moved the scold
  to a different row would otherwise pass.
- **`DC4`** The `sdk` row is driven through an **injected importer**
  (`B-7`): a fake module with `__version__` and
  `_cli_version.__cli_version__` produces PASS when the bundled and host
  CLI versions match and **WARN** when they differ; an importer that
  raises `ImportError` produces **SKIP**. **The skew leg's fixture is the
  measured live skew (`E3`), not a hypothetical**: SDK `0.2.121`, bundled
  CLI `2.1.212`, host CLI `2.1.226` — the state of this machine at
  `c2669a9` — so the criterion's worked example is a configuration that
  actually exists and the WARN it produces is one an operator sees today.
  One further leg runs the **real** importer and asserts only that the
  row does not raise.
- **`DC5`** The `region` row FAILs under `provider=bedrock` with no
  region from any rung, names both target env vars when a region
  resolves, and is SKIP under `provider=anthropic`.
- **`DC6`** `Id-1b`/`Id-1c` in both directions: `claude-sonnet-5` FAILs
  with the message containing `Anthropic alias, not a Bedrock id`;
  **`us.anthropic.claude-example-v0:0`** does **not** FAIL (the
  anchored-not-substring control);
  `arn:aws:bedrock:us-east-1:000000000000:inference-profile/example-profile`
  and a bare `vendor.model` id do not FAIL; and a shape matching no hint
  WARNs rather than FAILing. **Every id literal in this criterion is a
  non-real placeholder** (`D-6`), which `MD6` independently enforces over
  the whole test file.

  **`Doc-i`'s gating, asserted per surface (r4, MAJOR-A).** The same
  alias `claude-sonnet-5` produces **FAIL** on a surface resolving
  `backend=sdk` and **INFO** on one resolving `backend=cli`, within a
  single doctor run, with `provider=bedrock` throughout. Asserted in both
  directions in one test so a build that gates the wrong way — or does
  not gate at all — fails whichever way it errs. Under
  `provider=anthropic` every `models` line is SKIP.
- **`DC7`** `A-f`: with `provider=anthropic` and an ambient
  `CLAUDE_CODE_USE_BEDROCK=1` in `os.environ`, the `env` row is **WARN**
  and names the ambient key; with no ambient key it is PASS.
- **`DC8`** The `orphans` row is **SKIP** when U-sdk's report symbol is
  absent, renders the report when a fake one is injected, and — asserted
  by AST scan of **`preflight`'s call graph** (`Doc-0` gives the scan its
  named entry point; before r3 it had none) within `provider.py` and
  `selfcheck.py` — contains no `os.kill`, `os.killpg`, `signal.`,
  `.unlink(`, `.write_text(`, `.rmdir(` or `shutil.rmtree`.
- **`DC9`** `Doc-d`: the handoff block appears after `doctor: ---`,
  carries **exactly** the fixed field set, one `doctor: handoff: ` line
  each, and the whole block is byte-free of any seeded credential value
  (a second reader of `NS3`'s seeded fixture, scoped to the block).
  `Doc-d1`: each `env-keys.<surface>` value **equals** that surface's
  `Doc-h` line's detail — asserted as an equality between the two
  rendered strings, not by re-deriving the expected text, so the two
  sites cannot drift. `Doc-d0`: on the **zero-spawn path** (SDK not
  importable — the shipped default), `cli-version.host` carries exactly
  `(not probed — sdk row skipped)` and `cli-version.bundled` carries
  `(not probed — sdk not installed)`, so the fixed-field assertion has a
  defined subject on the commonest path rather than an absent one.
- **`DC10`** `Doc-a`'s network and spawn guarantee, with the one
  exception carved out precisely: `socket.socket` is patched to fail the
  test if called **at all**, and `subprocess.run` / `subprocess.Popen`
  are patched to a recorder that fails the test on **any argv other than
  `Doc-a`'s two-element `[<resolved claude>, "--version"]`**. The doctor
  runs to completion under both providers. **Asserted in both
  directions**: with the SDK importer absent the recorder fires **zero**
  times (the row SKIPs before spawning), and with a fake importer present
  it fires **exactly once**.
- **`DC11`** The selftest row: `run_selftest`'s `results` list has
  **8** entries, the eighth is named `invocation`, its `ok` is `False`
  **iff** the doctor produced at least one FAIL, its reason contains
  `self-learn doctor invocation`, and the printed output carries
  `PASS invocation` on the default posture.
- **`DC12`** `Doc-f`'s INFO lines are **per-surface and accurate**. On a
  mixed install (`provider=bedrock`; `analyst` and `miner-reader` on
  `sdk`, `worker` and `worker-repair` on `cli`) the `rollout` row emits
  exactly four INFO lines, one per surface; the two `cli` lines carry
  `backend=cli — provider does not apply` and the two `sdk` lines carry
  `backend=sdk provider=bedrock` plus that surface's own check verdicts.
  **Asserted per surface, not as a substring of the whole block**, and
  the assignment flips when the backends flip — so a build that prints a
  fixed four-line template regardless of resolution fails.

  **The fixture is `Doc-i`-shaped (r4, MAJOR-A)**, matching `DC16`'s:
  Bedrock ids configured only for `analyst` and `miner-reader`, aliases
  left standing on the two `cli` surfaces, and the whole run FAIL-free.
- **`DC13`** `Doc-a`'s carve-out is **byte-pinned and degrades to SKIP**.
  The recorded argv has `len(argv) == 2`, `argv[1] == "--version"`, and
  `argv[0]` equal to the resolved host path (`SELF_LEARN_SDK_CLI_PATH`
  when set, else `shutil.which("claude")`'s answer). The call passes a
  **finite `timeout`**. Each of `FileNotFoundError`, `OSError`,
  `subprocess.TimeoutExpired`, a non-zero return code, and an
  unresolvable path produces a **SKIP** row — never a FAIL, never a
  traceback. Driven with a fake `subprocess.run` per leg.
- **`DC14`** `Doc-h`'s two properties. **(a) Per-surface:** the `env` row
  emits **four** lines on a mixed install, and each line's verdict
  matches that surface's own `A-0` outcome — PASS with a sorted key list
  for the `sdk`+bedrock surfaces, SKIP with `provider does not apply` for
  the `cli` ones. **(b) The catch:** with a refusing configuration on an
  `sdk` surface (`provider=bedrock`, region unset), the doctor **exits
  with a FAIL row carrying the refusal string** and **no
  `ProviderRefused` escapes** — asserted with an inverted
  `pytest.raises` (`try/except ProviderRefused: pytest.fail(...)`), not
  merely by checking the return code, because a propagating exception is
  the specific failure this leg exists to exclude.
- **`DC15`** `Doc-0`'s separation. `preflight(home)` returns a
  `list[Row]` and writes **nothing** to stdout or stderr (captured and
  asserted empty). Every row the command prints corresponds
  one-to-one to a `Row` `preflight` returned — asserted by
  monkeypatching `preflight` to return a **single synthetic row** and
  requiring the command's entire output to be that one row plus the
  handoff block. A `_cmd_doctor` that computes any verdict of its own
  cannot pass this.
- **`DC16`** `Doc-g`: under `provider=bedrock` with an `sdk` surface and
  **no** credential mechanism seeded, the `credentials` row is **WARN**
  (never FAIL) and its detail names IMDS as the unprobed mechanism —
  **and does not name the container mechanism**, which `Cred-1` does
  probe (NOTE-b). With a mechanism seeded it is PASS and names which one.
  **The coupling to `DC3` is asserted here too**: the mixed-rollout
  fixture is run with and without credentials and the run is FAIL-free
  both times.

  **The mixed fixture is `Doc-i`-shaped (r4, MAJOR-A):** Bedrock ids are
  configured **only for the flipped (`sdk`) surfaces**, and the `cli`
  surfaces resolve their Anthropic aliases — the state a correct
  mid-rollout install actually has. A fixture that configured Bedrock
  ids for `cli` surfaces to reach FAIL-free would be certifying a state
  no rollout produces, which is worse than the wrong verdict it was
  hiding.
### RT — the runtime refusal path

- **`RT1`** `Rs-c`'s gating and table. Both halves:
  - each of the **two** causes fires on its own input when
    `provider == "bedrock"` **and** `backend == "sdk"`;
  - `refusal is None` under `provider == "anthropic"` at any backend
    **and** under `provider == "bedrock"` at any **non-sdk** backend —
    the latter asserted over a matrix that independently varies region
    (set / unset) and model (Bedrock-shaped / `claude-` alias), so a
    build that leaks a refusal into the legitimate mixed-rollout state
    fails no matter which cause it leaked (`Rs-c1`).
- **`RT2`** `Rs-d`'s two tokens: `resolution.refusal.startswith("refused-config: ")`
  and `"self-learn doctor invocation" in resolution.refusal`, for **both**
  causes.
**`RT3`–`RT5` are driven against the REAL `SdkBackend` with the TRANSPORT
faked** (`In-b`), never against a backend double that constructs the
refusal `Outcome` itself. Each configures a genuinely-refusing state
(`provider=bedrock`, `backend=sdk`, region unset) and lets `In-d`'s
guarded call at U-sdk's extension point do the conversion. A criterion
here that scripts a `FakeBackend` to return `failure="unavailable"`
asserts its own fixture and does not satisfy the criterion.

- **`RT3`** Driving the real backend from a refusing configuration
  yields `Outcome(ok=False, failure="unavailable")` whose `detail` is
  the refusal string, **nothing raised**, and — the leg that proves the
  refusal short-circuits — **the faked transport was never invoked**:
  no session was started and no process would have been spawned.
- **`RT4`** Never-lost, on the analyst leg: the same refusing
  configuration, driven through `analyst.analyze`, produces an
  `AnalystError` whose message carries the refusal text; `teach`'s route
  path captures the record to `pending/`; the exit code is **4**
  (`teach.EXIT_ANALYST`); and the record file exists on disk afterwards.
- **`RT5`** Never-lost, on the write legs: the same refusing
  configuration on `worker` leaves the run continuing (no exception
  escapes `_invoke_claude`), and on `miner-reader` returns `None` with a
  pre-seeded stray file in the spool **still present** (the sweep did not
  run).

### IN — the U-sdk integration

- **`IN1`** With `provider=bedrock`, `backend=sdk` and every switch set,
  a spy on the SDK options object records `options.env` **equal** to
  `session_env(resolve(home, surface), home=home)` for the driven
  surface — compared against a value **recomputed in the test**, not
  captured from the same call.
- **`IN2`** With `provider=anthropic`, the same spy records an
  `options.env` whose keys are disjoint from `BEDROCK_ENV_KEYS`. **The
  leak criterion at the integration level**, and it carries `A-e`'s
  vacuity guard: the same test asserts `IN1`'s bedrock leg is non-empty.
- **`IN3`** `options.model` equals `model_for(spec.surface, home=home)`
  and `options.cli_path` equals `resolution.cli_path` when
  `SELF_LEARN_SDK_CLI_PATH` is set, and is untouched when it is not.
- **`IN4`** The extension point is **exercised**, not merely present: the
  test drives a real session through U-sdk's backend (with the transport
  faked) and fails if the spy recorded nothing. *A source grep for
  `session_env(` does not satisfy this criterion.*
- **`IN5`** `In-d`'s guarded call is **real product code at the extension
  point**. Driving the real `SdkBackend` (transport faked) from a
  refusing configuration: the returned `Outcome` has
  `failure="unavailable"` and a `detail` carrying `Rs-d`'s two pinned
  tokens; `Outcome.exc` is the `ProviderRefused` instance; the faked
  transport was **never invoked**; and **nothing propagates** out of the
  backend (inverted `pytest.raises` on `ProviderRefused`). The handler is
  asserted to be **narrow**: a different exception raised from
  `session_env` in the same position is **not** converted and does
  propagate, so a bare `except Exception` fails this criterion.

### HY — hygiene

- **`HY1`** `P-b`, in two legs of **unequal strength** — stated so,
  because r2 implied they were interchangeable (NOTE-4):
  - **AST leg (unconditional killer).** A scan of `provider.py` finds no
    module-scope import of `worker`, `miner` or `analyst`, and at least
    one such import inside `model_for`'s body. **This leg reddens under
    `M20` regardless of anything U-sdk does**, and is the criterion's
    load-bearing half.
  - **Live leg (conditional, and worth having anyway).** In a **fresh
    interpreter**, `import self_learn.provider` as the very first
    `self_learn` import succeeds; likewise `import self_learn.invocation`
    first and `import self_learn.worker` first — three subprocess runs,
    one per entry point. **This leg only observes a cycle if U-sdk
    imports `provider` at module scope**; if U-sdk defers its own import,
    the cycle never closes at interpreter start and all three entry
    points import cleanly even under `M20`. The builder records which
    branch is live in the build report.

  The live leg is kept despite being conditional because it catches a
  failure the AST leg cannot see at all: a **second-order** cycle through
  `invocation.contract` — `provider` imports `SELECTOR_FOR_SURFACE` from
  it (`MD5`), so a future edit that gives `contract.py` an upward import
  closes a loop no scan of `provider.py`'s own import list would notice.
- **`HY2`** `A-d`'s static witness: an AST scan of `provider.py`,
  `selfcheck.py`'s new function, and `cli.py`'s `_cmd_doctor` finds no
  `os.environ` mutation and no `os.putenv`/`os.unsetenv`.
- **`HY3`** *(narrowed at r3 — `Hy-a`)* No function reachable from
  `provider.py`, `preflight`, or `_cmd_doctor` writes to the filesystem.
  The AST scan bans **write primitives only**: `.write_text(`,
  `.write_bytes(`, `.mkdir(`, `.unlink(`, `.touch(`, `.rmdir(`,
  `.rename(`, `.replace(`, `shutil.rmtree`, `shutil.copy`,
  `shutil.copytree`, `shutil.move`, `os.remove`, `os.rmdir`,
  `os.rename`, and `open(` **with a mode argument containing any of
  `w`, `a`, `x`, or `+`**. Reads are permitted and required —
  `Path.read_text`, `Path.is_file`, `Path.iterdir`, `Path.glob`, and
  `shutil.which` — because the credential probe (`Cred-1`), the SSO-cache
  count and the host-CLI resolution (`Doc-a`) all need them. **`NS4`,
  `NS5` and `DC10` are what bound those reads**; `HY3`'s property is
  *writes*, and r2's blanket ban on `shutil.` and bare `open(` was
  broader than that property. **And** `NOT_REPO_TRUTH` in
  `test_lock_invariant.py` is unchanged, because a module that writes
  nothing needs no exemption (`B-6`).

---

## 5. Mutation plan

**30 mutations.** Every mutation is applied to the **built** code, the
suite is run, and the named criterion must **redden**. A mutation that
leaves the suite green is a hole in §4 and must be closed before the
gate, not explained away.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | Provider chain reorder: `config.yaml` consulted before `SELF_LEARN_PROVIDER` | `PR3` |
| `M2` | Unknown provider value falls **open** to `bedrock` instead of `anthropic` | `PR4` |
| `M3` | Unknown provider value falls **through** to the next rung instead of stopping at `anthropic` | `PR4` (the `bogus` env + `bedrock` config leg specifically) |
| `M4` | `provider_unknown_keys` returns `[]` unconditionally | `PR2`, `DC1`'s row-presence leg is **NOT** credited (the row still prints, as PASS) |
| `M5` | Remove the `^claude-` FAIL guard | `DC6`, `RT1` (`Rs-c` **Cause 2**, `bedrock-model-is-alias`) |
| `M5b` | Widen the guard to an unanchored `claude-` | `DC6`'s **negative control** leg — `us.anthropic.claude-example-v0:0` starts FAILing. Row exists because a guard that fires on everything is as broken as one that fires on nothing, and only the negative control sees it |
| `M6` | `resolve_backend_name` warns on an unknown value (duplicating the registry's warning) | `BK3` |
| `M7` | The **wholly-inert** check removed — `provider=bedrock` with all four surfaces on `cli` is accepted silently | `DC3`'s wholly-inert leg. **This is the plan's bedrock+cli mutation, re-aimed by ruling `D-18` at the state that is actually wrong.** `RT1` is **NOT** credited — the refusal table no longer contains a backend cause at all (`Rs-c`), so nothing about `resolve()` changes under this mutation |
| `M7b` | The **opposite** error: the `rollout` row FAILs whenever **any** surface resolves `cli` under `provider=bedrock` (the mixed rollout state) | `DC3`'s mixed leg, `DC12`. **`RT1` is NOT credited** *(struck at r3, NOTE-2)* — this mutation edits a **doctor verdict**, and `RT1` observes `resolve()`'s `refusal` field, which the mutation does not touch. Claiming it would leave a phantom hole at the exact location `D-18` is the ruling for, which is the worst possible place for one. **Negative control, and the reason `D-18` exists**: this is the shape the brief originally asked for, and it fires on every invocation of every correct staged rollout. A guard that cries wolf on the normal path is as broken as one that stays silent on the wrong path, and only a criterion asserting the *absence* of FAIL can see it |
| `M8` | Drop the `refused-config: ` prefix from the refusal string | `RT2` |
| `M8b` | The refusal **raises** out of the seam instead of returning an `Outcome` | `RT3`, `RT4`, `RT5`. **This is the plan's never-lost mutation** |
| `M9` | `model_for` rung 3 returns the literal `"claude-sonnet-5"` instead of calling the delegate | `MD1`. **Negative control, and the reason `MD1` exists:** `MD2`, `MD3`, `MD4`, `MD5` and every `DC` row stay **GREEN** — at the shipped defaults the copied value and the delegated value are the same string |
| `M10` | `session_env` writes its dict into `os.environ` **as well as** returning it | `EV5` (runtime witness), `HY2` (static witness). **Both must redden**; if only one does, the other is the hole |
| `M11` | Set only `AWS_REGION`, not `AWS_DEFAULT_REGION` | `EV2` |
| `M12` | Inline the small-fast var name at a second site instead of referencing the constant | `EV3`'s occurs-exactly-once leg |
| `M13` | Add `ANTHROPIC_MODEL` to the assembled dict | `EV4` (the subset-of-`BEDROCK_ENV_KEYS` leg) |
| `M14` | The anthropic leg emits `CLAUDE_CODE_USE_BEDROCK` | `EV1` leg 1, `IN2`. **The plan's leak mutation** |
| `M15` | `session_env` returns `{}` on **every** input | `EV1` leg 2, `EV2`, `EV3`, `IN1`. **Negative control:** leg 1 alone stays green, which is why leg 2 exists |
| `M16` | The `sdk` row FAILs unconditionally when the SDK is not importable | `DC1`, `DC4`, `SU4` (the selftest goes red on the default posture) |
| `M17` | The handoff block prints the credential probe's matched line rather than the mechanism name | `NS3`, `DC9` |
| `M18` | The doctor shells out to `aws sts get-caller-identity` to check credentials | `DC10`, and `NS5` if it writes a cache |
| `M19` | *(re-aimed at r3, MAJOR-6)* The profile-section probe returns **the matched section's CONTENTS** — every line from the `[<profile>]` header to the next header — instead of a boolean | `NS2`. Row re-aimed because r2's version (return the matched **header line**) was **inert**: the header line is `[sandbox-profile]`, which contains no secret, and `NS3`'s positive control **requires** the profile name to appear in the output anyway — so the old mutation changed nothing either criterion could see. Returning the section body is the mutation that actually carries `aws_secret_access_key = …` into the return value, where `NS2`'s per-value absence assertion kills it. **`NS3` is NOT credited** — it reads the doctor's rendered output, and a probe that returns more than it prints is invisible there |
| `M20` | Move `provider.py`'s delegation imports to module scope | `HY1` — **specifically the AST leg, which is the unconditional killer**. *(Emphasis corrected at r4, NOTE-a: r3 credited the fresh-interpreter leg first, which inverts the priority — in the branch where **U-sdk defers its own import**, no cycle closes at interpreter start and that leg stays **GREEN** under this mutation. Crediting it as the primary killer would leave a phantom hole of exactly the shape struck from `M7b`.)* The live leg reddens **only** in the U-sdk-imports-at-module-scope branch; the builder records which branch is live (`HY1`) |
| `M21` | `_cmd_doctor` renamed to `_doctor_cmd` (dodging the `_ARGV_FOR` census) | `SU3`. Row exists because dodging a fail-closed registry is the tempting fix when `B-4` bites, and it silently removes the command from the held-lock audit |
| `M22` | The selftest row is printed as a bare line (like `"selftest: worker: M2 — not checked"`) instead of joining `results` | `DC11`, `SU4` — it can no longer fail, which is the whole point of the row |
| `M23` | *(r3, MAJOR-1)* Argv drift at `Doc-a`'s carve-out: `["claude", "--version", "--json"]`, or `--version` replaced by `-p ""`, or the `timeout` dropped | `DC13`, `DC10`'s exactly-once recorder. **The carve-out is the one place this unit spawns anything**, so an unpinned argv there is the one place a diagnostic could quietly become an invocation |
| `M24` | *(r3, MAJOR-2)* `A-0` row 2 removed — `session_env` assembles provider vars for a `bedrock` + **non-sdk** resolution | `EV1`'s non-sdk leg, `DC14`(a). With `region=None` the mutant additionally puts a non-`str` into a `dict[str, str]`, which is the type error r2 left reachable |
| `M25` | *(r3, MAJOR-5)* `_cmd_doctor` computes one row's verdict inline instead of taking it from `preflight` | `DC15` — the synthetic-single-row leg, which is the only thing that can see a verdict the printer invented. **`DC1` is NOT credited**: the row still prints and still reads PASS on the default posture |
| `M26` | *(r3, MAJOR-2)* The doctor does **not** catch `ProviderRefused` — it propagates out of `_cmd_doctor` | `DC14`(b)'s inverted `pytest.raises`. The command traceback on exactly the misconfiguration it exists to explain; a plain return-code check would read the crash as a non-zero "FAIL" and pass |
| `M27` | *(r4, MAJOR-A)* `Doc-i` removed — the `models` row's `Id-1` FAIL is **un-gated** and applies to every surface under `provider=bedrock` | `DC6`'s gating leg, `DC12` and `DC16`'s mixed fixtures (which go from FAIL-free to FAILing), and `DC11` (the selftest row turns red on a healthy mid-rollout install). **This is the shape the r2/r3 spec actually had**, which is why the row exists: it fires on a *correct* install, and the second-order harm is that the only way to keep `DC3`'s mixed leg green under it is a fixture configuring Bedrock ids for `cli` surfaces — a state no rollout produces |

**`M9` is the mutation this document is most afraid of.** It is
invisible: at the shipped defaults `worker.worker_model()` and the
literal `"claude-sonnet-5"` are the same string, so every functional
criterion, every doctor row and every integration assertion stays green.
It becomes visible only the day someone changes `DEFAULT_WORKER_MODEL` or
sets `SELF_LEARN_WORKER_MODEL`, at which point the SDK path and the CLI
path silently run different models. `MD1` is the only guard, and a gate
that finds `MD1` weakened should treat the unit as failed.

**`M7`/`M7b` and `M14` are the plan's named mutations**, with `M7`
re-aimed by ruling `D-18` and `M7b` added as its opposite. They are a
matched pair on purpose: `M7` is silence where a scold belongs, `M7b` is
a scold where silence belongs, and a criterion set that kills only one of
them has not specified the behavior, it has specified a direction.
**`M15` is the one the plan did not name** and is the more likely
accident: a leak test alone accepts an implementation that never
assembles anything.

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** `provider.py` lives at **root**, not under `invocation/`
  (`P-a`), with deferred delegation imports (`P-b`).
- **`D-2`** *(RULED, `Q-2`)* `provider` is **install-wide**; `backend`
  stays per-surface. This follows the plan's own config shape —
  `provider.name` sits at the top level while per-surface granularity
  already lives in the models table and in the backend switches — and the
  rollout pattern does not need more: **mixed backend flips already
  deliver attended-analyst-first**, which is the only staging anybody
  asked for. A per-surface provider would double the precedence matrix,
  the doctor's rows and the refusal surface for no operator benefit.
  Recorded as a future config extension in residual `R-8`, to be taken up
  only if a real need appears. The consistency and rollout rules are
  still evaluated **per surface**, because `backend` is.
- **`D-3`** Unknown provider value falls closed to `anthropic`, with
  U-seam's two warning spellings and `config._warn` reuse (`Pv-b`).
- **`D-4`** The backend name is **re-derived** rather than read from the
  registry, because `registry.py` is outside this unit's file surface,
  and the duplication is converted into evidence by `BK1` (`Rs-a`).
- **`D-5`** `resolve_backend_name` is silent; the registry keeps
  ownership of the warning (`Rs-b`).
- **`D-6`** *(narrowed at r3, BLOCKER-1)* **No real Bedrock model id
  ships in any default, fixture, or example a user could copy into
  configuration** — not as a default, not in a test fixture, not in a
  docstring example, not in `provider.py`. Unset means the doctor names
  the exact config key (`Mod-3`, `MD6`). **The ban is on
  copy-into-config surfaces, not on citing a measurement**: `E5` and
  `Id-1a` quote ids extracted from the CLI binary as *evidence that the
  shape is non-uniform*, which is the only reason `Id-1`'s hint set is
  advisory rather than strict. r2 wrote "anywhere", which forbade its own
  evidence; the narrowed wording is what `MD6` actually enforces.
- **`D-7`** Rung 3 of `model_for` **calls** the shipped functions
  (`Mod-2`), and `MD1` makes the delegation falsifiable.
- **`D-8`** The small-fast model is **config-only** — no fifth env var
  (`E-a`).
- **`D-9`** An ambient `CLAUDE_CODE_USE_BEDROCK` is **reported, not
  neutralized** (`A-f`). Writing `="0"` would be a guess about the CLI's
  truthiness parsing (`VB-3`), and a wrong guess would silently disable
  a deliberate operator setting.
- **`D-10`** A provider refusal is `failure="unavailable"` with a
  `refused-config: ` detail prefix, **not** a sixth `FAILURE_KINDS`
  member (`In-c`). This buys never-lost with zero edits to `contract.py`,
  `analyst.py`, `worker.py` or `miner.py`.
- **`D-11`** The doctor's default posture can never FAIL (`Doc-c`) — the
  selftest row makes this load-bearing for every existing user.
- **`D-12`** The doctor never calls an API and never probes IMDS
  (`Doc-a`, `Cred-1`), and never acts on the orphan report (`Doc-e`).
- **`D-13`** Model-id validation is **one FAIL guard plus advisory
  hints** (`Id-1`), because the shipped id shapes are not uniform (`E5`)
  and a strict regex would false-FAIL a shipped no-version id (`Id-1a`).
- **`D-14`** The two bounded edits to existing test files are declared,
  enumerated and bounded by `SU2` rather than avoided by renaming
  `_cmd_doctor` or by printing the selftest row outside `results`
  (`M21`, `M22`).
- **`D-15`** The SDK probe takes an **injected importer** (`B-7`), or its
  skew branch is untestable in this package.
- **`D-16`** `SELECTOR_FOR_SURFACE` is **imported** from
  `invocation.contract`, not re-spelled (`B-8`, `MD5`).
- **`D-17`** The integration contract is **abstract** and its symbol is
  named in the build report, not guessed here; a shape mismatch is a
  **stop-and-report**, not a reshape (`In-a`).
- **`D-18`** *(r2, RULED `Q-1`)* **`provider=bedrock` + `backend=cli` is
  neither refused nor warned about at runtime, because it is a legitimate
  intermediate state of the approved staged rollout** (`Rs-c1`). The
  brief's runtime-refusal obligation for that combination is
  **withdrawn**. What replaces it: refusals are gated to the SDK leg
  (`Rs-c`), the doctor FAILs only the **wholly-inert** config (`Doc-f`),
  every mixed state renders as per-surface **INFO** (`DC12`), and the
  silent inertness under `cli` is a documented residual (`R-1`) rather
  than a defect. The SDK-leg session-build shape checks and the
  `refused-config: ` never-lost path are unchanged. `M7b` is the standing
  guard against re-introducing the scold.

---

## 7. Out of scope, residuals, and the verify-at-build ledger

### 7.1 Deliberately not built

- **No `SdkBackend`.** U-sdk.
- **No live Bedrock call, no credential validation, no `sts`
  round-trip.** Impossible here and forbidden by `Doc-a`.
- **No credential *management*** — no writing `~/.aws`, no SSO login, no
  profile creation. This unit reads presence and nothing else.
- **No provider for the CLI backend, and no runtime complaint about
  it.** Under `backend=cli` the provider config is inert by construction
  (the CLI leg assembles no env). That is residual `R-1` and ruling
  `D-18` — a rollout mechanism, deliberately silent at runtime and
  diagnosed only by the doctor.
- **No retry, no fallback provider, no cross-region failover.**
- **No `ANTHROPIC_BEDROCK_BASE_URL` / `CLAUDE_CODE_SKIP_BEDROCK_AUTH`
  support.** Both exist in the CLI (`E1`) and both are escape hatches for
  proxies and non-standard auth. Neither is in the approved plan; adding
  them would widen the credential surface this unit exists to keep
  narrow.

### 7.2 The UI package is untouched

`plugins/self-learn/ui/` has its own `claude_agent_sdk` dependency and
its own engine. This unit does not touch, import, or unify with it
(`SU5`). Its installed SDK was **read** for measurements `E2`/`E3` —
reading a site-packages file is not a dependency.

### 7.3 Residuals this unit accepts, with owners

- **`R-1` — under `backend=cli` the provider configuration is silently
  inert, BY DESIGN.** *(RULED, `D-18`.)* The CLI leg assembles no
  environment, so a `provider: bedrock` setting does nothing for that
  surface and the child inherits whatever the operator's shell says.
  **This is the rollout mechanism, not a defect**: the approved staged
  flip (analyst → miner → worker) makes a mixed install the normal
  intermediate state, and an install-wide provider (`D-2`) means some
  surfaces are always on `cli` while the flip is in progress. Any runtime
  warning or refusal on that combination would fire on every invocation
  of every correct rollout.
  **What catches the failure mode instead:** the doctor's `rollout` row
  FAILs the wholly-inert config (`Doc-f`, `DC3`) — the forgot-to-flip
  trap — and renders every other state as per-surface INFO (`DC12`).
  **Owner: the docs unit's runbook**, whose obligation is one line —
  *run `self-learn doctor invocation` after any `provider` or `backend`
  change* — plus an `FW` row pointing at it.
- **`R-2` — no Bedrock model id is shipped** (`D-6`), so a
  `provider=bedrock` install is non-functional until the operator fills
  in `provider.bedrock.models.*`. Deliberate. The doctor names each
  missing key. Owner: documentation — the same docs-unit runbook row
  `R-1` opens.
- **`R-3` — an unset `small_fast` under bedrock is a WARN, not a FAIL.**
  Whether the CLI ever invokes its small/fast model — and therefore
  whether an Anthropic-alias default is fatal there — is `VB-4` and could
  not be settled from here. Owner: `VB-4`.
- **`R-4` — the IMDS / instance-profile credential mechanism is not
  probed** (`Cred-1`), so a doctor run on an EC2 instance with an
  instance role reports no mechanism while credentials in fact resolve.
  **This residual is why `Doc-g`'s verdict is WARN and never FAIL.** The
  operator-facing wording is **`Doc-g`'s**, stated once there and
  referenced here (NOTE-c) — r3 restated it in both places, and the two
  copies had already drifted (`Doc-g`'s named the container mechanism,
  which `Cred-1` does probe). Owner: an `FW` row.
- **`R-5` — `test_selftest_reports_seven_checks_criterion_12`'s NAME
  goes stale** when `B-5`'s two strings become "8". `SU2` forbids
  renaming it in this unit (a rename is a third changed line). Owner: an
  `FW` row.
- **`R-6` — the orphan row's contract is U-sdk's.** This unit consumes an
  optional exported report function and SKIPs when it is absent
  (`Doc-e`); the sidecar layout, the staleness rule and the reaping
  policy are U-sdk's to define. Owner: U-sdk.
- **`R-7` — the failure class this unit's suite structurally cannot
  reach.** IAM denials, model-access-not-granted, region-not-enabled,
  inference-profile-not-found, and throttling all surface only against a
  live endpoint. **No criterion in §4 covers any of them.** The doctor's
  handoff block (`Doc-d`) is the entire mitigation. Owner: the first
  operator with AWS access; an `FW` row records that the first live run
  is itself an experiment whose result belongs in the ledger.
- **`R-8` — per-surface `provider` as a future config extension.**
  *(RULED, `D-2`: not built.)* Should a real need appear — one host
  mining on Bedrock while routing on the API, for a reason mixed backend
  flips cannot serve — the extension point is `Key-1`: a
  `provider.surface.<surface>.name` branch above the flat
  `provider.name` rung, leaving `Prov-1`'s three rungs as the fallback.
  Nothing in this unit forecloses it; nothing in this unit builds it.
  Owner: an `FW` row, opened only on a stated need.

### 7.4 Handed to `03-decisions.md`

- **`S-36`** — the provider switch exists, is install-wide, is orthogonal
  to `backend`, and `bedrock` requires `sdk`.
- **`S-37`** — **no credential may enter `config.yaml`** (`SEC-1`);
  every credential check is presence-only and the ledger is a published
  repo.

### 7.5 Verify-at-build ledger

**Each item below is an open question this unit could not settle. The
builder MUST resolve each against live documentation at build time, and
the build report MUST carry the source (URL or the exact local artifact)
and the answer.** An unresolved item is a blocked build, not a caveat.

| # | Question | What is already measured | Where it lands |
|---|---|---|---|
| `VB-1` | **The small-fast model env var's exact name.** `ANTHROPIC_SMALL_FAST_MODEL` or `ANTHROPIC_DEFAULT_HAIKU_MODEL`? | **Both** literals are present in CLI 2.1.226 (`E1`), along with `ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_OPUS_MODEL`. Presence proves neither is current. | `SMALL_FAST_ENV_VAR` — one constant, one literal (`A-b`, `EV3`) |
| `VB-2` | **`AWS_REGION` vs `AWS_DEFAULT_REGION` semantics** — which does the CLI's AWS client actually consult, and does one shadow the other? | Both literals present in CLI 2.1.226 (`E1`). This unit sets **both** so the answer cannot change behavior (`A-a`). | Confirms `A-a` is correct rather than merely safe; if one shadows the other with a *different* value, `EV2`'s same-value assertion is what keeps it harmless |
| `VB-3` | **How the CLI parses `CLAUDE_CODE_USE_BEDROCK`'s value** — is `"0"` false, or is any non-empty value true? | Not determinable from the stripped binary. | Decides whether `D-9`'s report-don't-neutralize stance can ever become neutralization; if `"0"` is false, a future unit may add it |
| `VB-4` | **Is an unset small-fast model fatal under Bedrock?** i.e. does the CLI fall back to a hardcoded Anthropic alias that Bedrock will reject? | Not determinable here. | Decides whether `R-3`'s WARN should be a FAIL |
| `VB-5` | **Current Bedrock model-id and inference-profile shapes**, including whether the version suffix is optional and which regional prefixes exist. | CLI 2.1.226 ships all three of `…-v1:0`, `…-v1`, and no-version forms, and only `us.` prefixes appear in the binary (`E5`). | `Id-1`'s three advisory hints; a documented prefix this unit's hint set omits must be added |
| `VB-6` | **Whether `claude-*` aliases are ever valid Bedrock ids** (the guard's premise). | Not determinable here; every Bedrock id in the binary is prefixed. **Ruled: keep FAIL** — currently documented Bedrock id forms (full model ids, regional inference profiles) do not resolve bare Anthropic aliases. | `Id-1`'s FAIL guard, with `VB-6a`'s substitution list **pre-written** so a doc-reality flip costs a text edit, not a spec round |

**`VB-6a` — the FAIL→WARN substitution, pre-authorized and bounded.**
The builder **re-confirms `VB-6` from live documentation at build time**.
**If and only if** `claude-*` aliases turn out to be documented as
resolvable on Bedrock, the builder applies exactly these **four
substitutions** and records them, with the citation, in the build report.
No gate round is required, because the substitution is specified here
rather than discovered there:

| # | Site | Substitution |
|---|---|---|
| 1 | `Id-1` (§3.8) | `BEDROCK_ALIAS_RE`'s verdict changes **FAIL → WARN**, message becomes *"Anthropic alias — resolvable, but the explicit Bedrock id is clearer"*. The anchoring and the three advisory hints are unchanged. |
| 2 | `Rs-c` (§3.5) | Cause 2 (`bedrock-model-is-alias`) is **struck** from the refusal table, leaving one cause (`bedrock-needs-region`). A WARN is not a refusal. |
| 3 | `DC6` (§4) | The `claude-sonnet-5` leg's expected verdict changes FAIL → WARN. **The negative control is unchanged** — `us.anthropic.claude-example-v0:0` must still produce neither — and it is what keeps the guard honest under either verdict. |
| 4 | `RT1`/`RT2` (§4) | The alias-cause leg is dropped; "two causes" becomes "one cause" in `RT1` and "both causes" becomes "the cause" in `RT2`. `RT1`'s non-sdk gating leg is unchanged. |

Consequential, not a fifth edit: `M5`'s must-redden list narrows from
`DC6`, `RT1` to `DC6` alone. **`M5b` is unchanged and still required** —
it guards the WARN against unanchored widening exactly as it guarded the
FAIL. If the answer is the expected one, none of this applies and the
row closes with the citation alone.

**`VB-0` — the discipline.** Every answer must come from documentation
current at build time, quoted in the build report with its source. An
answer inferred from the CLI binary's string table is **evidence, not
verification**: the strings prove a name exists somewhere in 2.1.226,
never that it is the supported way to spell the thing today. The
measurements in §9 are labeled accordingly.

---

## 8. Conflicts between the approved plan and current master

Flagged, not silently resolved.

**`X-1` — `Outcome(ok=False, status="refused-config")` is not
constructible.** `Outcome` has fields
`ok, rc, stdout, detail, failure, exc` and no `status`; `FAILURE_KINDS`
has five members and `"refused-config"` is not one. Both live in
`invocation/contract.py`, outside this unit's file surface, and a sixth
kind would additionally require editing `analyst.analyze`'s dispatch
table (U-seam `W-h`). **Resolved by `In-c`/`D-10`:** `failure="unavailable"`
plus a pinned `refused-config: ` detail prefix — which reaches
never-lost with **zero** call-site edits, where the plan's shape would
have required four.

**`X-2` — "the runtime refuses bedrock+cli too" is WITHDRAWN, not
worked around.** *(RULED `D-18`; r1 raised this as a file-surface gap and
the ruling reframed it as a design error in the obligation itself.)* The
runtime refusal the brief describes lives in the `SdkBackend`, which
`backend=cli` never reaches — but the decisive objection is not
reachability, it is that **the combination is correct**. The approved
rollout flips surfaces one at a time under an install-wide provider
(`D-2`), so `provider=bedrock` with some surfaces still on `cli` is what
a *healthy* rollout looks like from the first flip to the last. A runtime
refusal or warning there would fire on every clean invocation and teach
the operator to ignore the channel.

**Resolved by `D-18`:** the obligation is dropped; the doctor FAILs only
the wholly-inert config (`Doc-f`, `DC3`), mixed states render as
per-surface INFO (`DC12`), and mutation `M7b` is the standing guard
against re-introducing the scold. The SDK-leg refusals (`Rs-c`) and the
`refused-config:` never-lost path are untouched. Residual `R-1` records
the silent inertness with its rationale and its runbook owner.

**`X-3` — the doctor cannot be added without touching two existing test
files.** `_cmd_doctor` must be registered in `test_lock_invariant.py`'s
fail-closed `_ARGV_FOR` (`B-4`), and an eighth selftest row moves two
byte-pinned counts in `test_selftest.py` (`B-5`). The plan's "NEW test
files only" cannot hold literally. **Resolved by declaring both edits,
bounding them to three lines total, and making the bound itself a
criterion (`SU2`)** — plus mutations `M21`/`M22` for the two ways a
builder might dodge them instead.

**`X-4` — `provider.py` cannot live under `invocation/`.** The plan
offers `invocation/` or `src/self_learn/` as equal options; they are not.
U-seam's `HY2` forbids `invocation/**` from importing `worker`, `miner`
or `analyst`, and `model_for`'s delegation requires exactly that.
**Resolved by `P-a`** (root placement, deferred imports, `HY1`).

**`X-5` — `SELF_LEARN_SDK_CLI_PATH` is not `options.env`.** The plan
lists it among the env overrides. `cli_path` is a distinct
`ClaudeAgentOptions` field (`E2`); putting the path in the environment
would do nothing. **Resolved by `E-b`:** it is a resolution field, not an
assembly key, and `PR6` asserts it never appears as an env key.

**`X-6` — a strict Bedrock model-id regex would reject shipped ids.**
The plan asks for a format check "against documented Bedrock shapes".
Measured (`E5`), CLI 2.1.226 ships ids with `-v1:0`, with `-v1`, and with
no version segment at all. **Resolved by `Id-1`:** one anchored FAIL
guard, three advisory hints, WARN for everything unrecognized — with the
negative control (`DC6`, `M5b`) that keeps the guard from widening.

---

## 9. What was executed, and against what oracle

Measurements taken while writing this spec, on `c2669a9`, in a clean
worktree. A builder who cannot reproduce these should stop.

| # | Measurement | Command | Result |
|---|---|---|---|
| `E0` | CLI suite baseline | `uv run --directory plugins/self-learn/cli pytest -q --color=no` | **1711 passed, 5 skipped** in 178.25 s; 1716 collected. rc captured **unpiped**. |
| `E1` | Provider env-var names present in the shipped CLI | `grep -aoE "<names>" ~/.local/share/claude/versions/2.1.226 \| sort \| uniq -c` on the ELF binary | All present, with occurrence counts: `ANTHROPIC_DEFAULT_OPUS_MODEL` 80, `ANTHROPIC_DEFAULT_SONNET_MODEL` 68, `ANTHROPIC_DEFAULT_HAIKU_MODEL` 63, `AWS_REGION` 54, `ANTHROPIC_SMALL_FAST_MODEL` 39, `AWS_PROFILE` 32, `AWS_DEFAULT_REGION` 26, `AWS_BEARER_TOKEN_BEDROCK` 26, `CLAUDE_CODE_USE_BEDROCK` 25, `ANTHROPIC_BEDROCK_BASE_URL` 20, `CLAUDE_CODE_SKIP_BEDROCK_AUTH` 14. **Evidence, not verification** (`VB-0`). |
| `E2` | The SDK's options surface and env merge | read of `claude_agent_sdk/types.py` and `_internal/transport/subprocess_cli.py` @ 0.2.121 | `ClaudeAgentOptions` has `env: dict[str, str]`, `model: str \| None`, `cli_path: str \| Path \| None`. The child's env is `{**os.environ (minus CLAUDECODE), "CLAUDE_CODE_ENTRYPOINT": "sdk-py", **options.env, "CLAUDE_AGENT_SDK_VERSION": …}` — **`options.env` overrides inherited, and inherited still reaches the child** (`A-f`). |
| `E3` | SDK installation state | `ls` of both venvs' site-packages | Installed in the **UI** venv at **0.2.121**, with `_bundled/claude` and `_cli_version.__cli_version__ = "2.1.212"`. **NOT installed in the CLI venv** (`B-7`). Host CLI is **2.1.226** — a real, currently-live skew the `sdk` row would WARN on. |
| `E4` | Pre-existing provider references | `grep -rn "SELF_LEARN_PROVIDER\|SELF_LEARN_BEDROCK\|SELF_LEARN_SDK_CLI_PATH\|bedrock\|Bedrock"` over `cli/src` and `cli/tests` | **Zero matches.** Clean slate; no name in `Env-1` or `Key-1` collides. |
| `E5` | Bedrock model-id shapes present in the shipped CLI | `grep -aoE "[a-z-]{2,6}\.anthropic\.claude[a-zA-Z0-9.-]*(:[0-9]+)?"` on the binary, `sort -u` | 17 distinct `us.anthropic.*` ids. **Three different shapes ship**: `…-20241022-v1:0`, `…-4-6-v1`, and `…-sonnet-5` (no version). Only `us.` prefixes appear. **Evidence, not verification** (`VB-5`). |
| `E6` | This host's AWS state | `ls -a ~/.aws`; `env \| grep -c "^AWS_"` | `~/.aws` **does not exist**; **0** `AWS_*` environment variables. No live Bedrock call is possible here — which is the premise of this whole unit, and of `R-7`. |
| `E7` | The `_cmd_*` census is fail-closed | read of `test_lock_invariant.py::_cmd_functions` / `test_every_cmd_surface_is_covered` | Enumerates `cli` attributes prefixed `_cmd_` and fails naming *"new dispatch surface(s) with no argv in `_ARGV_FOR`"*. `B-4` is load-bearing. |
| `E8` | The selftest row count is byte-pinned, twice | grep of `test_selftest.py` | `assert "all 7 checks green" in out` at two sites (`test_selftest_reports_seven_checks_criterion_12` and the FW-66 decode-safety test). `B-5` is load-bearing. |
| `E9` | The lock census's reach | read of `test_lock_invariant.py` | `MODULES = {p.stem for p in SRC.glob("*.py")}` and `for path in sorted(root.glob("*.py")):` — `glob`, not `rglob`. A **root-level** `provider.py` is inside the census; `invocation/**` is not (`B-6`). |
| `E11` | **The empty-value precedence asymmetry** (`Rs-a1`, `BK1`) — measured at r3 after the gate constructed the drift | a script driving `registry.backend_for` against a scratch `SELF_LEARN_HOME`, mapping `BackendUnavailable` → `"sdk"` | `SELF_LEARN_BACKEND_WORKER=""` + `SELF_LEARN_BACKEND=sdk` → **sdk** (env rung falls through). `invocation.backend_worker: ""` + `backend: "sdk"` → **cli** (config rung terminates the chain; `invocation_backend` returned `('backend_worker', '')`, so the coarser key was never read). **Positive control** — `backend_worker` absent, `backend: "sdk"` → **sdk**, proving the config rung is reachable and the cell above measures the empty-value rule, not a broken fixture. |
| `E10` | pyright whole-`src` baseline | `uv run --directory plugins/self-learn/cli pyright --pythonpath .venv/bin/python src` | **50 errors, 0 warnings**, rc 1. Same figure U-seam gate-measured at `83d05c6`. The build's requirement is **delta = 0** against this. |

**Not measured, and therefore not claimed:** that any Bedrock model id,
region, credential mechanism, or IAM policy actually works; that
`CLAUDE_CODE_USE_BEDROCK=1` plus this unit's env dict produces a
successful call; that the small-fast variable is read at all. Those are
§7.5's ledger, and §7.3's `R-7`.

---

## 10. Values questions — routed, and RULED

All five questions r1 routed have been ruled. **This section is the
decision trail, not an open list**; nothing here is awaiting an answer.
Each row records what was asked, what was ruled, and where the ruling
landed in the normative register — so a later reader can tell a decided
question from an unexamined one.

| # | Question | Ruling | Landed in |
|---|---|---|---|
| `Q-1` | Widen the file surface to `registry.py` so `provider=bedrock` + `backend=cli` is hard-refused at the seam? | **NO — and the obligation is withdrawn.** The combination is a *legitimate* intermediate state of the staged rollout (analyst → miner → worker under an install-wide provider), so a runtime refusal or warning would fire on every clean rollout invocation and train warn-blindness. Replaced by: doctor FAILs only the **wholly-inert** config; mixed states are **per-surface INFO**; the silent inertness is a documented residual owned by the docs unit's runbook. | `D-18`, `Rs-c` (backend cause struck; refusals gated to the sdk leg), `Rs-c1`, `Doc-f`, `DC3`, `DC12`, `M7`, `M7b`, `R-1`, `X-2` |
| `Q-2` | Is `provider` install-wide or per-surface? | **Install-wide**, per the plan's own config shape — `provider.name` at top level, per-surface granularity already in the models table and the backend switches. Mixed backend flips already deliver attended-analyst-first, so per-surface provider buys nothing and doubles the precedence matrix. | `D-2` (rationale recorded), `R-8` (future extension, opened only on a stated need) |
| `Q-3` | Are the two bounded edits to existing test files sanctioned? | **SANCTIONED.** Both are fail-closed registries doing their job; the numstat bounds and the dodge-mutations are the right containment. | Unchanged — `SU2`, `M21`, `M22`, `X-3` |
| `Q-4` | `--selftest`'s output changes for every user (7 → 8). | **SANCTIONED.** The count changing is the selftest doing its job; `Doc-c`'s no-new-FAIL-on-default-posture guarantee is the operator-facing protection. | Unchanged — `Doc-c`, `DC1`, `DC11`, `M16` |
| `Q-5` | `VB-6` — should the `^claude-` guard be FAIL or WARN? | **Keep FAIL.** No live check is possible here, and currently documented Bedrock id forms do not resolve bare Anthropic aliases. But `VB-6` becomes **self-executing**: the builder re-confirms from live docs, and a flip costs a pre-written four-substitution text edit rather than a spec round. | `VB-6` (ruled), **`VB-6a`** (the bounded substitution list) |

---

## 11. Revision history

| Rev | Change |
|---|---|
| r1 | Initial draft, written blind against `c2669a9`. 6 plan conflicts flagged (§8), 7 residuals accepted (§7.3), 6 verify-at-build items opened (§7.5), 5 values questions routed (§10). |
| r2 | **All 5 values questions RULED** (§10's table). `Q-1` is the substantive one: the brief's *"the runtime refuses bedrock+cli too"* obligation is **withdrawn**, because under the staged rollout that combination is a legitimate state and a runtime complaint would fire on every clean rollout. Refusals are re-gated to the SDK leg (`Rs-c`), the doctor gains a `rollout` row that FAILs only the wholly-inert config and INFOs everything else (`Doc-f`), and the guard against re-introducing the scold is a new negative-control mutation (`M7b`). `Q-2`/`Q-3`/`Q-4` confirmed as specced; `Q-5` keeps FAIL and makes `VB-6` self-executing via `VB-6a`. **r2 changed no criterion outside `DC3`, `DC4`, `RT1`, `RT2` and the new `DC12`, and no mutation outside `M7` and the new `M7b`.** |

| r3 | **r2 blind gate: NOT SOUND — 1 BLOCKER / 6 MAJOR / 8 NOTE.** All 15 folded; per-finding disposition below. Criteria 56 → **61** (`DC13`–`DC16`, `IN5`); mutations 25 → **29** (`M23`–`M26`). New normative rules: `Id-1a`/`Id-1b`/`Id-1c`, `Hy-a`, `Rs-a1`, `A-0`, `Doc-0`, `Doc-g`, `Doc-h`, `Doc-d1`, `In-d`. One new measurement, `E11`. **Every r2 fact reproduced under the gate's own measurement**; all 15 findings were contract gaps. |

| r4 | **r3 delta gate: 0 BLOCKER / 1 MAJOR / 6 NOTE**; 14 of 15 r3 folds verified clean, several judged stronger than the gate's own remedies. All 7 folded; **closed under the verdict-repricing rule — last spec round, CLEARED FOR BUILD**, with the code gate verifying these folds. Criteria stay at **61** (MAJOR-A landed as legs of `DC6`/`DC12`/`DC16`, not a new criterion); mutations 29 → **30** (`M27`). New normative rules: `Doc-i`, `Doc-d0`. |

Counts live in §4's header and §5's header and are not restated here —
one register per fact.

### r4 — per-finding disposition

| Finding | Disposition |
|---|---|
| `MAJOR-A` | New **`Doc-i`**: the `models` row's `Id-1` FAIL is **gated to `sdk` surfaces**. On a `cli` surface under `provider=bedrock` the Anthropic alias is the **correct** value — `Mod-3`/`MD4` require it — so the line renders **INFO** naming that reason; under `provider=anthropic` it is SKIP. Ungated, the row FAILed a *correct* mid-rollout install, exited 1, and turned `DC11`'s selftest row red on a healthy state (`D-18`'s warn-blindness, third door). The second-order harm is recorded because it is the worse one: `DC3`'s twice-run FAIL-free mixed leg would then have been satisfiable **only** by a fixture configuring Bedrock ids for `cli` surfaces — a state no healthy rollout has, so the criterion would have gone green against a fixture misrepresenting the state it certifies. `DC6` gains the per-surface gating leg (same alias, FAIL on `sdk` and INFO on `cli` within one run, both directions); `DC12` and `DC16`'s mixed fixtures are restated as **`Doc-i`-shaped** — Bedrock ids only for flipped surfaces, aliases standing on the `cli` ones, whole run FAIL-free. New **`M27`** un-gates the FAIL and must redden `DC6`'s gating leg, both mixed fixtures, and `DC11`. |
| `NOTE-a` | `M20`'s must-redden emphasis **inverted back**: the **AST leg** is the unconditional killer and is credited first; the fresh-interpreter leg reddens **only** in the U-sdk-imports-at-module-scope branch and stays green in the defers branch. Row now says so explicitly, naming it as the same phantom-hole shape already struck from `M7b`. |
| `NOTE-b` | `Doc-g`'s detail string corrected: **"and container roles" struck**. `Cred-1` **does** probe the container mechanism (`AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` / `_FULL_URI`), so the string was false at the exact moment it rendered — a row whose job is to name what it could not see must not name something it did. `DC16` now asserts the corrected wording in both directions (IMDS named, container **not** named). |
| `NOTE-c` | **`Doc-g` owns the operator-facing line**; `R-4` restated as a reference to it plus the residual's own rationale (it is *why* the verdict is WARN). r3 had the line in both places and the two copies had **already drifted** — `Doc-g`'s carried the NOTE-b error while `R-4`'s did not, which is the register-discipline failure in miniature. |
| `NOTE-d` | `Mod-3`'s "ships no Bedrock model id **anywhere**, including fixtures" restated to `D-6`'s r3 scope: **no REAL id in any default, fixture, or example a user could copy into configuration**, noting the two deliberate placeholders and that `MD6` is the enforcement point. Last surviving site of the pre-BLOCKER-1 wording. |
| `NOTE-e` | Orphaned empty `\| Condition \| Result \|` table header removed from between `session_env`'s signature and `A-0`. `DC12` moved back ahead of `DC13` so the `DC` group prints 1–16 in order; `M27` placed after `M26` for the same reason. |
| `NOTE-f` | New **`Doc-d0`**: every handoff field has a defined value on every path. `cli-version.host` renders `(not probed — sdk row skipped)` on the zero-spawn path — **which is every install without the SDK, i.e. the shipped default** — and `cli-version.bundled` renders `(not probed — sdk not installed)`. `DC9` gains the leg, so its fixed-field assertion has a defined subject on the commonest path rather than an absent one. |

### r3 — per-finding disposition

| Finding | Disposition |
|---|---|
| `BLOCKER-1` | Gate's remedy adopted. r2's negative-control fixture — the **real** measured id `<us-prefixed>.claude-sonnet-5`, elided here for the same reason `Id-1a` elides it — replaced by **`us.anthropic.claude-example-v0:0`** at `Id-1b`, `DC6` and `VB-6a` row 3 — the control's purpose (anchored, not substring) is preserved while the literal is unusable if pasted. `D-6` narrowed from "anywhere" to **"in any default, fixture, or example a user could copy into configuration"**, which is what `MD6` enforces; r2's wording forbade its own evidence. New `Id-1a` labels §3.8's three shapes as **measurement provenance** (and elides the `us.anthropic.` prefix so the block cannot be pasted); `E5` keeps the unelided strings as binary-string provenance. New `Id-1c` adds an ARN fixture with placeholder account `000000000000` (NOTE-7). `MD6` sharpened to scan both test files and name `D-6` in its failure. §1.4 reworded. |
| `MAJOR-1` | `Doc-a` restated with **one enumerated exception**: the `sdk` row may run `[<resolved host claude>, "--version"]`, argv byte-pinned to two elements, `timeout=10`, minimal parse, every failure leg → SKIP. Rationale recorded: it **spawns a local process and calls no API**, so the never-calls-any-API property holds; what is relaxed is a *proxy* (never spawn) that was stricter than the property. Path via `shutil.which`, honoring `SELF_LEARN_SDK_CLI_PATH`. **`HY3` narrowed to write primitives** (preferred option — this also resolves NOTE-5 at its root), with new `Hy-a` stating why: the property is *writes*, and r2's blanket ban on `shutil.` and bare `open(` forbade the reads `Cred-1`/`NS4`/`Doc-a` require. New `DC13` (byte-pin + SKIP degradation); `DC10` re-armed as an argv recorder asserted **zero** spawns without the SDK and **exactly one** with it; new `M23` (argv drift). |
| `MAJOR-2` | New **`A-0`** — `session_env`'s total rule in four ordered rows, with **row 2: `backend != "sdk"` → `{}` unconditionally**. Removes the reachability at source rather than patching the assembly branch with a region check, and says the right thing (provider vars do not apply to the CLI transport — the same fact `Doc-f`'s INFO line renders). `A-a` re-scoped to row 4. `EV1` gains the non-sdk leg, asserted with region both set and unset. New **`Doc-h`**: the `env` row is **per-surface** with three line shapes, and the doctor **catches `ProviderRefused`** and renders it as that surface's FAIL detail — a diagnostic must not die of the misconfiguration it explains. New `DC14` (both halves; the catch asserted by inverted `pytest.raises`); new `M24`, `M26`. |
| `MAJOR-3` | New **`In-d`**: the conversion owns a home — U-sdk's extension point wraps the provider call so `ProviderRefused` becomes `In-c`'s `Outcome`, stated abstractly with the builder quoting the real extension point verbatim and `In-a`'s stop-and-report standing if the real shape cannot express it. §3.9 step 2 expands from "exactly one call" to **three assignments plus the guarded-call shape**. `In-b` now forbids **two** things by name: source-grepping, and any double that constructs the refusal `Outcome` itself. **`RT3`–`RT5` restated to `IN4`'s shape** — real backend, faked transport — with `RT3` gaining a "transport never invoked" leg. New `IN5` pins the handler's **narrowness** (a different exception must propagate, so `except Exception` fails). `M8b` now has a product-code target. |
| `MAJOR-4` | Gate's constructed drift confirmed by measurement (`E11`): env-empty **falls through** (`sdk`), config-empty **terminates the chain** (`cli`), and the finer-key-absent control resolves `sdk`. **Shipped behavior is the contract**: new `Rs-a1` documents the asymmetry with its mechanism (`invocation_backend` returns the first **present** key) and states why it is defensible rather than a bug this unit fixes. `BK1`'s matrix widened 12 → **14**, with both cells and the positive control named and their expected values taken from the shipped reader. |
| `MAJOR-5` | New **`Doc-0`**: `preflight(home) -> list[Row]` with a `Row` dataclass (`name`, `verdict`, `detail`, optional `surface`/`cause`), returning the complete row list and **printing nothing**; `_cmd_doctor` is a **thin printer** computing no verdict of its own; `DC11`'s selftest `ok` computed programmatically as `not any(r.verdict == "FAIL" …)`. `DC8`'s AST scan re-pointed at **`preflight`'s call graph** — before r3 it had no named entry point. New `DC15` (asserted by monkeypatching `preflight` to a single synthetic row and requiring the command's whole output to be that row plus the handoff); new `M25`. |
| `MAJOR-6` | `M19` re-aimed exactly as the gate proved: the probe returns **the matched section's CONTENTS**, not the header line. Row records why the r2 version was **inert** — the header line carries no secret and `NS3`'s positive control requires the profile name anyway — and drops `NS3` from the credit, since a probe returning more than it prints is invisible in rendered output. `NS2` is the killer. |
| `NOTE-1` | Two-site substitution of the stale "cause 3": `Mod-3` and `M5` now name `Rs-c`'s **Cause 2** (`bedrock-model-is-alias`), matching `VB-6a`'s naming. |
| `NOTE-2` | **`RT1` struck from `M7b`'s must-redden.** The mutation edits a *doctor verdict*; `RT1` observes `resolve()`'s `refusal` field, which it does not touch. `DC3`-mixed and `DC12` are the real killers. A phantom hole at `D-18`'s exact location is the worst place to leave one. |
| `NOTE-3` | `SU3` restated as three **positive** assertions — `"_cmd_doctor" in _cmd_functions()`, its `_ARGV_FOR` entry present with a real argv, and the held-lock drive — with the reason recorded: the census computes a set *difference*, so it is blind to a **stale** key and `M21` would leave it passing. |
| `NOTE-4` | `HY1` split into legs of **unequal strength**: the AST leg is the unconditional killer of `M20`; the live three-entry-point control is **conditional on U-sdk importing `provider` at module scope** (gate measured both branches) and the builder records which branch is live. The live leg is kept for the reason the gate gave — it is the only thing that would catch a **second-order** cycle through `invocation.contract`, which `provider` imports for `SELECTOR_FOR_SURFACE`. |
| `NOTE-5` | Resolved at the root by `MAJOR-1`'s preferred `HY3` narrowing (`Hy-a`). No separate read-discipline clause needed. |
| `NOTE-6` | `Doc-b` restated: **one line per row unless the table's new "Lines" column says per-surface or per-cause**, with `DC1`'s "exactly once" clarified as being over **rows**, not lines. |
| `NOTE-7` | New **`Doc-g`**: the `credentials` verdict is **WARN, never FAIL**, decided by me and documented — because `Cred-1` provably cannot see IMDS/container roles (`R-4`), so the check cannot distinguish *absent* from *invisible to me*, and a false FAIL on a correct EC2 install is the same warn-blindness failure `D-18` refused. Coherence with `DC3` made **load-bearing**: `DC3`'s mixed leg now runs **twice, with and without a seeded credential mechanism**, FAIL-free both times. ARN placeholder fixture added at `Id-1c`. New `DC16`. |
| `NOTE-8` | `provider.py`'s symbol table completed with `DEFAULT_PROVIDER`, `MODEL_KEY_FOR_SURFACE`, `BEDROCK_ALIAS_RE`, `VERDICTS` (and `Row`, `ProviderRefused`). The env-row rendering contract collapsed to **one owner**: `Doc-h` states "sorted keys, values redacted"; new `Doc-d1` makes the handoff's `env-keys.<surface>` a **reference** to it, and `DC9` asserts the two renderings are **equal** rather than re-deriving the expected text. |

### r2 — per-ruling disposition

| Ruling | Disposition |
|---|---|
| `Q-1` | `Rs-c` rewritten: refusals **gated** to `provider=="bedrock" and backend=="sdk"`; the `bedrock-needs-sdk` cause **struck**, leaving two (region, alias). New `Rs-c1` carries the rollout rationale. New `Doc-f` (the `rollout` row) with its four-state verdict table; `DOCTOR_ROWS` gains `rollout`, `VERDICTS` gains `INFO`. `DC3` rewritten to the four verdict states with the **mixed leg asserting the absence of FAIL across the whole run**; new `DC12` for the per-surface INFO lines. `RT1` restated as gating + two causes with the mixed-state matrix; `RT2` "three causes" → "both causes". `M7` re-aimed at the wholly-inert check (and `RT1` **dropped** from its credit — the refusal table no longer has a backend cause); new **`M7b`**, the cry-wolf negative control. `R-1` rewritten as a by-design residual owned by the docs unit's runbook. `X-2` rewritten from *"gap we cannot close"* to *"obligation withdrawn, and here is why it was wrong"*. New `D-18`. |
| `Q-2` | `D-2` gains the ruling's rationale verbatim in substance (plan's own config shape; mixed backend flips already deliver attended-analyst-first; per-surface would double the precedence matrix for no operator benefit). New residual **`R-8`** naming the future extension point (`provider.surface.<surface>.name` above the flat rung) and stating it is opened only on a stated need. |
| `Q-3` | No change — `SU2`'s numstat bounds and `M21`/`M22` stand as written. Recorded as ruled in §10. |
| `Q-4` | No change — `Doc-c`, `DC1`, `DC11`, `M16` stand as written. Recorded as ruled in §10. |
| `Q-5` | `VB-6`'s row states the ruling (keep FAIL) with its reason. New **`VB-6a`**: a pre-authorized, four-row substitution table (`Id-1`, `Rs-c`, `DC6`, `RT1`/`RT2`) plus the consequential `M5` narrowing, so a doc-reality flip is a text edit the builder applies and reports, not a spec round. `M5b` explicitly retained under either verdict. |
| *(coordinator note)* | `DC4`'s skew leg now pins the **measured** live skew as its worked example — SDK `0.2.121`, bundled CLI `2.1.212`, host CLI `2.1.226` (`E3`) — rather than a hypothetical version pair. |
