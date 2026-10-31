"""SK4 -- the overseer looks for skills itself: phase S, skill discovery
(skill-writing plan §2 steps 2-3, D11, §4.1 row SK4 tests (a)-(h);
``03-decisions.md`` S-NEXT-skills parts 4 and 6; ``02-schema.md`` §3 "The
overseer's workspace for skills").

A run is phase A, then phase S (one model call, in a workspace of its own,
reading the catalogue, the lesson neighbourhoods, the skills on the machine,
earlier runs' candidates, briefs and the user's answers -- never anything of
the steward's), then phase B, which gives every candidate and every
``skill-proposal`` case one disposition. The runner commits both in
``overseer/skills/<week>.yaml``.

Every run here is scripted: the model is a fake ``write_session``, the
ledger a scratch one (``support.make_home``), ``~/.claude`` and the cache
scratch directories. No real model is called.

Red on master: ``self_learn.overseer.discovery`` does not exist there, so
every test here fails at import; on master a run also makes two calls, not
three (test (a)).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, miner, model_failures, settings
from self_learn.invocation.contract import Outcome
from self_learn.overseer import discovery, formats, skills
from self_learn.overseer import run as overseer_run
from self_learn.primitives import chrono
from self_learn.records import Record
from support import commit_all, git, make_home
from test_failstate_overseer import _seed_parked, _timed_out
from test_overseer_run import _enabled, _silence_notifications, _this_week

HEADINGS = (
    "Examined", "Decided in the user's stead", "Hooks", "User model",
    "Catalogue health", "Questions for you", "Refused / could not do",
)
RID_A = "lrn-5c000001"
RID_B = "lrn-5c000002"
RID_C = "lrn-5c000003"
UNKNOWN = "lrn-deadbeef"
GOOD = "sc-release-notes"
BAD = "sc-invented-lesson"
#: A Claude Code too old for the model: the environment class.
VERSION = (
    "Claude Code 2.0.1 does not support this model; version 2.0.9 or newer is "
    "required. Run 'claude update', then try again."
)


# ------------------------------------------------------------------ helpers


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    YAML().dump(data, stream)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _load(path: Path):
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _ok():
    return type("SdkLike", (), {
        "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
    })()


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A scratch ledger with two lessons placed in the user CLAUDE.md (so
    the catalogue lists them), a scratch ``~/.claude`` and cache, the
    overseer enabled for the test, notifications silenced."""
    claude = tmp_path / "claude"
    (claude / "skills").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("# user\n", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setattr(model_failures, "TRANSIENT_BACKOFF_SECS", 0.0)
    ledger = make_home(tmp_path)
    for rid, instruction in (
        (RID_A, "Leave internal refactors out of the release notes."),
        (RID_B, "Group release-note lines by what the reader notices."),
    ):
        _place(ledger, rid, instruction)
    commit_all(ledger, "two placed lessons")
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    return ledger


def _place(ledger: Path, rid: str, instruction: str) -> None:
    """A user-scope lesson routed to the user CLAUDE.md (a placed lesson)."""
    record = Record.create(
        type="behavior", scope="user", source="teach", kind="anti-pattern",
        trigger="About to write release notes.", instruction=instruction, record_id=rid,
        created_at=chrono.now_iso(),
    )
    record.set_routing({"routed_at": chrono.now_iso(), "destination": "claude-md", "by": "human"})
    record.set_status("routed")
    folder = ledger / "user" / "resolved"
    folder.mkdir(parents=True, exist_ok=True)
    record.write(folder / f"{rid}.md")


def _candidate(cid=GOOD, lessons=(RID_A, RID_B), **extra):
    return {
        "id": cid, "name": "release-notes", "lessons": list(lessons),
        "moment": "Writing release notes for a version about to ship.",
        "why": "Both lessons are steps of writing release notes.",
        **extra,
    }


def _model(monkeypatch, *, candidates=None, dispositions=None, s_outcome=None, s_journal=None,
           b_outcome=None, b_extra=None, seen=None):
    """The fake model. Phase A selects nothing. Phase S writes
    *candidates* (a whole file's data) and *s_journal*, or returns
    *s_outcome*. Phase B writes the four required files and an empty
    sheet, *dispositions* when given, then *b_extra(stage)*, or returns
    *b_outcome*. *seen* records, per phase label, the workspace, its paths
    (files and folders) and its files' text as the model found them, and
    the prompt."""
    labels: list[str] = []

    def invoke(spec):
        labels.append(spec.label)
        stage = spec.cwd
        if seen is not None:
            seen[spec.label] = {
                "cwd": stage,
                "names": {p.relative_to(stage).as_posix() for p in stage.rglob("*")},
                "texts": {
                    p.relative_to(stage).as_posix(): p.read_text(encoding="utf-8", errors="replace")
                    for p in stage.rglob("*") if p.is_file()
                },
                "prompt": spec.prompt,
                "containment": spec.containment,
            }
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "none"})
            _dump(stage / "initial-views.yaml", {"cases": []})
            return _ok()
        if spec.label == "phase-s":
            if s_journal is not None:
                with (stage / "journal.md").open("a", encoding="utf-8") as fh:
                    fh.write(s_journal)
            if s_outcome is not None:
                return s_outcome
            if candidates is not None:
                _dump(stage / discovery.CANDIDATES_FILE, candidates)
            return _ok()
        if b_outcome is not None:
            return b_outcome
        (stage / "report.md").write_text(
            "# draft\n" + "\n".join(f"## {h}\n- none" for h in HEADINGS) + "\n", encoding="utf-8",
        )
        _dump(stage / "findings.yaml", {"findings": []})
        _dump(stage / "questions.yaml", {"questions": []})
        _dump(stage / "user-model-delta.yaml", {"updates": []})
        _dump(stage / "sheet.yaml", {"version": 1, "items": []})
        if dispositions is not None:
            _dump(stage / discovery.DISPOSITIONS_FILE, dispositions)
        if b_extra is not None:
            b_extra(stage)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return labels


def _run(home: Path, **kwargs):
    kwargs.setdefault("no_push", True)
    kwargs.setdefault("manual", True)
    return overseer_run.run(home, **kwargs)


def _report(result) -> str:
    return Path(result.report).read_text(encoding="utf-8")


def _section(report: str, heading: str) -> str:
    start = report.index(f"## {heading}")
    end = report.find("\n## ", start + 1)
    return report[start:] if end == -1 else report[start:end]


def _journal_statuses(home: Path, run_id: str) -> list[str]:
    return [
        row["status"] for row in overseer_run.read_journal(home, limit=1000)
        if row.get("run") == run_id
    ]


def _as_proposal(monkeypatch, case_id: str) -> None:
    """The parked *case_id* reads as a steward ``skill-proposal`` (SK6 adds
    the reason to the case writer; the runner reads it off the parked
    queue's rows, which is what this changes)."""
    real = cases.awaiting_overseer

    def awaiting(h):
        return [
            {**row, "parked_reason": skills.SKILL_PROPOSAL_REASON} if row.get("case") == case_id else row
            for row in real(h)
        ]

    monkeypatch.setattr(cases, "awaiting_overseer", awaiting)


def _set_config(home: Path, text: str) -> None:
    """Write the SCRATCH ledger's config.yaml (a test fixture; never a
    real config) and commit it."""
    (home / "config.yaml").write_text(text, encoding="utf-8")
    commit_all(home, "test: config")


# ============================================= (a) three calls, in order


def test_a_run_makes_three_model_calls_with_phase_s_between_a_and_b(home, monkeypatch):
    labels = _model(monkeypatch, candidates={"candidates": []})
    result = _run(home)
    assert result.status == "applied", result
    assert labels == ["phase-a", "phase-s", "phase-b"]
    assert result.model_calls == 3
    assert "- Model calls this run: 3 of the runaway guard 50" in _report(result)


def test_a_guard_of_two_holds_a_run_that_makes_three_calls(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_OVERSEER_MAX_MODEL_CALLS", "2")
    labels = _model(monkeypatch, candidates={"candidates": []})
    result = _run(home)
    assert (result.status, result.model_calls) == ("runaway", 0)
    assert labels == []


# =========================================== (b) phase S sees only its own


def test_b_phase_s_stage_holds_its_inputs_and_nothing_of_phases_a_or_b(home, monkeypatch, tmp_path):
    _seed_parked(home, tmp_path, "lrn-5c0000aa", "parked-1")
    seen: dict = {}
    _model(monkeypatch, candidates={"candidates": []}, seen=seen)
    _run(home)

    s, b = seen["phase-s"], seen["phase-b"]
    # Positive control first: phase B's stage has the steward's material.
    assert {"full", "parked", "blind", "selection.yaml"} <= b["names"]
    # Phase S's stage has its six inputs and only those, beside its own
    # formats, prompt and journal.
    top = {name.split("/", 1)[0] for name in s["names"]}
    assert set(discovery.PHASE_S_INPUTS) <= top
    assert top <= {*discovery.PHASE_S_INPUTS, formats.FORMATS_DIR, discovery.PROMPT_FILE, "journal.md"}
    for absent in ("full", "parked", "blind", "selection.yaml", skills.PROPOSALS_FILE, "population.txt"):
        assert absent not in top, absent
    # Its own workspace, confined to itself.
    assert s["cwd"] == discovery.workspace_dir(home) and s["cwd"] != b["cwd"]
    assert s["containment"].write_globs == (f"{discovery.workspace_dir(home)}/**",)
    # The catalogue lists the placed lessons.
    catalogue_text = "".join(t for n, t in s["texts"].items() if n.startswith("catalogue/"))
    assert RID_A in catalogue_text and RID_B in catalogue_text
    # Nothing of the steward's vocabulary reaches phase S's formats.
    phase_s_formats = "".join(t for n, t in s["texts"].items() if n.startswith("formats/"))
    for word in ("sheet", "skill-proposal", "disposition", "steward"):
        assert word not in phase_s_formats, word


def test_b_phase_s_journal_entries_join_the_runs_journal(home, monkeypatch):
    entry = "\n## phase S · release notes\nids: lrn-5c000001\nPHASE-S-JOURNAL-MARK\n"
    _model(monkeypatch, candidates={"candidates": []}, s_journal=entry)
    result = _run(home)
    committed = overseer_run.model_journal_ledger_path(home, chrono.now_iso()[:10], result.run)
    assert "PHASE-S-JOURNAL-MARK" in committed.read_text(encoding="utf-8")


# ============================================ (c) an unknown lesson id


def test_c_a_candidate_naming_an_unknown_lesson_is_dropped_with_a_trace(home, monkeypatch):
    seen: dict = {}
    _model(monkeypatch, candidates={"candidates": [
        _candidate(),
        _candidate(BAD, lessons=(RID_A, UNKNOWN)),
    ]}, seen=seen)
    result = _run(home)

    staged = _load_text(seen["phase-b"]["texts"][discovery.CANDIDATES_FILE])
    ids = [c["id"] for c in staged["candidates"]]
    assert ids == [GOOD]  # positive control: the good one reached phase B
    assert staged["discovery"] == discovery.STATE_OK
    refused = _section(_report(result), "Refused / could not do")
    assert f"candidate {BAD} dropped" in refused and UNKNOWN in refused
    assert "skill-candidate-dropped" in _journal_statuses(home, result.run)


def _load_text(text: str):
    return YAML(typ="safe").load(text)


# ======================================= (d) every candidate and proposal


def test_d_a_missing_disposition_is_named_and_a_complete_set_is_reported(
    home, monkeypatch, tmp_path,
):
    proposal = _seed_parked(home, tmp_path, "lrn-5c0000bb", "proposal")
    _as_proposal(monkeypatch, proposal)
    seen: dict = {}
    _model(monkeypatch, candidates={"candidates": [_candidate()]}, dispositions={"dispositions": [
        {"source": "candidate", "id": GOOD, "disposition": "defer",
         "because": "two lessons are not a procedure yet",
         "would_change_it": "a third lesson about release notes"},
    ]}, seen=seen)
    result = _run(home)

    # Positive control: phase B was shown both the candidate and the proposal.
    assert GOOD in seen["phase-b"]["texts"][discovery.CANDIDATES_FILE]
    assert proposal in seen["phase-b"]["texts"][skills.PROPOSALS_FILE]
    report = _report(result)
    refused = _section(report, "Refused / could not do")
    assert f"no disposition for {proposal}" in refused
    assert f"no disposition for {GOOD}" not in refused
    assert f"[skill candidate] {GOOD} ({RID_A}, {RID_B}): defer" in _section(
        report, "Decided in the user's stead",
    )


def test_d_control_a_disposition_for_each_leaves_nothing_missing(home, monkeypatch, tmp_path):
    proposal = _seed_parked(home, tmp_path, "lrn-5c0000bc", "proposal")
    _as_proposal(monkeypatch, proposal)
    _model(monkeypatch, candidates={"candidates": [_candidate()]}, dispositions={"dispositions": [
        {"source": "candidate", "id": GOOD, "disposition": "decline", "because": "one line each"},
        {"source": "skill-proposal", "id": proposal, "disposition": "decline",
         "because": "the same group as the candidate"},
    ]})
    result = _run(home)
    report = _report(result)
    decided = _section(report, "Decided in the user's stead")
    assert f"[skill proposal] {proposal}: decline" in decided  # positive control
    assert "no disposition for" not in _section(report, "Refused / could not do")


# =============================================== (e) a failed phase S


def test_e_a_failed_phase_s_lets_phase_b_run_and_the_report_says_so(home, monkeypatch):
    seen: dict = {}
    labels = _model(
        monkeypatch, seen=seen,
        s_outcome=Outcome(ok=False, rc=1, stdout="", detail="reader produced no output", failure="exit"),
    )
    result = _run(home)
    assert labels == ["phase-a", "phase-s", "phase-b"]
    assert result.status == "applied", result
    assert result.model_calls == 3
    staged = _load_text(seen["phase-b"]["texts"][discovery.CANDIDATES_FILE])
    assert staged["discovery"] == discovery.STATE_FAILED and staged["candidates"] == []
    refused = _section(_report(result), "Refused / could not do")
    assert "skill discovery (phase S): its call failed (exit); phase B ran without candidates" in refused


def test_e_a_phase_s_that_wrote_no_file_is_a_failed_phase_s(home, monkeypatch):
    labels = _model(monkeypatch, candidates=None)
    result = _run(home)  # phase S ended normally and wrote no file at all
    assert labels == ["phase-a", "phase-s", "phase-b"] and result.status == "applied"
    assert "it wrote no skill-candidates.yaml" in _section(_report(result), "Refused / could not do")


def test_e_an_environment_failure_in_phase_s_holds_the_run_before_phase_b(home, monkeypatch):
    labels = _model(monkeypatch, s_outcome=Outcome(ok=False, rc=1, stdout="", detail=VERSION, failure="exit"))
    result = _run(home)
    assert result.status == model_failures.HELD_ENVIRONMENT
    assert labels == ["phase-a", "phase-s"]  # phase B was never called
    assert overseer_run._committed_failure_notes(home, _this_week()) == []
    assert not (home / "overseer" / "coverage.yaml").exists()


# ================================ (f) committed, and read back next time


def test_f_dispositions_are_committed_and_reach_the_next_runs_history_without_proposals(
    home, monkeypatch, tmp_path,
):
    proposal = _seed_parked(home, tmp_path, "lrn-5c0000cc", "proposal")
    _as_proposal(monkeypatch, proposal)
    _model(monkeypatch, candidates={"candidates": [_candidate()]}, dispositions={"dispositions": [
        {"source": "candidate", "id": GOOD, "disposition": "defer",
         "because": "CANDIDATE-MARK", "would_change_it": "a third lesson"},
        {"source": "skill-proposal", "id": proposal, "disposition": "decline",
         "because": "PROPOSAL-MARK"},
    ]})
    first = _run(home)
    assert first.status == "applied", first

    path = discovery.week_path(home, _this_week())
    rel = path.relative_to(home).as_posix()
    assert git(home, "ls-files", "--", rel).stdout.strip() == rel  # committed
    assert not git(home, "status", "--porcelain", "--", rel).stdout
    week = _load(path)
    (entry,) = week["runs"]
    assert entry["run"] == first.run and [c["id"] for c in entry["candidates"]] == [GOOD]
    # Positive control: the week file keeps the proposal's disposition too.
    assert "PROPOSAL-MARK" in path.read_text(encoding="utf-8")

    seen: dict = {}
    _model(monkeypatch, candidates={"candidates": []}, seen=seen)
    _run(home)

    history = _load_text(seen["phase-s"]["texts"][discovery.HISTORY_FILE])
    (earlier,) = history["earlier"]
    (shown,) = earlier["candidates"]
    assert shown["id"] == GOOD and shown["disposition"]["disposition"] == "defer"
    assert shown["disposition"]["because"] == "CANDIDATE-MARK"
    text = seen["phase-s"]["texts"][discovery.HISTORY_FILE]
    assert "PROPOSAL-MARK" not in text and proposal not in text


def test_f_a_run_with_no_candidate_and_no_disposition_writes_no_week_file(home, monkeypatch):
    _model(monkeypatch, candidates={"candidates": []}, dispositions={"dispositions": []})
    result = _run(home)
    assert result.status == "applied"
    assert not discovery.week_path(home, _this_week()).exists()


# ===================================================== (g) the switch


def test_g_skill_discovery_off_makes_two_calls_and_tells_phase_b(home, monkeypatch):
    _set_config(home, "overseer:\n  skill_discovery: false\n")
    seen: dict = {}
    labels = _model(monkeypatch, seen=seen)
    result = _run(home)
    assert labels == ["phase-a", "phase-b"]
    assert result.model_calls == 2
    assert "Skill discovery is off this run" in seen["phase-b"]["prompt"]
    staged = _load_text(seen["phase-b"]["texts"][discovery.CANDIDATES_FILE])
    assert staged["discovery"] == discovery.STATE_OFF
    assert not discovery.workspace_dir(home).exists()


def test_g_with_discovery_off_a_guard_of_two_admits_the_run(home, monkeypatch):
    _set_config(home, "overseer:\n  skill_discovery: false\n")
    monkeypatch.setenv("SELF_LEARN_OVERSEER_MAX_MODEL_CALLS", "2")
    _model(monkeypatch)
    assert _run(home).status == "applied"


def test_g_with_discovery_off_a_skill_proposal_waits_parked(home, monkeypatch, tmp_path):
    rid = "lrn-5c0000dd"
    proposal = _seed_parked(home, tmp_path, rid, "proposal")
    _as_proposal(monkeypatch, proposal)
    _set_config(home, "overseer:\n  skill_discovery: false\n")

    def successor(stage):
        _dump(stage / "case-p.yaml", {
            "kind": "resolution", "trigger": "weekly", "outcome": "reject",
            "records": [rid], "scope": "skill:s", "question": "keep?", "supersedes": proposal,
            "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
            "decision": {"verb": "reject", "because": "narrow", "confidence": "settled"},
        })
        _dump(stage / "sheet-p.yaml", {"version": 1, "items": [{"id": rid, "verb": "reject"}]})
        (stage / "sheet.yaml").unlink()

    _model(monkeypatch, b_extra=successor)
    result = _run(home)
    assert "waits parked while overseer.skill_discovery is off" in _section(
        _report(result), "Refused / could not do",
    )
    row = next(r for r in cases.list_cases(home, parked_for="overseer") if r["case"] == proposal)
    assert not row.get("superseded_by")


def test_g_the_setting_is_tier_c_config_only_and_on_by_default(home):
    setting = settings.by_name(discovery.SETTING)
    assert (setting.kind, setting.default, setting.tier) == ("bool", True, "C")
    assert setting.env_var is None and setting.override_channel is False
    assert discovery.enabled(home) is True
    _set_config(home, "overseer:\n  skill_discovery: false\n")
    assert discovery.enabled(home) is False


# =================================================== (h) the miner skips it


def test_h_the_phase_s_prompt_opens_with_the_session_opening(home, monkeypatch):
    seen: dict = {}
    _model(monkeypatch, candidates={"candidates": []}, seen=seen)
    _run(home)
    prompt = seen["phase-s"]["prompt"]
    assert prompt.startswith(overseer_run.SESSION_OPENINGS)
    assert prompt.startswith(miner.SELF_PROMPT_HEADERS)
    assert discovery.CANDIDATES_FILE in prompt  # positive control: it is phase S's prompt
    assert "steward" not in prompt


# ========================================== kept, reused, and dropped


def test_a_validated_phase_s_is_kept_and_reused_by_the_weeks_next_attempt(home, monkeypatch):
    entry = "\n## phase S · release notes\nids: sc-release-notes\nKEPT-PHASE-S-MARK\n"
    labels = _model(
        monkeypatch, candidates={"candidates": [_candidate()]}, s_journal=entry,
        b_outcome=_timed_out(),
    )
    first = _run(home)
    assert first.status == "timed-out"
    assert (discovery.keep_dir(home, _this_week()) / discovery.CANDIDATES_FILE).is_file()

    seen: dict = {}
    labels = _model(monkeypatch, candidates={"candidates": []}, seen=seen)
    second = _run(home)

    assert labels == ["phase-b"]  # phase A and phase S both reused
    assert second.status == "applied", second
    staged = _load_text(seen["phase-b"]["texts"][discovery.CANDIDATES_FILE])
    assert [c["id"] for c in staged["candidates"]] == [GOOD]
    journal = overseer_run.model_journal_ledger_path(home, chrono.now_iso()[:10], second.run)
    text = journal.read_text(encoding="utf-8")
    assert "KEPT-PHASE-S-MARK" in text and f"phase S of attempt {first.run}" in text
    assert "phase-s-reused" in _journal_statuses(home, second.run)
    # Published: the kept copy has served its purpose.
    assert not discovery.keep_dir(home, _this_week()).exists()


def test_a_kept_phase_s_is_not_used_when_the_catalogue_changed(home, monkeypatch):
    _model(monkeypatch, candidates={"candidates": [_candidate()]}, b_outcome=_timed_out())
    _run(home)
    _place(home, RID_C, "Write each release-note line as what the reader can now do.")
    commit_all(home, "a third placed lesson")

    labels = _model(monkeypatch, candidates={"candidates": []})
    _run(home)
    assert labels == ["phase-s", "phase-b"]  # phase A reused; phase S made again


def test_a_failed_phase_s_is_not_kept(home, monkeypatch):
    _model(monkeypatch, candidates=None, b_outcome=_timed_out())
    _run(home)
    assert not discovery.keep_dir(home, _this_week()).exists()


def test_a_dry_run_neither_keeps_nor_writes_a_week_file(home, monkeypatch):
    labels = _model(monkeypatch, candidates={"candidates": [_candidate()]}, dispositions={"dispositions": [
        {"source": "candidate", "id": GOOD, "disposition": "decline", "because": "one line each"},
    ]})
    result = _run(home, dry_run=True)
    assert result.status == "dry-run" and labels == ["phase-a", "phase-s", "phase-b"]
    assert not discovery.keep_dir(home, _this_week()).exists()
    assert not discovery.week_path(home, _this_week()).exists()


# ========================================= the trial reads phase S and B


def test_a_run_whose_discovery_steps_validate_is_autos_drafts_only_run(home, monkeypatch):
    _model(monkeypatch, candidates={"candidates": []}, dispositions={"dispositions": []})
    result = _run(home)
    trial = skills.trial_path(home)
    assert trial.is_file(), _section(_report(result), "Decided in the user's stead")
    assert _load(trial)["run"] == result.run
    assert "this was the drafts-only week" in _report(result)


def test_a_run_whose_phase_b_wrote_no_dispositions_is_not_the_trial(home, monkeypatch):
    _model(monkeypatch, candidates={"candidates": []})
    result = _run(home)
    assert result.status == "applied"  # positive control: the run completed
    assert not skills.trial_path(home).exists()
    assert "phase B wrote no skill-dispositions.yaml" in _report(result)


def test_a_run_whose_phase_s_failed_is_not_the_trial(home, monkeypatch):
    _model(monkeypatch, candidates=None, dispositions={"dispositions": []})
    result = _run(home)
    assert result.status == "applied"
    assert not skills.trial_path(home).exists()


def test_trial_readiness_needs_discovery_on_phase_s_and_valid_dispositions():
    good = discovery.Dispositions(True)
    ok = discovery.PhaseS(discovery.STATE_OK)
    assert discovery.trial_readiness(ok, good) == (True, "")
    assert not discovery.trial_readiness(discovery.PhaseS.off(), good)[0]
    assert not discovery.trial_readiness(discovery.PhaseS.failed("x"), good)[0]
    assert not discovery.trial_readiness(ok, discovery.Dispositions(False, why="y"))[0]


# ===================================================== the file checks


def _inputs(known=(RID_A, RID_B), skills_here=("example-diagrams",)):
    return discovery.StagedInputs(known_lessons=frozenset(known), skill_names=frozenset(skills_here))


@pytest.mark.parametrize(("entry", "why"), [
    (_candidate(into="example-diagrams"), "exactly one of name"),
    ({**_candidate(), "name": "Release Notes"}, "lowercase"),
    ({k: v for k, v in _candidate().items() if k != "moment"}, "missing moment"),
    (_candidate(lessons=()), "non-empty list"),
    ({**_candidate(), "extra": 1}, "unknown key"),
    ({**_candidate(), "id": "release-notes"}, "sc-<short-kebab-slug>"),
    ({k: v for k, v in _candidate(into="nowhere").items() if k != "name"}, "not a skill in"),
])
def test_a_bad_candidate_costs_that_candidate_only(tmp_path, entry, why):
    path = tmp_path / discovery.CANDIDATES_FILE
    _dump(path, {"candidates": [_candidate("sc-kept"), entry]})
    checked = discovery.read_candidates(path, _inputs())
    assert checked.valid
    assert [c["id"] for c in checked.entries] == ["sc-kept"]  # positive control
    assert len(checked.drops) == 1 and why in checked.drops[0], checked.drops


def test_a_second_candidate_with_the_same_id_is_dropped(tmp_path):
    path = tmp_path / discovery.CANDIDATES_FILE
    _dump(path, {"candidates": [_candidate(), _candidate()]})
    checked = discovery.read_candidates(path, _inputs())
    assert len(checked.entries) == 1 and "same id" in checked.drops[0]


@pytest.mark.parametrize("text", [
    "candidates: {}\n", "- a\n", "candidates: []\nnotes: x\n", "candidates: [\n",
    "candidates: []\nwhy_stopped: \"token = ghp_abcdefghijklmnopqrstuvwxyz123456\"\n",
])
def test_a_candidates_file_of_the_wrong_shape_is_not_valid(tmp_path, text):
    path = tmp_path / discovery.CANDIDATES_FILE
    path.write_text(text, encoding="utf-8")
    assert not discovery.read_candidates(path, _inputs()).valid
    path.write_text("candidates: []\nwhy_stopped: nothing cleared the bar\n", encoding="utf-8")
    assert discovery.read_candidates(path, _inputs()).valid  # control


@pytest.mark.parametrize(("entry", "why"), [
    ({"source": "candidate", "id": "sc-nope", "disposition": "decline", "because": "x"}, "is not a candidate"),
    ({"source": "candidate", "id": GOOD, "disposition": "maybe", "because": "x"}, "must be one of"),
    ({"source": "candidate", "id": GOOD, "disposition": "build", "because": "x"}, "names its skill"),
    ({"source": "candidate", "id": GOOD, "disposition": "defer", "because": "x"}, "would_change_it"),
    ({"source": "steward", "id": GOOD, "disposition": "decline", "because": "x"}, "source must be"),
])
def test_a_bad_disposition_is_dropped_and_its_candidate_named_missing(tmp_path, entry, why):
    path = tmp_path / discovery.DISPOSITIONS_FILE
    _dump(path, {"dispositions": [entry]})
    checked = discovery.read_dispositions(path, candidates=[GOOD], proposals=[])
    assert not checked.valid
    assert any(why in note for note in checked.notes), checked.notes
    assert any(f"no disposition for {GOOD}" in note for note in checked.notes)
    _dump(path, {"dispositions": [
        {"source": "candidate", "id": GOOD, "disposition": "build", "skill": "release-notes", "because": "x"},
    ]})
    assert discovery.read_dispositions(path, candidates=[GOOD], proposals=[]).valid  # control


def test_an_absent_dispositions_file_with_nothing_owed_says_nothing_but_is_not_valid(tmp_path):
    checked = discovery.read_dispositions(tmp_path / "absent.yaml", candidates=[], proposals=[])
    assert not checked.valid and checked.notes == ()
    owed = discovery.read_dispositions(tmp_path / "absent.yaml", candidates=[GOOD], proposals=[])
    assert owed.notes == (f"absent.yaml: no disposition for {GOOD}",)


def test_history_leaves_out_every_skill_proposal_disposition(tmp_path):
    ledger = tmp_path / "ledger"
    path = discovery.week_path(ledger, "2026-10-25")
    path.parent.mkdir(parents=True)
    path.write_text(discovery.week_text(None, "2026-10-25", {
        "run": "abcd1234", "at": "2026-10-25T04:15:00Z", "discovery": "ok",
        "candidates": [_candidate()],
        "dispositions": [
            {"source": "candidate", "id": GOOD, "disposition": "decline", "because": "seen"},
            {"source": "skill-proposal", "id": "case-0000abcd", "disposition": "build",
             "skill": "PROPOSED-NAME", "because": "STEWARD-MARK"},
        ],
    }), encoding="utf-8")
    (path.parent / skills.TRIAL_FILE).write_text("week: x\n", encoding="utf-8")  # not a week file
    history = discovery.history(ledger)
    (earlier,) = history["earlier"]
    assert earlier["candidates"][0]["disposition"]["because"] == "seen"  # positive control
    text = discovery._yaml_text(history)
    assert "STEWARD-MARK" not in text and "case-0000abcd" not in text and "PROPOSED-NAME" not in text


def test_the_week_file_keeps_each_runs_entry(tmp_path):
    entry = {"run": "aaaa0001", "at": "t", "discovery": "ok", "candidates": [_candidate()], "dispositions": []}
    text = discovery.week_text(None, "2026-10-25", entry)
    text = discovery.week_text(text, "2026-10-25", {**entry, "run": "aaaa0002"})
    text = discovery.week_text(text, "2026-10-25", {**entry, "run": "aaaa0002", "candidates": []})
    runs = _load_text(text)["runs"]
    assert [r["run"] for r in runs] == ["aaaa0001", "aaaa0002"]
    assert runs[1]["candidates"] == []  # the same run's entry is replaced, not repeated


# ============================================================ formats


def test_phase_s_formats_hold_only_the_candidates_file_and_it_validates(tmp_path):
    root = formats.write(tmp_path, "S")
    assert sorted(p.name for p in root.iterdir()) == ["README.md", "closed-sets.yaml", discovery.CANDIDATES_FILE]
    assert set(_load(root / "closed-sets.yaml")) == {"skill_candidates"}
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Phase S file" in readme  # positive control
    for word in ("sheet", "skill-proposal", "disposition", "steward", "verb"):
        assert word not in readme, word
    checked = discovery.read_candidates(
        root / discovery.CANDIDATES_FILE,
        _inputs(
            known=(*formats.EXAMPLE_SKILL_LESSONS, formats.EXAMPLE_INTO_LESSON),
            skills_here=(formats.EXAMPLE_EXISTING_SKILL,),
        ),
    )
    assert checked.valid and not checked.drops
    assert [c["id"] for c in checked.entries] == [formats.EXAMPLE_CANDIDATE, formats.EXAMPLE_INTO_CANDIDATE]
    # Its broken twin: the same file shown fewer lessons drops the first.
    broken = discovery.read_candidates(
        root / discovery.CANDIDATES_FILE,
        _inputs(known=(formats.EXAMPLE_INTO_LESSON,), skills_here=(formats.EXAMPLE_EXISTING_SKILL,)),
    )
    assert [c["id"] for c in broken.entries] == [formats.EXAMPLE_INTO_CANDIDATE]
    assert overseer_run._secret_files(tmp_path) == []


def test_phase_b_formats_carry_the_dispositions_section_and_example(tmp_path):
    formats.write(tmp_path, "A")
    root = formats.write(tmp_path, "B")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "## Skill dispositions" in readme
    sets = _load(root / "closed-sets.yaml")
    assert sets["skill_dispositions"]["disposition"] == list(discovery.DISPOSITIONS)
    assert sets["skill_candidates"]["id_pattern"] == discovery.CANDIDATE_ID_RE.pattern
    checked = discovery.read_dispositions(
        root / discovery.DISPOSITIONS_FILE,
        candidates=[formats.EXAMPLE_CANDIDATE], proposals=[formats.EXAMPLE_PARKED_CASE],
    )
    assert checked.valid, checked.notes
    broken = discovery.read_dispositions(
        root / discovery.DISPOSITIONS_FILE, candidates=[formats.EXAMPLE_CANDIDATE], proposals=[],
    )
    assert not broken.valid
    assert overseer_run._secret_files(tmp_path) == []


def test_the_phase_b_prompt_carries_the_dispositions_rule_both_ways(tmp_path):
    on = overseer_run._phase_b_prompt(tmp_path, (), ())
    off = overseer_run._phase_b_prompt(tmp_path, (), (), discovery=False)
    assert f"Write {discovery.DISPOSITIONS_FILE} giving every candidate" in on
    assert "Skill discovery is off this run" in off
    assert f"Write {discovery.DISPOSITIONS_FILE} giving" not in off
