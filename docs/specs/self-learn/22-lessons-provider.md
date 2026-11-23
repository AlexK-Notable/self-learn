# Lessons provider: task selection and capture receipts (S-161)

**2026-11-22.** An external task runner can capture lessons, ask which routed
lessons fit a task, and record feedback without parsing presentation prose.
The ledger remains the authority; the index is a disposable acceleration cache.
This surface does not approve lessons, change their placement, or replace canon.

## 1. Selection

`self-learn select --query TEXT [--path FILE_OR_GLOB]… [--project DIR]
[--literal-path FILE]… [--skill NAME]… [--exclude ID]… [--limit N] [--no-embed] [--json]`.

Eligibility is exactly `domain.is_canon_live`: routed and not superseded.
Pending, deferred, rejected and superseded lessons cannot be returned. There is
no pending opt-in: capture is not approval, and a provider consumer must not
silently turn the pending queue into instructions. A record also needs routing
metadata naming its destination.

User lessons are always eligible. Project lessons require `--project`, matched
against the bucket's recorded `meta.yaml` path, not its lossy slug. Resolve an
existing project directory to its Git root and apply the same registered-worktree
mapping as capture. Include registered ancestor hosts from `hosts.ancestors_of`
as S-52 requires, even across nested Git roots. Skill lessons require an explicit
repeatable `--skill NAME`. Omitting `--project` does not implicitly include the
current project's lessons. A returned lesson keeps its stored `scope`; the
additional `scope_relation` is `user`, `skill`, `project` or `ancestor-project`.
Ancestor matches say `ancestor project scope` in `why`, and their gates and
`matched_paths` use the ancestor host's relative names (for example a child's
`src/main.py` is `child/src/main.py` to its parent host).

`routing.rules_paths` is an additional gate, never a replacement for relevance.
A gated lesson requires at least one matching supplied path, using the existing
routing glob matcher (`*` stays within a component, `**` crosses components).
Paths are relative to the task's Git root, or the supplied directory outside Git;
without a project they are relative to the current Git root/directory. Literal
paths may name planned files. An existing file passed with `--path` is literal
before glob interpretation; `--literal-path` also names nonexistent files with
brackets or wildcard characters. Preserve the supplied path's normalized spelling
for matching, including an internal symlink's name. A symlink pointing outside
the project is ignored with an explicit note; it does not discard other paths or
ungated lessons. A lexical path outside the root is a usage error.

Input globs expand existing files. Inside Git, use the read-only streamed
`git ls-files --cached --others --exclude-standard -z` inventory; ignore rules
apply, `.git` is never walked, and tracked files remain eligible even if a later
ignore rule names them. Outside Git, walk only possible matching subtrees and
skip `.git` and symlinks. The inventory has deterministic limits of 10,000 entries
and 4 MB of combined Git output. Git runs through the shared bounded-child
primitive with the standard 30-second local Git deadline; exceeding bytes or
time kills its entire process group. This is a hung-process guard, not the old
one-second traversal cutoff. Exhaustion or an inventory error
omits path-gated lessons and records that degradation in `note`; ungated lessons
still rank normally. No partial glob evidence is treated as complete. A zero
limit skips enumeration. Empty expansion matches nothing.

## 2. Ranking and the relevance floor

Read current record bodies and routing on every call. Use redacted lesson text
and the existing query tokenizer plus FTS5 Porter/unicode61 stemming. The corpus
is **every readable record**, including records later excluded by lifecycle,
project, skill, path or `--exclude`. The query is tokenized in a separate RAM table
and never contributes to corpus document frequency. Thus eligibility changes
cannot alter another lesson's lexical score (actual ledger edits still can).

Use BM25 term saturation (`k1=1.2`, `b=0.75`) with positive IDF
`log(1 + (N - df + 0.5)/(df + 0.5))`. This fixes FTS5's zero/negative-IDF clamp on
small ledgers. Compute query-self and lesson-self weights using those same fixed
corpus statistics; average the two cross/self ratios, each clamped at 1. This is
an explicitly revised task lexical scale, not an assertion that FTS5 lesson-pair
BM25 values are interchangeable. Retain the existing lexical floor 0.16, with
additional evidence: **at least two distinct matched query stems** after the
usual stopword filter and generic-task filter. Generic terms (`add`, `after`,
`before`, `check`, `config`, `configuration`, `during`, `file`, `launch`, `run`,
`test`, `unit`, `while`, `write`) may contribute to ranking but never corroborate
a topic. One-word lexical lookups conservatively return no hits; a semantic hit
can still qualify independently. Return `thresholds.lexical_min_terms = 2`.

Calibration is pinned in `tests/test_provider_review.py`: 16 synthetic lessons,
six positive tasks with one intended hit each and six short/noise tasks with no
intended hits. The fixed implementation returned 6 true positives, 0 false
positives and 0 false negatives: 100% precision and recall on these fixtures.
This is a small labelled calibration set, not a held-out estimate of real-world
precision. Its exact-match expectations remain regression tests;
semantic retrieval is separately tested with fakes, never live embedding calls.

Read cached embeddings only when their text hash matches the current lesson text.
Embed the query using the existing bounded interactive provider path and compare
only the same model. A model without an entry in `COSINE_THRESHOLDS` cannot supply
semantic relevance. Use its existing measured threshold (currently 0.75 for the
registered Gemini model). No model, no key, stale/missing vectors, corrupt cache,
or a failed request falls back to lexical search with an explicit reason.
`--no-embed` makes no embedding call. Selection never builds the persistent index.

A lesson must meet the lexical or cosine floor; being the nearest result alone
is insufficient. Rank the two legs with the existing reciprocal-rank fusion and
its deterministic id tie break. Compute lexical weights before eligibility filtering; apply scope, lifecycle,
gates and exclusions before ranking/cutting to the limit, so an excluded nearest result cannot hide
an eligible next result. The returned similarity names its scale (cosine when
that floor passes, lexical otherwise); RRF is a ranking value, not a probability
or a distance comparable with another provider's score.

## 3. Read contract

Selection bypasses the CLI miner watchdog, sentinel heartbeat, telemetry flush,
worker kick and mutating epilogue. It does not acquire the ledger commit lock
(which can recover an intent), create cache directories, initialize schema,
write counters, commit or push. The index is opened using SQLite `mode=ro` and
`query_only`; the FTS table is RAM-only. The ordinary command watchdog can spawn
a miner catch-up run and write cache state; it is expressly excluded here.

JSON output is one object with `command`, `mode`, `note`, `thresholds`, `lessons`
and `unreadable`. Each lesson has `id`, agent-facing `text`, `type`, `kind`,
`scope`, `scope_relation`, `bucket`, `status`, the complete `routing` mapping, `score` (`value`,
`basis`, `rrf`, `cosine`, `lexical`), `why` and `matched_paths`. `why` names
semantic/lexical evidence, scope and any satisfied path gate. Reference/hook destinations preserve complete Trigger/Instruction or Fact
sections and Context using the reference compiler; managed-line destinations use
their existing compact line. Legacy multiline records also retain full sections.
Episode briefs, evidence and metadata are not emitted as lesson text. Bad record files
are omitted and listed in `unreadable`; missing/uninitialized homes return 5,
not an empty successful result. Invalid selection values and unknown CLI arguments return the usage code 64;
argparse's own syntax errors retain its existing code 2. Success (including
no matches or a zero limit) returns 0. Human output is the default.

The read sees each atomically replaced record at the time it opens it; it is
not a transaction over the entire ledger. Consumers must tolerate a concurrent
retirement immediately after selection, as with any read followed by use.

## 4. Capture and feedback receipts

`teach`, `note`, `confirm-held` and `supersede` accept `--json`. When a record was
successfully addressed or captured, stdout is one object: `id`, `path`, `status`,
`scope`. Feedback verbs (`note`, `confirm-held`, `supersede`) additionally return
`applied` (whether this call staged a mutation), `pushed` and `host_pushed`.
The established push vocabulary is `not_requested`, `no_remote`, `pushed`, or
`failed`; `host_pushed` is null when no host commit occurred. A keyed duplicate
has `applied: false`, `pushed: "not_requested"`; a kept commit followed by a failed
ledger push has `applied: true`, `pushed: "failed"` and the existing nonzero exit
code. A host-only push failure sets `host_pushed: "failed"` with that same exit
code while `pushed` still describes the ledger push.
`supersede` names the old record. Diagnostics go to stderr. Exit codes
are unchanged, including `teach --route`'s pending fallback (4) with a receipt
for the captured pending record. Validation failures with no record emit no
receipt. A receipt does not imply a successful push: callers must check the exit
code and push fields (teach retains its four-field capture receipt). `teach` retains its historical exit 0 after a committed
capture whose push failed (stderr reports that failure); use `--no-push` for
integrations. Plain pending `teach --no-push` is supported as well as routed capture.

`confirm-held` and `supersede` retain the requirement for `--note` in an
agent-marked shell. All four verbs commit ledger writes and ordinarily push; integrations pass
`--no-push` on every invocation. `SELF_LEARN_HOME` selects the ledger for every
verb. Background capture/feedback behavior remains the existing write-command
behavior; clients that need inert trials disable miner and worker autokick.

`note --append TEXT --key KEY` checks the key after acquiring the commit lock and
rereading the current record path and bytes. Different keys preserve all notes;
the same key appends once. `confirm-held --key KEY` does the same, using a separate
`confirmation_keys` list in record frontmatter: a single event can append a note
and confirm the lesson using the same token. A retry neither changes
`last_confirmed` nor creates a feedback commit. The ordinary write-command epilogue may still flush unrelated telemetry. Without `--key`, each call is an observation as
before; providers must supply a stable event key for retries. Keys are retained
for the record's lifetime. Confirmation rereads under lock so it cannot overwrite
concurrent notes or a changed lifecycle. No new lifecycle state is introduced.


Feedback keys use the same validation for both verbs: 1..40 ASCII letters,
digits, dot, underscore, colon or hyphen, and no secret-scanner hit. UUIDs or
32-hex event identifiers are convenient; raw SHA-256 (64 hex) is not accepted.
Invalid keys return 64 naming `--key`, without echoing its value, before record
writes, locks or the CLI watchdog/epilogue. Direct verb callers get the same
validation, and batch previews call the same preflight as apply. This prevents storing text that would make future record scans
refuse every verb. Existing record readers remain compatible; no migration or
secret-scan bypass is introduced.

Confirmation performs read-only preflight before sentinel/commit locks, then
rechecks the current record under lock. Non-routed refusals and acknowledged
retries do not newly acquire those write-side resources; concurrent lifecycle
changes still refuse under lock. This restores the pre-provider refusal behavior
while preserving the lost-update fix. Ordinary successful write-command
telemetry epilogues remain possible, including after a duplicate acknowledgment.

`confirmation_keys` is specified in **02 §2**, not only here. Retention is
append-only and lifetime-long: a provider should record meaningful observations,
not each selection or task tick. Each new observation adds one key and one commit;
there is no bounded/TTL dedupe guarantee. Silently evicting old keys would break
retry safety, so no lossy cap or compaction is permitted. A future exact archival
index would need its own atomicity and migration contract.
