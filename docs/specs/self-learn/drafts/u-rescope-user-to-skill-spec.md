# U-rescope — re-scoping a pending record across scopes (`user` ↔ `skill:<name>`)

**Status:** DRAFT, round 1 · **Author:** u-rescope spec author · **For:** blind Opus spec gate → Sonnet builder
**Base commit:** `b8ac3cb` (master) · **Drafted:** 2026-08-23
**Task note:** `mNv4FZKHeEKKnuc8hQenz` · **Work order:** `misc/orchestration-plan-2026-08-23.md` item #7

---

## 0. Reader's warning — one work-order requirement is contradicted by verified evidence

The work order for this unit carries a hard requirement:

> Must move the proposal sibling WITH the record — `rehome` swept it on
> 2026-08-18, do not repeat that defect; add a test that the proposal survives.
> — `misc/orchestration-plan-2026-08-23.md:75-78`

**This spec does not implement that requirement.** It specifies the opposite —
the proposal sibling is **swept**, exactly as `rehome` does — and it does so on
evidence gathered and tested for this unit. §5 lays out the evidence in full,
including two behaviours measured on the live ledger. §5.5 states what the
work order got *right* (the sweep is silently lossy) and specifies the fix for
that (disclosure), which is the part of the requirement this spec does honour.

The gate should adjudicate §5 first. §5.3 leg 1 — the `user → skill` direction,
which is this unit's motivating case — carries the decision on its own: a carried
proposal there stays schema-valid, derivation-identical and `record_sha`-fresh,
so every freshness mechanism the system has reports "fresh" for an analysis
performed at the wrong scope. If the gate rules that the proposal must move
regardless, §5.6 records what else must change.

The provenance of the requirement, traced: `misc/decision-profile-2026-08-18.md:241`
recorded an *observation* during a review session ("`rehome` sweeps the proposal…
on the fast path this silently discards a worker analysis"), filed under
"§7 Incidental findings worth their own records". The orchestration plan then
promoted that observation to "defect". But the sweep is a **decision of record
predating it by a month** — `09-surface-spec.md:2065-2072` (Y-18, 2026-07-18),
with a stated rationale — and is pinned by a test whose name is the decision:
`tests/test_rehome.py::TestRehomeMove::test_sweeps_proposal_siblings_never_moves_them` (`:144`).
Neither the observation nor the plan cites Y-18. The date in the work order
(`2026-08-18`) is the date of the *observation*, not of any regression; `rehome`
has swept since it was born (`e0b374f`, 2026-07-18).

---

## 1. Objective

Add a verb that moves a **PENDING** (or `deferred`) record between the
`user` bucket and a `skills/<name>` bucket, rewriting the record's `scope`
field so bucket and scope stay in agreement, in one ledger commit, under the
same mutation discipline as every other record-writing verb.

`rehome` cannot do this. It is pinned `project → project` and refuses
everything else in its own words (`verbs.rehome`'s non-project refusal, `verbs.py:3622-3627`):

```
record {id} lives in a non-project bucket ({bucket}) — rehome is
project→project only (M1); user-scope targets and skill/user-scope
sources are dated future work, not silent extensions
```

That refusal string is this unit's charter: the codebase asked for a separate,
dated unit rather than a silent widening of `rehome`. This is it.

## 2. Current behaviour and the card-6 gap (verified)

### 2.1 What exists

| Capability | Where | Covers |
|---|---|---|
| `rehome <id> --to <path\|slug>` | `verbs.py:3576` | `project → project` only |
| `Record.set_scope(scope)` | `records.py:419` | already exists, already validated, already tested (`tests/test_records.py:291`) |
| `bucket_dir_for_scope(home, scope)` | `ledger_ops.py:292` | resolves all three scopes; gates `skill:<name>` against the registry |
| `hosts.skill_dir_for(hosts, name)` | `hosts.py:546` | the skill-name validity gate (missing / ambiguous / no root) |

Nothing wires these together. There is no verb, no CLI subcommand, and the
review command doc (`plugins/self-learn/commands/review.md`) does not mention
re-homing or re-scoping at all — verified by grep: zero hits for
`rehome|rescope|re-home|re-scope`.

### 2.2 What the schema permits

`02-schema.md:316-317`:

> **Lifecycle metadata may mutate**: `status`, `routing`, `sightings`,
> `scope`/`kind` (triage may re-classify — the filing is never frozen).

`records.py:19-20` restates it in the implementation's own words, and
`set_scope` is not gated on status. `_validate_scope` (`records._validate_scope`, `records.py:806-811`)
accepts exactly `project`, `user`, and `skill:<name>` with a non-empty name.

**Note the exact form:** the scope value is `skill:bitwarden-cli`, *not*
`skill`. A builder who writes `set_scope("skill")` gets
`ValidationError: scope must be skill:<name>, project, or user` — confirmed by
running it.

### 2.3 The card-6 gap — what actually happened

Review of 2026-08-22 (local; `2026-08-23T04:0*Z` in the ledger), card 6,
record `lrn-a43bf00c` ("an unverified awk/sed/grep filter on secret-listing
output can silently print values in full"). The ledger is the source:

| Ledger commit | Time (local) | What |
|---|---|---|
| `0559a5f` | 2026-08-22 21:01:07 | `self-learn: route lrn-a43bf00c → hook` — resolved at **user** scope |
| `1890983` | 2026-08-22 21:02:04 | `self-learn: capture lrn-5f13e684 (skill:bitwarden-cli)` — a **separate** record, `source: teach` |

57 seconds apart. Two artifacts where the user first wanted one moved.

**The honest reading — and it qualifies the work order's framing.** The
resolution note committed with `0559a5f` says:

> Human routing call. Guard stays at user scope: a PreToolUse Bash guard fires
> on every Bash call regardless of loaded skill, so scoping it to
> skill:bitwarden-cli would not narrow it. The scope-mismatch flag was resolved
> by splitting the artifacts instead — the prose form is being captured
> separately into the bitwarden-cli skill, where someone writing a bws command
> will read it.

So the eventual disposition was a deliberate **split**, for a reason
(a PreToolUse hook's firing range is scope-independent) that would have held
even if `rescope` had existed. **This spec must not claim `rescope` would have
changed card 6's outcome.** It would not have.

What card 6 does establish is narrower and still sufficient:

1. The user's stated first move was to re-scope, and the option **did not exist**
   at the moment of decision. The choice was made from a truncated option set.
2. The workaround cost a second record. `lrn-5f13e684` and `lrn-a43bf00c` now
   carry the *same* evidence quote ("I exposed your secrets and you should
   rotate them") in two buckets — provenance is duplicated, and the two will
   age independently.
3. The general case is real and unrelated to hooks. `lrn-9409ecf4`
   (`skill:bitwarden-cli`, the `bws --color no` fact) is a lesson whose firing
   range genuinely *is* one skill; it happened to be captured at skill scope.
   A capture-cwd or capture-time misjudgement in the other direction has no
   repair today except hand-editing the ledger.

## 3. DECIDE — verb surface: a new `rescope` verb

**Decision: a new verb, `self-learn rescope <id> --to <scope>`.** Not an
extension of `rehome`.

Rationale, in order of weight:

1. **The target argument is a different kind of thing.** `rehome --to` takes a
   project path *or* a bucket slug, resolved against `hosts.yaml`'s `projects`
   list (`_resolve_rehome_target`, `verbs.py:3555-3573`). `rescope --to` takes
   a *scope literal* — `user` or `skill:<name>` — resolved against the
   `skills_root` registry via `skill_dir_for`. Different registry, different
   resolver, different refusal string ("`host add <path>`" vs
   "`host add <path> --skills-root`"). Overloading one `--to` so its type
   depends on its content is how a slug that happens to equal a skill name
   becomes a silent mis-file.
2. **`rehome` is agent-proposable; `rescope` should not be, yet.** `rehome` sits
   in the pane's closed proposable verb list with `to` intake-validated against
   `hosts.yaml` (`09-surface-spec.md:2088-2095`, `10-surface-build-plan.md:72`).
   Widening `rehome`'s reach would widen, in the same edit, what a model may
   propose — to any registered skill. A new verb starts outside that list and
   joins it only by a later dated decision. **Out of scope for this unit** (§9).
3. **The commit subject is pinned to the project shape.** `rehome`'s subject is
   `self-learn: rehome lrn-… → projects/<slug>`, and `cli.py:1272` parses the
   destination back out of it via `_routed_destination` (split on `→`).
   A second target vocabulary inside one pinned subject makes that parse
   ambiguous.
4. **The codebase asked for this.** The refusal quoted in §1 names
   "dated future work, not silent extensions". A separate verb is the
   dated-future-work shape; an added branch in `rehome` is the silent extension.

`rehome` is **not** deprecated, renamed, or touched by this unit beyond adding a
cross-reference line to its refusal string (§6.5).

## 4. DECIDE — direction generality: the `user ↔ skill` pair, project excluded

**Decision: M1 supports exactly two directions —**

| From | To | M1 |
|---|---|---|
| `user` | `skill:<name>` | ✅ the motivating direction |
| `skill:<name>` | `user` | ✅ the inverse, free |
| `skill:<a>` | `skill:<b>` | ❌ refuse, dated future work |
| `project` | anything | ❌ refuse — `rehome`'s territory |
| anything | `project` | ❌ refuse — `rehome`'s territory |

**Why include `skill → user`.** It is the exact inverse of the motivating case
and reuses the same resolver, the same refusals, and the same test fixtures.
Shipping only `user → skill` would create a one-way door: a record mis-filed
into a skill would have no repair but a hand edit of the ledger. The
asymmetry would cost more to explain than the leg costs to build.

**Why exclude `skill:<a> → skill:<b>`.** It is safe in principle, but it is the
direction with no live motivating instance, and it is the one where the
proposal-sweep hazard has its sharpest form (§5.3 — a trace owned by skill `a`
re-derived under skill `b`). Refusing it now costs nothing and keeps the M1
refusal matrix a simple predicate. Dated future work; the refusal names it.

**Why exclude `project` on both sides.**
- `project` buckets carry an identity invariant the other two do not: a
  `meta.yaml` recording the project path, which `ensure_project_meta`
  (`ledger_ops.ensure_project_meta`, `ledger_ops.py:325`) *refuses to silently reconcile* on mismatch. Every
  project-side move therefore needs a `project_path`, which `--to <scope>`
  does not carry.
- Verified on the live ledger: `~/.self-learn/skills/bitwarden-cli/` and
  `~/.self-learn/user/` contain only `pending/`, `proposals/` (and `resolved/`
  where one has been created). **No `meta.yaml`.** So the `user ↔ skill` pair
  needs none of the project machinery — that is precisely what makes this a
  small unit.
- `project → project` is `rehome`'s pinned territory. Supporting it here would
  make `rescope` a superset of `rehome` and force a deprecation ruling this
  unit must not make.

### 4.1 The structural difference from `rehome` — the record file CHANGES

State this loudly, because it inverts `rehome`'s central invariant.

`rehome` is byte-untouched: `verbs.rehome`'s docstring (`verbs.py:3589-3590`) — "``resolution_note`` stays
untouched… The record's bytes are untouched: a deferred record moves and stays
deferred", pinned by the byte-identity assertion in
`test_rehome.py::TestRehomeMove::test_moves_record_in_one_commit_with_pinned_subject`
(`:105`). It can be, because a project→project move changes only
the *bucket slug*, and the slug is not in the record — the record just says
`scope: project`.

`rescope` **cannot** be byte-untouched. The scope literal *is* in the record's
frontmatter, and `bucket_dir_for_scope` maps `scope → bucket`. A record reading
`scope: user` sitting in `skills/bitwarden-cli/pending/` is internally
inconsistent: every consumer that re-derives the bucket from the scope would
look in `user/` and not find it.

**Therefore `rescope` rewrites `scope:` in the same motion as the move.**
Consequences the builder must carry:

- The secret scan `_scan_or_refuse` is **not** a formality here. In `rehome` it
  is documented as a practical no-op (`verbs.rehome` step (a), `verbs.py:3605-3607`); in `rescope` the
  file is genuinely rewritten, so the scan is load-bearing (P2-7).
- `Record.write()` re-emits frontmatter through ruamel round-trip mode.
  Round-trip fidelity is a hard requirement (`records.py:3-7`), so comments and
  key order survive — but the file is not byte-identical, and no test may
  assert that it is.
- Only `scope` changes. `status`, `deferred_until`, `deferred_count`,
  `sightings`, `evidence`, `routing`, `resolution_note` and the entire body are
  untouched. A deferred record re-scopes and **stays deferred**, with its
  `deferred_until` and `deferred_count` intact.

## 5. DECIDE — proposal freshness: SWEEP, and disclose the sweep

**Decision: the proposal sibling is swept, never moved** — `lrn-<id>.yaml`,
`lrn-<id>.diff`, and any source-bucket `merge-*.yaml` naming the record — via
the existing `remove_proposal_siblings` (`ledger_ops.py:2019`), exactly as
`rehome` does. **And** the verb discloses the sweep (§5.5), which `rehome` does
not.

### 5.1 The prior decision this inherits

`09-surface-spec.md:2065-2072`, Y-18, 2026-07-18 — verbatim:

> **Proposal siblings are swept, never moved** (decision of record): the
> analyst's destination judgment is bucket-relative and `record_sha` staleness
> cannot catch a move (the hash is of record content, which did not change), so
> a carried sibling would render an honest-looking stale card; the worker
> re-proposes in the new home.

### 5.2 Verified: a scope change does not move `record_sha`

The rationale hinges on a claim about the hash. Tested, not assumed.

`record_sha` is `sha_anchor(record.body)` — `analyst.py:307`,
`ledger_ops.py:1981`, and the freshness comparison at `ledger_ops.py:2374`.
`Record.from_text` (`Record.from_text`, `records.py:143-152`) sets `body` to everything *after* the
closing `---`. **`scope` is frontmatter. It is not in the hash.**

Run against a synthetic record, flipping only `scope: user` → `scope: skill:bitwarden-cli`:

```
record_sha before: sha256:0473e9841ff0
record_sha after : sha256:0473e9841ff0
SCOPE FLIP LEAVES record_sha UNCHANGED: True
positive control — a body edit DOES change it: True  (sha256:cc911cd482b9)
```

The positive control is load-bearing: without it, "unchanged" is also what a
broken hash function prints.

So a carried proposal keeps matching. `proposal_fresh` stays `true`,
`is_unanalyzed` stays `false` (`ledger_ops.is_unanalyzed`, `ledger_ops.py:2378-2386`), and the review takes
its **fast path** — `review.md:61-62`, "a record whose proposal is fresh and
schema-valid". The card renders from an analysis performed for a different
scope, and nothing in the pipeline says so.

### 5.3 Verified on live data: what a carried proposal actually does

Better than reasoning — the two directions were measured against real proposals
in `~/.self-learn`.

**Direction `user → skill`: the stale analysis survives completely intact.**
Three real user-scope proposals, re-derived at `skill:bitwarden-cli` through
`gates.expected_outcome`:

```
lrn-19f82fc5  dest=claude-md  user-> ALWAYS  skill-> ALWAYS  SAME: True
lrn-74debc2c  dest=claude-md  user-> ALWAYS  skill-> ALWAYS  SAME: True
lrn-9aab3bb1  dest=claude-md  user-> ALWAYS  skill-> ALWAYS  SAME: True
```

Same derived outcome, so `_validate_derivation` (`ledger_ops.py:1576`) passes.
Destination still `claude-md`. `record_sha` still matching (§5.2). **Every
freshness mechanism the system has reports "fresh"** for a proposal that
recommends compiling into the user's `CLAUDE.md` a record that now lives in a
skill bucket. This is the Y-18 harm, reproduced on this unit's own direction,
with nothing to catch it.

**Direction `skill → user`: the carried proposal degrades gracefully — it does
NOT crash.** `gates.t3_route_taken` (`gates.py:54-64`) is true iff
`t3.answer == "yes" and scope == "skill:" + t3.owner`. When it is true,
`_validate_gates`'s §3.2 scope-conditional rule forces `t4` to null. The real
proposal `~/.self-learn/skills/bitwarden-cli/proposals/lrn-5f13e684.yaml` has
exactly that shape (`t3: {answer: yes, owner: bitwarden-cli}`, `t4: null`).

Taken in isolation, `gates.load_class` on that trace at another scope does raise
`TypeError: 'NoneType' object is not subscriptable` — it reads `t4`
unconditionally once the t3 route is not taken (`gates.py:74-107`). **But that
path is unreachable in production**, and the spec must not claim otherwise:

- `validate_proposal` calls `_validate_gates(data, record_text=…, scope=scope)`
  at `ledger_ops.py:1846` and only then `_validate_derivation(data, scope=scope)`
  at `:1847`, at the same scope.
- `_validate_gates`'s §3.2 rule refuses that exact trace first. Measured:

```
skill:bitwarden-cli  _validate_gates   -> PASSED
skill:bitwarden-cli  validate_proposal -> PASSED
user                 _validate_gates   -> ProposalError: gates.t4 must be non-null
                                          when the t3 route is not taken
                                          (scope 'user' does not match gates.t3.owner)
user                 validate_proposal -> ProposalError: (same)
```

- `proposal_info` catches `ProposalError` (`ledger_ops.py:2372`) → `proposal_fresh:
  False` → `is_unanalyzed: True`. No exception escapes.
- `_validate_derivation` has exactly one caller (`ledger_ops.py:1847`) and
  `gates.load_class` exactly one production caller (`ledger_ops.py:1646`, inside
  it). No caller can reach `load_class` at a scope `_validate_gates` did not
  already accept.

So `load_class`'s stated contract — "total on every trace `_validate_gates`
**accepts**, at every legal scope" (`gates.py:79-81`) — is **not violated**, and
there is no live latent crash in `self-learn status`. The totality is a property
of the CALL ORDER in `validate_proposal` (`ledger_ops.py:1846-1847`), not of
`load_class` itself; any future direct caller that skips `_validate_gates` at the
same scope would get the `TypeError`.

**What this leg contributes to the decision:** a carried `skill → user` proposal
lands on `is_unanalyzed: true` — the *same* outcome as the sweep — while leaving
a dead, permanently-invalid proposal file in the destination bucket. So on this
direction the move buys nothing and costs litter. **Leg 1 is what carries the
sweep decision.**

### 5.4 What the sweep costs, and why the cost is the designed path

Sweeping does discard a worker analysis — the 2026-08-18 note is right about
that, and `0559a5f` shows the scale (a 117-line `user/proposals/lrn-a43bf00c.yaml`
deleted at resolution).

But the recovery is designed, not accidental. Sweep → `has_proposal: false` →
`is_unanalyzed: true` → `review.md:39-40`: "For each queued record **without a
fresh valid proposal** (`has_proposal` false, or `proposal_fresh` false),
perform the inline analysis" — and the background worker re-proposes in the new
home. A re-analysis in the destination bucket is worth more than a preserved
analysis from the source bucket, because the destination is what the analyst's
judgment is relative to.

### 5.5 What the work order got right — the sweep is SILENT. Fix that.

The real defect in the 2026-08-18 observation is the word **"silently"**:
"on the fast path this silently discards a worker analysis". `rehome` sweeps
with no mention anywhere the human sees — not in stdout, not in the commit body.
That is a genuine gap, and this unit closes it for `rescope`:

- **`R-DISCLOSE-1`** — when the sweep removes at least one file, the verb's
  human-facing output includes one line naming the count and the fact of
  re-analysis. The line lists **only the non-zero swept components** — a
  proposal-only sweep prints `swept 1 proposal — lrn-… will be re-analyzed
  in skills/bitwarden-cli`; a merge-cluster-only sweep prints `swept 1
  merge cluster — lrn-… will be re-analyzed in skills/bitwarden-cli`; both
  non-zero prints `swept 1 proposal + 2 merge clusters — …`. A component at
  zero is never named (never "0 proposal", never "0 merge cluster(s)") —
  a merge-cluster-only sweep must not print "swept 0 proposal". When
  nothing was swept, the line is absent entirely (never "swept 0").
- **`R-DISCLOSE-2`** — the commit body records the swept paths, so the
  discarded analysis is recoverable from git by anyone reading the commit,
  which is how it was recovered on 2026-08-18.

Both requirements have a **pinned carrier**, specified in §6.2 step 8 and step
10 and in `rescope_record`'s `(touched, swept)` return (§6.3): `swept` is what
distinguishes a removed proposal from a rename half, `post_notes` (`verbs.py:309`,
printed by `_finish_verb` at `cli.py:1181-1182`) carries R-DISCLOSE-1 to stdout,
and the composed commit body carries R-DISCLOSE-2. Without that plumbing these
would be untestable prose — T11 asserts against exactly those carriers.

This gives the work order's underlying concern a real remedy without
reintroducing the stale-card hazard the requirement's stated fix would create.

### 5.6 If the gate overrules §5

Recorded so the builder is not left guessing. A moving proposal additionally
requires, at minimum:

1. A decision about the dead `skill → user` proposal (§5.3 leg 2): a carried
   trace whose `t4` was nulled at its owning scope is refused by `_validate_gates`
   at every other scope, permanently. Moving it puts a file in the destination
   that can never read fresh — the move must either sweep it after all, or the
   spec must accept known-dead files in `proposals/`.
2. A re-stamp mechanism that invalidates the carried proposal at the
   destination, since `record_sha` cannot (§5.2). There is no such mechanism
   today; `stamp_proposal` re-stamps to *fresh*, which is the wrong direction.
3. Reversal of the Y-18 decision of record (`09-surface-spec.md:2065`) and of
   `test_rehome.py::TestRehomeMove::test_sweeps_proposal_siblings_never_moves_them`
   (`:144`), or an explicit statement that `rescope` and `rehome`
   deliberately differ on this — with the reason why the analyst's judgment is
   bucket-relative for one and not the other.

## 6. Verb surface and mutation procedure

### 6.1 CLI surface

```
self-learn rescope <ID> --to <SCOPE> [--note TEXT] [--no-push]
```

- `<ID>` — positional, `metavar="ID"`, mirroring `rehome` (`cli.py:259`).
- `--to` — **required**, `metavar="SCOPE"`. Accepts `user` or `skill:<name>`.
  Help text names the two accepted forms and that the skill must already exist
  under the registered skills root.
- `--note` — from the shared `_verb` builder; rides the **commit body only**.
  `rescope` is not a resolution: `resolution_note` is never written. (Same pin
  as `rehome` — `verbs.rehome`'s docstring, `verbs.py:3588-3589`.)
- `--no-push` — from the shared `_verb` builder.
- **No `--json`.** `rehome` has none (`cli.py:256-257` omits `json_flag`);
  match it.

Dispatch in `_cmd_verb` beside the `rehome` arm (`cli.py:1268-1273`):

```python
if args.command == "rescope":
    result = verbs.rescope(home, args.id, to=args.to, note=args.note,
                           no_push=args.no_push)
    return _finish_verb(result, <target scope>)
```

**Do not reuse `_routed_destination`** to derive the reported target.
`_routed_destination` splits the commit subject on `→` and then on a space
(`cli._routed_destination`, `cli.py:1193-1196`); the subject shape here is `→ skills/<name>` or `→ user`,
which happens to survive that parse, but the coupling is accidental. Pass the
resolved target explicitly.

Register `"rescope"` in the verb-name list at `cli.py:1844` alongside `"rehome"`.

### 6.2 `verbs.rescope` — step order

Mirrors `rehome` (`verbs.rehome`, `verbs.py:3576-3665`) exactly, with the scope rewrite added.
**Every refusal lands before the sentinel hold and before any commit or
directory creation.**

1. `home = Path(home)`; `path = find_record_path(home, record_id)` — pending
   **or** resolved, so the status refusal below can speak accurately.
2. `_scan_or_refuse([path], note)` — secret scan of the record file and the
   note, **before** trusting contents (P2-7). Load-bearing here (§4.1).
3. `record = Record.from_path(path)`. Refuse unless
   `path.parent.name == "pending"` **and** `record.status in ("pending", "deferred")`.
   The status is what refuses, never mere existence.
4. Parse and validate `--to`:
   - `user` → target scope `user`, target bucket `home / "user"`.
   - `skill:<name>` → validity-gate the name through
     `skill_dir_for(load_hosts(home), name)`, converting `HostsError` to
     `VerbError`. Target bucket `home / "skills" / name`.
     **The gate is mandatory**: a typo'd skill name must refuse, never create
     `skills/<typo>/`. (`bucket_dir_for_scope` already does exactly this
     — `ledger_ops.bucket_dir_for_scope`'s `skill:` arm, `ledger_ops.py:313-320` —
     and is the preferred implementation.)
   - anything else (`project`, a bare `skill`, a path, empty) → refuse.
5. **Source-scope refusals — the BUCKET is the single authority, never the
   record's `scope:` field.** Derive `source_bucket = path.parent.parent` and
   `source_scope` from the bucket's own location (`projects/<slug>` → `project`,
   `skills/<name>` → `skill:<name>`, `user` → `user`). Then refuse if the source
   bucket is under `projects/`, if source scope == target scope, or if source and
   target are both `skill:` (§4).

   **Why the bucket wins.** On a record whose frontmatter `scope:` disagrees with
   its bucket — exactly the corruption this verb exists to prevent — a
   record-derived and a bucket-derived check disagree about what is being moved.
   `rehome` already resolves this the same way: it uses `path.parent.parent` for
   both its non-project refusal (`verbs.py:3620-3621`) and its
   target==current check (`verbs.py:3632`), and never reads `record.scope`.
   Matching it keeps one rule across both filing verbs. A record whose `scope:`
   disagrees with its bucket is therefore *repaired* by `rescope` (the rewrite in
   §6.3 sets `scope` to match the destination), never refused on the strength of
   the field the corruption lives in.
6. Destination collision, checked **before any dir creation**: refuse if
   `<target_bucket>/{pending,resolved}/lrn-<id>.md` exists. (The F4
   `create_record` precedent — `verbs.rehome`'s destination-collision guard,
   `verbs.py:3638-3646`.)
7. `hold = sentinel.hold()`; `sentinel.heartbeat()`; `try: … finally: hold.release()`.
8. Inside `with _ledger_write(home):` — the commit lock, opened **before the
   first mutation**, not at commit time (`verbs._ledger_write`, `verbs.py:397-409`):

   ```python
   touched, swept = rescope_record(home, record_id, target_scope, target_bucket)
   body = _rescope_commit_body(note, swept)      # R-DISCLOSE-2, see below
   staged, sha = _commit_ledger(home, touched, message, body)
   ```

   `rescope_record` returns a **pair**, not a flat list (§6.3) — `swept` is the
   list `remove_proposal_siblings` returned, and it is the only thing that can
   tell the swept paths apart from the two rename halves inside `touched`.

   `_rescope_commit_body(note, swept)` composes the commit body: `note` (or
   nothing) followed, when `swept` is non-empty, by one `swept: <relpath>` line
   per swept file. This composed string is what reaches `_commit_ledger`'s
   `note` parameter, because `_commit_ledger` passes it straight through as
   `gitops.commit(..., body=note, ...)` (`verbs.py:460`) — there is no second
   body channel. **R-DISCLOSE-2 is implemented here or not at all.**
9. `push = _push_ledger(home, no_push)` — **outside** the lock, behind the
   no-remote guard (`verbs._push_ledger`, `verbs.py:468-474`).
10. Return — note the THIRD argument to `_rescope_sweep_note`: it takes the
    **display label** (`skills/bitwarden-cli` or `user` — the same shape
    the commit subject uses, e.g. via a small `target_scope -> dest_label`
    helper such as `_rescope_dest_label`), never the raw scope literal
    (`skill:bitwarden-cli`) — passing `target_scope` here would print
    "will be re-analyzed in skill:bitwarden-cli", contradicting §5.5's
    own worked example (`skills/bitwarden-cli`):

    ```python
    dest_label = _rescope_dest_label(target_scope)  # "skills/<name>" or "user"
    VerbResult(
        action="rescope", record_id=record_id, commit_message=message,
        commit_sha=sha, staged=staged, push=push, sentinel_owned=hold.owned,
        post_notes=([_rescope_sweep_note(record_id, swept, dest_label)]
                    if swept else []),
    )
    ```

    `post_notes` (`verbs.py:309`) is the carrier for **R-DISCLOSE-1**: it is a
    real `VerbResult` field that `_finish_verb` prints to stdout, one line each,
    immediately after the summary line (`cli.py:1181-1182`). It is the only
    stdout channel a ledger-only verb has beyond that summary. Empty list when
    nothing was swept — so the "never `swept 0`" rule in §5.5 falls out of the
    structure rather than needing a guard.

**No telemetry emission** — see §7.

### 6.3 `ledger_ops.rescope_record` — the file-op half

Modelled on `resolve_record`'s rewrite-then-move ordering
(`ledger_ops.resolve_record`'s tail, `ledger_ops.py:2157-2172`), not on `rehome_record`'s move-only ordering.

```
path = find_record_path(home, record_id, statuses=("pending",))
source_bucket = path.parent.parent
<destination collision check — belt, before any dir creation>
for sub in ("pending", "resolved", "proposals"):
    (target_bucket / sub).mkdir(parents=True, exist_ok=True)
record = Record.from_path(path)
record.set_scope(target_scope)          # the one substance change
dest_path = target_bucket / "pending" / path.name
if _is_tracked(home, path):
    _git_ok(home, "mv", str(path), str(dest_path))
else:
    path.rename(dest_path)
record.write(dest_path)                 # rewrite AT THE DESTINATION
swept = remove_proposal_siblings(home, source_bucket, record_id)
touched = [path, dest_path, *swept]
return touched, swept                   # PAIR — swept is the disclosure carrier
```

- **No `meta.yaml`.** `ensure_project_meta` is project-only and must not be
  called; `user/` and `skills/<name>/` carry no meta (verified, §4).
- `remove_proposal_siblings` is reused unchanged — it already sweeps
  `lrn-<id>.yaml`, `lrn-<id>.diff`, and every `merge-*.yaml` whose `records`
  list names the id (`ledger_ops.remove_proposal_siblings`, `ledger_ops.py:2019-2038`).
- Returns `(touched, swept)`. `touched` is the exact path list `_commit_ledger`
  stages, deletions included (pre-staged by `git mv`/`git rm`, or untracked);
  `swept` is the subset the sweep removed. Returning a pair rather than a flat
  list is what makes R-DISCLOSE-1/-2 implementable — from a flat `touched` the
  verb layer cannot tell a swept proposal from a rename half. This is the one
  place `rescope_record`'s signature deliberately differs from
  `rehome_record`'s.

### 6.4 Crash window — the two post-mutation states, and why mv-first is correct

§6.3 orders `git mv` (which stages the rename instantly) **then**
`record.write(dest_path)`. A kill between those two calls is a real window, and
the spec names both states it can leave:

| State | Shape on disk | Reached by |
|---|---|---|
| **S1 — moved, not rewritten** | record at `<target>/pending/lrn-<id>.md` still carrying the **source** `scope:`; rename staged | kill between `git mv` and `record.write` |
| **S2 — moved and rewritten, not committed** | record at the destination with the correct `scope:`; rename staged, content modified | kill between `record.write` and the commit landing |

S1 is precisely the scope↔bucket inconsistency §4.1 calls corruption: a
`scope: user` record sitting in `skills/<name>/pending/`, which every consumer
that re-derives the bucket from the scope would look for in `user/` and not find.

**Exit 7 covers both without needing to distinguish them.** The half-written
renderer prints the state fact and `exc.repair` rather than a per-state narrative
(`cli.py:1354-1362`: "WRITE NOT COMMITTED … The ledger IS mutated — this is NOT a
clean refusal and a blind retry is not safe. Repair: …"). A human re-running
`rescope` after S1 hits the destination-collision refusal (§6.2 step 6) rather
than compounding the damage, which is the behaviour the collision guard exists
for.

**`reconcile` will not heal either state — and that is the argument for this
ordering.** Reconcile "never commits a deletion and never touches a staged
rename: a half-committed `git mv` … must not be committed one half at a time",
and reports such entries as **blocked**, naming the verb's own printed repair
(`reconcile.py:46-54`; the porcelain guard is `_BLOCKING_CODES = ("R", "D")` at
`reconcile.py:87`). Both S1 and S2 carry a staged `R`, so both are blocked and
reported — visibly stuck, never silently "fixed".

Now invert the order to see why that is the good outcome. Writing the new `scope:`
at the *source* path first and moving afterwards would leave, on a kill, a merely
**modified tracked file** — no staged rename, no `R` code. Reconcile *would*
auto-commit that, landing a record in `user/pending/` whose frontmatter says
`scope: skill:<name>`: a scope↔bucket mismatch committed silently, with a clean
`git status` and exit 0. **The mv-first order converts a silently-committable
corruption into a loudly-blocked one.** That is why §6.3 follows
`resolve_record`'s ordering rather than inventing its own.

### 6.5 Commit message

Pinned subject, one commit for the whole move:

```
self-learn: rescope lrn-<id> → skills/<name>
self-learn: rescope lrn-<id> → user
```

Body carries `--note` when given, plus the `R-DISCLOSE-2` swept-path lines.

Also update `rehome`'s refusal string (`verbs.py:3622-3627`) to name `rescope`
as the human's repair for the cross-scope case, the way its target refusal
already names `host add`. This is the only edit this unit makes to `rehome`.

## 7. DECIDE — telemetry: no event

**Decision: `rescope` emits no telemetry event.**

- `EVENT_KINDS` is a **closed set** and "extending the closed event-kind set is
  a schema version bump (11 §4.3)" — `telemetry.EVENT_KINDS` and the bump note
  above it, `telemetry.py:63-89`. The v3 set is
  `offer-made, offer-declined, capture, card-shown, card-decided, fire,
  recurrence-suspect, staleness-flag, surface-budget, route, reference-read`.
  `rescope` is in none of them, so emitting anything requires a v3→v4 bump.
- **The sibling verb emits nothing.** `rehome` — the other filing move — has no
  telemetry call at all. The only `spool_*` calls in `verbs.py` are the two
  routing legs' (`route` `:2814`, `route_direct` `:3122`) and the compilers'
  `surface-budget` spool inside `_apply_target` (`:2338`) — all three
  `spool_quiet`, never `spool_event`, because telemetry must never break a verb.
  A ledger-only filing move is neither a resolution nor a compile, and touches
  neither.
- **No consumer would read it.** `read_events`, `report.gather`, and
  `worker._recurrence_suspects` all key on kinds they name (`telemetry.py:64-67`).
  A `rescope` kind would be written and never read — bookkeeping cost with no
  instrument attached.
- **Git already is the record.** `02-schema.md:334-336` pins that lifecycle
  provenance is carried by git: the commit's author, date, and message. The
  pinned subject makes every re-scope greppable (`git log --grep='rescope'`).

If a later cap/report unit wants filing-churn as a measured signal, that unit
owns the schema bump and the consumer together. Adding a producer now, with no
consumer, is the shape this codebase already regrets elsewhere.

## 8. Failure modes — every exit code and its trigger

Verified against `cli.py:13-22`, `cli.py:65-76`, `gitops.py:114-140`,
`ledger.py:41`, and the `_cmd_verb` handler chain (`cli.py:1298-1363`).

| Code | Constant | Trigger for `rescope` |
|---|---|---|
| **0** | `EXIT_OK` | Move committed. (Push skipped by `--no-push` or by the no-remote guard still exits 0.) |
| **1** | `VerbError.exit_code` | Every refusal in §6.2 steps 3–6: not pending/deferred · source is a `projects/*` bucket · `--to` unparseable or `project` · skill name not under the registered skills root, or ambiguous, or no skills root registered · target scope == source scope · `skill → skill` · id already present in the target bucket. **Also** `SecretRefusal` — a secret in the record file or in `--note` (P2-7), refused before any write. |
| **3** | `EXIT_PUSH_FAILED` | The commit landed; `push_if_remote` failed. The move is **kept** — this is a push failure over a good commit, never a rollback. |
| **4** | `EXIT_REBASE_CONFLICT` | The commit landed; the push's `pull --rebase` hit a conflict. Move kept. |
| **5** | `EXIT_NO_HOME` | `_home_gate` — the ledger home is missing or is not a git repo. Refused before `find_record_path`, so a bad home never surfaces as "no such record" (`cli._cmd_verb`'s docstring, `cli.py:1200-1206`). |
| **6** | `EXIT_GIT_FAILED` | A `GitOpsError` reached dispatch that is **not** half-written — e.g. the commit lock could not be taken. Nothing mutated. |
| **7** | `EXIT_HALF_WRITTEN` | `gitops.HalfWrittenError`: `rescope_record` moved and rewrote the record, then `stage`/`commit` failed. The ledger is mutated and the commit did not land. Rendered through the single half-written renderer (`cli`'s single half-written renderer, `cli.py:1351-1363`). |
| **64** | `EXIT_USAGE` | `LedgerOpsError` — unknown or malformed record id. Deliberately not 2, which is pinned to `proposal validate`'s scan-hit (`cli.py:66-69`). |

**A missing `--to` is refused by argparse itself with exit 2**, exactly as
`rehome`'s is — probed: `cli.main(["rehome", "lrn-00000000"])` returns `2` after
printing `the following arguments are required: --to`. `cli.py:69` says so in its
own words: "argparse's own flag-error exit stays 2 but cannot occur on a
well-formed programmatic invocation." 64 is the CLI's own usage code and is never
reached for a flag error. **The builder must NOT intercept argparse to remap it** —
that would move a pinned surface shared with every other verb.

**6 vs 7 is the distinction to get right.** 6 = the git operation failed with
nothing mutated. 7 = the mutation happened and the commit did not. The split is
made in `_commit_ledger` (`verbs._commit_ledger`, `verbs.py:442-460`), which raises `HalfWrittenError`
in the *verb* layer precisely because everything reaching it is post-mutation
by construction. `rescope_record` must therefore raise `LedgerOpsError` (→ 64),
never `GitOpsError`, for its own validation failures.

## 9. Out of scope

Non-empty by requirement, and each item is a real thing a builder might reach for.

1. **Routing analysis and destination selection.** `rescope` never reads,
   writes, or reasons about `destination`. It does not re-run the analyst.
2. **Cap logic / load-class budgets.** A re-scope changes which budget a record
   would eventually charge; this unit measures, enforces, and reports nothing
   about that. (`misc/orchestration-plan-2026-08-23.md` Wave 2 item #1 owns caps.)
3. **The review card UI.** No change to `07-review-ui.md`, the pane, the review
   command doc's card sections, or any SSE surface. A human runs `rescope` from
   the CLI in M1.
4. **The pane's proposable-verb list.** `rescope` does **not** join the §4.5
   closed list. No `propose_verb` intake validation, no proposal bar, no
   `rescope:` proposal field. (§3 rationale 2.)
5. **`skill:<a> → skill:<b>`** and **any direction involving `project`.** §4.
6. **`rehome` itself** — not deprecated, not merged, not re-scoped. One line of
   its refusal string changes (§6.5); nothing else.
7. **`gates.load_class`'s isolated cross-scope behaviour** (§5.3 leg 2).
   `load_class` reads `t4` unconditionally once the t3 route is not taken
   (`gates.py:74-107`), so called *directly* at a foreign scope it raises
   `TypeError`. It is `_validate_gates` running first in `validate_proposal`
   (`ledger_ops.py:1846-1847`) that makes it total in practice, and there is no
   production caller that skips it — so this is **not a live defect and not an FW
   row**. Do not "fix" it, and do not write it into any permanent doc as a latent
   crash.
8. **Re-scoping resolved records.** `routed`/`rejected`/`superseded` records do
   not move; `supersede` is the correction machinery (02 §2).
9. **Bulk / multi-id re-scope.** One id per invocation.
10. **`chezmoi` / host-side compilation.** `rescope` is ledger-only — no host
    phase, no recompile, no managed-section write. A record's *routed* surface
    is unaffected because only pending records move.
11. **`routing-doctrine.md`** — the analyst-facing doctrine at
    `plugins/self-learn/skills/self-learn/references/routing-doctrine.md`. A
    builder grepping `rehome` gets five hits there, including the
    `rehome-suggested` / `scope-mismatch` flag list (`:435`) and the "There is no
    `rehome:` proposal field" pin (`:371`) — the natural place to add `rescope`,
    and the one this unit must not touch. Its guidance stays as-is in M1:
    `rescope` is human-only (§3 rationale 2), so the analyst is not taught to
    suggest it.

## 10. Tests — enumerated

New file: `plugins/self-learn/cli/tests/test_rescope.py`.
Model it on `test_rehome.py`: module docstring naming what is covered, an
autouse `cache_dir` fixture redirecting `XDG_CACHE_HOME` (so the sentinel never
touches the real `~/.cache`), and an `Env` class over `support.make_env`.

**Fixture shape.** `make_env(tmp_path, skills=("s", "t"))` gives a host repo
with two registered skills (`s`, `t`) under a registered `skills_root`, and a
ledger home with `skills/ projects/ user/ telemetry/` + `hosts.yaml`. Seed
records with `create_record(home, make_knowledge(scope="user"))` — no
`project_path` needed for `user`/`skill:` scopes. Seed proposals with
`write_proposal(home, rid, proposal_dict(scope=<the record's scope>))`.
Commit between seeding and acting (`commit_all`), so `_is_tracked` takes the
`git mv` branch, matching production.

### 10.1 The move

| # | Test | Asserts |
|---|---|---|
| T1 | `test_user_to_skill_moves_and_rewrites_scope_in_one_commit` | record gone from `user/pending/`, present at `skills/s/pending/`; `Record.from_path(dest).scope == "skill:s"`; `result.action == "rescope"`; subject == `self-learn: rescope <id> → skills/s`; `verb_subject(home)` matches; `verb_files(home)` contains **both** the source and destination paths (one commit carries both rename halves) |
| T2 | `test_skill_to_user_moves_and_rewrites_scope` | the inverse leg; `scope == "user"`; subject `→ user` |
| T3 | `test_body_and_lifecycle_fields_survive_the_rescope` | body text byte-identical; `status`, `sightings`, `evidence`, `created_at`, `routing`, `resolution_note` all unchanged. **Positive control:** assert `scope` DID change in the same test, so a no-op implementation cannot pass by touching nothing |
| T4 | `test_deferred_record_rescopes_and_stays_deferred` | seed with `defer_record(home, rid, "2027-01-01")`; after: `status == "deferred"`, `deferred_until == "2027-01-01"`, `deferred_count == 1` |
| T5 | `test_creates_target_bucket_dirs_when_absent` | `skills/t/` does not exist before; after, `pending/`, `resolved/`, `proposals/` all exist |
| T6 | `test_no_meta_yaml_is_written_for_user_or_skill_targets` | `not (target_bucket / "meta.yaml").exists()` — guards against a builder copying `rehome_record`'s `ensure_project_meta` call |
| T7 | `test_note_rides_the_commit_body_not_resolution_note` | `"umbrella" in commit body`; `Record.from_path(dest).resolution_note is None` |
| T18b | `test_bucket_not_frontmatter_decides_the_source_scope` | MAJOR-3's pin. Hand-write a record with `scope: user` into `skills/s/pending/` (a scope↔bucket disagreement), then `rescope --to user`. The **bucket** is `skills/s`, so this is a legal `skill → user` move and it SUCCEEDS, landing the record in `user/pending/` with `scope: user`. **Positive control:** the same fixture with `--to skill:s` refuses with "already lives in" — proving the refusal read the bucket, not the frontmatter field (which said `user` and would have permitted it). Together the two legs pin which authority is consulted; a record-derived implementation gives the opposite answer on both |

### 10.2 The proposal sibling — the required test, in the shape §5 decides

| # | Test | Asserts |
|---|---|---|
| **T8** | **`test_proposal_is_swept_never_left_behind_and_never_carried`** | **The load-bearing test.** Seed a proposal AND a `.diff` in the source bucket, commit. **Positive control FIRST** — assert `(source_bucket/"proposals"/f"{rid}.yaml").is_file()` before acting, so a fixture that silently failed to write a proposal cannot make the test vacuous. Then rescope, then assert all three: (a) the proposal is **gone from the source bucket** — it is not left behind as litter; (b) it is **not present in the target bucket** — it was not carried; (c) `verb_files(home)` names the swept paths, proving the removal rode the same commit |
| T9 | `test_merge_cluster_naming_the_record_is_swept_strangers_survive` | two `merge-*.yaml` in the source bucket, one naming the record and one not; after: the naming one is gone, the stranger survives. Positive control: assert both exist before |
| T10 | `test_rescoped_record_reads_as_unanalyzed_in_the_new_bucket` | the recovery path §5.4 depends on. After the move, build a `QueueEntry` for the destination and assert `proposal_info(entry)["has_proposal"] is False` and `is_unanalyzed(entry) is True`. Positive control: assert `is_unanalyzed` was `False` in the source bucket before the move |
| T11 | `test_sweep_is_disclosed_in_post_notes_and_commit_body` | `R-DISCLOSE-1`/`R-DISCLOSE-2` against the carriers §6.2 pins. With a proposal present: `result.post_notes` is non-empty and its line names the record and the destination bucket (R-DISCLOSE-1), and `git log -1 --format=%B` on the verb commit contains a `swept:` line naming the proposal path (R-DISCLOSE-2). Drive the CLI once too, asserting the `post_notes` line reaches **stdout** — `_finish_verb` prints it (`cli.py:1181-1182`). **Negative leg in the same test:** with no proposal present, `result.post_notes == []`, no `swept:` line in the body, and no "swept 0" anywhere |

*If the gate overrules §5, T8/T10/T11 are the tests that invert; T9's
stranger-survives leg holds either way.*

### 10.3 Refusals — each exit code's trigger

Every refusal test asserts the refusal happened **and** that nothing moved
(source record still at its original path, target bucket not created).

| # | Test | Asserts |
|---|---|---|
| T12 | `test_refuses_resolved_record` | route the record first, then rescope → `VerbError`; message names `supersede` as the correction machinery |
| T13 | `test_refuses_project_scoped_source` | a `project`-scope record → `VerbError` naming `rehome` |
| T14 | `test_refuses_project_target` | `--to project` → `VerbError` |
| T15 | `test_refuses_unknown_skill_name` | `--to skill:nope` → `VerbError`; **and** `not (home/"skills"/"nope").exists()` — the typo did not create a bucket |
| T15b | `test_refuses_ambiguous_skill_name` | the same skill name under two plugins in the host repo → `VerbError` naming both paths (`hosts.skill_dir_for`'s ambiguity arm) |
| T15c | `test_refuses_when_no_skills_root_is_registered` | a ledger whose `hosts.yaml` carries no `skills_root` → `--to skill:s` refuses, and the message names `host add <path> --skills-root` as the repair (`hosts.py:551-554`). §8's exit-1 row lists all three `skill_dir_for` shapes; T15/T15b/T15c are one test each |
| T16 | `test_refuses_bare_skill_without_name` | `--to skill` and `--to skill:` both refuse |
| T17 | `test_refuses_same_scope` | `user` → `--to user` → `VerbError` "already lives in" |
| T18 | `test_refuses_skill_to_skill` | `skill:s` → `--to skill:t` → `VerbError` naming it as dated future work |
| T19 | `test_refuses_destination_collision_before_creating_anything` | same id already in `skills/t/pending/` (and a second case in `skills/t/resolved/`) → `VerbError` "duplicated id is corruption to surface"; assert the source record is untouched |
| T20 | `test_secret_in_record_or_note_refuses_before_any_write` | two legs — a secret in the record body, and a secret in `--note`. Both refuse; record still in the source bucket, target bucket absent |
| T21 | `test_unknown_id_exits_64` | `cli.main(["rescope", "lrn-00000000", "--to", "skill:s"])` → `64` |
| T22 | `test_missing_home_exits_5` | point the home at a non-repo → `5`, and the message is the home message, not "no such record" |

### 10.4 CLI surface

| # | Test | Asserts |
|---|---|---|
| T23 | `test_cli_rescope_happy_path` | `cli.main([...])` returns 0; the record moved; stdout names the target scope |
| T24 | `test_cli_rescope_requires_to` | omitting `--to` exits **`2`** — argparse's own flag-error code, matching `rehome` (probed: `cli.main(["rehome", "lrn-00000000"])` → `2`). Not 64, and the builder must not remap it |
| T25 | `test_cli_rescope_refusal_exits_1` | a refusing invocation exits `1` and prints `self-learn rescope: …` to stderr |
| T26 | `test_rescope_is_not_in_the_pane_proposable_verb_list` | guards §3 rationale 2 and out-of-scope item 4. The closed set is `PROPOSABLE_VERBS` in **`plugins/self-learn/ui/src/self_learn_ui/proposals.py:67`** — today `frozenset({"route", "reject", "defer", "graduate", "rehome"})`. Assert it does **not** contain `rescope`. **This test lives in the UI suite** (`plugins/self-learn/ui/tests/`), not the CLI suite, because that is where the symbol is; it is a guard against a later drive-by widening, and this unit changes no UI code. Run it with `uv run --project plugins/self-learn/ui pytest` |

### 10.5 Ledger discipline

| # | Test | Asserts |
|---|---|---|
| T27 | `test_exactly_one_commit_is_created` | commit count before/after differs by exactly 1 |
| T28 | `test_half_written_exits_7` | use `support`'s git shim to fail `commit` while the flag file exists; assert exit `7`, and that the record is in the destination with the commit absent — the state 7 exists to describe |
| T29 | `test_no_push_skips_the_push` | `--no-push` → `result.push is None`, exit 0. **Positive control:** without `--no-push`, the same remote-less fixture returns `result.push.skipped is True` — NOT `None` — because `push_if_remote` returns `PushResult(ok=True, skipped=True)` on a repo with no remote (`gitops.py:675`). Without that control, `push is None` could pass for the wrong reason |
| T30 | `test_no_telemetry_event_is_spooled` | §7. Assert the `*.jsonl` lines under **`telemetry.spool_dir()`** are unchanged across the rescope. **Positive control:** a `route` in the same fixture DOES add a line there. **Do not point this test at `<home>/telemetry/`** — `spool_quiet`/`spool_event` write only to the XDG-cache spool (`telemetry.py:187`), while `<home>/telemetry/` is written by `flush` alone (`telemetry.py:225`); a test aimed there gets a *failing positive control* (the `route` leg spools nothing there either) and invites the builder to "fix" the wrong thing |
| T31 | `test_kill_between_mv_and_write_leaves_a_blocked_staged_rename` | **Added at code gate (MAJOR-1, 2026-08-23):** §6.4's mv-first ordering had no test that would go red under a write-then-mv swap — the counterfactual crash probe silently commits a scope/bucket mismatch via `reconcile` while the rest of the suite stays green. Monkeypatch `Record.write` to raise, simulating a kill between `git mv` and the rewrite; call `rescope_record` directly. Assert the S1 state exactly: `git status --porcelain` starts with `R ` (a staged rename, no working-tree modification — the write never landed), the destination file exists and still carries the STALE source scope, and `reconcile(home)` reports it in `blocked` (never `committed`) |
| T32 | `test_git_mv_runs_before_record_write_not_after` | **Added at code gate (MAJOR-1, 2026-08-23):** an ordering witness independent of T31's crash-simulation mechanism — a swap mutation might not always produce an observably-wrong porcelain state under every monkeypatch shape, so this test instruments both `ledger_ops._git_ok` (recording only its `"mv"` invocations) and `Record.write` to append to a shared order list, then asserts the observed order is `["mv", "write"]`. Reds directly on a write-then-mv swap, regardless of whether anything raises |

**Suite command:** `uv run --project plugins/self-learn/cli pytest tests/test_rescope.py`
plus the full CLI suite. The known pre-existing UI failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`)
is unrelated and does not block.

## 11. Docs to update in the same commit

- `02-schema.md` §2 — a `rescope` verb row beside `rehome`'s pin.
- `09-surface-spec.md` — a dated decision entry recording §3, §4, §5, §7, and
  explicitly recording that §5 **re-affirms** Y-18's sweep on new evidence
  (§5.2, §5.3) rather than inheriting it unexamined.
- `14-forward-work-map.md` — **two** FW rows: (a) `skill → skill` re-scope;
  (b) `project ↔ user/skill` re-scope. **No row for `gates.load_class`** — §5.3
  leg 2 establishes it is not a live defect (§9 item 7); writing it up as one
  would put a false permanent fact into the map.
- `plugins/self-learn/commands/review.md` — one line telling the reviewer that
  a scope mismatch on a pending record has a verb now, and that using it
  discards the current proposal and re-analyzes in the new bucket.

## 12. Open question for the user

§5 declines a hard requirement in the work order on evidence. That is a
judgement about which of two costs matters more — a discarded worker analysis
(the sweep's cost) versus a card that renders as fresh while reasoning from the
wrong scope (the move's cost). This spec ranks them, but the ranking is a
values call about how much the user trusts a rendered card, and it belongs to
the user rather than to the spec author. **§5.5 is the hedge**: it pays down
the sweep's cost with disclosure, so the answer only changes how much is
recovered, not whether anything is lost. Flagged here so the gate routes it
rather than ratifying it silently.
