# UI walk instrument

Dev tooling for having an agent drive the real G-3 surface in a browser
and document **what using it was like**. Not a test suite: no assertions,
no pass/fail, no CI gate. Its output is a field report; triage into
defects is a separate human step.

Findings of record live in `docs/specs/self-learn/fixtures/ui-walks.md`.

## Why this is not a test suite

An LLM verdict cannot be mutation-verified, and this project's discipline
rests on mutation verification. So the loop is a **discovery instrument**
whose deliverable is observations and, downstream, new deterministic
tests — never a gate that can fail a build on a prose judgement.

## The three pieces

| File | Does |
|---|---|
| `sandbox_ui.py` | Serves the **real** app against a seeded throwaway ledger, with containment gated before the browser can reach it |
| `probe.js` | Enumerates reachable surfaces; reports perceptual deltas |
| `WALK.md` | The protocol the walking agent follows |

## Running it

```bash
cd plugins/self-learn/ui
uv run --project . python tools/sandbox_ui.py selftest   # prove the gate gates
uv run --project . python tools/sandbox_ui.py up         # seed + serve
uv run --project . python tools/sandbox_ui.py reset      # rewind to seeded state
uv run --project . python tools/sandbox_ui.py up --help  # list world states
```

## World states

The corpus varies what a **record** looks like. `--world` varies the
**world it resolves into**, which is where most of this product's
refusals live — and which was a constant until 2026-07-26.

```bash
up --world dirty-target            # route target has uncommitted changes
up --world analysed,dirty-target   # ...and records carry proposals, so the
                                   # refusal is reached the way a human does
```

Composable, comma-separated, `clean` by default so the normal path stays
normal. Applied **after seeding and before the snapshot**, so `reset`
rewinds *to* the world — a world applied afterwards evaporates on first
reset and gets rediscovered as "restore is broken". An existing sandbox
keeps the world it was seeded with; `--fresh` to change worlds.

Worlds are deliberately **not** in `KNOWN_DIVERGENCES`. A divergence is a
containment artifact a walker must be told to ignore; a dirty repo is a
state real users are in constantly, and a walker should be allowed to
discover it.

Two things bit while building this, both worth knowing:

- **World states are gated behind record states.** Dirtying the repo did
  not reach the dirty-target refusal — `route` raises `NoProposalError`
  first, because the seed leaves every record unanalysed. Hence
  `analysed`, and hence composition.
- **`commit_all` is `git add -A`.** Composing two worlds, the second
  one's commit absorbed the first one's uncommitted edit and the sandbox
  came up clean while announcing it was dirty. Worlds use `commit_paths`.
  Verify a world with `git -C <state>/live/host-repo status`, not with
  the startup banner.

`up` prints a deep-link URL with a bearer token, and the **known sandbox
divergences** — behaviours that differ from a real install by
construction. Pass those to the walker or it will faithfully file
containment measures as product defects.

Read the token from `<state>/live/runtime/self-learn/ui-token`, not from
an old log: it is minted per server start.

## Containment

`assert_isolated()` resolves every write location through the
**production** resolvers (never re-derived paths) and refuses to start
unless all land inside the sandbox. `selftest` is the negative control —
it strips the redirects in a child and requires the gate to fail, and to
fail for the right reason.

Six env redirects, of which **`HOME` matters most**:

    HOME, SELF_LEARN_HOME, XDG_CACHE_HOME, XDG_RUNTIME_DIR,
    SELF_LEARN_CLAUDE_DIR, SELF_LEARN_TRANSCRIPTS_DIR

The first version redirected only the five named vars and was still
unsafe. Those cover where the *server's own infrastructure* writes; they
say nothing about where the **verbs it spawns** write.
`self_learn.verbs.DEFAULT_USER_CLAUDE_MD` is the literal
`Path("~/.claude/CLAUDE.md")`, expanded at use, with no flag and no env
var to override — so a user-scope `route` reached the operator's real
global instructions file. `SELF_LEARN_CLAUDE_DIR` does not help; it
governs only hook symlinks and `settings.json`.

Redirecting `HOME` contains that, and everything else `~`-relative:
verified 2026-07-26 by running the escaping command and watching it land
inside the sandbox. It also contains the **pane/SDK path**, which spawns
a real Claude Code child that writes an entire `~/.claude` tree
(`.claude.json`, `sessions/`, `backups/`, `projects/`). With `HOME`
redirected that child finds no credentials, fails at auth, and reaches no
model — so pane sessions show "Not logged in" and cost nothing.

`XDG_RUNTIME_DIR` is the easy one to miss: `write_token_file` writes
`$XDG_RUNTIME_DIR/self-learn/ui-token`, so an unredirected start would
overwrite the bearer token of a **real** `self-learn-ui` and lock the
operator out of it.

## The probe

`window.__uiProbe` after injection (Playwright's
`addInitScript({path})` reads the file itself and re-injects on every
navigation — one call, no per-page paste cost):

- `surfaces()` — everything actable, each with a unique `selector`, plus
  `perceptible`, `container`, `keys`, `disabled`. Act on the leaf, not
  the `container`: clicking a `<form>` wrapper is a silent no-op. Also
  returns `coverage` (`visible` / `offscreen` / `hidden`) and `page`
  (scroll height vs viewport).
- `sweep()` — `surfaces({sweep: true})`: scrolls the page, measures at
  each position, restores the scroll exactly. Off-screen surfaces it
  actually saw get `scroll_reachable: true`. Reachability is **measured,
  never predicted** — without a sweep the field is simply absent.
- `digest({run})` — the **delta** since the last call. Nothing changed →
  near-zero bytes, so cost tracks *interesting* surfaces, not surfaces.
  Carries `unseen_offscreen` / `unseen_occluded` when meaningful nodes
  were skipped because they could not be seen; both are omitted when
  zero, which is what keeps a quiet step cheap.
- `baseline(run)` — set a fresh comparison point.

Always pass a `run` id that changes when the server's data does. Session
storage survives a reseed on the same origin; without it, the first
digest of a new run diffs against a ledger that no longer exists (110
phantom changes, measured).

Everything is gated on **perceptibility**, not DOM presence: effective
opacity through ancestors, occlusion via `elementFromPoint`, in-viewport,
non-zero box. The accessibility tree reports an element at `opacity: 0`
as present and `is_visible()` returns true for it — both measured on this
app's own applying-strip.

## Known limits

- **Below-the-fold surfaces used to be silently absent.** `perceptible()`
  requires in-viewport — correctly, since that is what a person can see —
  so the shortfall was never stated and a walker believed it had covered
  a 7-record bucket having seen 3. *Fixed* by reporting the shortfall
  rather than loosening the predicate: `coverage.offscreen`,
  `sweep()`, and `unseen_offscreen` on the digest. Verified against the
  live sandbox: on `/` at 900x380 four surface kinds are off-screen and
  a sweep reaches all four, among them the MINER **"Force run"** button
  a walk had already filed a bug against; the bucket page yields
  `Retry (r)` and `Close (q)`, the user bucket an entire
  `Open bucket chat (p)`. Same page, viewport as the only variable:
  1600px tall → no `unseen_offscreen`, 500px → 67.
- Screenshots: passing `filename` **suppresses the inline image** and
  returns a path. That is the lever that keeps pixels out of context —
  and the reason a walker that names its files sees nothing. Omit
  `filename` when you actually need to look.
- Screenshot paths must sit inside the browser tool's workspace root;
  `.playwright-mcp/` (gitignored) works, `/tmp` may be rejected.
- The pane path is contained but **unaudited when authenticated**. A
  credentialed run would make the charter's write-gating load-bearing
  rather than moot.
