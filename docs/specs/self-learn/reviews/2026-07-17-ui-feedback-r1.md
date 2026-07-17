# Review record — feedback round 1, batches A+B (2026-07-17)

Scope: `git diff master...ui-feedback-r1` (279c001 feat + c09fbd9 footer
dedupe), implementing feedback items 1/2/3/4/6/8 of
`feedback/2026-07-17-ui-feedback-01.md`. Blind adversarial review by an
independent Opus agent (no access to this directory), then a scoped
delta re-check by the same reviewer on the fold commit.

## Pass 1 — adversarial (VERDICT: NOT CLEAN — no MAJOR)

1. **MINOR** — install.sh's new launcher block ran `mkdir -p` outside
   the `run()` guard: `--dry-run` created the icon directory tree
   (extends a pre-existing top-level idiom, but the block's own dirs
   were provably absent on this host).
2. **MINOR** — the Deferred count keys by bucket NAME only; two
   same-named buckets in different scopes would each show the combined
   count. Forced by the data (`list --json` items carry no scope field)
   and consistent with the app's systemic name-uniqueness assumption
   (`next_record_url`, Bucket-page filtering).
3. **NIT** — `.desktop` declared two freedesktop main categories
   (validator hint: may appear twice in menus).
4. **NIT** — sed `|` delimiter / eval quoting break only on pathological
   `$HOME` values; repo-wide idiom; accepted as-is.
5. **NIT** — on an ACTIVE pane the footer still showed `Iterate (i)`
   (no button exists then — harmless no-op).

Verified clean in the same pass: CSP (no new inline style/script; sort
logic in app.js, footer filter pure CSS); autoescape/no `|safe`; Y-9
tooltip register; Y-10 (sort direction carried by ↑/↓ glyphs, accent is
blue); single-source keymap held; j/k + sort composition (appendChild
preserves `.selected` and scroll-margin; `rows()` reads live DOM order;
no NaN paths — every numeric cell carries an integer sort value incl.
the −1 null-oldest sentinel); delegation survives htmx swaps; SSE
reload merely resets sort state; no client-side arm state introduced;
SVG well-formed; help-key dedupe rule wins by order at equal
specificity; every template names its `data-page`.

## Fold (c29e86e)

- mkdir wrapped in `run` — `--dry-run` re-verified write-free.
- MINOR-2 resolved as a documented limitation (honest comment naming
  the failure and the real fix's home: an 08 §1 substrate edit adding
  scope to list items).
- `Categories=Utility;` only.
- New CSS rule hides the iterate footer key while a live pane exists
  (specificity (0,4,1) beats the (0,3,1) show rule; inert without a
  pane — idle wrappers carry no `data-pane-state`).

## Pass 2 — delta re-check (DELTA VERDICT: CLEAN)

All four folds verified with proof; the delta is exactly the four
files/14 insertions; suite 492 green.

## Empirical checks run during the pass (orchestrator)

- Playwright against a seeded sandbox ledger (dev server :7358,
  redirected XDG dirs): sort asc/desc on Pending verified against cell
  values; footer contents captured per page — Front `j k Enter Esc ?`,
  Bucket adds the quad + o/n (no i), Detail drops j/k (has i), Report
  `Esc ?` only; `:has()` reactivity proven live (r/q appear the moment
  a `data-pane-state` node enters the DOM, no reload); Deferred column
  shows the sandbox's one deferred record; both themes screenshotted.
- `desktop-file-validate` exit 0 on the generated entry.

Gallery: `~/Pictures/self-learn-ui/` (r1-* files added by this pass).
