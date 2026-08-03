# 16 — Worker-ecology channels & the portfolio auditor (FW-33 + FW-36)

**Status: DRAFT — build-grade; blind-gated NOT SOUND 2026-07-18 (foundation
intact — the timer-triggered-flush staleness claim passed on every leg),
all findings folded, delta re-check pending.** Fold record (this revision):
F3 MAJOR (doctrine consent path respec'd to a distinct `propose_doctrine`
tool + `doctrine draft`/`doctrine apply` CLI verbs — §3.3/§3.4, §10) · F5
MAJOR (reader-prompt `contradictions[]` schema + spool loop pinned — §2.1) ·
F2 (three-statement doc-sync list completed — §10) · F1 (falsifier recited
as `miner.py:1464`, MAJOR 3 demoted to corroborant — §2.4) · F4
(≥2-observations de-theatered to cardinality + ref-resolvability only —
§3.2, t-d) · F6 (`SCHEMA_VERSION` **incremented, not pinned to a
literal** — §10; corrected 2026-08-02 per FW-65 after `U-reach` took
`2`) · F7 (Y-22–26 held by
siblings, Y-27 reconfirmed — §0) · F8 (three-stage build plan — §8a) ·
reviewer note (`discover_buckets` excludes the siblings — §4.4).
**Delta re-gate 2026-07-18: NOT SOUND narrowly — Stages A/B judged SOUND
and build-ready, the residual contained to Stage C (doctrine drafts).**
This revision closes it: F-new-1 MAJOR (doctrine-file freshness leg —
`base_fingerprint` stamp + apply-time re-check + concurrent-apply clear
leg, the 09 §4.5 confirm-side check transposed to file-content identity —
§3.3/§3.4, t-j) · F-new-2 (orphaned committed drafts — `doctrine draft
--list` + pane re-surface + `doctrine dismiss` GC, no time-sweep —
§3.4, t-k) · F-new-3 (from-repo commit assumption stated + FW-10..15
pointer — §3.4) · reviewer nit ("surface" disambiguated to Front panels
vs the doctrine pane bar — t-b/d-a). The eight prior folds are untouched.
Authored 2026-07-18 by the spec author at the orchestrator's direction.
Proposed final home: **new numbered doc 16**
(`docs/specs/self-learn/16-ecology.md`) once gated; it lives in `drafts/`
until then. Charter: `forward/worker-
ecology.md` (Forward theme H) — §§2–6 binding design intent, §4's
four-rule constitution **non-negotiable**. Map row: `14-forward-work-map.md`
§2 FW-33 (portfolio auditor: receipts digest + worker briefs + one-time
why-audit) and FW-36 (ecology channels: miner field reports + pane
doctrine drafts). One spec because the auditor **consumes** what the
channels produce (the digest's fire-attribution closes exactly to the
extent field reports exist — charter §2).

**Register allocations this doc claims.** Proposed doc number **16**. One
surface-visible element: **Y-27 — the Front-page receipts-digest panel**
(§4.3). No other Y-numbers are claimed here; the auditor's CLI verbs,
event kinds, and brief files are substrate, not surface register entries.
**Register-allocation note (F7):** Y-22–Y-26 are held by the sibling
drafts in flight this round; **Y-27 was reconfirmed free** and is claimed
here. Whichever sibling graduates first re-verifies the 09 §11 high-water
mark before this doc's Y-27 lands, and this doc's graduation note in
14 §6a records the confirmed number — if Y-27 were taken by then, this
panel takes the next free number and every `Y-27` reference in this doc is
swept in one pass at graduation.
Two ratified-doc amendments are **required** and flagged in §10 (an 11
§4.2 prose doc-sync and an 11 §4.3 closed-set version bump); this draft
proposes them, it does not enact them — they graduate through the normal
gate with the build.

---

## 0. The load-bearing code facts (verified against master 2026-07-18)

Everything below is pinned to code, not to the charter's pointers (which
`worker-ecology.md` §6 itself says to re-verify — drift found and noted):

- **The miner already emits and flushes telemetry.** `mine run` spools
  `fire`, `recurrence-suspect`, and `capture` events
  (`miner.py:1008`/`:1099`/`:1125`, via `telemetry.spool_quiet`) and
  flushes them at run-end (`miner.py:1464–1468`, `telemetry.flush(home)`).
  `flush()` itself **commits and pushes** the tracked telemetry files with
  pinned subject `self-learn: telemetry flush <n> event(s)`
  (`telemetry.py:215`, docstring 231–247). Fire-attribution and
  recurrence-sighting field reports are therefore **already shipped** in
  substance; FW-36 is mostly a *contract, one new event kind, and a
  doc-sync*, not greenfield. Saying otherwise would be the failure mode.
- **The recurrence-suspect computation is already exposed.**
  `report.recurrence_suspects(home)` (`report.py:186`) reads the telemetry
  plane against currently-`routed` records, drops suspects already
  confirmed (`record.recurrences[].ref == nonce`), and returns rows
  `{id, nonce, seen_at}` — surfaced by `report --json .recurrence_suspects`
  and consumed by Front §Y-4. Every event carries a `nonce`
  (`telemetry.py:164`, `secrets.token_hex(4)`); `confirm-recurrence <id>
  --event <nonce>` matches on it (`verbs.py:2457`). **This is the single
  computation the charter's "EXPOSE, never a second one" rule protects.**
- **Non-textual anchors only.** A fire origin is `transcript:{session}#L{line}`
  (`miner.py:1121`); the (session, line) pair is regex-gated (`_valid_ref`,
  `miner.py:906`) before it touches any origin or telemetry line. No
  transcript text ever enters an event (11 §4.3/§4.4).
- **Prompt-assembly seams (brief load points).** The analyst prompt is
  built in `worker._compose_prompt` (`worker.py:615–645`) with named slots
  `{digest}`/`{doctrine}`/`{registry}`/`{records}`. The miner reader prompt
  is built in `miner._compose_prompt` (`miner.py:683`) with slots
  `{rubric}`/`{ledger}`/`{canon}`/`{digests}`. Worker briefs load **here**,
  as one new named slot each — nowhere else.
- **`_build_record` → `_scan_candidate` → `create_record` order holds**
  (`miner.py:1051`/`:1055`/`:1077`) — the compose-before-scan invariant
  12 §11 depends on. (Line numbers drifted from 12 §11's `812–862/1024/1046`;
  the *ordering* is intact.)
- **No `audit`/`brief`/`auditor` symbol exists yet** (grep clean). The
  systemd unit dir is `systemd/` (`self-learn-miner.{service,timer}` is the
  pattern to imitate).

---

## 1. The constitution (charter §4 — restated, binding on every clause below)

1. **Workers inform proposals; only the human amends canon.** Field
   reports, briefs, and doctrine drafts shape what is *proposed*, never
   what lands. **No clause in this doc grants any worker a write path into
   canon or a route/resolve verb** (P1/M-1 generalize, never relax).
2. **All channels are files in git.** Telemetry files, brief files, and
   doctrine-draft files are versioned and human-auditable. No hidden
   worker-to-worker state.
3. **Counts and examples, never scores.** Briefs and the digest carry
   counts, dates, and concrete examples; no modeled metric, no ranking
   number, ever (04 counted-not-modeled).
4. **Workers have attention budgets.** Every brief has a byte cap; the
   auditor's own job includes **pruning its stale advice** (§4.4).

**No fifth worker.** The auditor is the historian-synthesizer role, born
when this doc builds; the channels are expanded job descriptions of the
miner and pane. Out of scope by construction: any autonomy-ladder step
(12 A2 stays L0), any canon write, any team-scale mechanism.

---

## 2. Field reports (the miner's co-equal second product)

The miner is the **only actor that reads full sessions** (12 §11) — the
community's field reporter (charter §2). Its field reports are telemetry
events. They must be **self-contained after transcript pruning**: an event
read a month later, when `cleanupPeriodDays` has deleted the transcript,
must still be fully meaningful. That is achieved by carrying only stable
ids/enums + a non-textual anchor — never transcript prose.

### 2.1 The three event shapes

All three are telemetry events on the existing spool→flush plane (§2.4),
`kind`/`actor`/`ts`/`nonce` stamped by `telemetry.spool_event`
(`telemetry.py:135`). Payloads carry **ids, enums, and a non-textual
anchor only** (11 §4.4).

| Sighting | `kind` | Status | Payload (beyond kind/actor/ts/nonce) |
|---|---|---|---|
| **fire-sighting** | `fire` | **EXISTS** (`miner.py:1125`) | `record` (lrn-id, `RECORD_ID_RE`-gated), `origin` = `transcript:{session}#L{line}`, `outcome` ∈ `complied\|violated` |
| **recurrence-sighting** | `recurrence-suspect` | **EXISTS** (`miner.py:1008`) | `record`, `origin`, `basis` (label, e.g. `miner-match`) |
| **contradiction-sighting** | `contradiction-suspect` | **NEW** (§10 amendment) | `record`, `contradicts` (lrn-id or canon anchor), `origin`, `basis` |

- **fire-sighting** fires only against **live `routed`** rules
  (`miner.py:1119`) — a rule whose trigger-situation recurred in a later
  session, marked complied or violated. This is the digest's
  fire-attribution source (§4.3): a routed lesson can claim a fire iff a
  field report attributes one, or it activated in skill scope (an
  observable load), and **nothing else** — silence is silence.
- **recurrence-sighting** is the existing suspect: a new mined candidate
  that Phase-3-matches an already-routed record (the rule is absent, weak,
  or partial). It feeds the existing "not holding" card via
  `report.recurrence_suspects` (§2.2) — **no second detector.**
- **contradiction-sighting** is the genuinely new leg. The reader, given
  the compiled-canon index already in its prompt (`miner._canon_index`),
  may report that a session's decision **contradicted** a routed rule
  (did the opposite, and it worked / the human endorsed the opposite).
  It is a *suspect*, never a confirmed contradiction edge: it feeds a
  human `link contradicts <id> <target>` (11 §2.4/§2.5), the machine
  never writes `links.contradicts`. **Boundary (pin):** the miner emits
  the *suspect telemetry event only*; it does not touch the proposal
  schema's `contradicts:` field (that stays the analyst's, 11 §2.4) and
  never writes the record's `links` block (human verb only).

**Reader-prompt schema extension (pin — F5, this spec owns it).** The new
kind requires an explicit extension of the miner reader's JSON output
schema and a parse/validate/spool loop; test t-a presumes it. Two changes:

1. **`miner._PROMPT_TEMPLATE` (`miner.py:622–656`) gains a
   `contradictions[]` array** beside the existing `candidates[]` and
   `fires[]`, each element:
   ```json
   {"record": "lrn-…", "contradicts": "lrn-… | <canon anchor>",
    "session": "<id>", "line": <n>, "basis": "<short label>"}
   ```
   with one prompt line instructing: *given the ROUTED RULES index, report
   a span where a session's decision did the opposite of a routed rule and
   it held — `record` is the rule contradicted, `contradicts` the id or
   canon anchor of the conflicting authority; emit nothing when unsure.*
2. **A parse/validate/spool loop mirroring the fires loop
   (`miner.py:1104–1129`)** runs after it: iterate `parsed.get(
   "contradictions")`; skip non-dict elements; require `RECORD_ID_RE.match(
   record)`, a `_valid_ref` (session, line) pair, and a non-empty
   `contradicts`; require `_find_record(record).status == "routed"`
   (contradictions only against live rules, like fires); build
   `origin = f"transcript:{ref[0]}#L{ref[1]}"`; dedupe on the
   `(kind, record, origin)` key against the `seen_events` set (the new kind
   is added to the `kind in (...)` tuple at `miner.py:929`); then
   `telemetry.spool_quiet("contradiction-suspect", record=…, contradicts=…,
   origin=…, basis=…)`. The run-end flush already carries it (§2.4). The
   `basis` value is a short controlled label (`canon-index-match`), never
   model prose.

### 2.2 The nonce/ref linkage — expose, never re-derive

- The **only** promotion path from a sighting to a record mutation is the
  human confirm verb keyed on the event `nonce`: recurrence →
  `confirm-recurrence <id> --event <nonce>` (`verbs.py:2457`);
  contradiction → a human `link contradicts` after the analyst surfaces
  the suspect.
- Surfacing MUST reuse `report.recurrence_suspects(home)` and its
  contradiction analogue — **one CLI computation** that filters telemetry
  against routed records and drops already-confirmed nonces. The
  contradiction analogue is `report.contradiction_suspects(home)`, built
  in the same file, same shape (`{id, contradicts, nonce, seen_at}`),
  exposed via `report --json .contradiction_suspects`. **No surface or
  auditor may recompute suspects by walking telemetry itself** (the
  `canon_read_roots()` no-reimplementation posture, 10 U0).
- `_event_seen`/`read_events` dedupe on `(kind, record, origin)`
  (`miner.py:923`) — crash-replay and `--since` replay must not double a
  sighting; the new kind joins that dedupe set (a one-line change to the
  `kind in (...)` tuple at `miner.py:929`, tested).

### 2.3 Evidence that rides along

- The **only** evidence a field report carries is the non-textual anchor
  `transcript:{session}#L{line}` plus the record id(s) and the outcome
  enum. **No span, no quote, no phrase** (11 §4.3 pins `fire` to
  "non-textual anchor only… never a phrase or span"; the charter's word
  "span ref" MUST be read as this anchor, not a text span — pinned here to
  forestall the misread). The anchor is a *courtesy pointer*: by the time
  the auditor reads it the transcript is usually pruned, so the auditor
  treats the anchor as non-load-bearing and never dereferences it
  (mirroring 11 §2.2's "ref is a courtesy pointer" rule).
- Because the field report is anchor+ids+enum only, it is **self-contained
  after pruning by construction** — the charter's requirement is met not
  by copying transcript text (forbidden) but by carrying none.

### 2.4 Write path — spool→flush, actor-scoped (and the one hard question)

**The path is the one the miner already runs, unchanged:** the reader
(`claude -p`, no filesystem write beyond its spool) emits structured
candidates+fires+contradictions; **CLI harness code** validates them and
calls `telemetry.spool_quiet(...)` (S-5/E-18 preserved — the model pass
writes proposals/spool only, never telemetry directly); `mine run`
flushes at run-end (`miner.py:1464`), `flush()` scans every line
(scan-at-flush, refuse-whole-flush on a hit), moves to
`.self-learn/telemetry/<month>.<actor>.jsonl`, commits, and pushes.
Contradiction-sighting emission is one new `spool_quiet` call beside the
fire loop (`miner.py:1104–1129`); flush already carries it.

> **⚠ THE ONE KNOWN HARD QUESTION — and its resolution.** The task asks:
> 11 §4.2 says "**Only human-triggered CLI verbs flush**," and its
> enumerated flushing set is *teach, import, resolution verbs, report,
> worker run-end, `telemetry flush`* — it **omits `mine run`**, and the
> miner is timer-triggered, not human-triggered. Does a non-human-triggered
> miner writing telemetry violate 11 §4?
>
> **It does not — and the code already resolved this, ahead of the prose.**
> The **primary falsifier is `miner.py:1464` itself**: the miner —
> timer-triggered `mine run` — unconditionally calls `telemetry.flush(home)`
> at run-end, and the colocated comment (`miner.py:1461–1463`) names it
> exactly for what it is — *"an empty nightly flush would put a
> **machine-triggered commit on the tracked telemetry plane**"* — i.e. the
> code author already understood and sanctioned a machine-triggered flush,
> gating it only on whether the run produced events. Shipped behavior, not
> a loophole. **Corroborant:** `telemetry.flush`'s docstring
> (`telemetry.py:239–247`) records that an **audit 2026-07-16 (MAJOR 3)**
> resolved *commit-responsibility* — the old "human-triggered flush +
> autosync commits them later" model was broken because doc 13 **H-5**
> removed the ledger watcher, so nothing committed the tracked plane
> (invisible on machine B, destroyed by re-clone); H-5's rule is
> **"producers commit their own writes; telemetry is a producer,"** and
> `flush()` now commits+pushes its own telemetry with a pinned subject.
> That audit fixes *who commits*; the *who-may-flush* falsifier is
> `miner.py:1464` standing on its own. The invariant 11 §4.2 *actually*
> protects — **no unscanned publication, single-writer actor-scoped files,
> no per-session autosync storm** — is fully satisfied by the miner: the
> scan runs at flush; the actor filename is single-writer; the miner runs
> nightly, not per-session.
>
> **Resolution:** field reports need **no new plane and no new write
> mechanism** — they ride the exact spool→flush→commit→push path the miner
> already runs. What is stale is the **prose of 11 §4.2**, which still
> reads "human-triggered only" and omits `mine run`. **This spec requires
> an 11 §4.2 doc-sync amendment** (§10): restate the flushing rule as *"a
> flush is legitimate iff it (a) scans every line before moving any and
> (b) commits+pushes its own writes as a producer (H-5); the flushing
> agent may be timer-triggered so long as it is a CLI producer that does
> both"* — and add `mine run` to the enumerated set. This is a **prose
> correction to match shipped, audited code**, not a design change; no
> reopen of P6/E-8 (their letter is preserved by scan-at-flush).

### 2.5 Caps and secret-scan posture

- **Secret scan:** every flushed line passes `secret_scan` at flush;
  a hit refuses the **whole** flush and leaves the spool intact
  (`telemetry.py:270–278`). Payloads are ids/enums/anchors by schema, so a
  hit is near-impossible — belt-and-suspenders, unchanged.
- **Volume cap:** field reports are naturally bounded by the miner's
  per-run digest budget (`MAX_PROMPT_DIGESTS_CHARS`) and its scan of only
  new-since-cursor spans. No separate per-run field-report cap is added
  (the events are cheap ids); if a pathological run emits thousands, the
  journal (`mine status`) makes it visible and the fix is a cap then, not
  speculatively now.
- **No free text anywhere** — the `basis` label is a short controlled
  string (`miner-match`, `canon-index-match`), never model prose; enforced
  the same way the decline-reason enum is (`telemetry.py:147`).

---

## 3. Doctrine drafts (the pane's field notes)

The pane agent is the ethnographer — it hears **why the human decides**
routing, live (charter §2). Today that judgment survives only as a
resolution note. FW-36 lets the pane draft a **doctrine-amendment
proposal** that codifies an *observed, repeated* routing judgment, for the
human to approve.

### 3.1 What a doctrine amendment amends

`plugins/self-learn/skills/self-learn/references/routing-doctrine.md` —
the single source of routing judgment loaded by all three analyst
consumers (its own §preamble). A draft proposes prose to add/change in it
(e.g. a new §3-style tiebreak, a new destination heuristic). It is
**always a proposal beside the file, never an edit to it** (the same
proposer≠approver geometry as every channel).

### 3.2 Trigger discipline (pinned — the anti-one-off rule)

- The pane MAY offer a doctrine draft **only when it has observed the same
  routing judgment articulated at least twice** across distinct
  adjudications (charter §2's "articulated twice"). A single articulation
  is a resolution note, not a doctrine; one-off judgments never trigger a
  draft.
- **What intake actually enforces (honest — F4):** the `doctrine draft`
  verb / `propose_doctrine` handler enforces **two mechanical facts only**
  — (a) **cardinality**: `observations` has ≥2 entries with **distinct**
  `ref`s; (b) **ref-resolvability**: each `ref` resolves to a real record
  id (or a real prior draft id). **It does NOT and CANNOT verify that the
  notes faithfully describe what the human actually said** — that the two
  cited episodes really articulated *this* judgment is a semantic claim no
  validator can check. **Faithfulness is the human confirm's job:** the
  waiting bar renders the `observations` refs (and their titles) so the
  human can check each before arming — the two-gate consent is exactly
  where a fabricated or misremembered observation is caught. Intake
  guarantees "two resolvable, distinct refs are cited," nothing more; the
  human guarantees the rest.
- Observation evidence is drawn from **the pane's own visible history**
  (resolution notes, prior doctrine drafts) — the pane has no telemetry
  read and invents no cross-session store. Where the "twice" cannot be
  evidenced from durable files, the pane does not offer.

### 3.3 The artifact

- A **proposal-sibling file**, not a canon edit:
  `plugins/self-learn/skills/self-learn/references/doctrine-drafts/
  draft-<8hex>.yaml` (a new `doctrine-drafts/` dir beside the doctrine
  file, so drafts are versioned and swept as a set). **The pane never
  writes this file** — it is created **server-side** by a new CLI verb
  `self-learn doctrine draft` (§3.4), invoked by the server from the
  `propose_doctrine` call. The pane's zero-write allowance (09 §4.3:
  the agent has no filesystem write beyond nothing) is preserved
  verbatim: the agent supplies the draft fields as tool arguments; the
  **server-owned handler** validates them and shells the CLI verb that
  writes the file. Shape:

  ```yaml
  id: draft-3f9a2c10
  amends: routing-doctrine.md          # the only legal target in M1
  section: "§3 narrowest-surface bias" # human-readable anchor, not machine-eval
  proposed_text: |                     # the prose to add/change — bounded, §3.5
    When a lesson's trigger spans two sibling repos under one umbrella…
  observations:                        # ≥2 required (§3.2), each self-contained
    - {ref: lrn-4c1e9a2f, note: "user re-homed to the umbrella here"}
    - {ref: lrn-77ab01cd, note: "same call, keyboards→hyprland"}
  rationale: "codifies a judgment the human made twice; narrows nothing new"
  base_fingerprint: sha256:9c1f…    # F-new-1: hash of the target's CURRENT
                                    #   text at draft time — the freshness
                                    #   anchor (§3.4); stamped by the CLI,
                                    #   never model-emitted (record_sha
                                    #   precedent)
  model: <the pane engine's model>
  drafted_at: <ISO-8601 UTC>
  ```

- **Byte cap:** `proposed_text` ≤ **1500 chars**, refuse-not-clip
  (doctrine prose is small; a large diff is a rewrite, which is the
  human's job not the pane's). Whole-file secret scan on write, same as
  every proposal sibling.
- **Base fingerprint (F-new-1 — the freshness anchor).** `doctrine draft`
  stamps `base_fingerprint` = `sha256` of the **current text of the target
  `section`** as located in `routing-doctrine.md` at draft time (a section
  is located by its `## …`/`### …` heading anchor); **falling back to a
  whole-file hash** when the `section` cannot be isolated (a free-form or
  new-section amendment). Stamped by the CLI at draft write, never
  model-emitted (the `record_sha` no-trust precedent, 02 §1). This is what
  `doctrine apply` re-checks (§3.4).

### 3.4 The consent path (who finally writes the doctrine)

**The Y-13 `propose_verb` tool CANNOT carry this — a distinct tool is
required (F3, builder-blocking).** Verified against code: `propose_verb`'s
verb set is **closed** — `PROPOSABLE_VERBS = frozenset({"route", "reject",
"defer", "graduate", "rehome"})` (`proposals.py:67`); its handler
**validates a pending `record_id` in the session's scope**
(`SessionScope`, `proposals.py:104`); its single `ProposalSlot` is
**record/bucket-keyed** and cleared on bucket refresh; and the pane has
**zero write allowance**. A doctrine draft is not record-scoped, has no
bucket, and needs a file created — nothing `propose_verb` does fits.
Respec:

- **A distinct server-owned tool `propose_doctrine`** (SDK MCP tool,
  qualified `mcp__self-learn-surface__propose_doctrine`, charter-allowed
  exactly like `propose_verb`), exposed **only in pane sessions where the
  ≥2-observation trigger (§3.2) is satisfiable**. Arguments: `section`,
  `proposed_text`, `observations` (list of `{ref, note}`), `rationale`.
- **Its own single slot + clear-set — no bucket-staleness leg, but a
  file-staleness leg.** A second server-held `DoctrineProposalSlot`,
  independent of the record/bucket `ProposalSlot`, refuse-not-replace,
  nonce-echoed on arm/confirm/disarm/dismiss (the `propose_verb` slot's F5
  nonce discipline, reused). Its clear-set is {dismiss, confirm, disarm,
  session-end, **`a concurrent doctrine apply landed`**} — it is **not**
  keyed to a record or bucket, so **none of `propose_verb`'s
  bucket-refresh/record-resolution clear legs apply** (a doctrine draft
  cannot go stale against a bucket refresh — it references no bucket). The
  one axis it CAN go stale against is **its own target file** (§3.4,
  F-new-1): a `doctrine apply` (or FW-30 edit, or pull) that lands between
  this draft's authoring and the human's Enter changes `routing-doctrine.md`
  under the draft, so a **concurrent-apply clear leg** on any WAITING/ARMED
  doctrine bar is required — this is the confirm-side load-bearing check of
  09 §4.5 transposed **from bucket-identity to file-content-identity**.
- **The `propose_doctrine` handler creates the file, the pane does not.**
  On a valid call the server-owned handler (a) validates cardinality +
  ref-resolvability (§3.2), (b) shells `self-learn doctrine draft
  --section … --text … --observations …`, the **new CLI verb** that writes
  `doctrine-drafts/draft-<8hex>.yaml`, secret-scans it, and commits it
  with pinned subject `self-learn: doctrine draft (<draft-id>)`, then (c)
  renders the WAITING doctrine bar. Pane zero-write is intact — every byte
  is written by CLI code off a server call, never by the agent.
- **Human arm+Enter → `self-learn doctrine apply <draft-id>` (unchanged
  in shape; gains the freshness check).** The human's own keystroke arms
  the waiting bar and Enter confirms; the executing POST originates from
  the human's window (proposer ≠ approver verbatim). `doctrine apply`
  applies `proposed_text` into `routing-doctrine.md`, secret-scans the
  result, commits with pinned subject `self-learn: doctrine amend
  (<draft-id>)`, and `git rm`s the draft sibling. **The doctrine file
  ships with the package** (`worker.package_skill_refs()`), so the same
  commit updates the canon all three analysts load — the point of the
  channel.
- **Freshness check at apply (F-new-1 — load-bearing, confirm-side).**
  **Before** applying, `doctrine apply` recomputes the live fingerprint of
  the target `section` (same anchor + whole-file fallback as `doctrine
  draft`) and compares to the draft's `base_fingerprint`. On **mismatch**
  — or when the `section` is **no longer locatable** — it **refuses with
  the resolved-elsewhere shape**: clear the slot and render plain words —
  *"The routing notes changed since this draft was written — please
  re-review."* — never a silent overwrite of the doctrine the draft was
  not written against. This is the 09 §4.5 confirm-side re-validation
  precedent (the bucket-identity re-check) applied to file-content
  identity: a draft authored against base X must not land onto base Y. The
  human re-opens the pane and the analyst re-proposes against the current
  text — the honest cost of a concurrent change. **The whole-file
  fallback is deliberately over-conservative (F-new-4, final-delta
  fold): a section-less draft goes stale on ANY concurrent doctrine
  edit, related or not — a spurious re-review is the accepted cost of
  never silently applying against a changed base. The fallback must not
  be "optimized" into a narrower diff-check; that reintroduces the
  silent-stale hazard.**
- **Orphaned committed drafts — enumeration + GC (F-new-2).** The draft
  FILE is committed at `doctrine draft` time, but the WAITING slot is
  in-memory (`DoctrineProposalSlot`); a **server restart between the draft
  commit and the human's confirm loses the slot while `draft-<8hex>.yaml`
  persists** — an un-applied draft with no path back to a bar. Two pins:
  (a) **Enumeration** — `self-learn doctrine draft --list` renders every
  un-applied draft in `doctrine-drafts/` (id, section, drafted_at,
  observation count); and the pane **re-surfaces un-applied drafts at
  session start** (reads the dir, re-offers each as a fresh WAITING bar —
  the freshness check at §3.4 apply still guards a stale re-offer, so a
  draft written against changed doctrine refuses cleanly rather than
  landing wrong). (b) **GC posture** — a draft leaves `doctrine-drafts/`
  by exactly two doors: `doctrine apply` `git rm`s it (applied), and a new
  `self-learn doctrine dismiss <draft-id>` `git rm`s it (the human
  declined) with pinned subject `self-learn: doctrine draft dismissed
  (<draft-id>)`. **Wiring pin (F-new-5, final-delta fold): the human
  dismissing the WAITING doctrine bar SHELLS `doctrine dismiss` — a bar
  decline IS the file remover, durable and committed — so the
  re-surface-at-session-start leg never re-offers a declined draft.
  Unlike the record slot (where the propose tool wrote no file and
  dismiss is a pure in-memory clear), this slot's dismiss has a file
  consequence; a builder must not copy the record-slot's dismiss shape.
  Accepted asymmetry: disarm and session-end leave the file (they are
  not declines) and the draft re-surfaces next session.** **No time-based auto-sweep** — a lingering draft is
  visible (via `--list`) and harmless (never load-bearing, never
  auto-applied); silent deletion of a human-reviewable proposal is the
  wrong default. A draft whose `base_fingerprint` has gone stale is not
  GC'd either — it is refused at apply with the re-review message and the
  human dismisses it explicitly.
- **From-repo assumption (F-new-3 — honest limitation).** Both `doctrine
  draft` and `doctrine apply` **commit into the product repo's package
  tree** (`worker.package_skill_refs()` resolves to the in-repo skill dir);
  they therefore require a **writable git checkout of the product repo** —
  a packaged or read-only install (a `uv tool install` binary, a
  system-copied skill) would fail the draft/apply commit. That is
  accepted for M1 (the only live host is the from-repo dev checkout);
  making doctrine amendment work from a packaged install is a **packaging-
  phase question (FW-10..15)** — where the writable-canon-location problem
  is faced for every compile target, not just this one — and is out of
  scope here. **Rider (F-new-6, final-delta fold): a commit failure on a
  doctrine verb leaves an uncommitted partial in the PACKAGE tree that no
  backstop sweeps — `reconcile` is ledger-home-scoped and never touches
  it. The verbs assume the commit succeeds; commit-failure handling rides
  the same packaging-phase question, deferred deliberately, not silently.**
- **No standalone web-surface verb in M1.** Doctrine editing is FW-30
  territory (settings surface); until then the pane-request → human-confirm
  → `doctrine apply` path is the only consent route, and the bare CLI verbs
  (`doctrine draft`, `doctrine apply`) are the fallback. (This mirrors
  07 §Y-11's "the decision is the human's, the hand may be the surface" —
  but doctrine is higher-stakes than `host add`, so M1 keeps the hand at
  the pane-confirm/CLI, not a standalone web button.)

### 3.5 What a doctrine draft may NEVER do

- **Never edit `routing-doctrine.md` directly** — it is a proposal
  beside it; only `doctrine apply` (off a human confirm) writes the file.
- **Never fabricate quotes.** Every `observations[].note` describes a
  *real* prior articulation and cites its `ref`; the draft carries no
  invented user quotes and no transcript spans (the pane's evidence is its
  own visible resolution-note history, not reconstructed dialogue).
- **Never propose an amendment that grants any worker autonomy or a canon
  write** (constitution rule 1 — a doctrine draft that tried to relax P1
  is refused at validate).
- **Never target anything but `routing-doctrine.md`** in M1 (`amends`
  is validated against that one path; card-sections.yaml, mining-rubric.md,
  and any hook are out of scope — future drafts, own consent stories).

---

## 4. The portfolio auditor

The slowest worker (~monthly), which reads the whole ledger + telemetry +
journals at once and is best positioned *because* it is slow (charter §3:
low frequency → stable, cheap outputs). It has **two renderings of one
read** (charter §3, the (c)-ish economy): a human **receipts digest** and
machine **worker briefs**.

### 4.1 Cadence + trigger mechanism

- **A monthly systemd user timer**, imitating the miner
  (`systemd/self-learn-auditor.{service,timer}`, `Persistent=true` so a
  machine-off month fires at next boot). The entrypoint is a **new CLI
  verb `self-learn audit run`**; the timer calls it. Killable via
  `SELF_LEARN_AUDITOR=0` (entrypoint-honored) or disabling the timer.
- **Not** riding the nightly miner cycle: the auditor's value is *low
  frequency* (a nightly portfolio synthesis would be churn, the opposite
  of the charter's stability argument), and a monthly job must never block
  or be blocked by nightly mining. Its own `audit.lock` flock; never
  shares `miner.lock`/`worker.lock`.
- **Watchdog + force**, mirroring the miner's R1/R2: any self-learn verb
  opportunistically kicks a detached `audit run` when the last run is
  >35 days old and none is live (`SELF_LEARN_AUDITOR_AUTOKICK=0` disables
  in tests); `self-learn audit run` forces an immediate run; `--since
  <date>` scopes the window (used by the one-time why-audit, §5).
- **Never load-bearing (E-11/M-3 spirit):** teach, import, review, the
  miner, and the analyst are all complete without the auditor. It is
  additive synthesis, killable with zero data loss (its outputs are
  regenerable from the ledger+telemetry it reads).

### 4.2 Inputs (enumerated — exactly these, all already-shipped reads)

1. **The ledger facts map** — `report.gather(home)` (`report.py:225`),
   which already walks every pending/resolved record + the tracked
   telemetry plane into one map (`ledger_metrics`, `supply_mix`,
   `recurrence_suspects`, open follow-ups). The auditor consumes this;
   it does not re-walk records itself.
2. **The telemetry plane** — `telemetry.read_events(home)`: `fire`,
   `recurrence-suspect`, `contradiction-suspect`, `capture`, `card-*`,
   `surface-budget`, `staleness-flag` events (ids/enums/anchors only).
3. **The miner run journals** — `miner.read_journal()` (`miner.py:1142`):
   per-run landed/folded/recurrence/dropped/scan-refused outcomes +
   missed-window honesty.
4. **Skill-scope activation observations** — the only *fire*-class signal
   available without a field report (a skill loading is observable; a
   CLAUDE.md line firing is not). Sourced from telemetry `card-*`/`fire`
   events; **no new collector** — if a signal isn't already in the plane,
   the auditor reports its absence, it does not invent a probe.
5. **The prior audit's own briefs** (§4.4) — read to prune its own stale
   advice (constitution rule 4).

**Nothing else.** The auditor reads no transcripts (they are pruned; the
miner is the only transcript reader) and issues no `claude -p` that widens
its tool surface beyond Read over the ledger home — synthesis is
deterministic assembly + one bounded model pass for prose, contained like
the miner reader (`Read,Grep,Glob`, spool-scoped write only).

### 4.3 Output (a): the receipts digest — Y-27

A human-rendered monthly synthesis. **Delivery surface: a Front-page
panel (Y-27)** rendering a committed digest file
(`.self-learn/audits/<month>.md`, versioned) — read-only, reached from
Front like the `/report` screen (Y-12), never a popup (charter §3:
human-rendered, ambient, not demanding). The panel shows the latest
digest with a link to prior months.

**Sections (exact set):**

1. **Routed this period** — counts per bucket/destination (from
   `ledger_metrics`). Counts, not scores.
2. **Fires observed** — routed rules that a field report or a skill-scope
   activation attributed a fire to this period, with the count and one or
   two concrete examples (record title + complied/violated).
3. **Not holding** — routed rules with unconfirmed recurrence suspects
   (from `report.recurrence_suspects`); the human's `confirm-recurrence`
   queue, framed as a question.
4. **Contradictions surfaced** — contradiction-suspects awaiting a human
   `link contradicts`.
5. **Quiet canon (unobserved, NOT dead weight)** — routed rules with no
   observed fire this period. Framed exactly as 11 §5's `no-observed-fires`
   list: *"observation is lossy; a silently-working rule fires without a
   trace — these are candidates for your `confirm-held`/demote judgment,
   never auto-retirement."*
6. **Supply health** — supply mix (teach/import/mined), queue age,
   mined-card accept rate (12 §4) — all counted facts with their honesty
   labels.
7. **Staleness & follow-ups** — user-pinned env moved; open follow-ups.

**Honesty rules (each a testable "must"):**

- **Fires are claimed only where attributable** — a rule appears in
  §2 (Fires observed) **iff** a field report attributes a fire to it OR it
  is a skill-scope rule whose skill activation is observable in telemetry.
  A CLAUDE.md-scope rule with no field report gets **no fire claim** — it
  lands in §5 (Quiet canon), framed as *unobserved*, never *worthless*.
- **Absence is framed as unobserved, not dead** — the words "dead weight"
  never appear; §5's framing is 11 §5 verbatim in spirit.
- **Counts and examples, never scores** (constitution rule 3) — no ROI
  number, no ranking, no percentage the CLI didn't already compute with an
  honesty label. Examples are concrete (a record title, a date), not
  aggregates.
- **Every claimed fire cites its source** — the example row names the
  field report's origin anchor or the activation event, so the human can
  (in principle) check it.
- **Lower-bound labels ride through** — capture rate stays labeled a lower
  bound (11 §4.3); the auditor never launders a lower bound into a
  measurement.

### 4.4 Output (b): worker briefs — the up-cadence channel

Small versioned files that fast workers load at activation (charter §3).
**One brief per consumer**, both regenerated whole each audit run:

| Brief | Path | Consumer + load seam | Byte cap |
|---|---|---|---|
| Analyst brief | `.self-learn/briefs/analyst-brief.md` | `worker._compose_prompt` — a new `{brief}` slot beside `{digest}` (`worker.py:640`) | **≤ 2000 bytes**, refuse-not-clip |
| Miner brief | `.self-learn/briefs/miner-brief.md` | `miner._compose_prompt` — a new `{brief}` slot beside `{rubric}` (`miner.py:683`) | **≤ 2000 bytes**, refuse-not-clip |

- **Builder note (no skip pin needed):** `discover_buckets` globs only
  `skills/*` | `projects/*` | `user/`, so the new root-level siblings
  `.self-learn/audits/` and `.self-learn/briefs/` are **naturally excluded**
  from bucket discovery — they are never mistaken for record buckets, and
  no `--selftest`/glob skip clause is required (unlike `telemetry/`, whose
  skip is pinned in 11 §4.2 because it predates this reasoning). The
  digest/brief files are producer-committed but never walked as records.
- **Versioning:** each brief carries a `brief-version:` marker line
  (mirroring the rubric's `rubric-version:`, `miner.py:573`) stamped from
  the audit run id, so a shift in analyst/miner behavior is attributable
  to a brief edit (12 A3 precedent). Briefs are committed by the audit run
  (producer-commits-own-writes, H-5), pinned subject `self-learn: audit
  briefs (<run-id>)`.
- **Load points are exactly the two named seams** — no other code reads a
  brief; a missing brief file renders the slot as empty string (the seam
  already tolerates a missing doctrine/rubric with a fallback string, so
  the pattern is established). The brief is **input tokens** on every
  analyst/miner run (charter §3's "compiled briefs fast workers load"),
  hence the hard byte cap (constitution rule 4 / P2).
- **Content (counts + examples, never scores):** analyst brief =
  portfolio routing bias ("user-scope CLAUDE.md holds 8/10 entries —
  prefer narrower when defensible"; class-level rejection patterns beyond
  the raw digest). Miner brief = precision feedback ("candidate class X
  never survives review"; canary recall as a standing count). Both carry
  concrete counts and example ids, no ranking numbers.
- **Pruning obligation (stale-advice removal — testable):** each audit run
  **regenerates the brief from scratch** from the current period's facts;
  advice whose supporting observation no longer appears is **dropped, not
  carried**. A brief line MUST NOT persist across a run whose evidence
  evaporated — the auditor reads its own prior brief (§4.2 input 5) and
  omits any line it can no longer source. Test: a brief line present in
  month N whose evidence is absent in month N+1 is absent from the N+1
  brief.
- **Provenance rule (every line cites its observations — testable):**
  every brief line ends with a bracketed source — a count with its window
  (`[rejected 3× this period]`) or example ids (`[lrn-…, lrn-…]`). A brief
  line with no citation is a validator refusal at write. Unsourced advice
  is exactly the "oral tradition" constitution rule 2 forbids.

---

## 5. The one-time why-audit (the auditor's first-run special task)

On its **first run only**, the auditor additionally performs a why-audit
of **existing canon** — the accumulated routed lessons that predate the
telemetry era and never had capture-time grounding. It runs as
`self-learn audit run --since <ledger-genesis>` (the `--since` window,
§4.1) with a first-run flag persisted in the audit cursor
(`<cache>/audit/cursor.json`, cache-only, mirroring the miner's
`cursors.json`).

- **What it produces:** a one-time section in the first digest — *"canon
  audited: N routed lessons; M carry no observed fire and no recorded
  why."* For each, it nominates (never executes) a human judgment:
  `confirm-held` (still good), graduate (woven into prose), or supersede
  (wrong). **It writes nothing to canon** — it surfaces candidates for the
  human, exactly as 11 §5's no-observed-fires list does. Constitution rule
  1 is absolute here: the why-audit is a *reading*, its output is a *list*.
- **Why first-run-only:** the cold canon has no historical why; later runs
  have telemetry accumulating from month one, so the special pass is not
  repeated (the ordinary §4.3 digest covers steady state). The flag
  ensures it fires once and never again.
- **Supersedes cold-read at portfolio level** (charter §7 ranking:
  cold-read audit was conditionally superseded by FW-31 trigger-lint at
  entry level; the why-audit is the portfolio-level dead-weight check the
  ranking said to *revisit only if dead weight persists in digests* — this
  is that revisit, gated on the first digest actually showing it).

---

## 6. Degradation legs (every channel)

- **Missing telemetry plane** (`.self-learn/telemetry/` absent — fresh
  ledger, cache wipe before any flush): `report.gather` already tolerates
  it (empty events); the digest renders every observation section as
  "unobserved this period" and says so plainly; briefs render as "no
  portfolio signal yet — mine conservatively" (the same fallback-string
  posture the rubric/doctrine seams use). Never a crash.
- **Empty month** (no routes, no fires): the digest renders a one-line
  "quiet month" and the prior briefs are **regenerated unchanged if their
  evidence still holds, else pruned** — an empty month does not blank a
  brief whose standing counts are still true, but it also adds nothing.
- **Corrupt brief** (unparseable/oversized on load): the load seam treats
  an unreadable or over-cap brief as **empty string** (the analyst/miner
  proceeds on doctrine+rubric alone) and logs a warning — a brief is
  advisory, never load-bearing (E-11); a broken brief must never break an
  analyst or miner run. The next audit run overwrites it.
- **Corrupt / partial telemetry line** — `report`/`read_events` already
  skip malformed lines rather than crash (`report.py:213` posture); the
  digest counts what it can parse and says the plane had unreadable lines.
- **Miner never ran / no field reports** — the digest's fire sections read
  "unobserved" (not "zero fires"); the CLAUDE.md-scope attribution gap
  stays open and the digest says so (charter §2: the gap closes only to
  the extent sessions are mined).
- **Doctrine draft with <2 observations / unsourced brief line** — refused
  at CLI validate with a plain-words message (§3.2/§4.4), never written.
- **Audit run overlaps a sentinel-held review** — the audit takes no
  record locks (it only reads + writes its own briefs/digest files); its
  brief/digest commits ride the producer-commits-own-writes path and wait
  behind the sentinel like any flush (11 §4.2). No contention with review.

---

## 7. Security & consent posture

- **No new secret-scan surface for field reports** — they ride the
  existing scan-at-flush; payloads are ids/enums/anchors (a hit is
  structurally near-impossible, and refuses the whole flush if it happens).
- **Doctrine drafts and briefs are secret-scanned on write** like every
  proposal sibling / record write; the brief and digest are tracked files
  autosynced within seconds, so the scan guards the write path (E-8).
- **No worker widens its own scope.** The pane cannot apply its own
  doctrine draft (human confirm → CLI); the auditor cannot write canon or
  briefs the analyst is forced to trust (briefs are advisory, capped, and
  never load-bearing). The auditor's model pass is contained
  (`Read,Grep,Glob` + spool-scoped write) exactly like the miner reader.
- **Consent for canon change stays human + CLI** — `doctrine apply` and
  every route/confirm verb is the human's; this doc adds no autonomous
  write anywhere (constitution rule 1, restated in §8).

---

## 8. Non-goals & out-of-scope (constitution rule 1, absolute)

- **No autonomy changes.** 12 A2's ladder stays at L0; nothing here steps
  it. The miner still never routes; the auditor never resolves; the pane
  never executes.
- **No canon writes by any worker.** Field reports, briefs, and doctrine
  drafts are all proposals/observations. The only canon writers remain
  human-triggered CLI verbs.
- **No new event collector beyond the three field-report kinds** — the
  auditor reports the absence of a signal, it never grows a probe to
  manufacture one (no CLAUDE.md-fire instrumentation, no session hooks).
- **No modeled metric, no score, no chart** — the digest and briefs are
  counts + examples (04 counted-not-modeled; 07 §5 "not a monitoring
  platform").
- **No embedding/similarity infrastructure** — suspect matching stays the
  existing in-context computation (12 §5's pinned scaling path is
  untouched; G-5's trigger has not fired).
- **No web verb for doctrine editing in M1** — that is FW-30's settings
  surface; §3.4's pane-confirm/CLI path is the M1 consent route.
- **Contradiction *edges* are not written by any worker** — the miner
  emits a *suspect*; only a human `link contradicts` writes the edge.

---

## 8a. Build plan — three stages (F8)

One spec covers both FW items, but the work is **three stages with a hard
ordering**, and the build must not treat them as one drop:

- **Stage A — field reports** (FW-36 half one): the `contradiction-suspect`
  event kind + `SCHEMA_VERSION = 2` (§10), the reader-prompt
  `contradictions[]` schema + parse/validate/spool loop (§2.1/F5), and the
  three doc-syncs (11 §4.2 ×2 clauses + `telemetry.py` docstring, §10/F2).
  **Near-ship-ready** — it extends already-shipped miner telemetry with one
  kind and corrects stale prose. Build A **first**: it starts telemetry
  accrual, and the auditor (Stage B) is worthless until fire/recurrence/
  contradiction sightings have accumulated for it to synthesize.
- **Stage B — the auditor** (FW-33): the `audit run` verb, receipts digest
  + Y-27 Front panel, worker briefs + the two load seams, the why-audit,
  and the monthly timer/watchdog. **Depends on A at build time** — the
  digest's fire sections read "unobserved" until Stage A's field reports
  exist, so B ships after A even though this one spec specifies both. B
  needs no part of C.
- **Stage C — doctrine drafts** (FW-36 half two): the `propose_doctrine`
  tool + `DoctrineProposalSlot` (with the file-staleness clear leg), the
  `doctrine draft` / `doctrine apply` / `doctrine dismiss` verbs + `doctrine
  draft --list`, the `base_fingerprint` stamp + apply-time freshness check
  (§3.4/F-new-1), the orphan enumeration + GC posture (§3.4/F-new-2), and
  the 09 §4.5 + 09 §11 register amendments (§10/F3). **Buildable ONLY after
  the F3 respec is ratified** — it introduces a new surface tool and two
  register entries that this draft *proposes*; they must clear the gate
  before any C code lands. C is independent of A and B and can run in
  parallel with B once ratified, but never before its own register
  amendments are accepted. **The delta gate confirmed A/B SOUND and
  build-ready; the remaining NOT-SOUND surface is contained to C** (this
  fold closes it — F-new-1/2/3).

**Ordering pin:** A → B (data dependency); C gated on F3 ratification,
otherwise order-free. A single spec, three deliverables, not one merge.

## 9. Test obligations & DoD trials

**Unit / fixture (CI):**

- (t-a) contradiction-suspect emission: a synthetic digest naming a routed
  rule contradicted → one `contradiction-suspect` event spooled with
  `{record, contradicts, origin, basis}`, deduped on `(kind, record,
  origin)`, no transcript text in the payload.
- (t-b) `report.contradiction_suspects` exposes rows `{id, contradicts,
  nonce, seen_at}` filtering already-linked edges — and the auditor + the
  **Front panels** (the read-only digest/holding surfaces, Stage B —
  *not* the doctrine pane bar of Stage C) consume it, never re-walk
  telemetry (assert one computation).
- (t-c) field-report self-containment: an event read after its transcript
  fixture is deleted still parses and renders (anchor+ids+enum only).
- (t-d) `doctrine draft` intake proves **exactly what it can** (F4):
  <2 `observations`, or ≥2 with non-distinct `ref`s, is refused
  (cardinality); an `observations` entry whose `ref` resolves to no record
  or prior draft is refused (ref-resolvability); an `amends` target other
  than `routing-doctrine.md` is refused; a `doctrine draft` never mutates
  `routing-doctrine.md` (only `doctrine apply` does). **No test asserts
  the notes are faithful** — faithfulness is not a validator property
  (it is the human confirm's, §3.2).
- (t-e) brief byte cap refuses-not-clips at 2000 bytes; a brief line with
  no bracketed citation is refused at write (provenance rule).
- (t-f) brief pruning: a line sourced in month N with evidence absent in
  N+1 is absent from the N+1 brief (regenerate-from-scratch).
- (t-g) digest honesty: a CLAUDE.md-scope rule with no field report gets
  **no** fire claim and lands in "Quiet canon (unobserved)"; the string
  "dead weight" never appears.
- (t-h) load-seam tolerance: a missing/corrupt/over-cap brief loads as
  empty string; the analyst and miner runs complete unaffected.
- (t-i) `flush` still scans + commits + pushes for a `mine run` that emits
  only field reports (regression guarding the §2.4 resolution).
- (t-j) doctrine freshness (F-new-1): a `doctrine apply` whose draft
  `base_fingerprint` no longer matches the live target section (mutate the
  section between draft and apply) **refuses** with the resolved-elsewhere
  message and leaves `routing-doctrine.md` unchanged; a section that has
  become unlocatable refuses identically; a matching fingerprint applies.
  The whole-file-fallback path (unlocatable `section` at draft time) is
  covered symmetrically.
- (t-k) doctrine orphans (F-new-2): `doctrine draft --list` enumerates an
  un-applied committed draft after a simulated restart (slot lost, file
  present); `doctrine apply` and `doctrine dismiss` are the **only** two
  removers (no time-based sweep exists); a re-surfaced stale draft still
  refuses at apply per t-j.

**DoD live trials (user-present, logged in `fixtures/ui-trials.md`):**

- (d-a) a forced `mine run` over a synthetic session that contradicts a
  routed rule lands the contradiction-suspect, surfaced on a **Front panel**
  (the read-only digest/holding surface, Stage B — not the doctrine pane
  bar of Stage C) for a human `link contradicts` (never auto-written).
- (d-b) a forced `audit run` produces `.self-learn/audits/<month>.md`,
  the Y-27 Front panel renders it, and every fire claim cites a source;
  a rule with no observation reads "unobserved," not "worthless."
- (d-c) the first `audit run` performs the why-audit over existing canon,
  nominating (never executing) confirm-held/graduate/supersede per cold
  lesson; the run flag prevents a second why-audit.
- (d-d) a pane session that articulates the same routing judgment twice
  offers a doctrine draft; the human's arm+Enter runs `doctrine apply`,
  which updates `routing-doctrine.md` and removes the draft; a one-off
  judgment offers nothing.
- (d-e) analyst and miner runs after an audit visibly load their briefs
  (the `{brief}` slot is populated) and behave unaffected when the brief
  is deleted.

---

## 10. Register touch-points (amendments this build requires — the honest list)

| Pin | Status under this doc |
|---|---|
| **11 §4.2 (flushing discipline) — the complete stale-statement list (F2)** | **Prose doc-sync required (not a design change).** The "only human-triggered CLI verbs flush" model is already falsified by shipped, audited code (primary: `miner.py:1464` + its `1461–1463` machine-triggered-commit comment; corroborant: `telemetry.py:239–247`, audit 2026-07-16 MAJOR 3 + doc 13 H-5). **Three colocated statements must all be corrected in the same sweep:** (a) **11 §4.2 first clause** — "Only human-triggered CLI verbs flush" (add `mine run`; restate the rule as *scans-before-moving AND producer-commits-its-own-writes; a timer-triggered CLI producer qualifies*); (b) **11 §4.2:210–212 second clause** — "autosync commits them on its normal cycle" is stale (H-5 removed the watcher; `flush()` commits, per its own docstring) and must be struck; (c) **`telemetry.py` module docstring line 10** — the code-colocated "Only human-triggered CLI verbs flush" repeats the falsified prose and must be corrected in lockstep so code and spec agree. P6/E-8 letter preserved (scan-at-flush). §2.4 argues this in full. |
| **11 §4.3 (closed event-kind set) + `SCHEMA_VERSION` (F6)** | **Version bump required, pinned literally.** Add `contradiction-suspect` to `EVENT_KINDS` (`telemetry.py:67`) with payload `{record, contradicts, origin, basis}` — ids/enums/anchor only, §4.4 content discipline unchanged. **`SCHEMA_VERSION` must be INCREMENTED — do not pin the literal.** *(Corrected 2026-08-02, FW-65. This cell previously read "`SCHEMA_VERSION = 2` (bump the literal at `telemetry.py:64`, currently `1`)". **`U-reach` shipped `SCHEMA_VERSION = 2` on 2026-08-02** for its own `route` kind, so that instruction is now doubly wrong: the literal it names as the target is already taken by a different unit's closed set, and criterion F6 as originally worded — "`SCHEMA_VERSION = 2` pinned" — would **pass on arrival with nobody having bumped anything**, satisfied by another unit's work. Two closed kind-sets both labelled v2 is precisely what the constant's own contract forbids.)* Read the current value at build time and increment it; assert the **increment**, never a literal. Extending the closed set is a schema version bump by that constant's own contract; the derived SQLite index (11 §5) is keyed to `schema_version` and **rebuilds on mismatch**, so no migration. `fire`/`recurrence-suspect` are **untouched** (already emitted). |
| **09 §4.5 + 09 §11 (`propose_doctrine` tool) — F3** | **Two register amendments required.** (i) **09 §4.5** gains a **second server-owned SDK tool `propose_doctrine`** beside `propose_verb`, with its own `DoctrineProposalSlot` (independent slot, no bucket/record key, clear-set = dismiss/confirm/disarm/session-end only) — the `PROPOSABLE_VERBS` closed set (`proposals.py:67`) is **not** widened (a doctrine draft is not a verb-on-a-record; extending that frozenset was the wrong shape). (ii) **09 §11** gains a surface register entry for the WAITING **doctrine bar** and its arm/confirm/disarm/dismiss route triple (the first non-record, non-bucket proposal surface) — reusing the `.action-bar[data-armed]` + server-nonce contract, so Enter-confirms/any-key-disarms works unchanged. New CLI verbs `doctrine draft` (+ `--list`) / `doctrine apply` / `doctrine dismiss` are 08-owned substrate (pinned commit subjects §3.4; `base_fingerprint` stamp + apply-time freshness re-check per F-new-1), not a Y-number. |
| **12 (miner)** | Extended, not amended: contradiction-sighting is one new `spool_quiet` call beside the fire loop; `_event_seen` kind-tuple gains the new kind; the miner brief loads at `_compose_prompt`. Episode-brief invariants untouched. **Stale as of 2026-08-02 (FW-65):** `U-recur` changed `_event_seen`'s return type from `set` to `tuple[set, list]` (it now also returns the violated fires that must cross over to `recurrence-suspect`), so "gains the new kind" understates the change — read the current signature before building against this row. Line references to `telemetry.py` elsewhere in this spec were written against the pre-`U-reach` file and have all moved; resolve symbols, not line numbers. |
| **02 §1 (proposal schema)** | Untouched by field reports. Doctrine drafts are a **new proposal-sibling class** in `references/doctrine-drafts/`, not a record-proposal — no change to the `proposals/lrn-*.yaml` schema. |
| **routing-doctrine.md** | Becomes an *amendable* file via `doctrine apply` (human-confirmed). The file's content is not changed by this doc; its editability path is added. |
| **07 §2 (surfaces) / 09 §11** | Gains **Y-27** (Front receipts-digest panel) — read-only, ambient, a rendering of `.self-learn/audits/<month>.md`; no new demanding surface. |
| **P1 / M-1 / E-11 / 04 counted-not-modeled** | **Reaffirmed, never relaxed** — every channel is proposal/observation; no autonomy, no canon write, no score; the auditor is never load-bearing. |
| **13 §5 H-5 (producers commit own writes)** | Extended to the auditor: its briefs/digest are producer-committed (pinned subjects), consistent with the miner and telemetry flush. |

---

*End of DRAFT. Awaiting blind two-gate review; on SOUND, graduates to
`docs/specs/self-learn/16-ecology.md` with a dated disposition note on
FW-33/FW-36 in `14-forward-work-map.md` §6a.*
