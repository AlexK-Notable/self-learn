"""SK3 -- the overseer builds, changes and retires the skills self-learn
owns, in phase B (skill-writing plan §2 steps 4, 7 and 10, D4, D10, §4.1
row SK3 tests (a)-(f); ``03-decisions.md`` S-107 parts 4-6, with
``overseer.skill_writing`` taking auto|on|off, default auto).

Every run here is scripted: the model is the fake ``write_session``
(phase A selects nothing; phase B writes the files each test names), and
the scratch environment is ``test_skill_write``'s (a ledger, a git-mode
skills root with a marketplace, a scratch ``~/.claude``, scratch HOME and
XDG cache). No real model is called.

Red on master: ``self_learn.overseer.skills`` and ``self_learn.skill_writer``
do not exist there, so every test here fails at import.
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path

import pytest
from ruamel.yaml import YAML

import test_skill_write as sk1
from self_learn import batch, cases, scan, settings, skill_registry, skill_writer, verbs
from self_learn.compilers import BEGIN_MARKER
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import discovery, formats, skills
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from self_learn.skill_scaffold import SKILL_FRONTMATTER_ALLOWED_KEYS, SKILL_NAME_MAX_CHARS, check_skill
from support import commit_all, git, make_behavior

NAME = sk1.NAME
RID = "lrn-0000c001"
RID2 = "lrn-0000c002"
RID3 = "lrn-0000c003"
HEADINGS = (
    "Examined", "Decided in the user's stead", "Hooks", "User model",
    "Catalogue health", "Questions for you", "Refused / could not do",
)


# ------------------------------------------------------------------ helpers


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    YAML().dump(data, stream)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _load(path: Path):
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path, monkeypatch) -> sk1.Env:
    environment = sk1.Env(tmp_path, monkeypatch)
    real = settings.resolve_setting

    def resolve(home, setting):
        if setting.name == "overseer.enabled":
            return True, "test"
        return real(home, setting)

    monkeypatch.setattr(settings, "resolve_setting", resolve)
    return environment


def _set_writing(env: sk1.Env, value: str | None) -> None:
    """Write ``overseer.skill_writing`` into the SCRATCH ledger's
    config.yaml (a test fixture; never a real config)."""
    path = env.home / "config.yaml"
    if value is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(f"overseer:\n  skill_writing: {value}\n", encoding="utf-8")
    if git(env.home, "status", "--porcelain").stdout:
        commit_all(env.home, "test: skill_writing")


def _lesson(env: sk1.Env, rid: str) -> None:
    create_record(env.home, make_behavior(scope="skill:s", record_id=rid))
    commit_all(env.home, f"seed {rid}")


def _status(env: sk1.Env, rid: str) -> str:
    return Record.from_path(find_record_path(env.home, rid)).status


def _case(rids, *, name=NAME, kind="maintenance", outcome="route", supersedes=None, lessons=None):
    data = {
        "kind": kind, "trigger": "weekly", "outcome": outcome, "records": list(rids),
        "scope": "skill:s", "question": "Should these lessons live in one skill?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"} for rid in rids],
        "decision": {
            "verb": outcome, "because": "they are steps of one task", "confidence": "settled",
            "skill": {
                "name": name, "why": "one task-shaped trigger",
                "lessons": list(lessons if lessons is not None else rids),
            },
        },
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    return data


def _route_sheet(rids, name=NAME):
    return {"version": 1, "items": [
        {"id": rid, "verb": "route", "dest": f"new-skill:{name}"} for rid in rids
    ]}


def _write_folder(stage: Path, name: str, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = stage / skills.STAGE_SKILLS_DIR / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _phases(monkeypatch, write_b, *, seen: dict | None = None):
    """The fake model: phase A selects nothing; phase B writes the four
    required files, then whatever *write_b(stage)* writes. With no pair
    it writes an empty ``sheet.yaml``."""
    calls = []

    def invoke(spec):
        calls.append(spec)
        stage = spec.cwd
        if spec.label == "phase-s":
            # SK4 (2026-10-31): skill discovery, in its own workspace, finds
            # nothing; phase B's skill steps are what these tests drive.
            _dump(stage / discovery.CANDIDATES_FILE, {"candidates": []})
            return type("SdkLike", (), {
                "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
            })()
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "none"})
            _dump(stage / "initial-views.yaml", {"cases": []})
        else:
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {h}\n- none" for h in HEADINGS) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            if seen is not None:
                seen["stage"] = {
                    p.relative_to(stage).as_posix(): p.read_text(encoding="utf-8")
                    for p in stage.rglob("*") if p.is_file()
                }
                seen["secret_files"] = overseer_run._secret_files(stage)
            write_b(stage)
            if not any(stage.glob("sheet-*.yaml")) and not (stage / "sheet.yaml").exists():
                _dump(stage / "sheet.yaml", {"version": 1, "items": []})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return calls


def _run(env: sk1.Env, **kwargs):
    kwargs.setdefault("no_push", True)
    kwargs.setdefault("manual", True)
    return overseer_run.run(env.home, **kwargs)


def _report(result) -> str:
    return Path(result.report).read_text(encoding="utf-8")


def _section(report: str, heading: str) -> str:
    start = report.index(f"## {heading}")
    end = report.find("\n## ", start + 1)
    return report[start:] if end == -1 else report[start:end]


def _week() -> str:
    return overseer_run.week_key(overseer_run.week_boundary(time.time()))


def _build_b(rids, *, files=None, name=NAME):
    def write_b(stage: Path) -> None:
        _write_folder(stage, name, files if files is not None else sk1.draft(name))
        _dump(stage / "case-build.yaml", _case(rids, name=name))
        _dump(stage / "sheet-build.yaml", _route_sheet(rids, name))
    return write_b


# ===================================================== writing on/off: reading


def test_skill_writing_defaults_to_auto_and_reads_its_three_values(env):
    assert skills.writing_mode(env.home) == ("auto", None)
    for value in ("auto", "on", "off"):
        _set_writing(env, f'"{value}"')
        assert skills.writing_mode(env.home) == (value, None)


@pytest.mark.parametrize("raw", ["false", "true", "maybe", "null", "1"])
def test_any_other_value_reads_as_off_with_a_note(env, raw):
    """S-107 part 6: a mistyped rollback fails closed -- a YAML
    boolean included, which the generic resolver would read as the
    default (``auto``)."""
    _set_writing(env, raw)
    mode, note = skills.writing_mode(env.home)
    assert mode == "off"
    assert note is not None and "reads as off" in note
    assert skills.writing_state(env.home).deploy is False


def test_auto_deploys_only_once_the_trial_file_exists(env):
    state = skills.writing_state(env.home)
    assert state.mode == "auto" and not state.deploy and not state.trial_done
    path = skills.trial_path(env.home)
    path.parent.mkdir(parents=True)
    path.write_text("week: x\n", encoding="utf-8")
    state = skills.writing_state(env.home)
    assert state.deploy and state.trial_done
    _set_writing(env, '"off"')
    assert not skills.writing_state(env.home).deploy  # off wins over the trial
    _set_writing(env, '"on"')
    path.unlink()
    assert skills.writing_state(env.home).deploy  # on needs no trial


def test_the_setting_is_tier_c_config_only_with_no_override_and_refuses_other_values(
    env, monkeypatch,
):
    setting = settings.by_name("overseer.skill_writing")
    assert setting.default == "auto" and setting.tier == "C"
    assert setting.env_var is None and setting.override_channel is False
    assert (setting.config_section, setting.config_key) == ("overseer", "skill_writing")
    settings.config_set(env.home, "overseer.skill_writing", "off")  # control: a person may
    assert skills.writing_mode(env.home) == ("off", None)
    with pytest.raises(settings.SettingsError):
        settings.config_set(env.home, "overseer.skill_writing", "maybe")
    monkeypatch.setenv("CODEX_THREAD_ID", "synthetic")
    with pytest.raises(settings.AgentSettingRefusal):
        settings.config_set(env.home, "overseer.skill_writing", "on")
    assert skills.writing_mode(env.home) == ("off", None)


# ========================================================= (a) writing on


def test_a_writing_on_a_folder_and_its_pair_deploy_the_skill_and_move_the_lessons(
    env, monkeypatch,
):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _lesson(env, RID2)
    _phases(monkeypatch, _build_b([RID, RID2]))

    result = _run(env)

    assert result.status == "applied", _report(result)
    row = env.row()
    assert row is not None and row["status"] == "live"
    assert row["created"]["by"] == "overseer"
    case_id = row["created"]["case"]
    assert cases.show(env.home, case_id).frontmatter["kind"] == "maintenance"  # the pair's case
    text = env.skill_md().read_text(encoding="utf-8")
    assert BEGIN_MARKER in text and f"({RID})" in text and f"({RID2})" in text
    assert env.link().is_symlink() and env.link().resolve() == env.skill_dir().resolve()
    assert _status(env, RID) == "routed" and _status(env, RID2) == "routed"
    decided = _section(_report(result), "Decided in the user's stead")
    assert f"[new skill] {NAME}" in decided and case_id in decided
    assert not (env.home / skills.LEDGER_DIR).exists()  # nothing drafted


def test_a_the_write_comes_before_the_case_and_the_sheet(env, monkeypatch):
    """§2 step 4: the runner applies `skill write` first."""
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    order: list[str] = []
    real_write, real_record = skill_writer.write, cases.record

    def write(*args, **kwargs):
        order.append("write")
        return real_write(*args, **kwargs)

    def record(*args, **kwargs):
        order.append("record")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(skill_writer, "write", write)
    monkeypatch.setattr(cases, "record", record)

    assert _run(env).status == "applied"
    assert order[:2] == ["write", "record"]


# ============================================ (b) a refused folder drops the pair


def test_b_a_template_breaking_folder_drops_its_pair_and_moves_no_lesson(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    bad = sk1.draft()
    bad["SKILL.md"] = bad["SKILL.md"].replace(
        f"name: {NAME}\n", f"name: {NAME}\nallowed-tools: Bash\n", 1
    )
    assert "allowed-tools" in bad["SKILL.md"]  # control: the break is in the draft
    _phases(monkeypatch, _build_b([RID], files=bad))
    before_cases = {row["case"] for row in cases.list_cases(env.home)}

    result = _run(env)

    assert result.status != "refused"  # one pair, not the run
    assert _status(env, RID) == "pending"
    assert not env.plugin_dir().exists() and not env.link().exists()
    assert env.row() is None
    assert {row["case"] for row in cases.list_cases(env.home)} == before_cases
    refused = _section(_report(result), "Refused / could not do")
    assert "case-build.yaml" in refused and "frontmatter-key-refused" in refused
    assert "[new skill]" not in _report(result)


def test_b_control_the_same_pair_with_a_valid_folder_applies(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    result = _run(env)
    assert _status(env, RID) == "routed"
    assert "[new skill]" in _report(result)


def test_b_a_new_skill_named_with_no_folder_drops_its_pair(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)

    def write_b(stage):
        _dump(stage / "case-build.yaml", _case([RID]))
        _dump(stage / "sheet-build.yaml", _route_sheet([RID]))

    _phases(monkeypatch, write_b)
    result = _run(env)
    assert _status(env, RID) == "pending"
    assert "no skills/" in _section(_report(result), "Refused / could not do")


def test_b_a_folder_no_case_names_is_not_written_and_is_named(env, monkeypatch):
    _set_writing(env, '"on"')
    _phases(monkeypatch, lambda stage: _write_folder(stage, "orphan-skill", sk1.draft("orphan-skill")))
    result = _run(env)
    assert result.status != "refused"
    assert not (env.root / "plugins" / "orphan-skill").exists()
    refused = _section(_report(result), "Refused / could not do")
    assert "skills/orphan-skill/: not written" in refused


def test_b_a_secret_in_a_skill_folder_costs_its_pair_not_the_run(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    files = sk1.draft()
    files[sk1.REF] += "token = ghp_abcdefghijklmnopqrstuvwxyz123456\n"
    _phases(monkeypatch, _build_b([RID], files=files))
    result = _run(env)
    assert result.status != "refused"
    assert _status(env, RID) == "pending" and env.row() is None
    assert "secret scan" in _section(_report(result), "Refused / could not do")


# =========================================== (c) writing not in effect: drafts


@pytest.mark.parametrize("value, line", [
    (None, "the drafts-only week is still to come"),
    ('"off"', "skill writing is off"),
])
def test_c_writing_not_in_effect_commits_a_draft_and_deploys_nothing(env, monkeypatch, value, line):
    _set_writing(env, value)
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))

    result = _run(env)

    assert result.status == "applied", _report(result)
    draft_md = skills.drafts_dir(env.home, _week(), NAME) / "SKILL.md"
    assert draft_md.is_file()
    assert git(env.home, "ls-files", "--error-unmatch", str(draft_md)).returncode == 0
    assert not git(env.home, "status", "--porcelain", "--", str(draft_md)).stdout
    assert (draft_md.parent / sk1.REF).is_file()
    # nothing deployed, no lesson moved, no case recorded for the pair
    assert not env.plugin_dir().exists() and not env.link().exists()
    assert env.row() is None
    assert _status(env, RID) == "pending"
    decided = _section(_report(result), "Decided in the user's stead")
    assert f"[skill drafted] {NAME}: would build it" in decided
    assert line in decided
    # this branch has no phase S, so no run is the trial (fail closed)
    assert not skills.trial_path(env.home).exists()


def test_c_a_dry_run_writes_no_draft(env, monkeypatch):
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    result = _run(env, dry_run=True)
    assert result.status == "dry-run"
    assert not (env.home / skills.LEDGER_DIR).exists()


# ============================================================ the trial


def test_the_first_ready_completed_run_records_the_trial_and_the_next_writes(env, monkeypatch):
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    monkeypatch.setattr(discovery, "trial_readiness", lambda *args: (True, ""))

    first = _run(env)

    trial = skills.trial_path(env.home)
    assert trial.is_file()
    data = _load(trial)
    assert set(data) == {"week", "run", "completed_at", "drafts"}
    assert data["run"] == first.run and data["drafts"] == [NAME] and data["week"] == _week()
    # written in the commit that completes the run
    subject = git(env.home, "log", "-1", "--format=%s", "--", str(trial)).stdout.strip()
    assert subject == f"self-learn: overseer finalize {first.run}"
    assert "this was the drafts-only week" in _report(first)
    assert env.row() is None and _status(env, RID) == "pending"

    second = _run(env)  # auto, the trial done: this run writes

    assert env.row() is not None and env.row()["status"] == "live"
    assert _status(env, RID) == "routed"
    assert f"[new skill] {NAME}" in _report(second)
    assert _load(trial)["run"] == first.run  # written once, never rewritten


def test_a_run_not_ready_never_records_the_trial(env, monkeypatch):
    """Control for the test above: the same run with the shipped
    readiness leaves auto drafts-only (phase B here writes no
    skill-dispositions.yaml, so the discovery steps were not seen working;
    SK4, 2026-10-31)."""
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    _run(env)
    assert not skills.trial_path(env.home).exists()
    _run(env)
    assert env.row() is None and _status(env, RID) == "pending"


def test_an_off_run_with_a_ready_discovery_also_records_the_trial(env, monkeypatch):
    """The trial is written while writing is not in effect -- under off
    too -- and off still writes nothing after it."""
    _set_writing(env, '"off"')
    _phases(monkeypatch, lambda stage: None)
    monkeypatch.setattr(discovery, "trial_readiness", lambda *args: (True, ""))
    _run(env)
    assert _load(skills.trial_path(env.home))["drafts"] == []
    assert not skills.writing_state(env.home).deploy


def test_a_dry_run_never_records_the_trial(env, monkeypatch):
    _phases(monkeypatch, lambda stage: None)
    monkeypatch.setattr(discovery, "trial_readiness", lambda *args: (True, ""))
    _run(env, dry_run=True)
    assert not skills.trial_path(env.home).exists()


# ============================================= (d) a skill changed by hand


def _person_edits(env: sk1.Env, line: str) -> None:
    path = env.skill_md()
    text = path.read_text(encoding="utf-8")
    at = text.index(BEGIN_MARKER)
    path.write_text(text[:at] + line + "\n\n" + text[at:], encoding="utf-8")
    commit_all(env.root, "a person edits the skill")


def test_d_the_stage_shows_an_owned_skill_and_the_diff_of_a_hand_edit(env, monkeypatch):
    _set_writing(env, '"on"')
    assert env.write().ok  # self-learn's own skill (by: overseer, case CASE)
    _person_edits(env, "A person's own note about mouse care.")
    seen: dict = {}
    _phases(monkeypatch, lambda stage: None, seen=seen)

    _run(env)

    stage = seen["stage"]
    base = f"{skills.OWNED_DIR}/{NAME}"
    assert f"{base}/{skills.FILES_DIR}/SKILL.md" in stage  # positive control
    shown = stage[f"{base}/{skills.FILES_DIR}/SKILL.md"]
    assert "A person's own note" in shown
    assert BEGIN_MARKER not in shown and "self-learn:" not in shown  # no section, no stamp
    assert f"{base}/{skills.FILES_DIR}/{sk1.REF}" in stage
    diff = stage[f"{base}/{skills.DIFF_FILE}"]
    assert "+A person's own note about mouse care." in diff
    row = YAML(typ="safe").load(stage[f"{base}/{skills.ROW_FILE}"])
    assert row["changed_since_last_write"] is True
    assert row["row"]["created"]["case"] == sk1.CASE
    assert not re.search(r"[0-9a-f]{48,}", stage[f"{base}/{skills.ROW_FILE}"])
    assert YAML(typ="safe").load(stage[f"{base}/{skills.LESSONS_FILE}"]) == {"lessons": []}
    assert skills.WRITING_FILE in stage and skills.VETOES_FILE in stage
    assert skills.PROPOSALS_FILE in stage
    assert seen["secret_files"] == []  # the whole-stage scan never refuses for these


def test_d_an_unchanged_skill_says_so(env, monkeypatch):
    assert env.write().ok
    seen: dict = {}
    _phases(monkeypatch, lambda stage: None, seen=seen)
    _run(env)
    diff = seen["stage"][f"{skills.OWNED_DIR}/{NAME}/{skills.DIFF_FILE}"]
    assert diff.startswith("# Unchanged")


def _rewrite_b(extra: str, *, edit_during=None, env=None):
    """Phase B rewrites the owned skill from what it was shown, in a
    sheetless pair (only the text changes)."""
    def write_b(stage: Path) -> None:
        shown = stage / skills.OWNED_DIR / NAME / skills.FILES_DIR
        files = {
            p.relative_to(shown).as_posix(): p.read_text(encoding="utf-8")
            for p in shown.rglob("*") if p.is_file()
        }
        files["SKILL.md"] = files["SKILL.md"].rstrip() + "\n\n" + extra + "\n"
        _write_folder(stage, NAME, files)
        _dump(stage / "case-change.yaml", _case([RID], outcome="no-action", lessons=[]))
        _dump(stage / "sheet-change.yaml", {"version": 1, "items": []})
        if edit_during is not None:
            edit_during()
    return write_b


def test_d_control_a_rewrite_of_an_owned_skill_applies_from_an_empty_sheet(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    assert env.write().ok
    _phases(monkeypatch, _rewrite_b("The rewritten closing line."))

    result = _run(env)

    assert "The rewritten closing line." in env.skill_md().read_text(encoding="utf-8")
    row = env.row()
    assert row["last_write"]["case"] != sk1.CASE and row["created"]["case"] == sk1.CASE
    # `cases.show` defaults to the blind view, which leaves `outcome` out
    # (cases._BLIND_FRONTMATTER_ALLOW); the full view carries it.
    shown = cases.show(env.home, row["last_write"]["case"], evidence_only=False)
    assert shown.frontmatter["outcome"] == "no-action"
    assert f"[skill changed] {NAME}" in _section(_report(result), "Decided in the user's stead")


def test_d_a_skill_changed_after_it_was_staged_refuses_the_write(env, monkeypatch):
    """D4: the write carries the hash phase B was shown; a person's edit
    made after staging refuses it (target-busy) and is never overwritten."""
    _set_writing(env, '"on"')
    _lesson(env, RID)
    assert env.write().ok
    recorded = env.row()["last_write"]

    def person_edits():
        _person_edits(env, "Written by a person while the overseer ran.")

    _phases(monkeypatch, _rewrite_b("The rewritten closing line.", edit_during=person_edits))

    result = _run(env)

    text = env.skill_md().read_text(encoding="utf-8")
    assert "Written by a person while the overseer ran." in text
    assert "The rewritten closing line." not in text
    assert env.row()["last_write"] == recorded
    refused = _section(_report(result), "Refused / could not do")
    assert "case-change.yaml" in refused and "target-busy" in refused
    assert "[skill changed]" not in _report(result)


SCANNED_LINE = "token = placeholder-the-secret-scan-matches"


def test_d_a_skill_whose_text_matched_the_secret_scan_is_stubbed_and_not_rewritten(
    env, monkeypatch,
):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    assert env.write().ok
    # `key = ghp_<32 characters>` (this test's first fixture) matched no
    # rule: `github-token` wants 36+ characters after `ghp_`, and `key` is
    # not a credential-assignment keyword. `token = <8+ characters>` is.
    assert scan.scan(SCANNED_LINE)  # positive control: the scan matches it
    _person_edits(env, SCANNED_LINE)
    seen: dict = {}
    _phases(monkeypatch, _rewrite_b("The rewritten closing line."), seen=seen)

    result = _run(env)

    shown = seen["stage"][f"{skills.OWNED_DIR}/{NAME}/{skills.FILES_DIR}/SKILL.md"]
    assert shown.startswith("withheld: the secret scan matched")
    assert seen["secret_files"] == []
    assert result.status != "refused"
    assert SCANNED_LINE in env.skill_md().read_text(encoding="utf-8")
    assert "cannot be rewritten this run" in _section(_report(result), "Refused / could not do")


# ================================================= (e) retiring a skill


def test_e_a_retire_pair_moves_the_lessons_out_first_then_retires(env, monkeypatch):
    _set_writing(env, '"on"')
    assert env.write().ok
    _lesson(env, RID)
    verbs.route(env.home, RID, dest=f"new-skill:{NAME}", no_push=True)
    _lesson(env, RID2)
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]  # control

    def write_b(stage):
        _dump(stage / "case-retire.yaml", _case([RID, RID2], outcome="retire", lessons=[RID]))
        _dump(stage / "sheet-retire.yaml", {"version": 1, "items": [
            {"id": RID, "verb": "supersede", "new_id": RID2},
        ]})

    _phases(monkeypatch, write_b)
    routed_at_retire: list = []
    real_retire = skill_writer.retire

    def retire(home, name, **kwargs):
        routed_at_retire.append(skill_writer.routed_lessons(home, name))
        return real_retire(home, name, **kwargs)

    monkeypatch.setattr(skill_writer, "retire", retire)

    result = _run(env)

    assert routed_at_retire == [[]]  # the sheet ran first
    assert env.row()["status"] == "retired"
    assert not env.plugin_dir().exists() and not env.link().exists()
    assert f"[skill retired] {NAME}" in _section(_report(result), "Decided in the user's stead")


def test_e_a_skill_with_no_lesson_left_is_retired_by_a_sheetless_pair(env, monkeypatch):
    _set_writing(env, '"on"')
    assert env.write().ok
    _lesson(env, RID)

    def write_b(stage):
        _dump(stage / "case-retire.yaml", _case([RID], outcome="retire", lessons=[]))
        _dump(stage / "sheet-retire.yaml", {"version": 1, "items": []})

    _phases(monkeypatch, write_b)
    result = _run(env)
    assert env.row()["status"] == "retired"
    assert "[skill retired]" in _report(result)


def test_e_a_new_skill_pair_may_not_have_an_empty_sheet(env, monkeypatch):
    """Control for the sheetless rule: only a change or a retirement may
    move no lesson."""
    _set_writing(env, '"on"')
    _lesson(env, RID)

    def write_b(stage):
        _write_folder(stage, NAME, sk1.draft())
        _dump(stage / "case-build.yaml", _case([RID]))
        _dump(stage / "sheet-build.yaml", {"version": 1, "items": []})

    _phases(monkeypatch, write_b)
    result = _run(env)
    assert env.row() is None
    assert "needs a non-empty sheet" in _section(_report(result), "Refused / could not do")


def test_e_a_retirement_whose_sheet_did_not_apply_whole_leaves_the_skill_live(env, monkeypatch):
    step = skills.SkillStep(action="retire", name=NAME, updating=True)
    recipe = {"case_name": "case-retire.yaml", "skill": step.to_json()}
    refused_item = batch.ItemResult(n=1, id=RID, verb="supersede", rc=1, state="refused")
    result = batch.BatchResult(items=[refused_item], process_code=1)

    def never(*args, **kwargs):
        pytest.fail("a skill is retired only after its sheet moved every lesson out")

    monkeypatch.setattr(skill_writer, "retire", never)
    refusals: list[str] = []
    overseer_run._apply_skill_retire(env.home, "abcd1234", "case-1a2b3c4d", recipe, result, refusals, [])
    assert recipe["skill"]["state"] == "refused"
    assert refusals and "not retired" in refusals[0]
    # a sheet that STOPPED leaves the step for the resume, unrefused
    recipe2 = {"case_name": "case-retire.yaml", "skill": step.to_json()}
    stopped = batch.BatchResult(
        items=[batch.ItemResult(n=1, id=RID, verb="supersede", rc=6, state="stopped")],
        process_code=6,
    )
    overseer_run._apply_skill_retire(env.home, "abcd1234", "case-1a2b3c4d", recipe2, stopped, [], [])
    assert "state" not in recipe2["skill"]


def test_e_retiring_a_skill_self_learn_does_not_own_drops_the_pair(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _phases(monkeypatch, lambda stage: (
        _dump(stage / "case-retire.yaml", _case([RID], outcome="retire", name="s", lessons=[])),
        _dump(stage / "sheet-retire.yaml", {"version": 1, "items": []}),
    ))
    result = _run(env)
    assert "not a skill self-learn owns" in _section(_report(result), "Refused / could not do")


# ================================================ vetoes and proposals staged


def test_the_vetoes_are_staged_for_phase_b(env, monkeypatch):
    assert env.write().ok
    env.veto(NAME)
    env.veto("never-again")
    seen: dict = {}
    _phases(monkeypatch, lambda stage: None, seen=seen)
    _run(env)
    vetoes = YAML(typ="safe").load(seen["stage"][skills.VETOES_FILE])
    assert {v["name"] for v in vetoes["vetoed"]} == {NAME, "never-again"}
    assert [r["name"] for r in vetoes["renames_owed"]] == [NAME]
    assert vetoes["retire_requests"] == []


def test_a_vetoed_live_skill_cannot_be_rewritten_under_its_name(env, monkeypatch):
    _set_writing(env, '"on"')
    _lesson(env, RID)
    assert env.write().ok
    env.veto(NAME)
    _phases(monkeypatch, _rewrite_b("The rewritten closing line."))
    result = _run(env)
    assert "The rewritten closing line." not in env.skill_md().read_text(encoding="utf-8")
    assert "name-vetoed" in _section(_report(result), "Refused / could not do")


# ============================================================ (f) control


def test_f_control_a_run_with_no_skills_output_is_unchanged(env, monkeypatch):
    _set_writing(env, '"on"')
    _phases(monkeypatch, lambda stage: None)
    result = _run(env)
    assert result.status == "applied"
    report = _report(result)
    assert "## Decided in the user's stead" in report  # positive control: the section rendered
    assert not skill_registry.registry_path(env.home).exists()
    assert not (env.home / skills.LEDGER_DIR).exists()
    assert "[new skill]" not in report and "[skill " not in report
    assert "skill writing" not in report
    assert not env.plugin_dir().exists() and not env.link().exists()


# ================================================================ formats


@pytest.fixture
def formats_dir(tmp_path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    formats.write(workspace, "A")
    return formats.write(workspace, "B")


def test_the_skill_example_passes_the_template_check(formats_dir):
    folder = formats_dir / formats.SKILL_EXAMPLE_DIR
    files = {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
             for p in folder.rglob("*") if p.is_file()}
    assert set(files) == {"SKILL.md", formats.EXAMPLE_SKILL_REFERENCE}
    result = check_skill(files, loaded_names=[], vetoed_names=[], expected_name=formats.EXAMPLE_SKILL)
    assert result.ok, result.problems
    broken = dict(files)
    broken["SKILL.md"] = broken["SKILL.md"].replace("description:", "allowed-tools: Bash\ndescription:", 1)
    assert not check_skill(broken, loaded_names=[], vetoed_names=[],
                           expected_name=formats.EXAMPLE_SKILL).ok


def test_the_skill_pair_examples_validate(formats_dir, tmp_path):
    from support import make_home

    home = make_home(tmp_path)
    build = formats_dir / "case-skill-example.yaml"
    overseer_run._validate_maintenance_case(build)
    assert overseer_run._case_rule_problem(build, "abcd1234") is None
    assert skills.claimed_name(_load(build)) == formats.EXAMPLE_SKILL
    retire = formats_dir / "case-skill-retire-example.yaml"
    assert overseer_run._case_rule_problem(retire, "abcd1234") is None
    assert _load(retire)["outcome"] == "retire"
    for name in ("sheet-skill-example.yaml", "sheet-skill-retire-example.yaml"):
        work = tmp_path / name
        work.write_text((formats_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
        sheet = overseer_run._load_sheet_allow_empty(work, home)
        assert sheet is not None and len(sheet) == 2
    assert overseer_run._secret_files(formats_dir.parent) == []


def test_the_readme_carries_the_skills_section_for_phase_b_only(formats_dir, tmp_path):
    readme = (formats_dir / "README.md").read_text(encoding="utf-8")
    assert "## Skills self-learn owns" in readme
    assert f"at most {SKILL_NAME_MAX_CHARS} characters" in readme
    for name in (skills.OWNED_DIR, skills.VETOES_FILE, skills.PROPOSALS_FILE, skills.WRITING_FILE):
        assert name in readme
    sets = _load(formats_dir / "closed-sets.yaml")
    assert sets["skill_template"]["frontmatter_keys_allowed"] == list(SKILL_FRONTMATTER_ALLOWED_KEYS)
    phase_a = formats.write(tmp_path / "a-only", "A")
    assert "Skills self-learn owns" not in (phase_a / "README.md").read_text(encoding="utf-8")


def test_the_phase_b_prompt_points_at_the_skills_section(tmp_path):
    prompt = overseer_run._phase_b_prompt(tmp_path, (), ())
    assert '"Skills self-learn owns" section' in prompt
    assert skills.OWNED_DIR in prompt and skills.VETOES_FILE in prompt


# ======================================================= fix round 1 (gate r1)


UNOWNED = "never-built-skill"


def test_a_case_naming_a_skill_it_does_not_build_is_an_ordinary_pair(env, monkeypatch):
    """Gate r1 MAJOR: a case whose decision.skill names a skill self-learn
    does not own, with no skills/<name>/ folder and no line routing into
    new-skill:<name> (a declined proposal, a route into a linked skill),
    carries no skill step and applies as any pair. Red on 270d0e7: the
    pair was dropped ("not a skill self-learn owns ... no skills/ folder").
    The control is test_b_a_new_skill_named_with_no_folder_drops_its_pair:
    a sheet that routes into new-skill:<name> without the folder is still
    dropped."""
    _set_writing(env, '"on"')
    _lesson(env, RID)

    def write_b(stage):
        _dump(stage / "case-decline.yaml",
              _case([RID], name=UNOWNED, outcome="no-action", lessons=[RID]))
        _dump(stage / "sheet-decline.yaml", {"version": 1, "items": [
            {"id": RID, "verb": "note", "append": "Checked this week; no skill is built."},
        ]})

    _phases(monkeypatch, write_b)
    before = {row["case"] for row in cases.list_cases(env.home)}

    result = _run(env)

    report = _report(result)
    refused = _section(report, "Refused / could not do")  # control: the section rendered
    assert UNOWNED not in refused and "case-decline.yaml" not in refused
    assert len({row["case"] for row in cases.list_cases(env.home)} - before) == 1
    assert skill_registry.load(env.home).row(UNOWNED) is None
    assert not (env.root / "plugins" / UNOWNED).exists()


def _sk2_refusal(rid: str, name: str = NAME) -> str:
    """SK2's words for an agent's route into a skill self-learn does not
    own (`verbs.owned_skill_refusal`, carried by the batch's refusal)."""
    return (
        f"{rid}: a route to new-skill:{name} is refused for the overseer — new-skill:{name} "
        "is not a skill self-learn owns (no live row in owned-skills.yaml)"
    )


def test_a_build_preview_sets_aside_only_the_not_owned_yet_refusal(env):
    """Gate r1 MINOR: in a build pair's preview only SK2's "not a skill
    self-learn owns" refusal is set aside, and the line is judged again by
    route's own checks; any other refusal is believed. Red on 270d0e7:
    items 2 and 3 became would-apply."""
    _lesson(env, RID)
    target = f"new-skill:{NAME}"
    sheet = [batch.SheetItem(n=n, id=rid, verb="route", fields={"dest": target})
             for n, rid in ((1, RID), (2, RID2), (3, RID3))]
    preview = batch.DryRunResult(items=[
        # a pending lesson: only ownership stood in its way
        batch.DryRunItem(n=1, id=RID, verb="route", state="would-refuse",
                         detail=_sk2_refusal(RID), kind="bad-line"),
        # another reason: believed as previewed
        batch.DryRunItem(n=2, id=RID2, verb="route", state="would-refuse",
                         detail=f"{RID2}: status is routed, not pending", kind="bad-line"),
        # ownership refused first, but there is no such lesson: route's own
        # checks refuse it once the ownership refusal is set aside
        batch.DryRunItem(n=3, id=RID3, verb="route", state="would-refuse",
                         detail=_sk2_refusal(RID3), kind="bad-line"),
    ])
    step = skills.SkillStep(action="write", name=NAME)

    out = skills.preview_for_step(env.home, preview, sheet, step)

    assert {item.n: item.state for item in out.items} == {
        1: "would-apply", 2: "would-refuse", 3: "would-refuse",
    }
    # control: a rewrite of an owned skill is judged as previewed
    rewrite = skills.SkillStep(action="write", name=NAME, updating=True)
    assert skills.preview_for_step(env.home, preview, sheet, rewrite) is preview


def test_a_build_no_line_of_which_would_move_a_lesson_in_drops_its_pair(env):
    """Gate r1 MINOR: before, a build whose every line refused for another
    reason was written first and stood live and owned with no lesson."""
    target = f"new-skill:{NAME}"
    sheet = [batch.SheetItem(n=1, id=RID2, verb="route", fields={"dest": target})]
    preview = batch.DryRunResult(items=[
        batch.DryRunItem(n=1, id=RID2, verb="route", state="would-refuse",
                         detail=f"{RID2}: status is routed, not pending", kind="bad-line"),
    ])
    with pytest.raises(skills.SkillPairError, match="no line of the sheet would move"):
        skills.preview_for_step(env.home, preview, sheet, skills.SkillStep(action="write", name=NAME))
    # control: the same line refused with a retried kind may still apply
    busy = batch.DryRunResult(items=[
        batch.DryRunItem(n=1, id=RID2, verb="route", state="would-refuse",
                         detail=f"{RID2}: the target is busy", kind="target-busy"),
    ])
    skills.preview_for_step(env.home, busy, sheet, skills.SkillStep(action="write", name=NAME))


def test_e_a_retirement_whose_line_met_a_retried_refusal_waits_for_the_resume(env, monkeypatch):
    """Gate r1 MINOR: a line refused with a retried kind is dispatched
    again by the resume, so the retirement stays open for it. Red on
    270d0e7: the step was marked refused for good."""
    step = skills.SkillStep(action="retire", name=NAME, updating=True)
    recipe = {"case_name": "case-retire.yaml", "skill": step.to_json()}
    busy = batch.ItemResult(n=1, id=RID, verb="supersede", rc=1, state="refused",
                            kind="target-busy")
    result = batch.BatchResult(items=[busy], process_code=1)

    def never(*args, **kwargs):
        pytest.fail("not retired while a line waits for the resume")

    monkeypatch.setattr(skill_writer, "retire", never)
    refusals: list[str] = []
    overseer_run._apply_skill_retire(env.home, "abcd1234", "case-1a2b3c4d", recipe, result, refusals, [])
    assert "state" not in recipe["skill"]
    assert refusals == []


def test_a_skill_written_before_its_case_was_refused_is_named(env):
    """Gate r1 MINOR: the write is not undone when the case writer refuses
    the pair's case at execute time; the report says so."""
    step = skills.SkillStep(action="write", name=NAME, files={"SKILL.md": "text\n"})
    recipe = {"case_name": "case-build.yaml", "skill": {**step.to_json(), "state": "applied"}}
    line = overseer_run._skill_written_case_refused(recipe, "case-1a2b3c4d")
    assert line is not None
    assert NAME in line and "case-1a2b3c4d" in line and "stays as written" in line
    recipe["skill"]["state"] = "refused"  # control: no skill was written
    assert overseer_run._skill_written_case_refused(recipe, "case-1a2b3c4d") is None
    retire = {"case_name": "case-retire.yaml",
              "skill": {**skills.SkillStep(action="retire", name=NAME).to_json(), "state": "applied"}}
    assert overseer_run._skill_written_case_refused(retire, "case-1a2b3c4d") is None


@pytest.mark.parametrize("text", [
    "overseer: [\n",            # does not parse
    "- a list\n",               # top level not a mapping
    "overseer: 5\n",            # the section not a mapping
])
def test_a_config_yaml_that_cannot_be_read_reads_as_off(env, text):
    """Gate r1 NIT: before, a broken config.yaml read as the default,
    auto. Red on 270d0e7."""
    (env.home / "config.yaml").write_text(text, encoding="utf-8")
    mode, note = skills.writing_mode(env.home)
    assert mode == "off"
    assert note is not None and "cannot be read" in note


@pytest.mark.parametrize("text", ["", "other: 1\n", "overseer:\n  enabled: false\n"])
def test_control_a_readable_config_without_the_key_reads_as_auto(env, text):
    (env.home / "config.yaml").write_text(text, encoding="utf-8")
    assert skills.writing_mode(env.home) == ("auto", None)


def test_b_a_folder_whose_case_was_dropped_is_not_said_to_be_named_by_no_case(env, monkeypatch):
    """Gate r1 NIT: a skills/<name>/ folder whose case is dropped before
    its skill step is looked at (here: the case writer's confidence rule)
    is reported as such. Red on 270d0e7 ("no case names it")."""
    _set_writing(env, '"on"')
    _lesson(env, RID)

    def write_b(stage):
        _write_folder(stage, NAME, sk1.draft())
        case = _case([RID])
        case["decision"]["confidence"] = "not-a-confidence"
        _dump(stage / "case-build.yaml", case)
        _dump(stage / "sheet-build.yaml", _route_sheet([RID]))

    _phases(monkeypatch, write_b)
    result = _run(env)
    refused = _section(_report(result), "Refused / could not do")
    assert "case-build.yaml" in refused  # control: the case itself was dropped
    assert f"skills/{NAME}/: not written — the case that names it" in refused
    assert "no case names it" not in refused
    assert env.row() is None


# ============================================================ fix round 2 (gate r2)


def _old_skill_md(env: sk1.Env) -> str:
    """The SKILL.md of the sandbox host's skill ``s``, where a lesson routed
    ``dest: skill-md`` is placed."""
    return next(env.root.glob("plugins/s-plugin/skills/s/SKILL.md")).read_text(encoding="utf-8")


def test_a_reconsider_build_pair_moves_a_placed_lesson_into_the_new_skill(env, monkeypatch):
    """Gate r2 MAJOR: plan §2 step 6, a placed lesson moves into a new skill
    by reroute: a ``route`` line under the pair's ``kind: reconsider`` case
    over a routed lesson, which the batch applies as a reroute. Before the
    skill exists the preview refuses that line as "not a skill self-learn
    owns" (SK2); fix round 1 then asked ``route --dry-run``, whose status
    check refuses every routed lesson, and believed it, so the pair was
    dropped ("no line of the sheet would move a lesson into ..."). Red on
    893996b with SK2 merged. Needs SK2 (`w31-sk2-routes`) to pass: without
    it, RER4 refuses every reroute into new-skill, before and at apply."""
    from test_u3b_steward_authority import _route_through_a_case

    _set_writing(env, '"on"')
    setup = env.tmp / "setup"
    setup.mkdir()
    placed_by = _route_through_a_case(env.home, setup, RID)
    assert RID in _old_skill_md(env)  # control: placed where the first case put it

    def write_b(stage):
        _write_folder(stage, NAME, sk1.draft())
        case = _case([RID], kind="reconsider", supersedes=placed_by)
        case["evidence"] = [{"ref": f"record:{RID}", "quote": "status: routed"}]
        _dump(stage / "case-build.yaml", case)
        _dump(stage / "sheet-build.yaml", _route_sheet([RID]))

    _phases(monkeypatch, write_b)

    result = _run(env)

    report = _report(result)
    refused = _section(report, "Refused / could not do")  # control: the section rendered
    assert "case-build.yaml" not in refused, refused
    row = env.row()
    assert row is not None and row["status"] == "live", refused
    record = Record.from_path(find_record_path(env.home, RID))
    assert record.status == "routed"
    assert (record.routing or {}).get("destination") == "new-skill"
    assert f"({RID})" in env.skill_md().read_text(encoding="utf-8")
    assert RID not in _old_skill_md(env)  # the old placement was retired
    assert f"[new skill] {NAME}" in _section(report, "Decided in the user's stead")


def test_a_build_preview_lets_a_reconsidered_placed_lesson_move_in_by_reroute(env):
    """Gate r2 MAJOR, the preview alone (no SK2 needed: the preview is
    built by hand). A routed lesson the pair's reconsider case covers is
    not sent to ``route --dry-run``; the control, the same line with no
    reconsider case, still is, and its routed-status refusal is believed."""
    from test_u3b_steward_authority import _route_through_a_case

    setup = env.tmp / "setup"
    setup.mkdir()
    _route_through_a_case(env.home, setup, RID)
    target = f"new-skill:{NAME}"
    sheet = [batch.SheetItem(n=1, id=RID, verb="route", fields={"dest": target})]
    preview = batch.DryRunResult(items=[
        batch.DryRunItem(n=1, id=RID, verb="route", state="would-refuse",
                         detail=_sk2_refusal(RID), kind="bad-line"),
    ])
    step = skills.SkillStep(action="write", name=NAME)

    out = skills.preview_for_step(env.home, preview, sheet, step, reconsidered={RID})
    assert [item.state for item in out.items] == ["would-apply"]
    assert "reroute" in (out.items[0].detail or "")

    # control: not reconsidered, the routed lesson cannot be routed again
    with pytest.raises(skills.SkillPairError, match="no line of the sheet would move"):
        skills.preview_for_step(env.home, preview, sheet, step)


def test_the_run_hands_the_batch_preview_the_records_its_reconsider_covers(env, monkeypatch):
    """Integration mutation gap (side finding of item 73): the run passes
    `reconsidered=` to `batch.dry_run` as well as to `skills.preview_for_step`.
    Dropping it from the `dry_run` call alone left the build pair above green,
    because that pair's route line is refused by SK2's "not owned yet" either
    way and `preview_for_step` sets the refusal aside. Pinned at the call; the
    real `dry_run` still runs behind the spy (the control that it was reached)."""
    from test_u3b_steward_authority import _route_through_a_case

    _set_writing(env, '"on"')
    setup = env.tmp / "setup"
    setup.mkdir()
    placed_by = _route_through_a_case(env.home, setup, RID)
    seen: list[frozenset[str]] = []
    real = batch.dry_run

    def spy(*args, **kwargs):
        seen.append(frozenset(kwargs.get("reconsidered") or ()))
        return real(*args, **kwargs)

    monkeypatch.setattr(batch, "dry_run", spy)

    def write_b(stage):
        _write_folder(stage, NAME, sk1.draft())
        case = _case([RID], kind="reconsider", supersedes=placed_by)
        case["evidence"] = [{"ref": f"record:{RID}", "quote": "status: routed"}]
        _dump(stage / "case-build.yaml", case)
        _dump(stage / "sheet-build.yaml", _route_sheet([RID]))

    _phases(monkeypatch, write_b)

    _run(env)

    assert seen, "the pair was never previewed by batch.dry_run"
    assert frozenset({RID}) in seen, seen


def _retire_case_data(name: str) -> dict:
    return _case([RID], outcome="retire", name=name, lessons=[RID])


def test_a_retire_case_naming_a_skill_it_does_not_own_with_lines_is_an_ordinary_pair(env):
    """Gate r2 MINOR: a declining successor that keeps the proposal's
    decision.skill and retires the proposal's lessons carries no skill
    step. Red on 893996b ("not a skill self-learn owns, so it cannot be
    retired"). Control: with no line it can only mean retiring the skill,
    and is still refused."""
    stage = env.tmp / "stage"
    stage.mkdir()
    data = _retire_case_data(UNOWNED)
    staged = skills.StagedSkills()
    assert skills.step_for_case(
        env.home, stage, data, staged=staged, deploy=True, sheet_ids={RID},
    ) is None
    with pytest.raises(skills.SkillPairError, match="cannot be retired"):
        skills.step_for_case(env.home, stage, data, staged=staged, deploy=True, sheet_ids=set())


def test_a_retire_case_whose_sheet_leaves_a_lesson_in_the_owned_skill_is_dropped(env):
    """Gate r2 MINOR: a case with outcome: retire naming an owned skill
    retires it; a sheet with no line for a lesson routed there cannot move
    it out, so the pair is refused here by name instead of reported as
    "would retire" or retired in name only. Red on 893996b (a retire step
    came back). Control: a sheet with a line for it gets the retire step."""
    assert env.write().ok
    _lesson(env, RID)
    verbs.route(env.home, RID, dest=f"new-skill:{NAME}", no_push=True)
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]  # control: it routes there
    stage = env.tmp / "stage"
    stage.mkdir()
    data = _retire_case_data(NAME)
    staged = skills.StagedSkills()

    with pytest.raises(skills.SkillPairError, match=f"no line for {RID}"):
        skills.step_for_case(env.home, stage, data, staged=staged, deploy=False, sheet_ids={RID2})

    step = skills.step_for_case(env.home, stage, data, staged=staged, deploy=False, sheet_ids={RID})
    assert step is not None and step.action == "retire" and step.name == NAME


def _git_refusal(name: str) -> skill_writer.WriteResult:
    return skill_writer.WriteResult(
        name=name, ok=False, kind=skill_writer.KIND_GIT,
        problems=("the skills-root write failed (a git commit failed)",),
    )


def test_a_skill_write_met_with_git_trouble_waits_for_the_resume(env, monkeypatch):
    """Gate r2 NIT: a ``git`` refusal of the skill write is tried again by
    the run's resume, as a sheet line refused with that kind is (Q19); a
    stale --expect (``target-busy``, D4) stays final. Red on 893996b: the
    git refusal was final for the run."""
    calls: list[str] = []
    kinds = [skill_writer.KIND_GIT, skill_writer.KIND_GIT, skill_writer.KIND_TARGET_BUSY]

    def write(home, name, files, **kwargs):
        calls.append(name)
        return skill_writer.WriteResult(name=name, ok=False, kind=kinds[len(calls) - 1],
                                        problems=("refused for the test",))

    monkeypatch.setattr(skill_writer, "write", write)
    step = skills.SkillStep(action="write", name=NAME, files=sk1.draft())
    recipe = {"case_name": "case-build.yaml", "skill": step.to_json()}

    with pytest.raises(overseer_run._SkillRefused) as first:
        overseer_run._apply_skill_write(env.home, "abcd1234", "case-1a2b3c4d", recipe, [], [])
    assert first.value.kind == "git"
    assert recipe["skill"]["state"] == "retry"
    assert "resume writes the skill again" in first.value.line
    with pytest.raises(overseer_run._SkillRefused):  # the next attempt writes again
        overseer_run._apply_skill_write(env.home, "abcd1234", "case-1a2b3c4d", recipe, [], [])
    assert len(calls) == 2

    # control: target-busy is final, and never written again
    with pytest.raises(overseer_run._SkillRefused) as busy:
        overseer_run._apply_skill_write(env.home, "abcd1234", "case-1a2b3c4d", recipe, [], [])
    assert busy.value.kind is None and recipe["skill"]["state"] == "refused"
    with pytest.raises(overseer_run._SkillRefused):
        overseer_run._apply_skill_write(env.home, "abcd1234", "case-1a2b3c4d", recipe, [], [])
    assert len(calls) == 3


def test_a_build_whose_write_met_git_trouble_is_finished_by_the_resume(env, monkeypatch):
    """Gate r2 NIT, end to end: the first attempt's write fails with git
    trouble, so the pair waits and the run stays unfinished; the resume
    writes the skill and applies the pair."""
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    real_write = skill_writer.write
    calls: list[str] = []

    def write(home, name, files, **kwargs):
        calls.append(name)
        if len(calls) == 1:
            return _git_refusal(name)
        return real_write(home, name, files, **kwargs)

    monkeypatch.setattr(skill_writer, "write", write)

    first = _run(env)
    assert calls == [NAME]  # control: the write was tried
    assert env.row() is None and _status(env, RID) == "pending"
    assert overseer_run._unfinished_manifest(env.home) is not None, _report(first)

    _run(env)

    assert len(calls) == 2
    assert env.row() is not None and env.row()["status"] == "live"
    assert _status(env, RID) == "routed"
    assert overseer_run._unfinished_manifest(env.home) is None


def test_a_case_refused_after_its_skill_was_written_is_named_in_the_report(env, monkeypatch):
    """Gate r2 NIT: `_execute_manifest` names a skill written before the
    case writer refused its case (`_skill_written_case_refused`). Deleting
    that call kept every test green before this one."""
    _set_writing(env, '"on"')
    _lesson(env, RID)
    _phases(monkeypatch, _build_b([RID]))
    real_record = cases.record

    def record(home, path, *args, **kwargs):
        if Path(path).name == "case-build.yaml":
            raise cases.CaseError("refused by the test's case writer")
        return real_record(home, path, *args, **kwargs)

    monkeypatch.setattr(cases, "record", record)

    result = _run(env)

    refused = _section(_report(result), "Refused / could not do")
    assert "refused by the case writer" in refused  # control: the case was refused
    assert env.row() is not None  # the write stood
    assert "stays as written" in refused and NAME in refused
    assert _status(env, RID) == "pending"


@pytest.mark.parametrize("raw", ["false", "null", '""', '"maybe"'])
def test_doctor_settings_names_a_skill_writing_value_the_overseer_reads_as_off(env, raw):
    """Gate r2 MINOR (S-107 part 6): `doctor settings` showed the
    default, auto, for a YAML boolean, null or an empty string, while the
    overseer reads each as off. Red on 893996b (an INFO row). Control: a
    valid value is an ordinary INFO row."""
    _set_writing(env, raw)
    assert skills.writing_mode(env.home)[0] == "off"  # what the overseer obeys
    (row,) = [r for r in settings.preflight(env.home) if r.name == "overseer.skill_writing"]
    assert row.verdict == "WARN"
    assert "= 'off'" in row.detail and "reads it as off" in row.detail

    _set_writing(env, '"on"')
    (row,) = [r for r in settings.preflight(env.home) if r.name == "overseer.skill_writing"]
    assert row.verdict == "INFO" and "= 'on'" in row.detail
