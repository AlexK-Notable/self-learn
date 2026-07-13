# 2026-07-12 phased implementability gates — M1/M2/M3, all PASS

*User-directed process (goal directive): iterate the planning docs through
per-phase cycles of independent review → remediation → independent gate
check, until an independent review agent agrees that, given enough time, a
mid-tier agent could implement the full plan (TUI construction excluded)
from the documentation alone. Three phases (M1, M2, M3), three independent
Fable reviewers, every one blind to `reviews/` and ground-truthing against
the live repos. Like its siblings, this memo is withheld from future blind
reviewers.*

## Phase 1 — M1

- **Gate check 1: FAIL** — F1 BLOCKER: slash commands had no deploy path
  (install.sh has no commands surface; plugin-install forbidden; §6.2
  unsatisfiable). Minors F2–F6: scan-pin self-contradiction (40-hex),
  backlog source-file set vs the three GOTCHAS files, references target
  unpinned, supersession had a commit format but no CLI surface, fixture
  C absence-grep tripping on an ha-note usage example.
- **Remediation** (`6dcec5e`): Command-deploy pin (install.sh commands
  surface, colon-name expectation + written flat-name fallback), hex ≥48,
  journal-only import, `references/LEARNINGS.md`, `teach --supersedes` +
  bare `supersede` verb, fixture-C claim narrowed with the pre-dismissed
  non-hit.
- **Gate re-check: PASS** (`bb6e285` folded residuals R1–R3: 04-M1 synced
  to the F1 pin; shellcheck-availability scoping; C.1 "only in
  GOTCHAS.md" corrected to "only under references/").

## Phase 2 — M2 (08 §7 authored first, then reviewed)

- **Review: FAIL** — gates M2-1..5: no merge-proposal schema; no collapse
  CLI surface (contract-1 violation waiting); `--allowedTools` unpinned +
  circular test; mtime staleness broken by git checkouts; kick/coalesce
  mechanics undefined. Fifteen minors M2-6..20.
- **Remediation** (`d24c66c`): merge-proposal schema in 02 §1;
  `route --collapse` verb; literal allowedTools value + no-Bash warning +
  live refusal check; content-hash staleness (`record_sha`); full
  kick/window/dirty mechanics; all minors (event schema, notification
  template, escalation debounce, `status --fast`, real-worker smoke a′…).
- **Gate re-check:** all twenty closed, **one new gate M2-21** — the
  remediation had directed the *model* to emit `record_sha` (models can't
  hash; fabricated hashes would silently reconstitute the always-stale
  behavior). Fixed (`3db0ddcb`): the CLI computes and stamps the hash at
  proposal validation for all three producers; + M2-22..25 sync fixes.
- **Diff-verified: confirmed PASS.**

## Phase 3 — M3 (08 §8 authored first, then reviewed)

- **Review: FAIL** — gates M3-1..5: settings.json snippet shape
  unspecified (dead-matcher trap — path regex in the matcher field never
  fires); hook target broke regenerate-at-apply with no stated exception;
  08-vs-01/S-6 contradiction on the new-skill compiler (stop-trap under
  the authority rule); no correction/rollback path for live guards
  (S-12's recompile undefined for hooks; selftest semantics inverted);
  fixture A scoreable green via stdin pipe without the registered hook
  ever firing. Eight minors M3-6..13. Reviewer ground-truthed the guard
  protocol against `organizer-guard.sh` and the real settings.json.
- **Remediation** (`3733a9f`): literal snippet template (matcher =
  tool-name set); verbatim-apply exception pinned in 08 §8.1 + 02 §1;
  01 diagram/table + S-6 dated amendments (CLI-owned scaffold); hook
  rollback pin + selftest re-scope + false-positive playbook; live
  fresh-session fixture-A harness; slug/path/field/collision/manual-step
  pins; guard test replay; three new §4 judgment rows.
- **Gate check: PASS** (one non-gating M3-14, folded same day) — **plus
  the terminal full-plan verdict: PASS** — "given enough time, a
  mid-tier, literal-minded agent could implement the full plan from the
  documentation alone," on the basis that every inventable interface is
  pinned and ground-truth-correct, the beyond-mid-tier judgment calls are
  routed out of the builder's hands (§4) with a deterministic stop
  condition (§0 rule 5), and the failure modes have playbooks (§5).

## Standing notes for the build

- Keep §9's Build-findings appendix discipline during execution — the
  reviewers' verdicts rest on that mechanism as much as on the pins.
- Recurring lesson, now 3-for-3 across this process: **remediations can
  mint new blockers** (M2-4 → M2-21). Every fix batch got an independent
  re-verification before its gate closed; keep doing that.
- Independent-verification tally across the whole self-learn project:
  every review round has overturned or materially sharpened at least one
  authored position. Never self-certify a gate.
