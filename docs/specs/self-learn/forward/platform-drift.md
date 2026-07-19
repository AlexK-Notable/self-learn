# Forward theme F — Platform drift: the risks we don't control

*Companion to `../14-forward-work-map.md` §2 (FW-23…FW-25). Dated
2026-07-18. Everything self-learn delivers rides surfaces owned by
Anthropic: the Agent SDK (the pane engine), Claude Code's loading
semantics (SKILL.md bodies, CLAUDE.md, hooks, plugin format), and the
`claude` CLI itself (the worker/miner substrate). None of these carry
compatibility promises sized to this project. The theme's posture:
**watch protocols with pre-registered responses** — the cost of drift
is minimized by deciding *now* what each event means, so the response
is execution, not deliberation during breakage.*

## 1. FW-23 — Agent SDK drift (the pane engine's ground)

**Exposure, ranked**: (a) the pane engine — streaming shapes,
`canUseTool`/charter enforcement, session flags (the X-7 contingency
already fired once — session persistence was absent on the 0.2.121
verify-at-build run; `--no-session-persistence` via `extra_args` was
the pinned fallback and it engaged as planned);
(b) the `propose_verb` tool contract (schema handling changed behavior
once already — the dict-shorthand incident); (c) auth-chain behavior
(empirically probed 2026-07-12; subscription rides the same chain —
a change here dark-ens the pane for subscription users specifically).
**Protocol**: pin the SDK version in the lockfile — drift arrives only
when *chosen*; on any bump, re-run the verify-at-build probe battery
(10 §1's ledger) **before** merging the bump; promote that battery to
the release checklist (FW-15) so every release records "verified
against SDK x.y.z". On probe failure: the specced alternative engine
(CLI `claude -p` stream-json subprocess — a view-layer swap by design,
09 §4.1) is the standing fallback, which is precisely why that
alternative must stay recorded and not rot out of the spec.
**Watch rider**: the Esc-interrupt 5 s backstop (FW-18 item 5) upgrades
to a clean interrupt if/when the SDK exposes one — checked at each
bump, never chased between bumps.

## 2. FW-24 — Native per-skill memory (the existential watch)

**The event**: Anthropic ships native memory attached to skills or
projects — the reopen trigger written into S-1 on day one (E-9).
**Pre-registered reading of the event**: it is **not** a kill signal
for self-learn; it is a *delivery-surface* change. The system's value
concentration is upstream of delivery — capture with evidence, the
human gate, routing judgment (the doctrine, ancestor-project logic,
scope discipline), lifecycle telemetry. A native memory surface would
be, structurally, a **fourth compile target** (alongside skill-md /
claude-md / reference): the compilers are marker-bounded and
target-abstracted precisely so a new destination is an added backend,
not a redesign.
**Protocol when it fires**: reopen S-1 in the register (its stated
input changed — the register's own rule); evaluate the native
surface's properties against P1/P2 (does it load natively? can a human
gate writes to it? does it respect attention budgets?); if it
qualifies, spec it as a destination through the normal chain. The
failure to avoid is pre-registered too: **do not** rush lessons into a
native surface that lacks a human gate — P1 is not for sale to
platform convenience (the same line 06 §5 draws for team scale).
**Cheap standing hedge, already owned**: destination-abstraction in
the compilers and `--dest` plumbing. No speculative build beyond that.

## 3. FW-25 — Claude Code surface drift (loading, plugins, hooks)

**Exposure**: SKILL.md/CLAUDE.md loading semantics and attention
behavior (P2's lean-canon math assumes current loading); plugin/
command format (the flat-name fallback for colon-namespacing is
already written into 08 §1 — precedent for format hedges); hook
registration schema in settings.json (the P9 flow's manual-
registration step is also, usefully, a drift firewall — a human reads
the snippet at install time); `claude -p` flag surface (worker, miner,
launcher all shell to it; the bundle-exclusion contingency adds the
PATH-claude preflight, FW-14, which doubles as the version-visibility
hook).
**Protocol**: release-notes review on Claude Code updates is the whole
watch — this host updates frequently and organically, so drift
announces itself fast solo. The `doctor` preflight (FW-14) records the
`claude` version at install/upgrade; the release checklist (FW-11)
runs the suites against the then-current Claude Code, which
transitively exercises the loading and CLI seams the suites touch.
**Honest limit, stated**: loading-semantics drift (how much of a
SKILL.md body actually reaches attention, P2's ground) is **not
mechanically detectable** by any suite this project can write — it
would surface as gradual behavioral decay of routed lessons. The
long-term detector is the recurrence telemetry (11): lessons that
stop holding across the board is the signature to watch for, and FW-5's
periodic accounting is where it would be seen. This is a known
watch-gap, accepted, not solved.

## 4. The theme's one standing rule

Platform drift responses are **never** absorbed silently into builds:
any SDK bump, engine swap, format hedge, or destination addition gets
its dated note in the register or the relevant spec — the same P10
change-control the corpus already runs. Drift handled quietly is how a
system stops matching its own documentation, and this corpus's value
*is* that match.
