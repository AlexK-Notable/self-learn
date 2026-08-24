# Spec — U-cap: the report-only context budget (retiring the managed-section cap)

Status: **r1 folded — all 16 gate findings closed.** Unit `U-cap`, TaskList #1
(Wave 2 of the cap-rework sequence). Next consumer: the Sonnet builder, then
the blind code gate.

**Round 1** — blind Opus spec gate: **NOT SOUND, 3 BLOCKER / 4 MAJOR / 9 NIT**,
no ruling violations. All sixteen folded here, each re-verified against this
tree before folding rather than accepted on the gate's word.

**Where the r1 findings landed** — B1 §2.11 + §3.1 + §4.2 + T2.8a/T2.8b/T2.9/
T2.9a · B2 §4.3.1 + §6.4 + T3.6/T3.7 · B3 §4.3.2 + T3.1/T3.1a/T3.4/T3.4a ·
M4 §4.2.1 + §4.4.3 + T2.12 · M5 §8 `test_routes.py` row (6 assertions, 4 broken
+ 2 vacuous) + `test_models_detail.py:373` · M6 §8 `test_pointer.py` row ·
M7 §4.0.3 + all four block shapes + T2.11/T3.3a · N1 §2.7/§6.6 · N2 §2.9 ·
N3 §4.0.5 · N4/N5 §8 line spans · N6 §6.1 + §8 + T1.6 grep tokens ·
N7 §4.4.1 · N8 §4.4.1 + T5.7 · N9 §6.4.

**Two gate figures did not reproduce, and the spec carries my measurements.**
(1) M4's "live sum 21,904 w": through `hosts.load_hosts`, the five registered
projects total **17,746 w**, giving a naive all-hosts sum of **~24,200 w**
(§4.2.1). The finding is unaffected — both numbers are far past any sane
advisory, which is the point. (2) B1's "41 skills / 2,607 w": the index holds
**45** entries; 2,607/41 is what the *strict* loader yields, and the 4 it drops
are worth 492 w. That discrepancy turned out to be a second defect the gate did
not flag — see §2.11 — and is why §4.2's extraction is two-tier.

Every `file:line` in §2 was read in this tree at `b8ac3cb` before being cited.
Every behavioral claim about the live surface is either read from source or
labeled as a 2026-08-22 measurement carried in from the research hub.

**Research provenance.** znote hub `NCEhEO-bS--NvGg0n0P1H` and its twelve
linked atomics. The two conclusions that decide this unit:

- *the cap is downstream treatment for an upstream failure* — the file is
  oversized because routing picks the always-on tier, not because entries are
  verbose. Tightening the threshold yields the same misplaced rules,
  compressed. The upstream half shipped separately (#6, the strict routing
  gate); **this unit is the light at the file.**
- *a hard cap converts a measured cost into an unmeasured one* — refusal
  relocates lessons onto shelves with no instruments. That is risk transfer
  into the region where failure is silent.

**The user ruling this unit implements**, verbatim in substance: *absolutely
strict up top, looser in-file.* There is **no hard ceiling anywhere in this
unit.** Every signal defined below is report-only. No signal may refuse a
route, block a verb, change an exit code, or set a field any caller reads as
a refusal.

---

## 1. Objective

Replace the managed-section overflow cap — `DEFAULT_MAX_ENTRIES = 10` /
`DEFAULT_MAX_WORDS = 150`, which measures **our words inside one managed
block** — with a report-only context budget that measures **the load the
system actually pays**.

The cap's defect is not its number. It is its noun. Measured on this host
2026-08-22:

| Surface | words | ~tokens (est) | share the cap governs |
|---|---:|---:|---|
| user `~/.claude/CLAUDE.md` | 3,355 | ~4,460 | its 2,597-word managed block |
| skill `description` fields (45 skills in the session index) | ~3,099 | ~4,120 | **none — invisible to every instrument** |
| unpathed rules files | 0 | 0 | — |
| **always-on baseline (any session)** | **6,545** | **~8,700** | **~16%** |
| `+ ~/.config/CLAUDE.md` when working there | 9,723 | ~12,900 | **1.7%** |
| **total in a `~/.config` session** | **16,268** | **~21,600** | — |

**On that skill-description figure.** It is extraction-dependent, and the
spread is not noise: the strict YAML loader yields **2,607 w over 41 skills**
(4 descriptions are not valid YAML scalars), a lenient reader yields
**3,077 w over 45**, and the original research pass recorded 3,190. §4.2 pins a
two-tier rule so the number this unit reports is *reproducible* rather than
merely asserted, and §2.11 records why the strict-only reading is the dangerous
one — it hides the four largest descriptions.

The same 150-word threshold is simultaneously far too loose (at user scope the
managed block *is* 77% of the file and exceeds the word cap 17x, and is
ignored wholesale) and far too tight (in `~/.config` it fired on a 1% change
to a file 97% of which the cap cannot see). A threshold that means opposite
things at two destinations trains the reader to discount it — and it was
discounted, knowingly, twice in one evening. That is the behavior a
miscalibrated alarm reliably produces, and it is the reason this unit
**deletes** the threshold rather than retuning it.

What ships:

1. **Two load classes** (§3) — unconditional vs conditional — with different
   treatment. Unconditional load is the scarce resource.
2. **Four report-only signals** (§4) — a true budget report, a crowding check
   that offers a merge, composition drift, and a growth-rate alarm.
3. **`new-skill` charged to the always-on budget** via its description delta;
   the skill **description** measured against a soft, reported ceiling, the
   **body** not measured against any (§5).
4. **`reference` reported on read-rate**, consuming U-readref's shipped
   `reference_shelf` block — not redesigning it (§4.5).
5. **Retirement of the over-cap WARNING and its graduation-card trigger**,
   with a coherent replacement for what the review flow gets instead (§6).
6. **`rules_cofire`** (U-glob, shipped) kept report-only and folded into the
   budget report; its `over_cap` escalation removed (§4.6).

---

## 2. Current behavior (verified)

### 2.1 The threshold and where it is defined

`plugins/self-learn/cli/src/self_learn/compilers.py`:

```
170:DEFAULT_MAX_ENTRIES = 10
171:DEFAULT_MAX_WORDS = 150
```

Exported at `compilers.py:129-130`. Documented at `compilers.py:32-36`
("Overflow (02 §4, mechanical): cap = 10 entries or ~150 words inside the
section").

### 2.2 What the compiler counts

`compile_managed_text` (`compilers.py:289`) builds one entry line per eligible
record and counts:

```
304:    word_count = sum(len(e.split()) for e in entries)
305:    if len(entries) > max_entries:
306:        over_cap, cap_reason = True, "entries"
307:    elif word_count > max_words:
308:        over_cap, cap_reason = True, "words"
309:    else:
310:        over_cap, cap_reason = False, None
```

Three verified facts the design turns on:

- the word count is **whitespace-split over the ENTRY LINES ONLY** — marker
  lines are excluded, and every word outside the marker pair is invisible;
- the cap is **advisory at the compiler already**: the entry is applied and
  the result is flagged (`compilers.py:33-36`), nothing is dropped;
- `max_entries` / `max_words` are per-call overrides
  (`compile_managed_text` `compilers.py:289-294`, `compile_managed_file`
  `compilers.py:349-354`, mirrored in `chezmoi.py:274-275`) — and **no
  per-target override mechanism exists**; every live call site uses the
  defaults.

### 2.3 The result fields

`compilers.py:196-205`:

```
196:class SectionResult:
199:    text: str
200:    changed: bool
201:    bootstrapped: bool
202:    entry_count: int
203:    word_count: int   # words inside the section (entry lines only)
204:    over_cap: bool    # section exceeds the cap — surface a graduation card
205:    cap_reason: str | None   # "entries" | "words" | None
```

### 2.4 The over-cap WARNING path

`verbs.py:294-303`:

```
294:    def over_cap_note(self) -> str | None:
295:        """02 §4: the compiler flags-on-exceed; callers MUST surface it —
296:        the next review session opens with a graduation card."""
298:        if cr is not None and getattr(cr, "over_cap", False):
300:                f"WARNING: managed section over cap ({getattr(cr, 'cap_reason', '?')})"
301:                " — graduate the oldest entries; next review opens with a"
302:                " graduation card (02 §4)"
```

Three live consumers, all verified:

- `cli.py:1185` — printed to **stderr** by `_finish_verb` after every verb;
- `cli.py:1145` — carried in the JSON verb envelope as the key `"over_cap"`;
- `teach.py:756` — printed to stderr by the one-motion `teach --route` path.

`NewSkillApplyResult` (`verbs.py:2348`) duck-types the same interface —
`over_cap` at `verbs.py:2359`, `cap_reason` at `verbs.py:2363` — by delegating
to its inner `SectionResult`.

### 2.5 `surface_fill` — the routing-decision probe

`verbs.py:1971`, over `SURFACE_FILL_CAPPED_DESTINATIONS`
(`verbs.py:213` = `("skill-md", "claude-md")`; `reference` is never probed).
Per destination it emits (`verbs.py:2049-2055`):

```
2050:            "entries": section.entry_count,
2051:            "entries_cap": DEFAULT_MAX_ENTRIES,
2052:            "words": section.word_count,
2053:            "words_cap": DEFAULT_MAX_WORDS,
2054:            "over_cap": section.over_cap,
```

and for `claude-md` only, `rules_topic_count` plus U-glob's co-firing datum
(`verbs.py:2086-2091`):

```
2086:            entry["rules_cofire"] = cofire
2087:            if cofire["max_fanin"] > 5:
2090:                entry["over_cap"] = True
2091:                entry["cap_reason"] = "rules-cofire"
```

`_rules_cofire` (`verbs.py:1918`) returns
`{topics, unpathed, pairs, max_fanin}`, decided **symbolically** via
`ledger_ops.globs_may_intersect` — no filesystem access beyond reading the
topic files' own text — and `max_fanin` is an explicit **upper bound**
(pairwise intersection does not compose).

Degradation discipline already in place (`verbs.py:2035-2047`): any
`VerbError | CompileError | OSError | UnicodeDecodeError` **omits that
destination's key entirely** — never a zero, never a guess. This spec
preserves that rule exactly and generalizes it (§4.2).

### 2.6 The telemetry event

`verbs.py:2337-2343` spools a `surface-budget` event per compile:

```
2338:    telemetry.spool_quiet(
2339:        "surface-budget",
2340:        target=spec.destination,
2341:        words=getattr(compile_result, "word_count", None),
2342:        overflow=bool(getattr(compile_result, "over_cap", False)),
2343:    )
```

Verified against the live tracked plane (`~/.self-learn/telemetry/`, read-only):

```
{"actor":"…","kind":"surface-budget","overflow":false,"target":"skill-md","ts":"2026-07-15T19:46:27Z","words":114}
{"actor":"…","kind":"surface-budget","overflow":false,"target":"claude-md","ts":"2026-07-15T22:53:49Z"}
{"actor":"…","kind":"surface-budget","overflow":true,"target":"skill-md","ts":"2026-07-15T22:53:54Z","words":211}
```

**Load-bearing detail the builder must not miss:** `spool_quiet` drops
`None` payload values (`telemetry.py:177-178`), so `words` is **absent** from
some events, and `target` is the **destination enum**, never the file. This
plane therefore cannot answer "how did THIS file grow" and is **not** the
source for §4.4's growth signal. `EVENT_KINDS` (`telemetry.py:75-90`) is a
closed frozenset — this unit adds no kind to it.

### 2.7 The UI budget surface

- `ui/src/self_learn_ui/models.py:530-534` — `REFERENCE_NO_CAP_LINE`:
  *"reference files have no cap — this is the overflow surface entries
  graduate into."* Template-static, no CLI datum, no probe.
- `models.py:1710-1711` — `_NEAR_ENTRIES_HEADROOM = 2`, `_NEAR_WORDS_RATIO = 0.8`.
- `models.py:1714` — `_budget_text`, the plain-words fill sentence, reading
  `entries`/`entries_cap`/`words`/`words_cap`/`over_cap`.
- `models.py:1754` — `_budget_rows`; `models.py:1543` — `BudgetRow` (fields
  `destination`, `text`, `over_cap`).
- `models.py:1556` — `BudgetRow.over_cap`.
- `routes.py:1419` — the resolution-evidence envelope's `over_cap` field
  (inside `_EVIDENCE_FIELDS`); rendered by
  `ui/templates/partials/evidence.html:70` with the CSS class
  `evidence-warning`. `ui/templates/detail.html:177` applies
  `surface-budget-over-cap`.

### 2.8 The doc-level promises

- `docs/specs/self-learn/02-schema.md:504-508` — the **Overflow rule**: "caps
  at 10 entries or ~150 words … the next review session opens with a
  graduation card".
- `docs/specs/self-learn/01-architecture.md:385` — the risk row naming the
  "mechanical cap — 10 entries/~150 words — with graduation cards".
- `docs/specs/self-learn/09-surface-spec.md:335-364` — Y-20: the Detail Why
  region is the *single* budget surface; at/over cap it states the fill fact
  and **defers escalation to the 02 §4 WARNING flow**.
- `plugins/self-learn/commands/review.md:131-133` — *"If any route in this
  session printed the over-cap WARNING (managed section at its entry/word
  cap), open the next batch with a graduation card for that section's oldest
  entries (02 §4)."*

### 2.9 What already exists that this unit CONSUMES (never redesigns)

- **`report.py:291` `_reference_shelf`** (U-readref, shipped) — returns
  `instrumented`, `instrument_state`, `flush_state`, `enumeration_state`,
  `unresolvable_records`, `unresolvable_record_ids`, `window_days`,
  `window_start`, `observation_start`, `targets_total`, `targets_zero_read`,
  `records_on_zero_read_targets`, `reads_30d_total`, `targets`. Verified
  against the live `report --json` payload. Per-target rows carry
  `read_sessions_30d`, `reads_30d`, `reads_all_time`, `subagent_reads_30d`,
  `last_read`, `zero_read`, `records`, `scope`, `ref_target`.
  Its §6.3 rule — *not-instrumented is a distinct state, NEVER zero* — is
  the discipline §4.5 inherits verbatim.
- **`verbs.py:1918` `_rules_cofire`** (U-glob, shipped).
- **`worker.py:379` `cluster_candidates`** and `worker.py:2718` `_tokens`,
  with `CANDIDATE_SCORE_FLOOR = 0.20` (`worker.py:162`) and
  `CANDIDATE_CAP = 5` — the pinned IDF-cosine clustering signal §4.3 consumes.
  **Verified import-safe without the optional SDK extra**: importing
  `self_learn.worker` with `claude_agent_sdk` blocked at the meta-path
  succeeds, so a deferred import from `report.py` cannot break `report` for an
  install without the `sdk` extra.
- **`compilers.py:613` `has_paths_key` / `compilers.py:591`
  `read_paths_frontmatter`**, both built on a lenient, never-raising leading-
  mapping loader — the frontmatter machinery §5 reuses for reading skill
  `description` fields. **No new frontmatter parser.**
- **`hosts.py:87` `Hosts`** (`skills_root`, `projects`) and
  `hosts.py:546` `skill_dir_for` — which globs
  `<skills_root>/plugins/*/skills/<name>`. **`skills_root` is the
  route-target repo, NOT the session skill index** (§2.11).
- **`ledger.py:142` `discover_buckets`**, `verbs.py:180`
  `DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")`, `verbs.py:772`
  `_user_rules_dir`, `verbs.py:779` `_project_rules_dir`, `verbs.py:1836`
  `_compile_set`, `verbs.py:1133` `_resolve_target`.
- **`skill_scaffold.py:52` `scaffold_description`** — the deterministic
  description minted on a `new-skill` route.
- **`records.py:56` `KINDS = {"anti-pattern", "surface-rule",
  "reasoning-pattern"}`** — the composition classifier §4.4 uses.

### 2.10 What does NOT exist today

- No token estimate anywhere. `grep -rn 'tiktoken|token_count|estimate_tokens'`
  over both `src` trees returns nothing, and the CLI's only runtime dependency
  is `ruamel.yaml>=0.18` (`cli/pyproject.toml:12-14`). **This unit adds no
  dependency**; §4.1 pins an arithmetic estimator.
- No instrument reads a skill `description`. Confirmed by grep across
  `selfcheck.py` and `verbs.py`.
- No always-on / whole-file measurement of any kind. `report --json`'s
  top-level keys today are exactly: `generated`, `buckets`, `destinations`,
  `routed_live`, `routed_ever`, `superseded_after_routing`, `supersede_rate`,
  `graduated`, `rejected`, `open_followups`, `recurrence_suspects`,
  `deferred`, `mined`, `telemetry`, `reference_shelf`.

### 2.11 The session skill index is a DIFFERENT tree from `skills_root` (B1)

Measured on this host 2026-08-23, read-only:

| tree | glob | SKILL.md files | description words |
|---|---|---:|---:|
| **session skill index** | `~/.claude/skills/*/SKILL.md` | **45** | **3,099** (two-tier, §4.2) |
| registered `skills_root` | `<skills_root>/plugins/*/skills/*/SKILL.md` | 9 | 803 |

`skills_root` is `~/repos/claude-skills` (`~/.self-learn/hosts.yaml`), and
`hosts.py:546 skill_dir_for` confirms its role: it is the **route-target**
repo — where a `skill-md` route writes. It is **not** what the session loads.

All 45 index entries are **symlinks**, and they resolve to **three different
roots**: 32 into `~/.agents`, 12 into `~/repos/claude-skills`, 1 into
`~/repos/self-learn`. So the registered `skills_root` accounts for **12 of 45**
entries. Globbing it, as the r1 draft did, would have reported ~803 words with
`state: "ok"` against a real ~3,099 — a ~4x under-report that never touches
`surfaces_unmeasured`. That is precisely the plausibly-named-decoy shape
(`lrn-6d21607e`) §4.0.3 itself cites. All 45 resolve to **distinct** paths
today, so dedupe currently collapses nothing — the rule in §4.2 is defensive.

**A second, worse finding, measured while verifying the first.** The r1 draft
mandated reading descriptions through `_safe_load_leading_mapping`
(`compilers.py`, the loader behind `has_paths_key`). Run against the real
index it yields **41 ok / 4 failures / 2,607 words** — and the four failures
are `agentic-engineering` (98 w), `bitwarden-cli` (161 w), `firecrawl-build`
(104 w) and `home-network` (129 w): **492 words, 16% of the surface, and the
long tail §5.3 exists to flag.** They fail because a plain YAML scalar cannot
contain `": "`, and every one of those descriptions does (`"…inside the app:
web search…"`, `"…CLIs — they are DIFFERENT products, disambiguate first. (1)
`bw`, the password-vault CLI…"`). A strict-only reader therefore hides exactly
the biggest contributors while reporting `state: "ok"` for everyone else —
the same fail-open, one layer down. §4.2's extraction is two-tier for this
reason, and T2.9 is built on these four real skills.

---

## 3. Load-class model

Destinations do not differ merely in size. They differ in **when they are
paid**, and that is what one threshold flattens away.

### 3.1 The two classes

**Class A — unconditional.** Paid in every session, by every task, whether or
not the rule is relevant.

| member | identity used by this unit |
|---|---|
| user `~/.claude/CLAUDE.md` | the resolved `DEFAULT_USER_CLAUDE_MD` (or the `user_claude_md` override) |
| project `<repo>/CLAUDE.md` | the registered host's `CLAUDE.md`, keyed by the bucket slug's 8-hex digest |
| **unpathed** rules topic files | `_rules_cofire(...)["unpathed"]` stems, per resolved rules dir |
| every skill frontmatter `description` | `~/.claude/skills/*/SKILL.md` — the **session index** (§2.11), never `skills_root` |
| `new-skill` | the description it mints (§5.2) |

**Class B — conditional.** Paid on use.

| member | why it is conditional |
|---|---|
| **pathed** rules topics (`variant: rules` with globs) | load when a matching file is read |
| skill **bodies**, including their managed section | load when the skill is invoked |
| `references/*.md` | load when the model chooses to open them |
| hooks | no context cost at all |

### 3.2 Why the failure modes are opposites, and what follows

Class A fails by **dilution and distraction**: length degrades performance
independent of retrieval quality, and stylistically identical near-matches
compete. More content is monotonically worse for everything it is not about.

Class B fails by **reach**: the rule is fine and simply never arrives. A glob
that matches nothing. A trigger that fires before the matching file is opened.
A references file nobody opens. Here more content is not the problem —
*arrival* is.

Therefore:

- **Class A gets volume signals** (§4.1 budget, §4.4 growth) and a
  **composition** signal (§4.4) — a shelf can shrink in words and get worse.
- **Class B gets NO size signal at all.** It gets **arrival** signals:
  read-rate for `reference` (§4.5) and co-firing fan-in for pathed rules
  (§4.6). A size cap on Class B is close to meaningless; a reachability check
  on Class A is close to trivial (it always arrives — that is the problem).

### 3.3 The partition the current code got wrong, named

`SURFACE_FILL_CAPPED_DESTINATIONS` (`verbs.py:213`) caps `skill-md` and
`claude-md` with one threshold and exempts `reference` as "the overflow sink".
That partition **cuts across the real boundary** in three places:

1. it caps a skill's **body** (Class B) while ignoring its **description**
   (Class A) — and the descriptions total 3,190 words, essentially the whole
   user `CLAUDE.md` again;
2. it exempts `reference` for being *cheap* without ever checking whether
   cheap means *unread*;
3. it treats `claude-md` — genuinely Class A — with the same number as a skill
   body, which is why the same threshold reads as 17x-exceeded at one
   destination and as a 1% overrun at another.

**Pin:** `load_class` becomes an explicit, emitted field (§4.2, §6.3) so no
future reader has to re-derive the partition from a destination name.

---

## 4. The four signals (field-exact)

### 4.0 Rules binding on all four

1. **Report-only, no exceptions.** No signal sets `over_cap` (which ceases to
   exist, §6.1), returns a non-zero exit code, raises, or gates a verb. The
   only permitted effects are: a key in `report --json`, a line in
   `report`'s text render, a key in `list --json --surface-fill`, a
   non-imperative note on the verb envelope (§6.2), and a review-flow **offer**
   (§6.4).
2. **`severity` is the literal string `"informational"`** on every signal
   block. It is emitted, not implied — a builder must not be able to invent
   `"warning"` / `"error"` without editing a pinned constant, and the code gate
   greps for any other value.
3. **Every block carries its own measured/unmeasured tally, and an all-blind
   form.** `budget`, `crowding`, `composition` and `conditional.rules_cofire`
   each emit `*_total` / `*_measured` / `*_unmeasured`; when `*_measured == 0`
   that block's totals are `null` and its `flagged` is **`null`, not `false`**.
   `conditional.reference` expresses the same thing through its existing
   `read_rate_state` ladder and `safe_overflow: null` (§4.5). Consumers branch
   on `flagged is None` before truthiness.
4. **Unmeasurable is never zero.** A surface that could not be read, resolved,
   or enumerated contributes to `surfaces_unmeasured` and carries a `state`
   naming why. It **never** contributes `0` to a total and **never** produces a
   `flagged: false` that reads as an all-clear. This is
   `_reference_shelf`'s §6.3 rule generalized, and it is the fail-open class
   the ledger has already recorded three times (`lrn-ea833a5b`,
   `lrn-6d21607e`, `lrn-fc481dcb`).
5. **Totals over partial data are labeled.** Any total computed while
   `surfaces_unmeasured > 0` is a **lower bound**, and both the JSON (a
   `totals_are_lower_bound: true` flag) and the text render say so — the same
   phrasing discipline `report.py:798-802` already applies to `flush_state`.
6. **Every threshold is a named module constant with a `# PLACEHOLDER`
   comment** citing that it is calibrated on one host's single 2026-08-22
   measurement, per the hub's sequencing constraint (*instruments first, gate
   strictness second, thresholds last or never*). Thresholds decide only
   whether `flagged` is `true`; nothing else in the system reads them.
   **Exempt: `TOKENS_PER_WORD_EST` is an estimator, not a threshold** — it is
   read by every `_tokens_est` call and gates no flag (all seven real
   thresholds are words, shares, or percentage points, never token figures).

**Location.** All four land under ONE new top-level `report --json` key,
`context_budget`, produced by a new `report.py` function
`context_budget(home, today, *, flush_state="not-attempted")` and wired into
`gather` beside `reference_shelf` (`report.py:668`). `gather`'s existing keys
are byte-unchanged.

```
"context_budget": {
  "generated_for": "<YYYY-MM-DD>",
  "tokens_per_word_est": 1.33,
  "budget":      { … §4.1 … },
  "crowding":    { … §4.3 … },
  "composition": { … §4.4 … },
  "growth":      { … §4.4.3 … },
  "conditional": { … §4.5, §4.6 … }
}
```

### 4.1 The word/token estimator (shared by all signals)

```python
#: PLACEHOLDER, calibrated against the 2026-08-22 host measurement so the
#: report's figures stay directly comparable to the research table (6,545 w ->
#: ~8,700 tok). NOT a tokenizer: this unit adds no dependency (the CLI's only
#: runtime dep is ruamel.yaml).
TOKENS_PER_WORD_EST = 1.33

def _words(text: str) -> int:
    """The ONE word count in this unit — whitespace split, matching
    compilers.compile_managed_text's `len(e.split())` exactly (compilers.py:304)
    so a managed share is a ratio of like to like."""
    return len(text.split())

def _tokens_est(words: int) -> int:
    return round(words * TOKENS_PER_WORD_EST)
```

**Naming pin:** every emitted token figure ends in `_est`. There is no field
named `tokens`. A reader must never be able to mistake the estimate for a
measurement.

### 4.2 Signal (a) — `budget`: the true budget report

**The question it answers:** what does the whole always-on surface cost, and
how much of that is ours?

```
"budget": {
  "severity": "informational",
  "window_days": 30,
  "surfaces": [ <row>, … ],

  "session_baseline_words": int | null,      # user surfaces + skill descriptions
  "session_baseline_tokens_est": int | null,
  "largest_project_words": int | null,       # the single biggest project row
  "largest_project_key": str | null,
  "session_max_words": int | null,           # baseline + largest project
  "session_max_tokens_est": int | null,

  "project_rows_total": int,
  "all_hosts_words": int | null,             # diagnostic ONLY, never compared
  "surfaces_total": int,
  "surfaces_measured": int,
  "surfaces_unmeasured": int,
  "totals_are_lower_bound": bool,            # true iff surfaces_unmeasured > 0
  "flagged": bool | null
}
```

Each `<row>`:

```
{
  "surface": "user-claude-md" | "project-claude-md" | "skill-descriptions" | "unpathed-rules",
  "key": str,                  # identity; see the table below
  "load_class": "unconditional",
  "state": "ok" | "absent" | "unreadable" | "not-registered" | "corrupt-markers",
  "file_words": int | null,
  "file_tokens_est": int | null,
  "managed_words": int | null,
  "managed_entries": int | null,
  "managed_share": float | null,       # managed_words / file_words, 3 dp
  "flagged": bool
}
```

**`key` per surface:**

| `surface` | `key` |
|---|---|
| `user-claude-md` | the literal `"~/.claude/CLAUDE.md"` — the tilde form, never an expanded absolute path (this report is pasted into public issues) |
| `project-claude-md` | the bucket slug's **8-hex sha256 digest alone** — the ruling U-readref §5.2.1 already made for exactly this reason on this host; the readable slug is a mangled `$HOME` path |
| `skill-descriptions` | the literal `"<skills-root>"` |
| `unpathed-rules` | `"<scope>:<topic-stem>"`, e.g. `"user:hooks"` |

**Computation, per surface:**

- **`user-claude-md`** — resolve exactly as `surface_fill` does:
  `_resolve_target(..., "claude-md", None, user_claude_md=…, check_dirty=False)`
  at user scope. `file_words = _words(target.read_text())`.
  `managed_words` / `managed_entries` from
  `compile_managed_text(text, _compile_set(home, spec))` — **the compiler is
  the count authority, never a second section parser** (the
  `canon_read_roots()` no-reimplementation posture).
- **`project-claude-md`** — one row per **registered** project host
  (`load_hosts(home).projects`), same computation. An unregistered or
  vanished host is a row with `state: "not-registered"` and every numeric
  field `null` — **never omitted**, because an omitted row is
  indistinguishable from a clean one.
- **`skill-descriptions`** — ONE row whose `file_words` is the **sum** of every
  description's word count across the **session skill index**,
  `~/.claude/skills/*/SKILL.md` (§2.11) — **never `skills_root`**, which is the
  route-target repo and covers 12 of 45 entries. Every entry is `resolve()`d
  and the set **deduped on the resolved path**, so a symlink and its target,
  or two index names pointing at one file, are counted once. The index
  directory being absent is `state: "absent"` with `file_words: null` — never
  a zero, and never silently skipped.

  **Extraction is two-tier, and the tier is emitted per skill.** Tier 1 is
  `_safe_load_leading_mapping` (`compilers.py`, the loader behind
  `has_paths_key`) — the real YAML answer. When it returns `None` or carries no
  string `description`, tier 2 is a **pinned lenient fallback**: from the
  leading `---` block, the `description:` line plus its indented continuation
  lines, whitespace-split. Tier 2 exists because tier 1 alone drops 4 live
  skills worth 492 words — 16% of the surface, and the largest descriptions in
  it (§2.11). A skill counted by tier 2 is reported, not hidden:
  ```
  "skills": [ {"name": str, "description_words": int,
               "description_tokens_est": int, "over_soft_max": bool,
               "extraction": "strict" | "lenient"}, … ],
  "skills_total": int,          # entries found in the index
  "skills_strict": int,
  "skills_lenient": int,
  "skills_unreadable": int      # neither tier produced a description
  ```
  sorted by `description_words` descending, then `name` ascending. Only
  `skills_unreadable` — a file unreadable/undecodable, or with no leading block
  at all — yields no `skills` entry, sets the row's `state` to `"unreadable"`,
  and sets the block's `totals_are_lower_bound`. **A non-zero `skills_lenient`
  does NOT set `totals_are_lower_bound`**: those words are counted, and
  labelling a counted word as missing would be its own dishonesty. The text
  render names the lenient count when it is non-zero, so a reader knows which
  arithmetic produced the figure.

  `managed_words`/`managed_entries`/`managed_share` are `null` — a description
  has no managed section, and a zero there would read as "we contribute
  nothing", which is the exact falsehood this row exists to correct.
- **`unpathed-rules`** — one row per stem in `_rules_cofire(rules_dir)["unpathed"]`
  for each resolvable rules dir (user via `_user_rules_dir`, project via
  `_project_rules_dir`). `file_words` is the topic file's whole text.
  `managed_*` are `null` (a rules topic carries no marker pair).

**Degradation** is `surface_fill`'s, verbatim: every read/resolve is inside one
`try` catching `VerbError | CompileError | HostsError | OSError |
UnicodeDecodeError`; the failure maps to a `state` and nulls the numerics. It
never propagates — one broken target must not blank the whole report.

#### 4.2.1 No session pays every project host (M4)

The r1 draft summed one row per registered host into a single
`always_on_words`. That is not a load any session bears: **a project
`CLAUDE.md` loads only inside its own repo.** Measured 2026-08-23 through
`hosts.load_hosts` — 5 registered projects, all with a `CLAUDE.md`:
claude-skills 1,719 · zmk-config-offsetkey 87 · keyboards 1,546 · `~/.config`
9,723 · nsys-marketplace 4,671 = **17,746 w**. Added to user (3,355) and skill
descriptions (~3,099), the naive sum is **~24,200 w** — permanently past any
sane advisory from day one, and §6.4's "largest surface" would forever name
`~/.config/CLAUDE.md`, which loads in exactly one repo.

So the compared quantity is a **per-session** view:

- `session_baseline_words` = user `CLAUDE.md` + skill descriptions + unpathed
  rules — **the surfaces every session pays**. Live: 3,355 + ~3,099 + 0 ≈
  **6,454 w**.
- `largest_project_words` / `largest_project_key` = the single biggest `ok`
  project row (live: `~/.config`, 9,723 w).
- `session_max_words` = baseline + largest project — the **worst** single
  session, live ≈ **16,177 w**.
- `all_hosts_words` is retained as a **diagnostic only** and is compared to
  nothing. The text render must label it "not a session cost".

Per-host rows stay in `surfaces` individually, so the human can still see
every project's size; they are simply never summed into the compared figure.

**Threshold:**

```python
#: PLACEHOLDER — the measured per-session BASELINE is ~6,454 w (user +
#: skill descriptions), 2026-08-23, one host. Deliberately just above it, so a
#: healthy baseline is quiet and real growth trips it. Compared against
#: `session_baseline_words`, never against a sum of hosts no session loads.
SESSION_BASELINE_WORDS_ADVISORY = 7000
```

`budget.flagged` is `true` iff
`session_baseline_words >= SESSION_BASELINE_WORDS_ADVISORY`. A row's `flagged`
is `true` iff it is the largest `file_words` among `ok` **baseline** rows and
the block is flagged — a project row is never the thing that flags the block.

#### 4.2.2 The all-blind form (M7)

`session_baseline_words` = the sum of `file_words` over **baseline** rows with
`state == "ok"`. Rows in any other state contribute nothing and are counted in
`surfaces_unmeasured`.

**When `surfaces_measured == 0`, every total is `null` and `flagged` is
`null`** — not `0`, not `false`. A tri-state `flagged` is the whole point:
`false` means "measured, under the advisory", `null` means "we could not see
the surfaces at all", and collapsing those two is the fail-open this unit is
built against. `totals_are_lower_bound` is `true` whenever
`surfaces_unmeasured > 0`, including the all-blind case.

Every consumer — the text render, §6.4's budget card, the UI — must branch on
`flagged is None` before `flagged` truthiness. T2.11 is the all-blind fixture.

### 4.3 Signal (b) — `crowding`: report-only near-duplicate pairs

**The question it answers:** is one always-on surface accumulating entries that
say near-enough the same thing that consolidating them is the honest fix?

#### 4.3.1 It reports pairs; it invokes nothing (B2)

The r1 draft emitted a `merge_offer` naming
`self-learn route <survivor> --collapse <cluster-id>`. **That action is
structurally impossible for the records this signal sees**, verified twice:

- crowding pairs come from `_compile_set` — **routed** records only
  (`verbs.py:1836`; `_eligible` filters to `status == "routed"`,
  `compilers.py:278`). `_load_cluster` (`verbs.py:2559-2564`) raises
  `VerbError` unless **every** member is still in `pending/`:
  *"cluster … is invalidated: member … is no longer pending"*.
- independently, `remove_proposal_siblings` (`ledger_ops.py:2029-2036`)
  **deletes every `merge-*.yaml` naming a record at resolution**, so the
  "a matching `merge-*.yaml` already exists" branch could never be reached for
  a routed record either.

The r1 draft's only action-offering signal offered an action that refuses. So
the signal is now **purely report-only**, consistent with §4.0.1: it emits
pairs and scores, and **names no verb and mints no `cluster_id`**. The
`merge_offer` field, the "existing `merge-*.yaml`" branch, and T3.6's first leg
are **deleted**.

**The consolidation path for routed records, documented as prose in §6.4** —
not invoked here, and not a new verb: capture a single rewritten record that
covers both lessons and link it to one predecessor with
`teach --supersedes <lrn-id>`; routing that replacement resolves that
predecessor (`teach.py:160`, `teach.py:583-586`, `records.py:441-447`); each
remaining member is then retired individually through the review flow's
existing vocabulary (`self-learn graduate <id>`, `commands/review.md:116-118`).

> **Pinned arity constraint — do not write the repeated-flag form.**
> `--supersedes` is **single-valued** (`teach.py:160`: no `action="append"`),
> and `Record.supersedes` is a **scalar** `str | None`
> (`records.py:326-327`, `records.py:441-447`). `teach --supersedes <a>
> --supersedes <b>` does **not** merge two records: argparse silently keeps
> only the last value, so `a` stays routed and live while `b` is superseded —
> a silent half-merge, the same class of defect as the impossible verb above.
> Neither the spec, the card text, nor any test may use that form.

#### 4.3.2 The scorer, and why the corpus is the global pool (B3)

The r1 draft said "the imported scorer" and scored pairs **within one compile
set**. Both halves were wrong, and the second is fatal:

- `idf` and `sum_idf` are **closures inside `cluster_candidates`**
  (`worker.py:420-431`). Only `_tokens` (`worker.py:2718`) is module-level, so
  there was nothing to import.
- IDF over a corpus of size *n* gives every token shared by both members
  `df == n`, hence `idf = log(n/df) = log(1) = 0`. **A 2-record corpus can
  never produce a non-zero pair score.** Reproduced on the r1 draft's own
  T3.1 fixture: **0.0** with the compile set as corpus, **0.131** with a
  42-document pool. T3.1 as written could not trip its own signal.

**Chosen: option (a) — factor the arithmetic out, keep one definition.**

```python
# worker.py — NEW, module-level. cluster_candidates' closures are replaced by
# calls to this, so there is exactly one IDF-cosine in the codebase.
def pair_similarity(tokens_a: set, tokens_b: set,
                    doc_freq: dict[str, int], n_docs: int) -> float:
    ...
```

The crowding signal builds `doc_freq` / `n_docs` over **the same global pool
`cluster_candidates` uses** — every pending record in every bucket (including
deferred) plus every resolved record with `status == "routed"`
(`worker.py:397-413`) — then scores unordered pairs **whose members are both in
the target's compile set**.

*Why (a) over (b) — calling `cluster_candidates(home, batch)` and filtering:*
its return is per-record candidate lists already floored **and capped at
`CANDIDATE_CAP = 5`**, so a pair below one record's cutoff but above the
other's would appear asymmetrically, and the cap would silently truncate the
crowding view — a signal quietly reporting fewer pairs than exist is this
unit's own fail-open class. It would also make `report` depend on `batch`, a
worker-queue concept with no meaning there. Option (a) shares the arithmetic
without inheriting the per-record ranking policy.

#### 4.3.3 Shape

```
"crowding": {
  "severity": "informational",
  "score_floor": 0.20,
  "source": "worker.pair_similarity",
  "corpus": "global-pool",
  "corpus_docs": int | null,
  "surfaces": [
    {
      "surface": "user-claude-md" | "project-claude-md",
      "key": str,
      "state": "ok" | "unreadable" | "not-registered" | "too-few-entries",
      "entries_considered": int | null,
      "pairs": [ {"a": "lrn-…", "b": "lrn-…", "score": float} , … ],
      "pairs_total": int | null,
      "flagged": bool
    }, …
  ],
  "surfaces_total": int,
  "surfaces_measured": int,
  "surfaces_unmeasured": int,
  "flagged": bool | null
}
```

Pairs at or above the floor, sorted by `score` descending then `(a, b)`
ascending, list capped at 5 with the uncapped count in `pairs_total`.
`state: "too-few-entries"` when the compile set has fewer than 2 records —
distinct from `ok` with zero pairs, because "nothing to compare" and
"compared, found nothing" are different facts and only one is reassuring.
Per M7, `surfaces_measured == 0` ⇒ `flagged: null`.

**Threshold:** `flagged` is `true` iff `pairs_total >= 1`. No second threshold
on top of the floor — a second calibration is what the hub's clustering note
warns against.

### 4.4 Signal (c) — `composition`: managed share trending up

**The question it answers:** is the machine-managed share of a hand-authored
file growing, and is the shelf drifting toward pure prohibition?

Two sub-facts, one block. The second exists because **a file can shrink in
words and get worse**: cutting the five most verbose non-caution entries lowers
the word count and raises the caution ratio. Every instrument in the system
today reports entries and words; none reports what *kind* of instruction the
entries are.

```
"composition": {
  "severity": "informational",
  "window_days": 30,
  "window_start": "<YYYY-MM-DD>",
  "past_is_lower_bound": true,
  "surfaces": [
    {
      "surface": "user-claude-md" | "project-claude-md",
      "key": str,
      "state": "ok" | "absent" | "unreadable" | "not-registered",
      "managed_share": float | null,
      "managed_words": int | null,
      "managed_words_30d_ago": int | null,
      "managed_words_delta_30d": int | null,
      "managed_share_growth_30d_pp": float | null,
      "managed_share_30d_ago": null,
      "kind_mix": {"anti-pattern": int, "surface-rule": int,
                   "reasoning-pattern": int, "unclassified": int} | null,
      "caution_share": float | null,
      "flagged": bool,
      "flagged_by": ["share"] | ["growth"] | ["caution"] | [combinations] | []
    }, …
  ],
  "surfaces_total": int,
  "surfaces_measured": int,
  "surfaces_unmeasured": int,
  "flagged": bool | null
}
```

#### 4.4.1 How the past is reconstructed, and what that costs

There is **no history of `file_words`** anywhere — the hand-authored prose has
no ledger, and the `surface-budget` telemetry plane keys on the *destination
enum*, not the file (§2.6). So `managed_share_30d_ago` is **pinned to `null`**,
permanently, with the reason stated in the field's own docstring. A builder
must not synthesize it.

What **is** derivable, deterministically and without new state: recompile the
section from the subset of the compile set whose `routing.routed_at` is at or
before `window_start`, and count its words with `compile_managed_text` — the
same pure function, no second parser.

```python
from .compilers import _iso   # compilers.py:272, private — the SAME helper
                              # `_eligible` (compilers.py:278) sorts with, so
                              # the window split and the compile order can
                              # never disagree about a timestamp's string form.

past_set = [r for r in compile_set
            if _iso((r.routing or {}).get("routed_at") or "") < WINDOW_START_ISO]
managed_words_30d_ago = compile_managed_text("", past_set).word_count
```

**N8 boundary convention, pinned once for the whole unit:** the window is
**half-open** — `[window_start, today]`. A route timestamped exactly at
`window_start` is **IN** the window (recent), never in the past set. That is
why the comparison above is `<` and not `<=`. `growth`'s `new-skill` half
(§4.4.3) uses the same rule, so the two halves of
`always_on_words_added_30d` can never double-count or drop a route that lands
on the boundary instant. T5.7 pins it on both halves.

**The bias, stated because it must be:** records **retired** since the window
start (superseded, graduated, rejected) are not in today's compile set, so the
reconstruction under-counts the past. `managed_words_30d_ago` is therefore a
**lower bound** and `managed_words_delta_30d` an **upper bound**. That is why
`past_is_lower_bound: true` is an emitted field and not a comment — the text
render prints it whenever any delta is non-null. Overstating growth in a
report-only signal is the safe direction; silently overstating it is not.

`managed_share_growth_30d_pp` = `100 * managed_words_delta_30d / file_words`,
1 dp — "how many percentage points of *today's* file the managed block added
in the window". `null` when `file_words` is 0 or unmeasured. The denominator is
today's file deliberately: it is the only denominator that exists.

#### 4.4.2 The composition half

`kind_mix` counts `record.kind` over the compile set, using
`records.KINDS` (`records.py:56`). A record with no `kind` (knowledge records
carry none) counts as `"unclassified"` — **never** silently folded into a
behavior kind.

`caution_share` = `anti-pattern / (anti-pattern + surface-rule +
reasoning-pattern)`, 3 dp; `null` when that denominator is 0. Unclassified
records are excluded from the ratio and visible in `kind_mix`, so a shelf that
is mostly knowledge records cannot masquerade as a low-caution one.

#### 4.4.2b The three composition thresholds, pinned

Per rule §4.0.5, every threshold is a named module constant. `composition` has
three, and each drives exactly one token in `flagged_by`:

```python
#: PLACEHOLDER. The user CLAUDE.md measured 77% managed on 2026-08-22 and trips
#: this immediately — which is correct and is the point: it is report-only.
COMPOSITION_SHARE_ADVISORY = 0.50            # -> flagged_by "share"

#: PLACEHOLDER. 10 percentage points of today's file added inside one 30d
#: window. No prior series exists to calibrate against; revisit once the first
#: three windows of real data have run.
COMPOSITION_GROWTH_PP_ADVISORY = 10.0        # -> flagged_by "growth"

#: PLACEHOLDER. The conservatism tax is directional evidence, not a measured
#: magnitude for this shelf: an anti-hallucination instruction cost one model
#: 89.0% -> 72.0% literal extraction (arXiv:2601.02023) while barely moving
#: another. Nobody has measured what a shelf of N cautions compounds to, so
#: this number flags a composition worth LOOKING at, never one worth refusing.
COMPOSITION_CAUTION_ADVISORY = 0.75          # -> flagged_by "caution"
```

Comparison operators are pinned as `>=` for all three; T4.3 / T4.4 / T4.7 sit
on the trip side and T4.5 on the quiet side of the same boundaries, so a
builder cannot flip an operator without a test going red.

`flagged_by` is a **list**, ordered `["share", "growth", "caution"]` filtered to
the triggers that actually fired — so a row flagged by two independent
mechanisms says which two, and an empty list is the only representation of "not
flagged". A row whose `state` is not `"ok"` carries `flagged: false` and
`flagged_by: []`, and is counted in the block's unmeasured tally rather than
reading as a clean row (rule §4.0.3).

#### 4.4.3 Signal (d) — `growth`: the growth-rate alarm

Same reconstruction technique, aggregated across **all** of Class A, plus the
one door the old cap treated as free.

```
"growth": {
  "severity": "informational",
  "window_days": 30,
  "window_start": "<YYYY-MM-DD>",
  "past_is_lower_bound": true,
  "managed_words_added_30d": int | null,
  "new_skill_routes_30d": int,
  "new_skill_description_words_added_30d": int | null,
  "always_on_words_added_30d": int | null,     # BASELINE surfaces only
  "session_baseline_words": int | null,        # the matching denominator
  "doubling_days_est": float | null,
  "threshold_words_per_30d": 750,
  "flagged": bool,
  "totals_are_lower_bound": bool
}
```

- `managed_words_added_30d` — sum of `managed_words_delta_30d` over `ok`
  Class A rows.
- `new_skill_routes_30d` — count of live records with
  `routing.destination == "new-skill"` and `routing.routed_at` inside the
  window. Sourced from the ledger walk `gather` already performs.
- `new_skill_description_words_added_30d` — for each such route, the word count
  of the **current** `description` of the skill named by `routing.new_skill`,
  counted **once per distinct skill** (a second lesson routed into an existing
  skill mints no new description — §5.2). A skill whose SKILL.md is now
  unreadable or gone contributes nothing and sets
  `totals_are_lower_bound`.
- `always_on_words_added_30d` = the two above, summed. `null` if either is
  `null`. **Only baseline surfaces contribute** (user `CLAUDE.md`, skill
  descriptions, unpathed rules) — per §4.2.1 a project host's growth is not a
  cost every session pays, and folding it in would make the rate as
  meaningless as the naive sum was.
- `doubling_days_est` = `round(30 * session_baseline_words /
  always_on_words_added_30d, 1)` when the addition is `> 0` — **the baseline is
  the denominator**, matching the numerator's scope; mixing an all-hosts
  numerator with a baseline denominator (or vice versa) yields a number with no
  referent. **`null`** when the addition is `0` or negative, and when
  `session_baseline_words` is `null` — a doubling time for zero growth is not
  "infinity", it is undefined, and emitting a sentinel invites a consumer to
  sort on it.

```python
#: PLACEHOLDER — ~11.5%/30d against the 6,545 w measured baseline, i.e. a
#: linear doubling in ~9 months. One host, one measurement, 2026-08-22.
GROWTH_ALARM_WORDS_PER_30D = 750
```

`flagged` is `true` iff `always_on_words_added_30d >= GROWTH_ALARM_WORDS_PER_30D`.

### 4.5 `conditional.reference` — the read-rate report (consumes U-readref)

This unit **does not redesign `reference_shelf`**. It adds exactly one derived
thing that block does not carry: a **verdict on whether `reference` is a safe
overflow target right now**, which is the judgment the routing decision and the
review flow actually need.

A new **public** function in `report.py`:

```python
def reference_read_verdict(home, today, *, flush_state="not-attempted") -> dict:
    """One call to _reference_shelf (report.py:291), reduced to the verdict.
    Reads nothing else; derives no count of its own."""
```

```
"conditional": {
  "reference": {
    "source": "reference_shelf",
    "read_rate_state": "not-instrumented" | "none-enumerable"
                     | "no-reads-observed" | "partly-cold" | "ok",
    "safe_overflow": true | false | null,
    "counts_are_lower_bound": bool,        # mirrors flush_state != "ok"
    "targets_total": int,
    "targets_zero_read": int | null,
    "records_on_zero_read_targets": int | null,
    "reads_30d_total": int | null,
    "why": str,
    "severity": "informational"
  },
  …
}
```

**The state ladder, evaluated in this order (first match wins):**

| condition (read from `reference_shelf`) | `read_rate_state` | `safe_overflow` |
|---|---|---|
| `instrumented` is `false` | `not-instrumented` | **`null`** |
| `enumeration_state == "none-enumerable"` | `none-enumerable` | **`null`** |
| `targets_zero_read == targets_total` (all cold) | `no-reads-observed` | `false` |
| `targets_zero_read > 0` | `partly-cold` | `false` |
| otherwise | `ok` | `true` |

**The load-bearing rule, and the reason it is a table and not prose:**
`safe_overflow` is **`null`, never `false` and never `true`**, whenever the
shelf's reads are unobservable. An un-instrumented shelf must not read as an
unread one (`_reference_shelf`'s own §6.3), and equally must not read as a
healthy one. This is the same fail-open shape as a gate whose "pass" output is
identical to its "cannot see the target" output (`lrn-ea833a5b`) and a canary
pointed at a plausibly-named decoy (`lrn-6d21607e`). `null` is the honest third
value, and §7's T10.3 is the positive control that proves the code can produce
it.

`counts_are_lower_bound` mirrors `reference_shelf.flush_state != "ok"` — the
same phrasing `report.py:798-802` already prints.

`why` is one sentence built from the state by a pinned mapping (no free text at
the call site), e.g. for `not-instrumented`: *"read rate UNKNOWN — the refread
hook is not registered, so routing here trades a measured cost for an
unmeasured one."*

### 4.6 `conditional.rules_cofire` — the pathed-rules arrival signal

Consumes `_rules_cofire` (`verbs.py:1918`) unchanged — same function, same
symbolic intersection, same explicit upper-bound semantics on `max_fanin`.

```
"conditional": {
  "rules_cofire": {
    "severity": "informational",
    "threshold_max_fanin": 5,
    "scopes": [
      { "scope": "user" | "project",
        "key": str,                     # "~/.claude/rules" | project digest
        "state": "ok" | "absent",
        "topics": [str, …],
        "unpathed": [str, …],
        "pairs": [[str, str], …],
        "max_fanin": int,
        "max_fanin_is_upper_bound": true,
        "crowded": bool }, …
    ],
    "scopes_total": int,
    "scopes_measured": int,
    "scopes_unmeasured": int,
    "flagged": bool | null
  }
}
```

**What changes** is not the datum but its consequence. Today
`verbs.py:2087-2091` OR-s `max_fanin > 5` into `over_cap` with
`cap_reason = "rules-cofire"`. `over_cap` and `cap_reason` cease to exist
(§6.1), so the escalation becomes its own field:

- in `surface_fill`, `cofire_crowded: bool` (claude-md only) replaces the
  `over_cap`/`cap_reason` write;
- in `report`, `crowded: bool` per scope, and `flagged` = any `crowded`.

`max_fanin_is_upper_bound: true` is emitted, not documented-only: the function's
own docstring is explicit that pairwise intersection does not compose, and a
consumer reading `max_fanin: 7` without that flag will treat a bound as a
count.

**`unpathed` is dual-classed and that is deliberate:** the same list feeds
§4.2's `unpathed-rules` Class A rows (they load at launch) *and* rides here as
context for the co-firing arithmetic. One computation, two readers.

---

## 5. The description cap and `new-skill` charging

### 5.1 Cap the description, do not cap the body

The two halves of a SKILL.md have opposite economics: the frontmatter
`description` sits in every session's skill index (Class A); the body loads only
once the skill is selected (Class B).

The evidence forbids the intuitive move. Description quality gates whether a
skill **enters the candidate set**, but **body content dominates final
selection** — hiding the body costs **37–44 percentage points** of routing
accuracy (SkillRouter, arXiv:2603.22455). A fuller body routes *better*.
Capping it on words is counterproductive, and a word cap cannot tell padding
from rules anyway.

So:

- **`description`** gets a **soft, reported** ceiling (§5.3). Report-only.
- **body** gets **no ceiling of any kind** — its `entries`/`words` are reported
  as facts in `surface_fill` (§6.3) with `load_class: "conditional"`, and no
  threshold is applied to them anywhere.

### 5.2 Charging `new-skill` to the always-on budget

Routing a lesson to `new-skill` **creates a new permanent always-on cost** in
the shape of a new description, and the old cap treated that destination as
free. The live example is the `testing-methodology` skill self-learn itself
scaffolded: 104 managed words delivered on-invoke bought **76 always-on words,
forever** — a 42% always-on overhead on the transaction, invisible to every
instrument.

**The charging rule:**

- A `new-skill` route that **scaffolds** (first route; `NewSkillApplyResult.
  scaffolded` is `true`, `verbs.py:2348-2352`) charges
  `_words(scaffold_description(record))` — `skill_scaffold.py:52`.
- A `new-skill` route into an **existing** skill charges **0**. The description
  is not rewritten; only the managed body section grows, which is Class B.
  This is the fact that makes `new-skill` genuinely cheaper on the second
  lesson — and the report must show that, or reviewers will over-avoid a
  destination that is correct.
- The charge is reported at three places and nowhere else:
  1. `report --json` `.context_budget.growth.new_skill_description_words_added_30d`
     (§4.4.3), deduplicated per distinct skill;
  2. the verb's budget note (§6.2) — *"new-skill scaffolded: +N always-on
     description words (~M tokens est)"*, or *"new-skill: +0 always-on words
     (existing description unchanged)"*;
  3. the `budget.surfaces` `skill-descriptions` row's `skills` list, where the
     new skill now appears.

**Never** does the charge refuse, truncate, or rewrite. In particular the
builder **must not** truncate `scaffold_description` to fit
`DESCRIPTION_SOFT_MAX_WORDS` — a truncated description degrades routing for
that skill *and* is exactly the "convert a measured cost into an unmeasured
one" move this unit exists to refuse.

### 5.3 The soft description ceiling

```python
#: PLACEHOLDER. Live distribution, 45 skills in the session index, re-measured
#: 2026-08-23: ~3,099 w total, mean ~69 w; the scaffold's own output ~76 w;
#: long tail hypr-doctor 206, firecrawl-monitor 188, bitwarden-cli 161,
#: home-network 129, firecrawl-build 104, agentic-engineering 98. 80 sits just
#: above the scaffold and the mean, so it flags the tail, not the norm.
#: NOTE: four of those tail entries (bitwarden-cli, home-network,
#: firecrawl-build, agentic-engineering) are exactly the ones the strict YAML
#: loader cannot read (§2.11) — a strict-only build would flag none of them.
DESCRIPTION_SOFT_MAX_WORDS = 80
```

Emitted as `over_soft_max: bool` per skill in §4.2's `skills` list, and as a
block-level count. It sets nothing else. There is no refusal, no gate, no exit
code, and no UI red.

---

## 6. Retiring the old cap

### 6.1 What is deleted (not left inert)

A threshold left in place "just reporting" is precisely what trained the reader
to discount this one — measured: overridden twice in one evening. A dead
constant is also a zombie a future builder re-wires. So these are **deleted**,
not defaulted:

| symbol | file:line | disposition |
|---|---|---|
| `DEFAULT_MAX_ENTRIES` | `compilers.py:170`, `__all__` `:129` | **deleted** |
| `DEFAULT_MAX_WORDS` | `compilers.py:171`, `__all__` `:130` | **deleted** |
| `SectionResult.over_cap` | `compilers.py:204` | **deleted** |
| `SectionResult.cap_reason` | `compilers.py:205` | **deleted** |
| `max_entries` / `max_words` params | `compilers.py:289-294`, `:349-354` | **deleted** |
| the same params in `chezmoi.py` | `chezmoi.py:274-275`, import `:55-56` | **deleted** |
| `VerbResult.over_cap_note` | `verbs.py:294-303` | **replaced** by `budget_note` (§6.2) |
| `NewSkillApplyResult.over_cap` / `.cap_reason` | `verbs.py:2359`, `:2363` | **deleted** |
| the `over_cap`/`cap_reason` writes in `surface_fill` | `verbs.py:2051`, `:2053-2054`, `:2090-2091` | **replaced** (§6.3) |
| the `SURFACE_FILL_CAPPED_DESTINATIONS` doc comment | `verbs.py:208-212` | **rewritten** — it currently calls `reference` "the cap-free overflow sink" carrying "no 'fill against a cap' to report", both false after this unit. The *probe* prohibition it also states survives verbatim (§6.3); only the cap framing goes. |

**Kept, because they are facts and the budget report consumes them:**
`SectionResult.entry_count` (`compilers.py:202`) and `SectionResult.word_count`
(`compilers.py:203`). The `compilers.py:32-36` module docstring's Overflow
paragraph is rewritten to describe counting-without-a-threshold.

**Telemetry:** `verbs.py:2337-2343`'s `surface-budget` event keeps its kind and
its `target`/`words` fields (`EVENT_KINDS` is untouched) and **drops the
`overflow` payload key** — `spool_quiet` already omits `None`, so passing
nothing is the whole change. Historical events retain `overflow`; no reader in
this unit consumes it.

### 6.2 `budget_note` — a fact, not a warning

```python
def budget_note(self) -> str | None:
    """The post-route budget FACT. Never imperative, never the token
    'WARNING'. None when there is no compile result to describe."""
```

Shape, one line, no leading severity word:

```
budget: claude-md section now holds 23 entries / 2,597 words · ~/.claude/CLAUDE.md is 3,355 words (~4,460 tokens est) · managed share 77%
```

and for a scaffolding `new-skill` route, appended after ` · `:
`new-skill scaffolded: +76 always-on description words (~101 tokens est)`.

Rules:

- It is printed to **stderr** at the same two call sites the old note used —
  `cli.py:1185` and `teach.py:756` — and it is a fact line, not a warning line.
- The word `WARNING` must not appear. §7's T13.2 greps for it.
- Where the whole-file read fails, the note degrades to the managed half alone
  and says so (`· surface size unavailable`) — it never omits the clause
  silently.
- The JSON verb envelope key `cli.py:1145` `"over_cap"` is **renamed** to
  `"budget"` carrying this string or `null`. This is a breaking envelope
  change; §8 lists every test that asserts on it.

### 6.3 The new `surface_fill` shape

`SURFACE_FILL_CAPPED_DESTINATIONS` is **renamed**
`SURFACE_FILL_PROBED_DESTINATIONS` (`verbs.py:213`) — the word "capped" is
false after this unit — with its value unchanged, `("skill-md", "claude-md")`.
`reference` still gets **no compile probe**: feeding `LEARNINGS.md` to
`compile_managed_text` would bootstrap a marker pair that does not belong
there. That prohibition (08 §1 F1) stands verbatim.

Per probed destination:

```
{
  "entries": int,
  "words": int,
  "load_class": "unconditional" | "conditional",   # claude-md | skill-md
  "file_words": int | null,
  "file_tokens_est": int | null,
  "managed_share": float | null,
  "rules_topic_count": int,          # claude-md only, unchanged
  "rules_cofire": {…},               # claude-md only, unchanged shape
  "cofire_crowded": bool             # claude-md only — replaces the over_cap OR-in
}
```

Removed: `entries_cap`, `words_cap`, `over_cap`, `cap_reason`.

Plus a **new `reference` key** — the one place this unit widens the probe set,
and it is not a compile probe:

```
"reference": {
  "read_rate_state": …, "safe_overflow": true|false|null, "why": str,
  "targets_zero_read": int|null, "targets_total": int
}
```

sourced from `report.reference_read_verdict` via a **deferred import**
(same-family reuse, the idiom `report.py:275` already uses for `selfcheck`),
and **memoized in the `cache` dict `surface_fill` already threads**, under the
key `("refread", home.resolve())` — a shape that cannot collide with a target
path, mirroring the existing `("cofire", rules_dir.resolve())` key
(`verbs.py:2082-2085`). One computation per CLI invocation. The existing
degradation `try` covers it: any failure omits the `reference` key entirely.

The existing `_resolve_target(..., check_dirty=False)` posture, the
`_compile_set` compile-authority rule, the pending-record exclusion (F8), and
the omit-on-VerbError rule (F5) are all unchanged.

### 6.4 What the review flow gets instead of the graduation card

`02-schema.md:504-508` promises: *at the cap … the next review session opens
with a graduation card.* `commands/review.md:131-133` implements that trigger.
Both are retired and replaced as follows.

**Retired:** the over-cap-triggered graduation opener.
**Untouched:** the `already_canon: true` → **Graduate** card
(`review.md:116-120`) and the merge cards (`review.md:135+`). Those have their
own triggers and are not cap-derived.

**New — the budget card.** Placement is pinned, because `commands/review.md`
already puts the **M2 merge-card block at `:135`** "before the per-record
cards" — two things claiming one slot is how a builder invents an order. The
sequence in the batch is:

1. the **budget card** (this unit) — at most one, batch-level context;
2. the existing **M2 merge cards** (`review.md:135+`) — cluster-level,
   unchanged by this unit;
3. the **per-record cards**.

Rationale: the budget card frames *why* consolidation is being suggested at
all, and the merge cards are the per-cluster instance of that. Reversing them
makes the merge cards arrive without their motivation. In `commands/review.md`
the new block is inserted **immediately before** the `**Merge cards (M2).**`
heading, and that heading's own "Before the per-record cards" wording is
amended to "After the budget card, before the per-record cards" so the two
blocks cannot both claim to be first.

The card body:

> Run `self-learn report --json` and read `.context_budget`. If **any** signal
> carries `flagged: true`, open the batch with **one** budget card — never one
> card per signal. The card **states the flagged facts and offers**; it never
> demands, never blocks, and is dismissible with no action.
>
> Offers, in this order, and only for signals that are actually flagged:
>
> - **`crowding` flagged** → **state the near-duplicate pairs and their
>   scores.** Do **not** offer `route --collapse`: those records are routed,
>   and the collapse path refuses anything not still pending
>   (`verbs.py:2559-2564`), so the offer would be an action that cannot run.
>   Describe the consolidation path in prose instead: capture one rewritten
>   record covering both lessons, linked to one predecessor with
>   `self-learn teach … --supersedes <lrn-id>` (**one id — the flag is
>   single-valued and the field is scalar; never repeat it**), route it, then
>   retire each remaining member individually with `self-learn graduate <id>`.
>   The human runs these; the card runs nothing.
> - **`composition` flagged** → offer **Graduate**
>   (`self-learn graduate <id>`) for the named oldest entries, showing
>   `managed_share`, `managed_share_growth_30d_pp`, and `caution_share`. State
>   `past_is_lower_bound` when any delta is shown.
> - **`growth` flagged** → state the rate and `doubling_days_est`. **Offer
>   nothing.** There is no per-record action for a rate; it is a fact for the
>   human, and manufacturing an action for it would re-create the cap.
> - **`budget` flagged** → state `session_baseline_words` /
>   `session_baseline_tokens_est` and the largest **baseline** surface, then
>   `session_max_words` with `largest_project_key` named as the project that
>   would add it. **Never quote `all_hosts_words` as a session cost** — if it
>   is shown at all, label it "not a session cost". If
>   `totals_are_lower_bound`, say so.
>
> **Tri-state, before any of the above:** a signal whose `flagged` is `null`
> is **not** an all-clear. Say "could not measure" and name the states from
> `surfaces_unmeasured` / the row `state` values. A card that renders `null`
> as quiet is the exact fail-open §4.0.3 forbids.
>
> **The constraint that rides on every offer:** read
> `.context_budget.conditional.reference.safe_overflow`. When it is `false` or
> `null`, the card **must not** suggest "route it to references instead" as the
> relief. Quote `.why`. Routing to an uninstrumented or cold shelf trades a
> measured cost for an unmeasured one, and that is the move this whole redesign
> exists to refuse.
>
> **A signal is never a reason to refuse a route.** If the human routes into a
> flagged surface after reading the card, that is a correct outcome and the
> verb behaves identically to an unflagged route.

That last inversion is the substance of the replacement: the old flow made the
reference shelf the escape hatch the cap pushed you toward; the new flow makes
the shelf's **measured read rate a precondition for recommending it**.

### 6.5 Doc edits the builder must make

| doc | what changes |
|---|---|
| `02-schema.md:504-508` | the **Overflow rule** paragraph is replaced by a *Budget reporting* paragraph: the compiler counts entries and words and reports them; there is no threshold; the signals live in `report --json .context_budget`; the graduation opener is replaced by §6.4's budget card. The 2026-07-18 Y-20 cross-reference paragraph that follows it is updated to the §6.3 field names and loses the "cap-free overflow sink" framing for `reference`. |
| `01-architecture.md:385` | the risk row's mitigation column: "mechanical cap — 10 entries/~150 words — with graduation cards" → the four report-only signals + the routing gate (#6) as the upstream half. |
| `09-surface-spec.md:335-364` (Y-20) | the Why region still is the single budget surface; the fill sentence now carries `load_class` and `managed_share`; the `reference` line stops being template-static (§6.6); the "escalation is the existing 02 §4 over-cap WARNING" clause is replaced by a pointer to §6.4. |
| `commands/review.md:131-133` | replaced by §6.4's budget-card block. |
| `10-surface-build-plan.md:639-676` | the U17 rows describing `entries_cap`/`words_cap`/`over_cap` get a dated amendment naming U-cap and the new field set. Historical text is amended, never rewritten — the house convention in that file. |

### 6.6 UI changes

- `models.py:530-534` `REFERENCE_NO_CAP_LINE` is **deleted**. The `reference`
  budget row is now a CLI-datum row like the others, rendered from
  `surface_fill["reference"]`. Its template text for the three interesting
  states, verbatim:
  - `not-instrumented` / `none-enumerable` (`safe_overflow is None`) →
    *"reference read rate is UNKNOWN (not instrumented) — routing here trades a
    measured cost for an unmeasured one."*
  - `no-reads-observed` / `partly-cold` → *"N of M reference targets have never
    been read — this shelf may be coverage that isn't."*
  - `ok` → *"every reference target has been read at least once (N reads/30d)."*
  When the `reference` key is **absent** (degraded leg), the row is **omitted**
  entirely — the F5 posture, never a placeholder.
- `models.py:1710-1711` `_NEAR_ENTRIES_HEADROOM` / `_NEAR_WORDS_RATIO` are
  **deleted** — both are cap-relative and there is no cap.
- `models.py:1714` `_budget_text` is rewritten to state the fill fact plus the
  load class, e.g. *"this claude-md section holds 23 entries / 2,597 words — 77%
  of a 3,355-word always-on file"*, and for `skill-md`, *"…— on-invoke content,
  not always-on"*. No nearness clause, because there is nothing to be near.
- `BudgetRow.over_cap` (`models.py:1556`) → `BudgetRow.flagged`, defaulting
  `False`; `detail.html:177`'s `surface-budget-over-cap` class →
  `surface-budget-flagged`, styled as a neutral emphasis, **not** a warning.
- The resolution-evidence envelope's `over_cap` field (`routes.py:1419`,
  inside `_EVIDENCE_FIELDS` — `models.py:1556` is `BudgetRow.over_cap`, renamed
  by the bullet above, a different field) → `budget`; `evidence.html:70` renders it with the class
  `evidence-note`, **not** `evidence-warning`.

---

## 7. Tests

**The discipline these tests are designed against.** A signal that cannot fire
on a fixture built to trip it is the fail-open class — it reports SUCCESS when
the thing being checked is broken, which is the most dangerous shape a check
can take. Therefore **every signal gets three fixtures, not one**:

- **(+) a trip fixture** — built to make the signal fire; asserts `flagged is
  True` **and** asserts the specific numeric that drove it (never `flagged`
  alone, which a hardcoded `True` would satisfy);
- **(−) a quiet fixture** — structurally similar, below threshold; asserts
  `flagged is False` **and** that the numeric is present and correct;
- **(?) a blindness fixture** — the surface is unreadable / unresolvable /
  unenumerable; asserts the signal reports `null` and the appropriate `state`,
  and **explicitly asserts it is NOT `0` and NOT `False`**.

The (?) leg is the positive control. Without it, "0 surfaces over budget"
and "we could not see any surface" are the same output.

Suite: `uv run --project plugins/self-learn/cli pytest` and
`uv run --project plugins/self-learn/ui pytest`. New CLI file
`plugins/self-learn/cli/tests/test_context_budget.py`; UI assertions extend
`plugins/self-learn/ui/tests/test_models_detail.py`.

### T1 — the retirement is complete and irreversible-by-accident

1. `from self_learn import compilers; assert not hasattr(compilers, "DEFAULT_MAX_ENTRIES")` and the same for `DEFAULT_MAX_WORDS`.
2. `assert "DEFAULT_MAX_ENTRIES" not in compilers.__all__` (and `DEFAULT_MAX_WORDS`).
3. `SectionResult` field names contain neither `over_cap` nor `cap_reason`;
   `entry_count` and `word_count` are still present.
4. `inspect.signature(compile_managed_text).parameters` has no `max_entries` /
   `max_words`; same for `compile_managed_file` and the `chezmoi` wrapper.
5. `assert not hasattr(verbs.VerbResult, "over_cap_note")`.
6. Source-grep guard over `plugins/self-learn/cli/src` and
   `plugins/self-learn/ui/src`: zero occurrences of `over_cap`, `cap_reason`,
   `entries_cap`, `words_cap`, `DEFAULT_MAX_ENTRIES`, `DEFAULT_MAX_WORDS`,
   `REFERENCE_NO_CAP_LINE`, **`cap-free`**, and **`no cap`** — the last two
   catch the prose forms (`verbs.py:208-212`, `models.py:530-534`) that the
   identifier tokens miss (N6). **Positive control for the grep itself:** the same
   helper, run against a fixture string that *does* contain `over_cap`, must
   return a hit — otherwise a mis-rooted path search passes vacuously
   (`lrn-ca690038` / `lrn-ea833a5b`).
7. `assert "informational" == report.context_budget(...)["budget"]["severity"]`
   and a grep asserting no signal block in the payload carries any other
   `severity` value.

### T2 — `budget`: rows and totals (+ / − / ?)

- **T2.1 (+)** Fixture: user `CLAUDE.md` of 200 hand-authored words + a managed
  section compiled from 3 routed records. Assert `file_words == 200 + managed`,
  `managed_words` equals `compile_managed_text(...).word_count` exactly (not a
  recomputation in the test), `managed_share` to 3 dp, `state == "ok"`.
- **T2.2 (−)** `SESSION_BASELINE_WORDS_ADVISORY` not reached →
  `budget.flagged is False` **and** `session_baseline_words` is the exact
  expected int (assert the number, not just the flag).
- **T2.3 (+)** Fixture crossing `SESSION_BASELINE_WORDS_ADVISORY` →
  `flagged is True`, and exactly one row carries row-level `flagged` — the
  largest **baseline** row. Assert no project row is ever the flagged one.
- **T2.4 (?) blindness — unreadable target.** `chmod 000` (or an undecodable
  byte sequence) on the user `CLAUDE.md`. Assert: `state == "unreadable"`,
  `file_words is None`, `surfaces_unmeasured == 1`,
  `totals_are_lower_bound is True`, and **`session_baseline_words` does not
  include a 0 for that row** — verified by comparing against the same fixture
  with the row healthy (the two totals must differ by exactly that row's
  words, never by zero).
- **T2.5 (?) blindness — unregistered project host.** Assert a row exists with
  `state == "not-registered"` and nulls. **The row must not be omitted** —
  assert `len(rows_for("project-claude-md")) == 1`.
- **T2.6** `key` for `user-claude-md` is exactly `"~/.claude/CLAUDE.md"`; assert
  no row's `key` contains a `/home/` or `/Users/` prefix (the public-repo rule).
- **T2.7** `project-claude-md` `key` matches `^[0-9a-f]{8}$`.
- **T2.8** The skill-index row: a fixture index of 3 skills with 10/20/30
  description words → `file_words == 60`, `skills` sorted descending,
  `managed_words is None` (**assert `is None`, not `== 0`**).
- **T2.8a (B1, the tree control)** Build a fixture where the **session index**
  and `skills_root` disagree: index has 3 skills totalling 60 words;
  `skills_root` has 1 skill of 5 words. Assert `file_words == 60`. A build that
  globbed `skills_root` reports 5 and fails — this is the test that pins which
  tree is read, and without it B1 is undetectable.
- **T2.8b (B1, symlink resolution)** Index entries that are symlinks, two of
  them pointing at the **same** resolved SKILL.md → that skill is counted
  **once**; `skills_total` reflects the deduped set.
- **T2.9 (two-tier extraction)** Fixture carrying all three tiers: one
  well-formed description (strict), one whose description contains `": "` so
  YAML refuses it (lenient — model it on the four live cases in §2.11), and one
  file with no leading block at all (unreadable). Assert
  `skills_strict == 1`, `skills_lenient == 1`, `skills_unreadable == 1`; the
  lenient skill **is present** in `skills` with `extraction == "lenient"` and
  its real word count; `file_words` includes it. Assert
  `totals_are_lower_bound is True` (driven by the unreadable one) and — the
  load-bearing half — assert that a fixture with a lenient skill but **no**
  unreadable one has `totals_are_lower_bound is False`, proving lenient
  extraction is not mislabelled as missing data.
- **T2.9a (regression control for the 16% hole)** A strict-only implementation
  must fail this: assert the lenient skill's words are in `file_words`. Without
  it the build silently drops the largest descriptions (§2.11: 492 w, 16%).
- **T2.11 (?) all-blind (M7)** Every surface unmeasurable (no index dir, user
  target unreadable, no registered hosts). Assert `surfaces_measured == 0`,
  `session_baseline_words is None`, `session_max_words is None`, and
  **`flagged is None`** — explicitly `assert budget["flagged"] is None`, and
  `assert budget["flagged"] is not False`.
- **T2.12 (M4)** Fixture with 3 project hosts of 1,000/2,000/9,000 words plus a
  1,000-word baseline. Assert `session_baseline_words == 1000`,
  `largest_project_words == 9000`, `session_max_words == 10000`,
  `all_hosts_words == 13000`, and that `flagged` is decided by the **baseline**
  alone (set the advisory between 1,000 and 10,000 and assert `False`). A build
  that sums all hosts into the compared figure fails here.
- **T2.10** `tokens_est` == `round(words * 1.33)` on a fixture with a known
  word count; assert the field name ends `_est` and no field named `tokens`
  exists anywhere in the payload.

### T3 — `crowding` (+ / − / ?)

**Fixture rule that makes these tests possible at all (B3).** Scores are IDF
over the **global pool**. Shared tokens that are common in the pool score near
zero — reproduced live: the r1 fixture's shared tokens (`the`, `own`, `shell`,
`wrapper`, `matches`) scored **0.131** in a 42-doc pool, *below* the 0.20 floor,
and **0.0** with the compile set as corpus. So every (+) fixture must give its
two records shared tokens that are **rare in the seeded pool** (appearing in
those two records only), and must assert the **computed score against the
floor** — never a hardcoded expected float, which would pin an arithmetic
detail rather than the behavior.

- **T3.1 (+)** Seed a pool of ≥40 filler records with disjoint vocabulary, plus
  two routed records to the same `claude-md` sharing 3–4 rare tokens. Assert
  `pairs` non-empty, `score >= worker.CANDIDATE_SCORE_FLOOR`, `flagged is True`,
  and both ids present in the pair.
- **T3.1a (the corpus control — the test that would have caught B3)** Run the
  **same** two records with the crowding corpus forced to the compile set
  alone. Assert the score is `0.0` and no pair is emitted. This documents the
  degeneracy (`df == n ⇒ idf == 0`) as a property of the arithmetic, and any
  build that quietly scores within the compile set fails T3.1 instead.
- **T3.2 (−)** Two routed records with disjoint vocabulary in the same pool →
  `pairs == []`, `pairs_total == 0`, `flagged is False`, `state == "ok"`.
- **T3.3 (?)** Exactly one routed record → `state == "too-few-entries"`,
  `pairs_total is None`. Assert the **state**, not just the flag.
- **T3.3a (?) all-blind (M7)** No measurable surface → `surfaces_measured == 0`
  and **`flagged is None`**, asserted as `is None` and `is not False`.
- **T3.4 (scorer identity — must detect a reimplementation)** Monkeypatch
  **`worker.pair_similarity`** (the new module-level function, §4.3.2) to a
  sentinel returning `1.0` and assert every candidate pair is emitted. A build
  that inlines its own cosine still calls `_tokens` and would pass the r1
  version of this test; it cannot pass this one.
- **T3.4a** `cluster_candidates` still works after the factoring: its existing
  tests stay green, and a direct call returns the same candidates it did before
  (guards the "one definition" refactor from changing miner behavior).
- **T3.5** `score_floor` in the payload equals `worker.CANDIDATE_SCORE_FLOOR`;
  `len(pairs) <= 5` while `pairs_total` reports the uncapped count on a 7-pair
  fixture. Assert `corpus_docs` equals the seeded pool size — proving the global
  pool, not the compile set, was the corpus.
- **T3.6 (B2 — the impossibility guard)** The payload contains **no**
  `merge_offer` key, **no** `cluster_id`, and **no** string containing
  `--collapse`. Positive control: the same grep helper run against a fixture
  string containing `--collapse` must hit, so the negative assertion cannot
  pass vacuously.
- **T3.7 (B2 — arity)** A grep over the spec-derived card text and the CLI
  source asserts the substring `--supersedes` never appears twice in one
  command string. Guards the silent half-merge form.

### T4 — `composition` (+ / − / ?)

- **T4.1 (+)** Fixture: 4 records routed 60 days ago, 4 routed 5 days ago,
  file of 100 hand words. Assert `managed_words_30d_ago` equals the word count
  of the section compiled from the first 4 **only**, `managed_words_delta_30d`
  is the second 4's contribution, `managed_share_growth_30d_pp` matches the
  arithmetic to 1 dp, `past_is_lower_bound is True`.
- **T4.2** `managed_share_30d_ago is None` — always, on every fixture including
  the richest one. This field must never be synthesized.
- **T4.3 (+ share)** `managed_share >= 0.50` → `flagged is True` with
  `"share" in flagged_by`.
- **T4.4 (+ growth)** share below 0.50 but `managed_share_growth_30d_pp` past
  its threshold → `flagged is True` with `flagged_by == ["growth"]` — proving
  the two triggers are independent and neither is dead code.
- **T4.5 (−)** Low share, no recent routes → `flagged is False`,
  `flagged_by == []`, and `managed_words_delta_30d == 0` (a real zero here is
  correct — the surface WAS measured).
- **T4.6** `kind_mix`: a fixture with one of each `KINDS` value plus one
  knowledge record → counts of 1/1/1 and `unclassified == 1`;
  `caution_share == 1/3` to 3 dp (the knowledge record excluded).
- **T4.7 (+ caution)** 5 `anti-pattern` records and nothing else →
  `caution_share == 1.0`, `"caution" in flagged_by`.
- **T4.8 (?)** Unreadable file → every numeric `None`, `kind_mix is None`,
  `caution_share is None`, `state == "unreadable"`. Assert `caution_share is
  not 0.0`.
- **T4.9 word-count parity** — the section word count used by `composition`
  and by `budget` and by `surface_fill` on the same fixture are the **same
  integer**, sourced from `SectionResult.word_count`. A test that recomputes
  it independently and compares would be the second parser this spec forbids;
  instead assert equality across the three payload sites.

### T5 — `growth` (+ / − / ?)

- **T5.1 (+)** Managed growth of 500 w + two distinct `new-skill` scaffolds
  worth 150 w and 120 w in-window → `always_on_words_added_30d == 770`,
  `flagged is True` at `GROWTH_ALARM_WORDS_PER_30D = 750`.
- **T5.2 (−)** 700 w total → `flagged is False`, value exactly 700 (the
  boundary is `>=`; T5.1/T5.2 straddle it).
- **T5.3** `doubling_days_est` on a fixture with
  `session_baseline_words == 6000` and `added == 600` → `300.0` — and assert
  the denominator is the baseline by adding a 9,000-word project host to the
  same fixture and confirming the result is **unchanged** (a build using
  `all_hosts_words` or `session_max_words` gives a different number and fails).
- **T5.4** `added == 0` → `doubling_days_est is None`. **Assert `is None`, not a
  large float and not `0`.**
- **T5.5** A second lesson routed into an **existing** skill in-window →
  `new_skill_routes_30d == 2` but
  `new_skill_description_words_added_30d` counts that skill's description
  **once**. This is the dedup rule; a naive per-route sum double-counts.
- **T5.6 (?)** A `new-skill`-routed record whose skill dir has since been
  deleted → contributes nothing, `totals_are_lower_bound is True`.
- **T5.7 (N8, both halves)** A managed route AND a `new-skill` route both
  dated **exactly** at `window_start` are **in** the window (half-open
  `[window_start, today]`, §4.4.1). Assert both contribute, and assert the same
  instant is **absent** from `managed_words_30d_ago`'s past set. This pins the
  operator on both halves of `always_on_words_added_30d`, so the two can never
  double-count or drop a boundary route.

### T6 — description soft ceiling and `new-skill` charging

- **T6.1** A skill with an 85-word description → `over_soft_max is True`; an
  80-word one → `False` (boundary pinned; the constant is `>`).
- **T6.2 positive control that the ceiling changes nothing else:** routing to
  that over-ceiling skill succeeds, exit code 0, record lands `routed`, and the
  description on disk is **byte-identical** before and after. The truncation
  prohibition is tested, not just documented.
- **T6.3** First `new-skill` route → `budget_note` contains
  `"+N always-on description words"` with N equal to
  `_words(scaffold_description(record))`.
- **T6.4** Second `new-skill` route into the same skill → the note contains
  `"+0 always-on words"` and the description is unchanged on disk.

### T7 — `conditional.rules_cofire`

- **T7.1 (−)** Six **disjoint** topic globs → `crowded is False`,
  `max_fanin <= 5`. (This is the U-glob case that used to over-warn; it must
  stay quiet.)
- **T7.2 (+)** Six **intersecting** topics → `crowded is True`,
  `max_fanin > 5`, `max_fanin_is_upper_bound is True`.
- **T7.3** The datum is `_rules_cofire`'s: monkeypatch it to a sentinel dict
  and assert the payload carries the sentinel — proving no reimplementation.
- **T7.4 the escalation is gone:** on the T7.2 fixture, the `surface_fill`
  entry has `cofire_crowded is True` and **no `over_cap` key and no
  `cap_reason` key at all** (`assert "over_cap" not in entry`).
- **T7.5 (?)** No rules dir → `state == "absent"`, `topics == []`,
  `max_fanin == 0`, `crowded is False` — and assert the state, so "absent" is
  distinguishable from "present and empty".

### T8 — `conditional.reference` read-rate verdict (the five states)

Each leg drives `_reference_shelf` through the **real** function with a seeded
ledger + seeded `reference-read` events; none monkeypatches the verdict itself.

- **T8.1** Hook script absent → `read_rate_state == "not-instrumented"`,
  **`safe_overflow is None`**.
- **T8.2** Instrumented, zero enumerable targets →
  `read_rate_state == "none-enumerable"`, **`safe_overflow is None`**.
- **T8.3 (the load-bearing control)** Instrumented, 2 targets, **both** with
  reads → `read_rate_state == "ok"`, `safe_overflow is True`. Then flip **only**
  the instrument state (remove the hook registration) on the *same* ledger and
  assert `safe_overflow` becomes `None` — **not** `True`, **not** `False`. This
  is the fixture that proves an un-instrumented shelf cannot masquerade as a
  healthy one, and it is the single most important test in this unit.
- **T8.4** Instrumented, all targets zero-read →
  `read_rate_state == "no-reads-observed"`, `safe_overflow is False`.
- **T8.5** Instrumented, 1 of 3 zero-read → `partly-cold`, `False`.
- **T8.6** `flush_state != "ok"` → `counts_are_lower_bound is True` while the
  state ladder is otherwise unchanged.
- **T8.7** `why` is non-empty for every state and comes from the pinned
  mapping — assert the mapping covers all five states exactly
  (`set(mapping) == set(STATES)`), so a new state cannot ship with an empty
  sentence.

### T9 — `surface_fill` new shape

- **T9.1** Payload has `entries`, `words`, `load_class`, `file_words`,
  `file_tokens_est`, `managed_share`; and has **none of** `entries_cap`,
  `words_cap`, `over_cap`, `cap_reason`.
- **T9.2** `load_class`: `claude-md` → `"unconditional"`, `skill-md` →
  `"conditional"`.
- **T9.3** `reference` key present, carrying the verdict; and the compile probe
  was **never** attempted for it — the existing
  `test_surface_fill.py::test_reference_probe_is_never_even_attempted` idiom
  (monkeypatch `compile_managed_text` to raise on a reference path) is extended,
  not replaced.
- **T9.4 memoization:** two records sharing a home compute the reference
  verdict **once** — monkeypatch `reference_read_verdict` with a call counter,
  assert `== 1` across a two-record `list --json --surface-fill` run, and assert
  the cofire memo still works (both keys coexist without collision).
- **T9.5 (?) degraded leg:** make the verdict raise → the `reference` key is
  **omitted** and the other destinations' keys still render. The whole call must
  not fail.
- **T9.6** `SURFACE_FILL_PROBED_DESTINATIONS == ("skill-md", "claude-md")` and
  the old name is gone.

### T10 — the report-only invariant (the unit's central claim)

- **T10.1** On a fixture where **every** signal is flagged simultaneously
  (large file, high share, crowded pairs, 900 w growth, cold reference shelf),
  `self-learn route <id> --dest claude-md` **exits 0**, the record lands
  `routed`, the host commit exists, and the compiled section contains the new
  entry. Nothing is refused.
- **T10.2** The same run's stderr contains the budget note and **does not
  contain** `WARNING` (case-insensitive), `over cap`, or `graduate the oldest`.
- **T10.3** `report --json` on that same fixture: assert every signal block's
  `severity == "informational"`, and assert no top-level key named `over_cap`
  exists anywhere in the payload (recursive scan).
- **T10.4** The `surface-budget` telemetry event emitted by that route has no
  `overflow` key.

### T11 — verb envelope and note

- **T11.1** `_verb_envelope` has key `"budget"` and no key `"over_cap"`.
- **T11.2** `budget_note()` returns `None` for a verb with no compile result
  (e.g. `defer`), and the envelope carries `null`.
- **T11.3 (?)** Whole-file read fails but the section compiles → the note
  contains `"surface size unavailable"` and still reports the entry/word counts.
  Assert the clause is present, not silently dropped.

### T12 — UI

- **T12.1** `_budget_rows` renders `skill-md` with the on-invoke phrasing and
  `claude-md` with the always-on phrasing.
- **T12.2** The `reference` row renders from the CLI datum for each of the
  three text states; assert the `safe_overflow is None` case produces the word
  `UNKNOWN`.
- **T12.3** `reference` key **absent** → **no** reference row (F5 posture),
  asserted by row count.
- **T12.4** `BudgetRow` has `flagged`, not `over_cap`; `detail.html` emits
  `surface-budget-flagged`.
- **T12.5** `evidence.html` renders the `budget` string with class
  `evidence-note`; assert `evidence-warning` does not appear for it.
- **T12.6** `REFERENCE_NO_CAP_LINE` is gone: `assert not hasattr(models,
  "REFERENCE_NO_CAP_LINE")`, and `test_routes.py`'s
  `"reference files have no cap"` assertion is replaced (§8).

### T13 — full-suite criterion

`uv run --project plugins/self-learn/cli pytest` and
`uv run --project plugins/self-learn/ui pytest` both green, except the one
known pre-existing failure
`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`.
Any **new** failure blocks. The exit status must be read **unpiped** or via
`PIPESTATUS` — a piped `pytest | tail` reports the pipe's status and prints
`rc=0` on a red run (`lrn-ea833a5b`, confirmed live in this repo).

---

## 8. Cap-coupled test inventory — enumerated required updates

Every file below was located by grepping `over_cap|cap_reason|entries_cap|
words_cap|DEFAULT_MAX_ENTRIES|DEFAULT_MAX_WORDS|no cap|surface-budget|
surface_fill` across `plugins/self-learn/cli/tests` and
`plugins/self-learn/ui/tests` at `b8ac3cb`. Hit counts are from that grep.

| file | hits | required change |
|---|---:|---|
| `cli/tests/test_surface_fill.py` | 49 | **Heaviest.** `TestCountCorrectness::test_over_cap_by_entry_count` (:361) and `::test_over_cap_by_word_count` (:374) are **deleted** — the behavior is gone. `::test_effective_caps_are_the_compiler_defaults` (:388, asserts `entries_cap == 10` / `words_cap == 150`) is **replaced** by T9.1's shape assertion. The four literal payload dicts at :255-256, :332-333, :349, :394-395 are rewritten to the §6.3 shape. `TestKeySet::test_reference_is_never_a_key` (:168) is **inverted** — `reference` IS now a key — while `::test_reference_probe_is_never_even_attempted` (:175) is **kept and extended** (T9.3): the *probe* prohibition survives, only the *key* prohibition dies. `TestDegradedLegs` (:271-324) and `TestMemoization` (:401) gain the T9.5 / T9.4 legs. |
| `cli/tests/test_a2_rules_local.py` | 35 | `TestObligation8RulesTopicCount` (:366-471) is the U-glob co-firing suite. `::test_six_disjoint_topics_do_not_set_over_cap` (:374) → assert `cofire_crowded is False`. `::test_six_intersecting_topics_set_over_cap_rules_cofire` (:395, asserts `over_cap is True` **and** `cap_reason == "rules-cofire"`) → assert `cofire_crowded is True` and **no** `over_cap`/`cap_reason` keys (T7.4). `::test_entry_cap_over_cap_survives_orred_with_cofire` (:415) is **deleted outright** — it tests the OR-ing of two thresholds, one of which no longer exists; its intent (co-firing does not mask a per-file signal) is re-expressed by T7.2 + T2.1 on one fixture. `::test_five_or_fewer_leaves_per_file_over_cap_untouched` (:453) → same rewrite. The header comment at :369-370 is updated. |
| `ui/tests/test_models_detail.py` | 28 | `TestSurfaceBudgets` (**:319-466** — `TestContradicts` opens at :468; the r1 draft's ":319-440" stopped short of fixtures the row itself lists at :448-459). **M5:** `::test_nearness_clause_gated_on_actual_proximity` (**:373**) does not merely need its fixture rewritten — it tests the clause `_NEAR_ENTRIES_HEADROOM`/`_NEAR_WORDS_RATIO` produce, and §6.6 deletes both constants, so **the test dies with them**. Delete it; its intent (an empty surface must not claim to be near a cap) is void once there is no cap. `::test_no_surface_fill_key_yields_only_the_static_reference_line` (:324) is **rewritten** — there is no static line (T12.3: absent key → no row). `::test_both_capped_destinations_render_their_datum` (:333) and `::test_words_binding_constraint_gets_the_word_cap_phrasing` (:400) → the §6.6 phrasing; the "binding constraint" test is **deleted** (no cap, no binding). `::test_over_cap_flag_passes_through_without_extra_markup` (:427) → `flagged`. All seven inline fixture dicts (:336-341, :383-384, :403-404, :417-418, :433-434, :448-449, :458-459) rewritten to the §6.3 shape. |
| `cli/tests/test_u_glob.py` | 7 | Header comment at :5 names the `cap_reason` replacement — update to name `cofire_crowded`. `TestT8CofireOnFixtureRulesDir` (:458-533) asserts on the datum, not on `over_cap`; verify and adjust only where the escalation is asserted. `TestT11ReadOnlyNeverProbes` (:633) must keep passing unchanged — the new reference verdict must not introduce a `glob_reaches` call. |
| `cli/tests/test_compilers.py` | 5 | `TestOverflowCap` (:205-233 — the class body ends at the last assertion; :236-239 are the separator comment and `class TestBrokenTargets:`) — **the whole class is deleted**: `::test_eleventh_entry_still_applied_but_flagged` (:206), `::test_ten_entries_not_flagged` (:214), `::test_word_cap_variant` (:220), `::test_per_target_entry_override` (:230). Replaced by a new `TestSectionCounts` asserting `entry_count`/`word_count` are correct and that `SectionResult` has no cap fields (T1.3). |
| `cli/tests/test_pointer.py` | 4 | `test_b1_regression_guard_cap_at_default_max_entries` (:324) has **exactly two** assertions, :333-334 (`over_cap is False`, `cap_reason is None`). Deleting both — as the r1 draft said — would leave a **zero-assertion** test named "regression_guard", which is worse than deleting it: a guard that asserts nothing passes forever. **The guarded invariant survives the retirement**: the pointer block must not be counted as a managed entry, and `entry_count` is explicitly kept (§6.1). So **replace** the two assertions with `assert result.entry_count == 10` (and, since `word_count` is also kept, optionally that it equals the pre-pointer compile's). Rename the test to drop `cap_at_default_max_entries`. :26's `DEFAULT_MAX_ENTRIES` import and :326's `range(...)` become a local literal `10` — the fixture wants "ten records", not "the cap". |
| `cli/tests/test_resolution_evidence.py` | 2 | :138, :275 assert `envelope["over_cap"] is None` → `envelope["budget"] is None` (T11.2). |
| `ui/tests/test_resolution_evidence.py` | 2 | :68 helper param `over_cap: str \| None = None`; :87 envelope key. Rename both to `budget`. |
| `ui/tests/test_js_dom.py` | 2 | :1001, :1082 envelope literals `"over_cap": None` → `"budget": None`. (:241 `pane_budget_usd` is an unrelated name collision — **do not touch**.) |
| `ui/tests/test_routes.py` | 3 (grep) / **6 assertions** | **M5 — the §8 grep pattern missed these: they assert the *rendered phrasing* §6.6 rewrites, not the field names.** Verified line-by-line. **Break:** `:1103` `"this skill-md section already holds 8 of its 10 entries"` (the "of its 10" phrasing goes with the cap); `:1104` `"lands near the cap"` (clause deleted); `:1113` `"overflow surface entries graduate into"` (from `REFERENCE_NO_CAP_LINE`, deleted); `:1127` `"claude-md section already holds"` (rephrased per §6.6); `:1143` the same skill-md sentence used as the **positive control** inside `test_armed_action_bar_carries_no_budget_markup` — it must be updated to the new sentence, or that test's negative assertions go vacuous. Also `:1112` `"reference files have no cap"` → the state-derived text (T12.2), and `:1106`'s test name `test_why_region_shows_the_static_reference_line` is now a misnomer (the line is no longer static). **Go vacuous if not updated:** `:1125` `assert "skill-md section already holds" not in r.text` and `:1154` `assert "already holds" not in armed.text` — both would pass trivially once the phrase no longer exists anywhere, asserting nothing. Re-point both at the new sentence. `:1153` `"surface-budget" not in armed.text` — **keep unchanged**; the CSS class name survives and the invariant (no budget in the armed bar) still holds. |
| `ui/tests/test_resolved_surface.py` | 1 | :388 envelope literal `"over_cap": None` → `"budget": None`. |
| `cli/tests/test_audit_fixes.py` | 1 | :216 `test_route_emits_surface_budget_event` — extend to assert the event has **no** `overflow` key (T10.4). |
| `cli/tests/test_miner.py` | 1 | :469 `test_episode_brief_over_cap_refuses_whole_candidate` — **unrelated**: this is the miner's episode-brief size cap, a different mechanism. **Do not touch.** Listed here so the builder does not "fix" it. |

**Non-test source sites** requiring coordinated edits (from the same grep, on
`src`): `compilers.py` (:32-36, :129-130, :170-171, :204-205, :289-294,
:304-310, :349-354), `verbs.py` (:91-92, **:208-212 — the doc comment, N6**,
:213, :294-303, :2050-2054,
:2087-2091, :2337-2343, :2348-2370), `chezmoi.py` (:55-56, :274-275),
`cli.py` (:1145, :1185), `teach.py` (:756), `report.py` (new `context_budget`,
new `reference_read_verdict`, `gather` :668, `render_text` :843),
`ui/models.py` (:530-534, :1543-1556, :1710-1711, :1714, :1754-1782),
`worker.py` (:420-431 — the `idf`/`sum_idf` closures factored into the new
module-level `pair_similarity`, §4.3.2), `ui/routes.py` (:1419), `ui/templates/detail.html` (:177),
`ui/templates/partials/evidence.html` (:70).

---

## 9. Out of scope

1. **Any hard ceiling, refusal, or exit-code change.** Explicitly ruled out by
   the user (*"absolutely strict up top, looser in-file"*) and by the hub's
   sequencing constraint. Whether a token ceiling should exist **at all** once
   these instruments have run is deliberately unsettled — no literature figure
   transfers cleanly, and any fixed number chosen today would be a guess
   wearing the costume of a measurement.
2. **The upstream routing gate.** Shipped as #6. This unit does not touch
   routing destination selection, the analyst's proposal path, or the
   narrowest-surface doctrine.
3. **S-23's reference-shelf surface design** — PARKED. This unit **reads**
   U-readref's read-rate instrument and reports a verdict; it does not build a
   user-scope reference surface, a pointer mechanism, or a shelf UI.
4. **The COSTLY evidentiary bar** — a separate, parked discussion.
5. **Redesigning `reference_shelf`.** Its fields, states, ordering, window,
   and flush semantics are U-readref's and are consumed as-is. If a field is
   missing, that is a U-readref amendment, not a U-cap change.
6. **Redesigning `_rules_cofire`.** U-glob's symbolic intersection, its
   `unpathed` raw-key predicate, and its upper-bound `max_fanin` are consumed
   verbatim. Only the *consequence* (`over_cap` OR-in → `cofire_crowded`)
   changes.
7. **A real tokenizer.** The CLI's only runtime dependency stays
   `ruamel.yaml`. `TOKENS_PER_WORD_EST` is arithmetic and labeled.
8. **Measuring skill BODY size against anything.** Bodies are Class B and a
   fuller body routes better (37–44 pp). Body words are reported as a fact and
   compared to nothing.
9. **The `already_canon` graduation card and the merge cards** in
   `commands/review.md` — untouched; only the *over-cap-triggered* graduation
   opener is retired.
10. **New telemetry kinds.** `EVENT_KINDS` is closed and unchanged; only the
    `overflow` payload key is dropped.
11. **Hook context cost.** Hooks have none; they appear in the load-class table
    (§3.1) for completeness and are measured nowhere.
12. **Retroactive history.** `managed_share_30d_ago` is permanently `null`
    (§4.4.1). Building a real historical series would need new persisted state,
    which this unit does not introduce.
