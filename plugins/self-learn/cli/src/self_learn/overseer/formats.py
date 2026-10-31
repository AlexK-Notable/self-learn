"""The overseer workspace's ``formats/`` folder (2026-09-28).

The user's words: "that should all be stuff it has access to right off the
bat. maybe even have it live in its working directory." Run ``bf7788e6``
read the self-learn source to learn the exact shape of its successor cases
and sheets; everything it needs to write valid output is written here, into
its workspace, before each phase.

Nothing here is written by hand where the code has a constant or validator:
every closed set is read from the module that enforces it, so this folder
cannot drift from the runner. Each example file is checked by the runner's
own validators in ``tests/test_overseer_workspace.py``.
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from .. import lesson_writing

FORMATS_DIR = "formats"

#: Example ids: well-formed, and never a real record or case.
EXAMPLE_RECORD = "lrn-0000000a"
EXAMPLE_PARKED_CASE = "case-0000000a"
EXAMPLE_CASE = "case-0000000b"
#: E3b: the lessons a merge example folds into EXAMPLE_RECORD's successor.
EXAMPLE_MERGED = ("lrn-0000000b", "lrn-0000000c")

#: SK3 (S-NEXT-skills): the example skill phase B's formats carry, in
#: ``skill-example/`` (a folder shaped like ``skills/<name>/``), and the
#: lessons its example pair moves in.
SKILL_EXAMPLE_DIR = "skill-example"
EXAMPLE_SKILL = "example-release-notes"
EXAMPLE_SKILL_LESSONS = ("lrn-0000000a", "lrn-0000000b")
EXAMPLE_SKILL_REFERENCE = "references/procedure.md"

#: S-73: a WARNING hook's compile input, as a sheet line carries it (the
#: shape `batch.HOOK_INPUT_KEYS` and `ledger_ops._validate_hook_extension`
#: check). The shape of a real re-decision (a `pgrep -f`/`pkill -f`
#: self-match lesson moved to a warning hook), with invented text: the
#: agent may rightly use `-f`, so the hook warns rather than blocks.
EXAMPLE_HOOK_INPUT: dict[str, Any] = {
    "rationale": (
        "Warns on a pgrep -f or pkill -f; the call still runs, because a -f pattern is "
        "sometimes right. Other pgrep and pkill calls get no warning."
    ),
    "hook": {
        "mode": "warn",
        "event": "PreToolUse",
        "tools": ["Bash"],
        "path_regex": "(^|[;&|[:space:]])p(kill|grep)[[:space:]]+-[a-zA-Z]*f",
        "warn_message": (
            "A -f pattern matches whole command lines, this shell's included, so it can "
            "find or kill the caller.\nAct on a PID you captured, or check the pattern "
            "cannot match this command."
        ),
    },
    "examples": {
        "allow": [
            {"tool_name": "Bash", "tool_input": {"command": "pkill -x myserver"}},
            {"tool_name": "Bash", "tool_input": {"command": "pgrep -l node"}},
        ],
        "warn": [
            {"tool_name": "Bash", "tool_input": {"command": "pkill -f 'app --reindex'"}},
            {"tool_name": "Bash", "tool_input": {"command": "until ! pgrep -af worker; do sleep 1; done"}},
        ],
    },
}

#: S-73: a warning hook that runs AFTER the call (PostToolUse).
EXAMPLE_POST_HOOK_INPUT: dict[str, Any] = {
    "rationale": "Reminds the agent to check the migration after a Write under db/migrations/; nothing is blocked.",
    "hook": {
        "mode": "warn",
        "event": "PostToolUse",
        "tools": ["Write"],
        "path_regex": "db/migrations/",
        "warn_message": "A migration was written: run the migration check before the next step.",
    },
    "examples": {
        "allow": [
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/db/seeds/users.sql"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/README.md"}},
        ],
        "warn": [
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/db/migrations/0042_add.sql"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/db/migrations/0043_idx.sql"}},
        ],
    },
}

#: A DENY hook (the default mode): the call is blocked.
EXAMPLE_DENY_HOOK_INPUT: dict[str, Any] = {
    "rationale": "Blocks an Edit or Write of the service's database file; every other file stays allowed.",
    "hook": {
        "tools": ["Edit", "Write"],
        "path_regex": "/data/app\\.db$",
        "deny_message": "stop the service before editing its database file",
    },
    "examples": {
        "allow": [
            {"tool_name": "Edit", "tool_input": {"file_path": "/srv/app/config.yaml"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/srv/app/data/app.db.bak"}},
        ],
        "deny": [
            {"tool_name": "Edit", "tool_input": {"file_path": "/srv/app/data/app.db"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/opt/x/data/app.db"}},
        ],
    },
}


def _dump(data: Any) -> str:
    stream = io.StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.dump(data, stream)
    return stream.getvalue()


def closed_sets() -> dict[str, Any]:
    """Every closed set the runner and the case writer enforce, read from
    the modules that enforce them."""
    from .. import batch, cases, user_model, verbs
    from . import population, run

    overseer_containers = sorted(
        name for name, who in user_model._WHO_MAY_ADD.items() if "overseer" in who
    )
    return {
        "selection": {
            "top_level_keys": sorted(population._SELECTION_ALLOWED_KEYS),
            "case_entry_keys": sorted(population._SELECTION_CASE_ALLOWED_KEYS),
        },
        "initial_views": {
            "entry_keys": list(run.INITIAL_VIEW_KEYS),
            "confidence": list(run.INITIAL_CONFIDENCE),
        },
        "findings": {
            "entry_keys": list(run.FINDING_KEYS),
            "kind": list(run.FINDING_KINDS),
        },
        "questions": {"kind": list(run.QUESTION_KINDS)},
        "case": {
            "kind": sorted(cases.KINDS - {"parked"}),
            "trigger": sorted(cases.TRIGGERS),
            "outcome": sorted(cases.OUTCOMES - {"parked"}),
            "decision_confidence": sorted(cases.CONFIDENCE_VALUES),
            "successor_required_fields": list(run.SUCCESSOR_CASE_FIELDS),
            "maintenance_required_fields": list(run.MAINTENANCE_CASE_FIELDS),
            "parked_reasons_you_will_read": sorted(cases.PARKED_REASONS),
        },
        "sheet": {
            "top_level_keys": ["version", "items"],
            "version": 1,
            "verbs": {
                verb: {
                    "keys": sorted(keys),
                    "required": sorted(batch.REQUIRED_KEYS.get(verb, frozenset())),
                }
                for verb, keys in sorted(batch.PERMITTED_KEYS.items())
                if verb not in batch.SHEET_VERB_ALIASES
                # E1 fold 1: a verb the batch refuses the overseer by name
                # (`batch.REPLACE_REFUSED_ACTORS`, empty since E3b) is not
                # offered.
                and verb not in batch.agent_refused_verbs("overseer")
            },
            "item_keys_on_every_verb": ["id", "verb", "close_call"],
            "by": sorted(verbs.ROUTING_BY_VALUES),
            "refused_verbs": sorted(batch.REFUSED_VERBS_LITERAL),
            # 2026-10-06: the route destinations the runner refuses from the
            # overseer -- read from the batch's own actor set.
            "refused_dests": (
                ["reference"] if "overseer" in batch.REFERENCE_REFUSED_ACTORS else []
            ),
        },
        "user_model_delta": {
            "action": ["add", "lapse"],
            "containers_you_may_add_to": overseer_containers,
            "source": ["system-reading"],
            # 2026-10-05: the fields the user model refuses a line break
            # or a leading `#` in, per action (`user_model.ONE_LINE_FIELDS`).
            "one_line_fields": {
                action: list(fields) for action, fields in user_model.ONE_LINE_FIELDS.items()
            },
        },
        "report_headings_in_order": list(run._REPORT_SECTIONS),
        "hook": _hook_closed_sets(),
        "skill_template": _skill_template_sets(),
    }


def _skill_template_sets() -> dict[str, Any]:
    """SK3: the skill template's fixed rules, read from the constants the
    checker (`skill_scaffold.check_skill`, K1a) enforces."""
    from .. import skill_scaffold as k1a

    return {
        "name_max_chars": k1a.SKILL_NAME_MAX_CHARS,
        "name_reserved_words": list(k1a.SKILL_NAME_RESERVED_WORDS),
        "description_max_chars": k1a.SKILL_DESCRIPTION_MAX_CHARS,
        "listing_max_chars": k1a.SKILL_LISTING_MAX_CHARS,
        "frontmatter_keys_allowed": list(k1a.SKILL_FRONTMATTER_ALLOWED_KEYS),
        "frontmatter_keys_refused": sorted(k1a.SKILL_FRONTMATTER_REFUSED_KEYS),
        "metadata_key_the_runner_writes": k1a.SKILL_RUNNER_METADATA_KEY,
        "entry_file": k1a.SKILL_ENTRY_FILE,
        "references_dir": k1a.SKILL_REFERENCES_DIR,
        "references_suffix": k1a.SKILL_SUPPORT_FILE_SUFFIX,
        "references_max_depth": k1a.SKILL_REFERENCES_MAX_DEPTH,
        "body_soft_max_lines": k1a.SKILL_BODY_SOFT_MAX_LINES,
    }


def _hook_closed_sets() -> dict[str, Any]:
    """S-73: a hook block's closed sets, per mode, read from the validator's
    and the compiler's own constants."""
    from .. import hook_compiler, ledger_ops

    return {
        "mode": list(hook_compiler.HOOK_MODES),
        "default_mode": "deny",
        "events_per_mode": {m: list(e) for m, e in hook_compiler.MODE_EVENTS.items()},
        "default_event": "PreToolUse",
        "keys_per_mode": {
            mode: {"optional": list(ledger_ops._HOOK_OPTIONAL_KEYS), "required": list(required)}
            for mode, required in ledger_ops._HOOK_REQUIRED_KEYS.items()
        },
        "example_verdicts_per_mode": {m: list(v) for m, v in hook_compiler.MODE_VERDICTS.items()},
        "examples_per_verdict": [ledger_ops._HOOK_EXAMPLES_MIN, ledger_ops._HOOK_EXAMPLES_MAX],
        "tools": list(hook_compiler.GUARDABLE_TOOLS),
        "warn_message_max_chars": hook_compiler.WARN_MESSAGE_MAX,
    }


def user_model_one_line_rule() -> str:
    """The user model's one-line rule, as the overseer reads it, generated
    from `user_model.ONE_LINE_FIELDS` -- the table `add_entry` and
    `lapse_entry` check (2026-10-05).

    Run `03a07173`'s add `op-3b0e8cf5ca64` was refused ("a free-text field
    contains an embedded newline or a leading '#' heading-shaped line"):
    its `because` was a hard-wrapped block scalar, the form the general
    YAML rule (`run._YAML_TEXT_RULE`) recommends for free text and the one
    form these fields can never take, since even a one-line `|` scalar
    ends with a line break. The refusal is deliberate (gate r2 B1: a line
    break in these fields becomes forged structure in user-model.md); the
    instructions were what was missing."""
    from .. import user_model

    add = ", ".join(user_model.ONE_LINE_FIELDS["add"])
    lapse = ", ".join(user_model.ONE_LINE_FIELDS["lapse"])
    return (
        "In user-model-delta.yaml every free-text value is ONE paragraph on ONE line: an "
        f"add's {add} (every item of a list), and a lapse's {lapse}. Write each as a "
        "double-quoted string on a single line, never as a block scalar (`|` or `>` keeps "
        "a line break), with no line break inside it and no line starting with `#`. A "
        "value with a line break or a heading-shaped line is refused, and that update is "
        "lost."
    )


#: E3b (D-AUTHOR §2.8, the overseer's column, and §2.13): how the overseer
#: rewrites a lesson's words. Phase B's README only.
_REPLACE_RULES = (
    "Rewriting a lesson's words: a `replace` line writes a new lesson that takes over",
    "from the line's lesson, and from each lesson its `also` names (a merge), in one",
    "motion; the old lessons stay in the ledger, marked replaced. The new lesson goes",
    "where the line's lesson is placed now unless the line names a `dest`. If it",
    "lands on an always-loaded line -- an always-loaded `dest`, or no `dest` and a",
    "lesson placed in a CLAUDE.md itself (not a rules file) -- the case needs the",
    "combined test, as a route there does. Use it to correct",
    "or widen a placed lesson, to shorten one, or to merge several into one. To correct",
    "a lesson a case the steward or you recorded covers, write a kind: reconsider",
    "successor of that case; for anything else -- a shortening, a merge, a lesson no",
    "correctable case covers -- write a named kind: maintenance pair. Never a lesson",
    "routed to a hook: move it with `route`.",
    "The case's records name every lesson the line changes (its id and each id in",
    "also), and its decision carries `rewrite`: each idea of the old text, in a few",
    "words, with where it is now -- loaded, context, field:<name>, or dropped with a",
    "why (wrong, out of date, or said by another lesson you name). Quote the old text",
    "in the evidence. A replace case without `rewrite`, or naming a lesson its records",
    "do not, is dropped with its sheet. Shortening is yours to do when the line is",
    "longer than its moment needs; what matters is that no useful meaning is lost,",
    "and `rewrite` is where you show it. See case-rewrite-example.yaml (a",
    "shortening), case-merge-example.yaml (a merge) and",
    "case-correct-lesson-example.yaml (a correction of a placed lesson no case",
    "covers), each with its sheet-*.yaml. The shortening's lesson is placed in a",
    "user CLAUDE.md, so its case carries `always_loaded`; the merge's and the",
    "correction's lessons are placed in a SKILL.md, which needs none -- a merge or",
    "correction of a CLAUDE.md lesson carries it as the shortening does.",
)


def _skills_rules() -> list[str]:
    """SK3 (S-NEXT-skills parts 3-6; D-AUTHOR §3.2-§3.5): phase B's section
    on the skills self-learn owns. The template's numbers are read from the
    checker's constants (`skill_scaffold`), the workspace names from
    `overseer.skills`."""
    from .. import skill_scaffold as k1a
    from . import run, skills

    allowed = ", ".join(k1a.SKILL_FRONTMATTER_ALLOWED_KEYS)
    refused = ", ".join(sorted(k1a.SKILL_FRONTMATTER_REFUSED_KEYS))
    reserved = " or ".join(f'"{w}"' for w in k1a.SKILL_NAME_RESERVED_WORDS)
    text = f"""\
## Skills self-learn owns

Lessons that are parts of one task can become one skill that self-learn writes, keeps
up to date and can retire. The lessons stay lessons inside it: they compile into the
skill's managed section, as they do in any skill, and keep their history. The text
you write around them is the coherent part: when to use the skill, the procedure,
how its rules relate.

Your inputs: {skills.OWNED_DIR}/<name>/ for each skill self-learn owns, as it is now --
{skills.FILES_DIR}/ (its {k1a.SKILL_ENTRY_FILE} without the managed section, and its
{k1a.SKILL_REFERENCES_DIR}/ files: start a change from these), {skills.ROW_FILE} (who made
it, when, from which case), {skills.LESSONS_FILE} (the lessons routed into it) and
{skills.DIFF_FILE} (what changed in its text since self-learn last wrote it).
{skills.VETOES_FILE} lists the names the user vetoed, the skills whose name the user
vetoed, and the user's requests to retire a skill. {skills.PROPOSALS_FILE} lists the
steward's skill proposals; each is a parked case in parked/, decided like any other.
{skills.WRITING_FILE} says whether this run deploys what you write.

When to make a skill rather than add to one (judgment, not a rule with numbers):
- Prefer an existing skill: if one already owns the moment (its name and description
  match the task), route the lessons there.
- Make one when all of these hold: the lessons share one task-shaped trigger a
  description can name; the content is more than a line (a procedure, a format,
  examples); no existing skill owns it.
- Signs a skill is right: always-loaded lines are paid for in every session but matter
  only for that task; the user named the skill's shape; the pattern has recurred.
- Not a skill: a lesson tied to files (a path-scoped rule), a lesson tied to one
  command (a warning hook), one line that fits where it is.

To build a skill: write {skills.STAGE_SKILLS_DIR}/<name>/{k1a.SKILL_ENTRY_FILE} (and
{k1a.SKILL_REFERENCES_DIR}/<file>{k1a.SKILL_SUPPORT_FILE_SUFFIX} when the detail is long), and a
named pair: a case with outcome: route and decision.skill {{name, why, lessons}}
(kind: maintenance, or the successor of a skill-proposal parked case), whose sheet
routes each lesson in with dest: new-skill:<name>. A lesson already placed elsewhere moves
in by the same route line in a kind: reconsider successor of the case that placed it,
which the runner applies as a reroute once the skill is written. See {SKILL_EXAMPLE_DIR}/,
case-skill-example.yaml and sheet-skill-example.yaml. The runner writes the skill
first, then records the case and applies the sheet; if the write is refused, the whole
pair is dropped and named under "Refused / could not do", and no lesson moves. The
runner adds the managed section and the metadata.{k1a.SKILL_RUNNER_METADATA_KEY} stamp: never
write either.

The template (the runner refuses a skill that breaks it, naming the rule): the name is
the folder's name, kebab-case, at most {k1a.SKILL_NAME_MAX_CHARS} characters, without {reserved},
and not the name of any skill already loaded on this machine or any vetoed name; the
description is not empty, at most {k1a.SKILL_DESCRIPTION_MAX_CHARS} characters, says what the skill
does and when to use it, in the third person, with no XML tags; frontmatter keys only
{allowed} ({refused} are refused); supporting files are markdown only, in
{k1a.SKILL_REFERENCES_DIR}/, one level deep, each linked from {k1a.SKILL_ENTRY_FILE}; every file is
secret-scanned. Keep the body under {k1a.SKILL_BODY_SOFT_MAX_LINES} lines and concise: the reader is
a capable agent. closed-sets.yaml has these under skill_template.

To change a skill self-learn owns: write the whole new text in
{skills.STAGE_SKILLS_DIR}/<name>/, starting from {skills.OWNED_DIR}/<name>/{skills.FILES_DIR}/, in a pair whose
case carries decision.skill naming it. Read {skills.DIFF_FILE} first and keep what a person
wrote unless your case says why not. If the skill changes again before the runner
writes it, the write is refused and you see it next week. A pair that only changes a
skill's text may have an empty sheet (items: []).

To route a pending lesson into a skill self-learn owns, write a route line with dest:
new-skill:<name> in a case whose decision.skill names it; no folder is needed.

A case may name in decision.skill a skill it does not build: the successor that declines
a skill-proposal parked case may keep the proposal's decision.skill, and a case may name a
linked skill self-learn does not own whose lessons it routes the ordinary way. With
no {skills.STAGE_SKILLS_DIR}/<name>/ folder and no line routing into new-skill:<name>, such a
case carries no skill step and its pair applies as any other. A sheet that routes into
new-skill:<name> for a skill self-learn does not own is building it, and needs the folder.

To retire a skill self-learn owns: a pair whose case has outcome: retire and
decision.skill naming it. Its sheet first moves every lesson routed into it somewhere
else (each lesson's history in {run.LESSONS_DIR}/ says where it was before); moving a routed
lesson is a kind: reconsider successor of the case that moved it in. A sheet with no line
for a lesson routed into the skill drops the pair. The runner retires
the skill only after every line of the sheet applied. A skill with no lessons left is
retired with an empty sheet. A case that retires lessons out of a skill it keeps does not
name the skill in decision.skill. A request to retire in {skills.VETOES_FILE} is the user's: retire
that skill this run, or ask the user in questions.yaml why you did not.

A vetoed name is never used again, and a skill whose name was vetoed cannot be written
under it. While {skills.WRITING_FILE} says deploy: false, every skill you build or change is
checked by the same rules and kept as a draft, nothing is retired, and those pairs are
not applied; write them exactly as you would otherwise.
"""
    return text.splitlines()


def _rules(phase: str) -> str:
    from . import run

    lines = [
        "# Output formats",
        "",
        "Everything you need to write valid output is in this folder. Each file",
        "named below is a valid example the runner accepts; copy its shape, not its",
        "ids or words. closed-sets.yaml lists every value set you must pick from.",
        "",
        "Rules the runner enforces:",
        "",
        # E3b fold (gate N1): phase B's rule names its two exceptions.
        "- " + " ".join((run._YAML_TEXT_RULE_B if phase == "B" else run._YAML_TEXT_RULE).split()),
        "- Every file you write stays in this workspace; nothing outside it can be",
        "  read or written.",
    ]
    if phase == "A":
        lines += [
            "",
            "Phase A files: selection.yaml, initial-views.yaml (one entry per selected",
            "case, every field non-empty text).",
        ]
    else:
        lines += [
            "- In a case file no line of any text field may start with `## `.",
            "- Every text field of a case is secret-scanned: an evidence item whose",
            "  quote or ref matches is dropped; a hit anywhere else refuses the case.",
            "- A successor case supersedes exactly one case, and a case gets at most",
            "  one successor. A kind: resolution successor supersedes a parked case.",
            "  A kind: reconsider successor may supersede a parked case or a case that",
            "  is NOT parked, to correct it (for example a decision whose line the",
            "  ledger refused at apply time), provided that case covers every record",
            "  the reconsider names, has not been superseded, passes its freeze hash,",
            "  and was recorded by the steward or the overseer, never by a person. See",
            "  case-correct-example.yaml. Each case-<name>.yaml pairs with a",
            "  sheet-<name>.yaml; a successor's sheet is never empty.",
            "- A catalogue change that decides no parked case is a kind: maintenance",
            "  case with no supersedes. Write each one as its own named pair,",
            "  case-<name>.yaml with sheet-<name>.yaml, as many as the run needs and",
            "  beside your successors; the single case.yaml with sheet.yaml still works",
            "  for one. The runner tells a named maintenance pair from a successor by",
            "  its kind.",
            *textwrap.wrap(
                user_model_one_line_rule(), width=78,
                initial_indent="- ", subsequent_indent="  ",
                break_long_words=False, break_on_hyphens=False,
            ),
            "",
            "Phase B files: report.md, findings.yaml, questions.yaml,",
            "user-model-delta.yaml, case-example.yaml + sheet-example.yaml (a",
            "successor), case.yaml + sheet.yaml shapes in maintenance-case.yaml and",
            "maintenance-sheet.yaml.",
            "",
            "Moving a lesson that is ALREADY routed to a different destination",
            "(a path-scoped rule, a stronger surface, a hook): a successor with",
            "kind: reconsider whose sheet has a `route` item naming the new `dest`;",
            "the runner applies it as a reroute, retiring the old placement in the",
            "same motion. See case-redecide-example.yaml + sheet-redecide-example.yaml",
            "(a routed lesson moved to a warning hook). A hook carries its compile",
            "input on the line (`hook:`); the runner generates the script and replays",
            "the examples against it. A hook either DENIES the call (mode: deny, the",
            "default; PreToolUse only) or lets it run and WARNS the agent (mode: warn;",
            "event PreToolUse, before the call, or PostToolUse, after it). Choose warn",
            "when the lesson is advice the agent may rightly override, deny when the",
            "call is always wrong. The agent reads a warning as `self-learn <lesson",
            "id>: <warn_message>`; write only the message, the runner adds the prefix.",
            "See sheet-hook-warn-post-example.yaml (a warning",
            "after the call) and sheet-hook-deny-example.yaml (a deny guard); the",
            "hook block's keys per mode are in closed-sets.yaml under `hook`.",
            "Switching a hook on stays the user's setting (overseer.hook_activation).",
            "Re-decidable FROM claude-md, skill-md, new-skill, reference, hook;",
            "TO claude-md (any variant), skill-md, hook; never new-skill or reference.",
            "",
            "Never route a lesson to `reference` (a references/ shelf file such as",
            "references/LEARNINGS.md): the runner refuses that line from you, whether",
            "it is a fresh route or a re-decision (closed-sets.yaml, sheet.refused_dests).",
            "Never retire a lesson as covered by a shelf either (`covered_by:",
            "reference:<file>` on a `retire` line): the runner refuses that line too.",
            "A shelf is reached only through a pointer that names no subject, and none",
            "had ever been read when this was measured. A lesson you would have put on a",
            "shelf goes to a path-scoped rule when it is tied to files, an existing",
            "skill, a warning hook when it is tied to a command, or is parked or",
            "rejected -- never to an always-loaded line just because the shelf is",
            "closed (the combined test below still decides that). A lesson already ON",
            "a shelf can be taken off it by a kind: reconsider successor: a `route`",
            "line moves it, and a `reject` or `defer` line takes it off too; either way",
            "its shelf entry is removed in the same motion. A lesson routed to a hook",
            "cannot be rejected or deferred this way; move it with a `route` line.",
            "",
            "A path-scoped rule (dest: claude-md:rules:<topic>) takes its globs from",
            "`rules_paths:` on the line (relative globs; each must match a file unless",
            "allow_empty_glob: true). See sheet-rule-example.yaml.",
            "A route (or a reroute under a reconsider case) into a rules topic whose",
            "file already has a `paths:` list is REFUSED when the line carries no",
            "`rules_paths` -- an unpathed lesson would make the whole file load in",
            "every session; no sheet key unscopes a file. Choose the globs in this",
            "order: the lesson it supersedes (`self-learn show --json <old id>`",
            "prints routing.rules_paths; a successor inherits them if the line",
            "names none, but only from a lesson routed to the same topic in the same",
            "bucket -- same scope and, for a project lesson, the same project -- so",
            "write them out), the file's",
            "existing `paths:` when the lesson concerns the same files, else the",
            "files the lesson is about, relative to the host root, as narrow as the",
            "trigger. A glob for a file that no longer exists is fine when the",
            "lesson guards against recreating it: set allow_empty_glob: true and it",
            "is kept.",
            "",
            "A route to an always-loaded line (dest: claude-md or claude-md:local)",
            "needs the combined test in its case: decision.always_loaded with",
            "always_applies, missing_costs_more and cheaper_fixes_fail, each",
            "{because, refs} where refs are the case's own evidence refs. All three",
            "must hold; a case missing one is dropped. See",
            "case-always-loaded-example.yaml.",
            "",
            *_REPLACE_RULES,
            "",
            *_skills_rules(),
            "",
            # E3a: the passage on writing a lesson, inlined (never a pointer).
            # Phase B only: phase A selects cases and writes no lesson text.
            lesson_writing.inlined(),
            lesson_writing.AGENT_SHEET_NOTE,
        ]
    return "\n".join(lines) + "\n"


def phase_a_examples() -> dict[str, str]:
    from . import run

    return {
        "selection.yaml": _dump({
            "cases": [{"id": EXAMPLE_CASE}],
            "why_these": "The one case in the population whose evidence is thin.",
            "why_stopped": "The rest read as settled on their evidence.",
        }),
        "initial-views.yaml": _dump({"cases": [{
            "id": EXAMPLE_CASE,
            "what_i_would_do": "Keep the lesson where it is.",
            "why": "Its evidence names one repository only.",
            "what_evidence_decides_it": "A second repository showing the same failure.",
            "confidence": run.INITIAL_CONFIDENCE[0],
        }]}),
    }


def phase_b_examples() -> dict[str, str]:
    from .. import always_loaded
    from . import run

    headings = "\n".join(f"## {name}\n- none" for name in run._REPORT_SECTIONS)
    evidence = [{"ref": f"record:{EXAMPLE_RECORD}", "quote": "status: pending"}]
    return {
        "report.md": f"# Overseer report\n\n{headings}\n",
        "findings.yaml": _dump({"findings": [{
            "case": EXAMPLE_CASE, "kind": run.FINDING_KINDS[0],
            "text": "The decision follows from its evidence: the record names one repository.",
        }]}),
        "questions.yaml": _dump({"questions": [{
            "id": "q-example-question", "kind": "ask", "cases": [EXAMPLE_CASE],
            "text": "Will you keep using this repository next month? Yes keeps the lesson; no retires it.",
            "why": "It decides whether the lesson stays loaded.",
        }]}),
        # Every free-text value double-quoted on one line, the form
        # `user_model_one_line_rule` asks for (2026-10-05).
        "user-model-delta.yaml": _dump({"updates": [{
            "action": "add", "container": "D", "source": "system-reading",
            "title": DoubleQuotedScalarString("Prefers small reviewed steps"),
            "because": DoubleQuotedScalarString(
                "Three cases this week split one change into several reviewed parts: "
                "each part was reviewed before the next was started."
            ),
            "ref": DoubleQuotedScalarString(f"case:{EXAMPLE_CASE}"),
        }]}),
        "case-example.yaml": _dump({
            "kind": "resolution", "trigger": "weekly", "outcome": "reject",
            "records": [EXAMPLE_RECORD], "scope": "skill:example",
            "question": "Should this lesson be kept?",
            "supersedes": EXAMPLE_PARKED_CASE,
            "evidence": evidence,
            "decision": {"verb": "reject", "because": "It repeats another lesson.",
                "confidence": "provisional"},
        }),
        "sheet-example.yaml": _dump({
            "version": 1,
            "items": [{"id": EXAMPLE_RECORD, "verb": "reject", "close_call": False}],
        }),
        "case-redecide-example.yaml": _dump({
            "kind": "reconsider", "trigger": "weekly", "outcome": "route",
            "records": [EXAMPLE_RECORD], "scope": "user",
            "question": "The rule was broken twice while loaded; should a hook enforce it instead?",
            "supersedes": EXAMPLE_PARKED_CASE,
            "evidence": evidence,
            "decision": {"verb": "route", "because": (
                "The line was loaded and broken twice; the failure is one Bash call a hook can "
                "see, and a -f pattern is sometimes right, so the hook warns rather than blocks."
            ), "confidence": "settled"},
        }),
        # S-76: a reconsider correcting a case that is not parked -- the
        # shape of run `03a07173`'s re-decision of `lrn-19f82fc5`, whose
        # first decision (a resolution) had its route refused at apply.
        # It pairs with a sheet like sheet-redecide-example.yaml.
        "case-correct-example.yaml": _dump({
            "kind": "reconsider", "trigger": "weekly", "outcome": "route",
            "records": [EXAMPLE_RECORD], "scope": "user",
            "question": (
                "The earlier decision to move this lesson to a hook was right, but its route "
                "was refused because that case was not a reconsider; should it be made again?"
            ),
            "supersedes": EXAMPLE_CASE,
            # its own evidence: the lesson it re-decides is already routed
            "evidence": [{"ref": f"record:{EXAMPLE_RECORD}", "quote": "status: routed"}],
            "decision": {"verb": "route", "because": (
                f"{EXAMPLE_CASE} decided a warning hook and its route line was refused at apply "
                "time because the lesson was already routed; a reconsider is the case kind that "
                "moves a routed lesson, so the same decision is made again here."
            ), "confidence": "settled"},
        }),
        "sheet-redecide-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "route", "dest": "hook",
                "hook": EXAMPLE_HOOK_INPUT, "close_call": False,
            }],
        }),
        "sheet-hook-warn-post-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "route", "dest": "hook",
                "hook": EXAMPLE_POST_HOOK_INPUT, "close_call": False,
            }],
        }),
        "sheet-hook-deny-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "route", "dest": "hook",
                "hook": EXAMPLE_DENY_HOOK_INPUT, "close_call": False,
            }],
        }),
        "sheet-rule-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "route", "dest": "claude-md:rules:migrations",
                "rules_paths": ["db/migrations/**/*.sql"], "close_call": False,
            }],
        }),
        "case-always-loaded-example.yaml": _dump({
            "kind": "resolution", "trigger": "weekly", "outcome": "route",
            "records": [EXAMPLE_RECORD], "scope": "user",
            "question": "Should this lesson be in every session?",
            "supersedes": EXAMPLE_PARKED_CASE,
            "evidence": evidence,
            "decision": {
                "verb": "route",
                "because": "Every test of the combined test holds on the record's own evidence.",
                "confidence": "settled",
                "always_loaded": {
                    key: {"because": f"why {key} holds, in one sentence", "refs": [evidence[0]["ref"]]}
                    for key in always_loaded.TEST_KEYS
                },
            },
        }),
        # E3b (D-AUTHOR §2.13): three named maintenance pairs that rewrite
        # lessons' words -- a shortening, a merge, and a correction of a
        # placed lesson no correctable case covers -- each with the
        # `decision.rewrite` the runner requires of a replace.
        "case-rewrite-example.yaml": _dump({
            "kind": "maintenance", "trigger": "weekly", "outcome": "replaced",
            "records": [EXAMPLE_RECORD], "scope": "user",
            "question": "This always-loaded line carries its whole story; can it be shorter without losing meaning?",
            "evidence": [{"ref": f"record:{EXAMPLE_RECORD}", "quote": (
                "Instruction: stop when the yield per round is flat, because in the March review "
                "the fourth round found one nit and the fifth found the same nit again"
            )}],
            "decision": {
                "verb": "replace",
                "because": "The rule and its reason stay loaded; the story of the March review moves to Context.",
                "confidence": "settled",
                "rewrite": {"ideas": [
                    {"idea": "stop when the yield per round is flat", "now": "loaded"},
                    {"idea": "a flat yield is a steady state, not convergence", "now": "loaded"},
                    {"idea": "the March review: round four and five found the same nit", "now": "context"},
                ]},
                # E3b fold (gate D1): a dest-less replace keeps its lesson's
                # placement -- here a user CLAUDE.md, always loaded -- so the
                # case meets the combined test exactly as a route there does.
                "always_loaded": {
                    key: {"because": f"why {key} holds, in one sentence",
                          "refs": [f"record:{EXAMPLE_RECORD}"]}
                    for key in always_loaded.TEST_KEYS
                },
            },
        }),
        "sheet-rewrite-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "replace",
                "trigger": DoubleQuotedScalarString("About to run another round of the same review."),
                "instruction": DoubleQuotedScalarString(
                    "Stop when the yield per round is flat: that is a steady state, not convergence."
                ),
                "context": DoubleQuotedScalarString(
                    "In the March review the fourth round found one nit and the fifth found the same nit again."
                ),
                "because": DoubleQuotedScalarString("shorter; the story moves to Context"),
                "close_call": False,
            }],
        }),
        "case-merge-example.yaml": _dump({
            "kind": "maintenance", "trigger": "weekly", "outcome": "replaced",
            "records": [EXAMPLE_RECORD, *EXAMPLE_MERGED], "scope": "skill:example",
            "question": "Three lessons in one skill say the same rule about test timing; should they be one?",
            "evidence": [
                {"ref": f"record:{rid}", "quote": "Instruction: rerun a timing-sensitive failure before trusting it"}
                for rid in (EXAMPLE_RECORD, *EXAMPLE_MERGED)
            ],
            "decision": {
                "verb": "replace",
                "because": "One rule said three times loads three times; one line keeps every idea the three carried.",
                "confidence": "settled",
                "rewrite": {"ideas": [
                    {"idea": "rerun a timing-sensitive failure before trusting it", "now": "loaded"},
                    {"idea": "a browser test that failed once under load", "now": "context"},
                    {"idea": "the same advice for benchmarks", "now": "dropped",
                     "why": f"said by {EXAMPLE_RECORD}'s new line, which names benchmarks"},
                ]},
            },
        }),
        "sheet-merge-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "replace", "also": list(EXAMPLE_MERGED),
                "trigger": DoubleQuotedScalarString(
                    "About to trust one failing run of a timing-sensitive test or benchmark."
                ),
                "instruction": DoubleQuotedScalarString(
                    "Rerun it before acting: one failure under load is a lead, not a result."
                ),
                "because": DoubleQuotedScalarString("three lessons with one rule become one"),
                "close_call": False,
            }],
        }),
        "case-correct-lesson-example.yaml": _dump({
            "kind": "maintenance", "trigger": "weekly", "outcome": "replaced",
            "records": [EXAMPLE_RECORD], "scope": "skill:example",
            "question": "This placed lesson names the wrong command; no case the steward or the overseer recorded covers it. Should it be corrected?",
            "evidence": [
                {"ref": f"record:{EXAMPLE_RECORD}", "quote": "Instruction: restart the service with systemctl restart"},
                {"ref": "transcript:example-session#L52", "quote": "a user unit needs systemctl --user restart"},
            ],
            "decision": {
                "verb": "replace",
                "because": "The lesson is right about restarting and wrong about the command; the evidence shows the right one.",
                "confidence": "settled",
                "rewrite": {"ideas": [
                    {"idea": "restart the service after changing its unit", "now": "loaded"},
                    {"idea": "the command is systemctl restart", "now": "dropped",
                     "why": "wrong: it is a user unit, so the command is systemctl --user restart"},
                ]},
            },
        }),
        "sheet-correct-lesson-example.yaml": _dump({
            "version": 1,
            "items": [{
                "id": EXAMPLE_RECORD, "verb": "replace",
                "trigger": DoubleQuotedScalarString("About to apply a change to the sync service's user unit."),
                "instruction": DoubleQuotedScalarString(
                    "Restart it with systemctl --user restart; it is a user unit."
                ),
                "because": DoubleQuotedScalarString("the command was wrong"),
                "close_call": False,
            }],
        }),
        "maintenance-case.yaml": _dump({
            "kind": "maintenance", "trigger": "weekly", "outcome": "no-action",
            "records": [EXAMPLE_RECORD], "scope": "skill:example",
            "question": "Does this lesson need a note?",
            "evidence": evidence,
            "decision": {"because": "A note records what was checked.",
                "confidence": "provisional"},
        }),
        "maintenance-sheet.yaml": _dump({
            "version": 1,
            "items": [{"id": EXAMPLE_RECORD, "verb": "note", "append": "Checked this week."}],
        }),
        **skill_examples(),
    }


def skill_example_files() -> dict[str, str]:
    """SK3: a valid skill folder, keyed as phase B's ``skills/<name>/`` is
    (``SKILL.md``, ``references/<file>.md``); it passes
    ``skill_scaffold.check_skill`` (`tests/test_overseer_skill_build.py`)."""
    skill_md = (
        "---\n"
        f"name: {EXAMPLE_SKILL}\n"
        'description: "Drafts release notes from merged changes. Use when the user asks for '
        'release notes, a changelog entry, or a summary of what shipped in a version."\n'
        "---\n\n"
        "# Release notes\n\n"
        "Use this when a version is about to ship and its notes are wanted. Each lesson in the\n"
        "section at the end of this file says one rule; this text says how they fit together.\n\n"
        "## Procedure\n\n"
        "1. Collect the changes merged since the last release.\n"
        "2. Group them by what a reader of the notes cares about, not by where the code changed.\n"
        "3. Write one line per change; [the procedure](" + EXAMPLE_SKILL_REFERENCE + ") has\n"
        "   the full steps and a worked example.\n\n"
        "## How the rules relate\n\n"
        "A line that is wrong is worse than a missing line, so accuracy comes before brevity.\n"
    )
    reference = (
        "# Procedure\n\n"
        "1. List the merged changes since the last release, with their titles.\n"
        "2. Drop the changes no reader would notice (internal refactors, test-only changes).\n"
        "3. Group the rest: new, changed, fixed.\n"
        "4. Write each line as what the reader can now do, in one sentence.\n\n"
        "## Worked example\n\n"
        "A merged change titled \"cache parsed config\" becomes: \"Starting is faster when the\n"
        "configuration file is large.\"\n"
    )
    return {"SKILL.md": skill_md, EXAMPLE_SKILL_REFERENCE: reference}


def skill_examples() -> dict[str, str]:
    """SK3: phase B's skill examples -- the skill folder, a pair that
    builds it, and a pair that retires it."""
    evidence = [
        {"ref": f"record:{rid}", "quote": "Instruction: group release notes by what the reader notices"}
        for rid in EXAMPLE_SKILL_LESSONS
    ]
    skill = {
        "name": EXAMPLE_SKILL,
        "why": (
            "Both lessons are steps of one task, writing release notes, which a description "
            "can name; together with the procedure they are more than a line."
        ),
        "lessons": list(EXAMPLE_SKILL_LESSONS),
    }
    files = {
        f"{SKILL_EXAMPLE_DIR}/{rel}": text for rel, text in skill_example_files().items()
    }
    return {
        **files,
        "case-skill-example.yaml": _dump({
            "kind": "maintenance", "trigger": "weekly", "outcome": "route",
            "records": list(EXAMPLE_SKILL_LESSONS), "scope": "user",
            "question": "Two lessons are steps of writing release notes; should they become one skill?",
            "evidence": evidence,
            "decision": {
                "verb": "route",
                "because": (
                    "No skill owns writing release notes; the lessons share that trigger and need "
                    "a procedure around them, which a skill holds and a single line does not."
                ),
                "confidence": "settled",
                "skill": skill,
            },
        }),
        "sheet-skill-example.yaml": _dump({
            "version": 1,
            "items": [
                {"id": rid, "verb": "route", "dest": f"new-skill:{EXAMPLE_SKILL}", "close_call": False}
                for rid in EXAMPLE_SKILL_LESSONS
            ],
        }),
        # A retirement: a reconsider of the case that built the skill moves
        # its lessons out (applied as reroutes), then the runner retires it.
        "case-skill-retire-example.yaml": _dump({
            "kind": "reconsider", "trigger": "weekly", "outcome": "retire",
            "records": list(EXAMPLE_SKILL_LESSONS), "scope": "user",
            "question": "The release-notes skill has not been used in months; should it be retired?",
            "supersedes": EXAMPLE_CASE,
            "evidence": evidence,
            "decision": {
                "verb": "retire",
                "because": (
                    "Releases are no longer made from this machine; the lessons go back to a "
                    "path-scoped rule on the changelog, where they still apply."
                ),
                "confidence": "settled",
                "skill": {**skill, "why": "Retired: no release has been made here in months."},
            },
        }),
        "sheet-skill-retire-example.yaml": _dump({
            "version": 1,
            "items": [
                {"id": rid, "verb": "route", "dest": "claude-md:rules:release-notes",
                 "rules_paths": ["CHANGELOG.md"], "close_call": False}
                for rid in EXAMPLE_SKILL_LESSONS
            ],
        }),
    }


def write(workspace: Path, phase: str) -> Path:
    """Write the formats for *phase* (``"A"`` or ``"B"``) into
    ``<workspace>/formats/``; phase B adds its files to phase A's. Phase A
    sees no case or sheet vocabulary: it is blind to the steward's
    decisions."""
    from . import run

    root = workspace / FORMATS_DIR
    files = dict(phase_a_examples())
    if phase == "B":
        files.update(phase_b_examples())
        files["closed-sets.yaml"] = _dump(closed_sets())
    else:
        sets = closed_sets()
        files["closed-sets.yaml"] = _dump(
            {key: sets[key] for key in ("selection", "initial_views")}
        )
    files["README.md"] = _rules(phase)
    for name, text in files.items():
        run._write_stage(workspace, root / name, text)
    return root
