# FW-30 — The settings surface (Y-26): build-grade draft spec

*DRAFT 2026-07-18. Author owns **Y-26** only. Status: unratified,
ungated — graduates via the normal spec→gate chain (14 §2 FW-30 row;
`forward/ui-ux.md` §5). Proposed final home: a **09 §11 entry Y-26**
(the editor page) plus a **config-schema section** that most naturally
amends **doc 13** (config.yaml already lives there under S-10's
hosting/commit discipline) — or, if the schema grows past a section, a
new short doc `16-operator-config.md` owning `config.yaml`'s full key
registry. This draft is written so both halves can be lifted whole.*

*Verified against master 2026-07-18: `config.py`, `env.py`,
`miner.py`, `worker.py`, `analyst.py`, `engine/sdk.py`, `routes.py`,
`ledger.py`, `scan.py`, `gitops.py`, `systemd/self-learn-miner.timer`.
File:line anchors are drift-expected — re-verify before building.*

*Doc text-fix flag (F5 — not a user ruling): doc 12 §8 Q3 reads pending-gate
`10`, but 12 §10:357-360 already supersedes it with `25`, and the code
agrees (`DEFAULT_PENDING_GATE = 25`, `miner.py:77`). Code is correct;
§8's stale `10` is a documentation edit to make when this graduates, not
a decision for anyone to route. This spec uses `25` throughout.*

---

## 0. The one invariant everything hangs on (from the charter)

The page is an **editor over committed config**
(`<ledger-home>/config.yaml`, S-10's precedent), **never a live toggle
store**. Stated precisely (F9): **the UI/verb write path never writes
config without committing it** — there is no save-to-disk-without-commit
door in this feature. This is *not* a claim that every byte of
config.yaml is git-clean at all times: the effective policy is always
**the file's current bytes**, and a hand-edit, a partial write, or
write-crash residue is live and uncommitted until the next commit — the
exact S-10 posture, where a hand-editable committed file is acceptable
*because* its parse is fail-closed (§1.1), not because the bytes are
guaranteed to match HEAD. What FW-30 adds is the guarantee that the
*UI's own* edits are auditable in git history, synced to every machine,
and revocable by a commit — like routing decisions. This is the
architectural invariant `forward/ui-ux.md` §5 flags to pin at spec
time; it governs every section below.

Second invariant, inherited from S-2: **the UI stays a thin caller.**
All write+commit mechanics live in the CLI (a new `self-learn config`
verb group, §2.2); the server builds an argv verbatim from the CLI
parser and spawns it (the `routes.build_argv` → `runner` path that
`route`/`reject`/`defer`/`mine run` already use). No config write logic
lives in the web tier.

---

## 1. The config schema

### 1.1 Format, ownership, parse discipline

`config.yaml` already exists (`config.py`, S-10). Today it carries one
section (`one_motion_route`) read by `config.one_motion_enabled()`.
FW-30 **extends the same file**, keeps its idiom exactly:

- **Loader**: `ruamel.yaml` `YAML(typ="safe")` — YAML 1.2 core schema
  (bare `yes` is the *string* `"yes"`, not a boolean; established at
  S-10 and load-bearing).
- **Fail-closed on every read** (`config.py:67` pattern, verbatim
  shape): missing file → default, silent; unparseable / wrong top-level
  shape / wrong section shape / wrong value type → **default + one
  `_warn(...)` line on stderr** (`config.py:63` `self-learn:
  config.yaml ignored — <reason>`). Fail-closed must never be silent, or
  a typo reads as a policy decision (S-10's own words).
- **Per-key independence**: one malformed key warns and defaults *that
  key only*; every other key still parses. (The existing
  `one_motion_enabled` already resolves per-destination — FW-30 keys
  resolve per-key the same way. No key's malformation may poison
  another's.)
- **Version key, day one** (migration, §6): top-level `version: 1`.
  Absent → treated as `1` with no warn (back-compat with today's
  one-section files). A `version` the running build does not recognize
  (e.g. a newer machine's schema synced back) → **warn once, read every
  key this build *does* know at its own rules, ignore the rest**. Never
  a hard fail — a future-versioned config must degrade to "this build's
  known subset", not brick the CLI on every invocation.

### 1.2 The exposed keys

Every key: type, default, consumer site, fail-closed rule. Defaults are
**the current code defaults**, so an absent/empty config.yaml is
byte-for-byte today's behavior.

```yaml
version: 1

models:                     # §1.3 — role → model name
  miner:   claude-sonnet-5
  worker:  claude-sonnet-5
  pane:    claude-sonnet-5
  analyst: claude-sonnet-5

miner:
  cadence_hours: 24         # §5
  pending_gate: 25          # DEFAULT_PENDING_GATE (miner.py:77) — see conflict note
  cap_per_session: 2        # DEFAULT_CAP_PER_SESSION (miner.py:75)
  cap_max: 15               # DEFAULT_CAP_MAX (miner.py:76); cap = min(per_session·scanned, max)
  rubric_emphasis: ""       # tier B, §4 — free-text operator note, appended

pane:
  budget_usd: 1.00          # env.py DEFAULT_PANE_BUDGET_USD
  max_turns:  15            # env.py DEFAULT_PANE_MAX_TURNS

notify:
  pending_escalation: 5     # existing ≥5-pending escalation (12 §8, worker digest)
```

| Key | Type | Default | Consumer (verified) | Fail-closed rule |
|---|---|---|---|---|
| `version` | int | `1` | §6 migration guard | non-int → warn, treat as 1 |
| `models.miner` | str | `claude-sonnet-5` | `miner.miner_model()` `miner.py:167` → `build_reader_argv --model` `:563` | non-str/empty → default + warn |
| `models.worker` | str | `claude-sonnet-5` | `worker.worker_model()` `worker.py:263` → `build_argv --model` `:319` | non-str/empty → default + warn |
| `models.pane` | str | `claude-sonnet-5` | `env.load_env().pane_model` `env.py:121` → `pane.py:987` → `SdkPaneEngine(model=)` `sdk.py:356` | non-str/empty → default + warn |
| `models.analyst` | str | `claude-sonnet-5` | `analyst._model()` `analyst.py:115` → `build_argv --model` `:136` | non-str/empty → default + warn |
| `miner.cadence_hours` | number > 0 | `24` | derives `KICK_AFTER_SECS`/`STALE_AFTER_SECS` `miner.py:79,83` + run-gate (§5) | ≤0/non-number → default + warn |
| `miner.pending_gate` | int ≥ 0 | `25` | `miner.pending_gate()` `miner.py:162` (`DEFAULT_PENDING_GATE` `:77`) | non-int → default + warn |
| `miner.cap_per_session` | int ≥ 1 | `2` | `landing cap` `miner.py:156-158` (`DEFAULT_CAP_PER_SESSION`) | <1/non-int → default + warn |
| `miner.cap_max` | int ≥ 1 | `15` | `landing cap` `miner.py:156-158` (`DEFAULT_CAP_MAX`) | <1/non-int → default + warn |
| `miner.rubric_emphasis` | str | `""` | §4 — appended to `_rubric()` prompt as operator block | non-str → `""` + warn |
| `pane.budget_usd` | number > 0 | `1.00` | `env.py:127` `DEFAULT_PANE_BUDGET_USD` (`:39`) | ≤0/non-number → default + warn |
| `pane.max_turns` | int ≥ 1 | `15` | `env.py:132` `DEFAULT_PANE_MAX_TURNS` (`:40`) | <1/non-int → default + warn |
| `notify.pending_escalation` | int ≥ 1 | `5` | `ESCALATE_PENDING` `worker.py:95`, in `_maybe_escalate` `:1119` | <1/non-int → default + warn |

**`notify.pending_escalation` exposes ONE leg of a three-part rule
(F6).** The worker's escalation
(`_maybe_escalate`, `worker.py:1119`) fires when `total_pending ≥
ESCALATE_PENDING` **OR** `oldest_pending > ESCALATE_OLDEST_DAYS`,
debounced by `ESCALATE_DEBOUNCE_SECS`. FW-30 exposes **only**
`ESCALATE_PENDING` (`:95`); the **age leg** (`ESCALATE_OLDEST_DAYS = 7`,
`:96`) and the **debounce** (`ESCALATE_DEBOUNCE_SECS = 24h`, `:97`) stay
**fixed constants**, unexposed. Note the code comment at `worker.py:93`
("changing them is an edit to the pin, not a config file") — promoting
even one leg to config softens that pin. This is a real (if small) scope
decision; it is carried on the `notify.pending_escalation` row of the §3
tier table (whose ratification is §7 item 1's ruling), not a separate
ruling. The other two legs deliberately stay pinned.

**Env-var relationship (pin, do not skip).** Every one of these knobs
is *today* an env var (`SELF_LEARN_MINER_MODEL`,
`SELF_LEARN_PANE_MODEL`, `SELF_LEARN_PANE_BUDGET_USD`, …). Config.yaml
does **not** replace them; it becomes a **committed default layer under
them**. Precedence, pinned: **explicit env var > config.yaml > code
default.** Rationale: the systemd units pin env (`SELF_LEARN_HOME`
etc.) and a machine-local override must still win over a synced policy
file; but where no env var is set, the committed config governs (that
is the whole point of "policy in git, not ambient shell state" — S-10).
Each resolver (`miner_model()`, `worker_model()`, `_model()`,
`load_env()`) gains: `env var → config.yaml value → hard-coded
default`, threaded through a single new `config.get(home, path,
default, type)` helper beside `one_motion_enabled` so the fail-closed
idiom lives in one module.

**"The environment" is plural (F1 — the display cannot honestly claim
otherwise).** Precedence resolves **per process**, and the three
model-running contexts have **different, mutually-invisible
environments**: the **UI server** process (its unit pins only
`SELF_LEARN_HOME`), the **miner** systemd unit (its own
`Environment=` block, §5), and **interactive shells** that
opportunistically spawn `maybe_kick`/`worker` (whatever the user
exported). `config get` runs **inside the UI server process** and can
read **only the UI server's** environment. It therefore *cannot detect*
an env var set in the miner unit or a shell — a `SELF_LEARN_MINER_MODEL`
pinned in the miner's unit will silently win over config for the miner's
own runs, and the settings page has no way to see it. Consequence,
pinned: any provenance the page shows is scoped to **"env vars visible
to the UI server process"**, never a global claim, and the page must
never assert "config governs" for a role whose *other* process may be
env-shadowed. (This is why the DoD, §6, verifies the effect by watching
an actual run, not by trusting the page's provenance label.)

### 1.3 Models-per-role: the four roles and invalid-model handling

Exactly four model-choice sites exist (census verified against
`forward/worker-ecology.md` §1 and code):

1. **miner reader** — `models.miner`.
2. **worker analyst** (detached, coalesced `worker run`) —
   `models.worker`.
3. **pane engine** (interactive SDK session) — `models.pane`. It also
   carries a *fallback* model (`sdk.py:82`
   `DEFAULT_FALLBACK_MODEL="claude-haiku-4-5"`, `sdk.py:357`) — **not
   exposed** in v1 (it is an SDK-degradation detail, not a role choice;
   noted as a non-goal, §6).
4. **one-shot analyst** (`teach --route` inline mode) —
   `models.analyst`. Culturally a mode of the analyst
   (`worker-ecology.md` §1) but a *separate resolver* (`analyst._model`
   vs `worker.worker_model`), so it gets its own key; a future ruling
   could collapse the two under one `models.analyst` if the user wants
   them locked together — flagged, not decided.

**Package-boundary pin (F2 — the pane knob crosses a package line).**
Three roles (miner/worker/analyst) resolve in the **CLI package**
(`miner.py`, `worker.py`, `analyst.py`); the **pane** role resolves in
the **UI package** (`env.py` `DEFAULT_PANE_MODEL` + the
`SELF_LEARN_PANE_MODEL` read → `sdk.py`). The `config` verb lives in the
CLI package, and the dependency direction is strictly **UI → CLI** (the
CLI must never import the UI). Therefore, pinned:
- `config set models.pane <name>` (CLI) just **writes the YAML key** —
  shape-validated like every role (§below), needing zero pane-package
  knowledge; writing a key does not require the default or the resolver.
- `config get --json` (CLI) reports full `{value, source, default}`
  provenance for the **three CLI roles only**, plus the *raw stored*
  `models.pane` string (or null) — it does **not** compute pane
  provenance, because it cannot see `env.DEFAULT_PANE_MODEL` or the
  pane env var's shadowing without importing the UI.
- The **UI settings route** (new, in `routes.py`) calls `config get
  --json`, then computes the pane entry's `{value, source, default}`
  from its **own** `env.DEFAULT_PANE_MODEL` and `os.environ`, and merges
  it in before rendering. This keeps the pane default's single source of
  truth in `env.py` and adds no CLI→UI coupling and no duplicated
  constant. (Rejected alternative: relocating the pane var+default into
  a CLI constants module — it would drag a UI-owned concept into the CLI
  purely to serve display.) **Edit sites**: `env.py` (unchanged
  authority), `cli.py`/`config.py` (`config get` for the three CLI
  roles + raw pane passthrough), `routes.py` (the merge).

**Provenance authority is asymmetric — the pane row is the exception
(MINOR 2).** The pane both **resolves and runs inside the UI server
process** (`env.load_env()` → the in-process `engine_factory` at
`pane.py:985` → `SdkPaneEngine`); no other process ever runs the pane.
So a `SELF_LEARN_PANE_MODEL` the server sees in its own environment
**authoritatively** shadows the pane — the display can state it as fact.
The three CLI roles are the opposite: they run in **other** processes
(miner unit, worker/analyst spawns), so what the UI server's own
environment does or doesn't hold says nothing authoritative about their
runs. §2.3 splits the row treatment on exactly this line.

**Invalid / unavailable model name — the loud-default rule.** Today
these resolvers pass the string straight to `claude --model` with no
validation; an unknown name fails the *whole run* at the model layer.
FW-30 must **fail to DEFAULT, loudly — never to broken**:

- The `config set models.<role> <name>` verb (§2.2) is where validation
  lives. v1 validation is **syntactic + allowlist-shape**, not a live
  API probe: reject the empty string and obvious garbage; accept any
  `claude-*` / `us.anthropic.*`-shaped id (we cannot enumerate live
  model availability at write time without a network call, and a
  write-time probe would couple config edits to API reachability —
  rejected). The verb writes only after the shape check passes.
- At **read/resolve time**, an empty or non-string value → code default
  + stderr warn (the fail-closed rule above). This guarantees a
  corrupted config can never *silence* a role into a broken invocation:
  the worst case is "ran on the default model, warned on stderr", never
  "crashed the miner because the config held junk".
- A syntactically-valid-but-unavailable name (e.g. a model retired
  upstream) **cannot** be caught at config layer — it surfaces as the
  `claude -p` run failing, which the miner journal
  (`dropped`/run-failure) and the worker/pane error paths already
  render. Pin this honestly: config layer guarantees *shape*, the run
  layer surfaces *availability*. Do not claim the config validates
  availability.

---

## 2. The editor page (Y-26)

### 2.1 Rendering and page composition

A **form over `config.yaml`**, one row per exposed key, grouped by the
schema's top-level sections (Models / Miner / Pane / Notifications).
Per the round-4 principles and FW-19's page-composition convention
(`ui-ux.md` §4), the page's **full region list, in display order**:

1. **Page header** — title "Settings", one plain-words line (Y-9): "how
   this machine runs its background work. Every change is saved to your
   ledger's history." Always visible.
2. **Health strip** (optional, cohabiting with FW-14 `doctor` per
   §5-charter "settings + health = one page") — collapsed by default;
   out of Y-26 scope to *build*, but the region's slot is named here so
   FW-14 lands beside, not on top of, the form.
3. **The config form** — the always-visible spine. Each key row shows:
   label (plain words, Y-9), the **current committed value**, the
   **code default** shown inline when current ≠ default ("default:
   claude-sonnet-5"), an input, and a per-key one-line description.
   Grouped by section with quiet dividers — *composed, not stacked*
   (round-4): the sections are a rhythm, not five equal cards.
4. **Operator notes** (tier B, §4) — its own always-visible but
   visually-secondary region below the numeric form: an append-only log
   of standing routing notes + a single add-a-note input. Named as a
   distinct region (not a form field) because its authority and its
   write path differ.
5. **Save bar** — pinned; shows unsaved-change count, Save (commits),
   Discard (reload from committed state). Disabled until a field
   diverges from committed.

Progressive-disclosure posture (the FW-19 statement the spec must
carry): the numeric form is **always-visible** (it is the page's
reason to exist); the health strip is **default-collapsed** (reference,
not decision); operator notes are **always-visible but secondary**
(low-frequency, high-consequence — must not be buried, must not
dominate). If a future key set grows the form past one screen, it
belongs behind section disclosures, not more top-level rows.

### 2.2 The save path — the CLI verb that owns the write+commit

New CLI verb group (thin-caller doctrine, S-2). Parser sits in
`cli.py` beside `host`/`mine`/`proposal`:

```
self-learn config get [--json]                  # read: full resolved config + provenance
self-learn config set <key.path> <value>        # write ONE key, scan, commit
self-learn config note-add <text>               # append ONE operator note, scan, commit
```

`config set` runs the **pinned write sequence** (the resolution-verb
shape, `verbs.py:15` sequence, adapted — no host phase, config.yaml is
ledger-only):

1. **Validate** the key path against the known schema (unknown key →
   refuse, list valid keys) and the value against its type/shape rule
   (§1.2). Refuse loudly on failure; nothing written.
2. **Secret-scan** the *entire resulting file text* with
   `scan.scan()` — the same scanner every record write uses
   (`scan.py:100`); a hit refuses with `scan.format_refusal()`
   (`scan.py:135`) and writes nothing. (Config values are model
   names/numbers — a hit is nearly always a paste accident, exactly
   what the scan exists to catch. §6 security.)
3. **Write** config.yaml (round-trip-preserving via `ruamel` so the
   operator's own comments survive an edit — use `YAML()` round-trip
   for the *write*, `YAML(typ="safe")` for the *read*; the read path is
   the security boundary and stays strict).
4. **Commit** to the ledger repo via `gitops.commit(home, paths=[...],
   message=...)` (`gitops.py:489`), pinned subject `self-learn: config
   <key.path> = <value>`. Config edits **ride autosync's home** but
   self-commit their own pathspec (the S-2 / mine-landing pattern: the
   clean-tree autosync branch never owns a semantic write).
5. **Push** follows the existing pinned-retry posture; a failed push is
   loud but the commit is kept (`verbs.py` step (f) shape).

The web tier adds routes calling these verbs verbatim through
`routes.build_argv` + `runner` — the same seam `mine run`'s force
button uses (`runner.py:151` handles `push`/`mine run` today; `config
set` joins that list). No new subprocess machinery.

### 2.3 Current-vs-default display

`config get --json` returns, per key: `{value, source:
env|config|default, default}` — where `source` is computed against the
**UI server process's** environment only (F1). The page renders
`value`, and when `source != default` shows the `default` inline.

When `source == env` (an env var is shadowing config **in this server's
own environment**), the row is **read-only**, but the note splits by
role authority (MINOR 2):

- **The pane row is authoritative.** The pane resolves and runs in the
  UI server process (§1.3), so a `SELF_LEARN_PANE_MODEL` the server sees
  *is* the model the pane will use. Give it the **strong, exact** note:
  *"set by this server's environment — the pane runs here, so this is
  the value in effect. Change it there, or unset it to use the saved
  value."* No hedge; it is a fact.
- **The three CLI-role rows (miner/worker/analyst) keep the honest
  hedge (F1).** Their runs happen in other processes, so an env var in
  the UI server's own environment is at best a hint: *"overridden in
  this server's environment; the miner/worker runs in its own process
  and may differ. Change it in that environment, or unset it here."* And
  where those rows read `source == config`/`default`, the page still
  does **not** promise the miner unit isn't env-shadowing that role
  elsewhere — it promises only what the server can see.

The affordance is kept for all rows (not dropped): a live env override
in the server's own environment is real and worth surfacing; only the
*scope of the claim* is calibrated per role. This keeps the precedence
rule (§1.2) visible without the S-10-class overclaim the charter warns
against.

---

## 3. The exposure-tier decision table — **RULING REQUIRED**

This is the user decision `forward/ui-ux.md` §5 and 14 §4 say FW-30
must route first. The table below is the **author's recommendation**
per the charter; **the user edits it before build.** Rows are the
concrete knobs, not categories.

| Knob | Recommended tier | Rationale (charter) |
|---|---|---|
| `models.{miner,worker,pane,analyst}` | **A — expose freely** | S-18 economics are the user's; loud-default on bad input (§1.3) makes it safe |
| `miner.cadence_hours` | **A** | timer stays dumb; miner reads window from config (charter shape) |
| `miner.pending_gate`, `miner.cap_per_session`, `miner.cap_max` | **A** | throughput knobs; fail-closed to today's caps |
| `pane.budget_usd`, `pane.max_turns` | **A** | cost ceilings; already env-tunable, no new exposure of behavior |
| `notify.pending_escalation` | **A** | notification threshold; charter names it tier A. **Note (from §1.2 F6):** exposing this promotes ONE leg of the escalation rule to config, softening the `worker.py:93` "edit to the pin, not a config file" comment; the age leg (`ESCALATE_OLDEST_DAYS=7`) and debounce (`24h`) stay pinned. Confirming this softening is part of ratifying this row. |
| `miner.rubric_emphasis` (standing routing notes) | **B — expose with care** | changes what agents *propose*, never what executes (P1 holds); §4's safe shape |
| operator notes / doctrine additions | **B** | "make choices the way I would" — the most-aligned feature; human-gated downstream |
| pane charter / permission enforcement | **C — never expose** | a boundary, not a preference (`ui-ux.md` §5) |
| secret scan, consent invariants (Y-17-class) | **C** | boundaries; exposing them defeats them |
| record schema, `one_motion_route` gate | **C** | `one_motion_route` stays hand-edited + commit-gated (S-10) — a UI toggle would trivialize the "operator explicitly accepts unseen-bytes" ceremony; keep it out of the form |
| pane fallback model (`sdk.py:82`) | **C (v1)** | SDK-degradation detail, not a role choice; revisit if users ask |

**Ruling asked of the user:** confirm/redraw the tier column,
especially the three judgment calls — (a) `one_motion_route` staying
tier C (hand-edit only) vs promoting to a guarded tier-B toggle; (b)
whether `models.analyst` and `models.worker` are one knob or two; (c)
whether operator notes are UI-writable in v1 at all, or read-only-in-UI
until the pane's FW-36 drafter is the sole writer.

---

## 4. Doctrine / rubric editing (tier B) — the safe v1 shape

**Decision: NOT a free-text editor over the doctrine file.** The
routing doctrine
(`skills/self-learn/references/routing-doctrine.md`) stays
**package-and-human-owned**: workers, analyst, and skill all read it
package-relative (`analyst.doctrine_path()`,
`worker.package_skill_refs()`), and it is the exclusive target of
FW-36's pane doctrine drafts (`worker-ecology.md` §6). Two write paths
into one file is the conflict the task warns against — so the UI never
writes that file.

**v1 shape: a config-referenced, append-only supplement.** A new
home-relative `<ledger-home>/operator-notes.md` (committed, secret-
scanned) plus the `miner.rubric_emphasis` free-text config value:

- **Append-only through the UI.** `config note-add <text>` appends one
  timestamped, scanned, committed block; there is no destructive
  overwrite path in the UI. The user can only *add* standing notes,
  never silently rewrite history — the audit trail is the file's git
  log.
- **Consumed as an advisory block — the fence is convention, not a
  safety boundary (F8).** Prompt assemblers (worker/analyst/miner)
  append operator-notes and `rubric_emphasis` as a **fenced "operator
  standing notes"** section *after* the authored doctrine/rubric, never
  merged into it. Be precise about what that buys: the fence is a
  **legibility convention** — it does not *constrain* the model, and a
  note could in principle push a proposal in any direction the words
  allow. The **actual** guarantee that operator notes can't change what
  *executes* is **P1 downstream**: every proposal, however influenced,
  still lands in the pending queue behind the human review gate
  (culture rule 1, `worker-ecology.md` §4 — *workers inform proposals;
  only the human amends the constitution*). So: notes shape what is
  *proposed*; P1 — not the fence — is why they cannot rewrite canon
  unreviewed. Do not sell the fence as containment.
- **Ownership pin (resolves the FW-36 interaction):**
  - `routing-doctrine.md` — package/human-owned; FW-36 pane drafts land
    as **proposals beside it** (`.../proposals/`), never edits. UI:
    read-only-visible at most.
    - `operator-notes.md` — home-owned; UI-appendable via `config
    note-add`; secret-scanned; committed. FW-36 never targets it.
  - The two files never share a writer → no two-path conflict exists by
    construction.

Miner rubric: the versioned rubric file (`_rubric()`, `miner.py`) is
**never edited by the UI** (its version stamp, A3, must stay
meaningful). `miner.rubric_emphasis` is the *only* rubric-adjacent knob
— appended as an operator note, same as above.

---

## 5. Miner cadence

**The charter shape**: the systemd timer stays dumb; the miner reads
its window from config; **the UI never writes systemd units** (a
non-goal, §6). Config key: `miner.cadence_hours` (default `24`).

**How it interacts with today's mechanism** (all in `miner.py`,
verified): three hard-coded thresholds govern re-run pressure —
`KICK_AFTER_SECS = 24h` (`:79`, verb autokick / coalesce window),
`STALE_AFTER_SECS = 36h` (`:83`, SessionStart staleness alarm),
`ATTEMPT_COOLDOWN_SECS = 2h` (`:80`, failure backoff). The timer fires
`OnCalendar=*-*-* 03:30` nightly (`self-learn-miner.timer`).

**The change, pinned:**

- **A cadence gate on the scheduled pass itself (F3 — without this, the
  knob is a lie in the "slower" direction).** `run()` (`miner.py:1233`)
  has **no age gate today**: it touches `miner.last-attempt` and mines
  unconditionally; `trigger` is only journaled, never consulted. The
  nightly timer fires `run(trigger="timer")` every night regardless of
  `cadence_hours`, so raising the cadence to (say) 72h would *not* stop
  the nightly pass. Fix: at the top of `run()`, when
  `trigger == "timer"` **and** the last completed run is younger than
  `cadence_hours`, **no-op** — return a `MineResult(status="skipped")`
  and append one journal line (`"fresh, skipped (cadence Nh)"`) so
  `mine status` explains the quiet night. Manual (`trigger="manual"`)
  and watchdog (`trigger="kick"`) runs are **never** cadence-gated —
  force controls timing (R2, 12 §8). This makes `cadence_hours` mean
  what its name says in **both** directions: fewer scheduled passes when
  raised, and (with the autokick derivation below) sooner opportunistic
  ones when lowered.
- **The skip-marker contract — the pin that keeps a skip from stopping
  the miner forever (BLOCKER).** *Where* the skip sits and *what it must
  not touch* are load-bearing:
  - **Placement**: the skip check goes **after** the `disabled` guard
    (`miner.py:1250`) and the `busy`/`flock` guard (`:1256`), and
    **before** the `miner.last-attempt` touch at `miner.py:1257`. It
    runs only once the lock is genuinely held and the miner is neither
    disabled nor already running.
  - **Zero-work invariant**: a skip **touches neither `miner.last-run`
    nor `miner.last-attempt`**. A skip did no work, so both the
    staleness clock (`stale()`) and the autokick clock (`autokick()`)
    must keep counting from the **last real pass** — not from the skip.
  - **The failure this kills**: if a skip stamped `last-run`, then with
    `cadence_hours: 48` under a nightly timer, night-1 mines and stamps
    the clock; night-2's timer fires, sees age 24h < 48h, skips — but if
    that skip **re-stamped** `last-run`, night-3 again sees age 24h <
    48h and skips, forever. The miner would **silently never mine again**
    at any cadence above the timer interval. Not re-stamping is what
    makes the *next* eligible night actually eligible (night-2's skip
    leaves the clock at night-1, so night-3 sees age 48h ≥ 48h and
    runs). The `last-attempt` touch is likewise skipped so the 2h
    autokick cool-down is not falsely reset by a no-op.
  - **Test obligation (in addition to §6)**: assert a skipped
    `run(trigger="timer")` leaves **both** `miner.last-run` and
    `miner.last-attempt` mtimes **byte-identical** to their pre-call
    values (capture mtime, force a skip, re-read — unchanged), and that
    the following eligible night runs.
- **The new `"skipped"` status ripples to two consumers (MINOR 1).**
  Adding a `MineResult(status="skipped")` obliges two follow-on edits or
  the status renders as an unknown:
  - **`MineResult` enum comment** (`miner.py:742`) — extend the status
    docstring (`ok | idle | held-gate | failed | disabled | busy |
    landed-uncommitted`) to include `skipped`, so the contract stays
    self-documenting.
  - **`_MINER_STATUS_LABELS`** (`ui/models.py:181`) — add a Y-9
    plain-words label, e.g. `"skipped": "skipped — ran recently"`, so
    the UI miner block renders the quiet night in human words rather
    than a bare enum token.
- `KICK_AFTER_SECS` and `STALE_AFTER_SECS` become **derived from
  `cadence_hours`**, not literals: `kick = cadence_hours·3600`; `stale
  = 1.5 · cadence_hours·3600` (preserving today's 24h→36h ratio; 24h
  default reproduces today's numbers exactly; **see the F10 note below
  on low-cadence alarm noise**). `ATTEMPT_COOLDOWN_SECS` stays fixed (it
  is failure backoff, orthogonal to cadence). Replace the two module
  constants with functions of `config.get(home, "miner.cadence_hours",
  24)`, read by `autokick()` (`miner.py:1199`) and the staleness
  predicate `stale()` (`miner.py:192`) — this is **"recompute staleness
  against the CONFIGURED cadence"** in concrete terms.
- **The display strings that hard-code the old hours must move too, or
  they lie (F4).** The `>24h`/`>36h` literals are baked into
  user-facing text at three sites; each must compute the hours from
  `cadence_hours`:
  - `cli.py:541` — `"  ⚠ STALE (>36h)"` (the `mine status` line);
  - `cli.py:1439` — `"miner: catch-up run spawned (>24h)"` (the
    autokick stderr line);
  - `ui/models.py:491` — `"miner overdue (>36h)"` (the UI miner block).
- **Name-collision guard (F4 — a builder must not touch the wrong
  constant).** Only the **miner's** `STALE_AFTER_SECS`
  (`miner.py:83`, 36h) is cadence-derived here. There is a **different,
  identically-named** `STALE_AFTER_SECS` in `worker.py:1147` (`3 * 24 *
  60 * 60`, a 3-day *worker*-staleness threshold consumed at
  `ui/models.py:393` via `sl_worker.STALE_AFTER_SECS`) — it is **out of
  scope** and must **not** be changed by this work. Pin the two as
  distinct so the derivation edit does not blast-radius into the worker
  staleness path.
- **Coalescing**: the existing autokick already no-ops when the last
  run is within `KICK_AFTER_SECS` (`:1213`). With the constant now
  cadence-derived, a shorter configured cadence means the opportunistic
  re-run fires sooner; a longer cadence means fewer runs. The pending-
  gate coalescing (`pending_gate()`) is unchanged.
- **Timer frequency — the honest boundary.** The *nightly* timer is a
  ceiling on how often the scheduled pass runs; config can make the
  system re-run **less** aggressively (raise cadence) and governs the
  autokick/alarm math, but to run **more** often than nightly the timer
  interval itself must change — and the UI must never write systemd
  units (charter). Resolution: the fully-frequent timer the charter
  envisions ("dumb and frequent") is a **one-time units edit shipped
  with packaging** (change `OnCalendar` to e.g. hourly; the miner's
  cadence gate then does the throttling). Until that units change,
  `cadence_hours` governs autokick + staleness only. Pin this limit
  explicitly so no one claims the v1 UI can dial sub-nightly frequency.
- **Low-cadence alarm-noise dimension (F10 — flagged, not a routed
  ruling).** With `stale = 1.5 × cadence`, a very short configured
  cadence (e.g. 2h) makes the staleness alarm trip at 3h — a machine
  merely asleep an afternoon would read as "overdue". The 1.5× ratio is
  a reasonable default carried from today's 24h/36h, but it couples
  alarm sensitivity to cadence in a way that gets jumpy at the low end;
  if that proves annoying in practice, decoupling the alarm from cadence
  (a floor, or its own key) is the escape hatch. Noted so the coupling
  is a known trade-off, not a surprise.

---

## 6. Cross-cutting: security, degradation, migration, tests, non-goals

**Security.** No secrets belong in config.yaml by design (model names,
numbers, cadence). The `config set` and `config note-add` verbs
**secret-scan the whole resulting file** (`scan.scan`) before commit —
the same gate as every record write — refusing on a hit. The page
**never renders or accepts credentials**: no password/token field
exists, and the operator-notes input is scanned server-side (a pasted
API key is refused with `format_refusal`, not stored). The read loader
stays `YAML(typ="safe")` — no arbitrary tag construction.

**Degradation** (09 §5 degrade-gracefully). Config missing → all code
defaults, page renders every field at its default with no error.
Config corrupt/unparseable → all defaults + **a visible page notice**,
never a 500. **Where the notice's text comes from (F7 — the resolver's
warn is not user-visible).** The fail-closed `_warn` inside each
resolver goes to the **stderr of whatever detached process resolved the
config** — the miner unit's journal, the worker's log — which the user
sitting on the settings page never sees. So the page's notice is **not**
that warn surfaced; it is an **independent re-parse performed by `config
get` inside the UI server process**, which returns a structured
parse-status (ok / whole-file-unparseable / per-key-invalid with
reasons). The page renders *that* structured status ("your settings file
couldn't be read and defaults are in use — <reason from config get>"),
and a single malformed key → that key defaults + a per-row notice from
the same structured status, the rest of the form working. The CLI never
crashes on a bad config — worst case is default + warn-to-its-own-stderr,
by construction (§1.1); the *user-facing* explanation is always the UI's
own re-parse, never scraped stderr.

**Migration / packaging freeze.** `version: 1` ships from day one (§1.1)
so the packaging phase, which will freeze this schema for outside
users, has a version handle. Absent version = 1 (back-compat with
today's `one_motion_route`-only files). Unknown-future version = warn +
read known subset, never brick. The schema must stabilize **before**
packaging (charter sequencing pressure).

**Test obligations / DoD.**
- Config parse: fixture table — each key at default, valid, malformed,
  wrong-type, and missing — asserting fail-closed default + exactly one
  stderr warn per malformed key, and per-key independence (one bad key
  doesn't poison others). Mirror `test_*config*` style.
- Precedence: env > config > default proven for all four model
  resolvers + pane budget/turns.
- `config set`/`note-add`: unknown-key refusal, type-shape refusal,
  **secret-scan refusal** (planted token → refused, nothing written,
  nothing committed), successful write → one commit with the pinned
  subject, comment-preservation on round-trip write.
- Cadence: `cadence_hours` derives kick/stale; 24 reproduces 24h/36h;
  a short cadence trips autokick sooner (time-mocked, `AUTOKICK=0`
  discipline preserved).
- Page: renders current-vs-default; env-shadowed row is read-only;
  corrupt-config notice renders (no 500) — a `test_degradation_walk`
  addition.
- **DoD (round-4 instrument, charter):** a user walkthrough — change a
  model, save, confirm the commit in `git log`, confirm the next
  miner/worker/pane run uses it; add an operator note, confirm it
  appears fenced in a subsequent proposal prompt; corrupt the file by
  hand, confirm the page degrades with a notice and the CLI still runs.
  Logged in `fixtures/ui-trials.md`.

**Non-goals (v1).** No live toggles (every change commits — §0). No
systemd writes of any kind (timer frequency is a hand/packaging edit —
§5). No per-user multi-tenancy (one operator, one committed config per
ledger home). No pane-fallback-model exposure (§1.3). No free-text edit
of `routing-doctrine.md` or the versioned rubric (§4). No write-time
model-availability probe (§1.3). No exposure of tier-C boundaries (§3).

---

## 7. Open items routed to the user (blocking build)

1. **§3 tier table** — the RULING REQUIRED; especially
   `one_motion_route` staying hand-edit-only, worker/analyst one-vs-two
   knobs, and whether operator notes are UI-writable in v1.
2. **§5 timer frequency** — confirm the "frequent timer ships with
   packaging" resolution, or rule that v1 cadence governs autokick/alarm
   only and the scheduled pass stays nightly regardless.
3. **§1.2 precedence** — confirm env > config > default (vs config
   winning over env, which would let a synced policy override a
   machine's local pin — the author recommends env-wins for exactly the
   machine-local-override reason, but it is the user's economics call).
