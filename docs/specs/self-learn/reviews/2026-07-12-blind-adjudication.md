# 2026-07-12 blind adjudication — the material items from the refinement pass

*Two blind reviewers (Opus 4.8), given the corpus WITHOUT
`2026-07-11-refinement-review.md` or the gen-1 archive, after the
orchestrator's four fixes (sentinel honesty/TTL, E-16 compose clause,
claim-marker declaration, bulk-acknowledge status mapping) were applied.
Reviewer 1: adjudicate reopened S-8/S-12 + schema coherence sweep.
Reviewer 2: red-team the full multi-machine writer matrix against the real
`bin/claude-skills-sync`/`-watch` scripts. All dispositions below are folded
into the corpus.*

## Reviewer 1 — schema lifecycle (verdict: ADOPT, 3 MAJOR coherence findings)

- **S-8/S-12 freeze-at-routing: ADOPT.** The old capture-freeze contradicted
  three settled parts of the design (Edit-in-Discuss, the cluster mutation,
  the evidence note); pending is inert (P1) so nothing downstream trusts
  pre-routing content; git versions drafts. **Rider adopted:** the secret
  scan must run on *every* record-body write (review edits included), since
  freeze-at-routing legalizes edits that autosync publishes pre-review.
- **MAJOR:** `superseded_by: canon` was load-bearing but never formally
  defined → now defined in `02` §2 (`∈ {null, id, canon}`, status/dir/
  no-routing-linkage stated).
- **MAJOR:** the hand-weave graduation had no owning mechanism → new
  `self-learn graduate <id>` verb (ha-note's `--promoted` precedent).
- **MAJOR:** the routed-and-reverted metric conflated corrective
  supersession (bad lesson) with canon graduation (good outcome) → metric
  renamed **routed-and-corrected**, canon-graduations excluded.
- MINORs folded: rejection provenance = git (stated as deliberate);
  status-vs-directory note; deferred-status note; `teach --route` writes
  straight to `resolved/`; `source: session` forward-declared; random ids.

## Reviewer 2 — storage/concurrency red-team (verdict: build M1 after 4 fixes)

- **MAJOR (M1):** review commits were never pushed — `claude-skills-sync`'s
  clean-tree branch fetches/ff-merges but has no `git push`, and the
  sentinel release in `~/.cache` fires no inotify event → routed canon sat
  unpublished. **Fix folded: review self-pushes.**
- **MAJOR (M1):** "surgical `git revert` per lesson" is unsound against
  whole-section-regenerating compilers (reverting commit N after N+1
  conflicts or leaves the line) → **correction = supersede + recompile**;
  per-lesson commits kept for attribution; record→commit link moved to the
  commit *message* (a commit's own hash can't live in a file it contains).
- **MAJOR (design):** cluster merges were the one worker mutation of synced
  records, dragging in the designated-host + claim-marker machinery and
  weakening the P1/P9 story. **Fix folded: merges-as-proposals** — the
  worker emits `proposals/merge-*.yaml`; the human collapses at review. The
  worker is now fully append-only; designated host and claim marker deleted;
  the mid-review merge race and the claim-marker fragility findings are
  dissolved rather than mitigated.
- **MAJOR/MINOR (M1):** fixed-TTL-from-start would let a >2 h live review
  get its tree committed under it → **sentinel is heartbeated**; expiry
  means dead. Sentinel documented as per-machine; one-review-host-at-a-time
  stated as operating discipline.
- **MAJOR (narrow):** `chezmoi re-add` is same-machine-only → the user-scope
  compiler also commits+pushes the dotfiles repo (E-17 extended).
- Honesty fixes: "race-free by construction" scoped to the ledger (shared
  compile targets degrade to autosync's safe halt); preview-vs-applied
  divergence noted on the card; random-id requirement stated.

## Process note

Both material items settled through blind review per ground rule 2; the
register (S-2/S-5/S-6/S-7/S-8/S-12) carries dated re-amendment notes. This
memo, like its predecessor, must be withheld from any future blind reviewer.
