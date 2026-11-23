# Lessons provider: task selection and capture receipts (S-161)

**2026-11-22.** An external task runner can capture lessons, ask which routed
lessons fit a task, and record feedback without parsing presentation prose.
The ledger remains the authority; the index is a disposable acceleration cache.
This surface does not approve lessons, change their placement, or replace canon.

## 1. Selection

`self-learn select --query TEXT [--path FILE_OR_GLOB]… [--project DIR]
[--literal-path FILE]… [--skill NAME]… [--exclude ID]… [--limit N] [--tier confident|all] [--no-embed] [--json]`.

Eligibility is exactly `domain.is_canon_live`: routed and not superseded.
Pending, deferred, rejected and superseded lessons cannot be returned. There is
no pending opt-in: capture is not approval, and a provider consumer must not
silently turn the pending queue into instructions. A record also needs routing
metadata naming its destination.

User lessons are always eligible. Project lessons require `--project`, matched
against the bucket's recorded `meta.yaml` path, not its lossy slug. Resolve an
existing project directory to its Git root and apply the same registered-worktree
mapping as capture. Include registered ancestor hosts from `hosts.ancestors_of`
as S-52 requires, even across nested Git roots. At the default confident tier, skill lessons require an explicit
repeatable `--skill NAME`. The possible-tier exceptions below never infer a project. Omitting `--project` does not implicitly include the
current project's lessons. A returned lesson keeps its stored `scope`; the
additional `scope_relation` is `user`, `skill`, `project` or `ancestor-project`.
Ancestor matches say `ancestor project scope` in `why`, and their gates and
`matched_paths` use the ancestor host's relative names (for example a child's
`src/main.py` is `child/src/main.py` to its parent host).

`routing.rules_paths` is an additional gate, never a replacement for relevance.
In the confident tier a gated lesson requires at least one matching supplied path, using the existing
routing glob matcher (`*` stays within a component, `**` crosses components).
Relative input paths are relative to the task's Git root, or the supplied
directory outside Git; without a project they are relative to the current Git
root/directory. Absolute input paths may also name files outside that root.
Evaluate user rules against the same roots as routing reachability: the user
home plus registered project/skill hosts outside that home. Project/ancestor rules are
relative to the recorded project/ancestor directory. Map worktree paths back
to the registered project before evaluating project gates. Literal
paths may name planned files. An existing file passed with `--path` is literal
before glob interpretation; `--literal-path` also names nonexistent files with
brackets or wildcard characters. Preserve the supplied path's normalized spelling
for matching, including an internal symlink's name. A symlink pointing outside
its input root is ignored with an explicit note; it does not discard other paths or
ungated lessons. A relative path escaping its input root (`../x`) is a usage error.

Input globs expand existing files. Inside Git, use the read-only bounded
`git ls-files --cached --others --exclude-standard -z` inventory; ignore rules
apply, `.git` is never walked, and tracked files remain eligible even if a later
ignore rule names them. Literal glob prefixes become literal Git pathspecs, so
files outside the requested subtrees do not exhaust the budget. Descend into
nested Git checkouts and initialized submodules with their own ignore rules;
entry, byte and elapsed-time budgets are shared across all inventories and
absolute-path input groups. Uninitialized submodules
have no concrete file witnesses. All selection Git queries disable fsmonitor,
optional locks and the pager, with `GIT_OPTIONAL_LOCKS=0`. Outside Git, walk only possible matching subtrees and
skip `.git` and symlinks. The inventory has deterministic limits of 10,000 entries
and 4 MB of combined Git output. Git runs through the shared bounded-child
primitive with one 30-second inventory deadline; each child receives only the
remaining time, and filesystem traversal checks the same deadline. Exceeding bytes or
time kills its entire process group. This is a hung-process guard, not the old
one-second traversal cutoff. Exhaustion or an inventory error
omits path-gated lessons and records that degradation in `note`; ungated lessons
still rank normally. No partial glob evidence is treated as complete. A zero
limit skips enumeration. Empty expansion matches nothing.

If hosts.yaml is malformed or unsupported, retain user and exact-project
selection and report `hosts.yaml unreadable; ancestor lessons omitted`; never
guess ancestor registration. Missing Git at the CLI ledger-home gate returns 5
with a diagnostic, rather than a traceback.

## 2. Ranking and the relevance floor

Read current record bodies and routing on every call. Use redacted lesson text
and the existing query tokenizer plus FTS5 Porter/unicode61 stemming. The corpus
is **every readable record**, including records later excluded by lifecycle,
project, skill, path or `--exclude`. The query is tokenized in a separate RAM table
and never contributes to corpus document frequency. Thus eligibility changes alone
cannot alter another lesson's lexical score. Changing explicit retrieval context
or the ledger text can change the score.

Use BM25 term saturation (`k1=1.2`, `b=0.75`) with positive IDF
`log(1 + (N - df + 0.5)/(df + 0.5))`. This fixes FTS5's zero/negative-IDF clamp on
small ledgers. Compute query-self and lesson-self weights using those same fixed
corpus statistics; average the two cross/self ratios, each clamped at 1. This is
an explicitly revised task lexical scale, not an assertion that FTS5 lesson-pair
BM25 values are interchangeable. Retain the existing lexical floor 0.16.
There is no task-word blacklist: `run`, `test`, `config` and other content words
retain their corpus IDF weight. Additional query-side evidence is:

- Match at least `min(2, number of distinct query stems)` stems, so a one-word
  lookup can qualify. Short queries (at most three distinct stems) must match
  every stem and have mean IDF / maximum observed corpus IDF at least 0.85
  (0.75 for one-word lookups).
- Longer tasks qualify through shared stems in local windows allowing gaps,
  after the existing tokenizer and Porter stemming. In each text the shared
  stems must lie within at most 10 tokens. Compute their maximum-IDF common subsequence
  (distinct shared stems in the same order, allowing intervening words); it must
  contain two distinct alphabetic-bearing stems and at least 1.5 times the
  maximum corpus term IDF in distinct alphabetic-bearing stems. A window
  can combine moderately informative words; overlaps farther apart cannot qualify.
  Numeric fragments of addresses or versions do not establish a topic. Supporting
  stems after removing the rarest stem must themselves carry at least 0.75 times
  peak IDF: one rare word cannot carry a common companion into a match.
- Score the best qualifying phrase with the same symmetric BM25 ratios. Extra
  task prose does not dilute a distinctive shared phrase. Symmetric whole-field
  overlap of at least 0.65 remains an alternative for strong matches in small
  corpora that repeat their topic. Empty token sets never qualify.

Explicit context narrows scope/path eligibility and may strengthen an already
supported task match; **context alone never qualifies a lesson**. Retrieval
context contains only the caller's project argument and the literal `--path`
and `--literal-path` strings, including unexpanded glob patterns. No canonical
project name, directory listing or expanded filename is added. After redaction
and newline folding, retain at most 20 path fields and 2,048 UTF-8 bytes including
the project field; `note` reports truncation. This bound controls provider
payload and lexical field cost independently of the larger gate inventory.
The context cap never changes which supplied paths are considered for gating.

Each caller-typed context field is a separate lexical field at half weight. A
field can strengthen only a lesson that already passed the task's lexical test;
fields cannot create evidence or combine words across file boundaries. Project
and file fields follow the same rule, without a file-present special case.
All lifecycle, scope and path gates still apply before a result is returned.

These task tuning constants are exposed in `thresholds`: `lexical_min_terms`,
`lexical_anchor_information`, `lexical_window_tokens`, `lexical_context_weight`,
`lexical_query_specificity`, `lexical_lookup_specificity`, and
`lexical_strong_overlap`. Corpus frequency makes broadly shared words weak
rather than categorically unusable; it is not a semantic applicability oracle.

Read cached embeddings only when their text hash matches the current lesson text.
Measure the task alone and, when context exists, the task plus bounded context
in one batch using the provider's **query** template;
lesson/draft comparisons elsewhere retain their document template. The bounded
interactive call uses one attempt and at most five seconds of HTTP timeout.
At most two query vectors are requested, in one Gemini HTTP request; without
context, only one. The outer provider wait is also bounded. Compare only the same model.
For Gemini task queries use cosine 0.70; its existing 0.75 lesson-pair threshold
continues unchanged elsewhere. Other registered models retain their existing
thresholds; an unregistered model cannot qualify semantic results. These are
retrieval similarity floors, not probabilities of applicability.

### Confidence tiers

`--tier confident` is the default; `--tier all` also returns `possible` results.
Every result carries `confidence`. These names identify retrieval tests, not
probabilities or permission to follow a lesson. For the measured Gemini profile,
let T be task-only cosine, C be task-plus-context cosine, and L mean passing the
task's lexical evidence test, with the combined task/context score meeting the
0.16 floor (context can lift a task-supported score above that floor):

| Tier | Qualification for an otherwise eligible lesson |
|---|---|
| confident | T >= 0.75; or T >= 0.70 and L; or T >= 0.675, C >= 0.70 and L |
| possible | T >= 0.70; or T >= 0.65 and L; or a supplied path actually satisfies the rules gate and either (T >= 0.60 and C >= 0.675) or (T >= 0.65 and C >= 0.65) |

Evaluate confident first. Context cannot qualify a lesson without independent
task evidence: the lowest task floor requires both semantic context corroboration
and an actual path-gate witness. Merely naming a project is insufficient.
Current semantic evidence below these tests cannot be overridden by lexical
fallback. Confident results use RRF over exactly the default tier's candidate pool,
including candidates that later fail qualification; all-only scope exceptions
cannot change their scores or order. Possible results retain RRF over the expanded
candidate pool and follow every confident result, with id tie breaks within each
tier. For limit N and C qualifying confident results, return min(C, N) confident
results, then at most max(0, N - C) possible results. Thus, for identical inputs
and the same limit, the complete default result list is a prefix of `--tier all`;
if confident results fill the limit, no possible results are returned.

Only `--tier all` admits two normally excluded classes, always as possible:
unnamed skill lessons when **no** skill was requested require T >= 0.725;
user rules with paths when **no** path was supplied require T >= 0.75, or
T >= 0.70 with L (the same strong task-only test as confident retrieval).
These exceptions require a current vector and the measured model profile.
A named different skill, a supplied but nonmatching path, another project's
bucket, and project-scoped missing path gates remain exclusions. Explanations
explicitly say `skill not requested` or `path not supplied`; no gate witness is
invented. Supplying context never weakens these exception floors.

Other registered models retain their measured single floor and have no weaker
or scope-exception tier until calibrated. Missing vectors, no model/key, corrupt
cache or a failed request fall back to lexical qualification for structurally
eligible lessons, with an explicit reason and `score.basis: lexical`. Such
results retain the confident retrieval tier, but cannot distinguish word senses;
callers requiring semantic evidence must inspect the basis. `--no-embed` makes
no embedding call. Selection never builds or repairs the persistent index.

The original regression probes remain exact tests, alongside synthetic verbose
queries, generic one/two-word overlaps, paraphrases without common wording, and
path/project context. Independently labeled development tasks were used to tune
this revision; development results are not held-out quality estimates. Labels,
queries, ledger text and vectors stay outside this public repository. The held-out
split was scored only by the independent evaluator. No universal precision/recall
or semantic applicability guarantee is claimed by the synthetic fixtures.

Independent held-out measurement on 60 realistic tasks with 37 labelled positive
lesson/task pairs, one ledger and `gemini-embedding-2@3072/i1`:

| Mode / tier | Right | Wrong | Precision | Recall |
|---|---:|---:|---:|---:|
| Embedded, confident | 8 | 2 | 80% | 22% |
| Embedded, all | 20 | 6 | 77% | 54% |
| Lexical only, either tier | 8 | 2 | 80% | 22% |

Every one of the 24 near-miss and unrelated tasks returned nothing in these
measurements. The `confident` label did not establish a reliably more accurate
class than `possible`: 8 of 10 confident results were right, versus 12 of 16
possible results (80% versus 75%, only a small observed difference). It describes
the kind of evidence, not a probability. These are small counts on one ledger
and one embedding model, supplied by an independent evaluator on the round-3
implementation; they are not expected performance on another workload.
Re-measure both tiers after changing the model, dimensions, embedding templates,
retrieval/ranking policy, corpus size or topics, routing, or the caller's task and
context distribution. Development-set tuning figures are not quality forecasts.


Rank eligible candidates with existing reciprocal-rank fusion and deterministic
id tie breaks. Compute lexical weights before eligibility filtering; apply scope,
lifecycle, gates and exclusions before ranking/cutting to the limit, so an excluded
nearest result cannot hide an eligible next result. Similarity names its scale
(cosine for a current semantic result, lexical for fallback). RRF is a ranking
value, not a probability or a distance comparable with another provider's score.

Caller-typed absolute project and path strings can disclose home-directory names
to the embedding provider within the context cap. Expanded or canonical names
are never sent; `--no-embed` avoids provider disclosure entirely.

### Calibration and limits

These constants are retrieval heuristics, not learned probabilities. Their
origins and re-calibration conditions are part of the contract:

| Constant | Derivation / purpose |
|---|---|
| BM25 `k1=1.2`, `b=0.75`, IDF smoothing `0.5` | Conventional BM25 parameters, retained from the existing index; positive IDF prevents the tiny-corpus clamp. |
| Lexical floor `0.16` | Existing index floor, retained with synthetic and independently labelled regression checks on the revised symmetric scale; not analytically equivalent to the old scale. |
| Minimum 2 shared stems | Require corroboration; one generic shared word is insufficient. A complete one-word lookup is the explicit narrow exception. |
| Short-query boundary 3 stems | Preserve concise lookup behavior while allowing longer task descriptions to contain extra prose; a design boundary checked on the development inputs, not a statistical optimum. |
| Mean IDF ratios `0.85` (short) / `0.75` (single) | Conservative specificity margins selected during the first development calibration. The single-word exception uses the lower margin because an otherwise exact topic name may appear in several lessons. These were not independently optimized constants. |
| Window 10 tokens / information mass `1.5` peak IDF | Require two distinct informative stems in a local passage; the mass can combine moderately rare terms, but neither repeated terms nor numeric fragments count. Ten is a development-calibrated local-clause limit, not a model context window: 12 admitted a near-miss and 8 lost useful matches without improving observed precision. A weighted common subsequence permits gaps; fully unordered windows admitted unrelated topic-word combinations. The supporting stems, excluding the rarest, must carry at least the existing single-lookup specificity (`0.75` peak IDF), preventing one rare term from carrying generic overlap. |
| Whole-field overlap `0.65` | Approximately two-thirds symmetric self-match, an alternative for small corpora where repeated topics make normalized rarity less useful; retained after the synthetic small-ledger checks. |
| Context weight `0.5` | Deliberately weaker than task evidence; a ranking design choice, never an eligibility threshold. |
| Gemini base task floor `0.70` / strong `0.75` | The first independent development sweep rejected a blanket `0.675` floor because it added substantially more wrong than right results. The second, realistically contextualized development set supports `0.70` plus lexical corroboration, and `0.75` without it; the latter also retains the existing lesson-pair floor as a conservative task-only margin. These are measured task rules, not mathematical equivalence to lesson-pair similarity. |
| Confident context-supported task floor `0.675` | The previously rejected blanket floor is used only with two independent corroborations: task lexical evidence and context cosine >= `0.70`. Checked against realistically contextualized development negatives. |
| Possible lexical-supported task floor `0.65` | A deliberately weaker development-tested floor, requiring task lexical corroboration. It is not applied to semantic-only matches. |
| Possible gate-supported T `0.60`, C `0.675` | Reserve the weakest task floor for an actual gate witness plus context similarity. Development comparisons of context floors `0.65`, `0.675`, `0.70` found the middle choice retained more correct matches than `0.70` without the additional wrong matches at `0.65`. |
| Balanced gate-supported T and C `0.65` | An additional conjunction permits two moderate semantic scores instead of the asymmetric `0.60`/`0.675` pair, still requiring a real gate witness. On realistic development inputs it recovered a missed task without additional false positives; unlike lowering the context floor alone, both sides must pass. |
| Unnamed skill T `0.725` / missing user path T `0.75` or `0.70` with L | Separate development measurements of normally excluded classes: blanket `0.70` admitted wrong lessons in both. Skill `0.725` removed the observed false positives; for missing user paths, the ordinary confident task-only test (`0.75`, or `0.70` with lexical corroboration) retained another correct result without an added false positive. Both classes remain possible only and require current task semantics, never lexical fallback or context alone. |
| 20 context paths / 2,048 UTF-8 bytes | A disclosure and work bound, not relevance calibration. Keeps a broad glob from becoming an inventory-sized request; applies before embedding. |

Re-derive semantic thresholds for a different embedding model, dimension or
query/document instruction template. Re-measure lexical thresholds after changing
tokenization, stemming, the scoring formula, or substantially changing corpus size
or topic distribution: normalized peak IDF varies with those conditions. In
particular, a much larger ledger or a new small installation requires its own
labelled evaluation; synthetic tiny-ledger tests establish behavior, not a
precision guarantee. Evaluate both precision and recall by confidence tier and
retain near-miss/unrelated silence checks. Do not retune from held-out labels.

Lexical retrieval cannot determine word sense or whether a shared topic changes
the task. A query about an agent shell's colour can match a shell-permissions
lesson; a diagram of a container logo can match a container-restart lesson.
Porter stemming handles regular forms but not every irregular inflection.
Gapped ordered windows recover tasks supported by other shared terms (including
the build/built probe's topic and tool), without a special-case synonym list.
They recover some reordered tasks through a remaining shared subsequence, not
every word permutation; lexical retrieval cannot reliably infer grammatical roles. Lexical
fallback remains explicitly identified by `mode` and `score.basis`; its confidence
is confidence in the stated retrieval test, never proof of applicability.

## 3. Read contract

Selection bypasses the CLI miner watchdog, sentinel heartbeat, telemetry flush,
worker kick and mutating epilogue. It does not acquire the ledger commit lock
(which can recover an intent), create cache directories, initialize schema,
write counters, commit or push. The index is opened using SQLite `mode=ro` and
`query_only`; the FTS table is RAM-only. The ordinary command watchdog can spawn
a miner catch-up run and write cache state; it is expressly excluded here.

JSON output is one object with `command`, `tier`, `mode`, `note`, `thresholds`, `lessons`
and `unreadable`. Each lesson has `id`, agent-facing `text`, `type`, `kind`,
`confidence`, `scope`, `scope_relation`, `bucket`, `status`, the complete `routing` mapping, `score` (`value`,
`basis`, `rrf`, `cosine`, `context_cosine`, `lexical`), `why` and `matched_paths`. `why` names
the following independent facts (the ambiguous legacy `semantic` value is removed):

| `why` value | Meaning |
|---|---|
| `current vector` | A current vector supplied the task cosine; this alone never qualifies a result. |
| `semantic floor` | Task cosine passed the model's base `thresholds.cosine`, independently of the tier's other tests. A possible result may pass it, and a corroborated confident result may fall below it. |
| `lexical` | Task text established lexical evidence and the combined task/context score passed the lexical floor; context may strengthen that evidence. |
| `user scope` | The record is user-scoped. |
| `project scope` | The record belongs to the requested project. |
| `ancestor project scope` | The record belongs to a registered ancestor of the requested project. |
| `skill scope` | The record is skill-scoped; inspect `skill not requested` for an exception. |
| `path gate` | A supplied path actually matched the record's rules gate. |
| `task/context corroboration` | The stated confident or path-supported possible context test passed. |
| `skill not requested` | An unnamed skill was admitted as possible on strong task semantics. |
| `path not supplied` | A gated user rule was admitted as possible without a supplied path; no gate match is claimed. |

Reference/hook destinations preserve complete Trigger/Instruction or Fact
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
`scope`. If the post-operation record read fails (for example, a concurrent
move), keep the operation exit code and id, return null `path`/`status`/`scope`,
and add `receipt_error: "record unavailable after operation; use show to reconcile"`.
Never turn a committed write into a usage refusal just because the receipt read
failed. Feedback outcome fields still describe the completed operation.
Feedback verbs (`note`, `confirm-held`, `supersede`) additionally return
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
integrations. A repeated `supersede OLD NEW` remains a lifecycle refusal
(exit 1), even for the same NEW. After a lost reply or failed push, inspect
`show OLD --json` and its `superseded_by` before retrying; reconcile host cleanup
and publication separately. Do not mistake the refusal for an unapplied first
operation. Plain pending `teach --no-push` is supported as well as routed capture.

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
secret-scan bypass is introduced. Compatibility change: CLI and batch
`note --key` now refuse previously accepted keys outside this safe format;
shipped 16-hex batch keys remain accepted.

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


## 5. Repeated-call cost

Selection reads every record to keep corpus statistics stable under exclusions
and to reject stale vectors against current text. Cold CLI calls therefore pay
for every YAML parse; no constant-time or subsecond guarantee is implied.
The existing `Record.from_path` cache helps repeated calls in one Python process,
while rereading file contents and cloning parsed records preserves freshness and
caller isolation. It is bounded in memory and is not a persistent index or a
cross-process cache. Persistent memoization would conflict with the read-only
contract unless maintained separately by a writer; no such daemon is started.
