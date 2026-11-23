"""Machine capture receipts and feedback under real process contention."""
from contextlib import contextmanager
import json
import multiprocessing
from pathlib import Path

import pytest

from self_learn import cli, gitops, verbs
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict


@pytest.fixture
def feedback_home(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setattr(cli.settings, "agent_caller", lambda: False)
    return env.ledger


def _seed(home, *, routed=False):
    record = make_behavior()
    create_record(home, record)
    if routed:
        write_proposal(home, record.id, proposal_dict())
    commit_all(home, "seed feedback lesson")
    if routed:
        verbs.route(home, record.id, no_push=True)
    return record.id


def _receipt(stdout, home, rid, status, *, applied=None, pushed="not_requested", host_pushed=None):
    result = json.loads(stdout)
    expected = {"id": rid, "path": str(find_record_path(home, rid)),
                "status": status, "scope": "skill:s"}
    if applied is not None:
        expected.update(applied=applied, pushed=pushed, host_pushed=host_pushed)
    assert result == expected
    assert Path(result["path"]).is_file()
    assert Record.from_path(result["path"]).status == status


def test_teach_json_pending_and_routed(feedback_home, capsys):
    for extra, status in (([], "pending"), (["--route", "--dest", "skill-md"], "routed")):
        rc = cli.main([
            "teach", "--skill", "s", "--trigger", "Before a fixture operation",
            "--instruction", "Keep the fixture isolated", "--json", "--no-push", *extra,
        ])
        assert rc == 0
        output = capsys.readouterr()
        rid = json.loads(output.out)["id"]
        _receipt(output.out, feedback_home, rid, status)
        assert "kind:" in output.err


def test_teach_json_failure_keeps_exit_and_empty_stdout(feedback_home, capsys):
    rc = cli.main(["teach", "--json", "--no-push"])
    assert rc == cli.EXIT_USAGE
    assert capsys.readouterr().out == ""
    assert not list(feedback_home.rglob("lrn-*.md"))


def test_teach_json_fallback_receipt(feedback_home, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise verbs.VerbError("fixture route refusal")

    monkeypatch.setattr(verbs, "route_direct", refuse)
    rc = cli.main([
        "teach", "--skill", "s", "--trigger", "Before a fixture operation",
        "--instruction", "Keep the fixture isolated", "--route", "--dest", "skill-md",
        "--json", "--no-push",
    ])
    assert rc == 4
    output = capsys.readouterr()
    _receipt(output.out, feedback_home, json.loads(output.out)["id"], "pending")
    assert "fixture route refusal" in output.err


def test_feedback_json_and_retry(feedback_home, capsys):
    rid = _seed(feedback_home, routed=True)
    replacement = _seed(feedback_home)
    capsys.readouterr()
    for command in (
        ["note", rid, "--append", "Observed useful behavior", "--key", "observation"],
        ["confirm-held", rid, "--key", "observation"],
    ):
        assert cli.main([*command, "--json", "--no-push"]) == 0
        _receipt(capsys.readouterr().out, feedback_home, rid, "routed", applied=True)
        first_sha = gitops.head_sha(feedback_home)
        assert cli.main([*command, "--json", "--no-push"]) == 0
        _receipt(capsys.readouterr().out, feedback_home, rid, "routed", applied=False)
        assert gitops.head_sha(feedback_home) == first_sha
    assert cli.main(["supersede", rid, replacement, "--json", "--no-push"]) == 0
    _receipt(capsys.readouterr().out, feedback_home, rid, "superseded", applied=True, host_pushed="not_requested")


def test_confirm_retry_does_not_refresh_date(feedback_home, monkeypatch):
    rid = _seed(feedback_home, routed=True)
    monkeypatch.setattr(verbs, "_now_iso", lambda: "2026-01-02T00:00:00Z")
    verbs.confirm_held(feedback_home, rid, key="first", no_push=True)
    sha = gitops.head_sha(feedback_home)
    monkeypatch.setattr(verbs, "_now_iso", lambda: "2026-02-03T00:00:00Z")
    verbs.confirm_held(feedback_home, rid, key="first", no_push=True)
    assert str(Record.from_path(find_record_path(feedback_home, rid)).last_confirmed) == "2026-01-02"
    assert gitops.head_sha(feedback_home) == sha
    verbs.confirm_held(feedback_home, rid, key="second", no_push=True)
    assert str(Record.from_path(find_record_path(feedback_home, rid)).last_confirmed) == "2026-02-03"
    assert gitops.head_sha(feedback_home) != sha


def _feedback_process(home, rid, kind, key, barrier, results, note_done, own_done):
    original = verbs._ledger_write

    @contextmanager
    def synchronized_write(*args, **kwargs):
        # All processes complete preflight before any can acquire the real lock.
        barrier.wait(timeout=20)
        if kind == "held":
            for completed in note_done:
                assert completed.wait(timeout=20), "note process did not complete"
        with original(*args, **kwargs) as recovered:
            yield recovered

    verbs._ledger_write = synchronized_write
    try:
        if kind == "note":
            result = verbs.note(home, rid, append=f"Observation {key}", key=key, no_push=True)
        else:
            result = verbs.confirm_held(home, rid, key=key, no_push=True)
        results.put((True, bool(result.staged)))
        own_done.set()
    except Exception as exc:
        results.put((False, repr(exc)))
        raise


def _race(home, rid, operations):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(len(operations))
    results = ctx.Queue()
    completed = [ctx.Event() for _ in operations]
    note_done = [event for event, (kind, _) in zip(completed, operations) if kind == "note"]
    processes = [ctx.Process(target=_feedback_process,
                             args=(home, rid, kind, key, barrier, results, note_done, event))
                 for event, (kind, key) in zip(completed, operations)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert all(not process.is_alive() for process in processes), "feedback process deadlocked"
        outcomes = [results.get(timeout=5) for _ in processes]
        assert all(ok for ok, _ in outcomes), outcomes
        assert all(process.exitcode == 0 for process in processes)
        return outcomes
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def test_parallel_distinct_notes_survive(feedback_home):
    rid = _seed(feedback_home)
    _race(feedback_home, rid, [("note", "alpha"), ("note", "beta"), ("note", "gamma")])
    record = Record.from_path(find_record_path(feedback_home, rid))
    assert {entry["key"] for entry in record.notes} == {"alpha", "beta", "gamma"}
    assert len(record.notes) == 3


@pytest.mark.parametrize("kind", ["note", "held"])
def test_parallel_same_key_commits_once(feedback_home, kind):
    rid = _seed(feedback_home, routed=kind == "held")
    outcomes = _race(feedback_home, rid, [(kind, "same")] * 3)
    assert sum(wrote for _, wrote in outcomes) == 1
    record = Record.from_path(find_record_path(feedback_home, rid))
    if kind == "note":
        assert len(record.notes) == 1
        assert record.note_has_key("same")
    else:
        assert record.confirmation_has_key("same")
        assert record.last_confirmed is not None


def test_parallel_confirmation_preserves_notes(feedback_home):
    rid = _seed(feedback_home, routed=True)
    _race(feedback_home, rid, [("note", "alpha"), ("note", "beta"), ("held", "confirmed")])
    record = Record.from_path(find_record_path(feedback_home, rid))
    assert {entry["key"] for entry in record.notes} == {"alpha", "beta"}
    assert record.confirmation_has_key("confirmed")
    assert record.last_confirmed is not None


def test_confirm_retry_after_supersession_acknowledges_completed_observation(feedback_home, capsys):
    rid = _seed(feedback_home, routed=True)
    replacement = _seed(feedback_home)
    verbs.confirm_held(feedback_home, rid, key="observed", no_push=True)
    verbs.supersede(feedback_home, rid, replacement, no_push=True)
    # Complete supersession's normal CLI epilogue before measuring retry writes.
    cli._mutating_epilogue(no_push=True)
    path = find_record_path(feedback_home, rid)
    before = path.read_bytes()
    sha = gitops.head_sha(feedback_home)
    capsys.readouterr()
    assert cli.main(["confirm-held", rid, "--key", "observed", "--json", "--no-push"]) == 0
    _receipt(capsys.readouterr().out, feedback_home, rid, "superseded", applied=False)
    assert path.read_bytes() == before
    assert gitops.head_sha(feedback_home) == sha
    assert cli.main(["confirm-held", rid, "--key", "new-observation", "--json", "--no-push"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "superseded" in output.err
    assert path.read_bytes() == before
    assert gitops.head_sha(feedback_home) == sha


def test_parallel_distinct_confirmation_keys_survive(feedback_home):
    rid = _seed(feedback_home, routed=True)
    outcomes = _race(feedback_home, rid, [("held", "alpha"), ("held", "beta")])
    assert sum(wrote for _, wrote in outcomes) == 2
    record = Record.from_path(find_record_path(feedback_home, rid))
    assert record.confirmation_has_key("alpha")
    assert record.confirmation_has_key("beta")
    sha = gitops.head_sha(feedback_home)
    for key in ("alpha", "beta"):
        assert verbs.confirm_held(feedback_home, rid, key=key, no_push=True).staged == []
    assert gitops.head_sha(feedback_home) == sha


@pytest.mark.parametrize("command", [
    ["note", "lrn-ffffffff", "--append", "Observation"],
    ["confirm-held", "lrn-ffffffff", "--key", "observation"],
    ["supersede", "lrn-ffffffff", "lrn-fffffffe"],
])
def test_feedback_json_missing_record_keeps_usage_code(feedback_home, capsys, command):
    assert cli.main([*command, "--json", "--no-push"]) == cli.EXIT_USAGE
    output = capsys.readouterr()
    assert output.out == ""
    assert "lrn-ffffffff" in output.err


def test_confirm_json_nonrouted_keeps_refusal_code(feedback_home, capsys):
    rid = _seed(feedback_home)
    capsys.readouterr()
    sha = gitops.head_sha(feedback_home)
    assert cli.main(["confirm-held", rid, "--key", "observation", "--json", "--no-push"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "pending" in output.err
    assert gitops.head_sha(feedback_home) == sha


@pytest.mark.parametrize("rebase_conflict", [False, True])
def test_feedback_json_push_failure_keeps_receipt_and_code(feedback_home, monkeypatch, capsys, rebase_conflict):
    rid = _seed(feedback_home)
    called = []

    def failed_push(repo, **kwargs):
        called.append(repo)
        return gitops.PushResult(ok=False, rebase_conflict=rebase_conflict, detail="fixture offline")

    # All publication entrypoints are fake: this tests the push result without
    # contacting a remote, including any existing telemetry epilogue push.
    monkeypatch.setattr(gitops, "push_pending", failed_push)
    monkeypatch.setattr(gitops, "push_if_remote", failed_push)
    monkeypatch.setattr(gitops, "push_with_retry", failed_push)
    capsys.readouterr()
    expected = gitops.EXIT_REBASE_CONFLICT if rebase_conflict else gitops.EXIT_PUSH_FAILED
    assert cli.main(["note", rid, "--append", "Observed behavior", "--key", "observation", "--json"]) == expected
    output = capsys.readouterr()
    _receipt(output.out, feedback_home, rid, "pending", applied=True, pushed="failed")
    assert called and all(repo == feedback_home for repo in called)
    assert Record.from_path(find_record_path(feedback_home, rid)).note_has_key("observation")
