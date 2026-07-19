# Forward theme C — Packaging & distribution: the declared next phase

*Companion to `../14-forward-work-map.md` §2 (FW-10…FW-15). Dated
2026-07-18. Groundwork already banked: D2's product-repo extraction is
done (the product lives standalone at `~/repos/self-learn`), and the
SDK bundle-exclusion probe verified the big unknown — the Agent SDK
need not be bundled; a PATH-`claude` fallback works
(`../research/2026-07-18-sdk-bundle-exclusion.md`), making a slim
(~50 MB-class) distribution feasible. This doc maps what the phase
will actually contain, because "make it installable" hides six
distinct workstreams and two user decisions.*

## 1. What packaging is *for* (scope anchor)

Three honest motivations, in priority order: (a) **G-2's on-ramp** —
when a second host or user wants self-learn, install must be an act,
not surgery (06 stage 1); (b) **this user's own fleet** — a clean
install path beats the current repo-clone + install.sh + symlink
choreography even solo; (c) **discipline forcing-function** — a
version number that means something forces the release hygiene the
project currently doesn't need but will. Explicitly *not* a
motivation: distribution to strangers at scale. No registry publishing,
no marketing surface, no telemetry-of-installs. If that ever changes it
is a new conversation with new (privacy) stakes.

## 2. FW-10 — Distribution shape (USER DECISION, opens the phase)

The option space, mapped so the ruling is informed:

- **`uv tool install` from the git repo** (or a wheel). Cheapest to
  build (the CLI is already a uv project); upgrade = `uv tool upgrade`;
  requires uv + Python on the host — true of every current candidate
  host. The UI ships as an extra (`self-learn[ui]`) or a second tool.
- **Single-file binary** (PyInstaller/PyOxidizer-class). Heaviest to
  build and maintain (native deps, per-arch artifacts, slow CI);
  eliminates the Python prerequisite nobody currently lacks. The ~50 MB
  figure from the bundle-exclusion research describes this path.
- **Both, staged**: tool-install now, binary if/when a host without a
  Python toolchain actually appears (a G-2-flavored trigger: build on
  demonstrated need, not speculation).

**Orchestrator's lean, for the ruling**: staged. The binary's only
unique payoff is a prerequisite-free host, and no such host exists
today; meanwhile `uv tool install` exercises 90% of the same release
machinery (versioning, migrations, docs, preflights) at 10% of the
build cost. The Go port stays out of this option space entirely (O-8)
unless Python packaging *demonstrably fails*.

**Also inside this decision**: what the unit of distribution *is*. The
repo currently ships CLI + UI + miner units + companion scripts +
skills/commands (the plugin surface). Likely split: `self-learn` (CLI,
mandatory) / UI + service units (optional component) / the
skill+command plugin surface (stays a repo-managed install into
claude-skills — it is canon-adjacent, not binary-adjacent).

## 3. FW-11 — Versioning + release discipline

**Current state, honestly**: `plugin.json` says 0.1.0 and means
nothing; "v1.0/v1.1" are milestone labels living in prose; the real
version is "whatever master is." Fine solo; fatal with any installed
base.
**The work**: one version, single-sourced (pyproject; plugin.json and
`--version` read it); a CHANGELOG cut from the ship-round records
(the review records already contain every entry's substance); a tag
per release; a release checklist that runs the suites, pyright, the
verify-at-build ledger (FW-15), and `--selftest` against a sandbox
ledger before tagging. **Compatibility statement**: the ledger schema
(02) and the CLI's `--json` shapes become the *public* interface the
version number makes promises about — UI internals stay private.
**Non-goal**: semver theology. Two-tier is enough (breaking vs not),
where "breaking" means *ledger schema or JSON shapes*.

## 4. FW-12 — Ledger schema migrations (the sneaky-critical one)

**Why it outranks its apparent size**: today a schema change is "fix
the code and the files in one commit" — possible only because exactly
one ledger exists and its owner is the developer. The moment one other
ledger exists (second machine counts, packaged install counts), every
02 change needs: a schema-version marker in the ledger (bucket
`meta.yaml` or a ledger-root marker — to be spec'd), a migration
runner (`self-learn migrate`, idempotent, git-committing, refusing on
dirty), and a CLI posture on version mismatch (fail-closed with plain
words, per the Y-9 doctrine).
**Design constraint carried from the corpus**: migrations are
append-preserving — they may rewrite frontmatter shape, never lesson
substance (S-12's spirit extends to tooling).
**When**: machinery lands with the *first* packaged release, before an
installed base exists — retrofitting migration support onto unmarked
ledgers is exactly the archaeology this project exists to prevent.
**Cheap immediate step**: start stamping a schema-version now, ahead of
any migration runner; a marker that predates the need costs one line.

## 5. FW-13 — External-facing documentation

**The gap**: the corpus is written for its authors (registers,
Y-numbers, gate jargon); README's opening assumes the reader knows why
it exists. A packaged product needs: a quickstart (install → register a
host → teach one lesson → review it → see it in canon — under ten
minutes), an operations page (service units, miner timer, the
launcher, env vars — much exists in the repo README's G-3 section and
can be promoted), and a concepts page (the loop, the human gate, scopes
— 00-vision distilled to a page, jargon-free per Y-9's spirit).
**Boundary to keep**: the corpus stays the internal design record —
external docs *link* to it for the curious, never duplicate its
normative content (one source of truth; the docs describe, the corpus
governs).

## 6. FW-14 — Install/upgrade story + preflights

**Install**: whatever FW-10 rules, plus the parts install can't do —
`settings.json` hook registration and service enablement remain
documented manual acts (the corpus's standing posture: nothing
auto-registers into the user's Claude config or systemd; consent stays
with the human — same principle as H-3 and the S-10 activation gate).
A `self-learn doctor` preflight makes the manual steps checkable:
claude-on-PATH (the bundle-exclusion contingency's runtime half), git
version, uv presence, ledger reachable/initialized, hook registered or
not, service states. Doctor *reports*; it never fixes silently.
**Upgrade**: tool-upgrade (or binary swap) + `migrate` + a
post-upgrade `--selftest`; the release checklist (FW-11) rehearses
this path against a sandbox ledger every release.
**Uninstall** (the forgotten story): what remains (the ledger — always;
compiled canon sections — the user's, with markers), what leaves
(binaries, units, hooks), documented honestly.

## 7. FW-15 — SDK pin drift management

**The precedent**: the verify-at-build ledger (10 §1) exists because
one pre-verified assumption already failed to hold at build time — the
X-7 session-persistence contingency fired on the SDK 0.2.121 run. Pane behavior is pinned to
*observed* SDK behavior, and the SDK moves fast.
**The work**: promote the verify-at-build ledger from a build-time
artifact to a **release-gate check** — every release (and any SDK
bump) re-runs the probe battery (streaming, canUseTool, session flags)
against the installed SDK version and fails the release on drift, so
an SDK regression is caught in the checklist, not by the user's pane
going dark. Record the SDK version in the release notes. This is the
cheap standing form of FW-23's watch.

## 8. Phase sequencing + exit shape

FW-10 ruling → FW-11+FW-12 together (the version means nothing without
migration posture) → FW-14 → FW-13 → FW-15 folds into the checklist as
it forms. **Exit criterion, in the corpus's own style**: on a machine
that has never seen the repo, a documented install → register →
teach → review → route round-trip succeeds inside ten minutes without
reading the corpus; upgrade from the previous release preserves a
seeded sandbox ledger byte-for-byte in substance. Whole phase runs
under the standard two-gate discipline once specs exist; this doc is
the pre-spec map, not the spec.
