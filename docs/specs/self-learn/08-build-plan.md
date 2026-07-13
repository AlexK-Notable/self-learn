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
| Package | Plugin `plugins/self-learn/`: `.claude-plugin/plugin.json`, marketplace entry, `skills/self-learn/SKILL.md`, `commands/teach.md` + `commands/review.md` (→ `/self-learn:teach`, `/self-learn:review`), CLI `scripts/self-learn` (Python/uv, shebang, no extension → `~/bin` via install.sh's existing glob) | 04-M1 |
| Ledger home | `SELF_LEARN_HOME` env var, default `~/repos/claude-skills`; all bucket paths resolve against it; tests override it | 04-M1 |
| Bucket discovery | skill buckets = glob `plugins/*/skills/*/.self-learn/`; project+user bucket = `<home>/.self-learn/` (user records tagged `scope: user`) | 01 §2, 02 §3 |
| Record ids | `lrn-` + 8 random lowercase hex | 02 §1 |
| Sentinel | `~/.cache/claude-skills/self-learn/autosync-pause`; content = 1 info line (`pid= host= started=`); **live iff mtime < 2 h**; heartbeat = every mutating CLI invocation touches it (no daemon); checked at top of `claude-skills-sync`, which exits 0 without committing while live; stale sentinels ignored/deletable by either side | 02 §3 |
| Sentinel scoping | `self-learn sentinel hold\|heartbeat\|release` subcommands; slash review holds for its whole batch; TUI (later) wraps only apply flows; a bare resolution verb self-holds and releases only a sentinel it created | 01 §3.4, 07 §4 |
| Resolution verbs | `route <id> [--dest <target>] [--note …]` · `reject <id> [--note …]` · `defer <id> [--until <date>] [--note …]` (default +30 d) · `graduate <id> [--note …]`. `route` reads `proposals/lrn-<id>.yaml` (M1 inline analysis writes it; M2 worker takes over — pure producer swap); `--dest` overrides. Every verb: stage **only touched files** (never `-A`); abort if the compile target has unrelated uncommitted edits (tell the user to commit/stash); commit with the pinned message (02 §2, note → commit body); then push | 01 §3.4, 02 §2 |
| Push | Per-verb `git push` after commit; on non-FF, `git pull --rebase --autostash` then retry once; on failure: **loud** warning + keep local commit; review session end re-attempts (`self-learn push` exists as a bare verb) | 01 §3.4 |
| Proposal lifecycle | Resolution `git rm`s `proposals/lrn-<id>.{yaml,diff}`; M2 digest reads `resolved/` + commit messages only | 02 §3 |
| Secret scan | Built-in regex module (no external tool dependency): private-key headers, AWS `AKIA…`, GitHub `ghp_/gho_/github_pat_`, Slack `xox…`, JWT `eyJ…\.eyJ…`, `(password\|passwd\|secret\|token\|api[_-]?key)\s*[=:]\s*\S{8,}`, high-entropy base64/hex runs ≥ 40 chars. Default = **refuse**, printing the matched span + rule; `--redact` replaces the span with `[redacted:<rule>]` and sets frontmatter `redacted: true`; **no bypass flag in v1**. Runs on every record-body write (S-8 rider) including `resolution_note` | 02 §2 |
| Dedupe key | `evidence.origin` = `<path>#<anchor>` or `<path>#sha256:<12 hex>` of normalized entry text; never line numbers | 02 §2 |
| Managed-section bootstrap | First route to a markerless target: append marker pair at EOF, proceed; `--selftest` flags only should-have-section targets | 02 §4 |
| Already-canon flag | `type: knowledge` AND source file is itself canon; behavioral entries never bulk-flagged; judgment recorded in the proposal sibling | 01 §3.2 |
| Routing doctrine file | `plugins/self-learn/skills/self-learn/references/routing-doctrine.md` — the single source (01 §3.5's map + narrowest-surface bias + repo conventions). Consumers: M1 inline analysis, M2 worker prompt, G-3 TUI pane. One file, three loaders — never fork it |  |
| `teach --route` | Prints diff, applies, **no confirm prompt** (invocation = approval). In-session callers pass structured fields + `--dest`; bare-terminal `--route` without `--dest` runs a one-shot `claude -p` analyst against the doctrine file | 01 §3.2 |
| Offer line (S-15) | Lives in `~/.claude/CLAUDE.md` (chezmoi-managed — a **documented install step**, edited through chezmoi, not compiler output). Exact text: *"When I correct a mistake you made, or state a rule/preference that should change how you work beyond this task, offer once and briefly to capture it (`self-learn teach`). Offer only for durable lessons — corrections of wrong behavior, standing preferences, gotchas that will recur — never for one-off task instructions. Several serious corrections in one session each deserve an offer."* Load-bearing spec; revocable by deleting the paragraph | 04-M1 |
| `--json` stubs (M1-minimal; the TUI contract hardens them at G-3) | `list --json` → array of `{id, type, scope, kind, status, created_at, age_days, deferred_until, sightings, has_proposal, title}` (`title` = first line of Trigger/Fact). `status --json` → `{buckets: [{bucket, scope, pending, oldest_days}], total_pending, worker_last_run: null}` | 07 §4 |
| Versions | v1.0 = M1+M2 · v1.1 = M3+ | 04, S-14 |

## 2. Phase 0 — fixture baseline-qualification trials (no code; run FIRST)

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
1. *Absence proof:* grep the home-assistant SKILL.md **body** for the
   stop→edit→start surgery; confirm the lesson exists only in
   `references/GOTCHAS.md`.
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

## 3. M1 task breakdown (dependency order; each = tests + code + DoD)

Tasks are sized for one implementation agent each. T1–T11 in the worktree;
T12 on main-repo master. Parallelizable groups: {T2,T4} after T1; {T5,T6}
after T2–T4; T12 anytime.

- **T1 · Plugin scaffold.** `plugins/self-learn/` skeleton per §1 Package
  pin; marketplace entry; CLI entry point with arg parsing + `--selftest`
  stub; `SELF_LEARN_HOME` resolution. *Tests:* CLI runs from a symlink;
  home resolution honors the env var. *DoD:* `self-learn status` on an
  empty sandbox prints zero-state without error.
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
  route/reject/defer/graduate, `--note` → `resolution_note` + commit body,
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
- **T9 · Importers.** Backlog: GOTCHAS parser (entry boundaries, date
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
  end-of-session summary + push retry, batch sentinel hold/release),
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

## 6. M1 acceptance & merge procedure

1. Full automated suite green in the worktree ([auto] criteria c, d, e).
2. Merge worktree → master per repo convention; run `./install.sh`
   (idempotent) on this machine; verify: `~/bin/self-learn` symlink,
   skill symlink, `/self-learn:review` visible in a fresh session; sweep
   `~/.claude/hooks/` for dangling symlinks (repo doctrine).
3. Apply the offer-line chezmoi edit (documented install step).
4. [protocol] runs with the user: exit (a) one-motion `teach --route` on
   home-assistant; exit (b) the real backlog-import review session (this
   is also the E-3 honeymoon test — schedule it when the user has ~30
   minutes).
5. Route fixtures B and C through the system (their records via `teach`),
   then run the §0 post-routing trials — 3/3 each against the written
   predicates, attribution recorded per trial (B also proves the E-17
   chezmoi persistence check: `chezmoi apply` then re-grep). **B and C
   pass = the M1+M2 behavioral checkpoint is pre-armed** (final call at
   the M1+M2 boundary per 04 §0; A waits for M3).
6. Update the corpus README revision log; update project memory and the
   znote hub with the milestone state.

## 7. M2 / M3 briefs (pins to honor; detail lives in 01/04)

**M2:** worker = detached `claude -p` (setsid + machine-local flock in
`~/.cache/claude-skills/self-learn/`, coalesced runs, `--allowedTools`
restricted to repo reads + new files under `.self-learn/**/proposals/`),
writing analysis + merge proposals only; analyst prompt = the doctrine
file + the rejected-proposal digest (built from `resolved/` + commit
messages — G-11's formats make this a grep); last-run marker feeds the
SessionStart staleness line; notifications per worker run via
`notify-send`, payload = aggregate line + record ids (07 §4 contract 3);
SessionStart hook registered **manually** in settings.json (documented
step). Exit criteria per 04-M2 (tag: a–c [auto-ish], d [protocol]).

**M3:** hook compiler (P9: scaffold + settings.json snippet, never
auto-register), new-skill via plugin-dev delegation, statusline count,
O-3/O-7 revisits against a month of supply-mix data, fixture A trial =
exit criterion.

## 8. Change control

- Pins in §1 change only with a dated edit here + a pointer from the
  corpus doc that co-owns them; if a pin change would alter a settled
  decision's inputs, the 03 register reopens first (P10).
- New gaps found during the build get a dated **Build findings** appendix
  entry here (finding → disposition), so the next agent inherits answers,
  not archaeology.
- This plan is complete when M1 exits; M2 execution planning extends this
  file (same structure) rather than starting a new one.
