"""The skills index phase S is shown must list every skill on the machine
that Claude Code loads, and a candidate whose ``into`` is not in it must
reach phase B with its reason instead of vanishing.

Found 2026-11-12: the overseer's report said two candidates were dropped
because their ``into`` skills "are not in skills-index.yaml", though both
skills were loaded. The secret scan had matched a commit-hash directory in
one plugin-cache path, and stubbed the WHOLE index, so phase S saw no skill
and the check admitted none. All names here are invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import scan
from self_learn.overseer import discovery
from test_overseer_skill_discovery import (  # noqa: F401  (home is a fixture)
    GOOD, RID_A, RID_B, _candidate, _dump, home,
)

#: A directory name the secret scan reads as high-entropy base64, as a
#: plugin cache's commit-hash folder is.
HASH_DIR = "fbae0eb71f03"


def _skill(folder: Path, description: str = "Use when testing the index.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {folder.name}\ndescription: {description}\n---\nBody.\n", encoding="utf-8"
    )
    return folder


def _writer(workspace: Path, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stage(home: Path, tmp_path: Path) -> tuple[discovery.StagedInputs, dict]:
    workspace = tmp_path / "ws"
    staged = discovery.stage_inputs(home, workspace, _writer, answers=[])
    index = YAML(typ="safe").load((workspace / discovery.SKILLS_INDEX_FILE).read_text(encoding="utf-8"))
    return staged, index


@pytest.fixture
def claude(tmp_path) -> Path:
    return tmp_path / "claude"


def _link_into_hashed_cache(claude: Path, tmp_path: Path, name: str) -> Path:
    """A skill reached through a symlink whose target path holds a commit
    hash, the shape of a skill in the skills root or the plugin cache."""
    real = _skill(tmp_path / "cache" / "market" / "plug" / HASH_DIR / "skills" / name)
    (claude / "skills" / name).symlink_to(real)
    return real


def test_a_skill_behind_a_secret_looking_path_is_still_listed_and_nameable(home, claude, tmp_path):
    real = _link_into_hashed_cache(claude, tmp_path, "sample-owned")
    _skill(claude / "skills" / "sample-plain")
    # Positive control: the scan really matches the path, so the old
    # whole-file stub would have fired here.
    assert scan.scan(str(real)), "the fixture path must trip the scan"

    staged, index = _stage(home, tmp_path)

    assert {"sample-owned", "sample-plain"} <= staged.skill_names
    rows = {row["name"]: row for row in index["skills"]}
    assert "sample-owned" in rows and "sample-plain" in rows
    # Only the matched field is withheld; the rest of the row stays shown.
    assert rows["sample-owned"]["description"] == "Use when testing the index."
    assert "withheld" in str(rows["sample-owned"].get("resolves_to"))
    assert HASH_DIR not in json.dumps(index)


def test_a_root_skill_linked_from_the_claude_dir_is_listed(home, claude, tmp_path):
    # The scaffolded-by-self-learn shape: a plain skill under the skills root,
    # linked into ~/.claude/skills (not in owned-skills.yaml).
    root_skill = _skill(tmp_path / "skills-root" / "plugins" / "sample-scaffolded" / "skills" / "sample-scaffolded")
    (claude / "skills" / "sample-scaffolded").symlink_to(root_skill)

    staged, _index = _stage(home, tmp_path)

    assert "sample-scaffolded" in staged.skill_names


def test_a_skill_claude_code_does_not_load_is_not_offered(home, claude, tmp_path):
    (claude / "skills" / "sample-empty-folder").mkdir(parents=True)  # no SKILL.md
    _skill(claude / "skills" / "sample-switched-off")
    (claude / "settings.json").write_text(
        json.dumps({"skillOverrides": {"sample-switched-off": "off"}}), encoding="utf-8"
    )
    _skill(claude / "skills" / "sample-loaded")  # positive control

    staged, index = _stage(home, tmp_path)

    assert "sample-loaded" in staged.skill_names
    assert "sample-empty-folder" not in staged.skill_names
    assert "sample-switched-off" not in staged.skill_names
    assert any(item["name"] == "sample-switched-off" for item in index["not_loaded"])


def test_a_dropped_into_is_kept_with_its_reason_and_shown_to_phase_b(tmp_path):
    path = tmp_path / discovery.CANDIDATES_FILE
    entry = {k: v for k, v in _candidate("sc-held-one").items() if k != "name"}
    entry["into"] = "sample-missing"
    _dump(path, {"candidates": [_candidate("sc-fine"), entry]})
    inputs = discovery.StagedInputs(
        known_lessons=frozenset({RID_A, RID_B}), skill_names=frozenset({"sample-here"})
    )

    checked = discovery.read_candidates(path, inputs)

    assert checked.valid
    by_id = {c["id"]: c for c in checked.entries}
    assert set(by_id) == {"sc-fine", "sc-held-one"}  # nothing vanished
    assert "held_because" not in by_id["sc-fine"]  # positive control
    assert "sample-missing" in by_id["sc-held-one"]["held_because"]
    assert not checked.drops
    assert any("sc-held-one" in line for line in checked.held)

    phase_s = discovery.PhaseS(discovery.STATE_OK, candidates=checked.entries, notes=checked.held)
    stage = tmp_path / "stage-b"
    discovery.stage_phase_b(stage, phase_s, _writer)
    shown = YAML(typ="safe").load((stage / discovery.CANDIDATES_FILE).read_text(encoding="utf-8"))
    held = [c for c in shown["candidates"] if c["id"] == "sc-held-one"]
    assert held and "not a skill in" in held[0]["held_because"]
    assert "sc-fine" in {c["id"] for c in shown["candidates"]}


def test_an_into_naming_a_listed_skill_is_kept_plain(tmp_path):
    path = tmp_path / discovery.CANDIDATES_FILE
    entry = {k: v for k, v in _candidate("sc-plain-into").items() if k != "name"}
    entry["into"] = "sample-here"
    _dump(path, {"candidates": [entry]})
    inputs = discovery.StagedInputs(
        known_lessons=frozenset({RID_A, RID_B}), skill_names=frozenset({"sample-here"})
    )
    checked = discovery.read_candidates(path, inputs)
    assert [c["id"] for c in checked.entries] == ["sc-plain-into"]
    assert "held_because" not in checked.entries[0] and not checked.held


def test_a_skill_whose_own_name_matches_the_scan_is_not_nameable_but_others_are(home, claude, tmp_path):
    odd = "AKIAIOSFODNN7EXAMPLE"
    assert scan.scan(odd), "the fixture name must trip the scan"
    _skill(claude / "skills" / odd)
    _skill(claude / "skills" / "sample-fine")

    staged, index = _stage(home, tmp_path)

    assert "sample-fine" in staged.skill_names
    assert odd not in staged.skill_names
    assert odd not in json.dumps(index)



def test_a_secret_looking_description_withholds_only_that_field(home, claude, tmp_path):
    description = "Use when token = " + "synthetic-value-only"
    assert scan.scan(description)[0].rule == "credential-assignment"
    _skill(claude / "skills" / "sample-sensitive", description)
    _skill(claude / "skills" / "sample-clean")

    staged, index = _stage(home, tmp_path)

    rows = {row["name"]: row for row in index["skills"]}
    assert {"sample-sensitive", "sample-clean"} <= rows.keys()
    assert {"sample-sensitive", "sample-clean"} <= staged.skill_names
    assert rows["sample-clean"]["description"] == "Use when testing the index."
    assert "withheld" in rows["sample-sensitive"]["description"]
    assert "credential-assignment" in rows["sample-sensitive"]["description"]
    assert description not in json.dumps(index)
    assert not scan.scan((tmp_path / "ws" / discovery.SKILLS_INDEX_FILE).read_text())


def test_registry_metadata_cannot_withhold_the_skills_index(home, claude, tmp_path, monkeypatch):
    from self_learn import skill_registry

    odd = "synthetic" * 7
    assert scan.scan(odd)[0].rule == "high-entropy-base64"
    _skill(claude / "skills" / "sample-clean")
    _skill(claude / "skills" / odd)
    (claude / "settings.json").write_text(
        json.dumps({"skillOverrides": {odd: "off"}}), encoding="utf-8",
    )

    class Registry:
        def live(self):
            return ["sample-clean"]

        def editable(self):
            return self.live()

        def is_registered(self, name):
            return False

        def vetoed_names(self):
            return [odd]

    monkeypatch.setattr(skill_registry, "load", lambda home: Registry())
    staged, index = _stage(home, tmp_path)

    assert "sample-clean" in {row["name"] for row in index["skills"]}
    assert "sample-clean" in staged.skill_names
    assert index["self_learn_owns"] == ["sample-clean"]
    assert "high-entropy-base64" in index["vetoed_names"][0]
    assert any("withheld" in row["name"] for row in index["not_loaded"])
    assert odd not in json.dumps(index)
    assert not scan.scan((tmp_path / "ws" / discovery.SKILLS_INDEX_FILE).read_text())


@pytest.mark.parametrize("unavailable", ["withheld", "missing", "unreadable"])
def test_unavailable_index_uses_machine_roster_for_into(
    home, claude, tmp_path, monkeypatch, unavailable,
):
    _skill(claude / "skills" / "sample-real")
    _skill(claude / "skills" / "sample-disabled")
    (claude / "settings.json").write_text(
        json.dumps({"skillOverrides": {"sample-disabled": "off"}}), encoding="utf-8",
    )
    scanned = discovery._scanned

    def withhold_index(text, where):
        if where == "the skills index":
            return discovery._withheld("high-entropy-base64", where)
        return scanned(text, where)

    monkeypatch.setattr(discovery, "_scanned", withhold_index)
    workspace = tmp_path / "ws"
    staged = discovery.stage_inputs(home, workspace, _writer, answers=[])
    path = workspace / discovery.SKILLS_INDEX_FILE
    assert path.read_text().startswith("withheld:")  # the fallback is exercised
    if unavailable == "missing":
        path.unlink()
    elif unavailable == "unreadable":
        path.write_bytes(b"\xff")
    entries = []
    for ordinal, target in enumerate(("sample-real", "sample-invented", "sample-disabled")):
        entry = {k: v for k, v in _candidate(f"sc-fallback-{ordinal}").items() if k != "name"}
        entry["into"] = target
        entries.append(entry)
    candidates = tmp_path / discovery.CANDIDATES_FILE
    _dump(candidates, {"candidates": entries})

    checked = discovery.read_candidates(candidates, staged)

    assert checked.valid and not checked.drops
    rows = {row["into"]: row for row in checked.entries}
    assert set(rows) == {"sample-real", "sample-invented", "sample-disabled"}
    assert "held_because" not in rows["sample-real"]
    assert "held_because" in rows["sample-invented"]
    assert "held_because" in rows["sample-disabled"]
