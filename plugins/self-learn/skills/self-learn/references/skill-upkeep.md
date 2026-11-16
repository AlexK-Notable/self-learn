# Registering skills for upkeep

Register a user-maintained skill when continued correction, extension or reorganisation
would help. `self-learn skill register <name-or-path> --note "why"` records permission,
who registered it and why. Names resolve through the registered skills root, then the
Claude runtime skills directory. Paths follow symlinks. `skill list` shows the result.

A readable SKILL.md needs valid frontmatter with a name matching its folder. Missing or invalid descriptions can be corrected by the first
rewrite. Registration refuses AWS metadata, the agents shared store or skill lock,
Claude plugin and synced directories, node_modules, Codex system skills, the upstream
`LOCAL ADDITIONS BELOW` marker, `metadata.upstream`, and any other git repository.
It also refuses vetoed names, owned skills (already maintained), linked descendants,
and noncanonical layouts inside the skills root. The error names the signal; don't
remove installer marks to get around it.

A canonical skill in the registered root stays where it is. A loose real directory
with no installer or repository is backed up in the ledger's cache, moved into the
root's plugin layout, committed there, and linked back only at its original location.
An in-root registration ensures the Claude runtime link exists; repeating it repairs
a missing link. Adoption outside the Claude runtime does not add a Claude link.
Adoption requires git mode and a clean destination. A backup is retained. Commit failure restores the folder and marketplace before cleaning the
git index; any recovery failure names the backup and paths to repair. Unregistering
withdraws permission and records why; it preserves files, links, backup and history.

Registered does not mean authored by self-learn. Full updates may change prose,
description and reference files, preserving the user's intent and voice. The writer
retains the user's name and records registered provenance. Existing names containing
reserved words are valid for updates. Existing frontmatter keys outside the writer's
allow-list (including `allowed-tools` and `version`) must be carried unchanged: do
not remove or change them, or add a refused/unknown key. Description and prose remain
editable. Registration refuses unparseable frontmatter and non-mapping metadata by
rule name, because the writer cannot safely preserve and stamp those shapes. A content hash taken on
registration protects the first write; each later write records its new hash. Edits
made after reading require a fresh read and `--expect`; dirty files refuse writes.
Rename, retire, restore and veto-driven renames remain limited to owned skills.

Any agent may file a build or change request with a required explanatory `--note`:

```sh
self-learn skill request build --name <proposed> --lessons <id1>,<id2> --note "why"
self-learn skill request change <skill> --note "what should change and why"
self-learn skill request withdraw <id> --note "why this is no longer needed"
```

Build lessons must already exist. A change target must be owned or registered;
register it first otherwise. The next overseer run sees every open request, decides
it, and lists its answer and reason in the report. A built/changed answer closes only
when the corresponding writer step actually applies. Drafts or refused writes stay
open for the next run. Placed lessons with no covering case can move through the
maintenance-case route; covered lessons need reconsideration of their covering case.

All notes pass the secret scan before being recorded; refusals name the rule without
printing the match. Legacy matching rows are withheld in the model's inputs. Duplicate
open requests merge their notes and attribution. Build names pass the writer's name
checks; use a change request for an already registered name. A build may land under
another name or extend an existing skill, provided every requested lesson routes
there; the closed request records that actual name. Bad or missing answers leave
only those requests open and appear under “Refused / could not do”. A withdrawn
change target is labelled `target: withdrawn` so it can be declined with a reason.
If the skills root moves, unregister and register again at the new location.


## Draft against the Anthropic reference

Before drafting, rewriting or reorganising a skill, read `self-learn skill reference
show` (or `show --path`) and the native examples available on this machine. The
weekly overseer gets the same pack and examples in `skill-reference/`. Then run
`self-learn skill reference check <skill-name-or-path> --draft` on the draft.
The command prints its mode. Without a flag it uses installed mode only for the
deployed folder of an owned or registered skill; other folders are drafts.
Use `--installed` to inspect an unregistered installation or a copy of it.
Draft mode checks all supplied files, including stamps and compiler blocks;
installed mode strips those blocks in memory and notes retained user files. Refusals name
the rule and source; notes are advice, not permission to change the user's carried
settings or name. A passing static check does not prove useful triggering or output.
`skill write` reports its checked pack version and writes it into provenance;
`skill list` shows the version used by the last write.

`self-learn skill reference status` reads the pack's age, sources and last recorded
fetch without using the network. Use `status --fetch` to compare sources over plain
HTTP: exit 0 means all unchanged; exit 1 means a source changed or was unreachable.
An unavailable source is not evidence that the pack is current. Weekly runs use only
the recorded observation, so an outage cannot block skill writing.

To refresh: re-gather the named documentation and native skill examples, review
changes and licenses, update the packaged PACK.md and sources.yaml, calculate hashes
with `self_learn.skill_reference.digest`, bump the version/read date in both the
module and manifest, update checks/tests for changed requirements, and land a normal
code/spec revision. Do not edit the installed pack or replace it from model memory.
No native examples are vendored; optional roots can be set through
`SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT` and `SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT`.
Absent examples are omitted. Existing registered license/compatibility values, like
other carried settings, stay unchanged; conflicts with the reference are notes.
