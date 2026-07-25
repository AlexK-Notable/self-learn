# Contributing to self-learn

Thanks for looking at this project. It's a personal tool with, at time of
writing, zero external contributors — the process below is deliberately
light, but the two things it asks for are non-negotiable.

## License

self-learn is licensed under the **Functional Source License, Version
1.1, MIT Future License** (SPDX `FSL-1.1-MIT`) — full text at
[`LICENSE`](./LICENSE). It is **source-available, not open source**: the
license's grant is conditioned on using the Software for a Permitted
Purpose rather than a Competing Use. In practice that means internal and
commercial use are fine — only offering the Software, or something
substantially similar, to others as a commercial product or service is
barred. Each version converts to the plain MIT license, irrevocably, on
the second anniversary of its release.

## The CLA is a precondition of merge

**Agreeing to [`CLA.md`](./CLA.md) is required before any Contribution
can be merged.** Read it — the operative clause grants the project owner
the right to relicense your Contribution, including under proprietary
terms, while you keep your own copyright. This exists so the project can
change license later (or not) without needing to track down and get
sign-off from every past contributor.

To signify agreement, a pull request needs **both** of the following. The
maintainer will not merge without both:

1. **The exact line, in the pull request description:**

   ```
   I have read and agree to the CLA in CLA.md.
   ```

   This is the human-visible checkpoint the maintainer checks at review
   time — a string match, not a judgment call.

2. **A `Signed-off-by: Name <email>` trailer on every commit in the PR**
   (`git commit -s` adds this automatically). Unlike the PR description,
   which GitHub lets you edit or delete after merge, the trailer is part
   of the commit message — immutable once merged, and it travels with the
   history into any clone or mirror. That durability is why it's required
   in addition to, not instead of, the PR-description line.

   **Note:** this trailer's form is borrowed from the DCO (Developer
   Certificate of Origin) convention, but its meaning here is defined by
   `CLA.md`, not by the DCO — signing it means you agree to the broader
   relicensing grant in `CLA.md`, which is a stronger commitment than a
   DCO's certification of origin.

## Do not register this repo as a self-learn canon host

This repo is the **product** — the CLI, the plugin, and this spec corpus.
Compiled lesson output (skills, CLAUDE.md sections, references, hooks)
belongs in *your own* registered host repos, never in the product repo
(doc 13 §7.3 D1). Concretely: **do not run `self-learn host add
<this-repo-path> --skills-root`** against a checkout of this repository.

## Before you open a PR

- `docs/specs/self-learn/` is the authority the code follows. If your
  change touches behavior the corpus specifies, the corpus is where the
  reasoning should be checked against.
- Run the verification suites and make sure they're clean (or that any
  failure predates your change):

  ```bash
  # CLI tests — from plugins/self-learn/cli/
  .venv/bin/python -m pytest -q

  # CLI types — from plugins/self-learn/cli/
  pyright --pythonpath .venv/bin/python src

  # UI tests — from plugins/self-learn/ui/
  uv run pytest -q
  ```
