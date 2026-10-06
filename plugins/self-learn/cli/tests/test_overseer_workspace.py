"""2026-09-28 -- the overseer's own workspace (batch 0928, unit A).

The user's words: "that should all be stuff it has access to right off the
bat. maybe even have it live in its working directory ... it should have a
'sandbox' ... it can use as a workspace."

Pins: (1) the workspace's formats/ folder exists and every example in it
passes the runner's OWN validators, each with a broken twin that fails; (2)
the charter refuses a read outside the workspace; (3) the worker's stage and
the overseer's workspace no longer overlap (fail-state audit finding 11).
"""

from __future__ import annotations

import asyncio
import copy
import shutil
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import invocation, user_model, worker
from self_learn.invocation_sdk import charter
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from support import make_home


def _load(path: Path):
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _dump(path: Path, data) -> None:
    stream_yaml = YAML()
    with path.open("w", encoding="utf-8") as fh:
        stream_yaml.dump(data, fh)


@pytest.fixture
def formats_dir(tmp_path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    formats.write(workspace, "A")
    return formats.write(workspace, "B")


# ------------------------------------------------------ the formats folder


def test_phase_a_formats_carry_no_case_or_sheet_vocabulary(tmp_path):
    """Phase A is blind to the steward's decisions: its formats hold the
    two phase-A files and nothing about cases, sheets, or verbs."""
    root = formats.write(tmp_path, "A")
    names = sorted(path.name for path in root.iterdir())
    assert names == ["README.md", "closed-sets.yaml", "initial-views.yaml", "selection.yaml"]
    assert set(_load(root / "closed-sets.yaml")) == {"selection", "initial_views"}
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Phase A files" in readme
    assert "sheet" not in readme


def test_phase_b_formats_hold_every_file_the_run_writes(formats_dir):
    names = {path.name for path in formats_dir.iterdir()}
    for required in (*overseer_run.REQUIRED_OUTPUT_FILES, "selection.yaml", "initial-views.yaml",
                     "case-example.yaml", "sheet-example.yaml", "maintenance-case.yaml",
                     "maintenance-sheet.yaml", "closed-sets.yaml", "README.md"):
        assert required in names, required
    sets = _load(formats_dir / "closed-sets.yaml")
    # Read from the enforcing modules, not written by hand.
    assert sets["findings"]["kind"] == list(overseer_run.FINDING_KINDS)
    assert sets["initial_views"]["confidence"] == list(overseer_run.INITIAL_CONFIDENCE)
    assert sets["report_headings_in_order"] == list(overseer_run._REPORT_SECTIONS)
    from self_learn import batch
    assert set(sets["sheet"]["verbs"]) == set(batch.PERMITTED_KEYS) - set(batch.SHEET_VERB_ALIASES)


def test_formats_scan_clean(formats_dir):
    """The whole-stage secret scan walks the workspace: the formats must
    never be the thing that refuses a run."""
    assert overseer_run._secret_files(formats_dir.parent) == []


def test_selection_example_validates(formats_dir):
    data = _load(formats_dir / "selection.yaml")
    assert overseer_run._selected_ids(data, {formats.EXAMPLE_CASE}) == (formats.EXAMPLE_CASE,)
    broken = {**data, "cases": [{"id": formats.EXAMPLE_CASE, "note": "x"}]}
    with pytest.raises(Exception):
        overseer_run._selected_ids(broken, {formats.EXAMPLE_CASE})


def test_initial_views_example_validates(formats_dir, tmp_path):
    path = formats_dir / "initial-views.yaml"
    overseer_run._validate_initial(path, (formats.EXAMPLE_CASE,))
    broken = _load(path)
    broken["cases"][0]["confidence"] = "high"
    bad = tmp_path / "initial-views.yaml"
    _dump(bad, broken)
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._validate_initial(bad, (formats.EXAMPLE_CASE,))


def test_findings_example_validates(formats_dir):
    data = _load(formats_dir / "findings.yaml")
    clean, examined, dropped = overseer_run._validate_findings(data, (formats.EXAMPLE_CASE,))
    assert dropped == [] and examined == (formats.EXAMPLE_CASE,) and len(clean) == 1
    broken = copy.deepcopy(data)
    broken["findings"][0]["kind"] = "looked-at"
    _clean, _examined, dropped = overseer_run._validate_findings(broken, (formats.EXAMPLE_CASE,))
    assert any("kind must be" in line for line in dropped)


def test_questions_example_validates(formats_dir, tmp_path):
    path = formats_dir / "questions.yaml"
    index, dropped = overseer_run._questions(path, {}, {formats.EXAMPLE_CASE})
    assert dropped == [] and len(index["questions"]) == 1
    broken = _load(path)
    broken["questions"][0]["id"] = "Not A Slug"
    bad = tmp_path / "questions.yaml"
    _dump(bad, broken)
    index, dropped = overseer_run._questions(bad, {}, {formats.EXAMPLE_CASE})
    assert index["questions"] == [] and len(dropped) == 1


def test_user_model_delta_example_applies(formats_dir, tmp_path):
    """The example add goes through the same call the runner makes at
    execute time (`user_model.add_entry(home, by="overseer", ...)`)."""
    home = make_home(tmp_path)
    updates = overseer_run._model_updates(formats_dir / "user-model-delta.yaml")
    assert len(updates) == 1
    payload = dict(updates[0])
    assert payload.pop("action") == "add"
    entry_id = user_model.add_entry(home, by="overseer", **payload)
    assert entry_id.startswith("um-")
    broken = {**payload, "container": "B"}
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(home, by="overseer", **broken)


def test_successor_case_example_validates(formats_dir, tmp_path):
    # A kind: resolution successor: the parked-only rule decides it, so the
    # sandbox ledger is never read (S-76 reads it for a reconsider only).
    home = make_home(tmp_path)
    path = formats_dir / "case-example.yaml"
    overseer_run._validate_successor(path, {formats.EXAMPLE_PARKED_CASE}, home)
    assert overseer_run._case_rule_problem(path, "abcd1234") is None
    broken = _load(path)
    broken["decision"]["confidence"] = "high"
    bad = tmp_path / "case-bad.yaml"
    _dump(bad, broken)
    assert overseer_run._case_rule_problem(bad, "abcd1234") is not None
    missing = _load(path)
    del missing["supersedes"]
    _dump(bad, missing)
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._validate_successor(bad, {formats.EXAMPLE_PARKED_CASE}, home)


def test_maintenance_case_example_validates(formats_dir, tmp_path):
    path = formats_dir / "maintenance-case.yaml"
    overseer_run._validate_maintenance_case(path)
    assert overseer_run._case_rule_problem(path, "abcd1234") is None
    broken = _load(path)
    broken["kind"] = "resolution"
    bad = tmp_path / "case.yaml"
    _dump(bad, broken)
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._validate_maintenance_case(bad)


@pytest.mark.parametrize("name", ["sheet-example.yaml", "maintenance-sheet.yaml"])
def test_sheet_examples_load(formats_dir, tmp_path, name):
    home = make_home(tmp_path)
    work = tmp_path / name
    shutil.copy(formats_dir / name, work)  # the loader rewrites what it reads
    sheet = overseer_run._load_sheet_allow_empty(work, home)
    assert sheet is not None and len(sheet) == 1
    broken = _load(formats_dir / name)
    broken["items"][0]["verb"] = "obliterate"
    _dump(work, broken)
    from self_learn import batch
    with pytest.raises(batch.BatchError):
        overseer_run._load_sheet_allow_empty(work, home)


def test_report_example_needs_no_repair(formats_dir, tmp_path):
    work = tmp_path / "report.md"
    shutil.copy(formats_dir / "report.md", work)
    assert overseer_run._repair_report_headings(work) == []
    work.write_text("# r\n## Nonsense\n- none\n", encoding="utf-8")
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._repair_report_headings(work)


# ------------------------------------------------------------ read fence


def _verdict(decide, tool, tool_input) -> str:
    return type(asyncio.run(decide(tool, tool_input, None))).__name__


def test_the_charter_fences_overseer_reads_to_its_workspace(tmp_path):
    workspace = tmp_path / "overseer.workspace" / "overseer"
    (workspace / "formats").mkdir(parents=True)
    outside = tmp_path / "repo" / "src" / "cases.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    containment = invocation.containment_for(
        "overseer", allowed_tools="Read,Grep,Glob,Write,Edit", disallowed_tools="Bash",
        stage_dir=workspace.parent,
    )
    assert containment.write_globs == (f"{workspace}/**",)
    assert containment.read_roots == (f"{workspace}",)
    decide = charter.build_can_use_tool(containment, cwd=workspace)
    allow, deny = "PermissionResultAllow", "PermissionResultDeny"
    # Positive controls: reads inside the workspace pass.
    assert _verdict(decide, "Read", {"file_path": str(workspace / "formats" / "README.md")}) == allow
    assert _verdict(decide, "Grep", {"pattern": "case-"}) == allow
    assert _verdict(decide, "Glob", {"pattern": "blind/*.md"}) == allow
    assert _verdict(decide, "Grep", {"pattern": "x", "path": "formats"}) == allow
    # Outside: refused.
    assert _verdict(decide, "Read", {"file_path": str(outside)}) == deny
    assert _verdict(decide, "Grep", {"pattern": "x", "path": str(outside.parent)}) == deny
    assert _verdict(decide, "Glob", {"pattern": f"{outside.parent}/*.py"}) == deny
    assert _verdict(decide, "Glob", {"pattern": "../repo/**/*.py"}) == deny
    assert _verdict(decide, "Grep", {"pattern": "x", "glob": "../../**"}) == deny
    assert _verdict(decide, "Read", {"file_path": "../repo/src/cases.py"}) == deny


def test_a_symlink_in_the_workspace_cannot_carry_a_read_out(tmp_path):
    workspace = tmp_path / "overseer.workspace" / "overseer"
    workspace.mkdir(parents=True)
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("x", encoding="utf-8")
    (workspace / "link.txt").symlink_to(secret)
    containment = invocation.containment_for("overseer", allowed_tools="Read", stage_dir=workspace.parent)
    decide = charter.build_can_use_tool(containment, cwd=workspace)
    assert _verdict(decide, "Read", {"file_path": str(workspace / "link.txt")}) == "PermissionResultDeny"


def test_the_steward_reads_stay_unfenced(tmp_path):
    """The steward's evidence reads of transcripts are legitimate: its
    containment names no read roots, so a read anywhere is allowed."""
    containment = invocation.containment_for(
        "steward", allowed_tools="Read,Grep,Glob,Write,Edit", disallowed_tools="Bash",
        stage_dir=tmp_path / "run",
    )
    assert containment.read_roots == ()
    decide = charter.build_can_use_tool(containment, cwd=tmp_path / "run")
    assert _verdict(decide, "Read", {"file_path": "/var/tmp/transcript.jsonl"}) == "PermissionResultAllow"


# --------------------------------------- the run uses its own workspace


def _fake_phases(monkeypatch, seen: dict):
    def invoke(spec):
        stage = spec.cwd
        seen.setdefault("cwd", []).append(stage)
        seen.setdefault("containment", []).append(spec.containment)
        seen.setdefault("formats", []).append(
            sorted(path.name for path in (stage / "formats").iterdir())
        )
        seen.setdefault("prompt", []).append(spec.prompt)
        y = YAML()
        if spec.label == "phase-a":
            with (stage / "selection.yaml").open("w", encoding="utf-8") as fh:
                y.dump({"cases": [], "why_these": "none", "why_stopped": "empty"}, fh)
            with (stage / "initial-views.yaml").open("w", encoding="utf-8") as fh:
                y.dump({"cases": []}, fh)
        else:
            (stage / "report.md").write_text(
                "# r\n" + "\n".join(f"## {h}\n- none" for h in overseer_run._REPORT_SECTIONS) + "\n",
                encoding="utf-8",
            )
            for name, data in (
                ("sheet.yaml", {"version": 1, "items": []}),
                ("findings.yaml", {"findings": []}),
                ("questions.yaml", {"questions": []}),
                ("user-model-delta.yaml", {"updates": []}),
            ):
                with (stage / name).open("w", encoding="utf-8") as fh:
                    y.dump(data, fh)
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def test_the_run_works_in_its_own_workspace_with_formats(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    seen: dict = {}
    _fake_phases(monkeypatch, seen)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "dry-run"
    workspace = overseer_run.workspace_dir(home)
    assert seen["cwd"] == [workspace, workspace]
    for containment in seen["containment"]:
        assert containment.write_globs == (f"{workspace}/**",)
        assert containment.read_roots == (f"{workspace}",)
    assert "case-example.yaml" not in seen["formats"][0]
    assert "case-example.yaml" in seen["formats"][1]
    for prompt in seen["prompt"]:
        assert "formats/README.md" in prompt


def test_the_worker_stage_and_the_overseer_workspace_do_not_overlap(tmp_path, monkeypatch):
    """Audit finding 11: `stage_reset` removed the whole worker stage, the
    overseer's folder with it, and the overseer's reset removed a worker's
    batch. Now each reset leaves the other's files alone, both ways."""
    home = make_home(tmp_path)
    workspace = overseer_run.workspace_reset(home)
    stage = worker.stage_dir()
    stage.mkdir(parents=True, exist_ok=True)
    assert workspace != stage
    assert stage not in workspace.parents and workspace not in stage.parents
    (workspace / "journal.md").write_text("overseer", encoding="utf-8")
    (stage / "proposal.md").write_text("worker", encoding="utf-8")
    worker.stage_reset(home)
    assert (workspace / "journal.md").read_text(encoding="utf-8") == "overseer"
    (stage / "proposal.md").write_text("worker", encoding="utf-8")
    overseer_run.workspace_reset(home)
    assert (stage / "proposal.md").read_text(encoding="utf-8") == "worker"
    assert not (workspace / "journal.md").exists()
