"""S-157 end-to-end fake overseer: registered skills and requested work."""
import pytest

import test_overseer_skill_build as build
import test_skill_registration as registration
import test_skill_write as sk1
from self_learn import settings, skill_registry, skill_requests, skill_writer
from self_learn.overseer import skills, discovery, skill_work_requests as work
from self_learn.overseer import run as runner

NAME = sk1.NAME


@pytest.fixture
def env(tmp_path, monkeypatch):
    environment = sk1.Env(tmp_path, monkeypatch)
    real = settings.resolve_setting
    monkeypatch.setattr(settings, "resolve_setting", lambda home, setting: (True, "test") if setting.name == "overseer.enabled" else real(home, setting))
    return environment


def request(env, kind="change", name=NAME, lessons=None):
    return skill_requests.file_request(env.home, kind, name, lessons=lessons or [], note="Make the examples useful", by="agent")


def answer(stage, row, result, case=None):
    build._dump(stage / work.OUTPUT, {"decisions": [{"id": row["id"], "answer": result, "reason": "The examples now cover the missing step.", "case": case}]})


def test_open_change_request_stages_vetoed_target(env):
    registration.seed(env)
    registration.register(env)
    row = request(env)
    assert skill_requests.veto(env.home, NAME, by="human", no_push=True).ok
    stage = env.tmp / "vetoed-stage"
    shown = work.stage_requests(env.home, stage, runner._write_stage)
    assert len(shown) == 1 and shown[0]["id"] == row["id"]
    assert shown[0]["target"] == "vetoed"
    assert build._load(stage / work.INPUT)["requests"] == shown
    assert skill_requests.requests(env.home, open_only=True)[0]["id"] == row["id"]


def test_registered_stage_and_request_rewrite(env, monkeypatch):
    registration.seed(env)
    registration.register(env)
    build._lesson(env, build.RID)
    row = request(env)
    seen = {}
    expected = skill_writer.deployed_authored_sha256(env.home, NAME)
    def phase_b(stage):
        assert build._load(stage / work.INPUT)["requests"][0]["id"] == row["id"]
        staged = build._load(stage / skills.OWNED_DIR / NAME / skills.ROW_FILE)
        assert staged["row"]["permission"] == "registered"
        assert "authored_sha256" not in staged["row"]["registered"]
        assert (stage / skills.OWNED_DIR / NAME / skills.DIFF_FILE).exists()
        assert build._load(stage / skills.OWNED_DIR / NAME / skills.LESSONS_FILE)["lessons"] == []
        build._rewrite_b("The registered skill now has an example.")(stage)
        answer(stage, row, "changed", "case-change.yaml")
    real = skills.step_for_case
    def checked(*args, **kwargs):
        result = real(*args, **kwargs)
        if result:
            seen["expect"] = result.expect_sha
        return result
    monkeypatch.setattr(skills, "step_for_case", checked)
    build._phases(monkeypatch, phase_b, seen=seen)
    result = build._run(env)
    report = build._report(result)
    assert result.status == "applied", report
    assert "The registered skill now has an example." in env.skill_md().read_text()
    assert seen["expect"] == expected
    assert not skill_registry.load(env.home).is_owned(NAME)
    closed = skill_requests.requests(env.home)[0]
    assert closed["state"] == "closed" and closed["answer"] == "changed"
    assert row["id"] in report and "changed — The examples" in report
    assert "skill-request-decisions.yaml" in seen["stage"]["prompt-b.md"]


@pytest.mark.parametrize("placed", [False, True])
def test_build_request_applies_and_closes(env, monkeypatch, placed):
    build._lesson(env, build.RID)
    if placed:
        from self_learn import verbs
        assert verbs.route(env.home, build.RID, dest="skill-md", no_push=True)
        assert build._status(env, build.RID) == "routed"
    row = request(env, "build", lessons=[build.RID])
    def phase_b(stage):
        build._build_b([build.RID])(stage)
        answer(stage, row, "built", "case-build.yaml")
    build._phases(monkeypatch, phase_b)
    result = build._run(env)
    report = build._report(result)
    assert result.status == "applied", report
    assert skill_registry.load(env.home).is_owned(NAME)
    assert build._status(env, build.RID) == "routed"
    assert skill_requests.requests(env.home)[0]["answer"] == "built"
    assert row["id"] in report and "built — The examples" in report


def test_decline_and_repeat_finalization(env, monkeypatch):
    registration.seed(env)
    registration.register(env)
    row = request(env)
    build._phases(monkeypatch, lambda stage: answer(stage, row, "declined"))
    result = build._run(env)
    report = build._report(result)
    assert result.status == "applied", report
    assert row["id"] in report and "declined — The examples" in report
    closed = skill_requests.requests(env.home)[0]
    assert closed["state"] == "closed" and closed["answer"] == "declined"
    before = env.head(env.home)
    skill_requests.close_request(env.home, row["id"], answer="declined", reason="repeat", run="repeat")
    assert env.head(env.home) == before


@pytest.mark.parametrize("mode", ["off", "unapplied", "missing"])
def test_requests_do_not_close_for_drafts_claims_or_missing_answers(env, monkeypatch, mode):
    registration.seed(env)
    registration.register(env)
    build._lesson(env, build.RID)
    row = request(env)
    if mode == "off":
        build._set_writing(env, "off")
    def phase_b(stage):
        if mode == "missing":
            return
        if mode == "off":
            build._rewrite_b("This draft is not deployed.")(stage)
        answer(stage, row, "changed", "case-change.yaml")
    build._phases(monkeypatch, phase_b)
    result = build._run(env)
    assert skill_requests.requests(env.home, open_only=True)[0]["id"] == row["id"]
    report = build._report(result)
    if mode == "missing":
        assert result.status == "applied" and work.OUTPUT in report
        assert row["id"] in report and "Refused / could not do" in report
    else:
        assert row["id"] in report and "open —" in report
    assert "This draft is not deployed." not in env.skill_md().read_text()


def test_registered_missing_never_restored_or_renamed_by_veto(env, tmp_path):
    registration.seed(env)
    registration.register(env)
    veto = skill_requests.veto(env.home, NAME, by="human", no_push=True)
    assert veto.ok and "never renames" in veto.what
    assert skill_requests.pending_renames(env.home) == []
    assert NAME not in skill_registry.load(env.home).editable()
    # Withdraw the veto solely to exercise missing-file staging separately.
    skill_registry.with_update(env.home, lambda r: r.vetoed.clear(), subject="clear test veto")
    env.skill_md().unlink()
    stage = tmp_path / "stage"
    staged = skills.stage_phase_b(env.home, stage, [], skills.writing_state(env.home), runner._write_stage)
    assert NAME in staged.missing and NAME not in staged.absent
    shown = build._load(stage / skills.OWNED_DIR / NAME / skills.ROW_FILE)
    assert "do not restore" in shown["says"]
    assert not skill_writer.check(env.home, NAME, sk1.draft(), updating=True, expect_missing=True).ok


def test_discovery_registered_target_can_rewrite(env, monkeypatch, tmp_path):
    registration.seed(env)
    registration.register(env)
    skill_writer.link_skill(env.root, NAME)
    build._lesson(env, build.RID)
    from self_learn import verbs
    verbs.route(env.home, build.RID, dest="skill-md", no_push=True)
    assert build._status(env, build.RID) == "routed"
    # Discovery can target a registered skill through a full writer pair.
    stage = tmp_path / "discovery"
    staged = discovery.stage_inputs(env.home, stage, write=runner._write_stage, answers=[])
    index = build._load(stage / "skills-index.yaml")
    assert NAME in index["self_learn_registered"] and NAME not in index["self_learn_owns"]
    assert NAME in staged.skill_names
    def phase_b(stage):
        build._rewrite_b("Discovery extended this registered skill.")(stage)
        build._dump(stage / discovery.DISPOSITIONS_FILE, {"dispositions": [{
            "source": "candidate", "id": "sc-mouse-example", "disposition": "add-to-existing",
            "skill": NAME, "because": "The existing skill covers this task."}]})
    build._phases(monkeypatch, phase_b)
    fake = runner.invocation.write_session
    def invoke(spec):
        result = fake(spec)
        if spec.label == "phase-s":
            build._dump(spec.cwd / discovery.CANDIDATES_FILE, {"candidates": [{
                "id": "sc-mouse-example", "lessons": [build.RID], "into": NAME,
                "moment": "Remapping mouse buttons", "why": "An example belongs in the existing procedure."}]})
        return result
    monkeypatch.setattr(runner.invocation, "write_session", invoke)
    result = build._run(env)
    report = build._report(result)
    assert "Discovery extended this registered skill." in env.skill_md().read_text(), report
    assert "sc-mouse-example" in report and "add-to-existing" in report


def test_build_receipt_without_requested_lessons_stays_open(env):
    build._lesson(env, build.RID)
    row = request(env, "build", lessons=[build.RID])
    assert env.write().ok
    manifest = {"run_id": "synthetic-run", "skills": {"requests": [{**row,
        "answer": "built", "reason": "Built the procedure.", "case": "case-build.yaml"}]},
        "cases": {sk1.CASE: {"case_name": "case-build.yaml", "skill": {
            "name": NAME, "action": "write", "updating": False, "state": "applied"}}}}
    assert skill_writer.deployed_files(env.home, NAME) is not None
    assert skill_writer.routed_lessons(env.home, NAME) == []
    lines = work.settle(env.home, manifest, complete=True)
    assert skill_requests.requests(env.home, open_only=True)[0]["id"] == row["id"]
    assert "open —" in lines[0]


@pytest.mark.parametrize("source", ["request", "registration", "unreadable", "withdrawn"])
def test_stored_request_trouble_does_not_cost_run(env, monkeypatch, source):
    from support import commit_all
    from self_learn import skill_registration, scan
    registration.seed(env)
    registration.register(env)
    row = request(env)
    bad = "Mention token: EXAMPLE_CREDENTIAL"
    if source == "registration":
        path = env.home / skill_registry.REGISTRY_FILENAME
        data = build._load(path)
        data["registrations"][NAME]["registered"]["note"] = bad
        build._dump(path, data)
    elif source == "request":
        path = env.home / skill_requests.REQUESTS_FILE
        data = build._load(path)
        data["requests"][0]["note"] = bad
        build._dump(path, data)
    elif source == "unreadable":
        (env.home / skill_requests.REQUESTS_FILE).write_text("requests: [broken")
    else:
        skill_registration.unregister(env.home, NAME, note="User will maintain it", by="agent")
    if source != "withdrawn":
        commit_all(env.home, "synthetic stored request condition")
    def phase_b(stage):
        shown = build._load(stage / work.INPUT)["requests"]
        assert not scan.scan((stage / work.INPUT).read_text())
        if source == "unreadable":
            assert shown == []
        else:
            assert shown[0]["id"] == row["id"]
            if source == "withdrawn":
                assert shown[0]["target"] == "withdrawn"
            if source == "registration":
                text = (stage / skills.OWNED_DIR / NAME / skills.ROW_FILE).read_text()
                assert "withheld" in text and not scan.scan(text)
            answer(stage, row, "declined")
    build._phases(monkeypatch, phase_b)
    result = build._run(env)
    report = build._report(result)
    assert result.status == "applied", report
    assert "EXAMPLE_CREDENTIAL" not in report
    if source == "unreadable":
        assert "cannot read requests" in report and "Refused / could not do" in report
    else:
        assert skill_requests.requests(env.home)[0]["answer"] == "declined"
        assert row["id"] in report


@pytest.mark.parametrize("bad", ["missing", "unknown", "kind", "empty", "nontext", "malformed", "secret", "folded"])
def test_bad_answer_isolated_from_good_write(env, monkeypatch, bad):
    registration.seed(env)
    registration.register(env)
    build._lesson(env, build.RID)
    first = request(env)
    second = request(env, "build", "other-example", [build.RID])
    def phase_b(stage):
        build._rewrite_b("A useful independent rewrite landed.")(stage)
        good = {"id": first["id"], "answer": "changed", "case": "case-change.yaml", "reason": "Useful rewrite.\n"}
        other = {"id": second["id"], "answer": "declined", "reason": "No need.\n"}
        if bad == "missing":
            answers = [good]
        else:
            if bad == "unknown": other["id"] = "sr-unknown"
            if bad == "kind": other["answer"] = "changed"
            if bad == "empty": other["reason"] = " \n "
            if bad == "nontext": other["reason"] = ["not prose"]
            if bad == "secret": other["reason"] = "Mention token: EXAMPLE_CREDENTIAL"
            if bad == "folded": other["reason"] = "No need\nfor a duplicate.\n"
            answers = [other if bad != "malformed" else "not a mapping", good]
        build._dump(stage / work.OUTPUT, {"decisions": answers})
    build._phases(monkeypatch, phase_b)
    result = build._run(env)
    report = build._report(result)
    assert result.status == "applied", report
    assert "A useful independent rewrite landed." in env.skill_md().read_text()
    rows = {r["id"]: r for r in skill_requests.requests(env.home)}
    assert rows[first["id"]]["answer"] == "changed"
    assert rows[first["id"]]["reason"] == "Useful rewrite."
    if bad == "folded":
        assert rows[second["id"]]["reason"] == "No need for a duplicate."
        assert rows[second["id"]]["state"] == "closed"
    else:
        assert rows[second["id"]]["state"] == "open"
        assert second["id"] in report and "Refused / could not do" in report
    assert "EXAMPLE_CREDENTIAL" not in report


@pytest.mark.parametrize("updating", [False, True])
def test_build_receipt_accepts_actual_name_and_case_stem(env, updating):
    from self_learn import verbs
    build._lesson(env, build.RID)
    row = request(env, "build", "proposed-example", [build.RID])
    assert env.write().ok
    assert verbs.route(env.home, build.RID, dest=f"new-skill:{NAME}", no_push=True)
    manifest = {"run_id": "synthetic-run", "skills": {"requests": [{**row,
        "answer": "built", "reason": "Used the existing procedure.", "case": "case-build"}]},
        "cases": {sk1.CASE: {"case_name": "case-build.yaml", "skill": {
            "name": NAME, "action": "write", "updating": updating, "state": "applied"}}}}
    lines = work.settle(env.home, manifest, complete=True)
    closed = skill_requests.requests(env.home)[0]
    assert closed["state"] == "closed" and closed["answer"] == "built"
    assert closed["actual_name"] == NAME and NAME in lines[0]
