# Forward theme E — Sync & multi-machine: visibility before mechanism

*Companion to `../14-forward-work-map.md` §2 (FW-20…FW-22). Dated
2026-07-18. The posture being protected: D3 (03 S-17) — no autosync
anywhere in product or ledger; verbs commit and attempt their own
push, failures are tolerated-and-kept ("PUSH FAILED — commit kept"),
the product repo pushes manually. Correct solo. The theme maps what
changes when a second machine captures regularly — and the answer is
deliberately **visibility first, mechanism only if visibility proves
insufficient**.*

## 1. The failure geometry, stated precisely

The ledger is one git repo with its own remote; every producer
(verbs, worker, miner) commits locally and push failures are
non-blocking by design. Solo-single-host, an unpushed ledger is
latency. Two capturing hosts make it **divergence**: both commit
locally against the same bucket files' *shared* surfaces — `meta.yaml`,
proposal sweeps, telemetry JSONL months, the index — and the second
push meets a non-fast-forward. The design already minimizes the blast
radius (record-per-file, random ids, append-only proposals: the
*capture* surfaces cannot collide by construction — 06 §2 invariant 1);
what can conflict is the shared periphery. So the realistic failure is
not lost lessons; it is a rejected push nobody notices, aging silently
— the invisible-backlog failure mode (E-3) wearing git clothes.

## 2. FW-20 — Push-state surfacing in the UI (build before the second host)

**What**: two visibility legs on the web surface —
(a) **push-fail surfacing**: a verb that reports "PUSH FAILED — commit
kept" currently prints it to a log the web user never reads; the
surface owes a persistent, dismissible notice (the Y-16 persistent-
error pattern is the template: survives the post-verb reload, plain
words per Y-9 — "Your decision was saved on this machine but could not
be synced. It will sync with the next successful decision, or run
self-learn push.");
(b) **an ahead/behind cue**: the Front page status strip (07 §5 already
sanctions a status strip) gains one line computed from the ledger
repo's tracking state — "N decisions on this machine not yet synced" /
"remote has changes not yet here" — counts only, no graphs, per the
counted-not-modeled doctrine.
**Why before the second host**: leg (a) is arguably owed *today* (the
backlog has carried it since G-3 ship); leg (b) is what turns
divergence from a forensic discovery into an ambient fact. Both are
narrow, spec-able now, and testable in sandbox with a bare remote.

## 3. FW-21 — The divergence playbook (document before mechanism)

**What**: a short operations doc (lives with FW-13's ops page;
runbook-linked from FW-26) answering, ahead of need: which ledger
surfaces can actually conflict (the shared-periphery list above, kept
current against 02); the resolution recipe per surface (telemetry
JSONL: union-by-line, order-irrelevant by design — 11's append-only
monthly files make this mechanical; `meta.yaml`: regenerate from
hosts.yaml, never hand-merge; proposals: newest-wins is safe because
proposals are disposable by contract; records: **should never
conflict** — if one does, stop and investigate, because a substance
conflict means two hosts edited the same pending record, which the
operating discipline says not to do); and the one habit that prevents
most of it — **pull before reviewing**, as *manual operator
discipline*: the playbook (and FW-26's runbook) says "fetch/ff the
ledger before starting a review session"; the ahead/behind cue (FW-20)
makes forgetting visible. Any *automatic* fetch — session-opener,
verb-wrapped, timed — is ledger auto-sync, which D3/S-17 excludes and
**FW-22 reserves for the user's ruling**; it is not scheduled here or
anywhere short of that ruling. *(Blind-review F1 fold, 2026-07-18: an
earlier draft scheduled an opener fetch/ff "when FW-20 builds" — struck
as a D3 weakening this map has no authority to make.)*
**Explicitly deferred mechanism**: no merge drivers, no CRDT-shaped
cleverness, no lockfiles. 06 §3.6's judgment stands at fleet-of-one-
user scale too: the forge (or here, the remote) serializes; the
periphery is either append-only or regenerable; discipline + a
playbook covers the residue until evidence says otherwise.

## 4. FW-22 — The D3 posture review (USER DECISION, trigger-gated)

**Trigger**: a second host captures *regularly* (not the occasional
laptop session — sustained parallel supply).
**The question that will actually be asked**: should the *ledger*
(never the product repo, never canon) regain a bounded auto-sync —
e.g., verbs pull-rebase before commit, or a timer that pushes the
ledger when clean? The arguments will be: for — the invisible-rejected-
push failure mode disappears; against — D3 was ratified precisely
because background git activity against shared state is how the
original autosync storms happened (E-8's lineage), and FW-20's
visibility may prove sufficient at near-zero risk.
**Why it is pre-registered here**: so the ruling is made *as a
decision* with the trade-offs on the table, not absorbed as a hotfix
the first time a push failure bites. Until then D3 stands unweakened,
and nothing in FW-20/21 touches it — visibility and documentation
only.

## 5. Interaction with packaging (theme C)

A packaged second-host install (FW-14) creates exactly the fleet this
theme prepares for — the two phases should land in the order this map
already implies: FW-20 before or with the packaging phase, FW-21's
playbook inside packaging's ops docs, FW-22 left un-fired until the
fleet is real.
