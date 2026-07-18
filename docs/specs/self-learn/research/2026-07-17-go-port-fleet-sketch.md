# Go-port fleet sketch — "seatbelt YOLO" (2026-07-17)

**Status: SKETCH, not a plan of record.** Sizing input for a possible
full rewrite of self-learn (CLI + G-3 UI) in pure Go. Explicitly NOT
the standing gate discipline — this is the deliberately-fast variant,
with exactly three safety non-negotiables ("seatbelts") kept because
they're cheap and kill the worst failure classes. If this is ever
executed, it happens in a dedicated repo/worktree and the spec corpus
gets a dated revision pass only AFTER parity, not before.

## The three seatbelts (non-negotiable even in YOLO mode)

1. **Sandbox-only until parity.** Every agent runs against a CLONED
   ledger + sandbox hosts (the seeded-sandbox tooling from the
   2026-07-17 UI cycles). The real ledger is read-only input for
   golden extraction; no Go binary touches real state before cutover.
2. **Canonicalization goldens FIRST.** Phase 0 extracts golden files
   from the PYTHON implementation: `record_sha` for every ledger
   record, the X-12 home-slug/cache-path hash over a path matrix
   (`~`, `//`, `/.`, trailing-slash, `..` cases), canon-compile output
   for every routed record, and `list/status/report --json` snapshots.
   Cross-language canonicalization drift is the #1 silent-corruption
   class; two ~50-line golden tests kill most of it.
3. **Python stays the only canon WRITER until compile-diff is empty.**
   The compile path writes managed sections into REAL host repos and
   autosyncs across machines — highest blast radius. Go's compiler
   ships read-only (diff mode) until its output over the real ledger
   is byte-identical.

## Module map (from the live tree)

CLI `cli/src/self_learn/` (~15k lines src, ~16k tests): records,
normalize, scan, ledger/ledger_ops, gitops, hosts, verbs/cli, teach,
compilers + hook_compiler + skill_scaffold, analyst, worker, miner,
sentinel, telemetry, report, reconcile, selfcheck, config, chezmoi,
import_*. UI `ui/src/self_learn_ui/` (~5k src, ~8k tests): env,
ledger, models, rendering, routes, middleware, runner, sse, keymap,
pane, engine/{base,charter,sdk}, uilog, cli. Plus ~3k lines
templates/CSS/app.js (htmx vendored, unchanged).

Go dependency map: cobra (verb tree) · yaml.v3 · go-git or exec git
(keep exec — matches current behavior) · net/http + html/template ·
goldmark (markdown-it-py) · chroma (pygments; re-pin the dual-theme
generator test against chroma output, not pygments bytes) · fsnotify
(watchfiles) · stdlib SSE. No Go agent-sdk exists → pane uses the
09 §4.1 `cli` engine rung (shell `claude -p` stream-json; charter as
PreToolUse hook) — see risk register.

## Phases

**Phase 0 — scaffold + goldens (serial, ~half day)**
- S0a (Sonnet): Go module scaffold `cmd/self-learn`,
  `cmd/self-learn-ui`, `internal/<module>` mirroring the map above;
  vendored static assets copied; go vet + test harness wiring.
- S0b (Sonnet): golden extraction harness (runs the Python impl;
  emits the seatbelt-2 golden files) + cloned-ledger sandbox setup.

**Phase 1 — core library fan-out (8 Sonnet, parallel)**
1. records + normalize + record_sha (golden-gated)
2. ledger/ledger_ops (create/route/reject/defer/graduate, git ops,
   pinned commit subjects)
3. hosts + canon_read_roots + home-slug/cache paths (golden-gated)
4. proposal/merge validation + secret scan (regex parity tests)
5. compilers + hook_compiler + skill_scaffold (golden-diff vs Python
   output; READ-ONLY mode per seatbelt 3)
6. worker + sentinel + telemetry + report
7. miner (journal, transcript scan, claude -p subprocess)
8. verb-tree assembly (cobra) + exit-code/stderr contracts + teach
Each agent: port module + translate its Python tests + pass goldens.
Contracts between modules pinned up front by the orchestrator (one
interfaces file authored before fan-out) so agents don't negotiate.

**Phase 2 — UI fan-out (5 Sonnet, parallel; starts once 1.1–1.4
interfaces freeze — overlaps phase 1's tail)**
1. models (pure screen models)
2. routes + middleware (token flow, Host check, HX-Request CSRF,
   CSP — parity with test_middleware.py translated)
3. templates Jinja→html/template + chroma dual-theme generator +
   goldmark rendering
4. SSE + watcher + runner (serialized verb queue)
5. pane cli-engine (dark-shipped behind an env flag; NOT required for
   cutover — see risks)

**Phase 3 — integration + parity (2 Sonnet, serial-ish, ~1 day)**
- wiring: binaries, install.sh variant, systemd unit, launcher compat
  (port 7357 contract, token file paths byte-identical per golden).
- parity runner: scripted verb sequence replayed on TWO clones (Python
  vs Go), diff git trees + all --json outputs; canon compile-diff over
  the real ledger (read-only). Playwright smoke walk (existing loop):
  all screens, both themes, full keyboard flow.

**Phase 4 — Opus review gate (2–3 Opus, parallel lenses)**
YOLO-calibrated: fold MAJORs only, one delta pass, no spec-corpus
review.
- R1 security lens: middleware parity, token/CSRF posture, host-add
  path provenance, charter-hook enforcement — adversarial.
- R2 data-integrity lens: sha anchoring, YAML writes, managed-section
  markers, commit subjects — against goldens.
- R3 (optional) behavior-diff lens: screenshots + flows vs Python.

**Cutover:** ship as `self-learn-go` beside the Python binary; flip
the ~/bin symlink when parity is green; canon-compile write authority
flips only on empty compile-diff; pane stays Python (or dark Go) until
its own later cycle; Python retained for rollback ≥2 weeks.

## Fleet + budget

~15–17 Sonnet implementers + 2–3 Opus reviewers + orchestrator.
Token ballpark from this session's observed runs (Opus reviews
140–230k each; a module port with test translation + compile/test
loops realistically 150–400k): implementers ~4M, reviewers ~0.6M,
integration/parity/orchestrator ~1–1.5M → **order of 5–8M tokens**.
Wall-clock **2–4 days** at ~10 concurrent agents.

## Risk register (what YOLO consciously accepts)

- **Pane charter via hooks** — a port-shaped redesign; risk is a
  quietly PERMISSIVE pane, not a broken one. Mitigation: ships dark,
  excluded from cutover, gets its own later gated cycle (it is also
  item 7's dependency, so it will be revisited regardless).
- **Jinja→html/template semantic drift** (whitespace, with-scoping,
  autoescape differences) — benign-but-visible; caught by Playwright
  smoke + R3, not guaranteed exhaustively.
- **chroma ≠ pygments byte-output** — accepted; the generator test is
  re-pinned against chroma. Colors may shift slightly (Y-10 audit
  re-run in R3).
- **Test translation fidelity** — translated tests can silently
  assert less than their originals; R2's golden lens partially
  compensates. Residual risk accepted.
- **Long-tail behavior** (SSE reconnect, interrupt timing, miner
  journal edge cases) — expected to surface in use, git-revertible.

## Honest odds (per the assessment that spawned this sketch)

Demo-quality binary: ~90%. Trustworthy CLI against the real ledger
without incident: ~70–80% WITH seatbelts (vs 50–60% raw YOLO).
Drop-in including pane: not attempted — pane deliberately deferred.
