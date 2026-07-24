# Spec — de-personalize the shipped product (and close the `DEFAULT_MEMORY_DIR` wrong-target defect)

Status: DRAFT rev 1 — for BLIND Opus spec gate (reviewer reads this spec +
the code only; no review notes).
Origin: the user audited the repo for shareability. Verified finding:
there are **no** secrets, credentials, third-party PII, or employer
content anywhere in the tree or the 336-commit history. What remains is
personal-to-the-user content in the **shipped product**: their Linux
username in paths, and their real home-LAN facts used as test fixtures.
This spec removes exactly that, and — because one of the personal
literals is simultaneously a **correctness defect in a destructive verb**
— repairs that defect rather than merely relabeling it.

Secondary origin: Spec C1 §O-6 deliberately **deferred**
`plugins/self-learn/README.md:82` to "Spec D" and left a tripwire for it
(test_portability_docs.py **34-47**, quoted in §5.1 below). This spec
takes over that deferred line. It does **not** take over Spec D's actual
subject — see §4.4 and §8.

Scope: literal replacement across `plugins/self-learn/**` source, tests,
and fixtures, plus **one** behavior change (§4). No new public surface,
no new module, no lock change, no schema change.

Pin the code at commit `b11d9aa` (`git rev-parse HEAD`). All anchors are
against that commit. Paths are repo-relative from
`/home/komi/repos/self-learn`; within a table, `cli/` and `ui/` are
shorthand for `plugins/self-learn/cli/` and `plugins/self-learn/ui/`.

---

## 1. Problem statement

Two distinct harms share one inventory.

### 1.1 The correctness harm (Group A)

```python
# cli/src/self_learn/cli.py:81
DEFAULT_MEMORY_DIR = "~/.claude/projects/-home-komi-repos-claude-skills/memory"
```

This is the default target for **`import --memory`** *and* for
**`prune-memory`**, which calls `target.unlink()`
(import_memory.py **288**).

The literal names `claude-skills` — a project the user **no longer works
in**. Claude Code sessions for this repo write to
`-home-komi-repos-self-learn`. Both directories were confirmed to exist
on this host, so the default does not fail loudly; it **silently
addresses the wrong project**:

- `self-learn import --memory` (bare) reads the **stale** project's
  memory files and files them as records bound to `project_path =
  gitops.toplevel(Path.cwd()) or Path.cwd()` — i.e. the **current**
  project (import_memory.py **123-125**). That is cross-project
  contamination of the ledger: another project's knowledge, mis-attributed.
- `self-learn prune-memory` (bare) walks this ledger's terminal
  auto-memory records and looks for each one's file in the **wrong**
  directory. Every lookup lands in `report.missing`
  (import_memory.py **281-283**), the real memory dir is never pruned,
  and the sweep reports a clean-looking summary while doing nothing.
  The verb is silently inert.

A bounded but real deletion hazard also exists: `prune_memory` never
checks that `memory_dir` is the right directory or even that it exists.
It unlinks whenever `sha_anchor(target.read_text()) == sha`
(import_memory.py **284-289**). Content-identity is the only thing
standing between a wrong-target run and a cross-project deletion, and it
is not a check the *user* authored — it is incidental.

So the personal literal here is not cosmetic. It is a defect. Replacing
`komi` with `user` inside it would produce a path that is personal-free
**and still wrong** — arguably worse, because the wrongness would no
longer be self-evident to a reader.

### 1.2 The personal-content harm (Groups B–D)

- **Group B** — `/home/komi` in shipped source docstrings (hosts.py).
- **Group C** — `-home-komi-repos-*` / `/home/komi` in test literals.
- **Group D** — the user's **real home-LAN facts** used as fixtures:
  `192.168.1.232` is their Home Assistant host, nicknamed "the Nova";
  `192.168.1.254` is their router. A fixture file
  (`cli/tests/fixtures/memory/nova-host.md`) documents that host's real
  Wi-Fi/DHCP behavior in full.

None of this is a secret. All of it is a stranger's home network
topology, shipped in a public product's test corpus.

---

## 2. Scope rulings (RATIFIED — binding constraints, not open questions)

These are the user's decisions. The gate must **not** demand work that
contradicts them.

- **R-1 — `docs/specs/**` is NOT scrubbed.** The spec corpus ships as-is.
  It is a historical record citing 69 real commit SHAs across 20+
  documents, and includes a session post-mortem that narrates the user by
  name. Editing it retroactively would falsify the record. **No change
  under `docs/` except this spec file itself.**
- **R-2 — Git history is NOT rewritten.** No `filter-repo`, no squash, no
  force-push.
- **R-3 — Author identity is KEPT.** The user's real name and email stay
  in `.claude-plugin/plugin.json`, both `pyproject.toml` files, and the
  assertions at cli/tests/test_portability_docs.py **73-74**. These are
  **never** a target. (C1 already recorded this as P-C1.3.)
- **R-4 — Scope is the shipped product only:** `plugins/self-learn/**`
  source, tests, and fixtures.

---

## 3. Pinned replacement conventions

The builder does **not** improvise these. Each is pinned to an existing
in-repo convention or to a standards-reserved value.

| # | Class | From | To | Why this value |
|---|---|---|---|---|
| **K-1** | home dir | `/home/komi` | `/home/user` | **Already the codebase's convention** — ui/tests/test_registration_wipe.py **59** uses `/home/user/repos/keyboards`. Do not invent a new placeholder. (ui/tests/test_routes.py also uses a shorter `/home/u/`; that file's existing `/home/u/` occurrences are **not** touched — see §8.) `komi`→`user` is **length-preserving** (4→4), which keeps every aligned trailing comment and wrapped docstring line intact with no reflow. |
| **K-2** | project slug | `-home-komi-repos-…` | `-home-user-repos-…` | Direct consequence of K-1; these strings are `str(path).replace("/","-")` renderings of a K-1 path. Also length-preserving. |
| **K-3** | LAN address | `192.168.1.232` → `192.0.2.232`; `192.168.1.254` → `192.0.2.254` | **RFC 5737 TEST-NET-1** (`192.0.2.0/24`), reserved for documentation and guaranteed non-routable. **The final octet is deliberately preserved.** |
| **K-4** | bare octet fragments | `.232`, `.254` | **UNCHANGED — do not touch** | Five sites spell the address as a bare `.232` (cli/tests/test_round3_fixes.py **854**, cli/tests/test_hosting_fixes.py **1035**/**1054**, ui/tests/test_routes.py **2675**/**2690**). Because K-3 preserves the final octet, these fragments stay **internally consistent** with the full addresses and need **zero** edits. A bare `.232` identifies nothing on its own; the identifying part was the private-LAN prefix bound to a named host, and that is gone. This is a **recorded decision, not an omission** — the §9 gate does not flag it, so it must be written down here or a later reader will read it as a miss. |
| **K-5** | host nickname | `Nova` / `nova` | `Beacon` / `beacon` | Neutral, fictional, applied consistently in every case form. Chosen against three simultaneous constraints — see §3.1. **Pre-verified:** `git grep -in 'beacon' -- plugins/` returns **zero** hits at `b11d9aa`, so the §9 gate re-run against the new name is meaningful rather than vacuous. |
| **K-6** | fixture filename | `nova-host.md` | `beacon-host.md` | A **rename is mandatory, not optional** — the §9 acceptance gate is case-insensitive (`-i`), so `nova-host.md` matches `\bNova\b` and would fail the gate. See §6 for the complete reference list. |

### 3.1 Why the nickname must satisfy three constraints at once

`Beacon` is not a free choice. Any candidate must clear all three:

1. **Filename charset.** cli/tests/test_import_memory.py **28** pins
   `ORIGIN_RE = re.compile(r"^memory/[a-z-]+\.md#sha256:[0-9a-f]{12}$")`
   and line **83** asserts every origin matches it. The new fixture
   filename must therefore be **lowercase ASCII letters and hyphens
   only** — no digits, no underscores. `beacon-host.md` qualifies.
2. **Leading word of every rewritten sentence.** `teach.infer_type`
   (teach.py **118-120**) is an **anchored** regex on the *opening*
   word (`_TRIGGERISH_RE`, teach.py **111-115**): behavior iff the text
   starts with `never|always|don't|do not|stop|avoid|use|prefer|check|
   verify|ensure|run|ask|remember to|when(ever)|before|after|if|on`.
   **Empirically verified: it does NOT key on the IP token**, so K-3 is
   inert for classification. But the leading word is load-bearing. Every
   rewritten sentence MUST keep its current opening word (`The`, `the`).
3. **Journal-title leading word.** cli/tests/test_round7_fixes.py **174**
   writes an inline journal entry titled `### 2026-07-16 — the Nova
   reserves its own DHCP lease`. `import_backlog` infers type from the
   title-initial word (cli/tests/test_import_backlog.py **9-10**: entry
   e5 `Never edit …` is behavior *because* of its title-initial `Never`).
   The leading lowercase `the` MUST survive.

Substituting only the nickname token — `Nova` → `Beacon`, `nova` →
`beacon` — satisfies all three by construction. **The builder must not
rephrase any sentence.**

---

## 4. Design decision — `DEFAULT_MEMORY_DIR` (Obligation O-1)

### 4.1 Options considered

**(a) Derive the default from cwd at runtime.** Compute
`~/.claude/projects/<slug(cwd)>/memory` using the plain no-digest shape.

**REJECTED — this is the strongest finding in the spec, and it is
empirical.** Claude Code's `~/.claude/projects/<slug>` scheme is not
`str(path).replace("/", "-")`. A read-only listing of the 74 live project
directories on this host shows it also folds `.` and `_` into `-`:

| Real path on disk | Actual Claude Code directory |
|---|---|
| `/home/komi/.claude` | `-home-komi--claude` |
| `/home/komi/.config` | `-home-komi--config` |
| `/home/komi/repos/local_file_organizer` | `-home-komi-repos-local-file-organizer` |

(No directory under `~/.claude/projects` contains a `.` or `_` at all.)

So option (a) requires **reverse-engineering an undocumented external
tool's private path scheme** — and the resulting transform is
**many-to-one**. That collision hazard is not hypothetical here: this
codebase's own `hosts.slug_for` docstring (hosts.py **29-36**) records
that a readable-only slug already **cross-homed one project's lessons
into another project's canon** (audit 2026-07-16 BLOCKER 1), which is
precisely why `slug_for` appends a SHA-256 digest. `/w/a-b`, `/w/a_b`,
`/w/a.b`, and `/w/a/b` all render `-w-a-b`.

**Option (a) would reinstate an already-fixed bug class inside a verb
that calls `target.unlink()`.** It would also fail *open* — into a
directory that plausibly exists and belongs to a different project —
rather than closed. That is the exact silent-wrong-target failure of §1.1,
re-implemented with more machinery.

`hosts.slug_for` is also confirmed to be the **wrong** helper: its digest
suffix has no counterpart in a real `~/.claude/projects` directory name
(this session's is `-home-komi-repos-self-learn`, no digest).

**(b) Remove the default entirely; require `--memory DIR` or
`SELF_LEARN_MEMORY_DIR`. — CHOSEN.**

**(c) Variants considered and rejected:**
- *Derive-then-verify-existence.* Existence is not correctness — the
  collision case has an existing directory belonging to another project.
  Still relies on the reverse-engineered transform.
- *Keep a default but make it a non-real placeholder string.* That is (b)
  with a worse failure mode: a path that looks resolvable but never is.
- *Read the slug from Claude Code's hook payload `transcript_path`* (which
  is authoritative: `~/.claude/projects/<slug>/<session>.jsonl`). Only
  available inside a hook invocation, not for a bare CLI run. Noted here
  as **input for Spec D**, not for this spec.

### 4.2 The chosen design

Delete the constant. `default_memory_dir()` becomes **env-only** and
returns `None` when the env var is unset. Both verbs refuse.

**Pinned discriminating property — the gate should verify exactly this:**

> After this change, **`prune-memory` cannot delete anything without an
> explicit caller-supplied target.** No inference, no derivation, no
> guess stands between the user and `unlink()`.

**Pinned code shape** (this shape is required, not merely suggested —
see the pyright constraint below):

```python
def default_memory_dir() -> Path | None:
    """`import --memory` / `prune-memory` dir: env only, no default.

    There is deliberately NO built-in default: the only derivable
    candidate would be a guess at Claude Code's undocumented, many-to-one
    ~/.claude/projects slug scheme, and `prune-memory` DELETES at this
    path. Refusing is the safe answer; see the spec's §4.1.
    """
    env = os.environ.get("SELF_LEARN_MEMORY_DIR")
    return Path(env).expanduser() if env else None
```

**Two messages, one shared tail — the verbs do not share a flag.**
`import` takes `--memory DIR`; `prune-memory` takes a **positional**
`DIR`. A single shared message cannot name the right surface for both,
and a message that names neither would make M-2's stderr assertion
unsatisfiable. Pinned:

```python
_MEMORY_DIR_TAIL = (
    "or set SELF_LEARN_MEMORY_DIR. There is no default: the only "
    "derivable candidate would guess Claude Code's projects-dir slug, "
    "and prune-memory deletes at this path."
)
_IMPORT_MEMORY_DIR_REQUIRED = (
    f"self-learn import: no memory directory — pass `--memory DIR` {_MEMORY_DIR_TAIL}"
)
_PRUNE_MEMORY_DIR_REQUIRED = (
    f"self-learn prune-memory: no memory directory — pass `DIR` {_MEMORY_DIR_TAIL}"
)
```

**Substring invariant (both messages):** each MUST contain the literal
`SELF_LEARN_MEMORY_DIR`. The import message MUST additionally contain the
literal `--memory`. These are exactly what M-2/M-3 assert — the strings
above satisfy them; a builder who rewords must preserve the substrings
rather than weaken the tests.

**Placement is load-bearing, and it is DOUBLY contained.** In
`_cmd_import` (cli.py **1358-1370**) the `default_memory_dir()` call sits
inside **two** enclosures, and both matter:

1. inside the `try:` that maps `ImporterError → return 1` (cli.py
   **1360**, **1368-1370**); and
2. inside the **`else:` of the `--backlog` / `--memory` branch**
   (cli.py **1361-1367**).

Missing either one produces a broken build:

- **Ignore (1)** — signal the missing-dir case by raising `ImporterError`
  → the exit code becomes **1**, not 64.
- **Ignore (2) — the worse failure.** Hoisting the guard above the *`try`*
  also hoists it above the *branch*. Under `import --backlog <skill>`,
  `args.memory` is `None`, so `default_memory_dir()` returns `None`, the
  guard fires, and **`import --backlog` returns 64 whenever
  `SELF_LEARN_MEMORY_DIR` is unset** — which every backlog test
  guarantees: the `env` fixture calls
  `monkeypatch.delenv("SELF_LEARN_MEMORY_DIR", raising=False)`
  (test_import_cli.py **32**), and the `home` fixture is derived from
  `env` (test_import_cli.py **37-38**), so **all four** backlog tests
  inherit it.

  Three break outright — `test_import_backlog_prints_summary_exit_0`
  (**59**), `test_import_backlog_rerun_is_idempotent_at_cli_level`
  (**68**), `test_import_backlog_missing_journal_exits_1` (**84**). The
  fourth is the real damage: **`test_import_backlog_unknown_skill_is_usage_error`
  (test_import_cli.py 78-81) STILL PASSES** — it asserts `rc == 64` and a
  non-empty stderr, and the memory-dir refusal satisfies both **without
  ever reaching the unknown-skill path**. This spec exists to prevent
  assertions that pass for the wrong reason; a careless hoist would
  manufacture one.

**Pinned shape — the guard goes INSIDE the non-backlog branch, hoisted
above the `try`, AND the inner dispatch keys on `memory_dir`:**

```python
def _cmd_import(args: argparse.Namespace) -> int:
    home = resolve_home()
    memory_dir: Path | None = None
    if args.backlog is None:
        memory_dir = Path(args.memory).expanduser() if args.memory else default_memory_dir()
        if memory_dir is None:
            print(_IMPORT_MEMORY_DIR_REQUIRED, file=sys.stderr)
            return EXIT_USAGE
    try:
        if memory_dir is not None:            # NOT `args.backlog is not None`
            report = import_memory(home, memory_dir)
        else:
            report = import_backlog(home, args.backlog)
    except ImporterError as exc:
        ...
```

**Why the inner dispatch must key on `memory_dir`, not `args.backlog`
(this is a pyright constraint, not a style preference).** Narrowing must
reach the call site through the **same condition** that performed it.
Guarding `memory_dir is None` under `if args.backlog is None:` does not
narrow `memory_dir` inside the `else:` arm of a differently-keyed
`if args.backlog is not None:` — pyright does not correlate the two
predicates (and cannot: `args.backlog` is `Any` via
`Namespace.__getattr__`). At the join point `memory_dir` is back to
`Path | None`, while `import_memory` is typed `memory_dir: Path`
(import_memory.py **110-111**) — a **new `reportArgumentType`**, i.e. a
51st pyright error, which criterion 8 forbids.

**Verified empirically, not by inspection.** Both shapes were transcribed
into a standalone scratch file (no `self_learn` import, so a
missing-import diagnostic could neither mask nor manufacture the result)
and checked with `pyright --pythonpath .venv/bin/python` from
`plugins/self-learn/cli/`. The `args.backlog`-keyed dispatch produced
**exactly one** diagnostic — on its `import_memory(home, memory_dir)`
line — and the `memory_dir`-keyed dispatch produced **zero**. No config
confound: there is no `pyrightconfig.json` and no `[tool.pyright]` block,
and the 50-error baseline already contains 28 `reportArgumentType`
diagnostics, so the rule is unambiguously enabled.

**Behaviorally identical.** The mutually-exclusive group is
`required=True` (cli.py **454**), so exactly one of `--backlog` /
`--memory` is always present, making `memory_dir is not None` ⟺
`args.backlog is None` ⟺ the memory path. The backlog arm is unaffected
(`args.backlog` is `Any`, so it satisfies `import_backlog`'s `str`
parameter either way). An explicit `assert memory_dir is not None` inside
the `else:` would also silence pyright, but it adds a runtime assertion
for a condition the control flow already guarantees; the reordered
dispatch is preferred.

`_cmd_prune_memory` (cli.py **1403-1408**) has no branch; its guard goes
before any filesystem access, printing `_PRUNE_MEMORY_DIR_REQUIRED`.
Pinned exit code for both: **`EXIT_USAGE` (64)**, message to `stderr`.
Mutation **M-5** (§7) locks the branch containment.

**Type constraint.** Widening the return to `Path | None` is visible at
both call sites, where the value flows into `import_memory(home, memory_dir)`
and `prune_memory(home, memory_dir, …)`, both typed `Path`
(import_memory.py **110-111**, **252**).

The `if memory_dir is None: … return EXIT_USAGE` guard is **necessary but
not sufficient**. The narrowing it performs only survives to a call site
reached through the **same** condition:

- **`_cmd_prune_memory`** has no branch — the guard's narrowing flows
  straight through to `prune_memory(home, memory_dir, …)`. Nothing more
  is needed.
- **`_cmd_import`** has the `--backlog` / `--memory` branch, so the guard
  alone leaves `memory_dir` as `Path | None` at the join. The inner
  dispatch **must** re-key on `memory_dir` (see the pinned block above)
  for the narrowing to reach `import_memory`.

The pyright budget is **exactly 50 errors, unchanged** — not "no new
errors" (see §9). Both shapes above were checked against a real pyright
run; the `args.backlog`-keyed variant costs a 51st error.

**Unaffected:** `--memory`'s argparse spec keeps `nargs="?"`,
`const=""` — the mutually-exclusive `--backlog | --memory` group
(cli.py **453-466**) and its `SystemExit(2)` behavior are untouched, so
cli/tests/test_import_cli.py **127** (`… == 2`) stays green. The
`prune-memory` positional keeps `nargs="?"`, `default=None`.

### 4.3 Behavior change — stated explicitly

**This is a breaking change to two bare invocations.** It is the only
behavior change in this spec.

| Invocation | Before (`b11d9aa`) | After |
|---|---|---|
| `self-learn import --memory` (no dir, no env) | Silently reads the **stale** `claude-skills` project's memory and mis-files it as the current project's | Exits **64**, writes `_IMPORT_MEMORY_DIR_REQUIRED` to stderr, **imports nothing** |
| `self-learn prune-memory` (no dir, no env) | Silently sweeps against the **wrong** directory; every record lands in `missing`; the real memory dir is never pruned | Exits **64**, writes `_PRUNE_MEMORY_DIR_REQUIRED` to stderr, **deletes nothing** |
| `self-learn import --backlog <skill>` | works | **unchanged — must stay 0** (§4.2 enclosure 2; mutation M-5) |
| `self-learn import --memory DIR` / `prune-memory DIR` | works | **unchanged** |
| `SELF_LEARN_MEMORY_DIR=… self-learn import --memory` | works | **unchanged** |

The user loses a bare-invocation convenience whose behavior was wrong.
The replacement is an honest usage error naming both ways to supply a
target. **Flag this to the user at merge** — it is a real ergonomic cost,
consciously traded for a destructive verb that fails closed.

**Scope of the safety claim — stated so it is not over-read.** This spec
removes only the **silent, implicit** wrong target. An *explicitly*
supplied wrong directory — `self-learn prune-memory /some/other/project/memory`
— retains exactly the §1.1 hazard: `prune_memory` still does not verify
that the directory belongs to this project, and still unlinks on a
content-hash match. That remains the user's responsibility and is
**unchanged and out of scope** here. Criterion 3 in §9 must be read as
"no *inferred* target can reach `unlink()`", not as "no wrong target
can."

### 4.4 Why this does not preempt Spec D

Spec D (unwritten) holds the user's ratified intent to make memory import
**sweep ALL projects**, with open design questions (unregistered-project
handling, exclude mechanism, per-project source report).

Option (b) is the **only** option that leaves that question fully open.
It *removes a wrong answer* without installing a new one. Option (a)
would install a **single-project** semantic that Spec D would then have to
rip out — and would ship a slug-derivation module Spec D must either
inherit or delete. Under (b), the bare `import --memory` form is left
**vacant**, and Spec D fills it with the sweep. No sweep behavior, no
multi-project iteration, and no exclude mechanism appears in this spec.

---

## 5. Per-file change table

**22 files.** Every site below was re-verified against `b11d9aa`.
`git mv` is required for the one rename (K-6) so history follows the file.

### 5.1 Group A — `DEFAULT_MEMORY_DIR` (4 files)

| File | Line | Current | Required |
|---|---|---|---|
| `cli/src/self_learn/cli.py` | 79-81 | `#: The auto-memory location for THIS repo …` comment + `DEFAULT_MEMORY_DIR = "~/.claude/projects/-home-komi-repos-claude-skills/memory"` | **Delete the constant and its comment.** No replacement constant. |
| `cli/src/self_learn/cli.py` | 84-87 | `default_memory_dir() -> Path` | Per §4.2: `-> Path | None`, env-only, new docstring |
| `cli/src/self_learn/cli.py` | 465 | `help=f"import auto-memory topic files (default: {DEFAULT_MEMORY_DIR})"` | `help="import auto-memory topic files (DIR, or $SELF_LEARN_MEMORY_DIR; no default)"` — **must not interpolate any path literal** |
| `cli/src/self_learn/cli.py` | 1358-1370 | `_cmd_import` resolves inside the `try` **and** inside the `--backlog`/`--memory` `else:` | **Two coupled changes**, exact shape pinned in §4.2: (a) guard goes **inside the non-backlog branch**, hoisted above the `try` — **not** above the branch (hoisting above it breaks `import --backlog` in 3 tests and makes a 4th pass for the wrong reason); (b) the inner dispatch **re-keys on `memory_dir is not None`** instead of `args.backlog is not None`, or pyright gains a 51st error. `EXIT_USAGE` |
| `cli/src/self_learn/cli.py` | ~1403-1408 | `_cmd_prune_memory` resolves then sweeps | Guard before any filesystem access; `EXIT_USAGE` |
| `plugins/self-learn/README.md` | 82 | `\| \`SELF_LEARN_MEMORY_DIR\` \| \`~/.claude/projects/-home-komi-repos-claude-skills/memory\` \| \`import --memory\` / \`prune-memory\` default dir \|` | `\| \`SELF_LEARN_MEMORY_DIR\` \| (unset — required) \| \`import --memory\` / \`prune-memory\` target dir; no default, both verbs refuse without it \|` — `(unset)` is the table's **existing** convention (see rows 85, 86, 87) |
| `cli/tests/test_import_cli.py` | 111-116 | `test_default_memory_dir_is_the_pinned_auto_memory_path` | **DELETE this test** — see §5.1a |
| `plugins/self-learn/skills/self-learn/SKILL.md` | 50 | `\| \`import --backlog <skill>\` \\\| \`--memory [dir]\` \| One-shot ETL: …` | `\`--memory DIR\`` — dir no longer optional; append "(DIR or `$SELF_LEARN_MEMORY_DIR`; no default)" to the description cell |
| `plugins/self-learn/skills/self-learn/SKILL.md` | 51 | `\| \`prune-memory [--dry-run] [dir]\` \| S-13 sweep: …` | `\`prune-memory [--dry-run] DIR\`` — same note appended |

**§5.1c — why SKILL.md is in scope despite carrying no personal literal.**
Lines 50-51 are the **shipped verb reference** — the file the model itself
reads to learn `self-learn`'s syntax. Both present `[dir]` as freely
optional, which is the **pre-change contract**; after §4 the bare form
exits 64. Leaving it stale would have the model confidently emit a command
that now fails. It carries no `komi`/IP/`Nova` literal, so the §9 gate
**cannot** catch this — it is caught only by being written down here.
Verified: **no test binds this file**, so it is a doc-accuracy obligation,
not a baseline risk.

**§5.1a — this test must be DELETED, not edited. Highest-risk site in the
spec.** A builder handed "scrub the literal" will naturally *edit* the
asserted path (e.g. to `-home-user-repos-self-learn`), leaving the suite
green while **silently reinstating a default** — the exact defect §4
exists to remove. The test's own name (`…_is_the_pinned_auto_memory_path`)
asserts a property that must no longer hold. Replace it with three tests
(§7 M-1/M-2/M-3).

**§5.1b — a live tripwire the builder must not trip.**
cli/tests/test_portability_docs.py **34-47**
(`test_o6_readme_install_blocks_have_no_repos_claude_skills`) asserts
**whole-file** that `"repos/claude-skills"` does not appear in
`plugins/self-learn/README.md`. Its docstring states this explicitly:

> "It passes today only because README.md:82's Spec-D-deferred literal is
> spelled `repos-claude-skills` (hyphens). A Spec D author who rewrites it
> with slashes will trip this — by design."

The §5.1 README rewrite **removes the literal entirely**, so this test
stays green. The builder must **not** introduce a slash-spelled
`repos/claude-skills` anywhere in either README. Do not edit
test_portability_docs.py.

### 5.2 Group B — `/home/komi` in shipped source (1 file)

| File | Line | Current | Required |
|---|---|---|---|
| `cli/src/self_learn/hosts.py` | 9 | `    skills_root: /home/komi/repos/claude-skills   # plugins/*/skills/* live here` | `komi`→`user`; **preserve the trailing-comment column** (K-1 is length-preserving, so no realignment is needed or permitted) |
| `cli/src/self_learn/hosts.py` | 11 | `      - path: /home/komi/repos/claude-skills      # CLAUDE.md targets` | same |
| `cli/src/self_learn/hosts.py` | 22 | ` ``skills_root: /home/komi/repos`` would CREATE ``/home/komi/repos/` | **two** occurrences on this one line; both → `/home/user/repos` |

**hosts.py:22-23 semantic warning.** The example only makes sense if
`skills_root: <X>` is the **parent** of the `<X>/CLAUDE.md` it would
create. The string wraps across lines 22→23 (`…/home/komi/repos/` +
newline + `CLAUDE.md``). Both occurrences must change **together** and the
wrap must be preserved — K-1's equal length makes this a pure
character swap. Do not reflow the paragraph.

**`claude-skills` itself stays.** It is the user's real repository name
(`github.com/AlexK-Notable/claude-skills`), covered by R-3 and used
throughout the codebase as a legitimate architectural reference
(`claude-skills-sync`, the cache-migration marker, host-shape docs). It is
**not** a personal literal and is **not** a target — see §8.

### 5.3 Group C — path literals in tests (4 files)

| File | Line | Current | Required |
|---|---|---|---|
| `cli/tests/test_hosting.py` | 139 | `slug = slug_for("/home/komi/repos/x")` | `/home/user/repos/x` |
| `cli/tests/test_hosting.py` | 140 | `assert slug.startswith("-home-komi-repos-x-")` | `-home-user-repos-x-` |
| `cli/tests/test_hosting.py` | 141 | `assert len(slug) == len("-home-komi-repos-x-") + 8` | `-home-user-repos-x-` — **see §7 V-1; this line gives no test signal** |
| `cli/tests/test_status.py` | 157 | `(sandbox_home / "projects" / "-home-komi-repos-x" / "pending").mkdir(` | `-home-user-repos-x` |
| `cli/tests/test_status.py` | 164 | `assert "-home-komi-repos-x (project)" in out` | `-home-user-repos-x (project)` — must change **in lockstep** with 157 |
| `cli/tests/test_buckets.py` | 35 | `proj = tmp_path / "projects" / "-home-komi-repos-x"` | `-home-user-repos-x` |
| `cli/tests/test_buckets.py` | 42 | `assert buckets["project"].name == "-home-komi-repos-x"` | `-home-user-repos-x` — lockstep with 35 |
| `cli/tests/test_hosting_fixes.py` | 731-732 | docstring: `` `skills_root: /home/komi/repos` `` … `/home/komi/repos/CLAUDE.md` | `/home/user/repos` (both) |

### 5.4 Group D — home-LAN facts and the host nickname (13 new files)

`cli/tests/test_hosting_fixes.py` also appears here (lines 1035/1054) but
is already counted in §5.3, so the running total across §5.1-§5.4 is
4 + 1 + 4 + 13 = **22 distinct files**.

| File | Line | Current → Required |
|---|---|---|
| `cli/tests/fixtures/memory/nova-host.md` | file | **`git mv` → `beacon-host.md`**; line 1 `The Nova (HA host) runs on Wi-Fi;` → `The Beacon (HA host) runs on Wi-Fi;`. **No other line changes.** Must remain **frontmatter-free** (§6). |
| `cli/tests/fixtures/memory/MEMORY.md` | 3 | `- [Nova host facts](nova-host.md) — LAN host details for the HA box` → `- [Beacon host facts](beacon-host.md) — LAN host details for the HA box`. **Both** label and link target; the link target is matched by `_drop_index_line` (§6). |
| `cli/tests/fixtures/gotchas-journal-excerpt.md` | 33 | `### 2026-06-14 — Nova DHCP IP change silently broke …` → `Beacon DHCP IP change silently broke …`. Rest of entry e4 (lines 34-38) unchanged. |
| `cli/tests/test_import_backlog.py` | 8 | `- e4 2026-06-14 "Nova DHCP IP change…"      knowledge, not in canon` → `"Beacon DHCP IP change…"`. **Coupled to the line above** (§6). Docstring is a fixture map; column alignment is cosmetic — realign if the builder wishes, but the `knowledge, not in canon` classification text must not change. |
| `cli/tests/support.py` | 219 | `fact: str = "The router reserves 192.168.1.232 for the Nova."` → `"The router reserves 192.0.2.232 for the Beacon."` |
| `ui/tests/support.py` | 159 | same string → same replacement |
| `cli/tests/test_teach.py` | 104 | `"The Nova reserves 192.168.1.232.",` → `"The Beacon reserves 192.0.2.232.",` |
| `cli/tests/test_teach.py` | 117 | `run_cli(["teach", "The router UI lives at 192.168.1.254.", "--user"])` → `192.0.2.254` |
| `cli/tests/test_teach.py` | 154 | `assert infer_type("The Nova reserves 192.168.1.232.") == "knowledge"` → `infer_type("The Beacon reserves 192.0.2.232.")`; **verdict stays `"knowledge"`** (§3.1 constraint 2, §7 V-2) |
| `cli/tests/test_round7_fixes.py` | 174 | `"### 2026-07-16 — the Nova reserves its own DHCP lease\n\n"` → `the Beacon reserves …`; **leading lowercase `the` MUST survive** (§3.1 constraint 3) |
| `cli/tests/test_round7_fixes.py` | 175 | `"The router hands 192.168.1.232 to the Nova by MAC reservation.\n"` → `192.0.2.232 to the Beacon` |
| `cli/tests/test_round7_fixes.py` | 213 | `"The Nova reserves 192.168.1.232.",` → `"The Beacon reserves 192.0.2.232.",` |
| `cli/tests/test_round3_fixes.py` | 854 | `"--fact", "The router reserves .232 for the Nova.",` → `… for the Beacon.` — **`.232` unchanged** (K-4) |
| `cli/tests/test_hosting_fixes.py` | 1035, 1054 | `"--fact", "The router reserves .232 for the Nova.",` → `… for the Beacon.` — **`.232` unchanged** (K-4) |
| `cli/tests/test_proposal_validate.py` | 33 | `fact: str = "The Nova serves Glances on :61208."` → `"The Beacon serves Glances on :61208."` — **`:61208` unchanged**: it is Glances' stock default port, not personal |
| `ui/tests/test_proposals.py` | 1173 | `title="The router reserves 192.168.1.232 for the Nova.",` → `192.0.2.232 … the Beacon.` |
| `ui/tests/test_routes.py` | 2675 | `"fact": "The router reserves .232 for the Nova",` → `… for the Beacon` — `.232` unchanged (K-4) |
| `ui/tests/test_routes.py` | 2690 | `"The router reserves .232 for the Nova",` → `… for the Beacon` — **must change in lockstep with 2675**: 2675 seeds the snippet, 2690 asserts the argv the route shells out; a one-sided edit fails the test correctly, but both must move |
| `cli/tests/test_import_memory.py` | 6, 27, 99, 128, 176, 184, 190, 191, 215, 217, 224, 228, 234, 237, 240 | every `nova-host.md` → `beacon-host.md` (15 sites — **see §6; this file was absent from the original scouting inventory**) |

---

## 6. Fixture-coupling map

Fixture edits must stay mutually consistent or tests break for the wrong
reason. These are the couplings, each verified at `b11d9aa`.

**C-1 — journal entry ↔ backlog fixture map.**
`cli/tests/fixtures/gotchas-journal-excerpt.md:33` (entry e4's title) is
described by `cli/tests/test_import_backlog.py:8`. The docstring is a
7-entry map (e1…e7) used as the reader's index for the whole file. Both
must change together.

**C-2 — fixture filename ↔ `ORIGIN_RE` charset.**
`test_import_memory.py:28` pins `^memory/[a-z-]+\.md#sha256:[0-9a-f]{12}$`
and line 83 asserts every origin matches. `beacon-host.md` is lowercase
letters + hyphen: compliant. Any digit or underscore would fail.

**C-3 — fixture filename ↔ `MEMORY.md` link target.**
`import_memory._drop_index_line` (import_memory.py **237-250**) builds
`re.compile(r"\(" + re.escape(filename) + r"\)")` and drops matching
index lines. If `MEMORY.md`'s link target is not renamed in lockstep with
the file, the prune-index test (`test_import_memory.py:228`) breaks.

**C-4 — `TOPIC_FILES` is order-independent.** `test_import_memory.py:27`
is consumed only as `set(TOPIC_FILES)` (line 82) and `for fname in
TOPIC_FILES` (line 89). `beacon-host.md` also happens to preserve
alphabetical position (`b` < `r`), but no assertion depends on it.

**C-5 — fixture content ↔ scope inference.** `test_import_memory.py:6`
records that `nova-host.md` maps to **scope `project` because it has no
frontmatter** (the other two fixtures carry `metadata.type`). The renamed
file MUST remain frontmatter-free, or `test_import_memory.py:99`
(`.scope == "project"`) breaks.

**C-6 — fixture content ↔ origin hashes: SAFE.** Origins are
`sha_anchor(file content)` computed **at runtime** from the copied
fixture (`test_import_memory.py:90`), never hardcoded. Confirmed: **no
hardcoded sha/anchor literals exist in either test suite.** Editing
fixture prose is therefore safe. Likewise record ids are
`secrets.token_hex(4)` (records.py **98-101**), not content-derived.

**C-7 — `make_knowledge`'s default `fact` is a shared default.**
`cli/tests/support.py:219` and `ui/tests/support.py:159` supply the
default fact for every caller that omits one; it becomes the record's
`## Fact` body section (records.py `Record.create`). Confirmed: **no test
asserts this default's text** (the only occurrences of "router reserves"
are the sites listed in §5.4). The full-suite counts in §9 are the guard.

**C-8 — `test_status.py` 157↔164 and `test_buckets.py` 35↔42** are
seed↔assert pairs on the same slug. **C-9 — `ui/tests/test_routes.py`
2675↔2690** is a seed↔assert pair on the same fact string.

---

## 7. Mutation-verification plan

This project's signature bug class is **assertions that pass for the
wrong reason.** Several targets pin exact literals, and a careless
find-and-replace leaves them GREEN while they no longer check what they
claim. For each behavior touched, the mutation to apply and the named
test that MUST fail. **The code gate's reviewer executes these; each
mutation is reverted after it is observed to fail.**

### V-1 — `test_hosting.py:141` gives NO signal. Say so; verify deliberately.

`komi` and `user` are both **four characters**, so
`len("-home-komi-repos-x-") == len("-home-user-repos-x-")`. A builder who
updates lines 139-140 and **misses 141** leaves the suite fully green
**and leaves `komi` in the file.** For this one site the real verification
is the §9 `git grep` gate, **not** the test.

Verify the assertion binds at all:
- **Mutation:** in `hosts.slug_for` (hosts.py **91-106**, return at
  **106**) change the digest slice from `[:8]` to `[:7]`.
- **MUST FAIL:** `cli/tests/test_hosting.py::TestDiscovery::test_slug_for_keeps_readable_shape_and_disambiguates`
- **Second mutation:** change `slug_for`'s `resolved.replace('/', '-')`
  (hosts.py **106**) to `resolved.replace('/', '_')`.
- **MUST FAIL:** the same test (the `startswith` leg, line 140).

### V-2 — `test_teach.py:154` must bind to the classifier, not to any string.

The assertion would pass for almost any sentence starting with "The".

**Do NOT invert `infer_type`'s return.** `test_infer_type_heuristic`
(test_teach.py **150-155**) opens with three *behavior* assertions
(**151-153**); inverting the return fails at line **151** and pytest
never reaches line **154** — the site V-2 exists to protect. That
mutation verifies nothing about our target.

- **Mutation:** flip only the **non-triggerish** branch — add `|the` to
  `_TRIGGERISH_RE`'s alternation (teach.py **111-115**).
- **MUST FAIL:** `cli/tests/test_teach.py::test_infer_type_heuristic`,
  **with the failure observed AT line 154** (the `The Beacon …
  == "knowledge"` assertion). Lines **151-153** pass before it — the
  failure is reported at 154, not earlier — which is what proves 154 is
  the binding site. (Line **155** is *not* part of the observation:
  pytest stops at the first failing assertion, so 155 is never
  evaluated once 154 fails.)
- Collateral failures in other bare-text `teach` tests are expected under
  this mutation and do not invalidate it; only the line-154 failure is
  the verification.
- **Confirms:** the swapped sentence still classifies via the
  *leading-word* rule, i.e. K-3/K-5 are inert for classification
  (verified: `_TRIGGERISH_RE` is `^`-anchored and contains no numeric or
  IP-shaped alternative).
- **Mechanical leading-word check** (converts §3.1 constraint 2 from prose
  into something the reviewer executes): `git grep -n 'the Beacon\|The
  Beacon' -- plugins/` and confirm **every** rewritten sentence still
  opens with `The` / `the`. `_TRIGGERISH_RE` includes a bare `on\b` among
  its alternatives, so "the leading word is fine" must be checked, not
  assumed.

### V-3 — `test_buckets.py:42` (exact slug equality).
- **Mutation:** in `ledger.discover_buckets`, make the project bucket's
  `name` the parent directory's name instead of the slug directory's.
- **MUST FAIL:** `cli/tests/test_buckets.py::test_project_and_user_buckets_are_separate_scopes`

### V-4 — `test_status.py:164` (substring on CLI output).
- **Mutation:** in the human `status` renderer, drop the ` (project)`
  scope suffix from the per-bucket line.
- **MUST FAIL:** `cli/tests/test_status.py::test_status_human_line_with_buckets`

### V-5 — the new no-default behavior actually refuses (replaces the deleted §5.1a test).

Three new tests in `cli/tests/test_import_cli.py`:

- **M-1** — `SELF_LEARN_MEMORY_DIR` unset ⇒ `cli.default_memory_dir() is None`.
  - **Mutation:** restore any string default in `default_memory_dir`.
  - **MUST FAIL:** M-1.
- **M-2** — `SELF_LEARN_MEMORY_DIR` unset ⇒ `cli.main(["import","--memory"]) == EXIT_USAGE` **and** stderr names both `--memory` and `SELF_LEARN_MEMORY_DIR`.
  - **Mutation:** move the guard back **inside** `_cmd_import`'s `try` and raise `ImporterError`.
  - **MUST FAIL:** M-2 (observed rc becomes **1**, not 64). *This is the exact §4.2 placement trap.*
- **M-3** — `SELF_LEARN_MEMORY_DIR` unset ⇒ bare `prune-memory` returns `EXIT_USAGE` **and mutates nothing.**
  - Seed a ledger with a terminal auto-memory record plus a real memory dir whose file matches the recorded origin hash; run bare `prune-memory`; assert rc == 64 **and** the memory file still exists **and** `MEMORY.md` is byte-identical.
  - **Mutation:** in `_cmd_prune_memory`, place the guard **after** the `prune_memory(...)` call.
  - **MUST FAIL:** M-3 — but note **how**: `prune_memory` does `memory_dir = Path(memory_dir)` at import_memory.py **256**, so `Path(None)` raises `TypeError` before any sweep occurs. The failure is a `TypeError`, **not** the file-still-exists assertion.
  - **Honest scope of this mutation:** it verifies the guard is reached *before* `prune_memory`, and nothing more. Once the default is gone, **nothing realistic isolates the no-mutation half** — there is no mutation that both reaches the sweep and leaves the rc at 64. The file-existence and `MEMORY.md` byte-identity assertions are therefore recorded as **defense-in-depth, NOT mutation-verified.** Criterion 7's gate record must say so rather than claim a verification that never happened.

- **M-4** (regression, existing) — the env-override path still works:
  `cli/tests/test_import_cli.py::test_import_memory_env_override_supplies_default` (lines **101-108**) must stay green **unmodified**.

- **M-5 — the guard must NOT reach the `--backlog` path.** This is the
  §4.2 enclosure-2 lock, and it is the difference between a correct build
  and one that manufactures a pass-for-the-wrong-reason.
  - **Assertion:** with `SELF_LEARN_MEMORY_DIR` unset,
    `cli.main(["import", "--backlog", SKILL])` still returns **0**.
  - **Mutation:** hoist **both statements — the resolution AND its
    guard** — above the `if args.backlog is None:` branch (i.e. to the
    top of `_cmd_import`). Moving *only* the guard is a different bug:
    `memory_dir` then keeps its `None` initializer, the guard fires on
    **every** invocation, and `test_import_memory_explicit_dir`
    (test_import_cli.py **93**) and M-4 (**101**) fail too — which is
    **not** the collateral pinned below. Only moving both statements
    reproduces the naive-builder defect this mutation is designed to
    expose.
  - **MUST FAIL:** M-5. Under the same mutation, confirm the collateral
    damage the mutation is designed to expose: three existing backlog
    tests (`…_prints_summary_exit_0` **59**,
    `…_rerun_is_idempotent_at_cli_level` **68**,
    `…_missing_journal_exits_1` **84**) also fail, while
    `test_import_backlog_unknown_skill_is_usage_error` (**78-81**)
    **still passes** — via the memory-dir refusal, never reaching the
    unknown-skill path. **Record that last observation explicitly in the
    gate log**: it is the concrete demonstration of this project's
    signature bug class, caught before it shipped.

### V-6 — the rename is complete.
- **Mutation:** revert the `beacon-host.md` entry in **`TOPIC_FILES`
  (`cli/tests/test_import_memory.py:27`)** back to `nova-host.md`. Pin
  this site specifically — reverting line **6** instead would mutate a
  docstring and fail nothing.
- **MUST FAIL:** `cli/tests/test_import_memory.py::test_one_record_per_topic_file_index_excluded`
  (the `set(TOPIC_FILES)` assertion at line **82**) and
  `::test_origin_is_hash_of_file_content` (lines **89-91**, which raises
  `FileNotFoundError` on the missing name).

---

## 8. Explicitly out of scope

Stated so the gate does not demand them.

- **Everything under `docs/`** except this file (R-1). The spec corpus,
  its 69 commit SHAs, and the session post-mortem naming the user are
  **preserved as a historical record**.
- **Git history** (R-2).
- **Author identity** (R-3): `plugin.json`, both `pyproject.toml` files,
  and cli/tests/test_portability_docs.py **73-74**. Never a target.
- **`claude-skills` as a repo name.** It is the user's real, kept
  repository (R-3) and a legitimate architectural reference across
  gitops.py 15, sentinel.py 26, verbs.py 873/1328, worker.py
  119/126/131/1297, and eight test files. Only its appearance **inside a
  `/home/komi` path or a `-home-komi-…` slug** is in scope, and those are
  handled by K-1/K-2. **Do not sweep `claude-skills`.**
- **`hosts.slug_for` itself is UNTOUCHED.** Its digest is *correct* for
  self-learn's own project buckets; the divergence from Claude Code's
  slug scheme (§4.1) is only the reason **not to reuse it** for the memory
  path. A reviewer must not read "wrong shape for that job" as "fix it."
  No change to `slug_for`, `hosts_path`, or bucket discovery.
- **The multi-project memory sweep** — unregistered-project handling, the
  exclude mechanism, the per-project source report. That is **Spec D**
  (§4.4). This spec leaves the bare `import --memory` form vacant for it.
- **Bare `.232` / `.254` fragments** (K-4) — a recorded decision.
- **`:61208`** — Glances' stock default port, not personal.
- **Home Assistant as a fixture domain.** "HA", "HA box", "`.storage`",
  the Wyoming/Piper journal entries, `DOD_ARGS`' `skill:home-assistant`
  scope: HA is widely-used open-source software and the test corpus's
  subject matter, not personal content. Only the **host identity** (the
  nickname) and the **LAN addresses** are personal. Scrubbing the domain
  would be a suite-wide rewrite far outside R-4.
- **`ui/tests/test_routes.py`'s existing `/home/u/` occurrences** (lines
  115, 117, 2099). Already impersonal; not a target. Do not normalize
  them to `/home/user` — that is unrequested churn.
- **The pre-existing UI test failure**
  `ui/tests/test_service_unit.py::test_both_units_document_manual_registration_via_symlink`.
  Unrelated and out of scope; it must remain the **only** UI failure.
- **`cli/tests/test_portability_docs.py`** — do not edit (§5.1b).
- **`cli/tests/test_lock_invariant.py`** — no change needed. Its
  allowlist already exempts `import_memory.prune_memory` and
  `import_memory._drop_index_line` (lines **146-149**) as "~/.claude
  auto-memory (not a repo)", `_cmd_prune_memory` is already skipped as
  "not a ledger-mutating surface" (line **658**), and line **665** sets
  `SELF_LEARN_MEMORY_DIR` for **every** parametrized case, so no case
  relies on the removed default.

---

## 9. Definition of Done / acceptance criteria

**Step 0 — re-establish all three baselines before the first edit.** The
values below are given; confirm them at `b11d9aa` so any later delta is
attributable to this work.

| Suite | Command (run from) | Baseline |
|---|---|---|
| CLI tests | `plugins/self-learn/cli/` → `.venv/bin/python -m pytest -q` | **1110 passed, 5 skipped** |
| CLI types | `plugins/self-learn/cli/` → `pyright --pythonpath .venv/bin/python src` | **50 errors** |
| UI tests | `plugins/self-learn/ui/` → `uv run pytest -q` | **1002 passed, 1 failed** |

Bare `pyright src` produces wrong-interpreter noise — **do not use it.**

A reviewer can check each of the following against the code:

1. **`DEFAULT_MEMORY_DIR` no longer exists.** `git grep -n
   'DEFAULT_MEMORY_DIR' -- plugins/` returns **zero** hits.
   `default_memory_dir()` is typed `-> Path | None`, reads only
   `SELF_LEARN_MEMORY_DIR`, and returns `None` when unset.
2. **Both verbs fail closed — and only on the memory path.** Each guards
   on `None` **before** any filesystem access and returns `EXIT_USAGE`
   (**64**) with its §4.2 message. In `_cmd_import` the guard is
   **above the `ImporterError` `try` AND inside the non-backlog branch**
   (`if args.backlog is None:`) — **not** above the branch — **and the
   inner dispatch keys on `memory_dir is not None`, not on
   `args.backlog is not None`** (criterion 8 fails at 51 pyright errors
   otherwise). `import --backlog <skill>` is unaffected and still returns
   0 with `SELF_LEARN_MEMORY_DIR` unset (M-5). Both messages contain
   `SELF_LEARN_MEMORY_DIR`; the import message additionally contains
   `--memory`. `cli.py:465`'s help string interpolates **no** path
   literal.
3. **The discriminating property holds:** `prune-memory` cannot reach
   `target.unlink()` via an **inferred** directory — only a
   caller-supplied or env-supplied one. M-3 proves the guard precedes the
   sweep; its file-existence / byte-identity assertions are
   defense-in-depth, **not** mutation-verified (§7 M-3). (Read with the
   §4.3 scope note: an explicitly wrong directory is unchanged and out of
   scope.)
4. `cli/tests/test_import_cli.py::test_default_memory_dir_is_the_pinned_auto_memory_path`
   is **deleted** (not edited), and M-1/M-2/M-3 exist and pass. M-4
   passes **unmodified**.
5. All 22 files in §5 are changed exactly as tabulated — **including
   `skills/self-learn/SKILL.md` 50-51, which the §9 gate cannot catch**
   (§5.1c); the fixture
   rename used `git mv`; every one of the 15 `test_import_memory.py`
   references moved; `MEMORY.md`'s label **and** link target both moved;
   the renamed fixture is still frontmatter-free.
6. `.232` / `.254` bare fragments (5 sites, K-4) and `:61208` are
   **unchanged**. `slug_for`, `test_portability_docs.py`,
   `test_lock_invariant.py`, and `ui/tests/test_routes.py`'s `/home/u/`
   lines are **unchanged**.
7. **Mutation verification V-1…V-6 and M-1…M-5 executed and recorded**,
   each named test observed to FAIL under its mutation and PASS after
   revert. Four notes must appear **verbatim** in the gate record, since
   each marks a place where a green suite would otherwise be misread:
   - **V-1:** `test_hosting.py:141` is length-blind (`komi`/`user` are both
     4 chars) and carries **no signal** for this change; the `git grep`
     gate is its real verification.
   - **V-2:** the mutation is `|the` added to `_TRIGGERISH_RE`, and the
     failure was observed **at line 154** — *not* an inverted return,
     which fails at 151 and never reaches the target site.
   - **M-3:** the no-mutation half (file existence, `MEMORY.md` byte
     identity) is **defense-in-depth, not mutation-verified**; the
     mutation fails via `TypeError` from `Path(None)`.
   - **M-5:** under the hoist-above-branch mutation,
     `test_import_backlog_unknown_skill_is_usage_error` was observed to
     **still pass, for the wrong reason** — record this explicitly.
8. **All three baselines re-established exactly**, not merely "no new
   failures": CLI **1112 passed, 5 skipped** (Step 0's 1110 is the
   PRE-edit baseline; criterion 4 deletes one test and §7 V-5 adds three,
   so 1110 − 1 + 3 = 1112 — verify the reconciliation, not just the
   total); pyright **exactly 50
   errors** (a 51st means the `_cmd_import` dispatch was left keyed on
   `args.backlog` — see §4.2); UI **1002 passed, 1 failed** with
   `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
   still the **only** failure.
9. **The final gate:**

   ```
   git grep -n -iE 'komi|192\.168\.1\.|\bNova\b' -- plugins/
   ```

   returns **ZERO** hits.

10. **Supplementary gate** (the new name must not collide with anything
    pre-existing, which would make criterion 9 vacuous):
    `git grep -in 'beacon' -- plugins/` returns hits **only** at the §5.4
    sites — no incidental pre-existing use. (Verified zero at `b11d9aa`.)

11. **Behavior change is reported to the user at merge** (§4.3): bare
    `self-learn import --memory` and bare `self-learn prune-memory` now
    exit 64 instead of silently targeting the stale `claude-skills`
    project. This is a deliberate trade, and Spec D fills the vacancy.
