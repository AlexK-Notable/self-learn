# Spec — make this repo publishable (licence, CLA, marketplace manifest, public README)

Status: DRAFT rev 1 — for BLIND Opus spec gate (reviewer reads this spec +
the code only; no review notes).

Origin: the user has decided to open `github.com/AlexK-Notable/self-learn`
to the public. The prior unit (`cf22d13`, `6105983`, `ac28695`) removed
owner-specific literals from `plugins/**`, which was the *content*
precondition. This unit supplies the *legal and distribution*
preconditions, which are absent: there is no LICENSE file, three manifests
declare a licence the repo does not grant, there is no marketplace
manifest so the plugin cannot be installed, there is no contribution
agreement, and the README tells a reader the repo is private.

Scope: four new root files, three manifest edits, one README rewrite, one
shipped-source docstring correction, five new tests, and the corpus
recording of a ruling reversal. **No behavior change in any verb.** No
schema change, no lock change, no new public CLI surface.

Pin the code at commit `ac28695fbb1c36b108ae70c6973d6123f3f5840c`
(`git rev-parse HEAD`). All anchors are against that commit. Paths are
repo-relative from `/home/komi/repos/self-learn`; within a table, `cli/`
and `ui/` are shorthand for `plugins/self-learn/cli/` and
`plugins/self-learn/ui/`.

---

## 1. Problem statement

### 1.1 The headline defect — a declared licence that grants nothing

`plugins/self-learn/.claude-plugin/plugin.json:15` declares:

```json
"license": "MIT",
```

and both `cli/pyproject.toml:6` and `ui/pyproject.toml:6` declare
`license = { text = "MIT" }`. **No licence text exists anywhere in the
repo.** Verified at `ac28695`:

```
$ git ls-files | grep -i licen     # → no output, exit 1
```

Under the Berne Convention default, a work published with no licence
grant is **all rights reserved**. A bare `"license": "MIT"` string in a
manifest is metadata, not a grant: it identifies a licence by name
without reproducing the terms, and the MIT licence's own operative
sentence ("Permission is hereby granted…") never appears. So today the
repo simultaneously (a) advertises MIT, and (b) grants nothing. Publishing
it in that state is worse than publishing it with no declaration at all,
because the declaration invites reliance the repo does not support.

The three declarations are also about to become *wrong on their face*: the
user's ratified licence is FSL-1.1-MIT, not MIT.

### 1.2 The plugin cannot be installed

`plugins/self-learn/.claude-plugin/plugin.json` exists, but a **plugin
manifest is not an install surface**. Claude Code installs plugins from a
*marketplace* manifest at `.claude-plugin/marketplace.json` in a
repository root. That file does not exist here. Verified live at
`ac28695`, from the repo root:

```
$ claude plugin validate .
Validating plugin manifest: /home/komi/repos/self-learn

✘ Found 1 error:

  ❯ directory: No manifest found in directory. Expected .claude-plugin/marketplace.json or .claude-plugin/plugin.json

✘ Validation failed
```

So a stranger who finds the public repo has **no supported install path**
at all: `/plugin marketplace add AlexK-Notable/self-learn` fails, and
`install.sh` is a live-symlink development deploy, not a distribution
mechanism.

### 1.3 The README tells the reader the repo is private

`README.md:38-40`:

```bash
# self-learn is a PRIVATE repo — cloning it needs an SSH key on file
# with access to AlexK-Notable/self-learn (P-C1.4: private, by ruling)
git clone git@github.com:AlexK-Notable/self-learn.git ~/repos/self-learn
```

This is the *first* instruction a reader meets. It is about to be false,
and it prescribes an SSH clone that a public visitor cannot perform.

### 1.4 Contribution without a CLA forecloses relicensing — permanently

GitHub's default is **inbound = outbound**: absent a separate agreement,
a contributor licenses their contribution under the project's outbound
licence and **retains their own copyright in it**. The moment a third
party's patch merges, the project owner can no longer unilaterally
relicense the codebase — not to a proprietary licence, not to a dual
licence, not even to a *more* permissive one — because part of the work
is no longer theirs to relicense.

A DCO does not solve this. A DCO is a **certification of origin**: the
signer attests that they wrote the contribution or have the right to
submit it. It transfers no rights and grants no relicensing power. It is
the correct instrument for a project that never intends to change its
licence, and the wrong one here.

The user's stated intent is to preserve the option to close-source or
dual-licence future versions. That intent requires an actual grant, taken
before the first external merge.

---

## 2. Binding rulings (RATIFIED — constraints, not open questions)

The gate must **not** demand work that contradicts these.

- **R-1 — Licence is FSL-1.1-MIT.** Functional Source License, Version
  1.1, MIT Future License. SPDX identifier `FSL-1.1-MIT`. Copyright
  holder: **Alex Kechichian**. Canonical template:
  `getsentry/fsl.software`, file `FSL-1.1-MIT.template.md`. The licence
  text is **transcribed, never reconstructed** — §4 carries the fetched
  text verbatim.
- **R-2 — A CLA is required, with a broad relicensing grant.** Not a DCO.
  The grant must let the owner relicense contributions under any terms,
  including proprietary. §6.
- **R-3 — The repo becomes public.** This reverses P-C1.4 and its
  ratifying ground, doc 13 §7.3 **D2**. §7.
- **R-4 — Author identity STAYS.** Real name and email in `plugin.json`,
  both `pyproject.toml` files, and the assertions at
  `cli/tests/test_portability_docs.py` **73-74**. Never a target. (Carried
  from P-C1.3 and the prior unit's R-3.)
- **R-5 — `docs/specs/**` is a historical record.** Past *drafts* are not
  retroactively edited to reverse a ruling. The corpus's own dated
  amendment convention is used instead — §7 identifies exactly which
  documents that convention licenses editing and which it does not.
- **R-6 — Git history is NOT rewritten.** No `filter-repo`, no squash.

---

## 3. Pinned decisions with their grounds

Each of these was a real fork. The evidence is recorded so the gate can
check the reasoning, not just the outcome.

### 3.1 D-1 — PEP 639 string form, not the `{ text = … }` table

**Decision: both `pyproject.toml` files use `license = "FSL-1.1-MIT"`.**

This was decided **empirically, not by preference.** A scratch project
(outside the repo, under the session scratchpad) with
`[build-system] requires = ["hatchling"]` — byte-identical to
`cli/pyproject.toml:17-19` — was built three times with `uv build
--no-cache` (uv 0.9.25):

| `[project].license` value | Build result | Emitted metadata |
|---|---|---|
| `"FSL-1.1-MIT"` | **succeeds** | `Metadata-Version: 2.4` / `License-Expression: FSL-1.1-MIT` |
| `"not-a-real-license-xyz"` | **FAILS** — `ValueError: Error parsing field \`project.license\` - Unknown license: 'not-a-real-license-xyz'` (hatchling `metadata/core.py:685`) | — |
| `{ text = "NOT-A-REAL-LICENSE-XYZ" }` | **succeeds silently** | `Metadata-Version: 2.4` / `License: NOT-A-REAL-LICENSE-XYZ` |

Two conclusions, both load-bearing:

1. **The string form is machine-validated against the SPDX licence list;
   the table form is unvalidated free text.** Row 3 is precisely the
   defect class §1.1 exists to repair — a licence declaration nobody
   checks. Choosing the table form here would fix the *value* while
   preserving the *mechanism* that let the wrong value survive.
2. **Row 2 is simultaneously the proof that `FSL-1.1-MIT` is a recognized
   SPDX identifier.** Row 1 did not succeed because hatchling is lenient;
   the negative control shows it is not. This is a positive-control /
   negative-control pair, and it is the whole argument.

The table form is also the *deprecated* PEP 639 spelling. Nothing else
recommends it.

**Residual risk the DoD must close:** `Metadata-Version: 2.4` requires a
recent build backend and installer. `[build-system] requires =
["hatchling"]` is unpinned in both projects, so `uv sync` fetches the same
hatchling that passed row 1 above. Criterion 9 re-runs both suites to
prove the editable installs still resolve.

### 3.2 D-2 — the plugin `version` field is REMOVED, not bumped

**Decision: delete `"version": "0.1.0"` from
`plugins/self-learn/.claude-plugin/plugin.json`, and do NOT set `version`
in the new marketplace entry.** Version resolves to the git commit SHA.

Grounded in two **distinct** Claude Code documents. Each quote below is
verbatim and **individually attributed** — this spec pins "transcribed,
never reconstructed" for the licence (§4) and the same standard applies to
its own citations.

**Source A — `plugin-marketplaces`, "Version resolution and release
channels":**

> Claude Code resolves a plugin's version from the first of these that is
> set:
>
> 1. `version` in the plugin's `plugin.json`
> 2. `version` in the plugin's marketplace entry
> 3. The git commit SHA of the plugin's source

> Avoid setting `version` in both `plugin.json` and the marketplace entry.
> Claude Code always uses the `plugin.json` value without warning, so a
> stale manifest version can mask a version you set in `marketplace.json`.

**Source B — `plugins-reference`, the version-resolution Warning:**

> If you set `version` in `plugin.json`, you must bump it every time you
> want users to receive changes. Pushing new commits alone is not enough,
> because Claude Code sees the same version string and keeps the cached
> copy. If you're iterating quickly, leave `version` unset so the git
> commit SHA is used instead.

*(The two documents carry parallel warnings in different words; `plugin-
marketplaces`' version reads "Setting `version` pins the plugin. … Bump the
field on every release, or omit it to use the commit SHA." Either
substantiates the point; do not blend them into a single quotation.)*

`plugins-reference`'s guidance table names commit-SHA versioning as "Best
for: Internal or team plugins under active development", and explicit
versioning as "Best for: Published plugins with stable release cycles."

**This repo is the former, factually.** Verified at `ac28695`: one git tag
in the entire history (`v1.1`), no `CHANGELOG.md`, and a per-unit gated
commit cadence (the spec corpus's two-gate discipline commits on every
CLEAN gate). A pinned `0.1.0` that nobody bumps means **every future
commit is invisible to installed users** — the exact documented failure
mode. Keeping the pin would ship a broken update path on day one.

`version` is safe to remove: the plugin reference states **"If you include
a manifest, `name` is the only required field."**

**Verified nothing reads it.** `git grep -n 'SCAFFOLD_VERSION|__version__|
importlib.metadata' -- plugins/self-learn/cli/src plugins/self-learn/ui/src`
returns four hits, none of which read our own `plugin.json`:
`cli/src/self_learn/__init__.py:3` (`__version__ = "0.1.0"`, the Python
package version — **out of scope**, see §8) and
`skill_scaffold.py:35,71,126` (`SCAFFOLD_VERSION`, which is written *into
generated* manifests for other repos' plugins — see §5.5). No test asserts
our manifest's version; `cli/tests/test_new_skill.py:104`
(`assert data["version"] == "0.1.0"`) asserts the **scaffolded** manifest
and is unaffected.

**User-visible consequence to report at merge:** the plugin no longer
carries a semantic version. If the packaging phase (`forward/packaging.md`
FW-10) later establishes a release cadence with a `CHANGELOG.md`, this
decision reopens — that is a declared input change under 03's own register
rule, not a defect.

### 3.3 D-3 — marketplace name = `self-learn` (RATIFIED)

The manifest's `name` is public-facing: users type
`/plugin install self-learn@<marketplace-name>`.

**Checked against the reserved list** in the current marketplace docs —
`claude-code-marketplace`, `claude-code-plugins`, `claude-plugins-official`,
`claude-plugins-community`, `claude-community`, `anthropic-marketplace`,
`anthropic-plugins`, `agent-skills`, `anthropic-agent-skills`,
`knowledge-work-plugins`, `life-sciences`, `claude-for-legal`,
`claude-for-financial-services`, `financial-services-plugins`,
`first-party-plugins`, `healthcare`, plus any name impersonating an
official source. **`self-learn` is on none of these lists and impersonates
nothing.** It is kebab-case with no spaces, as required.

**RATIFIED BY THE USER: `self-learn`.** The install sequence is therefore
pinned and final:

```
/plugin marketplace add AlexK-Notable/self-learn
/plugin install self-learn@self-learn
```

It matches the repo, so the `marketplace add` argument and the marketplace
name agree and there is no second identifier to learn. The install line is
redundant-looking but self-evidently correct.

**This is settled — the gate must not reopen it.** An earlier revision of
this spec carried the name as a user-ratifiable question with
`alexk-notable` as an alternative; the user has since ruled. The
alternative is recorded here only as history, not as a live option: it
reads better (`self-learn@alexk-notable`) and would leave room to publish
a second plugin under one marketplace, so it is the name to revisit **if
and only if** a second plugin ever ships. Until then, `self-learn` is
binding and the builder writes it without comment.

### 3.4 D-4 — CLA enforcement is a PR sign-off line checked by hand

Not a CLA bot, not a signed-document workflow. §6.3 gives the reasoning
and the escalation trigger.

### 3.5 D-5 — `docs/specs/**` gets no licence of its own

The corpus is part of the repository and is therefore covered by the root
`LICENSE` like every other file. Minting a second licence (e.g. CC-BY for
docs) would create a boundary question — where does "documentation" end
and "the Software" begin, given the corpus contains fixtures, YAML
proposals and shell runbooks — for no benefit the user has asked for.

**Recommendation: one clarifying sentence in
`docs/specs/self-learn/README.md`** noting the corpus ships under the repo
LICENSE and is a historical record, not a specification of the shipped
product. That is proportionate. Do not add a `docs/LICENSE`.

---

## 4. `LICENSE` — the verbatim text to be written

**File: `LICENSE` at the repo root** (no extension). Fetched from
`getsentry/fsl.software`, `FSL-1.1-MIT.template.md`. The template's two
placeholders — `${year}` and `${licensor name}` — are substituted with
`2026` and `Alex Kechichian`. **Nothing else changes: not a heading, not a
clause, not the section order.** The builder MUST NOT retype this from
memory; it is reproduced here so the exact bytes are reviewable.

```markdown
# Functional Source License, Version 1.1, MIT Future License

## Abbreviation

FSL-1.1-MIT

## Notice

Copyright 2026 Alex Kechichian

## Terms and Conditions

### Licensor ("We")

The party offering the Software under these Terms and Conditions.

### The Software

The "Software" is each version of the software that we make available under
these Terms and Conditions, as indicated by our inclusion of these Terms and
Conditions with the Software.

### License Grant

Subject to your compliance with this License Grant and the Patents,
Redistribution and Trademark clauses below, we hereby grant you the right to
use, copy, modify, create derivative works, publicly perform, publicly display
and redistribute the Software for any Permitted Purpose identified below.

### Permitted Purpose

A Permitted Purpose is any purpose other than a Competing Use. A Competing Use
means making the Software available to others in a commercial product or
service that:

1. substitutes for the Software;

2. substitutes for any other product or service we offer using the Software
   that exists as of the date we make the Software available; or

3. offers the same or substantially similar functionality as the Software.

Permitted Purposes specifically include using the Software:

1. for your internal use and access;

2. for non-commercial education;

3. for non-commercial research; and

4. in connection with professional services that you provide to a licensee
   using the Software in accordance with these Terms and Conditions.

### Patents

To the extent your use for a Permitted Purpose would necessarily infringe our
patents, the license grant above includes a license under our patents. If you
make a claim against any party that the Software infringes or contributes to
the infringement of any patent, then your patent license to the Software ends
immediately.

### Redistribution

The Terms and Conditions apply to all copies, modifications and derivatives of
the Software.

If you redistribute any copies, modifications or derivatives of the Software,
you must include a copy of or a link to these Terms and Conditions and not
remove any copyright notices provided in or with the Software.

### Disclaimer

THE SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING WITHOUT LIMITATION WARRANTIES OF FITNESS FOR A PARTICULAR
PURPOSE, MERCHANTABILITY, TITLE OR NON-INFRINGEMENT.

IN NO EVENT WILL WE HAVE ANY LIABILITY TO YOU ARISING OUT OF OR RELATED TO THE
SOFTWARE, INCLUDING INDIRECT, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES,
EVEN IF WE HAVE BEEN INFORMED OF THEIR POSSIBILITY IN ADVANCE.

### Trademarks

Except for displaying the License Details and identifying us as the origin of
the Software, you have no right under these Terms and Conditions to use our
trademarks, trade names, service marks or product names.

## Grant of Future License

We hereby irrevocably grant you an additional license to use the Software under
the MIT license that is effective on the second anniversary of the date we make
the Software available. On or after that date, you may use the Software under
the MIT license, in which case the following will apply:

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Two things the builder must not do:** leave a literal `${` anywhere in
the file (test O-P1 asserts this), and reformat the markdown. The FSL is
distributed as markdown by design.

### 4.1 Claim → clause map (the licence-prose verification plan)

Every claim the new prose makes about the licence must be substantiated by
a named clause. This table IS the verification plan for §5's README and
CONTRIBUTING copy: the gate reviewer checks each written sentence against
its row, and any sentence with no row is unsubstantiated and must be cut.

| Claim the prose may make | Clause that substantiates it | Operative words |
|---|---|---|
| Commercial and workplace use is permitted | **Permitted Purpose** | "Permitted Purposes specifically include using the Software: (1) for your internal use and access" |
| You may read, modify, fork, redistribute | **License Grant** | "the right to use, copy, modify, create derivative works, publicly perform, publicly display and redistribute" |
| …but only for a Permitted Purpose | **License Grant** | "Subject to your compliance with this License Grant…for any Permitted Purpose identified below" |
| Reselling / competing is the thing barred | **Permitted Purpose** | the three-limb Competing Use definition: "substitutes for the Software" / "substitutes for any other product or service we offer" / "offers the same or substantially similar functionality" |
| Redistribution must carry the licence | **Redistribution** | "you must include a copy of or a link to these Terms and Conditions and not remove any copyright notices" |
| Each version converts to MIT after two years | **Grant of Future License** | "irrevocably grant you an additional license…effective on the second anniversary of the date we make the Software available" |
| The conversion is per *version*, not per repo | **The Software** | "each version of the software that we make available" |
| The conversion cannot be withdrawn | **Grant of Future License** | "irrevocably" |
| No warranty | **Disclaimer** | "PROVIDED \"AS IS\" AND WITHOUT WARRANTIES OF ANY KIND" |
| No trademark rights | **Trademarks** | "you have no right…to use our trademarks, trade names, service marks or product names" |

### 4.2 Two things the prose must NOT say — both are wrong

- **Do NOT call FSL open source.** It is **source-available**. The ground
  is internal to the licence: the License Grant is *conditioned* on a
  Permitted Purpose, i.e. the grant discriminates by field of endeavour.
  Write the claim from that clause.

  **Do NOT cite "OSI clause 6"** as the reason, in the README or anywhere
  a reader sees. That clause number belongs to the Open Source Definition,
  a document the licence does not contain — citing it inside prose about
  the LICENSE file is a cross-reference to a clause that is not there.
  P-C1.19 exists because a wrong cross-reference, once propagated, gets
  copied again. Ground the claim on the License Grant's conditionality
  instead, which is checkable against the file the reader is standing in.

- **Do NOT describe FSL as prohibiting commercial use.** It does not.
  Verbatim: "Permitted Purposes specifically include using the Software:
  (1) for your internal use and access". A company may deploy it, build on
  it, and use it to make money internally. **Only Competing Use is
  barred** — offering it, or something substantially similar, to others as
  a commercial product or service. Any sentence containing
  "non-commercial" as a description of the *whole* licence is false; the
  word appears in the licence only in limbs (2) and (3) of the Permitted
  Purposes list, which *widen* the grant rather than narrow it.

---

## 5. Per-file change table

**15 files.** Every anchor re-verified at `ac28695`.

Running total, counting **files** and never table rows:

| § | Files | What |
|---|---|---|
| 5.1 | **4** | `LICENSE`, `.claude-plugin/marketplace.json`, `CONTRIBUTING.md`, `CLA.md` (all new) |
| 5.2 | **3** | `plugin.json` (**3 edits: licence, version, repository**), `cli/pyproject.toml`, `ui/pyproject.toml` |
| 5.3 | **2** | `README.md` (§5.3a-c), `plugins/self-learn/README.md` (§5.3d) |
| 5.4 | **3** | doc 13, `03-decisions.md`, corpus `README.md` |
| 5.5 | **1** | `cli/src/self_learn/skill_scaffold.py` |
| 5.6 | **1** | `cli/tests/test_portability_docs.py` (2 modified assertions + 5 new tests) |
| — | **1** | this spec file |

4 + 3 + 2 + 3 + 1 + 1 + 1 = **15**.

### 5.1 New files at the repo root (4)

| File | Content |
|---|---|
| `LICENSE` | **§4 verbatim**, with `${year}`→`2026`, `${licensor name}`→`Alex Kechichian`. No other edit. |
| `.claude-plugin/marketplace.json` | **§5.1a verbatim.** |
| `CONTRIBUTING.md` | §6.3. Must state the CLA as a merge precondition and link `CLA.md`. |
| `CLA.md` | §6.2 — the substantive grant. |

**Confirmed not blocked:** `.gitignore` at `ac28695` contains only
`.playwright-mcp/`, `.claude/worktrees/`, and five `.codeboarding/`
entries. **Nothing excludes a root `.claude-plugin/`.** This check matters
because a gitignored manifest is invisible to `/plugin marketplace add
owner/repo` and fails silently.

#### 5.1a — `.claude-plugin/marketplace.json`, exact content

```json
{
  "name": "self-learn",
  "owner": {
    "name": "Alex Kechichian",
    "email": "alexkechichian1@gmail.com"
  },
  "description": "Capture, triage, and route Claude Code session lessons into canon via a git-backed ledger.",
  "plugins": [
    {
      "name": "self-learn",
      "source": "./plugins/self-learn",
      "description": "Capture, triage, and route session lessons into skills, CLAUDE.md, references, and hooks via a git-backed ledger — teach/review slash commands plus the self-learn CLI.",
      "author": {
        "name": "Alex Kechichian",
        "email": "alexkechichian1@gmail.com"
      },
      "homepage": "https://github.com/AlexK-Notable/self-learn",
      "repository": "https://github.com/AlexK-Notable/self-learn",
      "license": "FSL-1.1-MIT",
      "keywords": ["self-learning", "lessons", "ledger", "capture", "triage", "claude"]
    }
  ]
}
```

Schema grounds, each verified against the current marketplace docs:

- **Required top-level:** `name` (string, kebab-case), `owner` (object),
  `plugins` (array). All three present.
- **`owner`:** `name` required, `email` optional. Both present.
- **Required per plugin entry:** `name`, `source`. Both present.
- **`source` as a relative path** resolves "relative to the marketplace
  root, which is the directory containing `.claude-plugin/`" — here the
  repo root, so `./plugins/self-learn` points at
  `<repo>/plugins/self-learn`. This is the documented self-hosting layout.
  Do not use `../`.
- **`version` deliberately absent** from the entry — D-2. The entry
  carries no `version` key at all; adding one silently re-pins.
- `description`, `author`, `homepage`, `repository`, `license`, `keywords`
  are documented optional entry fields. **`repository` is typed `string`
  — in the marketplace entry AND in `plugin.json`.** An earlier revision
  of this spec claimed `plugin.json` takes an object; that was **wrong**,
  and the error is now a BLOCKER-grade change in its own right — see
  §5.2's `repository` row and §5.2a.
- **The top-level `description` is not optional in practice.** It is
  schema-optional, but omitting it makes `claude plugin validate .` emit
  *"description: No marketplace description provided…"*. Since criterion 4
  makes the validator an acceptance gate, include it — the content above
  clears that warning (empirically confirmed, §5.2a).
- **Formatting:** 2-space JSON + trailing newline. This is not cosmetic —
  `skill_scaffold.marketplace_with_entry` (skill_scaffold.py **98-130**)
  rewrites marketplace files as `json.dumps(data, indent=2,
  ensure_ascii=False) + "\n"`, and matching that shape keeps a future
  `route --dest new-skill` against this repo a minimal diff. See §5.5b.

### 5.2 The three false MIT declarations (3 files, 5 edits — `plugin.json` three times)

**Count the FILES, not the table rows.** `plugins/self-learn/.claude-plugin/plugin.json`
appears **three** times below — line 15 the licence, line 3 the version,
and the `repository` row added by §5.2a — and is **one** file against
§5's total of 15.

*(Corrected: an earlier revision read "4 edits — `plugin.json` twice"
and "a total of 14", written before §5.2a added the `repository` row.
The table rows and §5's summary were already right; only this heading
and paragraph lagged.)*

| File | Line | Current | Required |
|---|---|---|---|
| `plugins/self-learn/.claude-plugin/plugin.json` | 15 | `  "license": "MIT",` | `  "license": "FSL-1.1-MIT",` |
| `plugins/self-learn/.claude-plugin/plugin.json` | 3 | `  "version": "0.1.0",` | **DELETE the line** (D-2). `name` is the only required field. |
| `cli/pyproject.toml` | 6 | `license = { text = "MIT" }` | `license = "FSL-1.1-MIT"` (D-1 — **string form, not a table**) |
| `ui/pyproject.toml` | 6 | `license = { text = "MIT" }` | `license = "FSL-1.1-MIT"` (D-1) |
| `plugins/self-learn/.claude-plugin/plugin.json` | 11-14 | `  "repository": {`<br>`    "type": "git",`<br>`    "url": "https://github.com/AlexK-Notable/self-learn.git"`<br>`  },` | `  "repository": "https://github.com/AlexK-Notable/self-learn.git",` — **collapse the object to a string.** Mandatory: the object form makes `claude plugin validate .` FAIL (§5.2a). |

**One existing test changes as a direct consequence.**
`test_portability_docs.py::test_o8_plugin_json_names_self_learn_repo`
(**68-74**) currently asserts `data["repository"]["url"] == …` at line
**71**. That subscript raises `TypeError` once `repository` is a string,
so line 71 becomes
`assert data["repository"] == "https://github.com/AlexK-Notable/self-learn.git"`.
**Line 70 (`homepage`) and lines 73-74 (author name/email) are NOT
touched** — R-4 protects the author identity, and `homepage` is already a
string. This is the only edit to an existing assertion in this file
besides §5.3c's tripwire inversion.

### 5.2a — why the `repository` change is in scope, and the evidence

**Verified live** (Claude Code v2.1.219) by replicating the post-change
tree in a scratch directory — the new `marketplace.json` from §5.1a plus
a `plugin.json` carrying today's object-form `repository`:

```
❯ plugins[0] plugin.json → repository: Invalid input: expected string, received object
✘ Validation failed          (rc=1)
```

With `repository` as a string **and** the top-level marketplace
`description` present:

```
⚠ plugins[0] plugin.json → version: No version specified. Consider adding a version following semver (e.g., "1.0.0")
✔ Validation passed with warnings   (rc=0)
```

**Why this is this unit's problem and not a pre-existing defect.** The
object form is inert today — nothing validates `plugin.json` because
nothing points at it. It becomes blocking *because this unit creates the
marketplace manifest*: when an entry's `source` is a local path, the
validator descends into that plugin's own `plugin.json` and applies the
manifest schema, where the docs type `repository` as **string**. This unit
both introduces the per-entry validation and makes the validator an
acceptance criterion (criterion 4), so it owns the consequence.

**R-4 permits the fix.** R-4 protects the author's *name and email*. The
`repository` field is neither.

**The residual `version` warning is EXPECTED, not breakage.** It is the
direct, intended consequence of D-2 removing the pin. Criterion 4 is
stated as "passes, warnings permitted" precisely so a builder does not
read it as a failure and re-add `version` — which would silently undo D-2.

**Do not touch** `version = "0.1.0"` in either `pyproject.toml`. That is
the Python distribution version, a different thing from the plugin
manifest version D-2 removes — see §8.

### 5.3 `README.md` (repo root) (1)

Three edits. **Two live tripwires constrain this rewrite** — see §5.3c.

#### 5.3a — replace lines 35-50 (heading through the ledger paragraph)

**The range is 35-50, not 35-45.** Line 35 is the `## Install (this
machine's live-symlink model)` heading; 37-45 is the fenced block
containing the private-repo comment quoted in §1.3; **47-50 is the ledger
paragraph** ("The ledger needs a git repo at `$SELF_LEARN_HOME` …"). That
paragraph appears at the END of the replacement block below, so it is
**MOVED, not COPIED** — a builder who replaces only 35-45 and then pastes
the block verbatim will emit the ledger paragraph twice. The duplicate
would not fail any test (the §5.3c tripwire only needs the strings to be
present *somewhere*), so nothing but this note catches it.

Required shape (exact prose is the builder's, but every element below is
mandatory and the §5.3c tripwires bind):

```markdown
## Install

### As a Claude Code plugin (the short path)

```
/plugin marketplace add AlexK-Notable/self-learn
/plugin install self-learn@self-learn
```

That gives you the skill and the `/self-learn:*` slash commands.

### Full install — everything the plugin mechanism cannot deliver

The plugin install covers the skill and commands. It does **not** cover
the parts that live outside a plugin's boundary:

- the `~/bin` shims — `self-learn`, `self-learn-ui`, `self-learn-ui-open`,
  `self-learn-notify`
- the two `systemd --user` units (nightly miner timer; the G-3 UI service)
- the desktop launcher + icon
- the SessionStart pending-count hook symlink into `~/.claude/hooks/`
  (registration in `settings.json` stays manual either way)
- `uv sync` of the CLI project

For those, clone and run `install.sh`:

```bash
git clone https://github.com/AlexK-Notable/self-learn.git ~/repos/self-learn
cd ~/repos/self-learn && ./install.sh
# then (manual, load-bearing): register the SessionStart hook in ~/.claude/settings.json
systemctl --user enable --now self-learn-miner.timer
systemctl --user enable --now self-learn-ui.service   # G-3 surface, see below
```

`install.sh` is a **live-symlink** deploy: the repo working tree *is* the
installed copy, so edits are live next session. The two routes are
alternatives for the skill and commands, not a sequence — pick one.

The ledger needs a git repo at `$SELF_LEARN_HOME` (default
`~/.self-learn`) before anything else works — bootstrap one with
`self-learn init`; then register canon targets with `self-learn host add
<path> [--skills-root]`.
```

**The `install.sh` surface list above is exhaustive and verified** against
install.sh **4-24** and **48-100**: skill symlink (**52**), commands
(**55**), `~/bin/self-learn` (**58**), the three G-3 scripts
(**61-63**), the generated `.desktop` + icon (**72-74**), the
SessionStart hook symlink (**80**) with its manual-registration notice
(**81**), `uv sync` (**83-87**), miner units (**91-92**), UI unit
(**97**). A reviewer will check this list; do not abbreviate it.

**The "pick one" sentence is required and its scope is deliberately
limited.** `install.sh` symlinks the skill to `~/.claude/skills/self-learn`
while a plugin install places it in the plugin cache under a different
namespace. Whether both being present causes duplicate skill activation
was **NOT tested** — testing it would require writing to the real
`~/.claude`, which this unit's safety rules forbid. So the README states
the two routes are alternatives and **must not claim a specific failure
mode**. Recorded as a residual unknown in §9 criterion 11, not as a
verified fact.

#### 5.3b — add a `## License` section

Placement: after `## Development`, at the end of the file. Every sentence
must map to a §4.1 row. Required content:

- SPDX identifier `FSL-1.1-MIT`, full name spelled once, link to `LICENSE`.
- **"source-available, not open source"**, grounded on the License Grant
  being conditioned on a Permitted Purpose. **No "OSI clause 6"** (§4.2).
- Internal and commercial use **permitted** — cite the Permitted Purpose
  clause's own "internal use and access" language.
- Competing Use — offering it or substantially similar functionality to
  others as a commercial product or service — is what is barred.
- **Each version converts to MIT on the second anniversary of its
  release**, irrevocably, per version.
- One closing line: this is a summary for orientation, not a substitute
  for the licence text.

The section must **not** contain the word "non-commercial" as a
description of the licence as a whole (§4.2).

#### 5.3c — THREE live tripwires; the third must be INVERTED, not merely avoided

All three live in `cli/tests/test_portability_docs.py` and all three
assert against `README.md` **whole-file**:

1. **`test_o11_readme_states_git_repo_prerequisite_and_names_init`
   (lines 96-99)** asserts `"self-learn init" in text` **and**
   `"git repo" in text`. The §5.3a block preserves both **in the ledger
   paragraph**, which is why that paragraph is carried forward verbatim
   rather than reworded. A builder who trims it fails this test.
2. **`test_o6_readme_install_blocks_have_no_repos_claude_skills`
   (lines 34-49)** asserts `"repos/claude-skills" not in text`. The
   rewrite must not introduce that slash-spelled literal. It does not
   today and the new copy does not either — but the clone path changes
   from SSH to HTTPS in this edit, so the line is being touched.

3. **`test_o11_readme_clone_block_discloses_private_repo` (lines
   102-107) — THIS ONE BREAKS, and it breaks the worst way.** It reads:

   ```python
   marker = "git clone git@github.com:AlexK-Notable/self-learn.git"
   idx = text.index(marker)
   window = text[max(0, idx - 200) : idx]
   assert "private" in window.lower()
   ```

   `str.index` raises **`ValueError`** when the substring is absent, so
   after §5.3a this test **errors** rather than failing cleanly — a
   builder reading a traceback may misdiagnose it as an unrelated break.
   Its whole purpose is to enforce a disclosure that R-3 abolishes.

   **Required: INVERT it, do not delete it.** Rename to
   `test_o11_readme_clone_block_is_public_https` and assert the public
   posture in place of the private one:

   ```python
   assert "https://github.com/AlexK-Notable/self-learn.git" in text
   assert "git@github.com:AlexK-Notable/self-learn.git" not in text
   ```

   **Inverting beats deleting.** The O-11 obligation — *the clone block
   must tell the truth about how to obtain the repo* — survives R-3; only
   its truth-value flips. Deleting would retire a live guard on the exact
   literal this unit removes, leaving nothing to catch a future
   reintroduction of the SSH-only block. Keeping the test count flat also
   keeps §9's arithmetic simple.

**`test_portability_docs.py` therefore takes exactly two modified
assertions and five additions** — the §5.2 `repository` line, this
inversion, and §5.6's new tests. **No other existing test is edited.**

#### 5.3d — `plugins/self-learn/README.md`, the SECOND install surface (1 file)

A stranger who lands on the plugin directory meets a different install
story. Two defects at `ac28695`:

| Line | Current | Required |
|---|---|---|
| 17-18 | "(live symlinks — edits in the repo are live next session, **never `claude plugin install` on this machine**)" | The "on this machine" qualifier is invisible to a stranger, and post-publication `/plugin install` is a **supported** route. Reword so the parenthetical describes *this deploy's* model without appearing to forbid the plugin route for everyone — e.g. "(live symlinks — edits in the repo are live next session; this is the development deploy, not `/plugin install`)". |
| 9-14 (`## Install`) | offers only `./install.sh` | Add one sentence at the top pointing at the root README's marketplace path as the short route, and framing `install.sh` as the full/development install. Do **not** duplicate the root README's surface list. |

**Why this is in scope:** §5.3a rewrites the root README to offer two
routes; leaving the plugin README asserting that `claude plugin install`
is never used would make the two documents contradict each other on the
unit's headline change.

**Two WHOLE-FILE assertions bind this README — clear them deliberately.**
Neither targets lines 9-18, but both scan the entire file, so an edit
elsewhere in it could trip them:

1. `test_o7_plugin_readme_cache_path_matches_sentinel_function` (**52-64**)
   — requires the `sentinel.sentinel_path()` rendering to be present and
   `"claude-skills/self-learn/autosync-pause"` to be absent.
2. `test_o9_no_manual_ln_sf_of_a_unit_install_sh_already_links` (**79-89**)
   — requires `"systemctl --user enable"` to be **present** and
   `"ln -sf"` to be **absent**.

The edits above introduce neither `ln -sf` nor the retired cache path, and
remove no `systemctl --user enable` line, so both stay green. Say it
rather than assume it: this is the §5.3c pattern — name the tripwire even
when the change clears it.

Beyond those two, **no test binds the specific content of lines 9-18**, so
the wording defect itself is caught only by being written down here (the
§5.5a pattern).

### 5.4 Corpus records of the reversal (3) — see §7 for the mechanism

| File | Edit |
|---|---|
| `docs/specs/self-learn/13-hosting-and-separation.md` | §7.2 — dated in-place amendment to **D2** (line **407-409**) |
| `docs/specs/self-learn/03-decisions.md` | §7.3 — new **S-19** row in the Settled table |
| `docs/specs/self-learn/README.md` | §7.4 — revision-log entry |

### 5.5 Shipped-source doc accuracy (1)

| File | Lines | Current | Required |
|---|---|---|---|
| `cli/src/self_learn/skill_scaffold.py` | 3-5 | ``plugins/<name>/.claude-plugin/plugin.json`` (the key set the repo's real manifests share: name / version / description) | Reword the parenthetical only — e.g. "(the three-key scaffold set pinned by 08 §8.1: name / version / description)". |
| `cli/src/self_learn/skill_scaffold.py` | 67-68 | `"""``plugin.json`` — exactly the key set the repo's real manifests share (08 §8.1): name, version, description."""` | Same: drop the "the repo's real manifests share" grounding, keep the 08 §8.1 citation. |
| `cli/src/self_learn/skill_scaffold.py` | 6-8 | "and the marketplace entry (**shaped like the repo's existing entries**, appended exactly once)" | Drop "shaped like the repo's existing entries" — reword to name the shape directly, e.g. "and the marketplace entry (a `name`/`source`-shaped entry, appended exactly once)". **See §5.5c — this claim becomes actively misleading, not merely stale.** |
| `cli/src/self_learn/skill_scaffold.py` | 101-105 | `The file is rewritten in the repo's own format (2-space JSON + trailing newline — **verified byte-stable against the live marketplace.json**)` | Drop "verified byte-stable against the live marketplace.json". Keep the format statement (2-space JSON + trailing newline) — §5.1a pins the new manifest to exactly that shape, so the *format* claim stays true; only the appeal to a verification against a file that did not exist in this repo goes. |

**§5.5a — why this is in scope despite carrying no licence literal.**
This is the same shape as the prior unit's §5.1c. D-2 removes `version`
from our own `plugin.json`, at which point the docstring's factual claim —
that name/version/description is "the key set the repo's real manifests
share" — becomes **false, and false because of this unit**. The §9 grep
gates key on `MIT`, `FSL`, and `private`; none of them can see this. It is
caught only by being written down here.

**The behavior does NOT change.** `SCAFFOLD_VERSION = "0.1.0"`
(skill_scaffold.py **35**) stays, and the generated manifest keeps all
three keys — that output is normatively pinned by **08 §8.1**'s New-skill
compiler row and asserted by `cli/tests/test_new_skill.py:104`. Only the
*justifying parenthetical* is stale. A builder who "fixes" this by
removing `version` from the scaffold breaks that test and violates a
ratified pin.

**§5.5c — lines 6-8 and 101-105 are the sharper half of this defect.**
Lines 3-5 merely go stale. Lines 6-8 and 101-105 become **actively
misleading the moment this repo has a marketplace**: they invite a reader
(or a future builder) to treat *this repo's* entry as the template the
scaffold reproduces — and §5.1a's entry deliberately carries **no
`version`** (D-2), while the scaffold always writes
`SCAFFOLD_VERSION` (skill_scaffold.py **126**). "Shaped like the repo's
existing entries" would then name a shape the function does not produce.
Before this unit there was no such entry and the sentence was merely
vague; after it, the sentence is false. Same detection gap as §5.5a: no
grep gate in §9.1 keys on it.

**08 §8.1 itself is NOT edited.** Its parenthetical carries the same now-
stale grounding, but 08 is an executed build plan describing a shipped
contract whose *normative* content (emit name/version/description) is
unchanged. Editing it would be cosmetic churn on a historical record under
R-5. Recorded here so a gate reviewer meets the decision instead of
raising it.

**§5.5b — the new marketplace manifest interacts with `new-skill`, and
the interaction is a LOOSENING. Read D1 before judging it.**

`verbs.py` **900-904** currently refuses a `route --dest new-skill` when
the registered skills-root has no `.claude-plugin/marketplace.json`:

```python
if not marketplace.is_file():
    raise VerbError(
        f"skills root {root} has no .claude-plugin/marketplace.json "
        "— the scaffold appends an entry to an EXISTING marketplace "
        "(08 §8.1); it never creates one"
    )
```

Creating the file at this repo's root therefore **removes a refusal**: if
someone registers `~/repos/self-learn` as a `--skills-root` host, the
new-skill scaffold would now write `plugins/<name>/` into the **product
repo**.

That is squarely against **doc 13 §7.3 D1** (user, stating the governing
principle): *"nothing should get committed to its repo other than work
that's specific to its development"* — compiled output of any kind lands
in the USER'S hosts, never in the product repo.

**The missing manifest was incidentally acting as a mechanical enforcer of
D1.** This unit removes the mechanism while leaving the policy. That is
accepted, on two grounds: (a) D1 is a policy about what the *operator*
registers, not a guard the code was ever designed to provide — nothing
else in the codebase enforces it either, and `host add` would equally
accept the product repo today for every other destination; (b) restoring a
mechanical guard would mean special-casing this repo's own path inside a
shipped product, which is the personal-literal class the prior unit just
removed.

**Required: D1 is restated in BOTH places, because the person at risk is
not the contributor.** `CONTRIBUTING.md` addresses people sending patches;
the operator who could actually register this repo as a `--skills-root`
host is the **owner or any installing user** — someone who may never open
`CONTRIBUTING.md`. So:

- **`CONTRIBUTING.md`** — one sentence, as part of the contributor
  guidance (§6.3).
- **`README.md` lines 10-14** — extend the existing product-boundary
  paragraph (which already says *"nothing is committed here except work
  specific to its own development… compiled output lands in your own
  registered host repos (doc 13 §7.3 D1)"*) with an explicit operational
  consequence: **do not register this repo with `self-learn host add …
  --skills-root`.** The paragraph already states the policy; this adds the
  one concrete action that would violate it. No new section — extend the
  paragraph in place.

**No code change** — the reasoning against special-casing this repo's own
path inside a shipped product stands (that is the personal-literal class
the prior unit removed). Recorded here so the gate meets the loosening as
a decision rather than an unnoticed regression.

### 5.6 New tests (1 file, 5 tests)

Append to `cli/tests/test_portability_docs.py` — the idiomatic home
(it already reads `REPO_ROOT / "README.md"` and the plugin manifest via
the `REPO_ROOT`/`PLUGIN_DIR` constants at lines **15-17**). This converts
the licence declaration from a one-time grep into a standing regression
guard, which is the point: §1.1's defect survived because nothing checked
it.

| # | Test | Asserts |
|---|---|---|
| **O-P1** | `test_license_file_exists_and_is_fsl_1_1_mit` | `REPO_ROOT / "LICENSE"` is a file; its text contains `"Functional Source License, Version 1.1, MIT Future License"`, `"FSL-1.1-MIT"`, `"Copyright 2026 Alex Kechichian"`, and the Competing Use limb `"offers the same or substantially similar functionality as the Software"`; and it contains **no** `"${"` (no unsubstituted template placeholder). |
| **O-P2** | `test_plugin_manifest_declares_fsl_and_no_pinned_version` | `plugin.json`'s `license == "FSL-1.1-MIT"` **and** `"version" not in data` (D-2 — a re-pinned version silently breaks updates). |
| **O-P3** | `test_both_pyprojects_use_pep639_license_string` | For each of `cli/pyproject.toml`, `ui/pyproject.toml`: the file contains the exact line `license = "FSL-1.1-MIT"` and does **not** contain `license = { text =` (D-1 — the table form is the unvalidated shape). |
| **O-P4** | `test_root_marketplace_manifest_is_schema_valid` | `REPO_ROOT / ".claude-plugin" / "marketplace.json"` parses as JSON; `name == "self-learn"`; `owner["name"]` is a non-empty string; `plugins` is a list of length ≥ 1; the entry with `name == "self-learn"` has `source == "./plugins/self-learn"` and **no** `"version"` key. |
| **O-P5** | `test_readme_offers_the_marketplace_install_path` | `README.md` contains `"/plugin marketplace add AlexK-Notable/self-learn"` and `"/plugin install self-learn@self-learn"`, and does **not** contain `"PRIVATE repo"`. |

**O-P5 is deliberately NARROW — it must not duplicate the §5.3c item-3
inversion.** The inverted `test_o11_readme_clone_block_is_public_https`
already owns the clone-URL pair (HTTPS present / SSH absent), so O-P5
covers only what that test does not: the **marketplace install path**, plus
the one private-repo phrase. Asserting the clone URLs in both places would
give two tests that fail together and verify one thing.

The `"PRIVATE repo"` negative is keyed on that exact capitalised phrase
rather than a loose `"private"` search: the word legitimately appears in
prose about the **ledger** (§7.1), so a broad negative would either fail
wrongly or force unnecessary rewording.

---

## 6. The CLA

### 6.1 Why a DCO is insufficient (do not let the gate re-propose one)

Stated once, plainly, so it is not re-litigated:

- A **DCO** is a certification: the signer attests they authored the
  contribution or have the right to submit it under the project's licence.
  It moves **no rights**. Signing a DCO a thousand times still leaves the
  copyright in each contribution with its author.
- **GitHub's inbound = outbound default** means a merged PR is licensed to
  the project under the outbound licence — here FSL-1.1-MIT — and nothing
  more. The owner receives a licence, not ownership.
- Therefore, after the first external merge under a DCO-only regime,
  **relicensing requires unanimous consent from every past contributor**.
  In practice that is a project-ending constraint; it is the reason many
  projects that later wanted to change licence could not.

R-2's requirement — a broad relicensing right — is only obtainable via an
actual grant taken at contribution time.

### 6.2 `CLA.md` — the substantive terms to specify

The builder writes the prose; these terms are the specification, and each
must appear.

1. **Scope.** Applies to every Contribution the contributor submits to the
   project, including code, documentation, specs, tests and fixtures.
2. **Copyright licence grant.** The contributor grants Alex Kechichian a
   **perpetual, worldwide, non-exclusive, irrevocable, royalty-free,
   fully-paid, transferable and sublicensable** licence to reproduce,
   prepare derivative works of, publicly display, publicly perform,
   distribute and otherwise exploit the Contribution.
3. **The relicensing right — the operative clause (R-2).** That licence
   **expressly includes the right to license, relicense and sublicense the
   Contribution, alone or as part of the project, under any terms the
   owner chooses, including proprietary or closed-source terms, and
   including terms different from the licence under which the Contribution
   was submitted.** This clause is why the document exists; it must be
   stated in these words or words of the same effect, not implied.
4. **Patent licence grant.** A perpetual, worldwide, non-exclusive,
   irrevocable, royalty-free, sublicensable patent licence covering the
   contributor's patent claims necessarily infringed by the Contribution
   alone or in combination with the project.
5. **Not an assignment — say so explicitly.** The contributor **retains**
   copyright in their Contribution and may use it elsewhere however they
   like. This is an additional grant, not a transfer. Saying so plainly is
   what makes the agreement acceptable to sign.
6. **Contributor warranties.** The contributor warrants that they are
   legally entitled to grant the above; that the Contribution is their
   original work or that they have the necessary rights; and that if their
   employer has rights in the work, they have permission or the employer
   has waived them.
7. **Third-party material.** Anything not original must be identified,
   with its source and licence, when submitted.
8. **No obligation.** The owner is under no obligation to accept, merge or
   use any Contribution.
9. **Disclaimer.** The Contribution is provided as-is, without warranty,
   except as expressly stated in clause 6.
10. **An honest note.** One line stating the document is a plain-language
    agreement drafted for a small personal project and is not legal
    advice.

**Durability of the assent — the grant needs an artifact that outlives the
PR.** A pull-request description is **editable after merge** and lives in
GitHub's database, not in the git object graph: a contributor can silently
revise or delete the text that recorded their agreement, and a repo
mirrored or migrated off GitHub carries none of it. That is a weak
evidentiary basis for the one clause (§6.2 clause 3) the whole document
exists to obtain.

**Therefore require BOTH, and say why in `CONTRIBUTING.md`:**

1. the PR-description line (§6.3) — the human-visible checkpoint the
   maintainer reads at review time; and
2. a **`Signed-off-by: Name <email>` trailer on every commit** in the PR
   (`git commit -s`), which is **immutable once merged** — it is part of
   the commit message, covered by the commit hash, and travels with the
   history into any clone or mirror.

The trailer is the durable artifact; the PR line is the deliberate,
legible act of assent. `CLA.md` states that the trailer signifies
agreement to this document. Note the trailer's *form* is borrowed from the
DCO convention — its **meaning here is defined by `CLA.md`, not by the
DCO**, and `CONTRIBUTING.md` must say so in one sentence, or a contributor
familiar with the DCO will assume the weaker certification (§6.1).

### 6.3 `CONTRIBUTING.md` and the enforcement mechanism (D-4)

**Proportionality is a requirement here, not a nicety.** This is a solo
personal project with, at time of writing, zero external contributors. The
mechanism must be the lightest one that actually obtains the grant.

**Pinned mechanism: a sign-off line in the pull request body, checked by
the maintainer by hand before merge.** `CONTRIBUTING.md` must state:

- the licence (FSL-1.1-MIT), with the same source-available framing as the
  README, and a pointer to `LICENSE`;
- that **agreeing to `CLA.md` is a precondition of merge**, with a link;
- the **exact line** a contributor includes in the PR description — a
  pinned literal, so the maintainer's check is a string match, not a
  judgment call — e.g. `I have read and agree to the CLA in CLA.md.`;
- the **commit trailer** requirement: every commit in the PR carries
  `Signed-off-by: Name <email>` (`git commit -s`), and **one sentence
  saying the trailer here means agreement to `CLA.md`, not the DCO**
  (§6.2's durability note — the form is borrowed, the meaning is not);
- that the maintainer will not merge without **both**;
- the **D1 restatement** from §5.5b: do not register this repo as a
  self-learn canon host (`host add … --skills-root`); compiled lesson
  output belongs in your own repos, never in the product repo;
- the practical bits a contributor needs: how to run the three
  verification commands in §9's baseline table, and that
  `docs/specs/self-learn/` is the authority the code follows.

**Considered and rejected for now:** a CLA-assistant bot (CLA Assistant,
cla-bot) with a signature ledger. It is the correct answer at volume and
the wrong answer at zero contributors — it adds a third-party GitHub App
with write access to the repo in order to automate a check that currently
runs zero times per month. **Escalation trigger, stated so the decision is
reopenable rather than forgotten: adopt a bot at the first merged external
PR, or when open PRs from distinct external authors exceed roughly one a
month.**

**Not in scope:** a Contributor Covenant / code of conduct. The user did
not ask for one and it is orthogonal to publishability.

---

## 7. Recording the P-C1.4 reversal (R-3, R-5)

### 7.1 What is actually being reversed, and what is NOT

**The scouting brief located the ruling one level too shallow.** P-C1.4
lives at `docs/specs/self-learn/drafts/c1-portability-defects-spec.md`
**224-233** — but it is a *derived* pin that cites its own authority:

> `13-hosting-and-separation.md:407-409` ratifies
> `github.com/AlexK-Notable/self-learn` as **private**, so the
> substitution does point at a repo a stranger cannot reach.

The **ratifying decision** is doc 13 §7.3 **D2** (lines **407-409**):

> - **D2 — product repo identity.** **RATIFIED 2026-07-17:**
>   `github.com/AlexK-Notable/self-learn`, private, same posture as
>   `self-learn-ledger`.

So D2 is what changes; P-C1.4 is downstream of it and needs no separate
act. This matters because D2's wording couples two repositories.

**D2 says "same posture as `self-learn-ledger`". The amendment MUST
decouple them explicitly.** The ledger is `~/.self-learn` — the user's
actual captured lessons, their private remote. Nothing in this unit opens
it, and an amendment reading only "now public" could be read as unpinning
both. **The product repo becomes public; the ledger stays private.**

Every `private` occurrence, classified. Verified at `ac28695`:

**This table is the unit's safety artifact for its most consequential
question, so it is exhaustive over every occurrence asserting a
*repository's* privacy posture, plus the SSH-clone literal.** It is NOT
exhaustive over the raw `git grep -n '\bprivate\b'` sweep, which returns
**40** hits against this table's 16: the other 24 are unrelated senses —
`private-key` scan regexes, private methods/constants/frontmatter, "M2's
private prompt", "UI internals stay private", the `private_source.py`
fixture name, and the decline-reason enum's other spellings
(`commands/teach.md:78`, `skills/self-learn/SKILL.md:35`). Two classes of
entry: *product* (changes, or is consciously left as dated history) and
*ledger* (never touched).

| Site | Refers to | Action |
|---|---|---|
| `README.md:38` ("PRIVATE repo") | product | **Rewritten** (§5.3a) |
| `README.md:39` (P-C1.4 citation) | product | **Rewritten** (§5.3a) |
| `README.md:40` (`git@github.com:` SSH clone) | product | **Rewritten** to HTTPS (§5.3a) |
| `cli/tests/test_portability_docs.py:102` (test name `…discloses_private_repo`) | product | **Inverted** (§5.3c item 3) |
| `cli/tests/test_portability_docs.py:104` (the SSH-clone marker literal) | product | **Inverted** (§5.3c item 3) — this is the third `git@github.com:` hit in the repo and the reason G-3 currently returns **3**, not 2 |
| `13-hosting-and-separation.md:408` (D2) | product | **Amended in place** (§7.2) |
| `docs/specs/self-learn/README.md:692` | product | Dated history — **not** edited; covered by the §7.4 revision-log entry |
| `docs/specs/self-learn/README.md:704` | **product** (see note) | Dated history — **not** edited |
| `drafts/c1-portability-defects-spec.md:121, 227, 230, 323, 589` | product | Completed unit's draft record — **not** edited (§7.5) |
| `drafts/c1-portability-defects-spec.md:488` | **ledger** (quotes 13:203's home-bootstrap line) | **Do not touch** |
| `13-hosting-and-separation.md:57` | **ledger** | **Do not touch** |
| `13-hosting-and-separation.md:203` | **ledger** | **Do not touch** |
| `13-hosting-and-separation.md:269` | **ledger** | **Do not touch** |
| `docs/specs/self-learn/README.md:607` | **ledger** remote | **Do not touch** |
| `09-surface-spec.md:1008` ("publish the un-scanned record body to the private remote") | **ledger** remote | **Do not touch** — nothing in this unit edits doc 09 |
| `cli/src/self_learn/gitops.py:149` | **ledger** remote | **Do not touch** |
| `cli/src/self_learn/telemetry.py:86` | a decline-reason enum value (`"private"`) | **Do not touch** |

**Correction — `docs/specs/self-learn/README.md:704` is PRODUCT, not
ledger.** An earlier revision of this table classified it as a ledger
remote. It is not: line 704 sits inside the 2026-07-17 STEP 2 EXECUTED
entry describing the **product** repo's bring-up ("product bring-up (own
install.sh: five surfaces + miner units, private remote, suite 875
passed…)"). The misclassification was **safe in effect** — a product line
wrongly labelled ledger inherits "do not touch", which is also its correct
action as dated history — but a safety table that is right by accident is
not right. Corrected above.

### 7.2 Doc 13 — dated in-place amendment to D2 (the corpus's own convention)

Doc 13 already carries this convention: line **96** reads
`*(Amended 2026-07-18 — feedback round 3 item 2; normative text at …)*`.

**Required:** append to D2, leaving the existing `RATIFIED 2026-07-17:
… private …` sentence **intact and visible**, an amendment of this shape:

> *Amended 2026-07-24 (user ruling — publication):* the product repo is
> **PUBLIC**, licensed FSL-1.1-MIT (see the root `LICENSE`; 03 S-19).
> This reverses the `private` half of the ratification above and, with
> it, the derived pin P-C1.4 in
> `drafts/c1-portability-defects-spec.md` §1.3 — the `plugin.json`
> `homepage`/`repository` links that P-C1.4 accepted as knowingly
> unreachable are now publicly correct, exactly as that pin anticipated.
> **The "same posture as `self-learn-ledger`" clause no longer holds and
> is severed: the LEDGER remains private.** D1 (product-boundary) and D3
> (no autosync) are unaffected.

This is *not* falsifying the record: the original ratification stays on
the page, dated, with the reversal dated beneath it. That is exactly the
mechanism doc 13 already uses.

### 7.3 `03-decisions.md` — a new **S-19** row

03 is the decision register, and it holds its own rule at the file's end:

> When any settled decision's stated inputs change — a platform feature
> ships, a gate fires, a review lands — the decision reopens *in this
> file* with a dated note. Nothing in this corpus is shielded by its
> status.

Publication + licence + CLA is a **new** decision, not merely an
amendment to an existing row, so it takes a new number. **Verified: the
highest existing settled number is S-18** (`grep -oE '^\| S-[0-9]+'` →
S-1…S-18), so the next is **S-19**. The Open table runs to O-9 and is
untouched.

Required row, in the `## Settled` table, matching that table's
**three-column** `| # | Decision | Rationale (inputs) |` shape and its
**bold-lede** house style. (Rendered below as a blockquote purely so this
spec's own markdown does not swallow it into a table; the builder writes
it as a real table row.)

> | S-19 | **The product repo is PUBLIC and source-available under
> FSL-1.1-MIT; contributions require a CLA granting a broad relicensing
> right.** Licence text at the root `LICENSE`; `plugin.json` + both
> `pyproject.toml` declare the SPDX id; installable via the root
> `.claude-plugin/marketplace.json`. | Reverses D2's `private` half (doc
> 13 §7.3, amended 2026-07-24) and the derived pin P-C1.4; the LEDGER
> stays private. FSL was chosen over MIT/Apache to bar Competing Use
> while permitting internal and commercial use, with each version
> converting to MIT on its second anniversary — so openness is deferred,
> not withheld. The CLA (not a DCO) exists because GitHub's inbound =
> outbound default leaves each contributor holding copyright, which
> would permanently foreclose the close-source / dual-licence option the
> user wishes to keep. Reopens if the user decides to relicense, or if
> contributor volume makes manual CLA checking impractical (a bot is the
> pre-agreed answer — spec §6.3). |

### 7.4 `docs/specs/self-learn/README.md` — revision-log entry

The root README states the convention: *"substantive changes land with a
README revision-log entry there."* The log's existing entries are
`- **YYYY-MM-DD — <headline> SHIPPED: …**` bullets appended at the end,
newest last.

Required: one dated bullet recording the publication unit — repo public,
FSL-1.1-MIT, CLA, root marketplace manifest, D2 amended, S-19 minted,
ledger still private. Plus the §3.5 sentence noting the corpus ships under
the repo LICENSE as a historical record.

### 7.5 What is NOT edited

- **`drafts/c1-portability-defects-spec.md` is NOT touched.** It is a
  completed unit's draft record. P-C1.4 explicitly anticipated this day —
  *"Naming the right repo is correct today and becomes publicly correct
  the day the repo opens"* — so the reversal *vindicates* the pin rather
  than contradicting it, and there is nothing to correct in place.
- **`docs/specs/self-learn/README.md:692`'s historical line** ("…
  AlexK-Notable/self-learn, private. D3: NO autosync …") stays. It
  accurately records what was true on 2026-07-17.
- **08 §8.1** — §5.5a.

---

## 8. Explicitly out of scope

Stated so the gate does not demand them.

- **Flipping the GitHub repository visibility.** That is an operator
  action in the GitHub UI/API, not a file change. This unit makes the repo
  *publishable*; a human publishes it. §9 criterion 11 routes it.
- **Git history** (R-6). No rewrite, no squash, no force-push. The history
  was audited clean by the prior unit.
- **The ledger's private status** (§7.1) and every ledger-referring
  `private` occurrence.
- **Author identity** (R-4): `plugin.json` author block, both
  `pyproject.toml` `authors`, and `test_portability_docs.py` **73-74**.
  Never a target.
- **`version = "0.1.0"` in either `pyproject.toml`, and
  `__version__ = "0.1.0"` at `cli/src/self_learn/__init__.py:3`.** These
  are the *Python distribution* version, a different identifier from the
  plugin-manifest version D-2 removes. Do not conflate them; do not sweep
  `0.1.0`.
- **`SCAFFOLD_VERSION` and the scaffold's three-key output**
  (skill_scaffold.py **35**, **71**, **126**) — normatively pinned by
  08 §8.1 and asserted by `test_new_skill.py:104`. Only the docstring's
  justifying parenthetical moves (§5.5).
- **Any code change to `verbs.py`'s new-skill guard** (§5.5b). The
  loosening is accepted and answered with policy in `CONTRIBUTING.md`.
- **Packaging (`forward/packaging.md`, FW-10…FW-15).** The marketplace
  path *partially* answers FW-10's distribution-shape question for the
  plugin half, but FW-10 is a user decision covering `uv tool install`
  versus a single-file binary for the **CLI**, and this unit neither
  forecloses nor makes it. **Do not fold FW-10 in.** Note the overlap in
  the §7.4 revision-log entry; leave the decision open.
- **A `CHANGELOG.md` and a release cadence.** D-2's commit-SHA choice is
  correct *because* these do not exist; creating them is the packaging
  phase's work, and doing it here would invert the ordering.
- **A code of conduct** (§6.3).
- **GitHub's own licence detection.** Whether github.com's `licensee`-based
  detector recognizes FSL-1.1-MIT and renders a licence badge was **not
  verified** and is **not** an acceptance criterion. The `LICENSE` file's
  legal effect does not depend on it.
- **The pre-existing UI test failure**
  `ui/tests/test_service_unit.py::test_both_units_document_manual_registration_via_symlink`.
  Unrelated; it must remain the **only** UI failure.
- **`docs/LICENSE` or any second licence** (D-5).

---

## 9. Definition of Done / acceptance criteria

**Step 0 — re-establish all three baselines before the first edit.**
Confirmed live at `ac28695` while writing this spec; confirm again so any
later delta is attributable to this work.

| Suite | Command (run from) | Baseline at `ac28695` |
|---|---|---|
| CLI tests | `plugins/self-learn/cli/` → `.venv/bin/python -m pytest -q` | **1112 passed, 5 skipped** |
| CLI types | `plugins/self-learn/cli/` → `pyright --pythonpath .venv/bin/python src` | **50 errors, 0 warnings, 0 informations** |
| UI tests | `plugins/self-learn/ui/` → `uv run pytest -q` | **1002 passed, 1 failed** |

Bare `pyright src` produces wrong-interpreter noise — **do not use it.**

A reviewer can check each of the following against the tree:

1. **`LICENSE` exists at the repo root** and is the §4 text byte-for-byte
   with exactly two substitutions (`2026`, `Alex Kechichian`). No `${`
   remains. `git ls-files | grep -i licen` now returns `LICENSE`.
2. **All three MIT declarations are gone.** `plugin.json:15` reads
   `"license": "FSL-1.1-MIT"`; both `pyproject.toml` line 6 read
   `license = "FSL-1.1-MIT"` — **the PEP 639 string form**, not
   `{ text = … }` (D-1).
3. **`plugin.json` carries no `version` key** (D-2), and the marketplace
   entry carries none either. **`repository` is now a STRING** (§5.2a);
   `homepage` and the author block are unchanged (R-4).
   `test_o8_plugin_json_names_self_learn_repo` is therefore **modified at
   line 71 only** — it does **not** stay green unmodified, and a builder
   who leaves it alone gets a `TypeError`.
4. **`.claude-plugin/marketplace.json` exists at the repo root** with
   §5.1a's content, and **`claude plugin validate .` PASSES (warnings
   permitted)** — run from the repo root, where it currently fails with
   *"No manifest found in directory."* The expected end state is exactly:

   ```
   ⚠ plugins[0] plugin.json → version: No version specified. Consider adding a version following semver (e.g., "1.0.0")
   ✔ Validation passed with warnings
   ```

   **That warning is REQUIRED, not tolerated** — it is D-2 working as
   designed. A run with **zero** warnings means someone re-added
   `version` and silently reverted D-2; treat it as a FAILURE of this
   criterion, not a cleaner result. Any **error**, or the string
   `repository: Invalid input`, means §5.2a's row was skipped.
5. **`CONTRIBUTING.md` and `CLA.md` exist**; `CLA.md` contains all ten
   §6.2 terms, with clause 3 (the relicensing right) and clause 5 (not an
   assignment) both explicit; `CONTRIBUTING.md` names the pinned sign-off
   line, states the CLA as a merge precondition, and restates D1 (§5.5b).
6. **`README.md`'s install section** offers the marketplace path first and
   an HTTPS clone for `install.sh`, enumerates the §5.3a surface list in
   full, contains the "pick one" sentence with **no claim about a specific
   failure mode**, and preserves the ledger paragraph verbatim. The
   private-repo comment and the `git@github.com:` SSH clone are gone.
7. **`README.md` has a `## License` section** in which **every sentence
   maps to a §4.1 row**. The reviewer walks the table. Specifically:
   nowhere does it say "open source"; nowhere does it say the licence is
   "non-commercial"; nowhere does it cite "OSI clause 6" (§4.2).
8. **The reversal is recorded per §7:** D2 amended in place with the
   original ratification still visible and the ledger explicitly severed;
   S-19 minted in `03-decisions.md`; a revision-log entry in the corpus
   README; and **`drafts/c1-portability-defects-spec.md` is byte-unchanged**
   (`git diff --stat` must not list it).
9. **All three baselines re-established, reconciled not merely
   "unbroken":** CLI **1117 passed, 5 skipped**. **The arithmetic is
   1112 + 5 = 1117, and the `+5` is additions ONLY** — §5.3c item 3
   *inverts* an existing test and §5.2 *edits* one assertion in another,
   so both stay in the count and neither is deleted. (If a builder deletes
   the clone-block test instead of inverting it, the correct total is
   **1116** and this criterion fails as written — inverting is the pinned
   choice, so **1117** is the number.) pyright **exactly 50 errors** (this
   unit touches only docstrings in `src/`, never a code path, so any
   change is a regression); UI **1002 passed, 1 failed** with
   `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
   still the **only** failure. The UI run also proves D-1 did not break the
   editable install (§3.1 residual risk).
10. **Mutation verification §10 executed and recorded.**
11. **Reported to the user at merge** — two items, neither of which a gate
    can settle:
    - **the GitHub visibility flip is a human action** and has not
      happened (§8);
    - **plugin-install and `install.sh` co-existence on one machine is
      untested** (§5.3a) — the README says "pick one" and claims nothing
      further.

    *(The marketplace name was a third item in an earlier revision. It is
    now RATIFIED as `self-learn` (D-3) and is no longer an open question —
    do not re-raise it.)*

### 9.1 The grep gates — RUN FROM THE REPO ROOT

⚠️ **Every `git grep` pathspec below is cwd-relative.** Run from a
subdirectory (e.g. `plugins/self-learn/cli/`) and `-- plugins/` matches
nothing, returning zero **vacuously** — a silent false pass. This fired
twice during the previous unit. **Print `pwd` alongside each run** and
pair the sweeps with the positive control in G-4.

**G-1 — no MIT declaration survives in the product.**

```
git grep -n '"license": "MIT"\|license = { text = "MIT" }' -- plugins/
```

returns **ZERO** hits.

**G-2 — the licence identifier is declared in exactly the three product
manifests.**

```
git grep -n 'FSL-1.1-MIT' -- plugins/ ':(exclude)plugins/**/tests/**'
```

returns **exactly three** hits: `plugin.json:15`, `cli/pyproject.toml:6`,
`ui/pyproject.toml:6`.

⚠ **The `:(exclude)` is mandatory.** §5.6's O-P1/O-P2/O-P3 each carry
`FSL-1.1-MIT` as an assertion needle and live at
`plugins/self-learn/cli/tests/test_portability_docs.py`, **inside** the
`-- plugins/` pathspec. Without the exclusion this gate returns **six or
more** hits and fails for entirely the wrong reason — the tests doing
their job. (G-1 needs no such exclusion: its needles are the old
`"license": "MIT"` / `license = { text = "MIT" }` spellings, which no test
reproduces.)

⚠️ **Scope this to `-- plugins/`, never repo-wide.** A repo-wide
`git grep -i 'MIT'` **fails for the wrong reason**: the new root `LICENSE`
legitimately contains "MIT Future License", "the MIT license" and an
entire MIT paragraph (§4), the new `marketplace.json` carries
`"license": "FSL-1.1-MIT"`, and
`docs/specs/self-learn/research/2026-07-12-sota-survey.md:85` has carried
an unrelated "(MIT, ~12.3k stars…)" since long before this unit. A gate
that reports those as findings has mis-scoped its pathspec, not found a
defect.

**G-3 — no surface still claims the product repo is private.**

```
git grep -n 'PRIVATE repo\|git@github.com:AlexK-Notable/self-learn' -- ':(exclude)plugins/**/tests/**' ':(exclude)docs/specs/**'
```

returns **ZERO** hits. Run from the REPO ROOT (the pathspec is
cwd-relative and returns zero vacuously from a subdirectory). Repo-wide
scoping is otherwise correct here — both patterns are specific to the
product-repo claim and neither appears in the ledger prose that §7.1
protects.

⚠ **CORRECTED after the build surfaced a contradiction. An earlier
revision of this gate demanded ZERO hits repo-wide and explicitly
forbade excluding the tests path ("that literal is real and must
genuinely go"). That is unachievable, and the reason is structural: a
Python `assert "<literal>" not in text` must CONTAIN the literal it
forbids.** §5.3c item 3's pinned inversion body contains
`assert "git@github.com:AlexK-Notable/self-learn.git" not in text`, and
§5.6's O-P5 contains `assert "PRIVATE repo" not in text`. Both are
byte-pinned by this spec. So the repo-wide gate goes 3 → **2**, never to
zero, and the two survivors are the assertions that *enforce* the
literals' absence everywhere else.

This is the same false positive G-2 already excludes, for the same
reason — tests legitimately reproducing a needle in order to do their
job — so it takes the same exclusion. The substantive requirement is
unchanged and still provable: the literals must be gone from every
NON-test surface, which the exclusion measures exactly. Verify the two
survivors are `not in` assertions (absence-enforcing), NOT `in`
assertions or live usage; an `in` assertion or a `text.index()` call
among them means the inversion was done wrong.

`docs/specs/**` is excluded for the same reason, one step removed. THIS
spec quotes both literals repeatedly in order to forbid them (11 hits at
last count), and it is itself one of the unit's 15 files — so the moment
it is committed, an un-excluded G-3 reports 11 hits and reads as a
regression. R-5 already makes the corpus a historical record, and §7.1
grants exactly this "dated history — not edited" treatment to
`c1-portability-defects-spec.md`'s own `private` mentions. Note the
gate returns zero BEFORE the commit only because this file is still
untracked; that is a false green, not a pass — run it after committing.

**G-4 — positive control (proves the pathspec can still find matches).**

```
git grep -c 'self-learn' -- plugins/
```

returns a **non-zero** count for multiple files. Without this, G-1's zero
is indistinguishable from a mis-scoped run.

---

## 10. Verification plan

Most of this unit is content, so most verification is the §4.1 clause walk
and the §9 grep gates. Three places admit a genuine mutation check —
apply each, observe the named failure, revert.

**Because this unit adds no behavior, a green suite proves less than
usual. The §4.1 clause walk is the primary verification and must be
performed sentence-by-sentence, not skimmed.**

### V-1 — the marketplace manifest is schema-valid, and the validator actually enforces the schema

- **Positive, already observed at `ac28695`:** `claude plugin validate .`
  from the repo root fails with *"No manifest found in directory. Expected
  .claude-plugin/marketplace.json or .claude-plugin/plugin.json"*. After
  the change it must **pass**. This is a real before/after, not an
  assertion.
- **Negative control — required, because a validator that accepts anything
  proves nothing.** Delete the `owner` key from the new manifest; re-run
  `claude plugin validate .`; it **MUST fail**. Revert. Repeat with
  `plugins[0].source` removed; it **MUST fail** (observed:
  `plugins.0.source: Invalid input`). Revert.
- **Both controls were pre-verified in a scratch replica** (Claude Code
  v2.1.219) and both produced `✘ Validation failed`. The builder
  re-runs them against the real tree.
- **Read the result from `claude plugin validate` DIRECTLY — never through
  a pipe.** `claude plugin validate . | tail -4; echo rc=$?` reports
  `tail`'s status, not the validator's, and prints a misleading `rc=0` on
  a failed run. This was tripped once while writing this spec. Either
  check the literal `✔`/`✘` line, or capture rc before piping.
- **Record both negative-control outputs in the gate log.** If either
  mutation still *passes*, the tool is not checking the required fields
  and criterion 4 must be downgraded to "JSON parses" rather than claiming
  schema validation.

### V-2 — O-P2 binds the version removal, not merely the licence

The risk is a builder who changes `license` and forgets D-2, leaving the
suite green because the test only checked the licence.

- **Mutation:** re-add `"version": "0.1.0"` to `plugin.json`.
- **MUST FAIL:** `test_plugin_manifest_declares_fsl_and_no_pinned_version`
  (O-P2), **with the failure observed on the `"version" not in data`
  assertion** — not on the licence assertion, which still passes. Record
  which assertion failed; that is what proves the test binds both halves.

### V-3 — O-P3 binds the *form*, not just the value

`license = { text = "FSL-1.1-MIT" }` carries the right value in the wrong,
unvalidated shape (D-1). A test that only searched for `FSL-1.1-MIT` would
pass on it.

- **Mutation:** change `cli/pyproject.toml:6` to
  `license = { text = "FSL-1.1-MIT" }`.
- **MUST FAIL:** `test_both_pyprojects_use_pep639_license_string` (O-P3).

⚠ **CORRECTED — this mutation short-circuits and does NOT prove what the
bullet below originally claimed.** Executed, it fails at the *positive*
leg (`license = "FSL-1.1-MIT"` is absent once the form changes), never
reaching the negative `assert "license = { text =" not in text`. So it
cannot confirm the negative half is load-bearing. Use **V-3b** to isolate
that leg: keep the string form AND add `license = { text = ` as a comment
line. Verified to fail on the negative assertion specifically. Run BOTH —
V-3 proves the positive leg binds, V-3b the negative. (This is the
project's signature defect — an assertion passing for the wrong reason —
found in the verification plan rather than the code.)

### V-4 — the D-1 build evidence is reproducible (re-run, do not trust the transcript)

§3.1's table is the entire ground for D-1. Reproduce it **outside the
repo** (session scratchpad; never inside the working tree), with the same
unpinned `[build-system] requires = ["hatchling"]`:

- `license = "FSL-1.1-MIT"` → `uv build` **succeeds**; wheel METADATA
  shows `License-Expression: FSL-1.1-MIT`.
- `license = "not-a-real-license-xyz"` → `uv build` **FAILS** with
  `Unknown license`.
- `license = { text = "NOT-A-REAL-LICENSE-XYZ" }` → **succeeds**; METADATA
  shows `License: NOT-A-REAL-LICENSE-XYZ`.

The middle row is the one that matters: it is simultaneously the proof
that the string form is validated **and** the proof that `FSL-1.1-MIT` is
a recognized SPDX identifier. If it does not fail, D-1's reasoning
collapses and the gate must say so rather than accept the outcome.

### V-5 — O-P1's `${` assertion is not vacuous

- **Mutation:** revert one substitution in `LICENSE` — restore
  `Copyright ${year} ${licensor name}`.
- **MUST FAIL:** `test_license_file_exists_and_is_fsl_1_1_mit` (O-P1).
- **Why this specific mutation:** an unsubstituted template is the single
  most likely LICENSE defect, it is invisible to every grep gate in §9.1,
  and a LICENSE naming `${licensor name}` as the copyright holder grants
  nothing to anyone.

⚠ **CORRECTED — same short-circuit as V-3.** Executed, it fails on the
copyright-line assertion, never reaching the `assert "${" not in text`
leg it exists to validate. Use **V-5b** to isolate that leg: leave the
copyright line correctly substituted and append a stray `${licensor
name}` elsewhere in the file. Verified to fail on the `${` assertion
specifically. Run both.

### V-6 — README tripwires: two unmodified, one inverted

**This is NOT an additions-only diff.** `git diff
cli/tests/test_portability_docs.py` must show exactly **two modified
assertions plus five appended tests**, and nothing else:

| Test | Expected diff | Why |
|---|---|---|
| `test_o6_readme_install_blocks_have_no_repos_claude_skills` | **unmodified**, green | §5.3c item 2 |
| `test_o11_readme_states_git_repo_prerequisite_and_names_init` | **unmodified**, green | §5.3c item 1 — proves the ledger paragraph survived the §5.3a move |
| `test_o8_plugin_json_names_self_learn_repo` | **line 71 only** | §5.2a `repository` string |
| `test_o11_readme_clone_block_discloses_private_repo` | **renamed + body inverted** | §5.3c item 3 |
| O-P1…O-P5 | **appended** | §5.6 |

**Mutation for the inverted test** (it must bind, not merely pass):

- **Mutation:** restore the SSH clone line
  `git clone git@github.com:AlexK-Notable/self-learn.git` to `README.md`
  alongside the HTTPS one.
- **MUST FAIL:** `test_o11_readme_clone_block_is_public_https`, on the
  `not in` leg — **not** on the `in` leg, which still passes because the
  HTTPS URL is also present. Record which leg failed; that is what proves
  the negative assertion carries the inversion's weight rather than riding
  on the positive one.
- Revert.

### V-7 — the clause walk (no mutation applies; do it by hand)

For each sentence in the README `## License` section and the licence
paragraph of `CONTRIBUTING.md`, the reviewer names the §4.1 row that
substantiates it. **A sentence with no row is a finding**, whether or not
it reads plausibly. Two specific checks, because both errors are common
and both are in the task's own do-not-get-this-wrong list:

- **grep the new prose for `open source` / `open-source`** — any hit
  describing *this* licence is a defect;
- **grep for `non-commercial`** — permitted only inside a faithful
  restatement of Permitted Purpose limbs (2) and (3); as a description of
  the licence as a whole it is a defect.
