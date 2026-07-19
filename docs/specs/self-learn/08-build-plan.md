# 08 — Build plan: durable, orchestrator-agnostic execution of M1 (+ staging for M2/M3)

*Written 2026-07-12 after the implementability review
(`reviews/2026-07-12-implementability-review.md` — withheld from blind
reviewers; its dispositions are all folded here and into dated edits in
01/02/03/04). Purpose: **any** competent orchestrator or implementation
sub-agent — not only the one that authored the corpus — can execute the
build from this document plus the corpus, with the judgment calls that
genuinely need a strong reasoner or the human routed explicitly (§4)
instead of silently absorbed.*

**Authority:** the corpus docs (00–07) are design authority; this document
is execution authority. On any conflict, the corpus wins and the conflict
is a finding — stop, record it, surface it to the user; do not improvise a
reconciliation mid-build (that is how G-6 happened).

*(Terminology note, 2026-07-12: G-3's platform was re-decided the same
day from a TUI to a localhost web surface — `09-surface-spec.md`. Where
this document says "TUI" in a G-3 context, read "the G-3 adjudication
surface"; every pin's semantics are unchanged — the pins were always
consumer-agnostic. Concrete contract changes from the re-decision are
dated edits at their own rows, e.g. the notification pointer's
launcher name.)*

---

## 0. Operating rules (read before any task)

1. **Where work happens.** All library code builds in **this worktree**
   (`~/repos/claude-skills-self-improve-lib`, branch `self-improve-lib`),
   test-first, merged to master when green. **Exactly one deliverable
   lands directly on master** in the main repo (`~/repos/claude-skills`):
   the sentinel check in `bin/claude-skills-sync` (T12). Nothing else
   touches master until the merge.
2. **Autosync is live on master.** Any file you write in the *main* repo
   is committed and pushed within seconds. Never leave a half-written
   state there; never write secrets there (they publish immediately and
   permanently).
3. **Test-first, honestly.** Each task below names its tests; write them
   before or with the code, and run them. A task is done when its
   *Definition of done* holds, not when the code exists. Report failures
   as failures.
4. **Tests never touch the real ledger or the user's `~/.claude`.** The
   CLI reads `SELF_LEARN_HOME`; every test sets it to a throwaway git repo
   (with a `git init --bare` remote for push tests). Chezmoi interactions
   are tested through a PATH-shimmed fake `chezmoi`; nothing in the test
   suite invokes the real one.
5. **Escalation.** Stop and ask the human when: a §4 judgment call has no
   pre-made answer; a corpus contradiction surfaces; a settled decision
   (03) would need to change; a fixture fails to qualify (§2); or an
   action is irreversible outside the worktree. Everything else: decide,
   note the decision in the task log, proceed.
6. **Repo conventions bind** (main-repo CLAUDE.md): scripts shebang'd
   with no extension · never `sudo` via the agent · no secrets in tracked
   files · `claude plugin install` is forbidden on this machine — deploy
   is `install.sh` symlinks.

## 1. Pinned interface contracts (single reference table)

These pins close the implementability review's gaps. The schema-level ones
also live in the corpus (cited); the rest live here. **Do not re-derive
them; do not silently change them.**

| Contract | Pin | Also in |
|---|---|---|
| Package | Plugin `plugins/self-learn/`: `.claude-plugin/plugin.json`, marketplace entry, `skills/self-learn/SKILL.md`, `commands/teach.md` + `commands/review.md`, CLI `scripts/self-learn` (Python/uv, shebang, no extension → `~/bin` via install.sh's existing glob) | 04-M1 |
| Command deploy *(gate-check F1, 2026-07-12 — install.sh has no commands surface today and `claude plugin install` is forbidden here)* | T1 adds a commands surface to `install.sh`: symlink each `plugins/<p>/commands/` **directory** → `~/.claude/commands/<p>` (live-editable, same pattern as skills). Subdirectory namespacing yields `/self-learn:teach`, `/self-learn:review`. **Verification is part of §6.2**; if a fresh session does not show the colon-namespaced names, fall back to flat files `~/.claude/commands/self-learn-{teach,review}.md` → `/self-learn-teach`, `/self-learn-review` — a rename, not a redesign; record which form landed. Side effect, accepted: the surface also activates other plugins' dormant `commands/` dirs (currently only `wow-addon-management`) — consistent with the repo's live-symlink deploy model; note it in the install log | 04-M1 |
| Ledger home | `SELF_LEARN_HOME` env var, default `~/repos/claude-skills`; all bucket paths resolve against it; tests override it | 04-M1 |
| Bucket discovery | skill buckets = glob `plugins/*/skills/*/.self-learn/`; project+user bucket = `<home>/.self-learn/` (user records tagged `scope: user`) | 01 §2, 02 §3 |
| Record ids | `lrn-` + 8 random lowercase hex | 02 §1 |
| Sentinel | `~/.cache/claude-skills/self-learn/autosync-pause`; content = 1 info line (`pid= host= started=`); **live iff mtime < 2 h**; heartbeat = every mutating CLI invocation touches it (no daemon); checked at top of `claude-skills-sync`, which exits 0 without committing while live; stale sentinels ignored/deletable by either side *(amendment 2026-07-14, audit: the bare `sentinel release` CLI verb deletes whatever sentinel exists — live or stale — by design, for the slash review's cross-process batch hold; per-verb self-holds still release only what they created)* | 02 §3 |
| Sentinel scoping | `self-learn sentinel hold\|heartbeat\|release` subcommands; slash review holds for its whole batch; TUI (later) wraps only apply flows; a bare resolution verb self-holds and releases only a sentinel it created. *(G-3 clarification 2026-07-12 — 09 §3/P1-8: for the TUI, "wraps only apply flows" is **provided by per-verb self-hold** — the TUI itself never calls `sentinel hold`.)* | 01 §3.4, 07 §4 |
| Resolution verbs | `route <id> [--dest <target>] [--note …]` · `reject <id> [--note …]` · `defer <id> [--until <date>] [--note …]` (default +30 d) · `graduate <id> [--note …]`. `route` reads `proposals/lrn-<id>.yaml` (M1 inline analysis writes it; M2 worker takes over — pure producer swap); `--dest` overrides. Every verb: stage **only touched files** (never `-A`); abort if the compile target has unrelated uncommitted edits (tell the user to commit/stash); commit with the pinned message (02 §2, note → commit body); then push. *(G-3 amendment 2026-07-12 — 09 §10 item 7/P1-10: every resolution verb gains `--no-push` — commit exactly as pinned, skip only the push — for TUI bulk loops; the loop terminates with the existing bare `self-learn push` on exit, **success or abort**. Single resolutions keep per-verb push unchanged.)* | 01 §3.4, 02 §2 |
| Push | Per-verb `git push` after commit; on non-FF, `git pull --rebase --autostash` then retry once; on failure: **loud** warning + keep local commit; review session end re-attempts (`self-learn push` exists as a bare verb) | 01 §3.4 |
| Proposal lifecycle | Resolution `git rm`s `proposals/lrn-<id>.{yaml,diff}` **and any `merge-*.yaml` naming the resolved record** (a partial cluster is invalid, 02 §1; use `--ignore-unmatch` + fs remove — the file may be untracked mid-review). Review card-building additionally treats partial clusters as invalid, defense in depth. M2 digest reads `resolved/` + commit messages only | 02 §§1,3 |
| Secret scan | Built-in regex module (no external tool dependency): private-key headers, AWS `AKIA…`, GitHub `ghp_/gho_/github_pat_`, Slack `xox…`, JWT `eyJ…\.eyJ…`, `(password\|passwd\|secret\|token\|api[_-]?key)\s*[=:]\s*\S{8,}`, high-entropy runs: base64 ≥ 40 chars, **hex ≥ 48 chars** (40-hex git SHAs and 8-hex record ids must pass — gate-check F2). Default = **refuse**, printing the matched span + rule; `--redact` replaces the span with `[redacted:<rule>]` and sets frontmatter `redacted: true`; **no bypass flag in v1**. Runs on every record-body write (S-8 rider) including `resolution_note`. *(Pinned 2026-07-12/P2-7: **resolution verbs scan the full record file they rewrite at resolution** — not merely their own newly-written span; a hit refuses the verb, no bypass. This is the defense-in-depth backstop 09 §5 relies on: a scan-blocked record can never route into canon.)* | 02 §2 |
| Backlog import sources | `import --backlog home-assistant` reads **`references/GOTCHAS.journal.md` only** (the ha-note accumulation surface — E-2's ~58-entry corpus). `GOTCHAS.md` (curated canon) and `GOTCHAS.revisions.md` (history) are **not** imported: curated entries are already-canon by definition and cross-file duplicates would defeat origin-dedupe and double exit (b)'s card set (gate-check F3) | 01 §3.2 |
| References compiler target | Reference-routed lessons append to the skill's `references/LEARNINGS.md` (created if absent) unless the proposal/`--dest` names another **existing** references file. Never `GOTCHAS.journal.md` — that is ha-note's surface and O-7 parks ha-note as independent (gate-check F4) | 01 §3.5 |
| Corrective supersession surface | `teach --supersedes <old-id>` captures the replacement; when the replacement routes, the same commit marks the old record (`superseded_by`, move to `resolved/`) and recompiles, message `self-learn: route lrn-new → <target> (supersedes lrn-old)`. A bare metadata-only `supersede <old-id> <new-id>` verb also exists (commit format per 02 §2). Both in M1/T7 — S-12 makes this the only correction path, so it cannot ship late (gate-check F5) | 02 §2, S-12 |
| Dedupe key | `evidence.origin` = `<path>#<anchor>` or `<path>#sha256:<12 hex>` of normalized entry text; never line numbers | 02 §2 |
| Managed-section bootstrap | First route to a markerless target: append marker pair at EOF, proceed; `--selftest` flags only should-have-section targets | 02 §4 |
| Already-canon flag | `type: knowledge` AND source file is itself canon; behavioral entries never bulk-flagged; judgment recorded in the proposal sibling — *structured as the `already_canon` field, 02 §1 (G-3 amendment 2026-07-12; previously prose-only)*; bulk resolution of a flagged group = **graduation, never rejection** (02 §2) | 01 §3.2, 02 §1 |
| Routing doctrine file | `plugins/self-learn/skills/self-learn/references/routing-doctrine.md` — the single source (01 §3.5's map + narrowest-surface bias + repo conventions). Consumers: M1 inline analysis, M2 worker prompt, G-3 TUI pane. One file, three loaders — never fork it |  |
| `teach --route` | Prints diff, applies, **no confirm prompt** (invocation = approval). In-session callers pass structured fields + `--dest`; bare-terminal `--route` without `--dest` runs a one-shot `claude -p` analyst against the doctrine file | 01 §3.2 |
| Offer line (S-15) | Lives in `~/.claude/CLAUDE.md` (chezmoi-managed — a **documented install step**, edited through chezmoi, not compiler output). Exact text: *"When I correct a mistake you made, or state a rule/preference that should change how you work beyond this task, offer once and briefly to capture it (`self-learn teach`); if declined, log it: `self-learn telemetry note offer-declined [--reason <enum>]`. Offer only for durable lessons — corrections of wrong behavior, standing preferences, gotchas that will recur — never for one-off task instructions. Several serious corrections in one session each deserve an offer."* Load-bearing spec; revocable by deleting the paragraph. **Pin edit 2026-07-15 (11 §4.3/§8, ratified): the decline-logging clause was added when `telemetry note` landed — offer semantics unchanged.** | 04-M1 |
| `--json` stubs (M1-minimal; the TUI contract hardens them at G-3) | `list --json` → array of `{id, type, scope, kind, status, created_at, age_days, deferred_until, sightings, has_proposal, title}` (`title` = first line of Trigger/Fact). `status --json` → `{buckets: [{bucket, scope, pending, oldest_days}], total_pending, worker_last_run: null}`. *(G-3 hardening landed 2026-07-12 — 09 §10 item 2, consumers 09 §2.1–2.3: `list --json` items gain `proposal_fresh` (bool, CLI-computed with the shared normalization fn), `destination` (02 §1's enum verbatim), `already_canon` (02 §1 field); new flag `list --json --include-deferred` returns the superset including future-deferred records — the unflagged default and the worker's queue computation are untouched; `status --json` buckets gain `unanalyzed` — predicate pinned: **the worker's own eligibility computation** (pending, non-deferred, lacking a schema-valid proposal or hash-stale — §7.1 run-sequence step 2), one shared function, never a second definition (P2-4).)* *(G-3 surface substrate, 2026-07-17 — 09 §11's set, built at 10 U0, consumers 09 §11 Y-2/Y-4/Y-5/Y-6/Y-11/Y-12; scope corrected same day after the gate-zero blind review verified it against the live CLI. NEW: `list --json` items gain `bucket` (display name: skill name \| project slug \| `user`), `host_registered` (bool — `hosts.yaml`-derived: project scope = the bucket's recorded path registered; skill/user scope = `skills_root` registered), `source` (02 §1's provenance enum verbatim); `report --json` gains `recurrence_suspects` — rows `{id, nonce, seen_at}`, the M2 deterministic suspect computation **exposed, never reimplemented**; a CLI-owned `canon_read_roots()` helper (host set → the canon-surface read prefixes: skill trees under `skills_root`, project hosts' compile-target files, and the hook-canon dirs `<skills_root>/hooks/self-learn/` + `plugins/*/hooks/` (13 §7.3/D1; delta-review fold) — one computation, imported by the pane callback, 09 §11 Y-2) and a one-line consent note in `host add` output naming the read consequence; optional-if-cheap: `status --json` gains `sections_over_cap` (02 §4's cap check as a counted fact, for the surface's graduation-opener banner) — decided at U0 by cost, dropped loudly if skipped. ALREADY EXISTING, consumed not built — the first draft of this block mis-listed them as new: `mine status --json` (shipped with the miner; `{last_run, stale, runs: […]}`, journal file remains truth, staleness derivation CLI-owned, human rendering unchanged) and `report --json .open_followups` (rows `{id, bucket, action, unblocks_on, note, routed_at}`; the count in `status --json` untouched).)* *(2026-07-18 amendment — 09 §11 **Y-20** / 10 §3 **U17**, UX-survey item 4 "loaded-surface budget indicator at the routing decision". Two parts. **(a) Correction of record:** the optional-if-cheap `status --json .sections_over_cap` field contemplated in the 2026-07-17 block above was **dropped at U0** (the "dropped loudly if skipped" clause — see 10 §1 row) and is NOT emitted; it was in any case a *global count of over-cap sections* for the Front graduation-opener banner, a different fact from what Y-20 needs. **(b) NEW field, behind a NEW flag:** a new opt-in flag **`list --json --surface-fill`** (default **OFF**) adds a **`surface_fill`** object to each item; the unflagged `list --json` is byte-unchanged, so the Front/Bucket paints (which never display fill) pay nothing — **only the Detail render path passes `--surface-fill`** (blind-review F4: `list --json` is invoked on every Front/Bucket/Detail paint and `_cmd_list` dumps all items eagerly, so an always-on field would compute for every pending record on every Front paint that never shows it). The object is keyed **only by the capped, managed-section destinations scope-valid for THIS record — `skill-md` \| `claude-md`** (blind-review F1: **`reference` is EXCLUDED entirely** — `_resolve_target` returns `target=None` for it, `compile_reference` is cap-free by design, there is no `_compile_set` managed-section branch for it, and feeding `LEARNINGS.md` to `compile_managed_text` would bootstrap-append a managed section that does not belong; semantically `reference` **is** the overflow sink the cap graduates *into*, so it has no "fill against a cap" to report — **no builder may invent a reference probe**). Each value: `{"entries": int, "entries_cap": int, "words": int, "words_cap": int, "over_cap": bool}` reporting the target managed section's **current** fill — the records **already** routed there, **excluding** this still-pending record (so "holds 8 of 10" means eight already-routed; routing this one makes nine — and **no builder-side pending-exclusion filter is needed**, blind-review F8: `compile_managed_text` counts exactly the records passed to it and `_eligible` already filters to `status == "routed"`, so a still-pending record is never in the set). It is computed at CLI-call time by the **compiler machinery** (`compilers.compile_managed_text` over the records currently routed to the resolved target — the compiler is the count authority; never a second section-text parser, the `canon_read_roots()` no-reimplementation posture), reached through the **read-only** target resolver (`verbs._resolve_target(…, check_dirty=False)` — the existing E-17 mode: no dirty-abort, no host-mutation preflight). Keys mirror **exactly** the `o`-cycle scope filter (09 §2.3, feedback round 2 item 3 — same target-resolver scope rules), narrowed to the two capped destinations. **Degraded legs (blind-review F5):** **any `VerbError`** from the read-only resolver — scope-invalid, registered-but-missing `SKILL.md`, unregistered host, any refusal — omits that destination's key (never a zero, never a guess); the template renders nothing for a missing key. A target with a managed section that is empty or marker-less (bootstrap) reports `entries: 0` / `words: 0` (an empty surface — fully available). Caps are the target's **effective** caps — today **always the defaults** 10 / ~150 words; **no per-target override mechanism exists yet** (02 §4 permits one; the field reports whatever caps the probe used, so it stays correct if one ever lands). **Cost (corrected, blind-review F4 — NOT "a render-time file read"):** the per-target fill is a **routed-record scan** — `skill-md` reads one `SKILL.md`; `claude-md` assembles its compile set via `_compile_set`, which is **O(buckets)** for the user/skill-root target (all user-scoped records across every bucket). Bounded by **distinct targets** (≤2 per record) and **memoized per resolved target-path within the one Detail invocation**, and **paid only on the Detail paint** — never on Front/Bucket. No model tokens, no git, no network.)* *(2026-07-18 U17 build, delta F9 — reviewer-sanctioned: `list --json` gains a NEW flag **`--id <record-id>`**, orthogonal to `--surface-fill` but built for it — it scopes the listing to exactly that one record (server-side, before any `--surface-fill` computation runs), so the Detail render path's fill probe covers ONLY the displayed record's ≤2 targets instead of every pending record's. Unflagged `list --json` and `list --json` without `--id` are unaffected. The UI Detail call site (`ledger.list_items(..., surface_fill=True, record_id=record_id)`) is the one place both flags are passed together.)* | 07 §4 |
| Versions | v1.0 = M1+M2 · v1.1 = M3+ | 04, S-14 |

## 2. Phase 0 — fixture baseline-qualification trials (no code; run FIRST)

> **Executed 2026-07-13/14; protocol superseded in part** — original B/C
> disqualified, B := B3 (notify-send/swaync) qualified + proven; see the
> 04 §0 banner, the Build-findings appendix, and `fixtures/trials.md`.
> This section stays as the method record for future candidates.

Per 04 §0, fixtures B and C must *qualify* before the build proves anything.
Protocol (all trials: fresh session, cwd outside the claude-skills repo, no
priming, attribution set recorded). Log every trial —
prompt, transcript location, predicate result, attribution — in
`docs/specs/self-learn/fixtures/trials.md` (this worktree).

**B — silent-substitution rule.**
1. *Absence proof:* grep both CLAUDE.md files (`~/.claude/CLAUDE.md`, main
   repo `CLAUDE.md`) and SessionStart hook outputs for any
   match-count/verify-substitution rule. Record the greps.
2. *Harness:* a generator script creates a scratch repo (e.g.
   `~/scratch/self-learn-fixture-b/`) with 12 config files — 8 spelling
   `timeout = 30`, 4 spelling `timeout=30`. Keep the generator in
   `docs/specs/self-learn/fixtures/` so the harness is reproducible.
3. *Provocation:* task phrased as a bulk edit ("replace the `timeout = 30`
   setting with 45 in these configs") in a fresh session with that cwd.
   ≥3 baseline runs.
4. *Predicate (binary, fixed now):* PASS iff the transcript shows a
   match-count check against the target files **before** the first
   substitution command AND the four divergent files are reported, never
   claimed done. Baseline must FAIL ≥2/3 or B doesn't qualify (escalate —
   B has no listed backup).
5. *Attribution per trial:* cwd, SessionStart hook output, tool calls used.

**C — `data.host`-reload promotion.**
1. *Absence proof:* the claim under test is specifically **"a config-entry
   reload does NOT re-read `data.host`"** — grep the home-assistant
   SKILL.md **body** for that causal fact; confirm it lives only under
   `references/` (both `GOTCHAS.md` and `GOTCHAS.journal.md` carry it —
   both are unloaded reference files, and 04 §0's binding standard is
   "absent from every surface *loaded during the trial*"). Known non-hit,
   pre-dismissed (gate-check F6):
   the SKILL.md body contains `--fix "stop container, edit, start"` inside
   an ha-note usage example — that names the surgery without the
   reload-doesn't-reread fact, and does not void the fixture.
2. *Provocation:* changed-IP scenario ("HA moved to 192.168.1.x — update
   the integration") + "state your exact plan before touching anything";
   plan-elicitation mode, no live HA action. ≥3 baseline runs, fresh
   sessions, cwd outside the repo but phrased so the home-assistant skill
   activates naturally.
3. *Predicate:* PASS iff the stated plan is stop → edit → start, not
   "reload the integration". Baseline must FAIL ≥2/3; if it unexpectedly
   passes, swap to the registry-write-batching backup (04 §0) and re-run.
4. *Attribution:* `attributionSkill` (did home-assistant activate — if it
   didn't, the trial is void, not a failure), hook output, cwd.

Fixture A needs only its one mechanical pre-routing trial (unguarded
`.storage` edit passes in a sandbox tree) and is **evaluated at M3 exit**.
Its harness (M3-5): a generator in `docs/specs/self-learn/fixtures/`
creates a scratch tree containing `.storage/core.config` and sibling
non-`.storage` files. The **post-routing trial is a live fresh session**
with the compiled guard's snippet actually registered: an Edit attempt on
the `.storage` path must be denied by the hook (and a sibling-file edit
must pass) — stdin-piped JSON fixtures are T17's unit layer and are NOT
acceptance evidence, because only a live session can catch a wrong
matcher or a bad registration path.

## 3. M1 task breakdown (dependency order; each = tests + code + DoD)

Tasks are sized for one implementation agent each. T1–T11 in the worktree;
T12 on main-repo master. Parallelizable groups: {T2,T4} after T1; {T5,T6}
after T2–T4; T12 anytime.

- **T1 · Plugin scaffold + deploy surfaces.** `plugins/self-learn/`
  skeleton per §1 Package pin; marketplace entry; CLI entry point with arg
  parsing + `--selftest` stub; `SELF_LEARN_HOME` resolution; **the
  install.sh commands surface** per the §1 Command-deploy pin (edited in
  this worktree, merged at §6). *Tests:* CLI runs from a symlink; home
  resolution honors the env var; install.sh change is idempotent (re-run
  = no-op) and lint-clean **scoped to the added block** (`shellcheck` if
  available, else `bash -n` — shellcheck is not installed on this machine
  and must not become a sudo detour; the pre-existing script is not held
  to the same bar). *DoD:* `self-learn status` on an empty
  sandbox prints zero-state without error.
- **T2 · Record schema module.** Parse/write/validate records (02 §1–§2):
  frontmatter round-trip, body sections by type, id generation (8 lowercase
  hex), field mutation rules (freeze-at-routing enforced in code paths).
  *Tests:* round-trip byte-stability; illegal mutations raise; two-lesson
  captures rejected (one lesson per record). *DoD:* the 02 §1 example
  parses and re-emits unchanged.
- **T3 · Ledger ops.** Bucket discovery; create; `git mv` resolution;
  defer metadata; supersede links; queue computation (pending minus
  future-`deferred_until`); proposal-sibling read/write/rm. *Tests:* on a
  sandbox git repo — status counts, defer hiding, resolution moves,
  proposal cleanup. *DoD:* 04 exit (d)'s layout/mutation suite green.
- **T4 · Secret-scan module.** Per §1 pin. *Tests:* each rule class
  fires; refusal prints span+rule and writes nothing; `--redact` writes
  redacted body + `redacted: true`; clean text passes; hex record ids and
  git hashes do NOT false-positive. *DoD:* 04 exit (d) refusal-path test
  green.
- **T5 · `teach`.** Flags per 01 §3.2; type inference echoed for
  confirmation; scan-then-write; structured fields → body sections.
  (`--route` wiring deferred to T8.) *Tests:* every flag path lands a
  valid record in the right bucket; malformed input echoes back. *DoD:*
  `self-learn teach "…" --skill home-assistant --type behavior --trigger …
  --instruction …` produces a conforming pending record in the sandbox.
- **T6 · Compilers (SKILL.md / CLAUDE.md / references).** Managed-section
  regeneration from `resolved/` records (trigger-first lines, record ids,
  overflow cap + flag), EOF bootstrap, outside-markers preservation;
  references append; **user-scope chezmoi flow**: `chezmoi diff` guard →
  abort on pre-existing drift or dirty dotfiles repo → edit → `chezmoi
  re-add` → dotfiles commit+push (via PATH shim in tests). *Tests:*
  golden-file regeneration; idempotency (second run = no diff); cap
  behavior; bootstrap on markerless file; hand-edits outside markers
  survive; chezmoi abort paths. *DoD:* all golden tests green; a routed
  record's line appears trigger-first with its id.
- **T7 · Resolution verbs + sentinel + commit/push.** Per §1 pins:
  route/reject/defer/graduate **+ the supersession surface** (`teach
  --supersedes` completion-at-route, bare `supersede <old> <new>`),
  `--note` → `resolution_note` + commit body,
  dirty-target abort, targeted staging, pinned messages, per-verb push
  with rebase-retry, `sentinel hold|heartbeat|release`, self-hold rules,
  `self-learn push`. *Tests:* sandbox repo with bare remote — each verb's
  commit message format; note in body; push retry on simulated non-FF;
  dirty-target abort; sentinel file mtime freshness; verb-created sentinel
  released, pre-existing one left. *DoD:* a scripted
  teach→route(`--dest skill-md`)→push round-trip leaves the sandbox remote
  containing the record in `resolved/`, the compiled section, and one
  commit named `self-learn: route lrn-… → skill-md`.
- **T8 · `teach --route` + one-shot analyst.** Wire T5→T6/T7; bare-terminal
  path spawns `claude -p` with the doctrine file (restricted tools) to
  produce the proposal, then applies. *Tests:* `--route --dest …` end to
  end without any model (deterministic); the analyst path mocked. *DoD:*
  04 exit (a)'s mechanical half (the [protocol] run happens at §6).
- **T9 · Importers.** Backlog: `GOTCHAS.journal.md` parser — journal only,
  per the §1 sources pin (entry boundaries, date
  anchors → `evidence.origin`), already-canon flagging recorded in
  proposal siblings, behavioral-minority card set. Auto-memory: MEMORY.md +
  topic-file parser, content-hash origins, dedupe across **all** statuses,
  S-13 prune sweep (terminal-status records only; edits MEMORY.md +
  memory files; prints what it pruned). *Tests:* fixture corpora (a
  GOTCHAS excerpt + a fake memory dir); idempotent re-run imports zero;
  a rejected record's origin never re-imports; prune sweep refuses
  in-flight records. *DoD:* 04 exit (e) green; exit (b)'s mechanical
  precondition (flag + card-set data) demonstrable on the fixture corpus.
- **T10 · Slash commands + doctrine file.** `commands/teach.md` (O-4
  extraction UX: compose trigger/instruction/evidence from the session,
  call the CLI), `commands/review.md` (bounded batch, four-option cards
  per E-16, bulk-acknowledge multiSelect, inline analysis **writing
  proposal siblings** before presenting, verbs for every action,
  end-of-session summary + push retry, batch sentinel hold/release
  *(G-3 amendment 2026-07-12/P2-1: a Discuss-path edit of the pending
  record ends by calling `self-learn proposal validate <id>` — §7.1's
  scan+stamp enforcement point for writes that bypass CLI verbs; a scan
  hit blocks the card until redacted)*),
  `references/routing-doctrine.md`. *Tests:* these are prompt files —
  verify by checklist against 07 §4's six contracts (esp. #1: no routing
  mechanics in the prompt) + a dry-run transcript. *DoD:* checklist
  signed off in the task log.
- **T11 · `--selftest` + SKILL.md + install docs.** Selftest: capture
  path, compiler dry-run, marker check per 02 §4, sentinel writability;
  worker check stubbed M2-conditional. Plugin SKILL.md + README document:
  install.sh run, the S-15 offer-line chezmoi edit (exact §1 text), the
  fact that M2's SessionStart hook needs manual settings.json
  registration later. *DoD:* selftest green in sandbox, loud on a
  sabotaged marker.
- **T12 · Main-repo sentinel check (master).** In
  `~/repos/claude-skills/bin/claude-skills-sync`, immediately after
  `cd "$REPO"`: if `~/.cache/claude-skills/self-learn/autosync-pause`
  exists and mtime < 2 h → log one line + `exit 0`. (The watcher needs no
  change — it only calls sync. Manual sync runs inherit the check too.)
  Include its test (shell test: fresh sentinel → no commit; stale → sync
  proceeds; the repo has no harness, so add `tests/sentinel-test.sh`
  runnable standalone). *DoD:* test passes; change committed on master
  with a descriptive message (autosync will push it — that's fine, it's
  an additive guard).

## 4. Judgment calls that stay routed (never absorbed by a sub-agent)

| Call | Who decides | Mechanism |
|---|---|---|
| Destination for a lesson (incl. hook-vs-SKILL.md) | Analyst proposes (strong model), human decides | Proposal + card; `--dest` override |
| Already-canon equivalence beyond the pinned criterion | Importing session flags; human de-selects on the bulk card | Wrong flag = one card, cheap |
| Cluster "same lesson" merges | Worker proposes (M2); human collapses | Merge proposals only |
| O-6 offer significance | Session model, bounded by the pinned filter words | Revocable one line |
| Secret-scan gray zones | Human (`--redact` or rephrase; no bypass exists) | Refusal message |
| Reject-vs-route, graduation timing | Human, by design | Review cards |
| Fixture provocation authoring, and B failing to qualify | Human + strong reasoner | §2 escalation |
| Any corpus contradiction or settled-decision pressure | Human | §0 rule 5 |
| Cluster survivor choice (M2) | Worker nominates (`suggested_survivor`); human confirms/overrides on the collapse card | 02 §1, §7.1 |
| Guard predicate scope — deliberate over-blocking (M3) | A deterministic guard often over-blocks its conditional rule (fixture A's path-only guard denies legitimate stopped-container edits too). The analyst must state the over-block explicitly in the rationale; the human accepts or narrows it on the card — never decided silently by the builder | §8.1 |
| Guard allow/deny test-case authoring (M3) | Analyst authors 2–3 allow + 2–3 deny examples per hook proposal; route replays them pre-commit, failures abort | §8.1 replay pin |
| Live-guard false positive — disable now vs supersede (M3) | Human: hand-remove the settings.json entry for immediate relief; supersede for the durable correction | §8.1 rollback pin, §5 |
| Worker prompt quality tuning (excerpt selection, digest phrasing, clustering sensitivity — incl. exit (b) retries) | Human + strong reasoner, never the T13 implementer | §7.3 (b) |
| Worker model default (cost vs proposal quality) | User — the pin carries `claude-sonnet-5` as a starting point, the trade is theirs | §7.1 |
| Escalation cadence calibration (first week of real use) | User | §7.1 thresholds pin |

## 5. Eventuality playbooks

- **Push fails (any verb):** loud message, commit stays local, `self-learn
  push` retries; review-end summary retries automatically. Never silent.
- **Rebase conflict during a verb's push-retry:** abort the rebase, stop,
  tell the user (mirror of `claude-skills-sync`'s own policy — never
  auto-resolve).
- **Chezmoi drift or dirty dotfiles repo at user-scope route:** abort that
  route with the message "fix drift / commit dotfiles first, or route to
  project scope"; the record stays pending. Never `re-add` over drift.
- **Scan false-positive on a legitimate capture:** rephrase the quote or
  use `--redact`; there is deliberately no bypass in v1.
- **Crash mid-route:** states are recoverable — compiled-but-uncommitted
  (working tree dirty: re-run `route <id>`, regeneration is idempotent);
  committed-but-unpushed (`self-learn push`). The sentinel goes stale
  within 2 h and autosync resumes on its own.
- **Sentinel left behind:** ignored once stale (mtime ≥ 2 h); either side
  may delete it. A >2 h silent Discuss tangent loses the pause —
  acceptable: between-cards autosync commits capture complete
  record-per-file states, and every apply re-holds; the hazard window
  (mid-apply) is always verb-wrapped.
- **Hand-edit inside managed markers:** the next regeneration overwrites
  it — by contract (02 §4). The marker comment says so; `--selftest` need
  not detect it.
- **Two machines reviewing/routing at once:** operating discipline says
  don't; if it happens, autosync's rebase-halt + `notify-send` is the
  degradation (01 §5). Review self-push means the next host starts
  current.
- **home-network capture commits mid-review (the accepted residual):** its
  targeted `git add` can't sweep `.self-learn` state; worst case its
  non-FF push fails, which those prompts already tolerate. If this ever
  bites in practice, the fix is routing its commit through
  `claude-skills-sync` — recorded here so nobody re-diagnoses it.
- **Auto-memory dir format shifts mid-M1:** invoke S-14's fallback — slip
  the importer to v1.1, note it in 03, continue; do not chase a moving
  format inside M1.
- **A routed guard blocks legitimate work (M3):** immediate relief =
  hand-remove its settings.json entry (the hook is inert without it);
  durable correction = supersede the record (which `git rm`s the script
  per the §8.1 rollback pin) — never hand-edit the generated script,
  which would drift from its record.

## 6. M1 acceptance & merge procedure

1. Full automated suite green in the worktree ([auto] criteria c, d, e).
2. Merge worktree → master per repo convention; run `./install.sh`
   (idempotent) on this machine; verify: `~/bin/self-learn` symlink,
   skill symlink, `~/.claude/commands/self-learn` symlink, and the review
   command visible in a fresh session — expected `/self-learn:review`;
   if colon-namespacing doesn't materialize, apply the §1 Command-deploy
   fallback (flat names) and record which form landed; sweep
   `~/.claude/hooks/` for dangling symlinks (repo doctrine).
3. Apply the offer-line chezmoi edit (documented install step).
4. [protocol] runs with the user: exit (a) one-motion `teach --route` on
   home-assistant; exit (b) the real backlog-import review session (this
   is also the E-3 honeymoon test — schedule it when the user has ~30
   minutes).
5. *(COMPLETE 2026-07-15: B-half proven 3/3 (2026-07-14); C-half re-scoped
   away by the user's boundary call — 04 §0 banner. **All §6 criteria are
   now satisfied: M1 EXITED 2026-07-15. M2 (§7) is unblocked**, with T13's
   scope extended by 11's worker riders.)* Route fixtures B and C through the system (their records via `teach`),
   then run the §0 post-routing trials — 3/3 each against the written
   predicates, attribution recorded per trial (B also proves the E-17
   chezmoi persistence check: `chezmoi apply` then re-grep). **B and C
   pass = the M1+M2 behavioral checkpoint is pre-armed** (final call at
   the M1+M2 boundary per 04 §0; A waits for M3).
6. Update the corpus README revision log; update project memory and the
   znote hub with the milestone state.

## 7. M2 execution plan (worker + surfacing)

*Detailed 2026-07-12 for the phased implementability gate. Same operating
rules (§0), same escalation routing (§4). M2 starts only after M1 exits
(§6).*

### 7.1 M2 pins (extends the §1 table)

*(Hardened 2026-07-12 after the phase-2 implementability review — gates
M2-1…M2-5 and minors folded.)*

| Contract | Pin |
|---|---|
| Worker trigger + coalesce mechanics | Kick-driven, not scheduled — no systemd unit, no cron (E-5). `teach` (without `--route`) and `import` end by calling `self-learn worker kick`: (1) `touch worker.dirty`; (2) under `flock -n worker.spawn.lock` (two racing kicks serialize; the loser exits absorbed): if `worker.window` names a **live** pid → exit (open window absorbs the kick); else `setsid`-spawn `self-learn worker run --coalesce`, writing the child pid to `worker.window`. A dead pid in `worker.window` = closed window (reboot/kill safe). `--coalesce` sleeps `SELF_LEARN_COALESCE_SECS` (default **600**; tests set ~0), then takes `worker.lock` (blocking), removes `worker.window`, and runs. `worker.dirty` is deleted **after** enumeration, so a kick landing mid-run re-marks it; at run end, if `worker.dirty` exists again → one follow-on window is spawned. All state files under `~/.cache/claude-skills/self-learn/` |
| Worker run sequence | (1) sync first — **only** if `SELF_LEARN_HOME` is the real claude-skills repo and `bin/claude-skills-sync` exists there (tests PATH-shim it; absence = log + skip); (2) enumerate: pending records, **excluding future-`deferred_until`** (same queue computation as `list`), lacking a schema-valid proposal or whose current normalized-body hash ≠ proposal `record_sha` (**content identity, never mtime** — git checkouts rewrite mtimes; unparseable proposal = missing); **batch cap 15, oldest first** — leftovers keep `worker.dirty` set for a follow-on window; (3) one `timeout 15m claude -p` invocation covering the batch + cluster pass; (4) validate every proposal file written: schema-invalid files are deleted + logged; (5) re-check each proposed id is *still pending* (drop resolved ones from the event) and sweep orphan proposals (no matching pending record → `git rm`); (6) run "succeeded" iff ≥1 valid proposal landed or nothing was eligible — only then touch `worker.last-run`; partial success (3 of 5 valid) succeeds and notifies for the valid ids only; (7) emit the event + notification |
| Worker `claude -p` invocation | **Literal flag set, verified against the live CLI at T13 start** (syntax may need adjusting to what the CLI actually accepts — the *property* is the pin): `--allowedTools "Read,Grep,Glob,Write(<HOME>/plugins/**/.self-learn/proposals/**),Write(<HOME>/.self-learn/proposals/**)"` where `<HOME>` = resolved `SELF_LEARN_HOME`. **No `Bash`, no `Edit` — ever**: with shell access the write restriction is void (do NOT copy home-net-capture's `--allowed-tools` line, which grants Bash; the append-only guarantee IS this flag, E-18). Two tests: the constructed-invocation assertion (cheap), plus the §7.3 live refusal check (real). Model: `SELF_LEARN_WORKER_MODEL`, default **`claude-sonnet-5`** (verified once at T13 start with `claude --model claude-sonnet-5 -p 'ok'`; proposals are human-gated — cost beats brilliance; changing the default is the user's call, §4). Prompt = `routing-doctrine.md` + rejected digest + record bodies + target-canon excerpts (= the candidate target's managed section ± 20 lines, or the whole file when < 200 lines). Output = proposal/merge YAML per 02 §1 — **the model does NOT emit `record_sha`** (models cannot compute hashes; M2-21): the **CLI computes and stamps** `record_sha`/`record_shas` into every proposal file during run-sequence step (4) validation, overwriting anything the model wrote; the M1 inline-analysis path stamps through the same code path; hash-absent (M1-era) proposals read as stale and self-heal. "Normalized" = the same normalization function as 02 §2's `evidence.origin` content hash — one definition, two uses |
| Rejected-proposal digest | Built by the CLI (not the model) from the last **20** rejected records in `resolved/`, ordered by **resolving-commit author date, newest first** (`git log --grep "self-learn: reject"`): id, title line, `resolution_note` if present, commit subject. Injected as negative exemplars ("never re-propose these classes") |
| Merge proposals + collapse surface | Schema in 02 §1 (`merge-<8hex>`, same-bucket-only, `suggested_survivor`, `record_shas`; invalidated when any member resolves). Collapse is a **CLI verb extension, never slash-command logic** (07 §4 contract 1): `route <survivor-id> --collapse <cluster-id> [--dest …] [--note …]` — in one commit: appends the losers' `evidence` provenance to the survivor, sets `sightings`, routes the survivor, marks losers `superseded_by: <survivor-id>` + moves them to `resolved/`, `git rm`s the merge proposal and the losers' analysis proposals. Commit message: `self-learn: route lrn-X → <target> (collapse merge-<cid>, supersedes lrn-Y, lrn-Z)` |
| Multi-machine honesty note | Two machines' workers CAN both write `proposals/lrn-<id>.yaml` before syncing (01 §3.3's "never collide" holds for *distinct* records only). The run-starts-with-sync step narrows the window; a residual add/add degrades to autosync's standard safe rebase-halt (01 §5) — accepted, same as every other cross-machine collision in the design |
| Event log (the deep-link contract's durable half) | Every worker run with ≥1 valid new proposal appends one JSON line to `~/.cache/claude-skills/self-learn/events.jsonl`: `{ts: <iso8601>, event: "proposals"\|"escalation", record_ids: […], aggregate: {pending: <n>, buckets: [{bucket, pending}…]}}`. Escalations append their own `event: "escalation"` line (empty `record_ids`) alongside the `notify-send` — the enum has a writer (M2-25). Machine-local by nature — ids from other machines' runs never appear here; the ledger is the recovery path. Size-capped: truncate oldest lines past ~1 MB (same for `worker.log`). Re-analysis of an edited record **does** count as a new-proposal event (revocable one-liner if it proves noisy). `notify-send` renders only the human line; the events file is what the G-3 TUI deep-links from (07 §4 contract 3) |
| Notification rendering | Template, pinned: `self-learn: {n} new proposal{s} for {bucket-list}. {total} pending across {k} scope{s} — /self-learn:review` — scopes = distinct buckets with ≥1 pending; deferred records excluded from all counts (02 §2). Delivery uses the sync script's own `note()` pattern: `command -v notify-send && notify-send … \|\| echo … >&2`; **notification failure never fails a run** (headless/SSH has no DBus). *(G-3 pointer, 2026-07-12 — 09 §3: when the G-3 surface lands, this emission point swaps to the detached helper `setsid self-learn-notify …`, which adds a click action (`notify-send -A open --wait`, blocking in its own detached process) deep-linking via `self-learn-ui-open --record <id>` — launcher name per the same-day platform re-decision, 09-surface-spec.md §3; it opens the record's URL in the dedicated app window. Template, payload, and the events.jsonl line are unchanged; hosts without an action-capable daemon degrade to exactly this M2 behavior. Until the surface ships, nothing changes.)* |
| Threshold escalation | Owned by **worker-run end only**: ≥5 pending or oldest >7 days → one escalation `notify-send`, debounced to once per 24 h via a `~/.cache` last-escalated marker. The SessionStart hook **prints** the escalation line into session context but never calls `notify-send` (multiple daily session starts would be S-9's popup treadmill). Thresholds are v1 constants — changing them is an edit to this pin, not a config file (no config surface exists in v1 beyond the two env vars) |
| SessionStart hook | `plugins/self-learn/hooks/self-learn-pending.sh` → `~/.claude/hooks/` via install.sh's existing hooks surface; **manual settings.json registration, documented** (repo doctrine). Prints the pending line ("📥 self-learn: 7 pending, oldest 9d — /self-learn:review") + staleness + escalation lines. Implementation: calls **`self-learn status --json --fast`** — a guaranteed-cheap CLI path (frontmatter-only scan of `pending/`, no git, no network; budget < 500 ms warm). **Queue semantics are never reimplemented in bash** — one computation, owned by the CLI |
| Staleness alarm predicate | Fires iff (≥1 pending record lacks a valid proposal) AND (`worker.last-run` mtime > **3 days** old **or the file is missing** — missing = infinitely old, so a fresh install with un-analyzed synced records alarms rather than hiding a wedge). Quiet queues with no un-analyzed supply never alarm |
| Review fast path | `/self-learn:review` uses an existing schema-valid proposal whose `record_sha` matches as-is (one-tap); falls back to M1 inline analysis when the proposal is missing, invalid, or hash-stale — the M1 path is kept, not replaced |
| `status --json` amendment | `worker_last_run` becomes `<iso8601>\|null` (null = never ran on this machine) |
| Proposal validate verb *(G-3 amendment, 2026-07-12 — 09 §4.3/P1-3; scan scope added same day — P2-1)* | `self-learn proposal validate <id>` — for one record: (1) validates the proposal sibling(s) and **stamps `record_sha`** via the same code path as run-sequence step (4), with one pinned divergence: on schema-invalid input it **reports (exit non-zero + reason) and never deletes** — delete-on-invalid is unattended-worker-output policy; this verb serves *attended* iteration and the file is work-in-progress, not litter; (2) **runs the §1 secret scan over the record body and all proposal siblings** (incl. `rationale`/`already_canon_reason` free text) — scan hit ⇒ report matched span + rule, exit non-zero, never delete and never auto-redact (redaction is the human's move, via Iterate or `--redact`-bearing surfaces). This makes the verb **the S-8 rider's enforcement point for agent-mediated edits outside the CLI**: the G-3 pane calls it at session end (09 §4.3), and the slash review's Discuss-edit path calls it at card completion (T10) — closing the previously unenforced direct-`Edit` write path in both surfaces (02 §2's every-write claim now has a mechanism wherever writes bypass CLI verbs). Stamps in place; **commits nothing** (proposals/records are working files pre-resolution; resolution verbs own commits — same posture as the worker's own writes). **Exit codes pinned (P2-8 — the TUI distinguishes outcomes without parsing prose, 07 §4 contract 2): 0 = valid + scan-clean (stamped) · 1 = schema-invalid · 2 = scan hit (wins when both apply)**. Built T11 (pulled forward — appendix 2026-07-13); T13 extends alongside the worker's validation internals; T13's tests gain four cases (valid+clean → 0 stamped; schema-invalid → 1, file intact; scan-hit in record body → 2 + span report; both → 2) — 09 §4.3 | 

### 7.2 M2 tasks

- **T13 · Worker.** `worker kick|run` per the pins (spawn-lock, window
  pidfile with liveness, dirty-marker lifecycle, batch cap, timeout,
  output validation, orphan sweep, mid-run-resolution re-check); digest
  builder; content-hash staleness; the `proposal validate <id>` verb
  (§7.1 G-3 amendment pin — report-never-delete); `worker.last-run`; failure logging to
  `~/.cache/claude-skills/self-learn/worker.log` (a failed run — zero
  valid proposals with eligible records — does NOT touch last-run; the
  alarm is the detector). *Tests:* PATH-shimmed fake `claude` (records
  argv; asserts the literal `--allowedTools` value and absence of
  Bash/Edit; prompt composition) and PATH-shimmed `claude-skills-sync`;
  two racing kicks spawn one window; dead-pid window reopens; kick
  mid-run re-marks dirty and triggers a follow-on; malformed-YAML output
  deleted + run fails; partial output (3/5 valid) succeeds, notifies 3;
  hash-unchanged records skipped, edited record re-analyzed, git-checkout
  mtime change alone does NOT re-analyze; deferred records skipped;
  orphan proposal swept; digest content + ordering from a fixture
  `resolved/` set. *DoD:* on a sandbox ledger, `teach` → kick →
  (shimmed) run → valid proposal sibling appears, events.jsonl line
  appended with the pinned schema, last-run touched.
- **T14 · Notifications.** events.jsonl writer + `notify-send` rendering
  (**the §7.1 Notification-rendering pin's template is the format
  source** — 01 §3.6's sentence is illustrative only) + threshold
  escalation. *Tests:*
  event-line schema; aggregate math (N pending across M scopes); escalation
  fires at the pinned thresholds, once per run, debounced 24 h. *DoD:*
  fixture run emits the §7.1 template string verbatim.
- **T15 · SessionStart hook.** Per the pin; plus the settings.json snippet
  + registration doc in the plugin README. *Tests:* output format; <500 ms
  warm on a 100-record fixture (the `status --json --fast` budget — the
  hook adds no logic of its own); staleness predicate truth table
  (**5 cases**, incl. missing `worker.last-run`).
  *DoD:* hook script green + install doc updated; registration itself is
  a documented manual step (§4 routes it to the human).
- **T16 · Review fast path + collapse verb.** The `route … --collapse
  <cluster-id>` CLI extension per the §7.1 pin (all collapse mechanics in
  the verb — the review card only invokes it; 07 §4 contract 1); review
  consumes fresh valid proposals one-tap; merge-proposal cards (cluster →
  single card; survivor pre-selected from `suggested_survivor`,
  overridable). *Tests:* collapse on a fixture cluster — one commit,
  survivor routed with merged evidence + `sightings`, losers
  `superseded_by: <survivor-id>` in `resolved/`, merge + loser proposals
  `git rm`'d, pinned commit-message shape; invalidated-cluster handling
  (member resolved first → merge proposal swept, card never shown);
  hash-stale and unparseable proposal fallback to inline. *DoD:* 04-M2
  exit (b)'s mechanical half green **and the 07 §4 contract checklist
  re-run over the M2 additions** (contract 1 especially).

### 7.3 M2 acceptance (04-M2 exit criteria, tagged)

(a) [auto, shimmed] taught lesson gains a proposal within one worker
cycle, no session involved; (a′) [protocol] **real-worker smoke** — one
un-shimmed run against ≥1 real record produces schema-valid YAML that
`route` consumes end-to-end, **and** a live refusal check: a real
`claude -p` run under the pinned `--allowedTools`, instructed to write
outside `proposals/`, is refused (this is the only test that can catch a
flag syntax that doesn't do what's believed — the constructed-string
assertion cannot); (b) [auto + protocol] planted near-duplicate
pair → merge proposal → next review collapses to one routed survivor +
one superseded record with `sightings: 2` — the worker gets **≤3 runs
with prompt tuning between attempts** to emit the merge proposal; still
none → escalate per §0 rule 5 (clustering sensitivity is a §4 tuning
call, not a build defect); (c) [auto, clock-mocked]
killed worker trips the staleness alarm at the pinned predicate;
(d) [protocol] 10-item triage in <~5 min on card taps alone, seeded from
the smoke run's ledger state. Plus:
fixtures **B and C final call at this M1+M2 checkpoint** (04 §0 staging;
§6.5 pre-armed them at M1 exit). After acceptance: register the
SessionStart hook (manual), update README/memory/hub.

## 8. M3 execution plan (remaining compilers + supply review)

*Detailed 2026-07-12 for the phased implementability gate. Same operating
rules (§0), same escalation routing (§4). M3 starts only after M2's
acceptance (§7.3).*

### 8.1 M3 pins (extends §1/§7.1)

| Contract | Pin |
|---|---|
| Hook compiler output | `route <id> --dest hook` scaffolds the guard script (bash, shebang'd, executable) + prints the `settings.json` registration snippet. Script path: skill-scoped records → `plugins/<p>/hooks/`, project/user-scoped → `plugins/self-learn/hooks/` (M3-7). Filename: `self-learn-<8hex-id>-<slug>.sh` — id **without** the `lrn-` prefix; slug = kebab-case of the first ≤4 Trigger words, `[a-z0-9-]`, ≤32 chars (M3-6). **Never auto-registers** (repo doctrine: settings.json is manual). The in-repo precedent to copy is `universal-directory-organizer`'s fail-closed PreToolUse guard, NOT a fresh invention. **Snippet template, literal** (M3-1 — ground-truthed against the live settings.json): `"PreToolUse": [{"matcher": "Edit\|Write", "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/self-learn-<id>-<slug>.sh"}]}]` — **the matcher is the TOOL-NAME set only** — concretely, the guard's `hook.tools` list joined with `\|` (the template shows the typical Edit/Write case; M3-14) — **the path regex lives exclusively in-script** (a path regex in the matcher field never fires) |
| Generated guard shape | PreToolUse protocol (ground-truthed against `organizer-guard.sh`): read the hook JSON from stdin; decide on `tool_name` ∈ the pinned set plus a **path regex applied to the named `tool_input` field — `Edit`/`Write` → `.tool_input.file_path`, `Bash` → `.tool_input.command`** (M3-8; never regex the raw JSON blob); deny = exit 2 with a one-line stderr message citing the rule and the record id (`self-learn lrn-…: <instruction>`); allow = exit 0; malformed stdin fails closed (ERR-trap, precedent's pattern). Deriving the regex from Trigger prose is a §4 judgment (analyst proposes, human reads the actual regex) |
| Hook apply convention — **deliberate exception to regenerate-at-apply** (M3-2) | For `--dest hook` the proposal carries the **structured compile input** — `hook: {tools: […], path_regex: "…", deny_message: "…"}` and the full generated script text — and the route verb applies that content **verbatim, byte-identical to what the human approved** (P9: eyes on the exact executable diff). A `record_sha` mismatch at apply time **aborts and forces re-analysis + fresh approval — never silent regeneration**. This is the one documented exception to 01 §3.4's regenerate-at-apply rule, and it exists because the compile input lives in the proposal, not the frozen record |
| Guard test replay (M3-12) | The hook proposal also carries 2–3 **allow** and 2–3 **deny** example inputs (analyst-authored); `route --dest hook` replays them against the generated script **before committing** — any mismatch aborts the route. T17 tests the replay machinery; the per-guard cases ride each proposal |
| Hook approval flow | The route card/verb shows the entire generated script as the diff (not a summary). Approval routes the record and commits the script; the settings.json snippet is printed and logged in the commit body; **the verb ends by printing the required manual steps: run `./install.sh` (the symlink materializes only then) and add the snippet to settings.json** (M3-11) — until both, the hook is inert by design |
| Hook correction/rollback (M3-4) | Superseding or graduating a hook-routed record **`git rm`s the script in its own pinned host commit** (`… (hook removed)`) — post-doc-13 the ledger and host are separate repos, so "same commit" is impossible; the ledger resolution commits first, then the host removal (two-phase, interruption flagged by `--selftest` as incomplete supersession) — and prints an un-registration reminder for the settings.json entry + the dead `~/.claude/hooks/` symlink. Immediate disable (guard blocking legitimate work right now) = remove the settings.json entry by hand; durable correction = supersede (§5 playbook). S-12's "supersede + recompile" for hooks means: script removed, registration manually retired — there is no section to regenerate |
| Hook selftest | `--selftest` (M3 extension): each **currently-routed** (not superseded/graduated) hook record's script exists and is executable; any `settings.json` registration referencing a `self-learn-*` hook whose script or symlink is missing is flagged (the inverse case — script present for a superseded record — is also flagged, as an incomplete supersession). Read-only checks; loud on failure |
| New-skill compiler | `route <id> --dest new-skill:<name>` (the name slot is the confirmed §4 human call) creates a **deterministic minimal scaffold** with the CLI's own template — `plugins/<name>/.claude-plugin/plugin.json` (`name`, `version: "0.1.0"`, `description` — the key set the repo's real manifests share), `skills/<name>/SKILL.md` (frontmatter + a managed section containing the routed lesson(s)) — and appends a marketplace.json entry shaped like the repo's existing entries. **Collision rule (M3-9):** if `plugins/<name>` already exists, append the lesson only when its SKILL.md carries a self-learn managed section (i.e., it was self-learn-scaffolded); otherwise **refuse** — never inject into a foreign authored SKILL.md. The route ends by printing "run `./install.sh`" (M3-11). No dependency on the plugin-dev plugin for the substrate; post-hoc enrichment is a normal session activity where plugin-dev *may* be used |
| One-motion policy config *(S-10 amendment 2026-07-16 — user ruling: "shouldn't be hard-coded. make it configurable")* | `<ledger-home>/config.yaml`, key `one_motion_route: {hook: <bool>, new-skill: <bool>}` — a COMMITTED operator opt-in (deliberately not hosts.yaml, whose contract distrusts hand edits, and deliberately not an env var: what executable code may auto-commit belongs in git history). Fail-closed parse: only the YAML boolean `true` enables; missing/malformed/false/strings refuse, malformed shapes warn on stderr. Default = the review-gated refusal, message unchanged. Enabled hook path (`teach --route --dest hook --hook-input <yaml>`, or the analyst's hook proposal on a bare `--route`): the CLI generates the script (caller `script` ignored — M2-21 for executables), validates the §5.1 schema, secret-scans the whole compile input, replays the examples PRE-commit, prints the applied bytes in full, and ends with the M3-11 manual steps — settings.json registration stays manual, so activation is human regardless. Per-destination gates independent | 03 S-10 |
| Statusline count | Optional, default OFF; if the user asks: a statusline script calling `status --json --fast`, budget rules same as the SessionStart hook. Not part of M3 acceptance |
| O-3 / O-7 revisit | [protocol] with the user, data-driven: `status --json` gains a `supply_mix` block (counts of resolved+pending by `source`) — the O-3 input 04's metrics name. The revisit is a conversation, not a build task; its outcome lands as dated register edits in 03 |

### 8.2 M3 tasks

- **T17 · Hook compiler.** Per the pins: scaffold generator, snippet
  printer, approval-diff flow through the existing `route` machinery,
  selftest extension. *Tests:* generated script against stdin fixtures
  (denied call exits 2 with the pinned message shape; allowed call exits
  0; malformed stdin fails closed); scaffold placement + executability;
  snippet content; selftest catches a deleted script and a
  registration pointing at a missing path. *DoD:* a fixture anti-pattern
  record routes to a working guard in a sandbox tree.
- **T18 · New-skill compiler.** Template scaffold + marketplace append
  (idempotent — re-route to the same self-learn-scaffolded skill must not
  duplicate the entry; foreign-plugin collision refuses per the §8.1
  pin). *Tests:* both JSON files parse; `plugins/<name>/skills/<name>/
  SKILL.md` exists with well-formed frontmatter + managed section;
  marketplace `.plugins[].name` contains the entry exactly once —
  **these are the only structural facts install.sh actually consumes**
  (its discovery is marketplace names + the skills path glob; it runs no
  manifest validation — don't invent checks it doesn't perform);
  collision refusal on a fixture foreign plugin. *DoD:* scaffolded
  plugin symlinks correctly on a real `./install.sh` run at §8.3.
- **T19 · `supply_mix` in status + metrics counters.** The counted-not-
  modeled numbers 04 §Success-metrics names: time-to-triage, queue
  health, routed-and-corrected (excluding `superseded_by: canon`),
  supply mix. All computed from the ledger + git on demand — no state
  files. *Tests:* fixture ledger → known counts; canon-graduations
  excluded from the corrected metric. *DoD:* `status --json` carries the
  block; numbers match the fixture by hand-count.
- **T20 · O-3/O-7 revisit + fixture A.** [protocol] — schedule with the
  user once a month of real supply exists; fixture A's post-routing
  trial per §2/04 §0: route the `.storage` record through T17's
  compiler, **run `./install.sh`** (the symlink exists only then),
  register the snippet manually, then the **live fresh-session trial per
  §2's fixture-A harness** (denied on `.storage`, allowed on a sibling;
  pre-routing pass already recorded in Phase 0).

### 8.3 M3 acceptance (04-M3 exit, tagged)

[protocol] One real anti-pattern lesson routed end-to-end into a working,
manually-registered PreToolUse hook through the explicit-approval flow —
**this is acceptance fixture A**, scored against §2's mechanical
predicate (unguarded pass before routing — recorded in Phase 0 — guard
denies after). [auto] T17/T18/T19 suites green. Then: v1.1 declared,
metrics collection begins (04 §Success-metrics), O-3/O-7 revisit
scheduled, README/memory/hub updated. TUI work (G-3) remains gated on
its own trigger and its own blind review — explicitly out of this plan's
scope.

## 9. Change control

- Pins in §1 change only with a dated edit here + a pointer from the
  corpus doc that co-owns them; if a pin change would alter a settled
  decision's inputs, the 03 register reopens first (P10).
- New gaps found during the build get a dated **Build findings** appendix
  entry here (finding → disposition), so the next agent inherits answers,
  not archaeology.
- This plan is complete when M1 exits; M2 execution planning extends this
  file (same structure) rather than starting a new one.

## Appendix — Build findings (dated; §9 discipline)

- **2026-07-13 · Phase 0: both fixtures failed to qualify** — baselines
  passed 3/3 each on claude-fable-5 (B: grep-before-sed + post-verify is
  baseline-native; C: the loaded SKILL.md body itself teaches the
  stop→edit→start surgery — the original absence proof covered the
  causal fact, not the predicate behavior). Disposition (user-decided):
  B → probe for a genuinely baseline-failing, environment-specific
  lesson; C → backup swap under a **hardened gate**: the absence proof
  must cover the PREDICATE BEHAVIOR across every loaded surface. The
  hardened gate then also disqualified the named C backup
  (registry-write-batching) pre-trial — same flaw class. Fixture
  selection principle recorded: on a frontier model, delta-provable
  fixtures are environment-specific/arbitrary-convention lessons, not
  general good practice. Evidence: `fixtures/trials.md`.
- **2026-07-13 · `proposal validate` pulled forward T13 → T11** — T10's
  review prompt calls it at Discuss-edit completion and every
  ingredient (validate/stamp/scan) existed at M1; T13 extends rather
  than builds it. Pinned semantics unchanged (§7.1 row).
- **2026-07-13 · Canonical test invocation** — `cd plugins/self-learn/cli
  && uv run pytest -q`. From the repo root, pytest collects other uv
  projects' suites (cron-claude) and fails on their imports; §6.1's
  "full automated suite" means the cli-project invocation.
- **2026-07-13 · T7 route ordering** — compile-before-ledger-op (the
  §3 T7 letter order (d)→(e) is impossible literally: the proposal must
  be read before resolution deletes it), which also makes the §5
  chezmoi/crash playbooks literally true. Crash between compile and
  ledger op = re-run route, idempotent.
- **2026-07-13 · `--dest reference:<file>`** — the "another existing
  references file" case (References pin) is expressed as a dest
  qualifier since the proposal enum stays 02 §1-strict; M3's
  `new-skill:<name>` will extend the same validator.
- **2026-07-13 · Missing compile target** — SKILL.md/named references
  targets REFUSE when absent (broken skill); `<home>/CLAUDE.md` is
  created empty + bootstrapped on first claude-md route (a repo without
  a CLAUDE.md is not an error).
- **2026-07-13 · Analyst invocation (T8)** — doctrine text via
  `--append-system-prompt`, `--allowedTools Read,Grep,Glob`, model
  `SELF_LEARN_ANALYST_MODEL` (default claude-sonnet-5), timeout
  `SELF_LEARN_ANALYST_TIMEOUT` (120 s); analyst/deterministic-path
  failures capture the record to `pending/` (never lost), exit 4.
  Literal flag syntax re-verified at T13 alongside the worker's.
- **2026-07-13 · teach behavior-kind default** — `surface-rule`,
  echoed with override hint (a kind is schema-required and the DoD
  invocation carries none).
- **2026-07-14 · Decision-support contract (card sections)** — first
  real review session revised E-3's honeymoon verdict: throughput pass,
  comprehension fail (machine-led cards → rubber-stamp approvals).
  Landed same day: 02 §1 optional `card:` map (shape-checked by
  `validate_proposal`, both proposal kinds; scan coverage was already
  whole-file); routing-doctrine §8 register rules; `card-sections.yaml`
  registry = single source of the section set AND each section's
  generation prompt — surfaces render generically, so section evolution
  is a registry-only edit. **T13 consequence:** the worker loads the
  registry and emits `card:` per proposal; required-section strictness
  in the validator is decided there (M1 leaves it analyst discipline).
  The user's venue verdict (REPL definitively wrong for review) is
  logged as G-3 trigger evidence; the surface build stays gated on M2.
- **2026-07-14 · Telemetry/lifecycle layer PROPOSED** — see
  `11-telemetry-and-lifecycle.md` (follow-ups, recurrences, telemetry
  plane, index/report). Its "now" tranche (§7) is M1-era small builds;
  its worker riders (fire mining, recurrence matching, not-holding
  cards) bind T13's scope when ratified. M3 gains a pinned first step:
  drain the follow-up list.
- **2026-07-14 · Audit-batch pin amendments (four-agent system audit)** —
  (1) **CLI usage errors exit 64** (EX_USAGE), never 2: P2-8's scan-hit
  code is no longer aliased by unknown-id/bad-flag paths (argparse's own
  flag-error 2 remains argparse-owned; teach's documented exit table
  unchanged). (2) **Compiler keeps the whole first line** — the
  first-sentence cut silently dropped doctrine §6's "why"; goldens
  updated, §6 now says "on a single line". (3) **Heartbeat covers every
  mutating invocation** — teach/import/prune-memory/proposal dispatch
  now touch a live sentinel. (4) **Over-cap flag has a consumer** —
  route/teach --route print the graduation-card WARNING; review.md opens
  the next batch with the card. All landed ff159a6, 377 tests.
- **2026-07-15 · 11's now-tranche LANDED (pre-T13, per 11 §7)** — the
  telemetry/lifecycle layer's M1-era builds, in the order 11 pins:
  (1) §3 schema fields + validator (capture-time grounding, follow-ups,
  recurrences, last_confirmed, contradicts — all optional, metadata
  class); (2) `route --follow-up [--unblocks-on --follow-up-note]` +
  `followup done` (pinned commit subject; done-notes live in
  `follow_up_done.done_note`, never `resolution_note`); (3) telemetry
  spool library + `telemetry note` (NOTE_KINDS = the two offer kinds
  only; reason enum enforced) + flush-in-verbs
  (teach/import/resolutions/report) + scan-at-flush (whole-flush
  refusal, spool intact; flush truncates in place so a concurrent
  appender can never write into a deleted inode); (4) code-emitted
  `capture` events from teach (both paths) and import; (5) `report` v1
  file-walking (11 §5's sanctioned pre-index divergence) with the
  honesty labels pinned: declined-count = LOWER bound, capture rate =
  optimistic CEILING, no-observed-fires = candidates-not-dead-weight;
  (6) `status` gains `open_followups` on the FULL paths only — the
  §7.1 `--json --fast` pin is untouched. S-15 pin edit applied (§1 row,
  plugin README, live `~/.claude/CLAUDE.md` via the chezmoi flow).
  Build decisions recorded: `teach --route` does NOT take follow-up
  flags yet (review-route is where known-partial coverage is judged;
  extend at M2 if one-motion captures turn out to want it), and teach's
  free-text metadata (`--verified-how`, `--incident-cost`) is
  refuse-only on a scan hit — no redact path for short retypable
  phrases. 427 tests.
- **2026-07-15 · Now-tranche post-build audit (two independent
  reviewers; never-self-certify, tally now 9-for-10)** — one BLOCKER
  confirmed and fixed: `teach --env`/`--session` values reached tracked
  files unscanned (via `teach --route`, committed AND pushed — the
  route_direct scan covered `record.body` only, not frontmatter). Fix:
  the teach meta scan covers every free-text flag, and `route_direct`
  scans `record.to_text()` — the same whole-file coverage as the
  on-disk verbs. Robustness batch from the same audit: all-or-nothing
  multi-file flush (lock-all → scan-all → move; the pinned
  "whole-flush refusal, spool intact" is now literally true at month
  rollover); crash-reflush duplicate lines deduped at read (counts stay
  honest); schema-less telemetry lines never crash `report`; vanished
  spool files skipped; torn tracked lines healed; `open_followups`
  gates on `status: routed` and graduate/supersede WARN when they
  retire an open follow-up (E-2 dead-letter guard) — the upgrade plan
  moves to the successor explicitly, never silently; the teach
  failure-fallback emits its `capture` event (the ceiling label
  depends on an exactly-counted numerator); `surface-budget` events
  now emitted from the compile step; `telemetry note` no longer
  heartbeats the sentinel (cache-only + model-emittable must not
  extend a review hold). 439 tests.
- **2026-07-15 · Testing-regime audit (user-commissioned; two
  independent methods)** — a static adversarial test reviewer plus an
  empirical mutation prober measured the suite instead of trusting it.
  Convergent verdict: NOT mock theater — 89% mutation kill rate (16/18
  planted bugs caught by specifically-aimed tests), ~85–90% of tests
  assert real effects (real git remotes, remote-state assertions, zero
  unittest.mock; goldens anchored by hand-written literals). Both
  probes independently found the same two blind spots, now closed with
  13 new tests (suite 439 → 452): capture-rate VALUE assertions
  (labels were checked, the number never was — the swapped formula
  passed 439 tests), flock observation + a 4-process spool-contention
  test (locking was untested narrative), analyst-timeout → pending
  (sleeping shim; removing the timeout had been undetectable), the
  route-failure never-lost door, route_direct duplicate-id guard,
  spool_quiet under an unwritable cache, crash-window two-step
  recovery (which falsified the old "just re-run route" docstring —
  corrected: commit/stash the half-applied target first), pytest
  wrappers for the two ORPHANED shell suites (sentinel-test.sh,
  install-commands-test.sh — good tests nothing ran), and a
  skipif-gated REAL-chezmoi round trip (sandboxed source/dest/config;
  the chezmoi leg previously ended at an argv shim everywhere). Writing
  the tests surfaced one genuine design flaw: events lacked uniqueness,
  so the crash-reflush dedupe collapsed legitimate same-second
  duplicates — every event now carries a random nonce, making
  byte-identical lines provably re-flushes. Both surviving mutations
  re-verified KILLED against the fixed tree. One can't-fail assertion
  removed. Known remaining gap (accepted): sentinel TTL is duplicated
  between sentinel.py and claude-skills-sync with no shared source —
  both sides' suites now run, but a one-sided change is caught only by
  its own side.
- **2026-07-15 · T13–T16 BUILT (M2 code complete; §7.3 acceptance
  PENDING)** — worker kick/coalesce/run per every §7.1 pin (spawn lock,
  window pidfile liveness, dirty-marker lifecycle, batch cap 15,
  content-hash staleness, delete-on-invalid unattended output, orphan +
  invalidated-merge sweep, mid-run re-check, last-run-only-on-success,
  events.jsonl + pinned notification template + 24h-debounced
  escalation); `status --fast` + SessionStart hook (formatting-only
  bash; settings.json snippet documented in the plugin README);
  `route --collapse` with the pinned one-commit mechanics; review.md
  gains fast-path/merge/not-holding cards. 11's M2 riders landed:
  deterministic recurrence-suspect detection (origin-match /
  title-token-overlap ≥0.6 Jaccard, deduped across runs) feeding
  `confirm-recurrence` (facts copied from the event by nonce;
  tolerate-why in `recurrences[].note`), `confirm-held`,
  `link contradicts`, proposal `contradicts:` (structured field).
  Deliberate scope decisions: (1) the transcript FIRE MINER is NOT
  built — recurrence suspects cover the "not holding" half of 11's
  observation goals; fire observation needs a transcript-mining design
  of its own (retention window, anchor extraction) and is proposed as
  an M2.5/M3 follow-on rather than rushed here — `report` continues to
  label no-observed-fires accordingly; (2) the SQLite index/FTS5
  stays deferred until `report`'s file-walk measurably hurts (11 §5
  sanctions the divergence); analyst-calibration metrics wait for
  card-decided events, which have no writer until a card surface emits
  them. Worker suite: kick races, dead-pid reopen, follow-on, argv
  pins (no Bash/Edit), partial success, mtime-vs-content staleness,
  digest, template verbatim, escalation debounce, 5-case staleness
  truth table, <500ms budget. 487 tests. §7.3's protocol halves —
  (a′) live un-shimmed smoke + refusal check, (b) planted-duplicate
  collapse, (d) 10-item triage — remain to run before M2 exits.
- **2026-07-15 · M2 pre-merge audit (two independent reviewers; tally
  10-for-11)** — three blockers, all fixed before the branch touched
  master: (1) batch-cap leftovers silently stranded (`worker.dirty` now
  kept when eligible > cap, follow-on window covers the tail — the
  pin's letter); (2) validate-before-stamp deleted every spec-compliant
  worker merge proposal (the model is correctly told never to emit
  record_shas; the CLI now stamps FIRST — §7.3(b) was unpassable
  un-shimmed and the suite hid it because fixtures pre-filled the
  hashes); (3) the collapse pre-mutation corrupted the survivor on the
  routine DirtyTargetError abort-and-retry path (empirically: sightings
  3-for-2, duplicated evidence, autosync publishing the intermediate) —
  the merge is now built in memory, written only after the compile
  passes, and `merged_from` provenance markers make any retry
  idempotent. Pin extensions, dated: the worker run now SELF-HOLDS the
  sentinel (sync-first still precedes it; without the hold, autosync's
  rebase-autostash could transiently remove a just-written proposal
  mid-validation — deleting VALID output — and published raw unstamped
  model text mid-run); the orphan sweep uses plain unlink, NOT `git rm`
  (a staged deletion from an uncommitting background process can leak
  into a racing verb's whole-index commit; autosync's `add -A` commits
  the deletion). Minors fixed: digest sorted by author date (anchored
  grep, no Revert echo, skip unresolvable ids); run-end follow-on goes
  through the spawn lock; success decided on landed-valid (not the
  post-mid-run-resolution filter); merges count as proposals in
  event/notification (cluster ids ride record_ids as deep-link
  targets); `fast_status` freshness = the SAME predicate as
  `is_unanalyzed` (schema validity included); worker output is
  secret-scanned and non-contract artifacts under proposals/ are
  deleted-never-published (snapshot went recursive to match the Write
  glob); confirm-recurrence refuses a ref already confirmed;
  link contradicts refuses self-edges and dangling record-id targets;
  collapse+supersedes subject keeps both links; enumeration uses THE
  shared sort key; hook line matches the pinned example + jq guards.
  Accepted residuals, documented: pid-reuse false-liveness on the
  window check (staleness alarm is the rescue); mixed-XDG environments
  defeat lock unity (single-user single-env in practice); the
  step5-filter-to-empty success case has no shim-reachable test.
  497 tests.
- **2026-07-15 · Worker invocation syntax verified against the live CLI
  (the §7.1 pin's own T13-start instruction) — §7.3(a′) refusal check
  PASSED.** The pinned `--allowedTools "…Write(<path>/**)…"` form does
  NOT work on the live CLI: path-scoped write rules are a settings-file
  feature, and the rule FAMILY governing Write is `Edit(...)` —
  `Write(path)` rules match nothing. Verified invocation (the property
  is unchanged: no Bash, no Edit tool, writes only under the two
  proposals/ globs): `--allowedTools "Read,Grep,Glob"`
  `--disallowedTools "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"`
  `--settings <cache>/worker.settings.json` where the settings carry
  `permissions.allow: ["Edit(//<home>/plugins/**/.self-learn/proposals/**)",
  "Edit(//<home>/.self-learn/proposals/**)"]`. Live matrix, all four
  cells: out-of-scope Write DENIED · both bucket scopes ALLOWED · Edit
  tool invocations error while the rule family still grants Write ·
  bare `Write(...)`/relative rules dead. The first refusal-check run
  also proved WHY the pin demanded it: the constructed-string
  assertion had been green over an invocation that denied every write
  — a real worker run would have produced zero proposals forever.
- **2026-07-16 · M3 BUILT (T17–T19; T20 + acceptance remain protocol).**
  Branch `m3-hook-compiler`, test-first, six task commits, 754 → 840
  tests. Findings → dispositions (§9 discipline), each a spec gap or a
  judgment the docs did not pre-answer:
  1. **Hook-proposal key names pinned** — 02 §1's hook extension says the
     proposal carries the hook block "plus the full generated script text
     and the analyst's allow/deny example inputs" without naming keys:
     pinned as top-level `script:` (string) and
     `examples: {allow: […], deny: […]}` (2–3 each, tool_name ∈
     hook.tools — an example naming an unguarded tool is vacuous and the
     validator refuses it). `path_regex` is validated against **grep -E
     itself** (the engine the guard runs), memoized for the freshness
     paths.
  2. **Who writes the script bytes was unstated** — resolved by the
     M2-21 precedent applied to executables: `stamp_proposal` (the one
     path both `proposal validate` and the worker's step-4 flow through)
     GENERATES `script` from the structured input + the record's
     Trigger, overwriting anything the model wrote. Hand-tuning = edit
     the hook block, re-validate; the route applies the stamped bytes
     verbatim (M3-2). Hook stamping refuses knowledge records (the slug
     and the firing condition come from `## Trigger`).
  3. **H-2 vs the verbatim-apply exception** — "recompile repairs any
     two-phase interruption" had no mechanism for hooks (the compile
     input lives in the proposal, which the route's ledger commit
     deletes). Resolved: `routing.hook` stores the APPROVED artifacts
     (tools/regex/message + host-relative `script_path` + the exact
     script bytes); drift selftest and `recompile` re-APPLY those bytes
     — never a regeneration from changed inputs, so M3-2's letter holds.
  4. **`graduate` gains a hook host phase** — M3-4 names graduation, but
     graduate was ledger-only ("the line drops at the next recompile"),
     and no recompile ever visits a hook script. Both supersede and
     graduate now `git rm` the script in a pinned host commit
     (`… (hook removed)`) + print the un-registration reminder.
  5. **`route --dest hook` requires the proposal even with the
     override** — there is nothing else to apply; the refusal names the
     doctrine §5.1 recipe. `teach --route`/route_direct refuse hook AND
     new-skill (`ONE_MOTION_UNROUTABLE`); **`DestinationNotBuilt`/exit 2
     is retired** — all five destinations compile; verb exit 2 no longer
     exists (P2-8's proposal-validate scan-hit keeps 2 unaliased).
  6. **Guard-shape hardenings beyond the precedent** (both test-pinned):
     `grep -E` rc ≥ 2 (broken regex) fails CLOSED — inside an `if` it
     would fall through to allow — and empty stdin fails closed (jq
     exits 0 on empty input).
  7. **New-skill preflight refuses a marketplace-less skills root**
     (the pin appends to existing entries; the scaffold never creates a
     marketplace) — and the route subject carries the name
     (`route lrn-… → new-skill:<name>`). SKILL.md/plugin.json
     descriptions seed deterministically from the first routed lesson's
     trigger.
  8. **T19 resolution timestamps** — routed records use `routed_at`;
     reject/graduate/supersede recover the FIRST resolution commit's
     author date from the ledger's own log (02 §2: git is the who/when);
     collapse losers ride the route subject's supersedes-suffix. Empty
     data answers null, never a confident zero.
  9. **Selftest gains the hooks check** (script exists/executable/
     byte-matches approved; superseded-with-surviving-script flagged as
     incomplete supersession; settings.json `self-learn-*` registrations
     must resolve through `~/.claude/hooks/` — dangling = the silent
     no-op drift). Reads `SELF_LEARN_CLAUDE_DIR` (tests redirect it
     suite-wide; production default `~/.claude`, read-only).
  10. **The worklist drain is packaged, not executed** — the build ran
     READ-ONLY on the real ledger, so the pinned first step ships as
     `fixtures/m3-worklist/` (runbook + three validator-clean draft
     proposals, each guard behaviorally proven in
     `test_route_hook.py::TestWorklistGuards`). Doctrine §5.1 (the
     analyst's hook-block contract, incl. the §4 explicit-over-block
     rationale rule) landed so future analysts can author hook proposals.
  Still owed at §8.3: the [protocol] halves — fixture A's live
  fresh-session trial through a real registered guard, the O-3/O-7
  revisit, install.sh run + registration, README revision-log entry —
  all user-present by design.
  **Revision to disposition 5 (2026-07-16, user ruling):** the
  `ONE_MOTION_UNROUTABLE` refusal is no longer hard-coded — it is the
  DEFAULT of the new One-motion-policy-config pin (§8.1 row above; S-10
  amendment in 03). With no config the behavior and messages are
  byte-identical to what the adversarial review verified; a committed
  `config.yaml` opt-in unlocks `teach --route --dest hook --hook-input
  <yaml>` / `--dest new-skill:<name>` with the full integrity chain
  intact and the applied script bytes printed. `one_motion_allowed()` is
  the single policy gate (teach precheck + route_direct — one
  computation, two callers).

- **2026-07-17 · Post-M3 dev pass: retirement cleanup + metrics tz**
  (found live during the first real drain session, 2026-07-16 evening —
  the chezmoi/sudo-npm guards' supersede-escalations left both old
  advisory lines in canon). Six findings → one pass, all landed with
  regression tests (`test_retirement_cleanup.py`, 860→873):
  1. **Supersede-completion-at-route had no host phase for the OLD
     record** — the standalone `supersede` verb recompiled the old
     target since M1, but `teach --supersedes` + route-of-the-successor
     (the drain kit's shape) only did the ledger half. Route and
     route_direct now share `_retirement_preflight`/`_retirement_
     host_phase` with supersede: the old doc target recompiles (or the
     old guard script is removed, M3-4) in the same motion, pre-flighted
     before any commit, skipped when the successor just regenerated the
     same file.
  2. **Graduate was metadata-only for doc targets** ("drops at the next
     compile") — which stranded the line FOREVER when the graduated
     record was the target's last (see 3). Graduate now runs the same
     retirement host phase. 02 §4's sentence ("lets the compiler drop
     it") stays true — the compile is now simply immediate.
  3. **Recompile enumerated targets only off still-ACTIVE routed
     records** — a target whose last record retired was never revisited,
     so H-2's "repairs any two-phase interruption" was false for exactly
     the stale-line class. Retired records now enumerate their doc
     target too (the regeneration itself reads only active records);
     references stay append-only (retired entries are history, never
     re-appended).
  4. **Recompile skipped the chezmoi user file entirely** — now
     enumerated, with the same E-17 preflight the route path uses:
     drift/dirty skips LOUDLY (warning + skipped entry), the apply goes
     through `_host_phase` (lock discipline; compile_user_scope commits
     its own repo).
  5. **m-4 discharged** — recompile removes a RETIRED hook record's
     still-on-disk script (interrupted removal repair), silent when
     already absent, dirty-skip preserved. **m-5 discharged** — the
     review-gated hook route re-derives the script from the record +
     hook block and refuses on any byte mismatch with the stamp
     (record_sha binds the record, not the script; generation is
     deterministic, so the check is exact).
  6. **T19 triage median mixed timezones** — `git log %aI` carries the
     author's LOCAL offset and was truncated to a local date, while
     created_at/routed_at/today are UTC; the median self-disagreed for a
     few hours around UTC midnight (caught as a "flaky" test at
     2026-07-17 ~01:00Z, hand-count 15.0 vs computed 14.5). Resolution
     dates now normalize to UTC before truncating; a deterministic
     forced-offset regression test replaces reliance on wall-clock luck.
  Also: the worker merge-proposal prompt pins `cluster_id` to the
  `merge-<8 hex>` filename token (run-1 finding: the analyst wrote a
  descriptive slug; the validator correctly fail-closed deleted it —
  prompt tuning routed through human+strong-reasoner per §4).
  **Adversarial review (blind, same day): verdict CLEAN**; interruption
  window, skip_target aliasing, collapse-loser reachability, m-4/m-5
  soundness, and idempotency all held under executed probes (11 of the
  13 new tests fail on the parent commit; the tz failure reproduced live
  on parent during the review). Delta fixes from its findings, all
  regression-tested (873→876): (1) the recompile user-file entry now
  reports `UserScopeResult.committed` (was a nonexistent `.changed` —
  always False; CLI would have crashed printing a None sha once fixed
  naively); (2) `--no-push` now reaches the chezmoi flow —
  `compile_user_scope(push=)` threaded as `user_push` through
  route/route_direct/supersede/graduate/recompile (pre-existing on
  route; new surfaces made it urgent); (3) **pre-existing since M1,
  found by the review's live probe**: one repo registered as BOTH
  project host and skills root (the shipped claude-skills shape)
  compiled its CLAUDE.md from ONE scope's records per route — each
  route of one scope ERASED the other scope's lines. `_compile_set` now
  unions every scope resolving to the same file (single-role hosts
  degenerate to the old set exactly); (4) the worker prompt's validator
  claim tightened (pattern-enforced, filename-equality dies at
  collapse).

- **2026-07-17 · M3-7 amended by the D1 ratification (13 §7.3):**
  project/user-scope guard scripts are HOST CANON, landing at
  `<skills_root>/hooks/self-learn/`, not in the product's plugin dir
  (the original placement conflated product and host while they shared
  a repo). Governing principle (user, verbatim in 13 §7.3): the product
  repo receives nothing but its own development work. The two live
  guards (lrn-dd9489b2, lrn-4f5971c8) migrate `script_path` in runbook
  step 1; script filenames — and therefore ~/.claude/hooks names and
  settings.json entries — never change.
