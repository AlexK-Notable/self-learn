# Durable pane / Iterate conversations with resume

**DRAFT · 2026-07-19 · spec-author task · owns register entry Y-28 only.**
Proposed final home: **09 §11 entry Y-28** (surface register) + one **10 §3
row U22** (surface build plan). UI-package-only: no 08 §1 CLI-substrate
line is owed — the pane lives entirely in `self_learn_ui`, and the store
this spec adds is a cache-local UI artifact keyed off the same
`self_learn.worker.cache_dir()` namespace the ui package already writes to
(`uilog`, `ui-token`). This draft is build-grade; it pins nothing
normative until folded.

**The ruling this specs** (user, 2026-07-19, binding): today the pane
session — record Iterate *and* bucket chat — is in-memory only. Persist
transcripts to disk and support resume across teardowns and restarts,
knowing it is medium-large and gate-first.

**Verification note — every code claim below re-checked against master
(post-`70e17ae`) and the resolved SDK on 2026-07-19:**

- `plugins/self-learn/ui/src/self_learn_ui/pane.py` — the ONE live session
  server-wide: `PaneManager._live` (`_Live` dataclass `:444-476`, transcript
  = `_Live.blocks: list[TranscriptBlock]` `:452`), `snapshot()` `:560-589`
  returns `_idle_snapshot` `:502-516` when `_live is None or
  _live.record_id != record_id`, `close()` (`q`) DISCARDS `:705-718`,
  `_teardown_live` `:765-777`, `teardown_parked` (idle) `:742-754`,
  `interrupt_active_session` (verb-dispatch teardown-before-`git mv`)
  `:720-733`, the one-session refusal (`return "armed"` at `pane.py:614`,
  guard block `:611-616`; the force-teardown `start(force=True)` leg at
  `:615`), `shutdown()` (app-lifespan) `:756-763`. `_validate_results` `:550`
  ALREADY outlives the session (survives `q` / a later reload) — the
  precedent for "some pane-adjacent state is not transcript state".
- `plugins/self-learn/ui/src/self_learn_ui/proposals.py` — `ProposalSlot`
  "ONE in-memory slot, never persisted (a server restart clears it by
  construction)" `:12-18`; clear-set `clear_for_session`/`clear_for_record`
  `:204-217`. **This spec PRESERVES that pin verbatim (§4a) — the slot is
  live consent state, not transcript content.**
- `plugins/self-learn/ui/src/self_learn_ui/engine/sdk.py` — module docstring
  `:19-25` and `_build_options` `:342-345` pass
  `extra_args={"no-session-persistence": None}` (the X-7 contingency), and
  the class docstring `:146-149` pins "fresh session per Iterate. No resume
  across Iterates." **Both re-examined empirically below — the docstring's
  "no field like session persistence" claim is now stale for the resolved
  SDK; §1 records the dated correction.** **Critically, that flag is
  incompatible with Tier 2**: `claude --help` verbatim — "Disable session
  persistence - sessions will not be saved to disk and **cannot be
  resumed** (only works with --print)"; §1's build-trial config therefore
  DROPS it as its primary configuration.
- `plugins/self-learn/ui/src/self_learn_ui/engine/base.py` — `PaneContext`
  `:98-125` (the seam the engine spends; `first_message` is the existing
  context-reinjection channel — §1 Tier-1.5 fallback rides it), `Result`
  `:76-90`, `PaneEngine` `:128-153`, `FakeEngine` `:156-200`.
- `plugins/self-learn/ui/src/self_learn_ui/routes.py` — pane split gate
  `pane_split = pane_snapshot.state != pane.STATE_IDLE` at Detail `:570-571`
  and Bucket `:457-458`; every pane route swaps the ONE `#pane-region-wrapper`
  id (`:618-622`), and the export-safe GET "excludes anything live/in-memory
  (pane snapshot, proposal slot)" `:236`.
- Templates `plugins/self-learn/ui/templates/partials/{pane,pane_idle,pane_armed}.html`;
  pane tests `plugins/self-learn/ui/tests/test_pane.py`.
- `self_learn.worker.cache_dir()` (`plugins/self-learn/cli/src/self_learn/worker.py:112-127`)
  = `${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(home)[:8]>/`,
  per-ledger-home, machine-local. Precedents that write here: miner run
  journal (`12` §8 A1 — "Lives in the miner's cache dir (machine-local);
  nightly journal-only repo commits would be noise") and the telemetry
  spool (`11` §4 — `~/.cache`, S-7's transient class, "sessions write
  `~/.cache` only; every tracked write remains human-triggered").

**SDK capability, verified empirically 2026-07-19** (dataclass
introspection + `claude --help`, `.venv` python on the resolved
`claude-agent-sdk==0.2.121`, pin `>=0.2.116,<0.3`; CLI 2.1.x):

- `ClaudeAgentOptions` exposes real fields `resume: str | None`
  ("Session ID to resume. Loads the conversation history…"),
  `continue_conversation: bool`, `fork_session: bool`, `session_id`,
  **`session_store: SessionStore | None`** and `session_store_flush`.
- `ResultMessage.session_id: str` is present on every turn — the id to
  capture for a later `resume`.
- `SessionStore` (`types.py:1426-1543`) is a **duck-typed Protocol**;
  only `append(key, entries)` and `load(key)` are required **for the
  write/resume-content path**. `append` mirrors the CLI's on-disk JSONL
  transcript entries (opaque pass-through blobs) **AFTER the
  subprocess's local write** (`types.py:1451` — "Called AFTER the
  subprocess's local write succeeds"); `load(key)` "materialized
  to a temporary JSONL file; the subprocess resumes from that file using
  its existing resume code" (`:1470-1484`). The docstring further documents
  (`types.py:1429`) "The subprocess still writes to local disk (set
  `CLAUDE_CONFIG_DIR=/tmp` for an ephemeral local copy)" — i.e. a caller
  that wants no durable CLI-side session can point `CLAUDE_CONFIG_DIR` at a
  swept temp dir rather than suppress persistence wholesale. The CLI also
  has `--resume`, `-c/--continue`, `--fork-session`.
  **Correction (U22-fix, 2026-07-19, live-DoD-caught BLOCKER — the
  "only required" claim needs a load-bearing caveat):** resume
  MATERIALIZATION (`claude_agent_sdk/_internal/session_resume.py::
  materialize_resume_session`, called by the SDK parent before every
  Tier-2 subprocess spawn) additionally probes the OPTIONAL method
  `list_subkeys` via `_store_implements()`
  (`session_store_validation.py:8-14`) and, if that probe reports the
  method "implemented," CALLS it (`session_resume.py:172-175`) to
  enumerate subagent transcripts — an unhandled `NotImplementedError`
  from that call is NOT treated as "optional, skip"; it propagates as a
  `RuntimeError` that aborts the whole resume. Critically,
  `_store_implements()` decides "implemented" by comparing
  `getattr(type(store), method)` against `SessionStore`'s own default
  **by object identity** — NOT by invoking the method and catching the
  raise. A concrete adapter that defines its own body for an "optional"
  method (even one that itself just `raise NotImplementedError`, written
  to satisfy a static type checker's structural-Protocol check) is a
  DIFFERENT function object from the Protocol's default, so it reads as
  "implemented" and gets called for real. **The only way an optional
  method genuinely reads as absent is to leave it completely undefined
  on the adapter class — inherited unchanged from `SessionStore`
  (subclassing it, never redefining the four optional methods with
  stub bodies).** Live-trial evidence: a real DoD walk (Resume click)
  hit exactly this — `CacheSdkSessionStore` initially DID define stub
  `list_subkeys`/`list_sessions`/`list_session_summaries`/`delete`
  bodies (added to satisfy pyright without subclassing the Protocol),
  which surfaced as "SessionStore.list_subkeys() for session `<id>`
  failed during resume materialization:" on every Tier-2 Resume,
  independent of turn count. Reproduced by importing and driving the
  SDK's REAL `materialize_resume_session()` in a unit test
  (`tests/test_store.py::test_real_sdk_materialize_resume_session_
  succeeds_multi_turn`), fixed by subclassing `SessionStore` and leaving
  the four optional methods undefined, and re-verified live end-to-end
  with a real multi-turn session + real resume (addendum entry,
  `docs/specs/self-learn/fixtures/ui-trials.md`).
- **The `sdk.py` U5-era docstring** ("no `ClaudeAgentOptions` field named
  anything like session persistence exists on the resolved SDK") **is now
  stale**: it was true of 0.2.116's *toggle*, but 0.2.121 ships a
  first-class caller-owned session mirror. Context-resume is therefore a
  real, in-tree capability — this spec designs against it, not around it.
  Folding Y-28 updates that docstring (§7).

---

## 0. What this is, and the one line it must not cross

Two things live in a pane session and they have opposite persistence
rules, so this spec keeps them in separate artifacts:

1. **The transcript** — the rendered conversation (the agent's prose, its
   tool lines, the human's follow-ups). Content. Safe to re-view forever.
   *Persist it.*
2. **The proposal slot** — an armed consent gate awaiting a keystroke.
   A restart that resurrected a waiting/armed bar would show the human a
   decision they never read this session, defeating the nonce guard
   (`proposals.py:143-181`) the whole refuse-not-replace design rests on.
   *Never persist it.*

Conflating the two is the one mistake this feature can make that matters.
Everything below keeps them apart: transcripts go to a cache-local store;
the slot's `:12-18` never-persisted pin is untouched (§4a).

**Non-negotiable inherited safety (unchanged by persistence):** a
resolution verb still tears the live session down BEFORE it `git mv`/`git
rm`s the files the session held write permission on
(`interrupt_active_session:720-733`, 09 §3 P3-7). Persistence removes no
teardown and relaxes no permission boundary (§4d).

**Durability model (MUST — pinned here so no section reads it as
buffered).** Tier-1 durability is **incremental append per finalized
block, each line `flush()`ed at write time** (§1) — the transcript on disk
is always current up to the last *finalized* block WITHOUT any teardown
running. A teardown-time flush exists only to capture a trailing
*in-flight* (not-yet-finalized) block; it is a nicety, **never the
mechanism durability depends on**. This matters because this service has a
documented `SIGTERM`-re-raise / exit-143 history (MEMORY: the uvicorn
SIGTERM blocker) and can also die by `SIGKILL` — no teardown, no flush
hook — and the last finalized block must still be on disk. Wherever a
later section says "flush before teardown", read it as "capture the
trailing in-flight block"; the finalized transcript is already durable.

---

## 1. What persists — two tiers (Q1)

**Tier 1 — render-resume (the floor, always on, MUST).** At the exact
points where a block becomes final — `_finalize_current`
(`pane.py:881-895`), the `ToolUse` block append (`_handle_event`
`:905-913`), and the `Result` footer (`:918-950`) — the manager appends
ONE **render event** line to the cache-local JSONL and `flush()`es it
(the durability model, §0). The events are exactly the already-computed
`TranscriptBlock`s (`pane.py:433-442`: `kind ∈ {"text","tool"}`, `html`,
`tool_name`, `tool_target`) plus the terminal `Result` footer fields
(`result_status`/`cost`/`turns`, `error_message`, `cap_hit`). This is a
faithful mirror of `_Live.blocks` — no new rendering, no model call, and
no dependence on any teardown running. On re-open the manager
reconstructs a **read-only** `PaneSnapshot` from the file and the split
re-renders the prior conversation. Tier 1 survives a server restart —
graceful OR `SIGKILL` — by construction, because every finalized block was
already on disk before the process died.

**Tier 2 — context-resume (the upper tier, gated, MUST-design /
MAY-ship-behind-a-build-trial).** Because the resolved SDK exposes
`resume`/`session_id`/`session_store`, a torn-down conversation's *model
context* can be restored so the human continues talking to an agent that
remembers. The mechanism:

- Wire `session_store=<cache-local adapter>` (§2) and capture
  `ResultMessage.session_id` on each `Result` (thread it through
  `engine.base.Result` — add `session_id: str | None = None`, mapped in
  `sdk._map_result:437-452`).
- On **Resume**, construct the engine with `resume=<captured session_id>`
  so the SDK `load()`s our mirror into a temp JSONL and the subprocess
  resumes from it.

**The Tier-2 configuration — the `no-session-persistence` flag MUST be
dropped (MAJOR-1 correction).** The engine today passes
`extra_args={"no-session-persistence": None}`. Its verbatim help is
"Disable session persistence - sessions will not be saved to disk and
**cannot be resumed** (only works with --print)", and `SessionStore.append`
fires only "AFTER the subprocess's local write succeeds"
(`types.py:1451`). Keeping the flag while wiring `session_store`/`resume`
therefore very likely **starves the mirror channel** and makes
`resume=<session_id>` a no-op — all the session-store/resume/session_id
wiring would ship as **dead code**. So the **primary build-trial
configuration is FLAG-DROPPED**: `session_store=<cache-local adapter>` +
`resume=<captured session_id>`, and — to keep the CLI's own on-disk
session ephemeral without the flag — **optionally** point
`CLAUDE_CONFIG_DIR` at a swept cache-local temp dir (the `types.py:1429`
recipe). The old X-7 privacy rationale for the flag is **retired on
0.2.121**: session materialization already lands in a temporary,
SDK-cleaned `CLAUDE_CONFIG_DIR` (`session_resume.py`; `types.py:1429`), so
the flag bought a privacy property the store mechanism now provides
natively. **The flag is kept ONLY if an independent build-trial proves it
does NOT suppress the mirror** — the burden is on evidence, not on
inertia.

**The build-trial gate (mirrors U5's verify-at-build).** Against the
subscription-auth streaming path (the path that already surprised us on
interrupts, T-E), two things MUST be live-trialed, not assumed:
  (i) with the flag dropped, `session_store.append` actually populates the
      cache-local mirror during a live streaming turn, and
  (ii) `resume=<session_id>` restores context on a fresh engine.
If **both** pass, Tier 2 ships as SDK-resume. If **either** fails, Tier 2
ships as **Tier 1.5 — fresh-session-with-context-reinjection**: a brand
new engine whose `first_message` is prefixed with the prior transcript
(the `PaneContext.first_message` channel `base.py:123` already carries
composed context; `compose_first_message`/`compose_bucket_message`
`pane.py:204-374` are the exact precedent). Reinjection restores *what was
said*, not the model's internal state — honest, and strictly better than
"start fresh". **Rejected: shipping Tier 2 unconditionally on unverified
SDK behavior** — fictional-API drift is the documented death of drafts
here; a field existing is not the path working. **Rejected: keeping the
flag "for privacy" while wiring resume** — it defeats the whole tier
(MAJOR-1). **Rejected: Tier 1 only** — it under-delivers on the ruling's
word "resume", which in a mid-conversation pane means "keep talking", not
only "re-read".

---

## 2. Where — plane, path, format, cap, multi-machine (Q2)

**Plane (the load-bearing argument).** 11's three-plane model forbids
per-session *tracked* writes: P6/E-8 (`11` §2 row) — "sessions write
`~/.cache` only; every tracked write remains human-triggered". A pane
transcript is the definitional per-session artifact. It therefore MUST be
**cache-local, machine-local, never tracked, never autosynced** — the
identical plane as the miner run journal (`12` §8 A1) and the telemetry
spool (`11` §4). It is NOT adjudication-plane (not a record) and NOT
observation-plane (not a flushed telemetry event); it is transient
session state in S-7's `~/.cache` class. **No `.gitignore` / autosync
exclusion edit is needed** because it lives under `cache_dir()`, already
outside every tracked root (verify at build with `git check-ignore` — the
cache dir is not in the repo tree at all).

**Path.** `cache_dir() / "panes" / "<session-key-slug>.jsonl"`, where the
slug is the URL-safe encoding of the PaneManager session key (a record id
`lrn-xxxxxxxx`, or the bucket key `bucket:<scope>/<name>` →
`bucket__<scope>__<name>`). One file per session key. Alongside it a
sidecar `<session-key-slug>.meta.json` holds `{schema, session_key,
record_id_or_bucket, bucket_dir, sdk_session_id, updated_at, block_count,
terminal_status}` for cheap listing without parsing the whole JSONL.
`bucket_dir` is the resolved bucket the session ran against — the §4e
resume-eligibility check compares it to the record's CURRENT
`locate_record(...).bucket_dir` to catch a rehome.

**Format.** JSONL, one render event per line, append-only during a live
session (mirrors journal A1's append-one-JSONL-per-run). Line schema:
`{"t": "block"|"result"|"turn-boundary", ...fields}`. A leading
`{"t":"header","schema":1,...}` line stamps the schema version so a future
shape change is detectable, not silently misparsed. Writes are `flock`ed
(the sentinel/telemetry precedent) — but there is only ever ONE live
session server-wide (`_live`), so contention is a restart-overlap edge,
not steady state.

**Size cap, refuse-not-corrupt.** Per-file soft cap **2 MiB** (a long
Iterate is tens of KiB of HTML; 2 MiB is ~100× headroom). On exceeding it
the writer stops appending render events and writes ONE
`{"t":"truncated","reason":"size-cap","at":<iso>}` marker; the live
in-memory transcript is unaffected (the cap bounds the *disk mirror*, not
the session). Re-render shows the persisted head plus an honest "(earlier
turns not persisted — size cap)" line, never a crash. **Rejected:
mid-file clipping** — it corrupts JSONL; a terminal marker keeps every
prior line valid.

**Multi-machine posture.** Cache-local ⇒ **per-machine history**, exactly
like the miner cursors/journal (`12` §A5: "Cursors and journals are
cache-local"). A transcript authored on machine A is not visible on
machine B, and that is correct: the SDK session it could resume lives only
in A's cache anyway, and the ledger (records, canon) — the thing that
*is* synced — carries the durable outcome. Stated as a non-goal (§9), not
a gap.

---

## 3. Scan posture (Q3)

**Decision: store-raw, cache-local, no write-time field scan.** The
secret-scan / validate checkpoints in this system guard *routed content*
— bytes about to become canon or a tracked file (02 §2 record-body scan;
`_post_session_validate` `pane.py:952-964` runs `proposal validate` when
canon may have changed). A pane transcript is **never routed**: it is not
compiled into any skill, never autosynced, never leaves the machine's
cache. It is in exactly the journal's position — 12 §8 A1 stores raw run
outcomes cache-local with no field scan; §10-2's field-length
refuse-not-clip and the `scan-refused` posture apply at *landing* (the
tracked write), which persistence does not perform.

The write-time protection is therefore the **size cap** (§2), not a
content scan. The existing scan boundary is untouched: the post-session
`proposal validate` still runs at its pin (`pane.py:873-878`), and a
proposal confirm still routes through the human's POST → the runner, where
the record-body scan already lives. **Rejected: field-scanning transcript
bytes at write** — it would scan the agent's own prose (which quotes
records and may echo the user) for secrets it can do nothing safe about
(no clip that preserves a conversation), buying nothing because the bytes
never land anywhere scanned content must be clean. The honest posture is:
cache-local transient state is trusted-local, like every other
`cache_dir()` writer.

---

## 4. Resume semantics per teardown cause (Q4)

**One live session server-wide STAYS** (`pane.py:611-613`). Persistence
adds history; it does not add a second concurrent engine. `start()` on a
record with a *persisted-but-not-live* transcript is a normal start whose
snapshot offers Resume vs. Start-fresh (§5); the one-live guard is
unchanged.

**(4a) Server restart.** `_live` is gone; the on-disk transcript remains
(durable per-block, §0 — a `SIGKILL`ed restart loses nothing finalized).
Tier 1: fully re-viewable. Tier 2: the SDK `session_id` is in the sidecar,
the mirror is in the cache — context-resume is OFFERED **iff the
`resumable` predicate holds** (§4e: status pending/deferred AND the
record's current `bucket_dir` equals the recorded one) AND the build-trial
gate (§1) enabled SDK-resume. The proposal slot is NOT resurrected
(§4a-slot below).

**(4b) Idle parked-teardown** (`teardown_parked:742-754`, Y-14).
Identical to restart from the transcript's view: finalized blocks are
already durable (§0), and teardown flushes only any trailing in-flight
block, so the next reload sees a complete transcript with
Resume/Start-fresh. The idle-exit
predicate (`has_interruptible_session:735-740`) is unchanged — a parked
session still does not block idle exit; it just leaves a resumable trail.

**(4c) `q` close** (`close:705-718`). Today `q` *discards*. The ruling
makes `q` a **park-to-disk**, not a hard delete: finalized blocks are
already on disk (§0); `close()` flushes any trailing in-flight block, then
does its existing live-teardown (dispose drain, close engine, clear slot). Afterward the split collapses to the idle region, now
showing the collapsed prior-conversation affordance (§5). Rationale: the
ruling says persist across teardowns, and `q` is a teardown; "history is
the point" (Q6). An explicit **discard-this-history** control is a
non-goal for v1 (§9) — retention prune (§6) is the only reaper. **Rejected:
`q` = hard delete** — it re-creates the exact volatility the ruling
removes, and leaves no way back from a fat-fingered `q`.

**(4d) Resolution verbs that resolve** (route / reject / graduate via
`interrupt_active_session:720-733`). The record leaves pending and its
files `git mv` to `resolved/` or `git rm`. Pin:
  - The teardown-before-`git-mv` safety is **unchanged** — the verb still
    tears the live session down first (P3-7). Persistence changes none of
    it.
  - The transcript persists **view-only**. It is history of how the
    now-resolved record was decided — valuable, kept.
  - **Context-resume (Tier 2) is NOT offered.** The record is no longer
    pending; the proposal and the on-disk files the session operated on
    have moved or gone, so a resumed agent would reason against a vanished
    world. Re-open shows the transcript read-only with an honest "(record
    resolved — view only)" line and **no Resume control**, only View.
  - `defer` is NOT a resolve: it keeps the record pending-in-place
    (`status="deferred"`, same bucket, same files). It stays Tier-2
    eligible exactly like a pending record (`validate_proposal` already
    treats `deferred` as adjudicable, `proposals.py:281`).

**(4e) Rehome — the bucket-move trap (MAJOR-2).** `rehome` is **NOT a
resolution**: `verbs.py` refuses unless `status ∈ {pending, deferred}` and
the record STAYS pending/deferred — it just `git mv`s the record and its
proposal siblings to a *different project bucket*
(`ledger_ops.rehome_record`). So a naive `status ∈ {pending, deferred}`
Tier-2 gate would **pass a rehomed record while its `bucket_root`/`cwd`
moved** — a resumed engine would be constructed against the OLD
`bucket_root` (`sdk.py:347` sets `cwd=str(ctx.bucket_root)`), reasoning
against files that are no longer there: exactly the vanished-world
resurrection §4d disallows. **Decision — option (a): any bucket move
invalidates Tier-2.** The meta sidecar (§2) records the transcript's
`bucket_dir`; **`resumable` requires ALL THREE (delta-2 residuals
folded): status pending/deferred, AND the record's CURRENT
`locate_record(...).bucket_dir` equal to the recorded one — compared
RESOLVED on both sides (`Path(...).resolve()`, the proposals.py:285
precedent; the recorded value is captured from the live session's own
`bucket_root`, already resolved per PaneContext — a non-canonical
string compare would silently downgrade every legitimate resume), AND
the sidecar's `terminal_status ∉ {error, cap-hit}`** — without this
last clause, §4f's "an errored session is Tier-2-ineligible" would be
enforced only by the live `send()` guard (pane.py:663-668), which
evaporates across a restart, and §5's card could read "hit an error"
while still offering Resume. A rehomed record therefore drops to
**View + Start-fresh only, no `resume=`** — the transcript is still
valuable history, but a live resume against a moved cwd is refused. **Rejected — option (b): rebuild
`PaneContext` from the record's current bucket and resume there** — it
would require recomputing the first-message context and silently accepting
that the SDK-restored *model context* (built in the old bucket, quoting
old paths) is stale relative to the new cwd; the mismatch is precisely the
confusion a resume is supposed to avoid, so (a)'s clean refusal wins.

**(4f) Non-teardown terminal states (acknowledged, MINOR).** Two ways a
session ends WITHOUT a teardown path running, both already durable because
Tier-1 appends per finalized block (§0), not at teardown:
  - **Engine death / error** — a `Result(error)` or an abnormal drain exit
    (`sdk._drain:372-375` yields `Result(status="error")`) parks the
    `_Live` at `STATE_ENDED` **without** `_teardown_live` running; `_live`
    stays set until the next start/close. The transcript's finalized
    blocks plus the error `Result` line are on disk already; re-open shows
    them view-only (an errored/cap-hit session is Tier-2-ineligible — it
    is `ENDED`, and `send()` refuses an ended session, `pane.py:663-668`;
    the "r starts a fresh session" path is Start-fresh, not Resume).
  - **Force-teardown on another record** — `start(record_B, force=True)`
    calls `_teardown_live()` on record A (`pane.py:615`). A's transcript
    was durable per-block; A's slot clears; A is later re-openable exactly
    like an idle-parked session (§4b). This IS a teardown, but it is
    driven by starting a DIFFERENT record, so it is named here to be
    explicit that A's history is not lost when B preempts it.

**(4a-slot) The proposal slot never resumes (Q from proposals.py:12-18,
PRESERVED).** Whatever the teardown cause, a waiting/armed proposal is
gone after teardown — the slot's clear-set already fires on session end
(`clear_for_session`), and nothing writes it to disk. On resume the bar is
empty; the human re-triggers a proposal if they still want one. This is
the §0 line held: content persists, consent does not.

---

## 5. UI surface (Q5) — zero new top-level regions (O-9)

Everything composes inside the existing `#pane-region-wrapper` that
`pane.html`/`pane_idle.html`/`pane_armed.html` already swap
(`routes.py:618-622`). **No new page region** (O-9; the four composition
principles govern). Concretely:

- **Snapshot gains one field.** Add `has_persisted_transcript: bool` and
  `resumable: bool` to `PaneSnapshot` (and to `_idle_snapshot`). The
  Detail/Bucket split gate stays `state != STATE_IDLE`, BUT `pane_idle.html`
  — the region rendered when idle — now branches: if
  `has_persisted_transcript`, it renders a **collapsed prior-conversation
  card** in place of the bare "press i" prompt.
- **The collapsed card** (within the idle region): a one-line summary in
  plain words (Y-9 — never engine vocabulary): the last human line / block
  count / relative time / a plain-words state (e.g. "12 blocks · 2h ago ·
  waiting for you", or "· finished", "· stopped early", "· hit an error" —
  never "awaiting-input"/"ended"/"streaming") — and controls:
  **[Resume]** (only when `resumable`, i.e. Tier 2 enabled AND the §4e
  resumable predicate holds), **[View]** (expand read-only, always),
  **[Start fresh]**
  (the existing `start` path, which now first archives-or-overwrites — §6).
  These are htmx swaps of the same one id; keymap follows the existing WASD
  discipline (a Resume key only lights when `resumable`, matching Y-19's
  "no signal keys are live" soft-dead-end posture).
- **Bucket chat** gets the identical treatment on its pane region
  (`routes.py:453-479`) — the bucket key is a first-class session key, so
  the store, the card, and the controls are the same code path.
- **The honest lifecycle line the pane displays.** Under a live session:
  unchanged. Under a *resumed* session: a small "(resumed — earlier turns
  restored)" note; under *reinjected* (Tier 1.5): "(continued — earlier
  turns re-read as context)"; under *view-only*: "(view only)". Never
  claim live-context restoration the build-trial did not grant — the line
  names which tier actually fired.

---

## 6. Retention (Q6)

- **Keep on record resolution** (Q6 default confirmed): history is the
  point; a resolved record's transcript is how it was decided. It is NOT
  deleted at resolution — only retention ages it out.
- **Prune policy — rolling, cache-local, two bounds** (mirrors the miner
  journal's rolling posture, `12` §A5/`:729`): a global **age** bound
  (default 30 days since `updated_at`) AND a global **byte** bound (default
  64 MiB across `panes/`, evicting oldest-`updated_at` first). Pruning runs
  opportunistically at manager construction and at each `close`/teardown
  flush — no timer, no new lifecycle (keeps this UI-package-only).
- **Start-fresh on a record with existing history**: the new session
  overwrites the same session-key file after copying the old one to
  `panes/archive/<slug>.<iso>.jsonl` (subject to the same byte bound), so
  "start fresh" never silently destroys the only copy of a conversation
  the human may have wanted. Bounded by retention like everything else.
- Both defaults are constants in the ui package, not env-configurable in
  v1 (settings surface is Y-26's, out of scope here); named here so the
  numbers are reviewable.

---

## 7. Register / plumbing (Q7)

- **09 §11 — new entry Y-28** (this doc's normative home): the two-tier
  persistence decision, the cache-local plane pin, the per-teardown
  matrix, the slot-never-persists carve-out, and the Tier-2 build-trial
  gate.
- **10 §3 — new row U22** (UI-package-only): `pane.py` store read/write +
  `PaneSnapshot`/`_idle_snapshot` fields + `session_id` threading through
  `engine/base.py::Result` and `engine/sdk.py::_map_result` + the
  `session_store` adapter and `resume` wiring in `_build_options` +
  `pane_idle.html` collapsed-card render + the three pane routes' resume /
  view / start-fresh legs. U22 depends on U6 (the pane itself) and is
  disjoint from the in-flight U19–U21 (f5-round) except `pane_idle.html`
  and `pane.py`, which U22 owns for this row — flag at orchestration if
  U19–U21 are concurrent.
- **08 §1 — no CLI-substrate line.** The pane and its store are entirely
  `self_learn_ui`; the CLI grows nothing. (Verify at build: the store
  imports only `self_learn.worker.cache_dir`, an existing public seam.)
- **`sdk.py` change + docstring correction** (folds with Y-28): when the
  build-trial enables SDK-resume, `_build_options:342-345` **drops
  `extra_args={"no-session-persistence": None}`** (MAJOR-1: the flag makes
  a session "cannot be resumed") and instead wires `session_store` +
  (on Resume) `resume=<session_id>`, optionally with an ephemeral
  `CLAUDE_CONFIG_DIR`. Replace the stale "no session-persistence field
  exists" docstring note with the verified 0.2.121 capability
  (`resume`/`session_id`/`session_store`), **retire the X-7 rationale**
  (its privacy property is now met by the temp-CLAUDE_CONFIG_DIR
  materialization), and pin that Tier-2 enablement is build-trial-gated on
  the subscription-auth path. The class docstring's "No resume across
  Iterates" `:149` becomes "no *implicit* resume; explicit Resume is Y-28,
  opt-in per session". If the trial fails, the flag MAY stay and Tier 2
  ships as Tier-1.5 reinjection (no `sdk.py` resume wiring at all).

### Test obligations

- **Unit (`tests/test_pane.py`, FakeEngine)**: a completed FakeEngine
  session writes a JSONL whose re-parse reconstructs a `PaneSnapshot`
  deep-equal (blocks + result footer) to the live one; `q` close leaves
  the file (park-to-disk, not delete); a resolve verb (route/reject/
  graduate) leaves the file but a re-opened snapshot has `resumable ==
  False`; **a rehome (record still pending, bucket_dir changed) also
  yields `resumable == False`** via the bucket-match clause (§4e); the
  proposal slot is empty after every resume (slot-never-persists); the
  size cap writes a `truncated` marker and never raises; a corrupt/
  truncated JSONL line yields a fresh-start idle snapshot, never a 500
  (§8).
- **Durability without teardown (MINOR — the `SIGKILL` leg, MUST)**: drive
  a FakeEngine to finalize ≥2 blocks, then **drop all manager references
  with NO `shutdown()`/`close()`/teardown call** (simulating exit-143 /
  `SIGKILL`); a fresh manager over the same `cache_dir()` reconstructs a
  snapshot containing every FINALIZED block. This is the test that would
  fail if durability were buffer-and-flush rather than per-block append.
- **`session_id` mapping**: `sdk._map_result` carries
  `ResultMessage.session_id` into `Result.session_id` (unit, against a
  stub message).
- **Restart-resume integration** (the ruling's headline, MUST): drive a
  FakeEngine session to `awaiting-input`, drop the `PaneManager` entirely
  (simulating restart), build a fresh manager over the same `cache_dir()`,
  assert the reconstructed snapshot re-renders the transcript and offers
  Resume; then Resume and assert the new engine was constructed with
  `resume=<session_id>` (Tier 2) OR the prior transcript in `first_message`
  (Tier 1.5), per the gate.
- **`js`-marked** (per 10's DOM-behavior convention): the collapsed
  prior-conversation card renders inside `#pane-region-wrapper` (no new
  region), Resume/View/Start-fresh swap the same id, and the Resume
  control is absent when `resumable == False`.
- **Build-trial record (live, not a unit test)**: a dated note capturing
  whether, **with the `no-session-persistence` flag DROPPED** (§1's
  primary config), `session_store.append` populated the cache-local mirror
  during a live streaming turn and `resume=<session_id>` restored context
  on the subscription-auth streaming path — the finding that decides Tier 2
  (SDK-resume) vs. Tier 1.5 (reinjection), recorded like U5's
  verify-at-build finding. If any independent trial is run to check
  whether the flag suppresses the mirror, its result is recorded here too.

### Degradation legs (all fail-open to a working pane, never a 500)

- Missing store file → fresh idle snapshot (identical to today).
- Corrupt/partial JSONL (bad line, missing header, wrong schema) → parse
  what is valid up to the first bad line, render that read-only with an
  honest "(earlier turns unreadable)" line; if nothing parses, treat as
  no history. Never raise into a route.
- `cache_dir()` unwritable → the pane runs exactly as today (in-memory
  only); a single `uilog` line notes persistence is disabled; no user-
  facing error.
- Tier-2 `resume` raises at engine construction (session bytes swept by
  the CLI's `cleanupPeriodDays`, or the gate mis-set) → fall through to
  Tier 1.5 reinjection for that Resume; the transcript view is unaffected.
- Size cap hit → `truncated` marker (§2), live session continues.

---

## 8. Cost accounting

**Zero new model calls introduced by persistence itself.** Tier 1 is pure
disk I/O of already-computed blocks. The size/retention bounds are local
file ops.

**Tier 2 resume re-sends the accumulated context** — the SDK replays the
prior transcript into the resumed turn, so a resumed turn's input tokens
include the whole history (the same tokens continuity always costs; not a
NEW turn, but real input tokens). The honest baseline is **not** "the
never-torn-down session" (that session no longer exists once the process
died) — after a teardown the two options actually on offer are **Resume**
(pay the history re-send for continuity) and **Start fresh** (send no
history, lose context). Start-fresh is strictly cheaper; Resume buys
continuity for the re-send. That trade is the human's, surfaced as two
distinct controls (§5), not hidden. Tier 1.5 reinjection sends the
transcript once as `first_message` context, bounded by the size cap (§2).
No budget/turn-cap pin (`pane.py:134-141`) changes.

---

## 9. Non-goals (v1)

- **No cross-machine sync** of transcripts or resumable sessions —
  cache-local, per-machine, by the plane argument (§2). The synced ledger
  already carries durable outcomes.
- **No search** across past transcripts, **no export** of a transcript as
  a shareable artifact (the export-safe GET explicitly excludes
  in-memory/pane state, `routes.py:236`; persisted transcripts inherit
  that exclusion).
- **No multi-session** concurrency — one live session server-wide stays
  (§4).
- **No explicit per-conversation discard control** — retention prune (§6)
  is the only reaper in v1; add a control only if a real need appears.
- **No settings surface** for the retention/cap constants — that is Y-26's
  page; the constants are named here, wired there if/when it lands.
- **No proposal-slot persistence** — the §0 line; the `:12-18` pin holds.
- **No new tracked files, no schema/frontmatter change, no autosync
  interaction** — the whole feature lives under `cache_dir()`.

---

## 10. Definition of Done

1. `pytest` green in `plugins/self-learn/ui` incl. the new unit +
   integration + `js`-marked cases (§7); no regression in existing
   `test_pane.py`.
2. `git check-ignore` (or a tree check) confirms `panes/` is outside every
   tracked root — persistence writes nothing autosync can see.
3. The Tier-2 build-trial is run and its finding recorded (dated review
   note); the shipped tier (SDK-resume vs. Tier 1.5) matches the finding,
   and the lifecycle line (§5) names it truthfully.
4. **Live restart-resume walk (the headline DoD):** with
   `self-learn-ui.service` running, open a record, `i` to Iterate, hold a
   real multi-turn conversation to `awaiting-input`; `systemctl --user
   restart self-learn-ui`; reload the Detail page and confirm the pane
   region shows the collapsed prior conversation with block count + time;
   **View** re-renders it read-only; **Resume** continues the
   conversation (agent shows continuity per the shipped tier); confirm the
   proposal bar is empty (slot did not resurrect). Repeat once for a
   **bucket** chat. Then resolve the record via a verb and confirm re-open
   shows view-only with **no Resume**; separately, **rehome** a
   still-pending record that has a transcript and confirm its re-open also
   shows **no Resume** (bucket-move invalidation, §4e). Walk with the user
   as the DoD sign-off (the drafts-house live-trial standard).
5. `sdk.py` docstring correction landed with the Y-28 fold (§7).
