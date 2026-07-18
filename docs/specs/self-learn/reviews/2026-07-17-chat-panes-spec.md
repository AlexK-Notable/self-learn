# Review record — Y-13 chat-panes spec amendment (feedback round 1, item 7)

**Cycle:** spec-first gate for G-3's second act (agentic chat panes
with verb proposals). Amendment set drafted from the ratified design
brief (`feedback/2026-07-17-chat-panes-design-brief.md`) → blind spec
review → fold → delta re-check. Build (10 U12) remains its own gated
cycle; this record closes only the SPEC gate.

**Commits:** `e6a3da3` (amendment set: 07 §3 note, 09 §1/§2.2/§2.4/
§4.2/§4.3 + new §4.5 + §11 Y-13, 10 §1/§2/§3 U12/§4) → `a092159`
(rework fold F1–F9) → the R1–R4 delta-residual fold (this commit).

**Reviewer setup:** fresh blind spec reviewer (no authorship stake,
`reviews/` withheld), with read access to the full corpus, the live
UI source, and the installed SDK for empirical grounding. Same
reviewer ran the delta.

## Round 1 — NEEDS REWORK (1 BLOCKER, 3 MAJOR, 4 MINOR, 1 NIT)

- **F1 BLOCKER** — the draft's proposals rendered directly as armed
  bars via SSE swap; because the standing arm machine is stateless
  server-side (armed state lives in the client DOM), a proposal
  could replace a HUMAN-armed bar between the human's read and their
  Enter — the agent's verb riding a keystroke meant for something
  else. The draft's own refuse-not-replace rationale named this
  hazard and failed to close it from the human-armed side.
- **F2 MAJOR** — the proposal's server-side state had no home or
  lifecycle; the refuse lock could wedge permanently (session dies
  with a proposal pending → every future proposal refused, no bar
  anywhere).
- **F3 MAJOR** — two `[data-armed]` bars could coexist on Bucket;
  Enter targeted whichever sat first in the DOM.
- **F4 MAJOR** — fixtures covered the mechanism's happy geometry,
  not its races.
- F5–F9 MINOR/NIT: 09↔10 conflict on who authors
  `pane-surface-model.md` (U5 vs U12); bucket-session fate on
  confirm unstated; "never echoed agent prose" overstated (the note
  IS agent prose); `pane_proposal` SSE unscoped; dest-validation
  boundary for parameterized enum forms unstated.

## The rework (a092159) — the mechanism changed, not just the text

Root cause of F1/F2/F3: the draft assumed an armed-state authority
the server does not hold. The fold made the proposal path
structurally race-free rather than suppression-guarded:

- **Proposals render WAITING, never armed.** The human's `y` arms
  the waiting bar through the standard armed contract; Enter
  confirms; Enter never acts on a waiting bar. The agent's proposal
  gets exactly the human's own two-keystroke consent path — never a
  shorter one. Even a missed client suppression cannot redirect a
  pending Enter, because nothing ever swaps in armed.
- **Server-held single proposal slot** (first server-held arm-state
  precursor, named honestly as a departure from the stateless
  machine) with an exhaustive clear-set: confirm · dismiss · session
  end for any reason · record leaves pending · restart. Navigation
  re-renders, never clears.
- **Single-armed-bar-per-document** promoted to a tested invariant.
- F4's race fixtures (collision, dual-armed, slot lifecycle,
  navigation survival, stale-confirm) pinned into T-A; T-B grew
  rows 6–8 (callback routing proof, closed-list refusal, bucket
  zero-write denial).

## Delta — SOUND (4 residual MINOR, folded same day)

Reviewer re-ran the F1 attack against the reworked text and confirmed
consent integrity now holds by construction. Residuals, all folded:
**R1** T-B(6) still said "armed bar renders" (→ waiting, not
`[data-armed]`); **R2** the 10 §1 SSE-protocol row missed the scope
gate + suppression belt the proposal-tool row carried; **R3** 07 §3's
refinement note still said the tool renders the standing arm/confirm
bar; **R4** the F7 fix's display-only note cap would let the human
confirm note text they only partially read — recut as an intake cap
(handler refuses >200 chars; displayed note byte-identical to the
executed `--note`).

## Disposition

Spec gate CLOSED — Y-13 is ratified corpus text. Build authority:
10 §3 U12 (depends U5, U6 — both shipped), with T-A's Y-13 block and
T-B(6)–(8) as its acceptance floor. The build cycle gets its own
blind CODE review per standing discipline.

**Verification honesty note:** the SDK mechanism
(`tool`/`create_sdk_mcp_server`/`mcp_servers`) was verified present
on installed 0.2.121 at drafting; whether an in-process MCP tool call
routes through the `can_use_tool` callback (footgun-B lineage) is
deliberately NOT claimed — T-B(6) proves or refutes it live at build,
and a failure pivots down the §4.3 ladder, never loosens the surface.
