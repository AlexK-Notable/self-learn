# Registering skills for upkeep

Register a user-maintained skill when continued correction, extension or reorganisation
would help. `self-learn skill register <name-or-path> --note "why"` records permission,
who registered it and why. Names resolve through the registered skills root, then the
Claude runtime skills directory. Paths follow symlinks. `skill list` shows the result.

A readable SKILL.md needs valid frontmatter with a name matching its folder and a
description. Registration refuses AWS metadata, the agents shared store or skill lock,
Claude plugin and synced directories, node_modules, Codex system skills, the upstream
`LOCAL ADDITIONS BELOW` marker, `metadata.upstream`, and any other git repository.
It also refuses vetoed names, owned skills (already maintained), linked descendants,
and noncanonical layouts inside the skills root. The error names the signal; don't
remove installer marks to get around it.

A canonical skill in the registered root stays where it is. A loose real directory
with no installer or repository is backed up in the ledger's cache, moved into the
root's plugin layout, committed there, and linked at both its original location and
the runtime skill path. Adoption requires git mode and a clean destination. A backup
is retained. Unregistering withdraws permission and records why; it preserves the
files, links, backup and history.

Registered does not mean authored by self-learn. Full updates may change prose,
description and reference files, preserving the user's intent and voice. The writer
retains the user's name and records registered provenance. A content hash taken on
registration protects the first write; each later write records its new hash. Edits
made after reading require a fresh read and `--expect`; dirty files refuse writes.
Rename, retire, restore and veto-driven renames remain limited to owned skills.

Any agent may file a build or change request with a required explanatory `--note`:

```sh
self-learn skill request build --name <proposed> --lessons <id1>,<id2> --note "why"
self-learn skill request change <skill> --note "what should change and why"
```

Build lessons must already exist. A change target must be owned or registered;
register it first otherwise. The next overseer run sees every open request, decides
it, and lists its answer and reason in the report. A built/changed answer closes only
when the corresponding writer step actually applies. Drafts or refused writes stay
open for the next run. Placed lessons with no covering case can move through the
maintenance-case route; covered lessons need reconsideration of their covering case.
