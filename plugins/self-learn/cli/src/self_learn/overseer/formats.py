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
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

FORMATS_DIR = "formats"

#: Example ids: well-formed, and never a real record or case.
EXAMPLE_RECORD = "lrn-0000000a"
EXAMPLE_PARKED_CASE = "case-0000000a"
EXAMPLE_CASE = "case-0000000b"


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
        },
        "report_headings_in_order": list(run._REPORT_SECTIONS),
    }


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
            "- A successor case supersedes exactly one parked case, and a parked case",
            "  gets at most one successor. Each case-<name>.yaml pairs with a",
            "  sheet-<name>.yaml; a successor's sheet is never empty.",
            "- A catalogue change that decides no parked case is case.yaml (kind:",
            "  maintenance, no supersedes) with sheet.yaml.",
            "",
            "Phase B files: report.md, findings.yaml, questions.yaml,",
            "user-model-delta.yaml, case-example.yaml + sheet-example.yaml (a",
            "successor), case.yaml + sheet.yaml shapes in maintenance-case.yaml and",
            "maintenance-sheet.yaml.",
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
        "user-model-delta.yaml": _dump({"updates": [{
            "action": "add", "container": "D", "source": "system-reading",
            "title": "Prefers small reviewed steps",
            "because": "Three cases this week split one change into several reviewed parts.",
            "ref": f"case:{EXAMPLE_CASE}",
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
