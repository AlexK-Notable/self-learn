# self-learn — design corpus (gen 2)

*Single-authored 2026-07-12, replacing the gen-1 harness spec (archived at
`../archive/gen1-self-learning-harness/` — its README explains why). Status:
**RATIFIED 2026-07-12** · **M1 SHIPPED 2026-07-13** · **M2 SHIPPED +
11-telemetry RATIFIED 2026-07-15** · **M3 COMPLETE, v1.1 tagged
2026-07-17** · **G-3 adjudication surface SHIPPED 2026-07-17** (live:
`self-learn-ui.service`, 127.0.0.1:7357) · **extension rounds U12–U18
SHIPPED 2026-07-17/18** (chat panes → idle lifecycle → feedback rounds
1–3 → UX round 1; revision log below) · **Agent-SDK migration Waves 0–1
SHIPPED 2026-08-09/19** (invocation seam → `SdkBackend` →
provider/Bedrock contract + `doctor invocation` → test tiering;
`S-34`–`S-44`, `17-invocation-runbook.md`) · **next: Wave 2 — the
analyst flip (`U-sdka`) and the per-surface burn-ins**; packaging
(`research/2026-07-18-sdk-bundle-exclusion.md`) is queued behind it
*(corrected 2026-08-19, U-docs: the header named a phase that did not
happen next and omitted the four units that did)*. Everything here was
written together, as one system, with
the full evidence of three review rounds and the repo's own usage history baked
in from the start — not iterated into shape.*

*This corpus ships under the product repo's root `LICENSE`
(FSL-1.1-MIT) like every other file in the repo — it is not separately
licensed. Treat it as a historical and design record of the product,
not as a specification of the shipped product's present behavior; where
the two disagree, the code and its own tests are authoritative.*

## What self-learn is, in one sentence

A **capture, triage, and routing system for lessons learned while using Claude
Code**: lessons accumulate quietly into per-skill and per-project buckets; a
review surface presents them pre-analyzed; the user routes each one — with
agent help — into the surface where it becomes permanent (SKILL.md, CLAUDE.md,
reference docs, a new skill, or a hook). Nothing influences Claude until a
human routes it. *Amended 2026-09-13 (S-29 as amended):* "a human" now has
one named exception — the steward routes nightly, alone, under the
delegated judgment `03-decisions.md` S-29 describes; every route still
passes the same compile+commit path this sentence's own paragraph names.

## Reading order

| Doc | What it holds |
|---|---|
| `00-vision.md` | The problem (restated correctly), the target UX, and the ten design principles with their evidence |
| `01-architecture.md` | The seven components, the life of a learning, failure modes, and what is deliberately absent |
| `02-schema.md` | The learning record, storage layout, and mutation rules |
| `03-decisions.md` | The decision register: settled / open / v2-gated (with explicit activation triggers) |
| `04-roadmap.md` | Build milestones, acceptance fixture, success metrics |
| `05-evidence.md` | The empirical facts this design is built on, with sources |
| `06-horizon.md` | The team-scale future (~5–6 users, shared artifact repo): invariants, the six team problems, staged path |
| `07-review-ui.md` | The review-surface vision (recorded 2026-07-12 as a resident TUI; platform since re-decided — see 09): attend-at-convenience, embedded agent adjudication pane, the don't-subvert contracts — recorded against v1/M2, binding on every later surface (the shipped G-3 UI inherits them) |
| `08-build-plan.md` | **Execution authority for the build**: pinned interface contracts, the Phase-0 fixture runbook, the M1 task DAG, judgment-call routing, eventuality playbooks — written so any orchestrator can run the build |
| `09-surface-spec.md` | **Design authority for the G-3 adjudication surface** (web revision, 2026-07-12): interaction model, surfaces/routes, files-as-truth data flow, security middleware, the adjudication pane (Agent SDK engine default / CLI stream-json alternative, empirically probed), degradation table, stack selection |
| `10-surface-build-plan.md` | **Execution authority for the G-3 build** (gated on G-3's trigger): surface-local pins + verify-at-build ledger, acceptance fixtures incl. live trials, task DAG U1–U11 plus the post-ship extension units U12–U18, judgment routing, playbooks — 09 wins on conflict; shared pins stay owned by 08 |
| `11-telemetry-and-lifecycle.md` | **RATIFIED 2026-07-15 (v2; user-delegated — Q&A in the revision log)** — the life of a lesson after routing: follow-ups, recurrence tracking (suspect→confirm), certainty-as-measured-events, the three-plane data model (record frontmatter / actor-scoped telemetry JSONL / disposable index+report), and the standing multi-machine posture principles |
| `12-transcript-miner.md` | **RATIFIED 2026-07-15 (same-day; §8 records the round — resolves O-3)** — autonomous capture: the nightly transcript miner as a third producer ("continuous import"), structural-digest → rubric-driven reader → verb-gated landing with use-scaled caps, run-journal observability contract (feeds the future G-3 miner pane), 24h three-layer watchdog, staged-autonomy ladder for future review autonomy, fire observation folded in, and the §5 embeddings decision of record (declined transcript-side, pinned as the ledger-side scaling path). §9 is the build plan |
| `13-hosting-and-separation.md` | **RATIFIED 2026-07-16 (user-directed; four calls answered live, §1)** — the product / ledger / host split: independent ledger home at `~/.self-learn` (git, own remote, hosts.yaml registry), per-project buckets (fixes cross-project mis-homing), ledger-first two-phase routing (revises 02 §2 — ledger is truth, canon is compiled output), producers commit their own writes (no watcher on the ledger), cache renamed + home-namespaced, history-preserving migration T-H1…T-H5, product-repo extraction as step 2, the overseer's own `overseer/` subtree (§7.4's hook-activation path, its coverage record and reports) |
| `14-forward-work-map.md` | **The forward work register (FW-1…FW-29)**: potential required work mapped with triggers, types (BUILD/DRILL/DECIDE/WATCH), the consolidated user-decision queue, the first-firing trigger table, and sequencing — authored 2026-07-18; items graduate into specs via the normal gates |
| `forward/` | Theme deep-dives behind 14: supply quality, canon lifecycle, packaging, UI/UX, sync & fleet, platform drift, process & horizon, worker ecology |
| `15-orchestration-runbook.md` | **How the agent rounds actually run** (FW-26): round lifecycle, worktree/blindness/merge/sandbox discipline, the gotcha bank, prompt skeletons — written so a fresh orchestrator can run a round without violating a standing rule |
| `17-invocation-runbook.md` | **The operator runbook for the two invocation switches** (`backend` per surface, `provider` install-wide): the doctor preflight ritual, the flip and rollback one-liners with their measured traps, the per-surface burn-in gates, and the instrument gaps those gates inherit — written so an operator can flip a surface, watch it, and put it back without reading a spec |
| `records-index.md` | One-line index of every review record, research memo, and trial-log section (FW-27) — date, subject, outcome, what it pinned; maintained at round-close |
| `research/` | External evidence memos (SOTA surveys etc.) — shareable with blind reviewers, unlike `reviews/` |
| `fixtures/` | `gen-fixture-b` + `trials.md` (Phase 0 rounds 1–3: six candidates disqualified, B3 qualified + proven 3/3 post-routing — the system's primary behavioral evidence); `ui-trials.md` lands with the G-3 build |

## Ground rules for changing this corpus

1. A **settled** decision (`03-decisions.md`) reopens automatically if a later
   decision changes its inputs — "settled" is not "shielded" (gen-1's
   sequential-lock-in failure).
2. Material design changes get a **blind** review before settling — reviewers
   receive the docs and a mandate, never the expected conclusion.
3. No code until the user ratifies the corpus; build happens in this worktree
   per the repo's worktree → test → merge convention.
4. *(Added 2026-07-12, after the SDK-auth false-fact failure — znote
   `zQgIhHiqhJFes7RRzU4bF`.)* **Sourced ≠ true, and true ≠ right-for-us.**
   A decision-relevant claim that is locally testable gets an empirical
   test before it may ground a decision — quoting live docs is not
   verification. And every material-decision review includes a
   **framing lens**: what option or assumption was never priced; does
   the stated frame fit the actual circumstance (this user, this
   workflow, this maintenance reality). Problem-space map before option
   comparison; the user's values questions routed early and binding,
   never as post-hoc veto footnotes.

## Revision log

- **2026-10-06 — (steward, records, ledger_ops, verbs) S-78: a filing move writes itself into the record; three stranded lessons come back.** New decision row **S-78** in `03-decisions.md`. The steward's eligibility is keyed on `(record, version)`, and a project->project `rehome` wrote no byte, so a lesson the steward filed kept its version and was never selected again (live: `lrn-b0788414`, `lrn-dcae3b28`, `lrn-7a0769fb`). **(1)** `records.HISTORY_EVENTS` gains `moved`: `ledger_ops.move_record` appends `{at, from, to, by, case?}` in the same write as every `rehome`/`rescope`, for every actor (`verbs._move` passes the delegated runner's actor and case), so a moved lesson is a new version, and a `host rebind`, which writes no record, leaves decided lessons decided. **(2)** `steward._terminal_versions` skips an `applied` row whose case's sheet holds a filing item for that lesson (`_files_record`), which brings back the lessons moved before (1). **(3)** The bound: a steward case that would move a lesson the steward already moved (`_FILING_MOVE_LIMIT` = 1, the larger of its applied move rows and the record's `moved` entries by the steward) or one a person or the overseer moved last (`_last_mover`) is parked as `scope-conflict` (`_refiling_reason`, in `_prepared_recipe` and skipped by the repair turn). **Forward-only:** older code refuses a record with a `moved` entry. Spec: `02-schema.md` §2 and §3a.8 and the parked-reasons passage; `steward-method.md`, `commands/review.md` and the steward's output contract name the runner-written `scope-conflict`. Tests: `tests/test_steward_filing_moves.py` (21); `tests/test_rehome.py`'s byte pin now allows the one `moved` entry. Gate: the first design (`61ec621`, bucket-scoped decisions) failed its blind gate (F1: a `host rebind` re-opened decided lessons) and was replaced; blind gate on `c04350c`: CLEAN (no defects; on a ledger copy exactly the three stranded lessons come back); its test gap (`_files_record`'s id match) closed in `023a36a`; four nits deferred (a rehome to the lesson's own bucket counts as a move; two moves in one sheet; a hand-run sheet's `by` written as given; moves before S-78 name no mover).
- **2026-10-06 — (batch, verbs, steward, overseer) S-77: the agents stop filling reference shelves; a reconsider reject or defer takes a lesson off one.** New decision row **S-77** in `03-decisions.md` (amends S-23 (1)). **(1)** `batch.REFERENCE_REFUSED_ACTORS` = {steward, overseer}: a route line whose destination resolves to `reference` (a fresh route, a destination taken from the proposal, a collapse route, a reroute, a reconsider's correcting route) is refused for them by name (`bad-line`) in `_dispatch` and `dry_run` alike; a person's route is unchanged. The overseer's `closed-sets.yaml` names it (`sheet.refused_dests`). **(2)** `verbs._RECONSIDER_RETIREABLE_DESTINATIONS` gains `reference`: under a `kind: reconsider` case, `reject` and `defer` take the lesson's entry block off the shelf in the same locked section the status flips in, holding the shelf host's lock (`_reconsider_retirement_lock`) and committing the predicted compile-record entry with the status flip (`_reconsider_retirement_records`); a git host commits the shelf, a plain host's file is changed and recorded, never committed. The hook case stays refused. An emptied shelf keeps its file and pointer line. **(3)** What the agents are told: the steward's output contract and worked examples (the shelf example now moves a lesson off a shelf), the overseer's phase-B prompt and `formats/README.md`, `routing-doctrine.md`, `steward-method.md` §16, `commands/review.md`. `13-hosting-and-separation.md` §7.4 amended. **Reach:** the path needs a steward- or overseer-recorded predecessor case, so on 2026-10-06 it reaches at most 11 of the 44 shelf lessons; the 33 a person shelved are a question to the user. Tests: `tests/test_agent_reference_routes.py` (17), `tests/test_reconsider_off_shelf.py` (22); four older tests now use a hook-routed example. Gate: blind gate on `aa86e32` (no defects; three untested behaviours and stale wording folded in `0ac6875`; two older risks, a reopen pair hiding a refusal from the steward's repair turn and an unrepaired shelf write after a failed host phase, recorded for later).
- **2026-10-06 — (mining) the session miner's output contract and the offline comparison with the old miner.** Built ahead of the engine, not a decision: no new `03-decisions.md` row. New package `src/self_learn/mining/` (an import-free `__init__.py`). **(1)** `contract.py` transcribes the three documents of the U4 spec's §6: the model output `miner-output-model/1`, the checked output `miner-output/1` and the run record `miner-shadow-run/1`, each with a hand-written validator returning path-first messages that never echo a value (an unknown key is named only when it is plain and `scan.redact` leaves it unchanged), plus `model_output_json_schema()` (which agrees with the validator, pinned by `SCHEMA_SHA256` and a test running both), `load_run()` (which checks a run folder against itself and refuses a session id listed twice) and the one definition of a typed turn (`has_typed_turn_marker`, `typed_turn_lines`, `turn_of`). A lesson's `kind` follows the ledger: one of `records.KINDS` for a behavior lesson, null for a knowledge lesson. Enums are imported from `records` and `refs`; every pattern check is a full match. **(2)** `compare.py`, run as `python -m self_learn.mining.compare`: `inventory` (a zero-call look at a frozen set; `--out` required) and `report` (a shadow run against the frozen set or the old miner's journal, telemetry and ledger). Moments are bucketed A/B/C from the records that cite them; every count is given strict and loose; a target in a session the new miner did not judge is counted under its reason and never as a miss. The user's 2026-10-06 answers are built in: bucket B is its own line and never a miss (`missed_moments` is bucket A only; the rest are `not_found_moments`); every skipped moment is logged by key with its reason; a deterministic sample of shared-but-maybe-different lessons (default 8) goes to the spot check beside the old miner's records; the person marks new finds and misses, and a mark survives a rerun. `report.json`, `report.md` and stdout carry counts and keys only; `spot-check.md` is private (0600). Reads only. **(3)** `02-schema.md` §3a.9 documents the contract and `miner-compare/1`. Tests: `test_mining_contract.py` (K1–K5) and `test_mining_compare.py` (H1–H10 and bad inputs), each mutation-checked. The engine (U4-engine) imports `contract` unchanged. Gate: blind gate on `ced6f85` (one low defect, the schema and the validator disagreeing on a one-step lesson, and four risks, all folded in `22802a1`).
- **2026-10-06 — (invocation, sdksession, provider) a seventh surface, `miner-session`, that runs on its own tools.** A seam for the coming session miner, not a decision: no new `03-decisions.md` row. **(1)** `invocation/contract.py`: the surface `miner-session` (last in `SURFACES`) shares the `MINER` selector, so `models.miner`, `sdk.max_turns.miner` and the backend variable apply to both miners. It defaults to `sdk`, has a miner-shaped log row, and its containment allows the caller's `allowed_tools`, writes nothing, and is strict MCP. `provider.MODEL_KEY_FOR_SURFACE` maps it to `miner`. **(2)** A session's own tools as plain data: `ToolReply`, `McpTool`, `McpToolset`, and three `SessionSpec` fields, keyword, defaulted and last: `mcp_toolset`, `sidecar_key`, `skip_orphan_sweep`. Tool, server and sidecar names must match in full; a toolset must not be empty, and each tool's `input_schema` must carry a string `type` and a `properties` mapping. **(3)** `invocation_sdk/backend.py`: with a toolset, `tools=[]` and one in-process server built in the seam. The session is refused unless the containment allows exactly the toolset's `mcp__<server>__<name>` names, when the SDK lacks the `tools` or `mcp_servers` option, and for `miner-session` when it carries no toolset (`_OWN_TOOLS_ONLY`). Each handler call is bounded at 60 s (`asyncio.timeout`; a handler's own `TimeoutError` is reported as a failure, not as the bound), an exception is reported by type name only, a cancellation reaches the caller, and a reply over 48,000 characters becomes an error that names the bound. Handlers must be async and non-blocking (documented, not enforced). Keyed pid sidecars and the sweep switch are opt-in. **(4)** `sdksession/events.prune_event_logs` sorts a file a sibling session already removed as the oldest instead of raising inside the session's `finally`. **(5)** `17-invocation-runbook.md` §1 and new §1a, including what a caller of `miner-session` owes: a cross-process run lock (one process's orphan sweep kills another's live `miner-session` children) and a unique `sidecar_key` per session. With the new fields at their defaults every surface sends exactly the options it sent before, so no armor door is owed. Tests: `tests/test_seam_mcp_tools.py`. Gate: blind gate on `5a5b12c` (no defects; three risks and six nits folded in `f03eacb`; deferred: a `SessionSpec` carrying a toolset cannot be hashed, and nothing hashes one today).
- **2026-10-06 — (miner) the old miner no longer reads self-learn's own agents' sessions.** A fix, not a decision: no new `03-decisions.md` row. The nightly miner halts a session whose first user turn opens with one of `SELF_PROMPT_HEADERS` (M-5), but the steward's, the overseer's and the worker's repair-pass openings were missing, so 79 of their sessions were tracked unhalted and mined. **(1)** Each agent's opening is now defined beside its prompt — `steward_prompt.SESSION_OPENINGS` (derived from the block order: `=== containment ===`, which began every steward session before and after `faa1853`), `overseer.run.SESSION_OPENINGS`, `worker.SESSION_OPENINGS` (normal and repair pass) — and `miner.SELF_PROMPT_HEADERS` unpacks them; `tests/test_miner_self_sessions.py` builds the real prompts and pins them. **(2)** `miner.halt_tracked_self_sessions` halts already-tracked sessions once per header list (fingerprint `__self_prompt_headers__` in `cursors.json`); one unreadable or malformed file never stops the pass, and the fingerprint is stamped only when nothing was left unchecked. **(3)** `_blocks` and `_first_user_text` skip a row whose `message` is not a dict, so one malformed row can no longer stop every nightly mine. Program-run sessions that are not self-learn's own are still mined (a test pins it). I recommended stopping this before the new-miner comparison; the user agreed on 2026-10-06. Deferred: the one-shot analyst's sessions are not yet halted; learning from the agents' own sessions is a later idea. Spec: `12-transcript-miner.md` M-5. Gate: blind gate on `bcec1bf` (no defects; risks R1/R2 folded in `bcb7a9d`, a sibling fold in `db1ed25`).
- **2026-10-05 — (overseer, cases, user-model, steward, cli) S-76: the overseer corrects a decision that failed once to apply; the user model's one-line fields are named and told; `rules_paths` inheritance needs the same bucket.** New decision row **S-76** in `03-decisions.md`. **(1) Reconsider of a non-parked case.** The live chain for `lrn-19f82fc5`: the steward parked it (`case-43852101`); run `ec93fb36` decided it with a `kind: resolution` successor (`case-5257d97d`) whose `route dest: hook` was refused at apply, consuming the parked case; run `03a07173`'s `kind: reconsider` successor of `case-5257d97d` was dropped at phase B ("supersedes must name a verified parked case"). `cases.require_reconsider_predecessor(home, supersedes, record_ids)` is the predecessor half of `require_reconsider_case` (which now calls it; messages unchanged); `overseer/run.py` `_validate_successor(path, parked, home)` holds a `kind: reconsider` successor to it (parked or not), to not-already-superseded, and, for a predecessor outside the parked queue, to `actor` in `_CORRECTABLE_ACTORS` = {steward, overseer} (a person's case is never superseded: the blind gate's risk 1); every other successor keeps the parked-only rule, and a non-string `supersedes` is a per-pair drop instead of a TypeError that ended the run. Phase B's preview now passes `reconsidered=` (the records the staged reconsider covers), so a reconsider reroute no longer counts "would refuse"; a reconsider pair whose preview refuses any line is dropped at phase B, named in "Refused / could not do" and the run journal (`_refuse_doomed_reconsider`, the gate's risk 2; `test_overseer_run.py::test_reference_reconsider_refusal_is_committed_and_not_retried` now pins that drop). The drop lines name the real reason. The phase B prompt, `formats/README.md` and new `formats/case-correct-example.yaml` state the rule in the code's terms (coverage, not superseded, freeze hash, steward or overseer actor; no selected-this-run check); `02-schema.md` §3a and the phase-B pairs note, and `13-hosting-and-separation.md` §7.4, amended. U3b's `ec93fb36`-shape test passed because its reconsider superseded the still-open parked case; it never built the refused first resolution. **(2) User-model one-line fields.** Run `03a07173`'s add `op-3b0e8cf5ca64` was refused by the gate r2 B1 structural check: its `because` was a hard-wrapped `|` block scalar, the form the general YAML rule recommends for free text. The check is unchanged; `user_model.ONE_LINE_FIELDS` names every caller-supplied field `_render_entry` writes (add: title, because, ref, conditions, statements, basis, held_since, recorded_by; lapse: the three causes and `at`) -- `held_since` let the gate's probe F forge an entry -- `add_entry`/`lapse_entry` check through it, and its drift check raises (it was an `assert`, which `python -O` strips). The overseer's prompt, `formats/README.md` and `closed-sets.yaml` (`user_model_delta.one_line_fields`) carry a rule generated from it, the general YAML rule names the user-model exception (`_YAML_TEXT_RULE`, which only the overseer reads), and the example is double-quoted on one line. **(3) S-75 follow-up.** The steward's brief, `steward-method.md` §15, the overseer's `formats/README.md`, `commands/review.md` and the `--rules-path` help of `route`, `reroute` (`cli.py`) and `teach` (`teach.py`) now say inheritance needs the same topic AND the same bucket (`verbs._inherit_rules_paths`). Tests: `tests/test_overseer_reconsider_chain.py` (25), `tests/test_overseer_user_model.py` (+6), `tests/test_rules_paths_inheritance_text.py` (7); `test_overseer_run.py`'s reference-reconsider test rewritten to the phase-B drop; `test_overseer_workspace.py` and `test_u3b_steward_authority.py` pass `home` to `_validate_successor`, and the u3b formats test records a real parked case for the reconsider example to name.
- **2026-10-05 — (hosts) FW-162 BUILT: a capture made inside a git worktree files under its registered parent host.** A status change, not a decision: no new `03-decisions.md` row. New `hosts.capture_host_path(home, path)`: when the path a producer took from the session's working directory lies inside a linked git worktree (`--git-dir` differs from `--git-common-dir`) whose main working tree (first entry of `git worktree list --porcelain`) is exactly a registered project host, the record lands in that host's bucket and its `meta.yaml` names the host. Callers: `teach._project_path`, `import_memory`'s cwd default, and the miner's `project_path` for a landed candidate. `verbs._resolve_target` is unchanged: route time reads only what capture wrote, and `route_direct` (teach --route) now receives the resolved path. A worktree that is already gone when the miner reads its session files under `<P>` only by the shape `<P>/.claude/worktrees/<name>`, with `<P>` exactly a registered project host; that pattern is never applied to a path that exists. Unchanged: plain repos and their subdirectories, an unregistered repo's worktree, a registered worktree, any other missing path. Fails closed when git is absent or hosts.yaml does not load. Existing worktree buckets are not moved. `14-forward-work-map.md` FW-162 and `13-hosting-and-separation.md` §3 (producers' project path) updated; the routing doctrine needed no edit (§2a is `variant: local`, and §3's "a record's bucket is fixed at capture time from the session cwd" stays true). Tests: `tests/test_worktree_captures.py` (18).
- **2026-10-04 — (steward, overseer, batch, verbs) S-75: how to choose `rules_paths`, told to both agents; `recompile --adopt` adopts a pointer region.** New decision row **S-75** in `03-decisions.md`. **(1)** Guidance added to `steward_prompt._render_output_contract`, `steward-method.md` §15, `overseer/formats._rules` and `commands/review.md`; `show --json`/`show` print a routed lesson's `rules_topic`, `rules_paths`, `rules_paths_from`; `batch` threads `allow_empty_glob` to `reroute`, its preview and both `route_dry_run` calls. **(2)** `verbs.recompile(adopt=)` takes a list; `PATH#pointer` / `PATH#managed` selectors; `cli --adopt` is repeatable. Tests: `tests/test_rules_paths_agents.py` (11), `tests/test_adopt_pointer_region.py` (8).

- **2026-10-03 — (verbs, compiled) S-74: compile-record entries identify a region; a rules route keeps its predecessor's globs.** New decision row **S-74** in `03-decisions.md`. **(1)** `compiled.region_key(host, target, region)` — the pointer region keys `<path>#pointer`, every other kind the bare path; `entry_for(..., region=)` reads a legacy bare-path entry by its `region:` tag; `write_entry`/`delete_entry` move such an entry to its suffixed key first (`compiled.migrate_legacy_entries`). Callers: `verbs._abort_if_region_unsound`, `_write_compile_record_entry`, `_resync_region_entry`, `recompile --adopt`, `selfcheck`. `recompile`'s `specs` (managed targets) and `ref_work` (reference files) are separate dicts, so a pointer and a managed spec for one CLAUDE.md never collided there. `--adopt` still adopts only a managed region. **(2)** `verbs._inherit_rules_paths` (route, route --dry-run, teach --route, reroute); `--rules-path` on `route`/`reroute`/`teach`; `--allow-empty-glob` and `--allow-unpathed` on `reroute`; `routing.rules_paths_from`; `reroute` onto the same rules topic with different globs is allowed (`_reroute_plan`'s RER3). **(3)** `verbs._abort_if_unscopes_rules_file` refuses a globless rules route into a file whose on-disk `paths:` is non-empty unless `--allow-unpathed`. Tests: `tests/test_region_key_and_rules_scope.py` (33); `test_a2_rules_local.py`'s two absorption tests and `test_hostmode.py`'s two pointer-key reads edited to the new rule.

- **2026-09-28 — (hooks, steward) S-73: warning hooks — FW-161 items 1 and 2 (PostToolUse for warnings); the reconsider preview widens.** New decision row **S-73** in `03-decisions.md`. **(1) Grammar.** A hook block gains `mode` (`deny`, the default and unchanged; `warn`, new) and `event` (`PreToolUse`, the default; `PostToolUse` for `warn` only — a deny after the call has run means nothing). A warn block carries `warn_message` (non-empty, at most 2,000 characters, newlines allowed) in place of `deny_message`, and its examples are `{allow, warn}` with the same 2–3 bounds; the keys stay a closed set per mode and a wrong-mode key is refused by name (`ledger_ops._validate_hook_extension`; the constants live in `hook_compiler`). **(2) The warn script.** Same input handling as the deny guard; on a match it prints `{"hookSpecificOutput": {"hookEventName": <event>, "additionalContext": "self-learn <record-id>: <message>"}}` (the deny message's prefix, added by the orchestrator's review) and exits 0, on no match it exits 0 silently, and it FAILS OPEN — a missing jq, empty or malformed stdin, a broken regex or the ERR trap exit 0 and print nothing. The JSON line is built at generation and embedded single-quoted; it is refused above 7,500 bytes. A deny block with no mode produces byte-identical scripts (the orchestrator's oracle hash is pinned in `test_hook_compiler.py`). **(3) Replay** learns warn (allow prints nothing; warn prints exactly the event and message) and runs at route pre-flight, sheet hooks, activation and — new, a deviation from the brief, which assumed it already did — the doctor (`selfcheck._check_hooks` replays each live, byte-intact hook's recorded examples: a fail-open hook that stopped firing is otherwise invisible). **(4) Event.** `settings_snippet`, the route's manual steps, activation, deactivation and `reachability._rp_hook` read the event from `routing.hook` (none = PreToolUse); `_merge_snippet` and `deactivate` refuse the same script registered under another event. **(5) Writers told:** the steward's brief (from the constants), `steward-method.md`, `routing-doctrine.md` §5.1, the overseer's `formats/` (the re-decide example is now the `lrn-19f82fc5` shape as a warning hook, plus a PostToolUse warning and a deny example; `closed-sets.yaml` gains `hook`). **(6) The reconsider preview:** `batch.dry_run(reconsidered=)` previews the lines a staged `kind: reconsider` case covers as apply time will (a `verbs.PreviewReconsiderCase` placeholder, a type no text can produce, never written); `steward._ledger_repair_message` and `_forced_parking_reason` pass it. FW-161 item 3 (hooks that run a command) and other events stay open. Builder report: `misc/pipeline-design-2026-09-26/advisory-hooks-build/`.
- **2026-09-28 — (steward, overseer, verbs, batch) U3b: the steward's authority — always-loaded lines under the combined test, hooks, re-deciding placed lessons, its own rule globs.** The user, 2026-09-26 20:48: "yes. let it do that kind of work and leave the overseer the job of corrercting it if it makes a mistake." New decision row **S-72** in `03-decisions.md` supersedes **SA-1**'s trial hold (the hold lived only in the steward's brief; nothing in code parked an always-loaded route). **(1) The combined test.** The user, 2026-09-26 19:37, asked for the three questions "enmeshed" with the three existing tests; the combined wording (orchestrator, shown to the user) is `always_loaded.TESTS`, carried verbatim by `steward-method.md` §14 and `routing-doctrine.md` §2. **All three must hold** — the orchestrator's decision under the user's 2026-09-28 delegation, not a user ruling. A decided steward or overseer case whose sheet routes to `claude-md` or `claude-md:local` (the ALWAYS load class, any scope; a dest-less route is tested through its proposal) must carry `decision.always_loaded` with `because` and `refs` per test, every ref one of the case's own evidence refs as recorded; otherwise that case alone is refused (steward: a pair problem the repair turn sees; overseer: the pair is dropped) (`02-schema.md` §3a.2). The analyst's "any ONE promotes" check stays until U5. **(2) Hooks.** A route line may carry `hook: {rationale, hook: {tools, path_regex, deny_message}, examples: {allow, deny}}`; the CLI still generates the script (never the model), and validates, secret-scans and replays it by the one-motion chain (`verbs._prepare_sheet_hook`); `route --dry-run` previews that chain, so a failed replay is a `bad-line` refused alone. `batch.HOOK_ROUTING_ACTORS = {overseer, steward}`; the steward's runner passes `overseer.hook_activation`, so off means placed with the delegated receipt. The runner no longer parks hook routes (`13-hosting-and-separation.md` §7.4). The compiler was deny-only at U3b: a warning was not a hook (S-73 added warning hooks the same day). **(3) Re-deciding.** Under a valid `kind: reconsider` case over a routed lesson, a `route` line is applied as `reroute` (`batch._dispatch_reroute`, previewed through `verbs._reroute_plan`); `reroute` may now go into a hook with the line's compile input; `outcome: route` applies to a routed record. Re-decidable FROM claude-md (any variant), skill-md, new-skill, reference, hook; TO claude-md/local/rules, skill-md, reference, hook (never new-skill). `classify` now tells claude-md's variants apart. The case must supersede one that covers the lesson (`commands/review.md`). **(4) Globs.** `rules_paths` on a `claude-md:rules:<topic>` line, shape-checked at sheet load with the proposal's own rule, reachability-checked where every rule's globs are, winning over a proposal's. **(5) Formats.** The steward's output contract gains the three authorities and `AUTHORITY_EXAMPLES` (one pair each for always-loaded, hook, re-decision, rule globs); the overseer's `formats/` gains `case-/sheet-redecide-example.yaml` (the run `ec93fb36` shape), `sheet-rule-example.yaml` and `case-always-loaded-example.yaml`; every example is fed through the runner's checkers in `tests/test_u3b_steward_authority.py`. Tests rewritten to the new rule: the steward tests that relied on the runner parking a hook route now use a case the model parks as `hook`; `test_batch_hook.py`'s non-overseer actors no longer include the steward; `test_u_verbs.py`'s not-applicable outcome pin moves to `rehome`.
- **2026-09-28 — (steward, overseer, verbs, invocation, doctor) follow-ups the user delegated.** The user, 2026-09-28 15:17 PDT: "i trust you to deal with the questions." The questions were raised by the builders of batch-0928 (merge `9940b03`); each decision below is the orchestrator's under that delegation, not a ruling of the user's. (1) *A moved lesson updates both files:* the post-run recompile also compiles the target a `rehome`d or `rescope`d lesson resolved to in the bucket it left, noted before the sheet is applied (`verbs.move_origins`), so a line it left there goes in the same run — before, only its new target was compiled, and when it was the old file's last lesson no recompile ever revisited that file (`02-schema.md`, the runner's owed host writes). A moved record is pending or deferred, so such a line is one a refused host write left behind (a reopen or reconsider-defer whose host commit a hook refused). (2) *A host that keeps refusing tells the user once:* when the post-run recompile's write to a target is refused by the host's commit (a route's own refused host phase reaches the same pass), the runner notifies the user through the existing notify path once per distinct cause — target plus what git said, request and message ids stripped — journaling each told cause as `host-refused-told`; a cause already told is never told again (the plain reading of "once"; the environment hold compares with the last hold only). (3) *A secret hit outside the overseer's pairs costs that file's contents:* a secret-scan hit in `findings.yaml` means no findings (as an unparseable one), in `user-model-delta.yaml` no user-model updates, in `report.md` a committed report of the runner's own lines plus one stub naming the rule; the staged file is rewritten before anything reads it, so the text never leaves the stage. The run no longer refuses whole for these three; a hit in any other stage file still does (`02-schema.md`, overseer phase-B pairs). `test_secret_evidence.py`'s report case and `test_overseer_run.py`'s whole-run secret refusal (now exercised by a stray stage file) are rewritten; every "the token never lands" assertion stands. (4) *An all-dropped run says so:* the overseer's run record counts the decisions (case/sheet pairs) phase B staged and how many were dropped before the ledger; when any was, the report's "Decided in the user's stead", the `overseer run` text line and notification, and the JSON's new `status_text` read e.g. `applied (0 of 3; 3 dropped)`, while `status` stays `applied` (the CLI exit code and the UI key on it) and the JSON adds `decisions_staged`/`decisions_dropped`. Shown whenever any decision was dropped, not only when all were. The steward needs nothing: a dropped steward case already counts as `refused`. (5) *The steward cannot read the transcript copies:* `Containment` gains `read_denied`, and the steward's containment names the cache's `sessions/` (a new `sessions_dir` scalar of `containment_for`); the charter's read step (3a) now runs when a containment names read roots OR deny roots, and `_read_decision` refuses a Read, Grep or Glob whose resolved path lies inside a denied directory, or a Grep/Glob rooted above one. The steward's reads under `~/.claude/projects/` stay open. This changes `build_can_use_tool`'s body (two lines and its step-3a docstring), so POL1's pin of that body is re-anchored at the commit that made the change, with a dated note, the way `74948d5` re-anchored it at `4aa5ab6` (`02-schema.md`, the overseer's workspace; `13-hosting-and-separation.md`, session copies). (6) *Show how big the kept transcripts are:* `self-learn doctor` (`doctor invocation`) prints a last row, `sessions`, always INFO: the file count and total size of `<cache>/sessions/`, or `none kept`; it resolves the cache without creating it, as the `serve` row does (`17-invocation-runbook.md`, the doctor's rows).

- **2026-09-28 — (invocation, steward, overseer) a copy of every model session's transcript, kept per run; summarized thinking on.** The user's words, 2026-09-28: "go ahead and just capture everything" — a durable record of every model session self-learn runs, kept per run, to look at later. Every session the seam starts (the miner's reader, the worker and its repair round, the analyst, the steward and its repair turns, the overseer's two phases) is a Claude Code session whose own transcript Claude Code deletes after its cleanup period. After each session ends, finished or failed, the seam (`invocation_sdk/backend.py` `_drive`, through the new `session_copies.py`) copies that transcript — found by session id under Claude Code's `projects/` directory, plus any `subagents/` files beside it — into the CACHE, never the ledger, at `<cache>/sessions/<surface>/<run id>/<session id>.jsonl` (`13-hosting-and-separation.md` §6). The session id comes from the result message, or from the first message that carries one, so a timed-out session is copied too. The steward and the overseer name their run id as the folder (`SessionSpec.transcript_group`); every other surface uses the seam's per-session run id, the one in the matching `tool-events` log's name. What is recorded is a small record — session id, the copy's path relative to the cache (an absolute path trips the secret scan's high-entropy rule on the `home-<hash>` segment, measured), its size, and counts of transcript entries by `type` and of assistant content blocks by block `type`; counts only, never text. It lands on `SdkOutcome.transcript`, in every session's `tool-events` meta line (the per-session journal every surface has), in each steward `attempts` row as `session` (decision, repair, and a transient retry's first call), and in the overseer's journal (`phase-a-returned`/`phase-b-returned`, `transient-retry`) and run record (`sessions`, one row per session, tagged with its phase) (`02-schema.md` §3a.5). A copy that fails is a record with an `error`, never an exception: it never fails the session or the run. Every session also passes the SDK option `thinking={"type": "adaptive", "display": "summarized"}` (claude-agent-sdk 0.2.134), so the kept transcripts carry summarized thinking. One registry setting, `sdk.capture_sessions` (default on), turns both off. No prompt builder reads `sessions/`: a sentinel planted there never reaches the steward's brief or stage, or the overseer's prompts or workspace (`tests/test_session_copies.py`). Copies are never pruned. Armor: `test_invocation_sdk.py::test_op14` pins the option set; it gains `thinking` under a dated `Behaviour.edited` door (`EXM3.census_edited` 1 → 2, `BEH3.control_edited` 193 → 194).

- **2026-09-28 — (steward, overseer, verbs, serve, telemetry, miner) fail-state batch 2026-09-28: the rest of the small items.** The user's words, 2026-09-28 11:54 PDT, on the list of small items: "fix the rest of 3"; standing since 2026-09-27 06:58: "Make the fix. Look for any other similarly outlandish fail states." **(D)** The steward's stage reader put the YAML parser's own message into its errors, and that message quotes the model's text around the error; when no case/sheet pair passes, that error is committed to the run record. It now uses the overseer's rule through one shared helper, `scan.yaml_error_text` (file, problem cut at its first quote, line and column; a problem that still matches the secret scan becomes a fixed phrase); `overseer/run.py`'s `_yaml_error_text` is that helper. **(E)** Retiring a hook-routed lesson in a git-mode host runs `git rm` on its guard script and commits; when a pre-commit hook refused that commit, the script was left deleted and staged in the user's repo, where the user's next commit would carry it, and `recompile` never retried it because the script was already gone. Sweep 2 R3's rule now covers the removal (`verbs._remove_hook_script`): the script is put back (its directory recreated if `git rm` removed it) and unstaged, the warning says the removal is owed, and `recompile` removes it once the commit can land, reporting it as skipped until then (doc 13 §4 item 2). **(F)** A host write a steward or overseer run left owed (sweep 2 R3's refused host commit says "run `self-learn recompile`"; `_move` never recompiles a rehomed or rescoped routed lesson's target) waited for a person. After a run that applied a `route`, `rehome` or `rescope` item (or left one `unresolved-host`), the runner now runs one recompile of those records' own targets (`verbs.post_run_recompile`, over sweep 2 R2's `only_records`), after `_run` has released its locks and before the run's push; journaled, never raising out of the run; a target it skips is reported in the run's result (`recompile_skipped`) and the CLI line, not retried in a loop. A periodic `serve` job was considered and not taken: it would rewrite registered hosts' files on a timer with no triggering action and nobody watching, and it is the ledger-wide shape R2 backed away from (one unrelated skipped target became every item's problem); the post-run form touches only targets this run's own verbs made stale, once, and reports in the run that caused it. Known limit: a rehomed routed lesson's OLD target keeps its entry until an ordinary `recompile`. `test_overseer_run.py`'s boundary-push test now finds the run's journal row by its key, since the recompile row follows it. `commands/review.md` (Steward run). **(G)** The morning audit's findings 9, 10, 12, 13 and 14 (`misc/failstate-audit-2026-09-27/REPORT.md`, untracked; 11 was this batch's earlier unit, the overseer's own workspace). **9:** each overseer phase-A entry (`selection.yaml`, `initial-views.yaml`) and each phase-B case/sheet pair that fails a check is dropped and named instead of refusing the attempt; a selected case left without a valid initial view is de-selected; a pair is dropped whole, never item by item, because a pair is one decision; a secret-scan hit in a pair drops that pair, a hit anywhere else still refuses the run. **10:** a steward reconsider case whose outcome does not fit its lesson is refused alone instead of escaping the run. **12:** the overseer keeps holding the commit lock through phase B — the most conservative reading: narrowing it would split the run's intent and let the ledger move between what the model read and what the run applies, which is a redesign; the only false claim, the worker's `_harvest` docstring saying a lock refusal "costs nothing", is corrected (in stage mode the batch's model call is lost; its lessons are analysed again). **13:** a telemetry line the secret scan refuses moves to the cache's `spool-rejected/` and the rest flushes (`11-telemetry-and-lifecycle.md` §4.2). **14:** a `hosts.yaml` that does not load holds only the skill-scoped mine candidates, with their sessions' cursors held. Rewritten to the new rule: `test_overseer_run.py`'s and `test_overseer_health.py`'s caseless-sheet tests (the misfit pair is dropped, not the run), `test_secret_evidence.py`'s two overseer secret tests (a hit in a pair drops the pair; a hit in the report still refuses; no successor and no token in the ledger either way), `test_telemetry.py`'s and `test_audit_fixes.py`'s flush scan-hit tests. The telemetry hold-back is `telemetry._hold_back`, one `NOT_REPO_TRUTH` entry in `test_lock_invariant.py` and one `keep` entry in `test_raw_write_gate.py` (both cache files). Tests: `tests/test_batch0928_steward_yaml_text.py`, `test_batch0928_hook_removal_refused.py`, `test_batch0928_post_run_recompile.py`, `test_batch0928_audit_findings.py` (`02-schema.md` §3a, "Fail-state batch 2026-09-28").

- **2026-09-27 — (records, verbs, steward, overseer, reconcile) fail-state sweep 2: one bad file or one refused host commit costs that item, not the unit around it.** The user, 2026-09-27 06:58: "Make the fix. Look for any other similarly outlandish fail states." Sweep 2 of the fail-state audit (`misc/failstate-audit-2026-09-27/sweep-2/REPORT.md`, untracked, with its probes `test_sweep2_probes.py`) reproduced four more ways one small bad thing wasted a whole unit of work; none had fired on the live system. **R4:** `Record.from_text` let the loader's own exception escape (ruamel `YAMLError` for an unclosed bracket, a duplicate key, a conflict marker; `ValueError` for an impossible date), so the miner's prompt and landing, the worker before its model call, and `recompile` crashed on every run while one such file existed. It is now `records.FrontmatterLoadError` (a `ValidationError`), its message naming only the error type and position, never the file's text; a list or mapping where a scalar belongs (`status: [x]`, which raised `TypeError` in `validate`) is a `ValidationError` too. The miner reports such a file in its `corrupt_records`, the worker's three context passes skip it and name it in worker.log, `recompile` skips it and names it in its warnings. **R3:** a host repo's pre-commit hook refusing one self-learn commit (the machine-wide gitleaks guard runs in block mode on every git-mode host) left the compiled file written and staged in the user's repo, so every later route to that file was refused as dirty, and `recompile` let the `GitOpsError` abort the whole repair. Now the host files a compile can write are snapshotted first and, on a refused commit, put back and unstaged; the ledger commit stands (H-2) and the next `recompile` retries; `recompile`'s managed, reference and hook legs skip only the refused target, with the hook's message (doc 13 §4 item 2). The refused lesson stays in its target's compile set, so later routes to that file are refused by the hook the same way until a person allowlists the finding or edits the lesson. **R2:** steward and overseer crash recovery established a recovered route's host result with a ledger-wide `recompile`, which rewrote every other stale target and turned any unrelated skipped target into this item's `unresolved-host`, halting the packet; it now runs `recompile(only_records=[id])` and `recompile_refusals` (02-schema.md, continuation). **R1:** `reconcile` refused its WHOLE batch when any one uncommitted file was invalid (M-C, "all-or-nothing"), which kept the miner's landed-but-uncommitted records uncommitted run after run. The orchestrator recommended that an invalid leftover hold back only itself and what depends on it, with a stopped intent still refusing everything; the user accepted ("yes", 18:54). Dependencies come from the writers (a proposal on its record, a merge proposal on its members, a bucket's orphans on its own new `meta.yaml`); a half-committed rename holds back only its own record; held dependants are named in a new `held` list; `self-learn reconcile` exits 8 when it committed the rest and 6 only when nothing was committed (reconcile.py module docstring, doc 13 §5, `commands/review.md`, `commands/teach.md`). Tests: `tests/test_sweep2_unreadable_record.py`, `test_sweep2_host_commit_refused.py`, `test_sweep2_recovery_own_target.py`, `test_sweep2_reconcile_holds_back.py`; `test_reconcile.py`'s blocked-rename test now asserts the new rule.

- **2026-09-27 — (overseer) a stage file that does not parse costs what it carries, not the run.** The hand-started overseer run `c2b9192b` (17:32–18:00 PDT) finished both phases, examined all 57 cases and staged three decided cases with sheets, and was then refused whole with nothing applied, for one reason: "findings.yaml: cannot parse: mapping values are not allowed here … line 64, column 87" — a plain (unquoted) `text:` value held ": " mid-sentence. This is the shape the user's 06:58 words cover: "Make the fix. Look for any other similarly outlandish fail states." `overseer/run.py` now raises `_YamlParseError` (a kind of `OverseerError`) for a stage file that is not YAML, and phase B treats it per file: an unparseable `findings.yaml` reads as no findings (so no selected case counts as examined, the report's "Cases examined" line reads `none`, and `coverage.yaml` advances for none of them); an unparseable `case-<name>.yaml`, `sheet-<name>.yaml`, `case.yaml` or `sheet.yaml` drops that pair alone, the other pairs going ahead; an unparseable `user-model-delta.yaml` means no user-model updates this run. Each is one line in "Refused / could not do" and the run record's `runner_notes`, naming the file, the parser's problem and its line and column — never the model's text: the parser's own message quotes the source around the error, and its problem can quote an alias, tag or character from it, or a duplicate key's values (which can hold quotes of their own), so the line keeps only the position and the problem cut at its first quote character (a problem that still matches the secret scan becomes "not valid YAML"). That message is built once in `_yaml_mapping`, so a phase-A refusal for an unparseable `selection.yaml` or `initial-views.yaml` — whose behaviour is unchanged: it still refuses the attempt — no longer carries the model's text into the committed failure note either. `questions.yaml` already read as zero questions and is unchanged. Unchanged too: a file that parses but has the wrong top-level shape (not a mapping, or `findings.yaml` without just a findings list) still refuses the run; a required file that is missing still refuses; and the whole-stage secret scan still runs on raw text first, so an unparseable file that also holds a secret still refuses the run. Both phase prompts now say to write every free-text YAML value as a block scalar or a double-quoted string, because a bare value containing ": " does not parse. `02-schema.md` (Findings; the overseer fail-state bullet) says the same.

- **2026-09-27 — (overseer) the journal is asked for as a work log.** The overseer's two retries on 2026-09-27 (runs `3d21f1f7`, `0972ab85`) were refused by Anthropic's API safety classifier with the tag `[reasoning_extraction]` about eight tool turns into phase A, and the week closed with nothing decided. Anthropic's docs define that category as a request that "asks the model to reproduce its internal reasoning in the response text" and say to read structured thinking blocks instead. Replays of the failed stage traced it to one phrase of the 2026-09-24 journal paragraph (5 of 6 refused with it; 0 of 10 without it). The journal is now asked for as a work log: per case or settled point, the ids, what was found in the files, what is still open, what was decided on which evidence, what evidence would change the decision, and a new entry when a later finding overturns an earlier view. Every part passed the replays; asking for "the other options considered and why each lost" was refused 2 of 3 times and is left out. The phase-A line that the journal must not guess at the steward's decisions is kept in the replayed form. The old wording is not quoted in the corpus: quoting it gets conversations refused. **The user's words, 13:30:** "focus on the prompt rewording first. i'll only accept a fallback model as a last resort." **17:03:** "go ahead." Full record: the orchestrator's z-note `F3JSdK54PrI1PlOWNnv5S`. Code: `overseer/run.py` `_journal_block`, `_phase_a_prompt`. Spec: `02-schema.md` (Journal).

- **2026-09-27 — (steward, overseer, serve, invocation) fail-state batch 1: a bad item costs that item; a failed model call is handled by its kind; nothing crashes uncounted or unlogged.** The user, 2026-09-27 06:58: "Make the fix. Look for any other similarly outlandish fail states." The fail-state audit (`misc/failstate-audit-2026-09-27/REPORT.md`, untracked, with its probes `test_failstate_probes.py` and `probe_validators.py`) found 14; the orchestrator recommended fixing findings 1–8 as one batch and the user approved it (13:11, "1. go."). At 13:30 the user narrowed unit 4: "i'll only accept a fallback model as a last resort" — so no fallback model and no `models.safeguard_fallback` setting were built. Eight units, one commit each. **(1)** The overseer runs the case writer's own rules (`cases.check_case_data`) on each staged decided and maintenance case during phase-B validation, as `cases.record` will see it; a case that fails is dropped with its sheet and one "Refused / could not do" line (file, parked case, rule — never the model's text); at execute time a `cases.CaseError` refuses that case and its sheet as final refusals and the run carries on, instead of halting every later case on every resume. **(2)** The steward keeps its validated first pass (in the cache, outside the session's writable directory) while the repair turn runs; a repair call that fails, a stage it leaves invalid, or one that flags more (or a file the first pass had clean) is undone and the first pass goes ahead; only what it still flags is refused, case by case, at apply time. **(3)** The steward's stage is judged pair by pair (`_check_stage`): an undeclared file is quarantined into a run-scoped cache directory and never reaches the ledger; each case/sheet pair and its coverage is checked on its own and a pair still failing after the repair turn is set aside; a lesson no passing pair covers stays `unfinished` (reason `not-covered`) and, when nothing else of the packet is open, the next attempt asks the model about the open lessons only; only a bad non-pair file or no valid pair at all fails the stage. **(4)** A failed model call is classified in one place (`invocation.failure_class`, carried on `SdkOutcome.failure_class` and in the event log): `transient` (overloaded, 5xx, rate limit, network) is retried once within the attempt after a 30 s backoff; `environment` (unsupported model or Claude Code version, auth, not found, a refused provider) is a hold — not an attempt — journaled `held-environment` and notified once per distinct cause; `safeguard`, `content` (Claude Code's own turn or spend limit) and `unclassified` are counted as before, with the class and the API's tag (e.g. `reasoning_extraction`) in the steward's run record and the overseer's failure note. The miner and analyst only gain the field. **(5)** The overseer steps after phase A never crash uncounted: an orphan `sheet-<name>.yaml` is dropped with a trace; a case in the window that cannot be classified into a coverage stratum is left out of coverage with a trace (`population.stratum_problem`; `coverage_update` itself is unchanged); a raise in `_full_inputs` or `_prepare_manifest` goes through the ordinary in-span failure path (note that counts, coverage put back). **(6)** `serve` logs a crashed job: error and traceback to stderr (the service log) and a `crashed` row in the job's own journal, or `serve.journal.jsonl` in the cache for a job with none. **(7)** Each overseer phase's time limit is `max(overseer.timeout_secs, 30 s × the cases it reads)` (measured 559 s/54 cases and 810 s/57 cases against a flat 900 s; 30 s is about twice the worst rate); a phase B that timed out after writing every file a run needs is checked like a finished one and what passes applies (any other failure still applies nothing — the 2026-09-24 turn-limit rule); a validated phase A is kept in the cache, keyed by week and a hash of the population shown to the model, and reused by the week's next attempt when the population is unchanged. **(8)** The steward refuses a step only for an unexplained change to a file that step commits (every commit is path-scoped); any other uncommitted ledger path is journaled (`unexplained-paths`) and notified once per distinct set, and never committed. Tests: `test_failstate_overseer.py`, `test_failstate_steward.py`, `test_failstate_model_failures.py`, `test_failstate_serve.py`; tests that encoded the old whole-packet or whole-ledger rule were rewritten to the new rule, each named in its commit (`02-schema.md` §3a, "Fail-state batch 1"; `13-hosting-and-separation.md`, "A job that raises is logged").

- **2026-09-27 — (overseer) a malformed finding costs that finding, not the run.** The weekly overseer run `a3c1df7c` examined 52 of 57 cases, then `_validate_findings` refused the whole run because ONE `dependency-moved` finding had no `ref`: no decisions, no questions, nothing kept. The orchestrator recommended the rule the user had already accepted for the steward ("a bad case costs that case", `5b6be09`); the user's words, 2026-09-27 06:58 PDT: "Make the fix." `overseer/run.py` `_validate_findings` now drops each failed finding and names it (ordinal and selected case id, never the text) in "Refused / could not do" and the run record's `runner_notes`; a selected case with no valid `examined` finding is reported "not examined", left out of the report's "Cases examined" line, and coverage is recomputed from the validly examined cases only, so it does not count as covered this week. A findings file that is not a mapping holding just a findings list still refuses the run; the whole-stage secret scan of `findings.yaml` is unchanged. `02-schema.md` gains a **Findings** paragraph beside **Questions**. Tests: three in `tests/test_overseer_run.py`.

- **2026-09-27 — (steward, verbs, serve, method) what the steward reads: the lesson and what code checked about it, in related batches; suspected rule violations become its inputs.** U3a of the pipeline redesign (plan `misc/pipeline-design-2026-09-26/PLAN.md`, untracked; unit order approved by the user 2026-09-26 21:58). The user's words, 2026-09-26: the pipeline is "a series of builders … miner finds lesson material > steward builds lessons > overseer builds a coherent system out of those lessons"; on retiring the analyst, "basically, i think i agree with you"; on the audit's suspected violations, "do both a and b", (b) being that the ones the miner records go to the steward; on relatedness, "lessons from the same project but different sessions count as related"; on the UI, keep no current functionality but make data points for a future dashboard easy to gather. The evidence is the 2026-09-26 miner-output audit (the steward read only the analyst's card, with no session or line; 117 record reads and 94 transcript calls over 9 runs; a lesson approved on a verification the transcript contradicts; fires with no consumer). **Eligibility:** a queued lesson is selected with or without an analyst proposal, and its identity is the record's committed blob (a proposal rewritten beside it changes nothing; a record edit is a new version); a version a run decided under the old proposal identity is still decided, and a lesson sent back under it still shows as sent back. **Batches** are §3a.7's groups (at most 10, at most 5 unrelated) over an index refreshed in the cache at run start; `steward.packet_size` can only lower the 10. **The brief** replaces the analyst card: the record's own lesson sections with their file lines, an evidence pack built by code with U1 (resolved ref, quote verdict with the corrected ref, a redacted excerpt with who spoke on each line; `stitched` and `not_found` shown as not checking out), the five closest existing lessons of any status, and the links that batched it; the output contract now asks for `dest` on every route. **Suspected violations:** an unhandled `suspected-violation` fire (legacy `violated`) about a routed record is a new input kind, decided with the existing `confirm-recurrence` / `dismiss-suspect`, whose preflights now also take a fire's nonce (no new verb; no `recurrence-suspect` is spooled); handled events are never offered again. **Data points:** the run record's `grouping`, each packet's `group` (basis counts cosine / lexical / none), and each attempt's `brief` (pack sizes, verdict counts) and `reads` (transcript and record reads the session still made). `steward-method.md` §§ intro, 2, 3, 9, 10 rewritten for the new brief ("a claim whose evidence does not check out is not established"). Budgets measured on the live ledger read-only with word search only (no embedding call): `02-schema.md` §3a.8 has the numbers. `02-schema.md` §3a.5 and new §3a.8; `11-telemetry-and-lifecycle.md` §4.3 (who reads fires). The web UI was not touched.

- **2026-09-26 — (index, schema, host unit) related-lesson search: a cache index over every record, the relatedness rule, and the steward's batches.** U2 of the pipeline redesign (plan `misc/pipeline-design-2026-09-26/PLAN.md`, untracked; unit order approved by the user 2026-09-26 21:58). New package `index/`, ported from the user's own `keys` project rather than written fresh (each module names its source file): the stdlib Gemini client (`gemini-embedding-2`, 100-per-batch cap, one request per text, bulk and interactive retry profiles, RPM pacing, truncation detection), the provider protocol and deterministic fake, FTS5 word search, reciprocal-rank fusion, hybrid ranking with total fallback to words, and the blob vector store (without its optional sqlite-vec and numpy paths). New: the index itself in the cache (`index/lessons.sqlite`: every record, incremental by text hash, vectors keyed by model), `related(a, b)` (same session or same entry uuid; or same bucket `(scope, name)` and similar), `group_for_steward` (at most 10 per group, at most 5 unrelated; the user's rule of 2026-09-20), and `self-learn index status|build|related|groups`. The key comes from the environment only (`SELF_LEARN_GEMINI_API_KEY`, then `GEMINI_API_KEY`); without it, or with the API failing, the index is word-search only and says why. `systemd/self-learn-host.service` gains the optional `EnvironmentFile=-%h/.config/self-learn/env` the user fills from Bitwarden Secrets Manager (user, 19:32: "don't wire bws into the project itself"); inert until the unit is reloaded. The thresholds were measured over the live ledger in one embedding pass: cosine 0.75 for `gemini-embedding-2@3072/i1`, lexical 0.16 (`02-schema.md` §3a.7 has the distributions). The Gemini client refuses a real call under pytest. Code only: the steward does not read the index yet (U3). `02-schema.md` §3a.7, `13-hosting-and-separation.md` §6.

- **2026-09-26 — (refs, schema) the checked pointer: a transcript ref every later pipeline unit writes to.** U1 of the pipeline redesign (plan `misc/pipeline-design-2026-09-26/PLAN.md`, untracked); the user approved the unit order on 2026-09-26 21:58 ("yes, i'm good with the order"). The evidence is the 2026-09-26 miner-output audit: of 43 mined quotes only 27–28 sat verbatim at their cited line, one was in the wrong session, two were stitched from pieces with "…", and the steward had to hunt for transcripts (no project folder in the pointer, a one-line stub copy under a second folder, the evidence `ts` being the miner's run time). New module `refs.py`: the ref shape, a resolver that finds the real file across project folders and the archive, a seven-outcome quote check, uuid-based duplicate detection and bounded, redacted excerpts; new registry setting `refs.transcript_roots`. New section §3a.6 in `02-schema.md`. Code only: the miner and the steward do not use it yet. Measured over the audit's 43 records: every exact, normalised, nearby and elsewhere verdict reproduced record for record; of the five the audit could not find, one resolves to the other session holding it, two are stitched, two are genuinely absent (one quote fixes the user's typo, one rewords the source).

- **2026-09-26 — (scan, batch, verbs, steward, overseer, serve) a model is never shown a secret's matched text, and a dry run no longer holds back the real run.** Agenda items 24 and 25 of the running z-note, found by the agenda-defects builder; the user approved fixing them (2026-09-26, "yesyesyes" for items 24–26; item 26 belongs to the steward redesign and is not in this change). **(item 24)** The steward's repair turn relayed the ledger's refusal of a sheet line whose `note` held a secret with the matched span in it (`verbs._scan_or_refuse` builds its message with `format_refusal`, and `batch` copied `str(exc)` into the item's `detail`): the secret never reached the ledger, but the model saw it and the run record kept it. The same `detail` fed the sent-back rows, the case results, and the overseer's "Refused / could not do" lines. New `scan.refusal_text(exc)` withholds every span the error (or the error it was raised from) carries, then any span a scan of the text still finds; `batch` uses it for every item detail and receipt failure, `route --dry-run` for its `would_refuse` entries, and the steward and overseer for the apply-time refusals of a case, statement or user-model write, whose errors now carry their hits (`scan.attach_hits`). Scrubbing at the batch seam also changes what `self-learn batch` prints to a person, deliberately: `/review` runs it through a model too. A verb run by hand still prints the span. `02-schema.md` (after the repair-turn paragraphs) states it. **(item 25)** A steward or overseer `--dry-run` wrote cache-journal rows (`model-log` above all, and `refused`, `population`, `phase-a-returned`) whose statuses are not holds, so serve's `_journal_attempt_epoch` read the newest of them as an attempt and the real run waited out the cache-side cooldown behind a rehearsal. Measured: that cooldown is `miner.ATTEMPT_COOLDOWN_SECS` (2 h), not `steward.cooldown_secs` (72,000 s) -- the committed `last_attempt_at` / `steward.last-run` check that uses 72,000 s is never written by a dry run. Every row a dry run writes is now marked `"dry_run": true` (a module flag set for the run's duration in `steward.run` and `overseer.run.run`; not a ContextVar, because the model-log callback may fire from another thread), and `_journal_attempt_epoch` skips a marked row. A real run's rows are unchanged. `02-schema.md` (the attempt rules) states it.

- **2026-09-26 — (steward, invocation) the steward's brief: the machine description cut down, and the part a run shares read from the prompt cache.** The user, 2026-09-26 17:46 PDT, of the steward's `=== conditions ===` block: "cut it down and let me know what we're left with." The specific cuts are the orchestrator's choices, grounded in the 2026-09-20 forensic count of which rows 26 real cases cited. **Part A.** The steward now reads `conditions.steward_feed`, not the whole feed: the rows no case used are gone (`report.destinations`, `report.open_followups`, `report.recurrence_suspects`, every `host.<path>.head`, every `models.*` but `models.steward`, `sdk.max_turns.*`, `status.*`, `steward.*`, `overseer.*`); the small rows stay in the table; each remaining `report.*` section is a YAML sub-block after it, headed by its own citation `cond:report.<name>@<observed_at>`, in place of a Python `repr` inside one escaped table cell; `report.routed_live` and `report.surface_reach` are sliced, once per run over all its lessons, to the buckets (`scope`, `name`) and scopes those lessons can reach and the records they name (`02-schema.md` §3a.5, "The steward's cut"). `conditions.feed` itself is unchanged: the overseer reads it whole and filtered and needs the rows the steward no longer sees. Replayed on the real values of run `run-1ca3de428b35` (2 lessons), the block goes from 82,703 to about 50,700 characters with one user-scope and one project lesson, and to about 46,100 with two project lessons; the user-scope bucket alone keeps 49 routed records and 48 surface rows. Two findings the spec's evidence predates: the `steward.*` rows were no longer dead (they read the committed run records since 2026-09-22; they are cut as never cited), and the duplicated host row was already fixed. **Part B** (the user, same message: "you know what to do with caching."). The brief is sent in two parts (`02-schema.md` §3a.5, "The brief's two parts"): the shared part — method, conditions, output contract, identical for every packet of a run — is appended to Claude Code's system prompt from a file in the run's cache stage (`SessionSpec.append_system_prompt_file`, passed as `--append-system-prompt-file`), with `SessionSpec.exclude_dynamic_sections` on; the per-packet part — containment, user model, sent-back, open cases, briefs — is the user message. Both fields are new, typed and default off, so the worker, the miner, the analyst and the overseer send exactly the options they sent before; a session with the file refuses to start rather than drop it when the SDK cannot pass it, and refuses a file together with `doctrine`. The repair round is a new session and carries both. Each call's prompt-cache counts (first response and session total) go into the event log's meta line and the packet's `attempts` row, which is how the first live run shows whether packet 2 read the shared part from cache. The method's sentence that the output contract "is the last block of your brief" now says where it is.

- **2026-09-26 — (steward, overseer, verbs, batch, serve) the agenda defect batch: a bad case costs that case; one broken file, one retryable refusal or one missing heading no longer costs a run.** The orchestrator listed items 8+13, 9, 14, 16, 17, 18, 19 and 22 of the running z-note's agenda and recommended building all of them in one serial batch; the user accepted that recommendation (2026-09-26). Eight units, one commit each. **(1, items 8+13)** The case writer's rules live in one function, `cases.check_case_data`, which `cases.record` calls and the steward's runner also runs on every staged case and parked.yaml entry as part of the check that feeds the one repair turn (evidence the runner drops is not a violation; a secret span is withheld); a case still in violation after the turn is refused alone, and the prepared-text secret scan runs per case and per maintenance operation instead of once over the packet, so one hit no longer refuses every case in it (`02-schema.md` §3a, "The steward's repair turn"). **(2, item 14 = N6)** `dismiss-suspect` secret-scans its `why` beside its note, in the verb and in `batch.dry_run` alike (kind `bad-line`, no bypass). **(3, item 17 = N11, Q20; N14)** An overseer resume re-drives the rest of a sheet that holds a FINAL refusal as a sheet with the same identity and item numbers minus the final refusals (batch's continuation contract is unchanged); every item that did not apply is listed under "Refused / could not do" with its kind and state; the cap close-out counts a retried-kind refusal as unfinished; the retried kinds have one definition, `batch.RETRIED_REFUSAL_KINDS`. **(4, item 18 = N8, N9)** A malformed `hosts.yaml` met while checking an unrecorded managed region refuses that item (`needs-person`), and the compile-set readers skip a resolved record whose frontmatter is not YAML. **(5, item 19)** A missing or misordered required heading in the overseer's report.md is repaired (an inserted heading's body says the overseer wrote nothing under it) and said under "Refused / could not do"; an unknown or repeated heading still refuses. **(6, item 22)** Steward journal rows carry `run_id` once it is known; a steward dry run writes one row marked `"dry_run": true`; serve's heartbeat is refreshed every half tick while a job runs and names it (`running`, `running_since`; `13-hosting-and-separation.md` §7.2a.7). **(7, item 9)** The steward's summary counts failed model calls (`failed_calls`, `all_calls_failed` in `--json`) and says plainly when every call failed; the overseer's dry run already reported a failed call as `refused`. **(8, item 16 = Q19; N13)** An overseer run whose only failure is a `git`/`target-busy` refusal stays unfinished so the next resume retries it, bounded by the attempt cap; a final refusal is unchanged; `commands/overseer.md` names `target-busy` and the `[kind]` suffix (`02-schema.md` §3a, "Refusal kinds"). Tests: `test_case_rules_repair.py`, `test_dismiss_suspect_scan.py`, `test_overseer_retry_beside_final.py`, `test_one_broken_file.py`, `test_report_headings.py`, `test_journal_heartbeat.py`, `test_dry_run_calls.py`, `test_overseer_retry_on_resume.py`.

- **2026-09-26 — (scan, steward, overseer) a folder path is not a secret; an evidence quote that matched the secret scan drops that quote, not the decision.** Steward run `run-1ca3de428b35` (2026-09-26 04:07 PDT) decided `lrn-2eb79751` and `lrn-4bb924c1`, and then the whole packet was refused by the prepared-text secret scan in `_prepared_recipe`: one evidence quote held a folder path, `/data/SteamLibrary/steamapps/compatdata/3669870/pfx/drive`, and the `high-entropy-base64` rule (`[A-Za-z0-9+/=]{40,}`, which never measures entropy) read it as a secret because `/` is in the base64 charset. Both lessons stayed pending and could hit the same wall every night. The orchestrator proposed two parts; the user approved both (2026-09-26 14:42 PDT: "both parts of the scanner fix, go for it."). **Scan:** a base64 run that starts with `/` and holds at least 3 `/` is judged per segment; a segment of ≥ 20 chars that is not pure hex still fires on that segment's span (a token hidden as `/api/v1/tokens/<random>` is caught), and the hex rule and every pattern rule are unchanged (`scan.py` docstring, `08-build-plan.md` §1). The carve-out is structural because entropy did not separate the two (real paths 3.75-4.34 bits/char, random 40-char base64 as low as 4.28). **Runners:** `cases.split_heading_evidence` became `cases.split_runner_evidence`, which in one pass drops an evidence item whose quote or ref has a `## ` line or a secret-scan hit (one pass, so "drop nothing when no evidence would remain" holds over both kinds). A secret row is `{ref, reason, rule}` with reason `a quoted line matched the secret scan (<rule>)`; any dropped row's ref is replaced by `(ref withheld: it matched the secret scan)` when it is itself flagged; no row, journal line or report line carries the quote or the matched span. The steward calls it where it called the heading helper, before its prepared-text scan. The overseer's whole-stage scan (`_secret_files`) no longer refuses the run over a successor case file whose every hit lies in evidence the runner will drop — each raw occurrence must be accounted for by a dropped item's quote or ref, and the case as serialized after the drop must scan clean — so a hit in any other field, a YAML comment, or `report.md` refuses as before. The steward's prepared-text refusal message, which is committed into the run record (`failure`, each disposition's `reason`), now names each hit's rule and offsets with the span withheld; before, it committed the matched text. `self-learn case record` (a person) stays strict. `02-schema.md` §3a states the drop. Tests: `tests/test_secret_evidence.py`.

- **2026-09-25 — (steward, overseer) an evidence quote that starts with `## ` drops that quote, not the decision.** Steward run `run-d8f5e198ff4f` (2026-09-25 08:02 PDT) decided `lrn-4b109d1d` (a route to the `~/.config` reference shelf, with a revision), and then `cases.record` refused the whole case: one evidence item was a verbatim quote of a heading line of the shelf file itself (`## 2026-08-19 — lrn-b197d06b`), and every free-text field is refused on a line starting `## ` (heading injection, D-i). The prompt told the steward both "quote is verbatim" and "no line may start with `## `", and quoting a heading of a shelf or a `CLAUDE.md` is natural evidence, so the two collided; the lesson stayed pending to be re-decided. The orchestrator proposed telling both agents how to quote such a line and having the case writer drop just that piece of evidence instead of the case; the user approved (2026-09-25 10:59 PDT). **Code:** `cases.split_heading_evidence` removes each evidence item whose quote or reference has a `## ` line, never rewriting the quote, and drops nothing when no evidence would remain, so that case is refused exactly as before. The steward's runner calls it in `_prepared_recipe` (for its decided cases and for the further questions it stages in `parked.yaml`, whose maintenance operation carries the same `dropped_evidence`) and the overseer's in `_prepare_manifest` — before the case text is frozen into the committed run record, so the quote never reaches the ledger. The recipe carries `dropped_evidence` (`ref` and reason, secret-scanned with the rest of the record); the steward journals an `evidence-dropped` line; the overseer adds `- case <id>: evidence from <ref> dropped — a quoted line starts with "## "` to "Refused / could not do". D-i is unchanged for every other field, and `self-learn case record` (a person) never calls the helper. Before this, the overseer's runner met such a refusal in `cases.record` at apply time and ended the run early, leaving that case and every later one for a resume that would hit the same refusal. **Prompts:** the steward's case contract and the overseer's phase-B prompt say to quote a heading line from after the `## `, and what happens otherwise. `02-schema.md` §3a (case Section 2) states the rule. Tests: `tests/test_heading_evidence.py`.

- **2026-09-24 — (overseer) questions have no cap and come in two kinds; the overseer keeps a journal; a hand-started run does not count toward the week.** The second real overseer run (2026-09-24 22:19 PDT, run `02227dc1`) finished both phases and was refused whole because it wrote ten questions against "at most three questions are permitted"; nothing was applied. Its prompt had never mentioned a limit or said what a question is for, and none of its ten ids (`q-…`) could have been opened anyway, since `overseer open` accepted only user-model propositions. The cap of three came from the orchestrator's plan (`misc/audit-2026-09-02/steward-design/plan-overseer-2026-09-12.md:282`), not from the user. **The user's words, 22:40 PDT:** "i think we uncap the number of questions, but make damn well sure it's being prompted well and using its questions well. also, instead of just questions, we could have a journal of sorts the overseer could uuse as a kind of scratch bucket. somewhere it can write down observations, decision making process, and basically a space for it to 'empty' itself." **On the journal, typed into a choice prompt:** "write only for now. it should be something it has access to throughout the run, not just once per phase or or once at the end. maybe we give it some basic instruction on acceptable formatting so it can carry forward things like lesson ids or other metadata that would be relevant". The user asked "do we need a size limit at all?"; the orchestrator answered no, so the journal has none and the report's 60 lines became guidance. **Two kinds of question** (a *reading* of the user, and an *ask* — a decision or fact only the user has): the orchestrator recommended this; the user accepted it. **The user's words, 22:49 PDT:** "user initiated runs don't count toward the weekly limit." Whether a hand-started run that completes counts as the week's review: the user selected "No, Sunday still runs" from options the orchestrator offered; the orchestrator recommended neither. **Code:** `overseer/run.py` validates `questions.yaml` entry by entry with no count limit and never refuses a run over questions — a failed entry is dropped and named in "Refused / could not do" (`- question <id>: dropped — <reason>`), a malformed file reads as zero questions plus one such line, and `questions.yaml` and `journal.md` are left out of the whole-stage secret scan and scanned by their own handling; a report over 60 lines is kept whole (it used to be truncated) with one runner line saying how long it ran, and missing or out-of-order headings still refuse. The phase-B prompt says what a question is for, the bar it must clear, and both kinds; both prompts carry the journal block. The journal (`journal.md` in the stage, created before phase A) is committed at `overseer/journal/<date>-<run>.md` with the committed recipe, the finalize, a partial finalize, a failed attempt's note and a push-failure record, carried in the run record for a resume, left out when it is only its header, and stubbed on a secret-scan hit. Phase B now reads the user's answers to earlier asks (`answers.yaml`; before this it saw no statement text at all). The phase sessions may use `Edit`, which the SDK charter already confines to the stage exactly as it confines `Write` (both are in its write family). `overseer open` shows every question (an ask's text and why from the index) and records a presentation for each; `overseer respond` answers an ask with a `question`-kind statement. A manual run (`self-learn overseer run`) adds nothing to the week's attempt count, is never held by a done or closed week, never closes one, and, when it completes, leaves `last_run_at` and the cache marker alone and is skipped by `week_done`. **Auto-memory off** (a defect the orchestrator verified the same night, not one of the user's asks): Claude Code's auto-memory was on inside the overseer's sessions; phase-B session `94505169` of run `02227dc1` wrote a `MEMORY.md` and two notes, one a "User-demand policy ruling", into the memory folder Claude Code keys to the stage path, which never changes, so every later overseer session, the blind phase A included, would have loaded them (the orchestrator moved the three files into forensics). Every overseer session and every steward session (its repair round included) now carries `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in its environment, through a new producer channel, `SessionSpec.extra_env`, which `CliSessionPolicy.env` lays under the provider's variables; the installed Claude Code (2.1.282) reads that variable. Spec: `03-decisions.md` S-66 and S-68, `02-schema.md` (question and journal shapes, attempt counting), `13-hosting-and-separation.md` §5 and §7.2a.7, `commands/overseer.md`.

- **2026-09-24 — (steward, overseer) a delegated run publishes what it committed.** Found the same day: the live ledger sat 41 commits ahead of its remote. Every steward write passed `no_push=True` and the steward had no push of its own (true since it was built, `646c7b4`), so its decisions reached the remote only when some later producer happened to push (on 09-23 an attended `route` at 20:58 carried the afternoon's run); the overseer pushed only on its completed path, so a failed attempt's note (`dc83ced`) and a partial report stayed local. `13-hosting-and-separation.md` §5's steward/overseer paragraph said each "commits under its own pinned subject" and was silent on pushing, against H-5 ("push their own writes"); it now says each run pushes once when it ends, however it ends. Code: `verbs.ledger_head` and `verbs.publish_after_run` (the bare `push` verb, only when the ledger `HEAD` moved during the run and something is still unpushed); `steward.run` and `overseer.run.run` are now thin wrappers that call the unchanged body (`_run`) and publish in a `finally`, journaling a `push` (or `push-error`) line; a dry run and a no-push request publish nothing, and the overseer's completed path, which already pushed, is not pushed twice. Tests: seven in `test_steward.py` and `test_overseer_run.py` against a local bare remote; six mutations (no publish in either runner, no `HEAD`-moved check, no unpushed check, either runner ignoring no-push) each turn one red.

- **2026-09-24 — (overseer) the runaway guard counts model calls, as S-66 says, not the tools a session calls.** The first real overseer run (2026-09-24, run `70938b8e`, started by the user by hand) read its 46 blind cases in phase A in eight model responses, wrote both of its files, and ended normally; the runner then discarded it as a runaway because `overseer.max_model_calls` (50) was compared with Claude Code's reported `num_turns` (53), which advances once per tool result, and phase B was never started. The steward's copy of this mismatch was fixed on 2026-09-20 (entry below); the overseer's was deliberately left then. Now a run counts its model calls, two (phase A, then phase B), and a guard below two holds the run before its first call, so no call is spent on output that could never be applied; a session that ended normally is judged on its files, and one Claude Code stopped at its own turn limit (`error_max_turns`) is a failed call of kind `turns` in either phase (`02-schema.md` §3a amended in place). The session's `num_turns` is still written to the cache journal (`tool_turns`), never compared with anything. A complete phase-B answer is therefore never discarded for the number of tools it called. The failed attempt's committed note was withdrawn from the live ledger at the user's word, so the re-run is the week's first attempt; its phase-A output is kept for comparison under `misc/forensics-2026-09-14/first-overseer-run-2026-09-24/` (untracked).
- **2026-09-23 — (steward, overseer) S-71: a ledger refusal is handled by its kind; the steward hears about its own bad lines while it can still fix them; two ways one bad line or file ended a whole sheet are fixed.** `03-decisions.md` S-71 records the design and its origin; every sentence of that row is the orchestrator's. **Kinds:** every refusal the ledger makes carries one kind from the closed set named once in `02-schema.md` §3a (`git`, `target-busy`, `status`, `destination-unavailable`, `needs-person`, `bad-line`, `secret-record`, `unclassified`), decided in `batch.refusal_kind` from the exception's type at the raise site (following `raise … from` to the typed refusal underneath a plain `VerbError`), never from its text; an item result, a preview item and both runners' disposition rows carry it, and the receipt line's format is unchanged. **The preview checks what the verb checks:** each sheet verb's pre-mutation checks moved, unchanged, into one `verbs._preflight_<verb>` function that both the verb and `batch.dry_run` call, so a preview's would-apply is no longer followed by a refusal for any check the verb makes before its lock (`tests/test_preview_parity.py`, one row per check; `defer` with an `until` that is not a date now refuses instead of raising). **The steward:** only `git` and `target-busy` leave a lesson `unfinished` for the next night (S-68's cap and close-out apply); a `status` refusal whose lesson changed status since selection is `overtaken` and closed; the steward's own bad line (`bad-line`, `destination-unavailable`, or a status that did not fit the verb) is `returned` and decided again by the next run, whose brief lists it under LESSONS SENT BACK TO YOU with the ledger's words, once per input version; `needs-person` and `unclassified` are parked at once with the new runner-only reason `ledger-refused` and the user is notified; `secret-record` is `refused`. A `returned` lesson counts in the run's refused count. Before the session ends, the ledger's preview of the staged sheets feeds the one repair turn (`02-schema.md` §3a), except for a `status` refusal of a lesson a staged reconsider case covers, which that case widens at apply time. **The overseer**, kept minimal until its first run has been watched: a resumed run dispatches a receipted `git` or `target-busy` refusal again, every other refusal stays final, and each "Refused / could not do" line ends with its kind in brackets. **Defect 1:** `resolution_note` is write-once, and every steward route line carries `note:`, so a later `retire` or `supersede` of a routed lesson written with a note was refused every time; `ledger_ops.resolve_record` now displaces the earlier note into `history` (`event: "resolution"`) before writing its own, as `reopen` and a reconsider correction already did (§2 amended in place). **Defect 2:** a malformed `hosts.yaml` or a record file that no longer validates raised straight out of `batch.run` and ended the whole sheet; each is now a refusal of that one item, of kind `needs-person`, naming the file, and the sheet carries on. Not covered: the registry read reached only by a user-scope route into a `CLAUDE.md` whose managed region has no compile record, and the compile-set readers, which skip a record that fails validation but not one whose frontmatter is not YAML at all. **Stale comment:** `batch._STOP_CODES` said exits 5, 6 and 7 all wrote nothing; 7 is half-written, and a later attempt is safe only because every ledger write runs intent recovery first. `commands/review.md` `## Steward run` and `steward-method.md` §12 now name `ledger-refused` and state the kind rule. Existing tests that encoded the old blanket retry were rewritten to the new rule, each named in its commit.
- **2026-09-23 — (steward) the brief's account of where a route lands was wrong; corrected against the verb.** The output contract written on 2026-09-22 said a route's variant, `rules_topic` and `rules_paths` come from the proposal and that "no sheet key sets or overrides them", and its example sheet wrote `dest: claude-md`. The route verb does not work that way: `verbs._resolve_destination` takes the proposal's variant only when the item carries NO `dest`; any `dest` replaces the proposal's whole destination, and a bare `claude-md` is the host's plain `CLAUDE.md`. Two real steward sheets (runs of 2026-09-22 and 2026-09-23) wrote a bare `dest` intending to keep a `local` and a `rules` proposal; both resolved to a committed `CLAUDE.md` and were parked as `plain-host-committed-file` only because the host was plain — on a git-mode host the lesson would have been committed there. An audit of every route the steward had made found no other case. The contract now says: leave `dest` out to take the proposal as written; `dest` replaces it, variant included; spell a kept variant as `claude-md:local` / `claude-md:rules:<topic>`; and it lists the accepted values from `ledger_ops.PROPOSAL_DESTINATIONS`. The example sheet no longer writes `dest`. `tests/test_steward_prompt.py` checks each of those sentences against `verbs.route_dry_run` on a scratch ledger. No verb, schema or runner behaviour changed. The two parked lessons were routed by hand at the user's word and their parked cases superseded by human cases.

- **2026-09-22 — (steward) a refusal that wrote nothing no longer halts the sheet or the cases behind it; a ledger refusal leaves the lesson `unfinished`, not terminal.** Follows the first real run's halt (entry below). **(1)** `batch.run` raised its host-outcome `BookkeepingHalt` for any `route`/`reject`/`retire`/`graduate`/`supersede` item that returned non-zero, whether or not it had written anything. All five commit their ledger leg before their host leg (`_execute_route`, `reject`, `_retire_impl`, `supersede`), so an unchanged ledger HEAD proves the host was never reached; such an item is now an ordinary receipted refusal and the rest of the sheet runs. A host-outcome verb that failed AFTER its ledger commit landed still halts with the partial result and untouched tail (02 §3a.2, amended in place). **(2)** The steward's case loop stopped every later case of a packet on exit 8 (some items applied, some refused) as if it were a STOP; it now stops only on a ledger STOP (5/6/7) or a bookkeeping halt, so exit 8 leaves the case `unfinished` and the later cases and maintenance run. **(3)** A case the ledger refused — at preview (`would-refuse`) or at dispatch — was stamped `refused`, a TERMINAL disposition, so the record dropped out of every later run while still pending (`lrn-351ba705`, refused over the probe bug fixed the next day). The reading applied: a ledger refusal of an accepted decision is a non-merits failure under S-68 — the case stays `unfinished`, a later run re-drives it, and at `runs.attempt_cap` the record is parked for the overseer with the ledger's own refusal text as the reason (the parked case's evidence quote and the `abandoned` disposition's `reason` now carry it, not only the generic no-progress sentence). `refused` is reserved for the steward's own refusals (`cases.CaseError`). The alternative not taken, for the user: park for the overseer at once instead of after the cap's three nights. `commands/review.md` `## Steward run` restated accordingly. **(4) The brief carries what the run went to the repository for.** The same run's first session spent 24 of 83 tool calls in this repository's source and spec trees (the always-loaded user-scope rulings, the `covered_by` grammar, where a route's `rules_paths`/variant come from, which status each verb needs). The output contract now states the `covered_by` grammar from `records.COVERAGE_KINDS`, that a route's destination variant and rules keys come from the proposal and no sheet key overrides them, the meaning of `follow_up`/`unblocks_on`/`allow_empty_glob`/`collapse`, one-line meanings for `supersede`/`rehome`/`rescope`/`reopen`, and each verb's status precondition from the verbs' own constants (`ledger_ops.LIVE_STATUSES`, `RESOLVABLE_STATUSES`, `DEFERRED_ONLY`, `verbs.REOPEN_ADMITTED_STATUSES`, made public for this); the method block ends with the S-23 and SA-1 headlines quoted verbatim (`steward_prompt.STANDING_RULINGS`, checked against `03-decisions.md` by the suite) and the instruction to park `always-loaded-user-scope` when they leave a route in doubt. **(5) The conditions feed tells the truth about the steward.** `steward.last_run_at` / `.last_run_outcome` / `.cases_since_overseer` read a cache projection whose keys never carried those names, so every brief said "unavailable"; they now read the newest completed committed run record and `steward.cases_since_overseer` (02 §3b table amended). A host registered as both the skills root and a project produced its rows twice; once now. The feed is built once per run and handed to every packet's brief (`assemble(..., conditions_items=)`), not rebuilt per packet.
- **2026-09-21 — (steward, from its first real run) a route whose predecessor is already superseded by that very record is complete, not refused; the route preview runs that same check; the glob probe sees files.** Three defects found by the first real `self-learn steward run` (2026-09-21 12:52–13:18, `run-3dfa8bebd36b`, 21 of 29 lessons applied). **(1)** The steward's case `case-0f95cb50` wrote the sheet `supersede old → new`, then `route new`, where `new` names `old` in `supersedes:`. Route's own `teach --supersedes` completion preflight required `old` to be pending, deferred or routed, found it `superseded` (by the line before), and refused; `batch` raised its host-outcome halt, and the packet stopped with five other prepared cases behind it. Now one helper, `verbs._supersede_completion_preflight`, serves `route`, `route_direct` and `route_dry_run`: a predecessor already superseded BY THIS RECORD is a completed obligation and the route carries no supersede leg (a plain `route` commit); a predecessor superseded by any other record, or rejected, still refuses naming its real status (FW-51). **(2)** `route_dry_run` (S-54: *"runs every preflight the real route runs"*) did not run that preflight, so `batch --dry-run` previewed the sheet as `would-apply` and the real run refused it; it runs it now. **Still open, named here:** the preview checks each item against the ledger as it stands, not as the earlier items of the same sheet will leave it, so a sheet whose second line depends on its first can still preview clean and refuse for real for a different pair of verbs; nothing simulates the sequence. **(3)** `ledger_ops.glob_reaches` (`u-glob` §4.3 step 5) tested a pattern's literal tail against DIRECTORY entries only, as the spec text said, so `**/.gitignore` — a one-part literal tail naming a file — matched only at a root's own zero-directory expansion and returned `none` for every real file below it; the run's route of `lrn-351ba705` (a `.gitignore` rule) was refused as *"matches nothing under $HOME"* with three such files two levels down. The tail is now tested against every non-symlink entry before the directory filter; the spec step is amended in place. **Not changed, for the user's decision:** a bookkeeping halt on one case still stops every later case of the packet (`commands/review.md`, `## Steward run`), which is what left five prepared decisions unapplied; the fixes above remove this run's cause of the halt, not the rule.

- **2026-09-20 — (liveness) the steward's turn limit comes down to 100 per lesson.** `steward.turns_per_lesson` default 200 → 100, at the user's instruction of 2026-09-20: *"bring the number down to 100 for now. still maybe a bit too generous, but definitely more sane than 200."* The 200 was chosen on 2026-09-19 when a turn was believed to be one tool call; the limit counts model responses (entry of the same day below), and the three real sessions used about 6 per lesson, so a batch of ten now gets 1,000 where it used about 60. Still crash protection and nothing else (S-29). Recorded with it, NOT built: the user's direction for batch sizes, in their words. The miner: *"if we're defining batch size for the miner as number of sessions a given agent deals with, that number should be 1."* The steward: *"that number should be variable, and maybe even dependant on how many lessons that are relevant to the same project or problem can be packaged up in one go. it makes sense to me that 3-4 lessons that all trace back to the same session log can and maybe should be batched together for 1 steward. the absolute maximum should be 10, and i think i would even say something along the lines of the maximum number of unrelated lessons a given agent should parse is 5."* `steward.packet_size` stays 10 (the stated absolute maximum); grouping related lessons and the limit of 5 unrelated ones are design work not yet started.

- **2026-09-20 — (liveness) how much goes into one model call is a setting: five numbers leave the code for the settings registry, behind one helper.** The user's instruction, 2026-09-20, in their words: sizing parameters *"can't be constants we just leave hardcoded in the code"*, and the code is to be *"written in an extensible way so we can more easily slot in other similar tuning knobs"*. Most sizing numbers already were settings (`steward.packet_size`, `steward.turns_per_lesson`, every `sdk.max_turns.*`, the worker's two timeouts, `miner.cap_per_session`, `miner.cap_max`, `miner.pending_gate`). The five that were not now are, each with its old value as the default, so nothing changes until a ledger's `config.yaml` says so: `worker.batch_cap` (15 lessons in one worker call; was `worker.BATCH_CAP`), `miner.message_chars` (2,000), `miner.session_chars` (60,000) and `miner.run_chars` (400,000) (the characters the miner keeps from one message, from one session, and puts into one run's model call; were `miner.MAX_TEXT_CHARS`, `MAX_DIGEST_CHARS`, `MAX_PROMPT_DIGESTS_CHARS`), and `miner.reader_timeout_secs` (900 s; was readable only from the env var `SELF_LEARN_READER_TIMEOUT_SECS`, which keeps its name and now sits below `config.yaml` like every config-first setting, S-58). **The helper:** `settings.sizing_knob(name, default=, description=)` builds the registry entry from the dotted name (section, key, env var), takes int or float from the default, and refuses a value that is not above zero, which falls through to the next rung as any bad value does; `settings.resolve_int` / `resolve_float` are the whole use site. A new knob is one `sizing_knob` line and one read. The module constants remain as names but are copies of the registry defaults, so each number is written once. **The miner:** its three sizes are read once per run into a frozen `miner.DigestLimits`, resolved by walking the dataclass's fields (a fourth limit is one field plus one `sizing_knob` line), and passed to `digest_transcript`; that object is the only thing the digest and the run size against, so it is where a measure other than characters would be introduced. No such measure is introduced here: the user has said plain character counts are to be reconsidered, and that is a separate discussion. **Removed:** `worker._timeout_secs`, the env-only reader kept alive solely for the miner's timeout, and the registry comment that declared that timeout deliberately unregistered. `test_u_fw100.py::test_shares_worker_helper_not_a_reimplementation` guarded that arrangement ("do not re-open"); the user's instruction re-opens it, and its purpose (the reader's timeout must not be parsed differently from the worker's) is kept by its replacement, which drives all three timeouts through every rung and requires identical behaviour. `test_reader_contract.py`'s three timeout tests set the env var instead of patching the module constant. **Not changed, and worth knowing before anyone lowers `worker.batch_cap`:** `worker.FOLLOWON_DEPTH_CEILING` (8 follow-on generations) was sized against 15 per generation, so a smaller batch drains fewer lessons before the chain stops. The overseer has no sizing number to expose: it puts the whole week into one call and never splits it. `tests/test_sizing_knobs.py` holds the helper's tests and one test per knob that a `config.yaml` value reaches the code that uses it.

- **2026-09-20 — (liveness) a lesson the steward's model parks is handed to the overseer with nothing done to it, and a lesson a case covers must have its own sheet item.** Both chosen by the user on 2026-09-20 from the two facts the entry below put to them. **Parking:** `steward-method.md` §12 tells the model to park a lesson it cannot decide alone, but `steward._prepared_recipe` took a parking reason only from the runner's own two checks (a route to a hook; a route into a plain-mode host's committed file), so a staged case with `kind: parked` was recorded as a question for the overseer AND had its sheet applied in the same run — measured on a scratch ledger: the lesson came out `deferred` and was reported decided. One existing test staged exactly that as a side control and had pinned it (`result.decided == ids`); it is rewritten. Now a case the model marks `kind: parked` takes the path every parked case takes: each sheet item is receipted `parked`, nothing is dispatched, the lesson stays pending, its disposition is `parked` (terminal, so the batch completes). The sheet is the model's tentative answer, on record and not acted on; since a sheet cannot be empty, §12 and the brief now ask for a tentative answer even when loosely held (this change's author recommended that; the user did not rule on the point). When the runner's own check fires too, its reason wins. The stage check now refuses, where the one repair turn can fix it, a parked case without a `parked_reason` the model may choose, and parking fields on a case that is not parked. `parked.yaml` is unchanged and is now described as what it is: a further question for the overseer, never the way to park a lesson of the packet (such a lesson would fail the every-lesson-in-one-case check and take the whole batch with it). **Sheet items:** the runner dispositions every lesson of a finished case `applied`; a lesson listed in a case's `records` with no item on the sheet was recorded as handled with nothing done (seen once in the real run of 2026-09-19). The stage check now refuses it, after the sheets' own shape check so a malformed sheet still gets `load_sheet`'s precise error. The brief gains a parked-case example and a PARKING paragraph; `tests/test_steward_parking.py` holds both behaviours.

- **2026-09-20 — (liveness) the steward's brief states the shape of every file it writes, generated from the checkers' own constants.** The user's instruction, 2026-09-19, in their words: *"give the steward the information it needs up front instead of having the poor guy read through the source code"*. On the first real run each steward session spent about 30 of its ~110 tool calls reading this package's source (`steward.py`, `cases.py`, `batch.py`, `verbs.py`, `02-schema.md`, even `tests/test_steward.py`) to learn its output formats — its own words: *"Now finding the runner code that parses the stage files, so the format I write validates."* The cause: `steward_prompt.OUTPUT_CONTRACT` was written before the code that reads those files existed (its own comment said so), described the finished six-section case DOCUMENT that `cases.record` renders rather than the YAML file the steward writes, and said almost nothing about the other five files. The brief's last block now gives, for each of the six files, every key and every allowed word, read at render time from `cases.KINDS`/`TRIGGERS`/`OUTCOMES`/`CONFIDENCE_VALUES`/`PARKED_REASONS`, `batch.PERMITTED_KEYS`/`REQUIRED_KEYS`/`REFUSED_VERBS_LITERAL`, `statements.ANSWER_KINDS`/`SCOPE_LEVELS` and `records.REQUIRED_SECTIONS`; what the runner fills in and the model must not write (`case`, `by`, `run_id`, …); the cross-file rules the stage check enforces; §3a's evidence-reference grammar; and a worked example of every file (`steward_prompt.STAGE_EXAMPLES`). `tests/test_steward_output_contract.py` feeds those examples through the real stage validator, `cases.record`, `statements.add` and `user_model.add_entry`/`lapse_entry`, and proves a member added to a checker's set reaches the brief unprompted. The two `parked_reason` values only a runner writes move to one shared constant. `steward-method.md` §6 points at the block. **Two facts found on the way and NOT changed here, both put to the user:** (1) the model has no working way to park a lesson of its own choice — a staged case with `kind: parked` is recorded as parked AND its sheet is applied (`_prepared_recipe` takes a parking reason only from the runner's own two checks), while a lesson carried only in `parked.yaml` fails the every-lesson-in-one-case check and refuses the whole batch; (2) a lesson covered by a case but given no sheet item is dispositioned `applied` with nothing done (seen once in the real run: a two-lesson case with one item). The brief states the second as a rule the model must follow; neither runner behaviour is changed.

- **2026-09-20 — (liveness) a steward session's turn limit grows with its batch: `steward.turns_per_lesson` (default 200) for each lesson in it.** The user's instruction, 2026-09-19: raise the limit to *"200 per lesson"*. `SessionSpec` gains an optional, keyword, defaulted, last field `max_turns`; a session that names one is handed that limit, and every other session keeps its surface's `sdk.max_turns.<surface>` lookup unchanged. The steward sets it to `steward.turns_per_lesson` × the lessons in the batch (a batch of ten: 2,000) and carries it into the repair round. What the number limits is what Claude Code's `--max-turns` limits — model responses, not tool calls (entry below); the three real sessions of 2026-09-19 used 51 to 61 for nine or ten lessons each, so this is crash protection against a runaway session and nothing else, which is how S-29 already describes turn bounds (*"crash protection, not a ration"*). `sdk.max_turns.steward` stays in the registry as the limit for a steward-surface session that names none; the steward's own runs no longer read it. Batch size (`steward.packet_size`) is unchanged.

- **2026-09-20 — (liveness) a steward session that ended normally is judged on the files it wrote, never on its turn count.** Found by the first real `self-learn steward run --dry-run` that reached the model (2026-09-19): three sessions decided all 29 waiting lessons, each ended on its own (`is_error` false), and the runner discarded all three because the turn count each reported — 104, 117, 115 — was at or over `sdk.max_turns.steward` (80). The two numbers count different things. `--max-turns` stops a session on MODEL RESPONSES: those three sessions made 61, 51 and 58 (several tool calls often ride one response), so the limit was never reached. The `num_turns` Claude Code reports back advanced once per TOOL RESULT in all three (103, 116, 114 tool calls, plus one); Anthropic's documentation does not define that field. A deliberate probe (limit 3, five sequential tool calls) confirmed the other half: a session the limit really stops comes back `is_error: true`, `subtype: error_max_turns`, `errors: ['Reached maximum number of turns (3)']` — already a failed call by the seam's own mapping. The runner's comparison is removed; `SdkOutcome` gains `result_subtype` (the failed result message's own `subtype`, `None` on a normal end), and the steward writes the `turns` failure kind only when that subtype is `error_max_turns`, with Claude Code's message as the committed detail. `02-schema.md` §3a's `failure` bullet says what `turns` now means. The overseer's equivalent guard (`overseer.max_model_calls`) has the same shape and is NOT changed here.

- **2026-09-19 — U4c (liveness): with `sdk.cli_path` unset, self-learn uses the Claude Code the PERSON has installed; the SDK's bundled copy is the fallback.** Origin: the user asked whether self-learn could just use the binary they already have installed for their own Claude Code sessions; the orchestrator answered yes and recommended making it the default with the bundled copy as the fallback; the user accepted. The design and its wording are the orchestrator's — see `03-decisions.md` **`S-70`** for the attribution stated in full. Until now an unset `sdk.cli_path` meant self-learn passed no binary at all, and `claude_agent_sdk`'s own `_find_cli` takes its **bundled** copy first — 2.1.226 in the pinned wheel, too old for `claude-fable-5-1` — so a default install could not run the steward or the overseer at all, and the 2026-09-14 outage needed a hand-written setting to work around. The order is now: an explicit `sdk.cli_path` (unchanged, still wins), then the `claude` on `PATH`, then the same install locations the SDK itself falls back to (mirrored in `provider.py` with a comment naming the SDK file and version, because the resolver must label its answer and the SDK's own method is bundled-first by construction), then nothing — and the SDK's bundled copy — exactly as before. POSIX only; finding a binary is filesystem checks only, never a spawn. **One resolver serves both the session launcher and `doctor invocation`'s `sdk` row**, so the doctor cannot name a binary different from the one a session launches, and that row now prints the deciding rule (`explicit sdk.cli_path`, `installed (PATH)`, `installed (<location>)`, `bundled fallback (no installed claude found)`) and the path. S-69's version floor is unchanged and now usually passes on a default install; the bundled-fallback case with a floor in play still FAILs, with fix text that now leads with *install or update Claude Code*. The opt-out is the new registry setting `sdk.prefer_installed_cli` (bool, default `true`, `config.yaml` > env var > code default), and it exists because an installed binary **updates itself** while the SDK was built against the bundled one — the trade is stated in S-70 and made visible by the row. `17-invocation-runbook.md` gains §3d (the order, the locations, the setting, the labels, the interlock); `scripts/liveness-acceptance` gains a step 0 that prints which binary a default configuration would choose and by which rule, and keeps step 1's positive control by pointing `sdk.cli_path` at the bundled binary explicitly.
- **2026-09-19 — U4b (liveness): a session's settings come from the ledger home, not from the directory the session runs in.** Found by a real `self-learn steward run --dry-run` on 2026-09-19: three model calls, all three answered `API Error: 400 Claude Code 2.1.226 does not support this model; version 2.1.251 or newer is required` — the Agent SDK's own bundled binary — although the ledger's `config.yaml` set `sdk.cli_path` to a 2.1.278 one. `SessionSpec` had no ledger-home field, so the invocation seam used `spec.cwd` as the ledger home in seven lookups. **The `steward` and `overseer` surfaces, added 2026-09-14, broke that invariant**: their sessions run inside a cache stage directory, which holds no `config.yaml`, so from 2026-09-14 to 2026-09-19 **six ledger settings were silently ignored for exactly those two surfaces** — the Claude Code binary (`sdk.cli_path`), the model (`models.<surface>`), the turn bound (`sdk.max_turns.<surface>`), the spend bound (`sdk.max_budget_usd`), the provider resolution, and the backend selection. The worker, the miner-reader and the analyst pass `cwd=home` and were never affected. `SessionSpec` gains an optional, keyword, defaulted, last field `ledger_home` and one helper, `SessionSpec.settings_home`, which every one of those lookups now reads; absent a `ledger_home`, it is `cwd`, so the three unaffected producers are unchanged. `03-decisions.md` `S-35` carries a dated correction of the sentence that stated the old invariant; `17-invocation-runbook.md` gains §3c, which says which ledger a session's settings come from and why setting `SELF_LEARN_SDK_CLI_PATH` is not a test of the `config.yaml` route. `scripts/liveness-acceptance` now sets the binary for its recovery steps in the scratch ledger's own `config.yaml`, with the environment variable unset, so the acceptance run crosses the path production uses — the env-var route it used before is env-first and bypassed this defect entirely, and the script would have passed over it.
- **2026-09-19 — U4 fold r1 (liveness): S-68's two rules were never the user's words; the attribution is corrected and NO RULE CHANGED.** The row opened "Two user rulings, 2026-09-19, binding and quoted rather than paraphrased" and then put two sentences in quotation marks as the user's own. That was false, and it was the orchestrator's error, not a builder's: the orchestrator put two multiple-choice questions, each carrying an option it had itself written and marked "(Recommended)" — "Fresh attempt, own repair turn" and "3 tries, then park for overseer" — and the user selected those two options. The row now says the rules were PROPOSED by the orchestrator and ACCEPTED by the user by selection, states plainly that the wording is the orchestrator's, and drops the quotation marks and quotation-italics from the two sentences while keeping every word of the rule text. The user's decision is no less binding: choosing an option is a decision. One code comment carried the same claim (`settings.py`'s `runs.attempt_cap` default, "user ruling 2026-09-19: …") and now reads "S-68 rule 2". Every other `ruling 1` / `ruling 2` in the runners and their tests is a short name for one of the two S-68 rules and cites S-68, never the user, so none was changed. Text and comments only; no rule, no behaviour, no test assertion changed.
- **2026-09-19 — U4 (liveness): the health check learns what Claude Code version the SELECTED model needs, and the one place 2.1.251 came from is named.** `03-decisions.md` gains **`S-69`** under the existing "Liveness of delegated runs" heading: the `doctor` `sdk` row compares the OPERATIVE binary against a per-model minimum instead of comparing the SDK's bundled copy against it for equality — it said PASS on 2026-09-14 while the steward could not run at all (`API Error: 400 Claude Code 2.1.226 does not support this model`) and WARN once the machine worked, so both verdicts carried no information. The minimum is the registry setting `sdk.model_cli_floors` (`config.yaml` > env var > code default), seeded with `claude-fable-5-1=2.1.251` and encoded as one comma-separated `<model>=<version>` string because the registry's kinds carry no map. Floor violated → FAIL naming surface, model, both versions and the fix; no registered floor → nothing; versions merely differing → INFO, not WARN; unprobed or unreadable → WARN, never PASS; comparison numeric per dotted component. **The only source for 2.1.251 is that API error string, not vendor documentation**, which is why it is user-editable. `17-invocation-runbook.md` gains §3a (the floor, the setting, the verdict table, the caveat) and §3b (a heading for the unchanged `switches` prose displaced by it), and its §3 example `sdk` row is replaced by a RENDERED (not captured) line for a machine whose `sdk.cli_path` points at a current binary — the stale `host-cli=` field name and the `WARN` verdict are both gone, and the surrounding text now says plainly that an all-defaults machine with an old bundled wheel reads FAIL there. `CLAUDE.md` § Running things names `plugins/self-learn/cli/scripts/liveness-acceptance`, the opt-in human-run script that crosses the real SDK → Claude Code → model boundary the suite deliberately blocks.
- **2026-09-19 — U4 (liveness), carried from U3's review: the overseer run record's numeric halt code gains its field name.** `02-schema.md` §3a spoke of "the run record's own numeric halt code (5, 6, 7, 8)" without naming a field; the sentence now names `halt_code` and states the set the runner actually accepts (`overseer/run.py`'s `_LEDGER_HALT_CODES`), which is wider than the text said: `3` push failed, `4` rebase conflict, `5` no ledger home, `6` git failed before any mutation, `7` half-written, `8` batch partial, and `null` for a stop whose code falls outside the set. Text only; no code changed for this item.
- **2026-09-19 — U3 (liveness): where the overseer's committed attempt evidence lives.** `02-schema.md` §3a's overseer bullet names the two places S-68's "counted from committed evidence" reads: one note per failed attempt under `overseer/failures/<week>/`, plus the run record's own `attempt_count`. The sources are disjoint — an attempt that fails before a run record exists (a first-model-call failure, a phase-B refusal) has nowhere else to put its trace and writes a note; an attempt that reaches the run record writes its reason into that record's `failure`/`failure_detail` — so the week's count is their sum. The close-out's own committed note is `overseer/failures/<week>/closed.md`. No rule changed; this states the storage S-68 already required.
- **2026-09-19 — U2 fold r1 (liveness): a close-out that fails is reported, not only journaled.** `02-schema.md` §3a's failed-close-out paragraph gains one consequence of its own rule: because a close-out is retried without a count, no cap will ever stop one that fails the same way every time, and nothing else would surface it — so a failed close-out is reported to the user once per distinct cause, not once per run and not once per record, and the run's own report names it beside the count of lessons still waiting for a successor. One sentence; no other spec text changed.
- **2026-09-19 — U0 (liveness): the retry rule, the close-out, and the two definitions a builder could otherwise read two ways.** `03-decisions.md` gains S-68 under its own dated heading, with PROGRESS and THE OVERSEER'S WEEK stated once beneath it: a failure that is not a judgment on the merits is retried by a later run as a fresh attempt with its own single repair turn, a decision refused on its merits never is, and after `runs.attempt_cap` (default 3) failed attempts the run closes so new runs can start — each affected lesson getting a parked case for the overseer carrying the real failure reason, with the user notified, and the overseer's own stuck decisions becoming questions to the user in its report. `02-schema.md` §3a adds the run record's attempt-counting fields (`attempt_count`, `last_attempt_at`, `progress_at`, `failure`, `failure_detail`, and the overseer's `week`), the concrete `abandoned` disposition shape with its `successor_case`, and `attempts-exhausted` in the closed `parked_reason` set. `13-hosting-and-separation.md` §5 adds the overseer's catch-up rule (due on the first tick at or after Sunday 04:15 local for which the week is not done, whatever the weekday) and the same-week guard, which lives in the runner so the linked-but-unenabled timer can never double-run a week. `commands/review.md`, `commands/overseer.md`, and `skills/self-learn/references/steward-method.md` gain only the sentences that state retry or close-out behaviour. Spec text only: no runner, setting, or test changed in this unit.
- **2026-09-14 — J1 implementation sweep, U0–U14 and O-1–O-7.** U0 added truthful unattended exit codes; U1 the ledger content contract; U2 cases/statements/user model; U3 case-bound sheets and receipts; U4 revise; U5 reconsider; U6 fire-suspicion semantics; U7 analyst briefs; U8 the two invocation surfaces; U9 the method, prompt, and conditions feed; U10 the steward runner; U11 the nine dry-run evaluation fixtures and supervised-period wording; U12 this documentation sweep; U13 retire/replaced terminology; U14 committed execution evidence. O-1 added blind population and coverage; O-2 hook activation and its batch path; O-3 the overseer runner; O-5 the indexed conversation surface; O-7 catalogue-health facts. O-4 scheduling, O-6 cues, and O-3b user-model maintenance are owned by parallel Lane A and are recorded by the merge note below rather than described here before that lane lands.
- **2026-09-14 — O-3b, O-4, O-6 (Lane A).** The overseer runs as the fourth `serve` job after the steward (Sunday 04:15 local; committed unfinished work is due regardless of the calendar; the attempt cooldown and a STOP refuse) *(extended 2026-09-19, S-68: due on the first tick at or after Sunday 04:15 local for which that week is not done, whatever the weekday, and the same-week guard lives in the runner — `13-hosting-and-separation.md` §5)*; exactly one notification per run, its cue decided by code from the applied results (hook activated → user-scope always-loaded surface → more than `overseer.broad_removal_threshold` removals → a sheet item's `close_call` → routine) and sent after the ledger lock is released; phase B's fifth output `user-model-delta.yaml` is applied one entry at a time through the user-model owner API with `by: overseer` (adds must carry `source: system-reading`), each operation checkpointed in the committed run manifest so a restart resumes without duplicating; `status --json` gains `overseer_last_run` and `overseer_next`, `status --fast` and the doctor serve row read `overseer_last_run` from a cached marker, and the text `overseer status` falls back to the committed coverage file.
- **2026-09-14 — O-5/O-7 and S-29 as amended.** `overseer open` presents at most three indexed questions only after successful output; scoped answers and declines preserve presentation truth and queue dependency-bound reconsideration. Phase B now receives bounded report, telemetry, reachability, and changed-condition facts. FW-82 records the 2026-09-12 supervised first drain and the steward maiden run as the supervised second.
- **2026-09-14 — U10 round 2 (S-29 as amended, S-54, S-65): steward recovery adopts U14's committed execution evidence.** `commands/review.md` now states that normal runs resume committed manifests before selecting new work, partial output preserves established results and names unfinished obligations, and dry-run never advances the completed-run watermark; cache files remain projections only.
- **2026-09-14 — U14 (S-54/S-65): delegated batch runs gain committed recipes, exact mutation trailers, original-ordinal continuation, ordered early Application receipts, compound in-commit ledger-effect proof, and intent-backed case publications.** `02-schema.md` §3a defines `cases/runs/<run_id>.json`, binding/disposition/recovery rules, and `plain-host-committed-file`; `13-hosting-and-separation.md` §3 adds the truth path and states that the companion is one registered path in an existing intent.
- **2026-09-14 — U10 fold r1a S6: the cheap steward status field is narrowed to the cached last-run marker.** `13-hosting-and-separation.md` §5 now keeps case-store-backed `steward_cases_since_overseer` on full `status`; `doctor serve` and `status --fast` carry only `steward_last_run_at`.
- **2026-09-14 — O-2a fold r2, ruling 5: the `hook-activated`/`hook-deactivated` history note text amended — deactivation never has a backup of its own to name, so its note instead names the removed registration and the symlink path.** `02-schema.md` §2's five-kind `history` bullet amended.
- **2026-09-13 — U0 fold r1: FW-134 gains a dated clause closing it for the run-command contract — FW-85's disposition (same date) supersedes its PROD3 negative criterion for `mine run`/`worker run`/`worker kick` only; S-54's batch exit space is untouched.** `14-forward-work-map.md` FW-134 amended and closed (trigger fired: the steward/overseer runners cannot read stdout).
- **2026-09-13 — U9 (steward plan)/O-0 (overseer plan): the README's own reading-order table gains the overseer's `overseer/` subtree and the corrected count of `01-architecture.md`'s components.** `README.md:42` "six components" → "seven"; `README.md:54`'s `13-hosting-and-separation.md` row gains the `overseer/` subtree.
- **2026-09-13 — U13 (steward plan): the rename's mapping sentence, in each spec file it falls to but does not otherwise touch.** `04-roadmap.md`, `06-horizon.md`, `08-build-plan.md`, `10-surface-build-plan.md` each gain one sentence mapping `graduate`/`superseded_by: canon` to `retire`/`covered_by:<kind>:<name>`; `09-surface-spec.md` gains the bulk-collapse mapping sentence.
- **2026-09-13 — U13 (steward plan): `graduate`/`supersede` become one internal status, `superseded`, displayed as `retire` (with a named covering surface) or `replaced`; `graduate` stays a hidden alias for one release; `reopen` widens to a wrong retirement.** `02-schema.md` §2's `superseded_by` bullet amended (domain widened to `covered_by:<kind>:<name>`), new §3a.1 rule 7; `03-decisions.md` gains S-67.
- **2026-09-13 — U1/U4 (steward plan): three new ledger-truth files — decision cases, the user-statement store, the user model — and the content contract confining free text to them.** New `02-schema.md` §3a; `13-hosting-and-separation.md` §3 gains the layout; `03-decisions.md` gains S-65.
- **2026-09-13 — U7/U9 (steward plan): the worker's output becomes a brief, not a verdict; a new steward agent decides every queued record nightly, alone, with no daily human sign-off list.** `01-architecture.md` §3.3 amended, new §3.3a "The steward"; `03-decisions.md` S-29 amended in place, S-18/S-26 amended.
- **2026-09-13 — U6 (steward plan): a mined `fire` observation is a suspicion the steward evaluates, never a verdict — `complied\|violated` replaced by `suspected-compliance\|suspected-violation\|cannot-tell`.** `11-telemetry-and-lifecycle.md` §4.3 (version bump, read-side legacy mapping); `12-transcript-miner.md` §1/§2/§7/§8 amended.
- **2026-09-13 — O-1/O-6 (overseer plan): recurrence suspects and always-loaded lessons with zero fires join the overseer's coverage nudges; the overseer's weekly report and any conversation stay ambient-informative, never a demand.** `11-telemetry-and-lifecycle.md` §2.2, §4.4 amended; `03-decisions.md` S-9 amended.
- **2026-09-13 — U8/O-3 (steward and overseer plans): two new invocation surfaces, `steward` and `overseer`, join the four this file already documents.** `17-invocation-runbook.md` §1's surface table widened to six rows; §9 dated note.
- **2026-09-13 — U3/U10/O-4 (steward and overseer plans): the steward's runner applies decisions through the existing verb surface with a `case:` sheet key; `serve` gains a nightly steward job and a weekly overseer job.** `03-decisions.md` S-54 amended; `13-hosting-and-separation.md` §5; `17-invocation-runbook.md` §10.
- **2026-09-13 — O-2 (overseer plan): the overseer may approve and install a hook on the user's behalf — the secret scan becomes the sole unconditional floor.** New `13-hosting-and-separation.md` §7.4; `01-architecture.md` §3.5/§5 amended; `03-decisions.md` S-29 amended (user decision 2026-09-12, recorded as S-66), new S-66.
- **2026-09-13 — U8/U10 (steward plan)/O-1..O-7 (overseer plan): the steward and overseer join every unattended-caller enumeration the intent-transaction contract already governs.** `13-hosting-and-separation.md` §7.2a.5, §7.2a.6, §7.2a.7 amended; `03-decisions.md` S-62 amended.
- **2026-09-13 — U2 (steward plan): the review UI's don't-subvert list notes that decision cases are not rendered in this cut, and that every overseer write is a verb.** `07-review-ui.md` §4 gains two contract lines.
- **2026-09-13 — FW-82 status rewrite: BUILT; supervised period open, ending after two consecutive zero-correction overseer examinations rather than a fixed date.** `14-forward-work-map.md` §6, FW-82, FW-85, FW-154/FW-155, FW-161/FW-162/FW-163 sequencing notes; new rows FW-164 through FW-174.
- **2026-09-13 — S-29 as amended: "a human routes it" gains the steward as a named exception.** `README.md:34-35` amended.
- **2026-09-12 — FW-82 (the steward agent, S-29) gains the 2026-09-12 steward-trial evidence and the decision classes it exercised; FW-161/FW-162 now cite FW-82 as the build they follow.** Text only.
- **2026-09-12 — FW-163: a host can declare `CLAUDE.local.md` as its always-loaded surface, honoured by the analyst and the route verb (closes the S-64 residual).** Text only.
- **2026-09-12 — FW-161 (hook destination widening, user ruling 2026-09-11) and FW-162 (worktree captures resolve to the parent host) added to `14-forward-work-map.md`, both sequenced after the steward agent build.** Text only.
- **2026-09-12 — S-64: the product repo may be a plain-mode canon host.** `03-decisions.md` gains S-64; root `CLAUDE.md`, `README.md`, `CONTRIBUTING.md` drop the "never register this repo" rule in favour of "plain mode only, compiled files git-ignored, `claude-md:local` for the always-loaded surface"; `.gitignore` ignores `/.self-learn-host`, `/references/`, `/.claude/rules/`. Text and ignore rules only; no code change.
- **2026-07-11 — refinement pass (draft, unratified).** Spec-bug fixes
  (evidence mutability contradiction, AskUserQuestion option limit, defer
  semantics, diff-as-preview ambiguity, `routed/`→`resolved/`),
  environment-verified gaps (chezmoi-managed `~/.claude/CLAUDE.md`, autosync
  pre-review publication + review-race, machine-local flock), and
  enhancements (in-session capture extraction, model-prompted offers O-6,
  backlog already-canon flagging, bounded review batches, per-lesson
  commits, managed-section overflow cap, ha-note unification O-7). New
  evidence: E-16, E-17. **S-8/S-12 reopened** (freeze-at-routing) pending
  blind review per ground rule 2. Findings→edits map:
  `reviews/2026-07-11-refinement-review.md` — for a *blind* re-review, give
  the reviewer the corpus without that memo.
- **2026-07-12 — blind adjudication + concurrency red-team (folded in).**
  Two blind reviewers (memo withheld). **S-8/S-12 SETTLED** —
  freeze-at-routing ADOPTED, with the secret-scan-on-every-write rider.
  Concurrency findings folded: review **self-pushes** (the sync's clean-tree
  branch never pushes); correction = **supersede + recompile**, not
  per-lesson `git revert` (unsound against regenerating sections);
  **merges-as-proposals** — the worker is now fully append-only and the
  designated-host/claim-marker machinery is deleted; sentinel **heartbeated**
  (TTL means dead, not long); `superseded_by: canon` formally defined with a
  `graduate` verb; routed-and-corrected metric excludes canon graduations;
  chezmoi user-scope writes must also commit+push the dotfiles repo (E-17
  extended). Register: S-2/S-5/S-6/S-7 re-amended, S-8/S-12 settled.
  Details: `reviews/2026-07-12-blind-adjudication.md` (also withheld from
  future blind reviewers).
- **2026-07-12 — SOTA survey folded + horizon set.** Five-stream external
  research (`research/2026-07-12-sota-survey.md`) found independent
  convergence on the corpus's load-bearing choices (curation gates, compiled
  canon over retrieval, files over infra, bounded edits, proposals-never-
  mutate) and no contradiction of any settled decision. New evidence
  E-18–E-21. Short-term adoptions folded: **rejected-proposal digest** for
  the M2 worker (SkillOpt's rejected-edit-buffer pattern), **trigger-first
  phrasing** as a compiler rule (`02` §4), **G-6** staleness revalidation
  gated (Copilot's citation-revalidation pattern), SkillOpt-Sleep named as
  G-1's evaluate-first reference. **Planning horizon reframed to team scale**
  (~5–6 users, shared artifact repo — user directive): new `06-horizon.md`
  (invariants, scope tiers, PR-based routing authority, provenance/trust,
  staged path). v1 scope and all gate triggers unchanged.
- **2026-07-12 — review-UI vision recorded (user-specified).** New
  `07-review-ui.md`: resident TUI as the destination adjudication surface —
  attend-at-convenience (ambient notifications carrying event + aggregate;
  neither popup treadmill nor invisible backlog), deep-link into the
  decision, embedded **SDK adjudication pane** (fresh session per item over
  a stable cached doctrine prefix; agent iterates, only the human's button
  routes). Consequent amendments: **S-2** (all resolution mechanics —
  `route`/`reject`/`defer` verbs, sentinel, self-push, `--note` — live in
  the CLI; slash command is a thin caller; `--json` on reads), **S-9**
  (per-worker-run ambient events with aggregate replace pure thresholds;
  "never per-item" refined to "never per-item-*demanding*"),
  **`resolution_note`** added to the schema (M1; feeds the M2 digest;
  amends the git-only-provenance lifecycle bullet), M2 notification payload
  carries record ids, **O-1/G-3 rewritten** (TUI is the recorded
  destination, gated on M2). **E-2 demoted to casual-solo floor** — the
  sizing environment is heavy daily work use (user directive; E-2 caveat,
  06-horizon §1).
- **2026-07-12 — RATIFIED.** Final calls locked (user-delegated): **S-14**
  (O-2 — auto-memory importer in v1.0), **S-15** (O-6 — quality-gated teach
  offers in v1.0), **O-1 settled** (TUI after M2; G-3 owns the gate).
  Register: **15 settled · 1 open (O-3, deliberately empirical — M3
  revisits with supply data) · 1 parked (O-7) · 6 v2-gated.** Ground rule 3
  is satisfied: M1 may begin (test-first, in this worktree; first actions
  are the §0 baseline-qualification trials for fixtures B and C, which
  need no code).
- **2026-07-12 — acceptance fixtures hardened (independent review, folded).**
  §0 rewritten per `reviews/2026-07-12-fixture-review.md`: the sourcing
  rule was self-defeating (existing-canon lessons already pass at
  baseline); **A reframed as the hook fixture** (deterministic enforcement
  claim — the `.storage` rule already lives in the loaded SKILL.md body,
  so the behavioral A/B had no delta arm), evaluated at **M3 exit**;
  **B sharpened to the silent-substitution rule** (Edit tool self-verifies;
  the failure class is `sed -i`-style zero-match no-ops) with the
  chezmoi-apply persistence check; **C pinned to the `data.host`-reload
  references-only lesson** via plan-elicitation trials. Qualification gate
  added (absence proof · demonstrated baseline ≥2/3 failures · written
  binary predicate), trial protocol (outside-repo cwd, attribution set,
  3/3 pass bar), one-fixture-per-surface stated as a constraint.
- **2026-07-12 — implementability review folded; build plan added.** Two
  independent post-ratification passes (orchestrator read + one blind-to-
  each-other Fable reviewer with ground-truthing against the live repos;
  memo: `reviews/2026-07-12-implementability-review.md`, withheld from
  blind reviewers) hunted gaps that would mislead doc-only implementation
  sub-agents. Six blockers closed with dated edits: **packaging pinned**
  (plugin layout, `SELF_LEARN_HOME`, command namespace — 04-M1), **the
  sentinel's cross-repo contract pinned** (path/mtime-TTL/check-in-sync —
  02 §3), **marker bootstrap rule** (02 §4), **`route` reads proposal
  siblings — M1 inline analysis writes them** (01 §3.4, 04-M1),
  **already-canon flag criterion** (01 §3.2), and the **S-14/M3
  contradiction resolved** — v1.0 = M1+M2, v1.1 = M3+; the auto-memory
  importer moves to M1 (03 note, 04). Risk fixes folded: resolution-verb
  commit formats + per-verb push (02 §2), `superseded_by` merge-loser
  boundary (02 §2), `evidence.origin` key stability (02 §2), proposal
  cleanup at resolution (02 §3), `--route` no-prompt semantics + sentinel
  hold/release scoping (01), chezmoi drift guard, offer-line placement +
  wording, home-net residual (04-M1/08). E-16 re-verified against the
  live tool schema. New: **`08-build-plan.md`** — the durable,
  orchestrator-agnostic execution plan (pins table, fixture runbook, task
  DAG T1–T12, judgment routing, playbooks, acceptance procedure).
- **2026-07-12 — phased implementability gates: M1/M2/M3 all PASS (full
  plan, TUI excluded).** User-directed cycle — per-phase independent
  review → remediation → independent gate check — run to the terminal
  condition: an independent reviewer's verdict that a mid-tier agent
  could implement the full plan from the documentation alone. M1 gated
  after the command-deploy blocker (F1) was pinned; M2's execution plan
  (08 §7) was authored, reviewed (5 gates: merge-proposal schema,
  collapse verb, allowedTools, content-hash staleness, coalesce
  mechanics), remediated, and passed — including a reviewer-caught
  blocker *introduced by* a remediation (M2-21: models can't hash;
  the CLI stamps `record_sha`); M3's execution plan (08 §8) likewise
  (5 gates: snippet template, verbatim-apply exception, new-skill
  compiler contradiction — S-6/01 amended to CLI-owned scaffold — hook
  rollback, live fixture-A harness). Process record:
  `reviews/2026-07-12-phased-gate-process.md` (withheld from blind
  reviewers). 08-build-plan is now the gated execution authority for
  M1→M3; build may start at 08 §2.
- **2026-07-12 — G-3 TUI: empirical grounding + design spec gated
  (phase 1 of 3).** Three research memos landed (`research/`): live
  Agent SDK verification (API-key-only auth, 5-min cache TTL, no
  fallback model), live-host + live-CLI grounding (Ghostty/swaync;
  `claude` 2.1.207 verifies every pane-critical flag), framework trade
  study (Textual over Ink, "not genuinely close on fit"; bus-factor-1
  caveat recorded with switch conditions). New **`09-tui-spec.md`** —
  design authority for the G-3 TUI, refining 07 with two evidence-driven
  dated departures (PaneEngine abstraction, CLI-subprocess default over
  the SDK; caching demoted to opportunistic) and a §10 amendment set for
  02/03/07/08. Phase-1 gate: independent review FAIL (4 gates — bulk
  collapse armed reject where the corpus pins graduation; already-canon
  flag had no structured field; validate-verb delete semantics;
  verb/agent write race) → remediated → **gate re-check PASS** (two
  wording residuals folded). Phases 2–3 (corpus reconciliation;
  execution plan `10-tui-build-plan.md`) follow. Build stays gated on
  G-3's trigger (M2 shipped). **Phase-2 gate PASS (same day):** the nine
  09 §10 amendments landed as dated edits (01/02/03/07/08); the
  independent cross-document sweep (nine contract families, file:line
  traced) caught one real contradiction — the S-8 every-write
  secret-scan invariant had no mechanism on agent-mediated edits that
  bypass CLI verbs (pane + review Discuss-edit) — closed by extending
  `proposal validate <id>` into the scan enforcement point (exit codes
  0/1/2 pinned; resolution verbs scan the full record file as the
  no-bypass backstop). **Phase-3 gate PASS + TERMINAL VERDICT (same
  day):** new **`10-tui-build-plan.md`** — execution authority for the
  G-3 build (TUI-local pins + verify-at-build ledger, fixtures
  T-A..T-E with live trials, task DAG U1–U11, judgment routing,
  playbooks). First review failed it on a symlink-breaking wrapper pin
  and an untested cluster-collapse flow (+8 minors); remediated;
  re-check clean. Terminal conditions, from the third independent
  reviewer: coherence PASS (nine contract families traced
  cross-document), implementability PASS ("Opus 4.8 / Sonnet 5-tier
  agents can execute U1–U11, TUI and adjudication pane included, from
  the documentation alone"), design quality PASS. Build start stays
  gated on G-3's trigger. Process record:
  `reviews/2026-07-12-tui-phased-gates.md` (withheld from blind
  reviewers).
- **2026-07-12 — ratification calls, first batch (user).** **O-5 settled as
  S-13**: auto-memory pruning is a post-decision, post-processing sweep —
  never in-flight, never inline with adjudication. **O-6 amended**: the
  offer gate is quality, not count — gen-1's ≤2-interruptions budget
  superseded as artificial; serious corrections are never rationed. **O-7
  parked**: ha-note stays independent until the library matures — focus is
  the standalone tool, not claude-skills internals.
- **2026-07-12 — G-3 re-derived post-correction (platform → web, engine →
  SDK).** The TUI plan's terminal verdict was voided the same day it
  passed (POST-GATE CORRECTION in the phase memo; ground rule 4 added).
  This cycle repaired the failure modes per that rule: a **holistic
  problem-space map** authored first
  (`research/2026-07-12-adjudication-surface-problem-space.md` — the
  full option space priced: TUI / localhost web / hybrids / do-less
  baseline, on fit-for-us criteria); the user's values routed **early
  and binding** via one AskUserQuestion round (§6: platform = localhost
  web app; residency = any dedicated window; pane engine = Agent SDK,
  restoring the original directive; standing weighting = DX & agent
  leverage); decision-relevant SDK claims **empirically probed before
  pins froze** (`research/2026-07-12-sdk-pane-probes.md` — streaming
  chunk-level ~5 Hz; `can_use_tool` exact-file gating verified, with
  three pinned footguns: streaming-mode requirement, `allowed_tools`
  shadowing, `setting_sources` unset ≠ none). **09/10 rewritten and
  renamed** (`09-surface-spec.md`, `10-surface-build-plan.md`):
  FastAPI/Jinja/vendored-htmx surface, systemd --user service,
  security middleware in scope, SDK pane engine with the charter as a
  `can_use_tool` callback; every TUI-era substrate pin (P1-x/P2-x/P3-x
  closures) carried forward explicitly; socket/launcher subsystems
  deleted, not ported. Dated amendments: 07 (platform + engine
  restoration), 08 (terminology note + launcher rename), 02 §3 (token
  replaces socket), 03 (G-3 row). Textual TUI + cli engine = recorded
  alternatives (view-layer swap only). Build stays gated on G-3's
  trigger. Review phases of this cycle: recorded below as they gate.
- **2026-07-13 — G-3 re-derivation cycle COMPLETE: terminal verdict PASS.**
  Phase A (09 design, fresh reviewer, framing lens + empirical mandate):
  FAIL — render-path XSS un-priced (W-1, caught as a *map mispricing* by
  the framing lens; sanitization + CSP now v1 pins), a still-live
  falsified "SDK has no fallback" claim killed by live introspection
  (W-2), pane read scope contradictory (W-3, re-pinned two-tier and
  empirically confirmed) — remediated, re-check PASS. Phase B (10 to the
  08 standard + traced 00–10 sweep, third reviewer — no authorship, no
  remediation): **zero gates; T1 coherence PASS (twelve contract
  families traced file:line, all AGREE); T2 implementability PASS
  (Opus 4.8/Sonnet 5-tier agents from the docs alone); T3
  fit-for-circumstance PASS (judged against the map's C1–C9 and the
  user's binding answers)**. Nine minors folded post-verdict; fold
  verified by the terminal reviewer, verdict affirmed standing; three
  wording residuals folded per the reviewer's own dispositions.
  Never-self-certify tally: 7-of-8 remediation batches minted findings
  only independent re-check caught. Process record:
  `reviews/2026-07-12-surface-rederivation-gates.md` (withheld from
  blind reviewers). Build stays gated on G-3's trigger.
- **2026-07-13 — M1 BUILT AND MERGED (v1.0 core loop live).** All twelve
  08 §3 tasks executed test-first in the worktree by per-task
  implementation agents (376 tests green; per-task commits T1…T11 +
  T12's sentinel check live on master since f198e49); merged to master
  (523fbf5), deployed via install.sh — `~/bin/self-learn`, the skill,
  and colon-namespaced `/self-learn:teach` + `/self-learn:review`
  verified live. S-15 offer line applied through the guarded chezmoi
  flow (which caught and reconciled real pre-existing drift — E-17
  vindicated). Build findings recorded in 08's appendix, including:
  **Phase 0 disqualified both fixtures** (baselines passed 3/3 on
  claude-fable-5 — general-good-practice lessons are baseline-native
  on a frontier model) → user-directed replacement probes for
  environment-specific candidates under a hardened qualification gate
  (absence proof must cover the predicate behavior; the gate also
  killed the named C backup pre-trial); `proposal validate` pulled
  forward T13→T11. Remaining M1 exit items: the two [protocol] runs
  (exit a: one-motion teach --route; exit b: the GOTCHAS backlog-import
  review session) and fixture ratification + post-routing trials.
- **2026-07-14 — M1 [protocol] runs done; decision-support contract
  landed.** Exit (a): one-motion `teach --route` on home-assistant
  (lrn-e2e4026b → LEARNINGS.md, analyst-chosen destination, ~7 s).
  Exit (b): the real backlog-import review session (32 records
  imported; first batch of 10 resolved — 7 graduated against curated
  GOTCHAS.md, 3 routed to reference; sentinel/verbs/push all clean).
  **E-3 honeymoon verdict: throughput PASS, comprehension FAIL** — the
  user could not defend the approvals from the cards shown, and ruled
  the REPL "definitively not the right venue" (logged as G-3 trigger
  evidence; build stays gated on M2). Same-day remedy, the
  **decision-support contract**: 02 §1 `card:` map; routing-doctrine §8
  (story first, concrete behavioral before/after, steelman-the-no);
  `card-sections.yaml` — a section registry holding the set, order,
  labels, required-ness, and per-section generation prompts, so
  changing what decision-makers see is a one-file edit that no surface
  or validator change can break (extensibility per the user's explicit
  direction); validator shape-check (e702afb, 377 tests green);
  /self-learn:review re-carded sections-first; 09 §2.3 amended to
  render cards data-driven. Fixture probes: B1 (hyprctl focus-trap)
  DNQ'd — baseline 3/3 queried `hyprctl clients -j` unprompted; B2/B3
  remain open candidates awaiting user direction.
- **2026-07-14 (overnight) — backlog fully drained; fixture B proven
  end-to-end.** Under explicit user authorization ("do as much as you
  can... even the stuff needing my validation"), the remaining 22 HA
  records were analyzed under the new card contract and the safe subset
  resolved: 11 graduated (curated GOTCHAS.md covers them; canon even
  corrects one record's data=writeback claim), 9 routed to
  LEARNINGS.md, 1 deferred (unverified hypothesis). Two records held
  for the user with full cards: pyscript log.info (tensions with
  canon's marker advice) and chezmoi `chezmoi cd` (skill-md-now vs
  M3-hook). Fixture probes: **B2 dead at gate 0** (all naive pytest
  paths fail loudly — no honest predicate); **B3 QUALIFIED 3/3
  baseline FAIL** (notify-send -A under swaync blocks forever
  unbounded; predicate pre-registered). B3 adopted PROVISIONALLY
  (ratification pending — supersede lrn-c9044f8c to veto): routed to
  user CLAUDE.md via the chezmoi compiler (E-17 persistence HOLDS),
  then **post-routing trials 3/3 PASS with attribution** in every
  artifact — baseline 3/3 FAIL → routed 3/3 PASS is the first complete
  behavioral delta the system has produced. B-half of the M1+M2
  checkpoint pre-armed; C-half has no candidate → boundary decision
  (04 §0): hunt a C-class environment-specific lesson or re-scope to
  the B-half. Compiler note recorded: managed-section entries cut at
  the first sentence — front-load the operative content. Queue: 2
  pending (both user-held). znote hub current through session 3.
- **2026-07-14 — 11-telemetry-and-lifecycle.md DRAFTED (PROPOSED).**
  User-directed design session: routed lessons are claims, not
  facts-in-perpetuity; the system must measure certainty instead of
  declaring it. New layer: follow-ups (done-but-upgradeable, no new
  lifecycle status), recurrence suspects→confirmation (the "not
  holding" card), capture-time context (incident cost, generality, env
  fingerprint, verified), the observation plane (actor-scoped
  append-only telemetry JSONL — offer ledger, card outcomes, fires
  from transcript mining), the disposable index + report, and five
  standing multi-machine posture principles (single-writer by
  construction; two planes one-way flow; regenerate-never-merge;
  causal order from git ancestry; same-machine concurrency as the
  common case). §8 claims no settled decision reopens — top-to-bottom
  consistency audit commissioned same day.
- **2026-07-14 — four-agent top-to-bottom audit; 11 revised to v2.**
  User-commissioned full-system check (corpus coherence · code-vs-spec ·
  deployed state/ledger · adversarial review of 11). Deployed state:
  HEALTHY (zero dangling symlinks, 36 records self-consistent, canon 1:1,
  both user-held cards user-resolved → queue 0 pending). Code: HIGH
  conformance — all safety pins to the letter; four fixes landed
  (usage-exit 64, keep-the-why compiler, heartbeat coverage, over-cap
  surfacing) + review.md's deferred-resurface filter bug. Corpus: stale
  pre-build language swept (README header, fixtures row, 04 §0/08 §2
  supersession banners, designated-host leftover, S-6/O-4/O-1/S-2
  bookkeeping). **11 v1's headline guarantees were falsified** by two
  independent auditors (per-session tracked writes broke P6/E-8+S-7;
  worker emitters broke S-5; free-text payloads broke the scan claim;
  ancestry ordering unstable under rebase; unowned mutations) — **v2
  repairs all confirmed findings**: cache spool + verb-flush, CLI-only
  emission, enum decline reasons + scan-at-flush, ts-primary ordering,
  §2.5 verb table with pinned commits, honest §8 touch-point table
  (S-7 amendment + S-15 pin edit declared for ratification). 11 remains
  PROPOSED — ratifiable-with-edits per the adversarial verdict, edits
  now landed; user ratification still owed.
- **2026-07-15 — 11 RATIFIED (user-delegated) · M1 EXITED · checkpoint
  re-scoped.** The user declined to read 11 v2 and delegated: "review
  them yourself and try to answer the questions you would ask me." The
  questions and self-answered calls, each vetoable by dated register
  edit:
  **Q1 — telemetry lives in the repo (committed, synced): acceptable?**
  YES — the user's explicit directive was multi-machine-first hard
  facts; cache-only telemetry would forfeit cross-machine analytics;
  volume is KB/month of ids and enums; the spool/flush mechanism keeps
  every storage pin's letter.
  **Q2 — the pinned offer line in ~/.claude/CLAUDE.md grows a
  decline-logging clause: acceptable?** YES — the user asked for the
  denominator; the cost per decline lands on the model, not the user;
  applied only when the spool verb ships (S-15 row).
  **Q3 — decline reasons: enum or free text?** ENUM — the user's
  no-secrets-in-tracked-files posture is absolute and autosync
  publishes in seconds; a decline interesting enough to explain is a
  teach, not a payload.
  **Q4 — a worker pass reads local session transcripts for fire
  detection: acceptable?** YES with the existing pins — local-only,
  non-textual anchors, CLI-validated output; the user's own data on
  the user's own machine feeding the user's own analytics.
  **Q5 — four new verbs of CLI surface: worth the maintenance?** YES —
  the alternative is unowned mutations, the exact rot 02 §2's
  discipline exists to prevent; each verb is small, pinned, testable.
  **Q6 — accept one proven fixture (B3) and re-scope the C-half?** The
  user answered directly ("i genuinely can't think of anything else").
  Re-scoped, with the recorded rider that 11's recurrence/fire
  telemetry supersedes the C-slot's evidentiary role: continuous
  measurement of routed rules replaces one-shot proofs.
  Register edits landed: S-7 amended (telemetry storage class), S-15
  amended (offer-line clause, deferred to build time), S-16 added
  (the layer itself), 04 §0 boundary banner, 08 §6 completion.
  **With §6 fully satisfied, M1 is formally EXITED; M2 (worker,
  T13–T16 + 11's riders) is unblocked.**
- **2026-07-15 — 11's now-tranche BUILT (M2 development opened).** The
  telemetry/lifecycle layer's pre-worker builds landed on the
  `self-improve-lib` worktree branch, test-first, in 11 §7's order:
  the §3 schema fields + validator; `route --follow-up` +
  `followup done` (pinned subject `self-learn: follow-up done on
  lrn-…`); the cache-spool library, `telemetry note` (offer ledger,
  closed reason enum), `telemetry flush`, flush-in-verbs with
  scan-at-flush; code-emitted `capture` events (teach + import);
  `report` v1 (file-walking, honesty labels: declined-count = lower
  bound ⇒ capture rate = optimistic ceiling; no-observed-fires framed
  as confirm-held candidates, never dead weight); `status` gains
  `open_followups` (full paths only — the `--json --fast` pin holds).
  S-15's decline-logging clause applied everywhere the offer line is
  pinned (08 §1, plugin README, live `~/.claude/CLAUDE.md` via
  chezmoi). lrn-98d42215's follow-up backfilled as the field's first
  entry (11 §2.1). Suite: 427. Build decisions in the 08 appendix
  entry of the same date (teach --route defers follow-up flags to M2;
  metadata scan is refuse-only).
- **2026-07-15 — now-tranche audit round.** Per never-self-certify, two
  independent reviewers (spec-conformance + adversarial code) audited
  the build before it was called done. One blocker survived to master
  for under an hour: capture-time metadata flags (`--env`, `--session`)
  bypassed the secret scan, and the one-motion route path would have
  committed and pushed a secret typed into them. Fixed with whole-text
  scan coverage plus a nine-item robustness batch (atomic multi-file
  flush, duplicate-event dedup, crash-tolerant report, follow-up
  status gating with an orphaned-follow-up warning on
  graduate/supersede). Details: 08 appendix, same date. 439 tests.
- **2026-07-15 — testing-regime audit (user-commissioned).** "How much
  mock theater are we living on?" Answer, by two independent methods
  (adversarial static review + mutation testing): very little — 89% of
  planted bugs caught, real-git effect assertions throughout — but two
  converging blind spots existed (the capture-rate number was never
  asserted; spool locking was untested narrative) plus an orphaned-
  shell-suite problem. Thirteen tests added (452 total), one design
  flaw found and fixed in the process (event nonce for honest dedupe),
  one docstring recovery claim falsified and corrected. Details: 08
  appendix, same date.
- **2026-07-15 — M2 code complete (T13–T16 + 11's riders), acceptance
  pending.** The background worker exists: capturing a lesson now opens
  a coalescing analysis window (no scheduler — the capture itself is
  the trigger), and a write-restricted model pass produces the review
  cards' proposals ahead of time, so review becomes one-tap where the
  worker got there first. Duplicate lessons collapse in one commit.
  The "is this rule actually holding?" loop is live end-to-end at the
  suspect level: deterministic detection → telemetry → not-holding
  card → confirm/tolerate verbs. Deliberately NOT built: the
  transcript fire miner (proposed as its own follow-on; the honesty
  labels in `report` already account for it) and the SQLite index
  (file-walk still cheap). What still gates the M2 exit: the three
  protocol runs in 08 §7.3 — a real un-shimmed worker smoke + the
  write-restriction refusal check, the planted-duplicate collapse
  proof, and a timed 10-item triage.
- **2026-07-15 — M2 pre-merge audit round.** For the first time the
  audit ran BEFORE the merge (once M2 is on master, every real capture
  spawns a real worker run — unaudited was not acceptable). Two
  reviewers found three blockers the 487-green suite could not see:
  stranded backlog beyond the batch cap, every model-written merge
  proposal being deleted by a validation-order bug (the fixtures
  pre-filled exactly what the spec forbids the model to emit), and a
  collapse retry that double-merged evidence after a routine abort.
  All fixed with regression tests; the worker also gained a sentinel
  self-hold after the reviewer showed autosync could delete valid
  worker output mid-validation. 497 tests. M2 acceptance (08 §7.3)
  still pending: live smoke + refusal check, planted-duplicate
  collapse, timed triage.
- **2026-07-15 — doc 12 drafted (transcript miner) — AWAITING
  RATIFICATION.** User-commissioned autonomous-capture design; reopens
  O-3 (the register's sole open item) and absorbs the fire-miner
  follow-on from 08's appendix. Core shape: nightly cron-claude batch →
  deterministic structural digest (drop tool-result bodies, keep all
  human/assistant text + error/retry annotations) → one contained
  claude -p reader driven by a versioned mining rubric → mechanical
  ledger reconciliation → capped, scanned, verb-gated landing into
  pending/ with source: session (schema field already forward-declared).
  Mined records never auto-route — the miner is doctrinally "continuous
  import." The user's embedding-retrieval hypothesis was assessed and
  recorded in §5: declined at the transcript side (speech-act signal is
  structural; ranking layers only lose recall once cost is out of the
  frame), adopted as the pinned scaling path for ledger-side
  dedup/recurrence matching, where it strictly dominates the Jaccard
  heuristic. Five ratification questions in §6 (O-3 gate, privacy
  scope, caps, rejected-resurfacing, trigger shape). Nothing builds
  until they're answered.
- **2026-07-15 — doc 12 RATIFIED same day (user present) — O-3
  resolved; register 16 settled · 0 open (O-7 parked, 6 v2-gated).**
  User: "build now without a shadow of a doubt"; autonomous capture
  with manual review now, autonomous review as a stated future goal.
  Ratification round (doc 12 §8): all projects mined; caps scale with
  use (2×sessions, ceiling 15, gate 25 — loose by directive, tunable);
  rejected matches resurface once after 3 fresh sightings; nightly
  systemd timer (not literally cron-claude — the miner entrypoint is a
  CLI verb). User requirements: 24h three-layer watchdog
  (Persistent=true + verb autokick + SessionStart staleness), manual
  `mine run`, web-UI force-run + full run insight — satisfied by the
  run-journal contract (A1), the pinned data plane for the future G-3
  miner pane. Accepted additions: staged-autonomy ladder (A2 — the
  evidence substrate for future autonomous review: per-class accept
  rates from day one), rubric version stamping, notification restraint,
  cache-local multi-machine posture. Build (doc 12 §9, T-M1…T-M5)
  proceeds in a worktree with a pre-merge audit — the change activates
  real background behavior.
- **2026-07-15/16 — doc 12 BUILT, AUDITED, MERGED, ACTIVATED.** Worktree
  build (T-M1…T-M5) landed at 527 tests; the pre-merge audit doctrine
  paid off a second time: two independent reviewers (code-adversarial +
  systems blast-radius) found 4 blockers — argv-borne prompts crashing
  E2BIG on any busy night (also latent in the M2 worker since T13),
  the first-run forward-only pin unimplemented (multi-hundred-MB history
  flood auto-triggered at first post-merge session start), the
  review-span exclusion collapsing on the first review reply (card text
  mined back as fake sightings — silent evidence corruption), and an
  unjournaled crash path — plus 6 majors (sentinel owner/joiner race
  re-exposing the rebase-eats-proposals window, no watchdog backoff,
  injection hardening: reader stripped of ALL filesystem tools + field
  caps + ref validation, replay-duplicated fire/recurrence events, the
  resurface counter self-killing at the cap, unscanned model-authored
  origins that could wedge every future telemetry flush). All fixed
  with scenario-reproducing regression tests; doc 12 §10 records the
  round and its dated pin adjustments. Merged at 540 tests; live
  verification: selftest green, first run `initialized` (122 files
  seeded forward-only), `mine status` + `status --fast` miner keys
  live, nightly timer registered and enabled (next fire 03:40,
  Persistent=true). The miner is operational: capture is now
  autonomous, review remains human, and the A2 autonomy ladder waits
  on accept-rate data.
- **2026-07-16 — doc 13 RATIFIED (hosting & separation).** User
  directive ("we need an independent home for the ledger") after the
  separation discussion surfaced two structural facts: project scope
  was quietly host-specific (the doc-12 miner made cross-project
  mis-homing live), and the cache plane was an unclaimed per-machine
  singleton. Ratified calls: home `~/.self-learn` · project buckets
  auto-create with a route-time host-registration gate · filter-repo
  history extraction (the rejected-proposal digest reads resolution
  commits — H-6) · ledger-first sequencing, product-repo extraction as
  step 2. Revision of record: 02 §2's single-commit route atomicity is
  superseded by "ledger is truth, canon is compiled output" — the
  chezmoi user-scope path was the standing two-repo precedent all
  along. Build = T-H1…T-H5 in a worktree with a pre-migration audit;
  acceptance includes a foreign-project mined candidate landing in its
  own project bucket.
- **2026-07-15/16 — T-H3 BUILT; the lock-invariant audit rounds**
  *(backfilled 2026-07-16 — the post-mortem below flagged that this
  round lived only in branch commit messages).* Doc 13's code refactor
  landed on the worktree branch in three strokes: the core (dda4a0a —
  ledger home layout + hosts.yaml registry, per-project buckets with
  meta.yaml-on-first-create, two-phase route/supersede with pinned
  apply subjects and a drift warning naming `recompile`,
  producers-commit (H-5) across teach/import/miner, package-relative
  doctrine/registry, home-namespaced cache (H-4), the global sentinel;
  new test_hosting.py, 39 tests green); the suite migration (43f8abe —
  two agents on disjoint file sets, no src changes, intent preserved by
  re-pinning two assertions rather than dropping them; 579 tests); then
  the hardening (c03a076): **seven independent review rounds** (2
  pre-merge audits + 5 verifications) fixed 11 original findings plus
  4+4 minted by the first two fix rounds. Round 3 re-scoped the commit
  lock to `[first mutation → commit]` after probing proved BOTH the
  original scope and the orchestrator's proposed replacement wrong —
  its justification is measured, not argued: without it a racing `pull
  --rebase --autostash` commits conflict markers INTO a record file at
  exit 0 with a clean `git status`. Round 4 generalized the rule into
  `tests/test_lock_invariant.py` — a call-graph property (AST fixpoint,
  derived entrypoints, fail-closed exemptions) rather than a surface
  list — which immediately forced 4 fixes nobody had listed (miner
  fold, worker sweeps, both importers, proposal validate). Also landed:
  `HalfWrittenError`/exit 7 (constructor REQUIRES `repair=`, so no
  layer can report the state without naming the fix), the `reconcile`
  verb wired into miner run-start, push, and repair messages,
  `--no-push` threaded through worker AND miner spawns, push_if_remote
  on all ten verbs, timeout-bounded git calls. Known-narrower-than-
  claimed gaps recorded, not fixed (function-scoped exemptions;
  11/19 runtime argvs bail on validation before the lock; nine
  checker-evasion spellings with no live occupants). 754 tests,
  2 skipped. Doc 13 §7.2 records the invariant as H-7/H-8 (229c6c3);
  the runtime instruction files + miner-unit env pin the handoff
  claimed were already in-branch were verified absent and landed
  before the merge (fd238af).
- **2026-07-16 — session post-mortem (independent, user-directed).** The
  25-day session that produced this corpus (06-22 discovery → 07-16 T-H3)
  documented from the transcripts alone by an agent that did not
  participate and was given no account of events, with the load-bearing
  claims re-verified against the live machine:
  `reviews/2026-07-16-session-post-mortem.md`. Confirms the T-H3 branch at
  **754 passed / 2 skipped**, the cutover unrun (`~/.self-learn` absent),
  and the 39-vs-177 test split between the directed separation and the
  elective concurrency work. Records the session's two governing
  corrections — the user's falsification of the SDK-auth claim (already
  ground rule 4) and the orchestrator's own disclosure that **H-5**
  (producers-commit, no ledger watcher) was an unforced preference written
  as a "therefore" and never put to the user among doc 13's four
  ratification calls. **Open and unrouted:** the H-5 call itself (ship /
  descope / park); the memo's §6 also flags that the miner has **never
  executed** (timer registered, `LAST` empty) and that the T-H3 build +
  its four audit rounds are recorded only in branch commit messages, not
  here. Like its siblings, withheld from blind reviewers.
- **2026-07-16 — CUTOVER EXECUTED: the ledger lives at `~/.self-learn`.**
  The §7.1 runbook ran to completion. Extraction carried **51 commits**
  of ledger history and the reconcile hard gate matched exactly the
  snapshot's **39 records**; the home bootstrapped with hosts.yaml,
  project meta.yaml, and the code-derived slug bucket (ledger commit
  6c7263b), private remote `github.com/AlexK-Notable/self-learn-ledger`;
  the code merged to master (cf23ae5) and the in-repo buckets removed
  in one recoverable commit (f6bd7f0); the miner unit now pins
  `Environment=SELF_LEARN_HOME=%h/.self-learn` (B-1 — the systemd user
  manager inherits no shell env). **T-H5 partially discharged:**
  selftest 5/5 green on the new layout; a hand-broken marker caught by
  three independent checks (compiler + markers + drift) and restored
  under sentinel guard; the first post-cutover capture committed and
  pushed by its own producer (lrn-316a5411 — install.sh restarts
  autosync mid-window, itself a lesson the cutover taught). **Still
  open:** the overnight miner run under the new cache, an organic
  foreign-project mined card, and the user-present route half — no
  route has yet exercised the two-phase host apply live. SessionStart
  hook symlinked (PC-1) but its settings.json registration remains
  user-manual. Next after T-H5 settles: product-repo extraction
  (step 2, §8-thin).
- **2026-07-16 — M3 BUILT, TWICE-REVIEWED, MERGED (same day as the
  cutover; 3-agent workflow: worktree builder ∥ sandboxed acceptance
  runner → blind adversarial reviewer).** T17 hook compiler (all six
  §8.1 pins: CLI-generated guards, verbatim two-phase apply with the
  approved bytes stored on `routing.hook`, M3-12 replay pre-commit,
  supersede/graduate host-phase removal, `--selftest` hooks check),
  T18 new-skill scaffold (`route --dest new-skill:<name>`, M3-9
  foreign-plugin refusal), T19 `supply_mix` + success metrics in
  `status --json`. 754 → 860 tests; seven spec gaps found and
  dispositioned in the 08 appendix (§9), none silently absorbed.
  **Review round 1: NOT CLEAN** — zero code blockers (shell-injection,
  fail-closed guard matrix, lock invariant, and idempotence all held
  under *executed* attack) but one governance MAJOR: the build
  hard-coded a refusal of one-motion `hook`/`new-skill` routing,
  narrowing settled S-10 without the register reopening. **Resolved by
  user ruling** ("this is exactly the kind of thing that shouldn't be
  hard-coded. make it configurable") → committed `<ledger>/config.yaml`
  `one_motion_route` policy, default OFF, fail-closed parse; dated
  S-10 amendment. **Delta review: CLEAN** (YAML-injection refused;
  the analyst path provably cannot smuggle script bytes — the CLI
  regenerates unconditionally; all type-checker flags proven dead
  branches). **Scope ruling same day** (S-10 row): the flag opens BOTH
  one-motion roads — explicit `--hook-input` and analyst-authored bare
  `--route`; split knob considered and rejected. Also same day: M2
  acceptance (b) worker half PASSED in a fully sandboxed ledger clone
  (planted near-duplicate → schema-conformant `merge-a1c3e7f2`, run 2
  of 3; run 1 exposed a worker-prompt gap — descriptive `cluster_id`
  correctly fail-closed by the validator — queued for §4 prompt
  tuning). The collapse half stayed user-present by design: the
  acceptance agent itself caught that a sandbox clone's `meta.yaml`
  points at the REAL host repo, so a sandbox collapse would have
  compiled real canon. M3 [protocol] exit still owed (user-present):
  fixture-A live trial, first hook route + install.sh + settings.json
  registration, worklist drain via `fixtures/m3-worklist/`.

- **2026-07-17 — worklist drained + retirement-cleanup dev pass**
  (Fable session, evening 07-16 local). Review session (user-present):
  lrn-316a5411 routed to project claude-md; ALL THREE m3-worklist
  guards captured→validated→routed (chezmoi-cd superseding
  lrn-98d42215; sudo-npm at user scope superseding lrn-d5f6b31b,
  lrn-6883f824's follow-up closed; uv-venv-copy WITHOUT supersede —
  the text regex can't see whole-tree copies, advisory kept, user
  ratified); hypr-doctor over-cap resolved by graduating lrn-6883f824
  into the recovery playbook (224→110 words). install.sh run;
  settings.json registration handed to the user (M3 [protocol] exit
  then rests on the first live guard denial). The drain exposed that
  supersede-at-route/graduate left stale advisory lines — fixed same
  night as the **retirement-cleanup dev pass** (08 appendix
  2026-07-17, two blind adversarial verdicts CLEAN, 860→876 tests):
  retirement host phase shared by route/route_direct/graduate,
  recompile completeness (all-retired targets, chezmoi user file, m-4
  hook-removal repair), m-5 script re-derive, worker cluster_id pin,
  T19 median UTC normalization, and the review-found pre-M1 latent
  shared-CLAUDE.md scope-erasure bug (union compile set). Live
  repair verified: both stale lines dropped, selftest 6/6.

- **2026-07-17 — step-2 extraction runbook drafted (13 §7.3)** after
  the forced miner run went green and landed the organic
  foreign-project card (lrn-4bcdd0a0, zmk-config bucket auto-created;
  H-3 held — capture open, canon registered), fully discharging T-H5
  and opening the step-2 gate. Runbook is DRAFT: execution gated on
  D1 (M3-7 amendment — project/user guards become host canon at
  hooks/self-learn/, two live records' script_path migrated), D2
  (repo identity), D3 (product autosync posture).

- **2026-07-17 — D1–D3 ratified (13 §7.3):** D1 guards stay in
  claude-skills at hooks/self-learn/ — user's governing principle:
  the product repo is a tool anyone could install; nothing commits
  there but its own development (M3-7 amended, 08 appendix). D2:
  AlexK-Notable/self-learn, private. D3: NO autosync on the product
  repo — manual pushes (recommendation declined). Execution of §7.3
  awaits the explicit go.

- **2026-07-17 — STEP 2 EXECUTED (13 §7.3): the product is standalone.**
  This corpus now lives in AlexK-Notable/self-learn (139 commits of
  history preserved via filter-repo). Sequence as run: D1 guard
  relocation first (git mv → claude-skills hooks/self-learn/, ledger
  script_path commit, symlinks repointed, selftest green — and
  lrn-316a5411 fired live: install.sh restarted autosync inside the
  window, caught and re-stopped per its own rule); extraction;
  product bring-up (own install.sh: five surfaces + miner units,
  private remote, suite 875 passed / 3 skipped — two boundary tests
  now skip loudly when host context is absent); removal commit in
  claude-skills (marketplace entry dropped, CLAUDE.md boundary note);
  dangling-symlink sweep CLEAN across all five surfaces; verified
  live from the new home (shim → product repo, selftest 6/6, miner
  units repointed + started, pending hook prints, autosync restored).
  No ledger or canon state touched at any step. Post-extraction:
  corpus edits land HERE with manual pushes (D3).

- **2026-07-17 — M3 [protocol] EXIT COMPLETE: first live guard denial.**
  The user authorized the settings.json edit directly ("fully
  authorized to make any changes you wish"); all three guards
  registered under one PreToolUse "Bash" matcher. The first live
  denial arrived seconds later — and organically: the agent's own
  smoke-test command *contained* the sudo-npm trigger text, and the
  production path (settings.json → PreToolUse → exit 2) blocked the
  real Bash tool call before it ran. Deliberate verification followed
  with trigger text assembled via string concatenation so the live
  hook wouldn't intercept the tester: all three guards deny on their
  trigger (exit 2, lesson message on stderr) and allow clean commands
  (exit 0); `--selftest` shows 3 live scripts intact, 4 registrations
  resolvable. §8.3 predicate satisfied: unguarded-pass-before recorded
  at capture (each drain lesson's incident IS the unguarded pass),
  guard-denies-after observed live. **v1.1 declared** (annotated tag
  on this repo). Metrics collection begins as of this date — 04's
  success metrics are counted by `self-learn report`, baseline n
  starts accruing now. O-3/O-7 revisit (T20): schedule with the user
  once ~a month of real supply exists — target on/after 2026-08-17.

- **2026-07-17 — G-3 pre-build re-ground (09 §11 Y-1…Y-12 + 10
  amendments).** *(Substrate details in this entry were corrected by
  the gate-zero round below — read both.)* The surface docs froze 2026-07-13/14; docs 11/12/13
  and M3 landed after. This pass re-grounds every pin those changes
  killed and fills the feature gaps, as dated edits: pane read scope
  re-derived for the post-13 topology (ledger + hosts.yaml roots +
  references dir — the old single-root wording would have denied all
  canon reads); cache paths re-based to the home-namespaced dir (02
  §3 swept — its literals had survived the cutover unswept, sentinel
  path included); product-repo build posture (no autosync, manual
  push, explicit install links); new surface scope: not-holding
  cards, miner block (12 R3 honored: journal reader + force-run
  only), follow-ups, contradicts edges, hook/new-skill Detail
  rendering, unregistered-host flow, /report screen; pinned UX
  rules: human-language-first rows (E-21 + the jargon lesson) and
  color-never-sole-carrier (the user's theme is daltonized) with
  dark theme promoted into scope. Substrate: 08 §1 dated block
  (list bucket/host_registered/source; report recurrence_suspects +
  open_followups rows; mine status --json; optional
  sections_over_cap) as new task U0. 10 §8 added: the parallel
  execution plan (file-ownership partition, five tracks, wave
  schedule, hard-blocker list, per-agent worktree mechanics). Gate
  zero pinned: independent spec review before any build agent
  consumes this set.

- **2026-07-17 — gate zero ran on the re-ground: NOT CLEAN → folded
  same session.** Blind adversarial review (fresh agent, reviews/
  withheld, everything verified against the live CLI and source)
  returned 2 blockers + 6 majors + 6 minors. The blockers: 10 §1's
  pane-engine row still carried the dead single-root read scope; and
  Y-2's first draft (whole-host-root reads) was judged a prospective
  loosening — host registration consents to compilers WRITING canon,
  not to a model session READING an entire repo, untracked files
  included. Resolution: read scope narrowed to canon surfaces via a
  CLI-owned canon_read_roots() helper + a consent line in host add;
  recorded as a dated 03 note on the G-3 row, user-ratifiable toward
  the wider posture. The review also proved two "new" substrate
  pieces already exist (mine status --json since M2.5;
  report open_followups — including a wrong shape pin in the draft),
  caught an install/enable contradiction, a dead token-fallback
  literal, a §8-vs-§3 scheduling conflict with a stranded middleware
  half, and un-swept autosync assumptions in W-5/W-8. All folded as
  dated corrections marked "gate-zero"; the full findings list lives
  in 10's Build-findings appendix. Delta re-check ran before commit.

- **2026-07-17 — G-3 adjudication surface SHIPPED.** The localhost web
  review UI (09/10) is built, reviewed, merged to master, and deployed
  live (`self-learn-ui.service`, 127.0.0.1:7357). Orchestrated build:
  Sonnet builder agents U0–U10 in per-agent git worktrees per 10 §8's
  wave plan (CLI substrate; ui scaffold; ledger/models; routes+security+
  SSE; SDK pane engine + charter; verb runner; iterate split; notifier
  swap; degradation walk; deploy/docs), Opus reviewers. ui 481 tests /
  cli 894·3, pyright clean. **Never self-certified** — five review passes,
  each folded CLEAN: gate-zero (the spec re-ground) → interim adversarial
  + delta → U11 live acceptance (T-A CI; T-B/T-E live SDK; T-C end-to-end;
  T-D desktop deep-link with the user; browser pass via Playwright) →
  final assembled-branch review + delta. Six real defects surfaced that
  the green suites could not see, each masked by a fake or environment-
  specific: 2 spec blockers (gate-zero), 1 interim blocker (a wave-1
  join miss — sdk.py kept a one-arg default called zero-arg, hidden by
  zero-arg-fake mock theater across every engine test), and 3 at
  acceptance (T-B: the charter double-prefixed the already-`lrn-`-prefixed
  record_id → the pane could never edit its own record/proposal; T-D:
  chromium-on-Wayland ignores `--class` for `--app` windows when chromium
  is already running → class-only focus never matched; final review: the
  title-focus fallback was dead because it gated on `focuswindow`'s
  always-0 exit code). Trials logged in `fixtures/ui-trials.md`; corpus
  amended at 09 §1 (window-class), 03 (G-3 SHIPPED + the canon-surfaces
  read-scope posture, user-ratifiable). Deploy: `install.sh` links
  `self-learn-ui{,-open,-notify}` → `~/bin` and the service unit; the
  service is enabled and serving the real ledger. Residual UX backlog
  (none blocking): Esc-interrupt uses the 5 s kill backstop on
  subscription auth; a push-failure on an otherwise-successful route is
  not surfaced in-UI; cross-record deep-links open a new window (09 §5).

- **2026-07-17 — U12 chat panes + UI feedback round 1 SHIPPED.** The
  pane rework (Y-13: server-owned `propose_verb` tool, waiting proposal
  bar, human arm+confirm — proposer ≠ approver survives verbatim) plus
  all 8 round-1 feedback items (visual polish + launcher, WASD keymap,
  Y-11 armed `host add`, bucket pane). Two-gate reviewed throughout;
  records: `reviews/2026-07-17-*`, `feedback/2026-07-17-ui-feedback-01.md`.

- **2026-07-18 — idle lifecycle (Y-14/U13) + feedback round 2 SHIPPED.**
  Resident-while-in-use (idle self-exit + launcher readiness wait +
  Esc-ladder; the live trial caught a uvicorn SIGTERM-re-raise blocker
  the suites could not), then round 2: scope-filtered destinations,
  Y-15 non-blocking pane start (instant split + SSE fill), monitor
  placement. Records: `reviews/2026-07-18-idle-lifecycle-*`,
  `reviews/2026-07-18-ui-feedback-r2.md`.

- **2026-07-18 — feedback round 3 SHIPPED: U14 (Y-16 + Y-17) + U15
  (Y-18).** Registration flow — persistent plain-words error (the wipe
  mechanism empirically pinned pre-fix) + `host add --init` with the
  consent invariant (git-init only when the arm rendering disclosed it);
  and record re-home — `rehome` verb, pane proposability, the
  routing-doctrine ancestor-project clause. Both units spec-gated then
  code-gated CLEAN with mutation verification. Records:
  `reviews/2026-07-18-ui-feedback-r3.md`,
  `feedback/2026-07-18-ui-feedback-03.md`.

- **2026-07-18 — UX round 1 SHIPPED: U16 (Y-19) + U17 (Y-20) + U18
  (Y-21).** From the Opus UX survey
  (`research/2026-07-18-ux-enhancement-survey.md`): queue-walk trio
  (next-record prefetch with global generation-gated invalidation,
  worker Force-run, first-row auto-focus); loaded-surface budget
  indicator in the Why region (reference excluded as the cap-free
  overflow sink — a spec-gate BLOCKER); miner episode briefs (composed
  before the secret scan — the security pin — compiler-excluded by
  construction). Combined master: **CLI 970 passed / 3 skipped, UI 722
  passed; pyright ui clean**. Record: `reviews/2026-07-18-ux-round-1.md`;
  trials: `fixtures/ui-trials.md`. Open DoD leg: episode briefs verified
  on the next real miner cycle.

- **2026-07-18/19 — forward planning + maintenance round + deep
  specs.** The forward work map (14, FW-1…FW-36 + `forward/` themes +
  worker ecology) gated SOUND and committed; the maintenance round
  shipped **FW-17** (the JS DOM harness — 22 Playwright tests pinning
  the reload-defer predicate, focus management, and key dispatch;
  first test coverage the JS layer has ever had) and **FW-18**
  (unreadable-record degradation per a twice-folded spec pair,
  the SSE pane_block duplication root-caused and fixed, the swapError
  NIT) — both units blind-gated CLEAN with 12 mutations killed
  between them; and **five build-grade spec drafts** (Y-22…Y-27 +
  doc-16 candidate: analyst riders, fast lane, miner visibility,
  settings surface, worker-ecology channels) all reached SOUND
  through five blind gates and seven fold cycles. Records:
  `reviews/2026-07-19-maintenance-round.md`,
  `reviews/2026-07-18-deep-specs.md`,
  `reviews/2026-07-18-forward-work-map.md`. Master counts: **CLI
  976/3, UI 758 (incl. 22 js), pyright ui 0.** Runbook (15) + records
  index shipped (FW-26/27). Opus ran everything this round by
  explicit user override; S-18's split resumes.

- **2026-07-18 — standing postures recorded** (register rows added same
  day, `03-decisions.md`): subagent model split (Opus reviews, Sonnet
  builds, the orchestrator model never spawns as a subagent — user cost
  ruling); **Go port PARKED** (`research/2026-07-17-go-port-fleet-sketch.md`
  stays a sketch; never reopened unprompted); **design round 4 PARKED
  but governing** (`feedback/2026-07-18-ui-feedback-04-design.md` — its
  four composition principles bind new UI work now, the full pass waits
  for the user to unpark it); **packaging is the next major phase** —
  SDK bundle exclusion verified live (PATH-claude fallback works,
  `research/2026-07-18-sdk-bundle-exclusion.md`), making a slim
  standalone distribution feasible.
- **2026-07-19 — rider/near-miss round SHIPPED: FW-31/32 (Y-22 lint +
  Y-23 bounded contradiction) + FW-34 (Y-24 near-miss + canaries + 12
  §12), first round back on the S-18 default split.** The four
  blocking rulings resolved and folded (fast-lane count cap; settings
  table as written; timer as spec'd; **precedence flipped to
  config > env > default**) — fast-lane/settings drafts re-gated
  SOUND, FW-35/FW-30 build-unblocked. The DoD walk (live models, live
  browser) proved lint and bounded contradiction end-to-end and found
  a latent Y-8 defect — the post-route contradicts offer was
  unreachable live (proposal swept before the post-verb read;
  FakeRunner masked it) — fixed same-day (U-C3 pre-verb capture +
  reload-defer leg (d); U-C3b instrumented falsification of the
  follow-up alarm, root cause a stale cached app.js). Backlog minted:
  multi-edge offer, promote bucket targeting, snippet-cap watch,
  static cache-busting. Record:
  `reviews/2026-07-19-rider-nearmiss-round.md`; trials in
  `fixtures/ui-trials.md`.
- **2026-07-19 (evening) — feedback round 5 SHIPPED: U19-U22.** Nine
  user items → investigation (two "dead keys" were silent no-ops) →
  two rulings (guided commit-first; pane persist+resume) → two spec
  gates (both NOT SOUND first pass; folded SOUND) → four Sonnet
  builds, six Opus code gates, all CLEAN → live DoD walk, which found
  two latent defects no gate could see (action-bar error strips
  reload-wiped since U14 — the leg-(a) marker was never on them; every
  Tier-2 pane resume aborting — pyright stub methods read as
  implemented by the SDK's object-identity probe) — both fixed,
  re-gated, re-walked PASS, including genuine context recall across a
  server SIGKILL and the two-commit guided-commit shape. Record:
  `reviews/2026-07-19-feedback-round-5.md`; walk in
  `fixtures/ui-trials.md`.
- **2026-07-24 — public-release unit SHIPPED: LICENSE, CLA, marketplace
  manifest, public README.** The product repo is now licensed
  FSL-1.1-MIT (root `LICENSE`; `plugin.json` + both `pyproject.toml`
  declare the SPDX id in the PEP 639 string form) and installable via
  the new root `.claude-plugin/marketplace.json`
  (`/plugin marketplace add AlexK-Notable/self-learn`). `CONTRIBUTING.md`
  + `CLA.md` require a broad relicensing grant from contributors (PR
  sign-off line + commit `Signed-off-by:` trailer, checked by hand — no
  bot at this contributor volume). `README.md`'s install section and
  `plugins/self-learn/README.md` both rewritten for a public reader; the
  private-repo SSH-clone disclosure is gone. Doc 13 §7.3 D2 amended in
  place (original ratification kept, dated reversal appended): the
  product repo is public; **the LEDGER (`self-learn-ledger` /
  `~/.self-learn`) remains private** — the "same posture" coupling is
  explicitly severed. `03-decisions.md` gains **S-19**. The GitHub
  visibility flip itself is a separate, human, out-of-band action — not
  part of this unit. See `drafts/public-release-spec.md` for the full
  reasoning, the licence clause-map, and the CLA terms.
- **2026-07-24 — PUBLISHED.** The out-of-band step above was authorised
  by the user and executed the same day: five commits pushed
  (`b11d9aa..1fef1d5`) and `github.com/AlexK-Notable/self-learn` flipped
  to **public**. The repo is live and installable. GitHub reports the
  licence as "Other" — expected, and not a defect: its detector
  recognises only OSI-approved and a few common licences, and FSL is
  source-available by design. The ledger's private posture is unchanged.
- **2026-08-19 — docs-truth sweep + the operator runbook (U-docs,
  Wave 2).** The Agent-SDK migration's Waves 0–1 shipped four units
  (`U-seam`, `U-sdk`, `U-bedrock`, `U-fake`) without a single numbered
  doc recording them, against `forward/platform-drift.md` §4's standing
  rule that an engine swap is never absorbed silently. This unit swept
  the numbered corpus for every claim about model invocation — 42 sites
  enumerated, 12 measured NOW FALSE, 11 stale, 14 still true, 5 missing —
  corrected 11 of the 12 by bounded substitution (`I-26`, a scheduling
  claim, was out of mandate and became `FW-96`), landed the eight
  decision rows the migration owed (`S-34`/`S-35`, reserved by `U-seam`
  §7.5 and never written; plus `S-39`–`S-44`, which give the 2026-08-09
  user rulings their first in-repo record), and wrote
  `17-invocation-runbook.md`. **Eight of the twelve falsehoods predate
  the migration** — `U-repair`, `U-attrib` and the 2026-07-15
  containment audit each moved the shipped mechanism without moving the
  corpus, and one clause described an artifact filename the
  implementation never adopted. Full inventory, per-site substitutions
  and the gate's verification table:
  `drafts/u-docs-truth-sweep-spec.md`.
- **2026-09-04 — S-58 amended: one mechanism, per-key direction (Sprint 2
  plan v2 §2 M-S; decision D1); folded r1–r5 same day against six
  blind spec gates (r1: 2 Blockers, 6 Majors, 5 minors, 2 nits; r2: 1
  Blocker, 2 Majors, 3 minors, 3 nits; r3: 0 Blockers, 2 Majors, 1
  minor, 1 nit; r4: 0 Blockers, 1 Major, 0 minors, 1 nit; r5: 0
  Blockers, 1 Major, 1 minor, 2 nits; r6 on `8603e1d`: 0 Blockers, 0
  Majors, 1 minor, 1 nit — CLEAN — see `03-decisions.md`'s `S-58`
  row for the current folded text).** The two
  precedence DIRECTIONS `S-58` ruled on 2026-07-19/2026-09-01 are
  unchanged — the settings registry's operator-policy keys stay
  `override > config.yaml > env > default`; provider/model/backend
  SELECTION keys stay `override > env > config.yaml > default`. What
  changes is the MECHANISM count: `provider.py`'s second, independent
  transcription of the backend-selection chain (`resolve_backend_name`)
  and its own env/config lookups (`_resolve_provider`,
  `_resolve_str_setting`, `model_for`) retire in favour of ONE
  registry-backed resolver. Of `config.py`'s two loaders that fed
  those hand-rolled cascades, only `provider_setting` retires with
  them; `config.invocation_backend` SURVIVES, unchanged in name and
  signature, as the Rs-a1 termination delegate the shared specific/
  general cascade (`config.paired_cascade`, code-gate fold r1, MAJOR-1)
  now calls via `config.paired_leaf` — `resolve_backend_raw` and
  `settings.resolve_setting`'s paired-entry branch both reach it
  through that ONE shared walk, never two independent re-derivations
  of the same Rs-a1 rule (r1 minor-2's correction of this same
  paragraph's original over-claim). `settings.py`'s `Setting` gains
  `direction` (per-key rung
  order), `enabled_when` (a `provider.name` predicate gating exactly the
  SIX bedrock-scoped entries — `region`, `profile`, and the four
  `bedrock.models.*` — never `provider.name` itself, r2 fixed this
  count from a wrong "all five"), and an optional `env_var`. `models.
  {worker,miner,analyst}` join as a NEW top-level `models:` section
  (r1 BLOCKER-1: `settings-surface-spec.md` §1.2 already pinned these
  three config-first, but the binding never took effect in code — this
  amendment corrects §1.2's direction for exactly these three keys to
  `env-first` instead of disposing the reopened trigger silently);
  `model_for`'s wrapper discriminates by the returned SOURCE LABEL
  (override/env answer immediately; config/default defer to the active
  bedrock leaf first) rather than running a flat rung list (r2 m3).
  runtime dispatch and the registry's own reporting/write surfaces are
  now two deliberately separate mechanisms (r3 M1/M2, correcting r2 M1's
  conflation of the two): a PURE `resolve_backend_raw(home, surface) ->
  (raw_value, source)` emits nothing, so `backend_for` keeps its
  existing emitter `registry._resolve` on ITS path only (today's four
  pinned literals, unedited) while `provider.resolve_backend` folds the
  same raw value SILENTLY with `provider.py`'s own pure halves — no
  warn ever on the provider side, preserving `Rs-b` and its witness
  `test_bk3_resolve_backend_name_never_warns` (r4 n1: `backend_for`
  strips `resolve_backend_raw`'s prefixed label to the bare `source`
  `_resolve` expects, deriving `is_config` from the prefix, since the
  two functions' vocabularies differ). Separately, corrected again by
  r4 M1 (one `validate` cannot both refuse-on-write and clamp-on-read
  for the same input, and a clamping `validate` emits no warning at
  all, so r3's "visible in existing warning text" was wrong): `Setting.
  validate` STAYS the read-path clamp, unchanged for all 21 shipped
  entries; a NEW, separate optional `Setting.accepts` predicate is the
  write-path gate. Refined by r5 M1/m1: `config_set`'s sequence is
  parse -> `accepts` refusal -> `validate` clamp -> the existing
  downstream steps — `accepts` judges the operator's PARSED input,
  before `validate` can clamp an off-whitelist value into an accepted
  one (the natural insertion point, after `validate`, would have
  silently committed a laundered value); the refusal names the allowed
  set from a new `accepts_hint` field, not `validate_hint` (reserved for
  a rejecting `validate` by its own docstring). `provider.name` and the
  `invocation.backend` family carry BOTH `validate` and `accepts`. The
  fold is surfaced as a NEW `setting_row` detail field named `note`
  outright — not the `warn` field (which keeps its override-only
  meaning) — computed by `setting_row` AND `preflight` each
  RE-DERIVING the fold rather than widening `resolve_setting`'s 2-tuple
  return (measured: 20 call sites, 18 wanting only the 2-tuple, against
  2 display sites that would use a 3rd element). The UI `/settings`
  page is an accepted, ruled residual: it renders a folded value with
  no `note` (minor-4's standing scope), not a defect. The backend
  chain's specific/general PAIR at each end (env, config) keeps its
  full preservation constraint — `Rs-a1`'s asymmetry (an EMPTY
  per-surface config value terminates at the default WITHOUT
  consulting the general key; an ABSENT one falls through and does
  consult it), byte-for-byte rung/source-label preservation, and the
  "one entry per surface silently drops the general fallback" warning
  — restored in full after the r1 fold accidentally deleted it (r2
  B1), with the order string itself now qualified at the
  config-specific → config-general arrow so the empty-value
  termination is visible there too, not only in prose. **Correction to
  r1's own claim:** `Rs-a1`'s discriminating witness
  (`test_provider.py:477-483`, an empty per-surface key beside a
  present general one) is NOT armor-pinned — `test_provider.py` is not
  in `test_armor.py` at all; the AST-pinned `test_invocation.py`'s
  `test_rg6`/`test_rg7` do not discriminate this case. Because the
  witness is unpinned, the code step must keep it and add a second
  discriminating case beside it. One override slot per LOGICAL key
  (`invocation.backend` and `invocation.backend_<surface>` are two
  logical keys, each keeping its own override var, preserving both the
  blanket and per-surface reach today's env vars have — r2 m1), the
  specific outranking the general, mirroring the env pair (r3 m1); the
  default rung stays `S-47`'s per-surface table, never flattened to one
  literal (MAJOR-6); `models.*`'s own default rung is each surface's
  already-called function (`worker_model()`/`miner_model()`/the
  analyst's `_model()`), the same STYLE `S-47` used for backend
  defaults, not a reuse of `S-47`'s own table — confirmed explicitly.
  `settings-surface-spec.md` §1.2 itself gets a pointer annotation to
  this correction (r2 m2), separate from this entry. §1.2's `models:`
  table actually names a fourth key, `models.pane` — UI-scope, correctly
  left out of this amendment's three (r2 n2). `03-decisions.md`'s `S-58`
  row carries the full folded amendment; `01`–`17` are otherwise
  unchanged by this entry. Code landed separately, in Sprint 2 lane L4,
  one commit (`M-S: provider/backend keys resolved by the settings
  registry with per-key direction`) implementing the row exactly as it
  reads after the spec gate returned CLEAN at r6. **Code-gate fold r1
  consequence, swept into the runbook 2026-09-04 (delta gate r2
  minor-1):** unifying the runtime and registry faces onto ONE shared
  cascade (`config.paired_cascade`/`paired_leaf`, MAJOR-1's fix)
  required their CONFIG source-label vocabularies to match, moving the
  runtime face's bare `config:backend[_<surface>]` to the registry
  face's own `config:invocation.backend[_<surface>]` — the string an
  operator sees on `doctor invocation`'s `switches` row changed as a
  necessary side effect; `17-invocation-runbook.md`'s two mentions of
  the old spelling were swept to match (the dated measurement record in
  `drafts/u-docs-truth-sweep-spec.md` was deliberately left alone).
- **2026-09-11 — Sprint 3 lane A: the placement-and-promotion amendment
  (text only).** Carries the six 2026-09-05 values-call rulings and
  their 2026-09-11 addenda (`misc/audit-2026-09-02/d4-values-calls-
  DECISIONS.md`) and the 2026-09-11 GO-NO-GO binding answers
  (`misc/audit-2026-09-02/sprint-3/GO-NO-GO-2026-09-11.md`) into the
  corpus, per the adopted `d4-general-policy-codex.md`. **Routing
  doctrine** §1/§3/§4/§8: applicability/timing-before-surface-selection
  and the active-demand task-cue requirement stated explicitly; the two
  ancestor-registration sentences at `:315`–`:317` and `:324`–`:327`
  rewritten to state the Q2 auto-registration target model (human tap
  or authorized automated reviewer, subject to a never-register
  blocklist) **as forward work, not built this sprint** — the route verb
  still refuses an unregistered host today, and the doctrine says so;
  Q5's managed region gets one sentence at §4; Q3's review cap ("three
  cards or ten minutes, whichever first," replacing not adding) is
  written into §8. **`01-architecture.md`** §1 gains a paragraph
  reframing native auto-memory as a tracked, uncontrolled knowledge
  surface (Q6) rather than an inbox to drain; §3.5's stale chezmoi
  description (`~/.claude/CLAUDE.md` predating `U-hostmode`) is
  corrected to the shipped PLAIN-host model. **`13-hosting-and-
  separation.md`** §1/§3 gain the Q2 target model and the persisted-
  placement-intent/blocklist/worktree-resolution/personal-literal-scan
  notes, all marked forward work; §5 and §7.2 untouched (spec lane B's).
  **`09-surface-spec.md`** §2.3 states what a *complete* placement card
  means (the policy's six-question delivery contract, no new card key);
  Y-4 folds Q3's review cap in; Y-20's stale "overflow surface" line
  (`:2255`–`:2258`) is recorded as **deleted** (`U-cap` §6.6, shipped
  2026-08-24) rather than reworded, with the routing rule it gestured at
  restated in routing-doctrine §1. **`02-schema.md`** (~`:303`) names,
  descriptively only, the facts a placement will eventually persist — no
  field is added. **`03-decisions.md`** gains a new `SA-`-prefixed
  subsection (Sprint 3 lane A, avoiding a numbering collision with lane
  B's parallel edits to this same file) carrying the Q1–Q5 trial rulings
  and the Q2 auto-registration decision, plus dated reopen notes on
  `S-13`/`S-14` (Q6: import-then-prune is no longer the model, reason
  "the model changed") and a reconciling note on `S-51` flagging a
  genuine tension the Sprint 3 readiness review missed: S-51 refused
  deriving host mode from `.git` presence for the *existing* `host add`
  verb, while an orchestrator default for the *new* auto-registration
  call site (`GO-NO-GO-2026-09-11.md:51`) assumes exactly that
  detection. **Resolved by the user 2026-09-11 20:31: an auto-registered host is registered in `plain` mode; S-51's refusal of git-checkout detection stands for both call sites (S-51 note, SA-2).** `S-23` and
  `O-10` explicitly preserved, untouched. **`14-forward-work-map.md`**
  gains FW-151…FW-156, one per piece of code this text implies and this
  sprint does not build (persisted placement facts, movable/retireable
  placements including auto-registration, compiled entry cues and the
  managed region, delivery instrumentation, review consuming the
  evidence, and Q6's replacement lifecycle) — each row names the spec
  sentence it implements. **Fences held:** no edit to routing-doctrine
  §5, the proposal output contract, or the decision trace; no new
  proposal or schema field; O-10 not re-asked. **Landing note:** the
  doctrine is loaded live by three consumers and an installed checkout's
  working tree is production (repo `CLAUDE.md`) — this merge changes
  what the nightly worker routes on its next run. **Fold r1** (blind
  gate round 1, `ae9eaac`) closed 1 BLOCKER (§4's managed-region sentence
  had escaped the forward-work discipline), 5 MAJOR (the Q1-HELD
  movement constraint added to doctrine §1; the Y-20 rewording corrected
  against shipped `U-cap`; the S-51 mode-detection argument withdrawn and
  the tension re-labelled an unresolved orchestrator default; H-3's own
  invariant text annotated; "authorized automated reviewer" tied to
  S-29) and 6 MINOR/1 NIT of cross-reference and wording fixes. **Fold
  r2** (blind gate round 2, current commit) scoped the doctrine's
  promotion sentence to mean moving an already-placed lesson — §2 still
  derives `ALWAYS`/`HOOK` for first placements — and fixed two stale
  cross-references in the reworded Y-20 passage. Full report:
  `misc/audit-2026-09-02/sprint-3/spec-A-placement-report.md`.
- **2026-09-11 — the intent transaction written into the corpus, the
  recover-or-refuse contract for every lock-holding ledger commit path,
  and the host-phase record design (Sprint 3 spec lane B; text only,
  no code).** Sprint 2's D7 transaction — the `<home>/.intents/<id>.json`
  file that brackets the four multi-file ledger writes so a crash rolls
  forward, restores, or stops — shipped 2026-09-05 with no spec sentence
  anywhere. `13-hosting-and-separation.md` gains **§7.2a** as the
  normative home: the file and schema (§7.2a.1, now with the `stopped`
  field recovery persists), the bracket (§7.2a.2), the three outcomes
  with M-W gate r1 MAJOR-2 quoted verbatim (§7.2a.3), clearing a STOP
  (§7.2a.4), the five answers of the user's 14:31 rulings stated once
  (§7.2a.5: the seam, the ordering, finish-and-tell, STOP scope option 1
  with its outage cost and its three-fact promise, the exit codes), the
  agent-callable recovery verb (§7.2a.6), visibility (§7.2a.7), the test
  plan (§7.2a.8) and the option-B host-phase record (§7.2a.9). **H-7**
  gains the intent bracket as a second clause scoped to the four D7
  operations, **H-8** the fail-closed lock census as a second check,
  **§5** the recovery-first / STOP-refuses-the-batch / batch-checks-once
  / 8-not-6 paragraph, **H-2** the option-B amendment (`recompile`
  remains the only repair; no caller applies a host step from an
  intent). `03-decisions.md` gains **`S-61`**, **`S-62`**, **`S-63`**
  (decision, rationale, links — the mechanisms live in 13 only);
  `14-forward-work-map.md` gains **`FW-157`** (host-phase BUILD, deferred
  behind M-I wave 3 and four pre-build decisions) and **`FW-158`** (the
  recovery verb, built with the live-intent guard lane); `u-verbs`
  §3.3a rule 3 carries a dated note (a mid-sheet 6 after a landed commit
  reports 8). Gate r1 (Opus + Codex Astra) folded 2026-09-11: STOP's
  promise split into the verb's own writes / completed recovery /
  partial recovery; the ledger rebase leg converts; recovery persists a
  STOP so a read-only classifier can see it; H-7 scoped to the four
  operations; the host-phase design restated as an observation set and
  two invariants with the lifetime a pre-build decision. Fences kept:
  13 §3–§4 and the routing doctrine untouched (spec lane A's), no code,
  no test edits, no new proposal field. `09-surface-spec.md` unchanged:
  it is the review-UI surface, and the adjudicator is a CLI caller.
