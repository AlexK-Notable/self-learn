"""`self-learn teach` (T5): flag paths land valid records in the right
bucket; inference echoes; scan-then-write refusal/redaction; --supersedes
capture half; validation errors echo back and write nothing; --route
deferred to T8.

CLI-level via cli.main (the console entry's target), like test_list_cli.
"""

import json

import pytest

from self_learn import cli
from self_learn.ledger_ops import create_record
from self_learn.records import Record
from self_learn.teach import infer_type

from support import make_behavior, make_home

# 4 + 36 chars — fires the github-token rule (see test_scan.py).
SECRET = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"

DOD_ARGS = [
    "teach",
    "never live-edit HA storage",
    "--skill",
    "home-assistant",
    "--type",
    "behavior",
    "--trigger",
    "About to edit .storage while HA is running.",
    "--instruction",
    "Stop the container first.",
]


@pytest.fixture
def home(monkeypatch, tmp_path):
    h = make_home(tmp_path, skills=("home-assistant",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


def run_cli(argv):
    """cli.main, with argparse's own SystemExit(2) paths normalized."""
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code


def all_pending(home):
    return sorted(home.glob("**/.self-learn/pending/*.md"))


def sole_record(home):
    (path,) = all_pending(home)
    return path, Record.from_path(path)


# ------------------------------------------------------------- happy paths


def test_dod_invocation_lands_conforming_pending_record(home, capsys):
    assert run_cli(DOD_ARGS) == 0
    out = capsys.readouterr().out
    path, rec = sole_record(home)
    bucket = home / "plugins/home-assistant-plugin/skills/home-assistant/.self-learn"
    assert path.parent == bucket / "pending"
    assert rec.type == "behavior"
    assert rec.scope == "skill:home-assistant"
    assert rec.status == "pending"
    assert rec.source == "teach"
    assert rec.kind == "surface-rule"  # defaulted
    assert "## Trigger" in rec.body and "Stop the container first." in rec.body
    # printed: id + path + kind-default echo; --type was explicit → no inference echo
    assert rec.id in out and str(path) in out
    assert "kind: surface-rule (defaulted — pass --kind to override)" in out
    assert "(inferred" not in out


def test_structured_knowledge_project_scope(home, capsys):
    rc = run_cli(
        [
            "teach",
            "--project",
            "--type",
            "knowledge",
            "--fact",
            "The Nova reserves 192.168.1.232.",
            "--context",
            "Router DHCP reservation.",
        ]
    )
    assert rc == 0
    path, rec = sole_record(home)
    assert path.parent == home / ".self-learn" / "pending"
    assert rec.type == "knowledge" and rec.scope == "project"
    assert "## Fact" in rec.body and "## Context" in rec.body


def test_user_scope_bare_text(home):
    rc = run_cli(["teach", "The router UI lives at 192.168.1.254.", "--user"])
    assert rc == 0
    path, rec = sole_record(home)
    assert rec.scope == "user"
    assert path.parent == home / ".self-learn" / "pending"


def test_default_scope_is_project(home):
    assert run_cli(["teach", "The default scope is project."]) == 0
    _, rec = sole_record(home)
    assert rec.scope == "project"


def test_explicit_kind_no_default_echo(home, capsys):
    rc = run_cli(DOD_ARGS + ["--kind", "anti-pattern"])
    assert rc == 0
    assert "(defaulted" not in capsys.readouterr().out
    _, rec = sole_record(home)
    assert rec.kind == "anti-pattern"


def test_record_visible_to_list(home, capsys):
    assert run_cli(DOD_ARGS) == 0
    capsys.readouterr()
    assert cli.main(["list", "--json"]) == 0
    (item,) = json.loads(capsys.readouterr().out)
    assert item["type"] == "behavior" and item["scope"] == "skill:home-assistant"
    assert item["title"] == "About to edit .storage while HA is running."


# ---------------------------------------------------------- type inference


def test_infer_type_heuristic():
    assert infer_type("Never edit .storage while HA is running") == "behavior"
    assert infer_type("when routing, prefer the narrowest surface") == "behavior"
    assert infer_type("Don't run sudo from the Bash tool") == "behavior"
    assert infer_type("The Nova reserves 192.168.1.232.") == "knowledge"
    assert infer_type("HA caches .storage in memory.") == "knowledge"


def test_bare_text_knowledge_inference_echo(home, capsys):
    rc = run_cli(["teach", "HA caches .storage in memory.", "--project"])
    assert rc == 0
    assert "type: knowledge (inferred — pass --type to override)" in capsys.readouterr().out
    _, rec = sole_record(home)
    assert rec.type == "knowledge"
    assert "HA caches .storage in memory." in rec.body


def test_bare_text_behavior_inference_with_trigger(home, capsys):
    rc = run_cli(
        [
            "teach",
            "never edit .storage while HA is running",
            "--skill",
            "home-assistant",
            "--trigger",
            "About to edit a .storage file.",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "type: behavior (inferred — pass --type to override)" in out
    _, rec = sole_record(home)
    assert rec.type == "behavior"
    # positional filled the missing Instruction
    assert "never edit .storage while HA is running" in rec.body


def test_structured_flags_infer_type_with_echo(home, capsys):
    rc = run_cli(
        [
            "teach",
            "--skill",
            "home-assistant",
            "--trigger",
            "About to edit .storage.",
            "--instruction",
            "Stop the container first.",
        ]
    )
    assert rc == 0
    assert "type: behavior (inferred — pass --type to override)" in capsys.readouterr().out
    _, rec = sole_record(home)
    assert rec.type == "behavior"


def test_inferred_behavior_without_trigger_is_usage_error(home, capsys):
    rc = run_cli(["teach", "never run sudo from the Bash tool", "--project"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "type: behavior (inferred" in captured.out  # echo still shown
    assert "--trigger" in captured.err
    assert all_pending(home) == []


# ------------------------------------------------------------ evidence


def test_quote_and_session_land_evidence_entry(home):
    rc = run_cli(
        DOD_ARGS + ["--quote", "stop HA before touching .storage", "--session", "f687d7ce"]
    )
    assert rc == 0
    _, rec = sole_record(home)
    (entry,) = rec.evidence
    assert entry["session"] == "f687d7ce"
    assert entry["quote"] == "stop HA before touching .storage"
    assert entry["ts"]


def test_evidence_session_alias(home):
    rc = run_cli(DOD_ARGS + ["--evidence-session", "f687d7ce"])
    assert rc == 0
    _, rec = sole_record(home)
    (entry,) = rec.evidence
    assert entry["session"] == "f687d7ce"
    assert "quote" not in entry


def test_quote_without_session_is_usage_error(home, capsys):
    rc = run_cli(DOD_ARGS + ["--quote", "some quote"])
    assert rc == 2
    assert "--session" in capsys.readouterr().err
    assert all_pending(home) == []


# ------------------------------------------------------------ secret scan


def test_scan_refusal_writes_nothing_exit_3(home, capsys):
    rc = run_cli(
        [
            "teach",
            "--project",
            "--type",
            "behavior",
            "--trigger",
            "About to push credentials.",
            "--instruction",
            f"use {SECRET} for auth",
        ]
    )
    assert rc == 3
    err = capsys.readouterr().err
    assert "github-token" in err and SECRET in err  # rule + span echoed
    assert all_pending(home) == []


def test_scan_refusal_on_evidence_quote(home, capsys):
    rc = run_cli(DOD_ARGS + ["--quote", SECRET, "--session", "f687d7ce"])
    assert rc == 3
    assert "github-token" in capsys.readouterr().err
    assert all_pending(home) == []


def test_redact_writes_redacted_body_and_flag(home, capsys):
    rc = run_cli(
        [
            "teach",
            "--project",
            "--type",
            "knowledge",
            "--fact",
            f"the CI token was {SECRET} and it leaked",
            "--redact",
        ]
    )
    assert rc == 0
    assert "redacted" in capsys.readouterr().out
    path, rec = sole_record(home)
    text = path.read_text(encoding="utf-8")
    assert SECRET not in text
    assert "[redacted:github-token]" in rec.body
    assert "redacted: true" in text
    assert rec.redacted is True


def test_redact_covers_evidence_quotes(home):
    rc = run_cli(DOD_ARGS + ["--quote", SECRET, "--session", "f687d7ce", "--redact"])
    assert rc == 0
    path, rec = sole_record(home)
    (entry,) = rec.evidence
    assert entry["quote"] == "[redacted:github-token]"
    assert SECRET not in path.read_text(encoding="utf-8")


def test_clean_capture_with_redact_flag_sets_no_frontmatter_flag(home):
    rc = run_cli(DOD_ARGS + ["--redact"])
    assert rc == 0
    path, rec = sole_record(home)
    assert rec.redacted is False
    assert "redacted" not in path.read_text(encoding="utf-8")


# ------------------------------------------------------------ supersedes


def test_supersedes_recorded_old_record_untouched(home, capsys):
    old = make_behavior(scope="skill:home-assistant", record_id="lrn-aa000001")
    old_path = create_record(home, old)
    before = old_path.read_bytes()

    rc = run_cli(
        [
            "teach",
            "HA moved: the old lesson pointed at the wrong port.",
            "--project",
            "--type",
            "knowledge",
            "--supersedes",
            "lrn-aa000001",
        ]
    )
    assert rc == 0
    assert "supersedes lrn-aa000001" in capsys.readouterr().out
    assert old_path.read_bytes() == before  # capture half: old record untouched
    new_paths = [p for p in all_pending(home) if p != old_path]
    (new_path,) = new_paths
    rec = Record.from_path(new_path)
    assert rec.supersedes == "lrn-aa000001"


@pytest.mark.parametrize("bad", ["aa000001", "lrn-XYZ", "lrn-aa00", "lrn-AA000001"])
def test_supersedes_bad_id_format(home, capsys, bad):
    rc = run_cli(["teach", "some fact", "--project", "--supersedes", bad])
    assert rc == 2
    assert bad in capsys.readouterr().err
    assert all_pending(home) == []


# ---------------------------------------------------- validation / errors


def test_type_behavior_without_trigger(home, capsys):
    rc = run_cli(["teach", "x", "--type", "behavior", "--instruction", "do it"])
    assert rc == 2
    assert "--trigger" in capsys.readouterr().err
    assert all_pending(home) == []


def test_behavior_without_instruction_or_lesson(home, capsys):
    rc = run_cli(["teach", "--type", "behavior", "--trigger", "About to X."])
    assert rc == 2
    assert "instruction" in capsys.readouterr().err.lower()
    assert all_pending(home) == []


def test_kind_on_knowledge_rejected(home, capsys):
    rc = run_cli(["teach", "a fact", "--type", "knowledge", "--kind", "anti-pattern"])
    assert rc == 2
    assert "--kind" in capsys.readouterr().err
    assert all_pending(home) == []


def test_trigger_on_knowledge_rejected(home, capsys):
    rc = run_cli(["teach", "a fact", "--type", "knowledge", "--trigger", "t"])
    assert rc == 2
    assert "--trigger" in capsys.readouterr().err
    assert all_pending(home) == []


def test_fact_on_behavior_rejected(home, capsys):
    rc = run_cli(
        ["teach", "--type", "behavior", "--trigger", "t", "--instruction", "i", "--fact", "f"]
    )
    assert rc == 2
    assert "--fact" in capsys.readouterr().err
    assert all_pending(home) == []


def test_mixed_structured_families_rejected(home, capsys):
    rc = run_cli(["teach", "--trigger", "t", "--fact", "f"])
    assert rc == 2
    assert all_pending(home) == []


def test_two_lesson_body_rejected(home, capsys):
    rc = run_cli(
        ["teach", "--project", "--type", "knowledge", "--fact", "first\n## Fact\nsecond"]
    )
    assert rc == 2
    assert "duplicate" in capsys.readouterr().err.lower()
    assert all_pending(home) == []


def test_nothing_to_capture(home, capsys):
    rc = run_cli(["teach"])
    assert rc == 2
    assert all_pending(home) == []


def test_unknown_skill_errors_and_writes_nothing(home, capsys):
    rc = run_cli(["teach", "a fact", "--skill", "nope", "--type", "knowledge"])
    assert rc == 2
    assert "nope" in capsys.readouterr().err
    assert all_pending(home) == []


def test_unrecognized_flag_rejected(home, capsys):
    rc = run_cli(["teach", "a fact", "--bogus"])
    assert rc == 64
    assert "--bogus" in capsys.readouterr().err
    assert all_pending(home) == []


def test_conflicting_scope_flags_rejected(home, capsys):
    rc = run_cli(["teach", "a fact", "--project", "--user"])
    assert rc == 2
    assert all_pending(home) == []


def test_bad_kind_value_rejected(home, capsys):
    rc = run_cli(DOD_ARGS + ["--kind", "bogus-kind"])
    assert rc == 2
    assert all_pending(home) == []


# ------------------------------------------- --route flag family (T8 gate)
# The live --route paths are covered in test_route_cli.py; here: the
# route-only flags without --route are usage errors, nothing written.


@pytest.mark.parametrize(
    "extra",
    [["--dest", "skill-md"], ["--note", "why"], ["--no-push"]],
)
def test_route_family_flags_need_route(home, capsys, extra):
    rc = run_cli(DOD_ARGS + extra)
    assert rc == 2
    assert "needs --route" in capsys.readouterr().err
    assert all_pending(home) == []


def test_route_bad_dest_is_usage_error(home, capsys):
    rc = run_cli(DOD_ARGS + ["--route", "--dest", "bogus"])
    assert rc == 2
    assert "--dest must be one of" in capsys.readouterr().err
    assert all_pending(home) == []
