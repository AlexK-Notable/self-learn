"""O-3b: overseer user-model delta ownership and restart guards."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

from self_learn import execution_evidence, user_model
from self_learn.overseer import run as overseer_run
from support import commit_all, make_home


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        YAML().dump(value, stream)


def _fake_delta_phases(monkeypatch, updates: list[dict]) -> None:
    calls = []

    def invoke(spec):
        calls.append(spec.label)
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "empty"})
            _dump(stage / "initial-views.yaml", {"cases": []})
        else:
            headings = (
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            )
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {heading}\n- none" for heading in headings) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "sheet.yaml", {"version": 1, "items": []})
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "user-model-delta.yaml", {"updates": updates})
        return type(
            "SdkLike", (),
            {"ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1},
        )()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def _enable(monkeypatch) -> None:
    real = overseer_run.settings.resolve_setting

    def resolve(home, setting):
        if setting.name == "overseer.enabled":
            return True, "test"
        return real(home, setting)

    monkeypatch.setattr(overseer_run.settings, "resolve_setting", resolve)


def test_o3b_phase_b_prompt_names_the_fifth_file_and_provisional_source(tmp_path):
    prompt = overseer_run._phase_b_prompt(tmp_path, (), ())
    assert "user-model-delta.yaml" in prompt
    assert "source: system-reading" in prompt
    assert "action: lapse" in prompt


def test_o3b_valid_add_and_lapse_apply_while_malformed_entry_is_refused(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    old_id = user_model.add_entry(
        home,
        container="D",
        title="Prefers evidence from direct runs",
        because="Repeated local verification choices support this reading",
        source="system-reading",
        by="overseer",
        ref="record:seed",
    )
    updates = [
        {
            "action": "add",
            "container": "D",
            "title": "Prefers concise operational reports",
            "because": "Several observed handoffs favored the core result first",
            "source": "system-reading",
            "ref": "record:lrn-0123abcd",
        },
        {
            "action": "lapse",
            "id": old_id,
            "changed_condition": "Recent work now uses a different evidence workflow",
        },
        {
            "action": "add",
            "container": "D",
            "title": "Invalid source must be refused",
            "because": "The model cannot promote its prose to user evidence",
            "source": "own-words",
            "ref": "stmt-not-actually-user-supplied",
        },
    ]
    _enable(monkeypatch)
    _fake_delta_phases(monkeypatch, updates)

    result = overseer_run.run(home, no_push=True)

    assert (result.status, result.code, result.applied, result.refused) == (
        "partial", 8, 2, 1
    )
    shown = user_model.show(home)
    rows = [row for values in shown["containers"].values() for row in values]
    assert next(row for row in rows if row["id"] == old_id)["status"] == "LAPSED"
    added = next(row for row in rows if row["title"] == "Prefers concise operational reports")
    assert added["source"] == "system-reading"
    assert "updated_by: overseer" in (home / "user-model.md").read_text(encoding="utf-8")

    manifest = json.loads(
        execution_evidence.manifest_path(home, result.run).read_text(encoding="utf-8")
    )
    assert [row["state"] for row in manifest["maintenance"]] == [
        "applied", "applied", "refused"
    ]
    assert all(row["kind"] == "model" for row in manifest["maintenance"])
    report = Path(result.report).read_text(encoding="utf-8")
    assert added["id"] in report
    assert old_id in report
    assert "non-system-reading source" in report


def test_o3b_started_add_is_recovered_without_duplicate(tmp_path):
    """A real SIGKILL after the owner commit must resume from Git truth."""
    home = make_home(tmp_path)
    run_id = "deadbeef"
    payload = {
        "action": "add",
        "container": "D",
        "title": "One durable reading",
        "because": "The first owner commit landed before the process stopped",
        "source": "system-reading",
        "ref": "record:lrn-0123abcd",
    }
    operation = overseer_run._model_operation(payload, ordinal=1)
    operation.update(state="started", baseline=[])
    path = execution_evidence.manifest_path(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "run_id": run_id, "maintenance": [operation]}) + "\n")
    commit_all(home, "self-learn: overseer prepare kill-shaped maintenance")
    barrier = tmp_path / "owner-commit-landed"
    child_cache = Path(os.environ["XDG_CACHE_HOME"]) / "o3b-kill-child"
    child_cache.mkdir(parents=True, exist_ok=True)
    child = r'''import os, signal
from pathlib import Path
from self_learn import user_model
from self_learn.overseer import run

home = Path(os.environ["LEDGER_HOME"])
original = user_model.add_entry
def add_then_die(*args, **kwargs):
    result = original(*args, **kwargs)
    Path(os.environ["BARRIER"]).write_text(result, encoding="utf-8")
    os.kill(os.getpid(), signal.SIGKILL)
user_model.add_entry = add_then_die
run._maintain_manifest(home, "deadbeef")
'''
    env = os.environ.copy()
    env.update(
        LEDGER_HOME=str(home),
        BARRIER=str(barrier),
        XDG_CACHE_HOME=str(child_cache),
    )
    env.pop("SELF_LEARN_ANALYST_MODEL", None)
    env.pop("SELF_LEARN_ANALYST_TIMEOUT", None)
    killed = subprocess.run(
        [sys.executable, "-c", child], env=env, capture_output=True, text=True,
        timeout=30,
    )
    assert killed.returncode == -signal.SIGKILL, (killed.stdout, killed.stderr)
    first_id = barrier.read_text(encoding="utf-8")
    shutil.rmtree(child_cache)

    applied, refused, halted, lines = overseer_run._maintain_manifest(home, run_id)

    assert (applied, refused, halted) == (1, 0, False)
    assert first_id in lines[0]
    rows = [row for values in user_model.show(home)["containers"].values() for row in values]
    assert [row["title"] for row in rows].count("One durable reading") == 1
