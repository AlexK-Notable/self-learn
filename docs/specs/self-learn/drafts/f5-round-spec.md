# DRAFT — Feedback round 5 build spec: U19 (small set) + U20 (guided commit-first) + U21 (post-iterate summary)

**Status: DRAFT 2026-07-19. Build-grade; unratified.** Source:
`feedback/2026-07-19-ui-feedback-05.md` (nine items, investigated
same day, file:line evidence). Owns the CONFIRMED fixes and the two
NOT-CONFIRMED items' UX gap. Does NOT own F5-8 persistence (its own
draft: `pane-transcript-persistence-spec.md`). Proposed final homes:
three U-rows in 10 §3 (U19/U20/U21) + one 08 §1 line for U20's verb,
authored at build. All anchors below are from the 2026-07-19
investigation against master 70e17ae; re-verify before editing.

## 1. U19 — the small set (one builder, UI package only)

### 1.1 F5-3 — help-overlay key containment (severest; build first)

Today: the `?` overlay is non-modal with no Escape handler; Escape
falls through `onKeyDown` (app.js:169-214) to the keymap `up` entry →
`goUp()` (app.js:163-167) → `clickAction("interrupt")` when a pane
turn is in flight — **an open help window silently cancels a running
Iterate**. The overlay's own text (help_overlay.html:14) promises
"Press `?` again, or any other key, to dismiss" and only `?` works.

Pinned behavior (implements the overlay's own promise):
- While the overlay is visible (**the signal is `overlay.hidden`,
  app.js:66** — the help_overlay.html file comment claiming a
  `visible` class is stale and is corrected as part of this item),
  **any plain keydown closes the overlay and stops** — no key reaches
  the armed-bar branch, the KEYMAP dispatch, or `goUp()`. One
  keypress = dismiss, nothing else.
- Ordering (gate n11): the dismiss check runs **after** the existing
  text-input guard (app.js:170) and modifier-chord guard (:171) and
  **before** every dispatch branch — typing in a focused input and
  browser chords behave exactly as today; any plain key dismisses.
- `?` keeps its toggle semantics (open when hidden; close when shown —
  now just a special case of any-key-closes).
- MUST NOT introduce a focus trap or new modal machinery — visibility
  check + early return only.
- **Corpus amendment scope (gate M3 — wider than a §2.3 note).** The
  overlay doctrine is currently self-contradictory: 09 §1 (line ~98)
  pins *"a layer, not a modal — any action key acts immediately from
  it"* while help_overlay.html:14 promises any-key-dismisses. The
  build MUST amend BOTH statements to the new pinned behavior (the
  09 §1 line rewritten to "a layer, not a modal — any key dismisses
  it and does nothing else; keys act on the page only while the
  overlay is closed", the template file comment corrected), plus the
  one-line 07/09 §2.3 keymap-contract note. Leaving 09 line 98 as-is
  would invite a future "fix" back to the interrupt-eating behavior.

Tests (js-marked, FW-17 harness): overlay open + Escape → overlay
hidden AND no interrupt fired with a pane turn in flight (the exact
reported disaster, pinned as a negative); overlay open + `s` →
overlay hidden AND selection unmoved; `?` toggle regression; overlay
open + keypress while a text input is focused → input receives the
key, overlay stays (the n11 ordering pin).

### 1.2 F5-1/2 — silent no-op keys get feedback

Today both reported-dead keys work but no-op silently when gated:
`o` with a single-element cycle (user scope → `("claude-md",)`,
models.py:94-98) or when the action bar is replaced/armed; `b` on a
record without `## Episode brief` (models.py:1020-1044).

Pinned behavior: a **transient, non-blocking hint line** — Y-9 plain
words, auto-clears on next keypress or ~3s. **This transient element
is NEW client behavior (gate m5):** the existing notice register
(`showBanner`, app.js:615-622) prepends a persistent banner and has
no auto-clear; the hint is a distinct lightweight element (or an
explicit transient mode added to showBanner) — the spec names it new
rather than pretending to ride the register.

The two cases and their detection (gate M1 — the server signals the
no-op; the client never derives it):
- **`o` with nowhere to cycle** (single-element cycle, user scope →
  `("claude-md",)`, models.py:94-98): the cycle button ALWAYS renders
  today (action_bar.html:101-106), so a clickAction-false mechanism
  cannot see this case. Pinned: when the record's cycle has exactly
  one element, the server renders the cycle control **without
  `data-key-action`** and **with
  `data-noop-hint="only one destination fits this lesson's scope"`**;
  on clickAction-false the dispatch queries
  **`[data-noop-hint][data-noop-action="<action>"]`** — the control
  also carries `data-noop-action="cycle_destination"` so the lookup
  is action-keyed from day one (gate R4: a bare global
  `[data-noop-hint]` query would break the "next gated key joins by
  adding an attribute" claim the moment a second such control
  exists). (Display stays as today otherwise.)
- **`b` with no brief**: the summary element is genuinely absent →
  `clickAction` returns false → hint lookup per action:
  *"no episode brief on this record"*.
- Mechanism: ONE dispatch-site hook handling both signals
  (absent-target per-action message; present-but-noop via
  `data-noop-hint`) — the next gated key joins by adding a message
  or an attribute, never a mechanism.
- MUST NOT hint when the key is consumed by the armed-bar branch or
  when a pane-proposal bar has replaced the action bar (both are
  visibly modal contexts; the replaced-bar case gets NO scope
  message — it would be wrong there, gate M1).

Tests: js-marked — `o` on a user-scope record shows the scope hint
and the destination text is unchanged (via the `data-noop-hint`
path); `o` on a proposal-bar-replaced record shows NO hint; `b` on a
briefless record shows the brief hint; hint clears on next key; NO
hint when a bar is armed and `o` is pressed.

### 1.3 F5-4 — collapse the raw-YAML Change fallback

Today the Change section (detail.html:70-100) renders always-open;
the `proposal-yaml` kind (models.py:1095-1098) duplicates in raw form
what the card sections above render humanly. The `diff` and `hook`
kinds are genuinely informative previews and STAY always-open.

Pinned: `kind == "proposal-yaml"` renders inside a default-collapsed
`<details>` (episode-brief pattern), summary in plain words (e.g.
*"The full proposal, as stored (raw)"*). No keymap key is allocated
(mouse/Enter-on-summary only — the key budget stays flat); the
"compilers regenerate from the record at apply time" advisory line
stays visible OUTSIDE the disclosure.

Tests: proposal-yaml renders collapsed with the advisory outside;
diff kind still renders open (regression); no new top-level region.

### 1.4 F5-6 — humanized timestamps everywhere a human reads them

Today raw ISO-8601 at: Detail finding line (models.py:1048-1060
"created 2026-07-19T19:19:16Z"), Front miner block last-run + per-run
`ts` (index.html ~:121,:126), follow-ups `unblocks_on` (index.html:95),
report.html:66 (`unblocks_on`, `routed_at`).

Pinned: ONE shared Jinja filter `humanize_ts` (UI package), rendering
relative plain words — *"just now"* (<90s), *"N minutes ago"*,
*"N hours ago"*, *"yesterday"*, *"N days ago"*, *"Mon DD"* (≥14 days,
current year), *"Mon DD, YYYY"* (older) — with the full ISO string in
the element's `title` attribute (hover reveals the precise moment).
Applied at every raw site above. **Detail-site prerequisite (gate
M4):** the "created …Z" stamp is baked into the pre-joined
`provenance_text` string (`_build_finding` models.py:1060), which no
Jinja filter can reach — the build MUST drop the raw stamp from
`provenance_text` and render the already-existing discrete
`FindingRegion.created_at` field (models.py:1059) as its own
filtered element on that line. Server-rendered only (no client clock
math — the server's now() is the reference; a stale relative label
refreshes with the page, acceptable). Parse failures render the
original string verbatim (never crash, never blank). The existing
humanized precedents (`age_days` counts, "Routed Nd ago…"
models.py:484-490) are left as-is (already plain words).

Tests: filter unit table (each bucket boundary + garbage input →
verbatim passthrough); one render test per site asserting no bare
`T…Z` ISO pattern remains in the visible text (title attr exempt).

### 1.5 F5-9 — destination glosses on Detail

Today `_GROUP_LABELS` (models.py:164-172: skill-md→"Skill doc",
claude-md→"Project instructions", reference→"Reference file",
new-skill→"New skill", hook→"Guard hook") is used ONLY by Bucket
group headers; the Detail action bar prints `Destination: skill-md
(o)` (action_bar.html:104) and the Why region prints the raw enums
(detail.html:107-109).

Pinned: Detail reuses `_GROUP_LABELS` — action bar renders
*"Destination: Skill doc (o)"* with the enum demoted to the `title`
attribute (hover shows `skill-md`); the Why region's "Suggested
destination" and "Alternates" lines gloss every value the same way.
The enum stays the machine value in forms/argv (display-only change).
Single source: the existing map — **no second label map may be
created** (a builder adding one breaks the single-source rule; test
below guards it).

Tests: Detail action bar + Why region show the glosses for each enum
(param table); the argv/hidden form fields still carry raw enums
(regression); a source assertion that the labels render from
`_GROUP_LABELS` (e.g. monkeypatched map changes the render).

## 2. U20 — F5-5 guided commit-first (ruled 2026-07-19)

**The ruling:** the dirty-target refusal stays fully intact (S-10
family; chezmoi.py:99-116 `preflight_user_scope`, gitops.py:542-546
`paths_dirty` — refuse before any edit, no --force, no override).
The UI gains a **guided path**: commit the TARGET repo's own pending
changes first (their commit, separate from ours), then retry.

### 2.1 The verb (CLI package; 08 §1 line authored at build)

New verb `self-learn host commit-drift <path-or-scope-arg>` (exact
name/arg shape settled at build against the existing host verb
family; MUST route through the same target-resolution the refusal
used):
- Preconditions: the target resolves; the target's repo IS dirty
  (clean repo → clean refusal *"nothing to commit — the target repo
  is clean"*, exit 64; never an empty commit).
- **Dirty-vs-drift boundary (gate M2 — the load-bearing correction).**
  `preflight_user_scope` refuses on TWO distinct conditions sharing
  an advice tail (chezmoi.py:57-60): **pre-existing chezmoi DRIFT**
  (:109-111 — destination differs from source state; fixed by
  `chezmoi re-add`/`apply`, which a commit cannot fix) and a **dirty
  dotfiles repo** (:115-116 — uncommitted source-state changes; fixed
  by a commit). This verb serves the DIRTY case ONLY. It MUST refuse
  the drift case with a plain explanation (*"the dotfiles file
  differs from what chezmoi manages — run chezmoi re-add or apply
  first; a commit can't fix drift"*), and the UI button (§2.2) MUST
  NOT appear on a drift refusal. Whether drift deserves its own
  guided action is a possible follow-up, deliberately out of scope
  (the ruling covered uncommitted changes).
- Behavior (dirty case): scope per leg —
  - **gitops leg** (skill/project targets): the refusal
    (`paths_dirty`, gitops.py:542-546) is target-path-scoped, so the
    add is too: `git add -- <target paths>` + one commit. Never
    `add -A` (gate m8 — repo-wide add would sweep unrelated pending
    work into the pinned-subject commit).
  - **chezmoi leg** (user scope): the dirty check is repo-wide, so
    `chezmoi git -- add -A` + commit matches its own read path.
  One commit with the pinned subject
  `chore: commit drift before self-learn route`, NO other side
  effects — never a push, never touching the ledger, never our
  compile. The commit is theirs, in their repo, of their changes.
- **`--dry-run --json` mode (part of THIS verb, gate R3):** reports
  `{repo, files: […]}` for the would-be commit and writes nothing —
  the §2.2 armed display's only data source. Same preconditions and
  refusals (incl. the drift refusal) as the real run.
- **Message constants first (gate R1):** both dirty-refusal messages
  are inline f-strings today (chezmoi.py:116; the `DirtyTargetError`
  raise at verbs.py:304). The build FIRST extracts them into shared
  named constants referenced by the raise sites, the UI marker
  match, AND the tests — no hand-copied substrings anywhere. The
  pinned stable substrings: chezmoi dirty
  `"dotfiles repo has uncommitted changes"` (:116); gitops dirty
  `"has unrelated uncommitted changes"` (verbs.py:304). The drift
  message (chezmoi.py:110) contains neither — the boundary is
  string-detectable by construction.
- Output: one plain line naming the repo, the file count, and the
  short sha. Secret scan does NOT run (we are not authoring content —
  we are committing what already sits in THEIR working tree; the scan
  gate exists for content WE compose. State this in the verb docs.)
- The verb REFUSES paths outside registered hosts / the dotfiles
  source (no arbitrary-repo commit surface; the resolution reuse
  guarantees this).

### 2.2 The UI leg

When a route confirm fails AND the stderr matches the DIRTY-specific
refusal clauses ONLY — the pinned markers are the extracted
constants of §2.1 (chezmoi dirty
`"dotfiles repo has uncommitted changes"`, chezmoi.py:116; gitops
dirty `"has unrelated uncommitted changes"`, verbs.py:304), **never**
the shared advice tail and **never** the drift clause (:110), which
gets no button (gate M2) — the error strip gains ONE action button:
*"Commit that repo's changes, then retry"*. Behavior:
- **Armed, two-step (consent posture):** first tap arms, showing the
  repo path and the dirty file list from **the new verb's own
  `--dry-run --json` mode** (gate m6 — no other dirty-list source
  exists today; the dry-run is part of §2.1's verb, reporting
  `{repo, files: […]}` and writing nothing). Server derives nothing;
  the CLI reports the list. Enter/confirm runs the verb via the
  standard runner seam; on success the strip swaps to
  *"Committed (<sha>). Retrying…"* and re-fires the original route
  confirm automatically (one retry, the same argv; a second dirty
  refusal renders plainly, no loop).
- Failure of the commit verb renders its stderr verbatim in the same
  strip (standard error leg).
- This composes INSIDE the existing error-strip/action-bar machinery
  (no new region, O-9).

Tests: CLI — dirty repo committed with the pinned subject + count
(gitops leg: add scoped to the target paths — an unrelated dirty
file in the same repo is NOT in the commit); clean repo → exit 64
refusal, no commit; **drift-state dotfiles → exit 64 with the
re-add/apply explanation, NO commit** (gate M2); dotfiles dirty path
goes through chezmoi git; out-of-scope path refused; `--dry-run
--json` lists files and writes nothing. UI — refusal renders the
button only for the dirty-marker stderr; **the drift refusal renders
NO button** (gate M2); a generic failure renders no button; **the
marker-match test imports the actual message constants from
chezmoi.py/gitops** (gate n12 — a hand-copied string would let the
marker and message drift apart undetected); arm shows the dry-run
file list; confirm → verb argv + auto-retry of the original route
argv (FakeRunner sequence assertion); commit-verb failure renders
verbatim. js-marked: the armed flow survives the refresh push (the
Y-16 family; reuse the existing defer legs).

## 3. U21 — F5-7 post-iterate change summary

Today pane completion renders transcript + status/$cost/turns footer
(pane.html:47-52); FileChanged events only fire `record:<id>`
refreshes (pane.py:914-917); nothing consolidates what a turn did.

Pinned: the result footer gains one plain-words line built from two
named sources (gate m7 — stated precisely, both legitimate):
- **File facts from the drain's own events**: the set of
  `FileChanged.path` targets (engine/base.py:73), dedup, classified
  relative to the record — *the lesson itself* / *its proposal* /
  other path shown shortened. No diffing, no file reads, no git —
  events the drain already receives (09 §2.1 holds).
- **Proposal fact — two signals composed (gate R5, current-turn
  attribution):** the line appends *"…and proposed: route to Skill
  doc"* (glosses per F5-9's map) iff BOTH hold at `pane_result`:
  (a) THIS turn's drain saw a `propose_verb` ToolUse (gates
  *whether* — a prior turn's still-waiting proposal never
  misattributes to this turn), AND (b) a WAITING proposal for this
  record exists in the slot (supplies verb+destination for the
  gloss, and excludes refused/rejected proposals — the slot is the
  consent-gate truth). ToolUse alone or slot alone is insufficient.
  Edge pin (delta-2 residual): (b) additionally requires the slot's
  CURRENT proposal to have been placed THIS turn (capture its
  identity when this turn's propose_verb ToolUse lands and compare
  at pane_result) — otherwise a this-turn propose refused by
  slot-occupancy would misattribute the PRIOR turn's still-waiting
  proposal to this turn's summary.
Examples: *"This turn changed: the proposal and the lesson text."* /
*"This turn changed: nothing."* The line is part of the SAME footer
block, persists in the snapshot exactly like the footer does.

Tests: unit — drain accumulation (record-file event → "the lesson
text"; proposal sibling → "the proposal"; other path → shortened;
none → "nothing"); render — footer line present after pane_result,
present again on snapshot re-render (navigation-return regression);
proposal-made variant names the glossed verb.

## 4. Sequencing, ownership, non-goals

- U19 and U21 are UI-package-only; U20 spans cli (verb) + ui (strip
  leg). U19/U20/U21 are parallel-buildable (disjoint files except
  app.js: U19 owns the onKeyDown/hint edits; U21 does not touch
  app.js — the footer line is server-rendered; U20's js is none —
  the strip reuses existing armed machinery).
- Register: U19/U20/U21 rows in 10 §3 authored at build; U20 adds an
  08 §1 substrate line for the verb. No 09 §11 Y-numbers minted (no
  new invariant class; the F5-3 containment amends the keymap
  contract note in 07/09 §2.3 where the overlay is specified — one
  line, authored at build).
- **O-9 compliance, cited correctly (gate m9):** O-9 is the four
  composition principles that bind all new UI work (compose don't
  stack; frame the page; progressive disclosure of chrome; one
  rhythm). This round: every addition composes inside an existing
  element (hint line in the existing strip area, commit button in
  the existing error strip, summary line in the existing footer,
  F5-4 behind a disclosure = progressive disclosure applied); no new
  regions, no new chrome rhythm; the F5-4 collapse actively REDUCES
  stacked weight on Detail.
- Non-goals: NO override/force path for dirty targets (ruled out);
  no drift-fixing action (M2 boundary — commit can't fix drift; a
  guided re-add is a possible later item); no client-side clock
  math; no second label map; no new keymap keys; no new page
  regions; no pane persistence (owned by
  `pane-transcript-persistence-spec.md`); no autosync/push from the
  U20 verb, ever.
- DoD: sandbox live walk — the overlay-Escape negative with a real
  in-flight Iterate; a real dirty dotfiles-style route refusal →
  guided commit → auto-retry landing the route; humanized stamps
  visible on Front/Detail/report; a post-iterate summary line after
  a real pane turn. Logged in `fixtures/ui-trials.md`.
