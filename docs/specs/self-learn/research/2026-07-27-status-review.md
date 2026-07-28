# Research — independent status review (recent work, outstanding, path forward)

*2026-07-27, evening. An outside read requested by the user, deliberately
prompted **neutrally**: the reviewer was given the repo, the entry points,
and the three questions, and was explicitly **not** given the orchestrator's
priorities, conclusions, or ranking. Reviewer model: Fable.*

**Status: assessment, not authority.** Like
[`2026-07-27-routing-monoculture-and-pin-audit.md`](2026-07-27-routing-monoculture-and-pin-audit.md),
this record pins nothing and ratifies nothing. It is one agent's read.
Where it disagrees with the plan of record, that disagreement is recorded
as a *claim to weigh*, not a decision taken. Items graduate by becoming a
`03` row, an FW row, or a spec.

**Independence caveat, stated because it matters:** the reviewer read the
same-day routing/pin audit before forming its view. Its agreement with that
audit's findings is therefore only partly independent — it reports having
re-verified the central claims at HEAD, which is real, but the framing may
be inherited. **Its two disagreements (§3) are the least contaminated part
of this review** and should carry the most weight.

## 1. Verdict

The system is live and healthy at the unit level, and the engineering
discipline is strong. But the **delivery layer — the point of the product —
is broken in three independent ways**, none fixed, and the official forward
plan does not reflect that. Recent effort went to UI perceptibility polish:
good work, one layer above the actual problem.

## 2. Recent work — verified by the reviewer in-session

- Public release (07-24) executed cleanly; the reviewer independently
  confirmed the personal-literal scrub landed **before** the flip (no
  `komi` / `DEFAULT_MEMORY_DIR` in shipped source).
- In-flight SSE feedback; the source-blind walk instrument + 5 walks;
  the resolution-evidence and commit-drift receipt units; the routing/pin
  audit; the UI test cache-isolation fix.
- Suites run sandboxed by the reviewer: **CLI 1133 passed / 5 skipped;
  UI 1010 passed / 77 skipped / 1 failed** — the failure is the known
  pre-existing `test_service_unit` item. It independently identified the
  77 skips as an artifact of the `XDG_CACHE_HOME` redirect moving
  Playwright's browser path, not a property of the host (matching
  `drafts/ui-test-cache-isolation-spec.md` §7, reached separately).
- Miner ran that morning (`ok, 1 fire`); ledger consistent (13 pending
  files, 51 resolved); master pushed; tree clean.

## 3. The two disagreements with the plan of record

**These are the reviewer's own, and both were verified by the orchestrator.**

### 3.1 `14-forward-work-map.md` §3's "recommended next three moves" is stale

Verified verbatim at `14-forward-work-map.md:96-107`: (1) FW-17/18 hygiene,
(2) FW-16 round 4, (3) FW-10…FW-15 packaging. Written 2026-07-18 — **before
the audit existed**. None of the three touches routing, delivery, or the
analyst.

The reviewer's argument for deferring packaging specifically, which the
orchestrator had not made: the repo is **already public**, and what a new
user meets first *is* the routing layer — the part that is broken.

*(Disposition note added to §3 of doc 14 under this record.)*

### 3.2 The fast lane is armed and pointed at the delivery hole

`drafts/fast-lane-spec.md` is gated SOUND and build-unblocked since
2026-07-19, and it tiers `reference` as **FAST** on the grounds that it is
an "unloaded surface… affects zero activations". Given §4.1, that
justification is true in the worst sense. **Nothing currently blocks
someone building it**, and doing so before the `reference` ruling would
industrialise the defect. (Its own header still reads `DRAFT` — see §5.)

## 4. Outstanding — the audit's fallout is the real backlog

Re-verified by the reviewer at HEAD; all still live:

1. **Delivery hole** — 14 of 28 routed records sit in a `LEARNINGS.md`
   nothing references. "Routed" ≠ "loadable", and no metric distinguishes
   them.
2. **User-scope monoculture** — the `("claude-md",)` singleton, plus
   `verbs.py:950` still refusing `reference` on a chezmoi premise retired
   2026-07-24; the dead premise mis-teaches the analyst in 3+ places.
3. **Analyst can never emit `hook`** — the serializer drops
   `hook:`/`examples:`; 34% silent failure at rc=0; it silently re-splits
   the S-10 knob the user explicitly ruled unsplit.

Also named: the excerpt marker case mismatch (the 703-line
`~/.config/CLAUDE.md` analyst is blind today); `routing.by` a hardcoded
constant **and** no telemetry kind for route/reject/defer/graduate — so the
autonomy ladder's evidence substrate does not exist; `~/.claude/CLAUDE.md`
at 337% of the word cap while the UI leads with the non-binding axis;
1.1 GB / 31,214 stale cache dirs (fix shipped, cleanup outstanding).

**Ring-targeting (W4-F1) is spec-ready at rev 7 but unbuilt** — described by
the reviewer as the one live defect that can act on the *wrong record*.

## 5. Bookkeeping decay — verified, and not cosmetic

Four spec headers claim a state the repo contradicts:

| file | header says | reality |
|---|---|---|
| `a1-labels-spec.md` | "DRAFT — for blind Opus spec gate" | shipped, `4950929` |
| `a2-rules-local-spec.md` | "DRAFT — for blind Opus gate" | shipped, `b11d9aa` |
| `analyst-riders-spec.md` | "Not gated, not built" | merged 2026-07-19 |
| `ui-inflight-feedback-spec.md` | "Status: SOUND" | builder-landed, `03` S-20 |
| `fast-lane-spec.md` | "DRAFT" | gated SOUND + build-unblocked 07-19 |

`records-index.md`'s Reviews section stopped at 2026-07-19 while `reviews/`
held a 2026-07-24 record.

The reviewer's framing, which the orchestrator endorses: in a corpus whose
own audit proved **fossil rationale reads exactly like live rationale**,
five specs misreporting their own state is a live hazard, not tidiness.

## 6. The reviewer's recommended sequence

Recorded as proposed, not adopted:

1. **Graduate the audit** — FW rows + a repair spec, and one round of the
   §13 values questions to the user (it calls these blocking).
2. **The mechanical fixes** — serializer passthrough, marker casing,
   `routing.by`, resolution telemetry kinds, the budget line's binding
   axis, the chezmoi-text sweep.
3. **Ship ring-targeting, then pause UI rounds.**
4. **Decide `reference`**, add the "reachable from a loaded surface"
   selftest (fails 14× today), re-deliver the stranded records.
5. **The funnel-loosening round** as the next major phase, with fast-lane
   held and re-gated behind it.
6. Cache cleanup (user-owned) · 7. bookkeeping catch-up · 8. packaging
   stays queued.

## 7. What the reviewer could not establish

- The worker-path routing distribution (the audit marks it untested too).
- Whether the walks' worker "Force run" unresponsiveness reproduces
  outside the sandbox.
- Live-UI behaviour — the service was idle and it did not start one
  against the real ledger.

## 8. Disposition

- §3.1 → dated note on `14-forward-work-map.md` §3.
- §4 → FW-40…FW-45 (`14-forward-work-map.md` §2).
- §3.2 → FW-41's trigger wording; fast-lane held pending the `reference`
  ruling.
- §5 → headers corrected and `records-index.md` caught up, same commit.
- §6 → **proposed only.** Sequencing is the user's call; the values
  questions in §4 of doc 14 gate most of it.
