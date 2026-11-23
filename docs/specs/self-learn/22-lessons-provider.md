# Lessons provider: task selection and capture receipts (S-161)

**2026-11-22.** An external task runner can capture lessons, ask which routed
lessons fit a task, and record feedback without parsing presentation prose.
The ledger remains the authority; the index is a disposable acceleration cache.
This surface does not approve lessons, change their placement, or replace canon.

## 1. Selection

`self-learn select --query TEXT [--path FILE_OR_GLOB]… [--project DIR]
[--skill NAME]… [--exclude ID]… [--limit N] [--no-embed] [--json]`.

Eligibility is exactly `domain.is_canon_live`: routed and not superseded.
Pending, deferred, rejected and superseded lessons cannot be returned. There is
no pending opt-in: capture is not approval, and a provider consumer must not
silently turn the pending queue into instructions. A record also needs routing
metadata naming its destination.

User lessons are always eligible. Project lessons require `--project`, matched
against the bucket's recorded `meta.yaml` path, not its lossy slug. Resolve an
existing project directory to its Git root and apply the same registered-worktree
mapping as capture. Skill lessons require an explicit repeatable `--skill NAME`.
Omitting `--project` does not implicitly include the current project's lessons.

`routing.rules_paths` is an additional gate, never a replacement for relevance.
A gated lesson requires at least one matching supplied path, using the existing
routing glob matcher (`*` stays within a component, `**` crosses components).
Paths are relative to the task's Git root, or the supplied directory outside Git;
without a project they are relative to the current Git root/directory. Literal
paths may name planned files. Input globs expand existing files (including hidden
files, excluding symlinks); an empty expansion matches nothing. Enumeration
stops with an explicit error after 10,000 entries or one second; narrow the
glob or supply literal paths. A zero limit skips enumeration. Absolute paths must lie inside that
root. Parent traversal and symlinks outside it are refused or excluded. Return
concrete matching paths so the consumer can explain the gate.

## 2. Ranking and the relevance floor

Read current record bodies and routing on every call. Use the index's redacted
lesson text and tokenizer. Construct an FTS5 table in memory with these texts and
one synthetic query document. Lexical similarity is the average of normalized
BM25 in both directions: query retrieving lesson relative to query retrieving
itself, and lesson retrieving query relative to lesson retrieving itself. Clamp
each direction at 1, as `LessonIndex.lexical_profile` does. Reuse the existing
`LEXICAL_THRESHOLD` (0.16); do not normalize against the best returned hit.
This applies the existing lesson-pair scale to a task document; it is not a new
empirical calibration for task queries.

Read cached embeddings only when their text hash matches the current lesson text.
Embed the query using the existing bounded interactive provider path and compare
only the same model. A model without an entry in `COSINE_THRESHOLDS` cannot supply
semantic relevance. Use its existing measured threshold (currently 0.75 for the
registered Gemini model). No model, no key, stale/missing vectors, corrupt cache,
or a failed request falls back to lexical search with an explicit reason.
`--no-embed` makes no embedding call. Selection never builds the persistent index.

A lesson must meet the lexical or cosine floor; being the nearest result alone
is insufficient. Rank the two legs with the existing reciprocal-rank fusion and
its deterministic id tie break. Apply scope, lifecycle, gates and exclusions
before ranking/cutting to the limit, so an excluded nearest result cannot hide
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
`scope`, `bucket`, `status`, the complete `routing` mapping, `score` (`value`,
`basis`, `rrf`, `cosine`, `lexical`), `why` and `matched_paths`. `why` names
semantic/lexical evidence, scope and any satisfied path gate. Reference/hook destinations preserve complete Trigger/Instruction or Fact
sections and Context using the reference compiler; managed-line destinations use
their existing compact line. Legacy multiline records also retain full sections.
Episode briefs, evidence and metadata are not emitted as lesson text. Bad record files
are omitted and listed in `unreadable`; missing/uninitialized homes return 5,
not an empty successful result. Invalid values return 2 (unknown CLI arguments retain the global usage code 64); success (including
no matches or a zero limit) returns 0. Human output is the default.

The read sees each atomically replaced record at the time it opens it; it is
not a transaction over the entire ledger. Consumers must tolerate a concurrent
retirement immediately after selection, as with any read followed by use.

## 4. Capture and feedback receipts

`teach`, `note`, `confirm-held` and `supersede` accept `--json`. When a record was
successfully addressed or captured, stdout is one object: `id`, `path`, `status`,
`scope`. `supersede` names the old record. Diagnostics go to stderr. Exit codes
are unchanged, including `teach --route`'s pending fallback (4) with a receipt
for the captured pending record. Validation failures with no record emit no
receipt. A receipt does not imply a successful push: callers must check the exit
code and diagnostics. `teach` retains its historical exit 0 after a committed
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
