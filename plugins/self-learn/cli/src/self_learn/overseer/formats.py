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

FORMATS_DIR = "formats"

#: Example ids: well-formed, and never a real record or case.
EXAMPLE_RECORD = "lrn-0000000a"
EXAMPLE_PARKED_CASE = "case-0000000a"
EXAMPLE_CASE = "case-0000000b"

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
            },
            "item_keys_on_every_verb": ["id", "verb", "close_call"],
            "by": sorted(verbs.ROUTING_BY_VALUES),
            "refused_verbs": sorted(batch.REFUSED_VERBS_LITERAL),
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
        "- " + " ".join(run._YAML_TEXT_RULE.split()),
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
            "- A catalogue change that decides no parked case is case.yaml (kind:",
            "  maintenance, no supersedes) with sheet.yaml.",
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
            "TO claude-md (any variant), skill-md, reference, hook; never new-skill.",
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
