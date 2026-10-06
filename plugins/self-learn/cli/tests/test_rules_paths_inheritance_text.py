"""The rules_paths inheritance text matches the code (S-75 follow-up, 2026-10-05).

`verbs._inherit_rules_paths` lets a rules route of a record that supersedes
another inherit that record's `rules_paths` only when the old record is
routed to the same rules topic AND sits in the same bucket (same scope and,
for a project lesson, the same project: `old_path.parent.parent !=
bucket_dir` returns no inheritance). S-75 left the steward's and the
overseer's instructions, `commands/review.md` and `steward-method.md`
saying only "routed to the same topic", so an agent could leave a cross-
project successor's globs out expecting them to be inherited, and have the
route refused as unpathed.

Text only: no ledger, no model call.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

import pytest

from self_learn import cli, steward_prompt, verbs
from self_learn.overseer import formats

METHOD = Path(__file__).resolve().parents[2] / "skills" / "self-learn" / "references" / "steward-method.md"
REVIEW = Path(__file__).resolve().parents[2] / "commands" / "review.md"


def _rules_path_help(command: str) -> str:
    """The `--rules-path` help of one CLI subcommand, as argparse holds it."""
    parser = cli._build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    sub = subparsers.choices[command]
    return next(
        action.help or "" for action in sub._actions
        if "--rules-path" in action.option_strings
    )


def _text_of(name: str) -> str:
    if name.endswith(" --rules-path help"):
        raw = _rules_path_help(name.split()[0])
    elif name == "steward brief":
        raw = steward_prompt._render_output_contract()
    elif name == "overseer rules":
        raw = formats._rules("B")
    elif name == "steward method":
        raw = METHOD.read_text(encoding="utf-8")
    else:
        raw = REVIEW.read_text(encoding="utf-8")
    return " ".join(raw.lower().split())


@pytest.mark.parametrize("name", [
    "steward brief", "overseer rules", "steward method", "review md",
    # 2026-10-05 fold: the CLI's own help says it too (cli.py, teach.py)
    "route --rules-path help", "reroute --rules-path help", "teach --rules-path help",
])
def test_each_text_says_inheritance_needs_the_same_topic_and_the_same_bucket(name):
    # The texts describe these two lines of `_inherit_rules_paths`; if
    # either goes, so must the words.
    source = inspect.getsource(verbs._inherit_rules_paths)
    assert "old_path.parent.parent != bucket_dir" in source
    assert 'old_routing.get("rules_topic") != topic' in source
    text = _text_of(name)
    assert "claude-md:rules:" in text or "rules topic" in text or "rules_paths" in text  # control
    assert "inherits" in text  # control: the inheritance sentence is there
    assert "same bucket" in text, name
    assert "for a project lesson, the same project" in text, name
    # the S-75 wording that left the bucket out
    assert "routed to the same topic inherits" not in text, name
