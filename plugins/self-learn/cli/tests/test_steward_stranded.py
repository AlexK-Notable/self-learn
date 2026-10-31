"""S-NEXT-cadence, part 2: the stranded-lesson census.

The case (interventions survey 2026-10-31, §3): `lrn-e92861b2` and
`lrn-f55e9e47` sat about 55 days in the queue. A steward run deferred both
under the pre-U3a proposal identity; the identity change kept that row
"decided" for ever, so when the deferral came due no run selected them, and
nothing noticed until a person swept the queue. S-95 cured that one cause.
The class is cured here: every queued lesson must be selectable, held by the
overseer, or in an unfinished run, and a census says which one is not and
why -- in `--selftest`, in the overseer's facts, in a cache file the
session-start status can read, and as a `health` notice in the self-learn
checkout, where the people who can fix the selection code work.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``). No model call; ids are synthetic.
Each absence assertion has a positive control first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import ledger_ops, notices, selfcheck, serve, steward
from self_learn.overseer import health
from self_learn.records import Record
from support import commit_all, git, make_env, proposal_dict


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _blob(home: Path, path: Path) -> str:
    return git(home, "rev-parse", f"HEAD:{path.relative_to(home).as_posix()}").stdout.strip()


def _lesson(home: Path, rid: str) -> tuple[str, str]:
    """A pending lesson with an analyst proposal, committed; answers the
    (record blob, proposal blob)."""
    ledger_ops.create_record(home, Record.create(
        type="behavior", scope="skill:s", source="session", kind="anti-pattern",
        trigger=f"About to edit storage for case {rid}.",
        instruction=f"Stop the container first ({rid}).", record_id=rid,
    ))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    commit_all(home, f"lesson {rid} with a proposal")
    record_path = ledger_ops.find_record_path(home, rid)
    return (
        _blob(home, record_path),
        _blob(home, record_path.parent.parent / "proposals" / f"{rid}.yaml"),
    )


def _publish(
    home: Path, rid: str, version: str, verb: str, run_id: str, *, status: str = "complete"
) -> None:
    """A committed steward run whose one disposition, `applied`, decides
    *rid* at *version* with one sheet line of *verb*."""
    case_id = "case-0000cade"
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-09-22T06:00:00Z",
        "completed_at": "2026-09-22T06:23:53Z" if status == "complete" else None,
        "status": status,
        "cases": {case_id: {"items": [{"id": rid, "n": 1, "verb": verb}]}},
        "packets": [{
            "index": 1, "inputs": [{"record": rid, "version": version}], "records": [rid],
            "dispositions": {rid: {"case": case_id, "input_version": version,
                                   "state": "applied"}},
        }],
    }, reason=f"an applied {verb} row")


def _ids(rows) -> list[str]:
    return [row.record for row in rows]


# ------------------------------------------------------------ 1. the census


def test_a_legacy_deferral_that_came_due_is_stranded_only_under_the_pre_s95_rule(
    tmp_path, monkeypatch
):
    """The live case. The positive control is the mutation itself: with the
    selection's deferral rule put back the way it was before S-95
    (`defers_decide=True`), the census reports the lesson and names the run;
    under the current rule it is selectable and the census is empty."""
    home = make_env(tmp_path).ledger
    rid = "lrn-ca0e0001"
    _record_blob, proposal_blob = _lesson(home, rid)
    _publish(home, rid, proposal_blob, "defer", "run-aaaa0000ca01")

    real = steward._terminal_versions
    with monkeypatch.context() as pre_s95:
        pre_s95.setattr(
            steward, "_terminal_versions",
            lambda h, states=steward._DECIDED_DISPOSITIONS, *, defers_decide=True, manifests=None:
                real(h, states, defers_decide=True, manifests=manifests),
        )
        rows = steward.stranded_lessons(home)
        assert _ids(rows) == [rid]
        assert rows[0].run == "run-aaaa0000ca01"
        assert rows[0].version == proposal_blob
        assert "terminal by run-aaaa0000ca01" in rows[0].reason
        assert "proposal version" in rows[0].reason

    assert steward.stranded_lessons(home) == []
    assert [entry.record.id for entry, _row in steward._eligible_lessons(home)] == [rid]


def test_a_lesson_decided_at_its_version_and_still_queued_is_stranded(tmp_path):
    """A committed `applied` reject row at the lesson's current record blob,
    the lesson still pending: no run selects it again, and nothing else
    looks at it."""
    home = make_env(tmp_path).ledger
    rid, other = "lrn-ca0e0002", "lrn-ca0e0003"
    record_blob, _proposal = _lesson(home, rid)
    _lesson(home, other)
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca02")
    rows = steward.stranded_lessons(home)
    assert _ids(rows) == [rid]  # the undecided lesson is selectable, not stranded
    assert rows[0].state == "applied" and rows[0].case == "case-0000cade"
    assert "record version" in rows[0].reason
    assert rows[0].bucket == "skill:s"


def test_a_held_lesson_is_not_stranded(tmp_path, monkeypatch):
    """Would catch: the census dropping the overseer's hold, so every lesson
    waiting for the overseer reads as a selection defect."""
    home = make_env(tmp_path).ledger
    rid = "lrn-ca0e0004"
    record_blob, _proposal = _lesson(home, rid)
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca04")
    assert _ids(steward.stranded_lessons(home)) == [rid]  # positive control
    monkeypatch.setattr(
        steward.cases, "held_lessons",
        lambda h: {rid: [{"case": "case-0000beef", "parked_reason": "needs-overseer"}]},
    )
    assert steward.stranded_lessons(home) == []


def test_an_input_of_an_unfinished_run_is_not_stranded(tmp_path):
    home = make_env(tmp_path).ledger
    rid = "lrn-ca0e0005"
    record_blob, _proposal = _lesson(home, rid)
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca05", status="unfinished")
    assert steward.stranded_lessons(home) == []
    # control: the same row in a complete run strands it
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca05")
    assert _ids(steward.stranded_lessons(home)) == [rid]


# --------------------------------------------- 2. the cache file and notice


def _row(rid: str = "lrn-ca0e00a1") -> steward.Stranded:
    return steward.Stranded(
        rid, "user:global", "2026-09-06T00:00:00Z",
        "terminal by run-3dfa8bebd36b (case case-66dceef4, applied) at its proposal version 4e6c0c8b",
        run="run-3dfa8bebd36b", case="case-66dceef4", state="applied", version="4e6c0c8b" * 5,
    )


def test_a_census_keeps_one_health_notice_in_the_checkout_and_an_empty_one_ends_it(
    tmp_path, monkeypatch
):
    """Would catch: a notice that is never discarded (it would outlive the
    fix by 14 days), or one written per census (one line per night)."""
    home = make_env(tmp_path).ledger
    checkout = tmp_path / "self-learn-checkout"
    (checkout / "src").mkdir(parents=True)
    cache = tmp_path / "serve-cache"
    monkeypatch.setattr(serve, "_installed_checkout", lambda h: checkout)
    found = [[_row()]]
    monkeypatch.setattr(serve.steward, "stranded_lessons", lambda h: found[0])

    assert _ids(serve.census_stranded(home, cache)) == ["lrn-ca0e00a1"]
    serve.census_stranded(home, cache)  # the next night: the same notice
    shown = notices.visible(home, cwd=checkout / "src")
    assert [(n.source, n.project) for n in shown] == [("health", str(checkout.resolve()))]
    assert "1 queued lesson(s) the steward never selects" in shown[0].text
    assert "lrn-ca0e00a1" in shown[0].text and "run-3dfa8bebd36b" in shown[0].text
    assert notices.visible(home, cwd=tmp_path) == []  # only inside the checkout
    kept = serve.read_stranded(cache)
    assert kept is not None and kept["count"] == 1
    assert kept["lessons"][0]["record"] == "lrn-ca0e00a1"

    # a second lesson changes the words of the same notice
    found[0] = [_row(), _row("lrn-ca0e00a2")]
    serve.census_stranded(home, cache)
    shown = notices.visible(home, cwd=checkout)
    assert len(shown) == 1 and shown[0].text.startswith("2 queued lesson(s)")

    found[0] = []
    assert serve.census_stranded(home, cache) == []
    assert notices.visible(home, cwd=checkout) == []
    assert notices.all_notices(home) == []
    assert serve.read_stranded(cache)["count"] == 0


def test_a_census_that_cannot_be_taken_leaves_the_last_one(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    checkout = tmp_path / "self-learn-checkout"
    checkout.mkdir()
    cache = tmp_path / "serve-cache"
    monkeypatch.setattr(serve, "_installed_checkout", lambda h: checkout)
    monkeypatch.setattr(serve.steward, "stranded_lessons", lambda h: [_row()])
    serve.census_stranded(home, cache)

    def _broken(h):
        raise OSError("git is wedged")

    monkeypatch.setattr(serve.steward, "stranded_lessons", _broken)
    assert serve.census_stranded(home, cache) is None
    assert serve.read_stranded(cache)["count"] == 1
    assert len(notices.visible(home, cwd=checkout)) == 1


def test_the_notice_goes_only_to_a_registered_self_learn_checkout(tmp_path):
    """`_installed_checkout` is the git work tree of the running module,
    and only when it is a registered project host."""
    env = make_env(tmp_path)
    assert serve._installed_checkout(env.ledger) is None  # not registered
    root = serve.gitops.work_tree_of(Path(serve.__file__))
    assert root is not None  # positive control: this module lives in a checkout
    (env.ledger / "hosts.yaml").write_text(
        f"skills_root: {env.host}\nprojects:\n  - path: {env.host}\n  - path: {root}\n",
        encoding="utf-8",
    )
    assert serve._installed_checkout(env.ledger) == root


def test_a_health_notice_a_person_marked_done_stays_done_while_the_fault_lasts(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    made = notices.set_health(home, project=project, key="k", text="1 thing is wrong")
    assert made is not None and made.source == notices.SOURCE_HEALTH
    notices.mark_done(home, made.id)
    again = notices.set_health(home, project=project, key="k", text="2 things are wrong")
    assert again is not None and again.done_at is not None
    assert notices.visible(home, cwd=project) == []
    # the fault clears, then comes back: a fresh notice
    assert notices.clear_health(home, project=project, key="k") is True
    fresh = notices.set_health(home, project=project, key="k", text="1 thing is wrong")
    assert fresh is not None and fresh.done_at is None
    assert [n.id for n in notices.visible(home, cwd=project)] == [made.id]


# ------------------------------------------------- 3. selftest and overseer


def test_the_selftest_row_fails_on_one_stranded_lesson(tmp_path, monkeypatch):
    """Would catch: a row that passes whatever the census says."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(steward, "stranded_lessons", lambda h: [])
    verdict, text = selfcheck._check_steward_queue(home)  # positive control
    assert verdict is selfcheck.Verdict.PASS
    assert text == "every queued lesson is selectable or held"
    monkeypatch.setattr(steward, "stranded_lessons", lambda h: [_row()])
    verdict, text = selfcheck._check_steward_queue(home)
    assert verdict is selfcheck.Verdict.FAIL
    assert "lrn-ca0e00a1" in text and "run-3dfa8bebd36b" in text


def test_the_selftest_row_on_a_real_ledger(tmp_path):
    home = make_env(tmp_path).ledger
    rid = "lrn-ca0e0006"
    record_blob, _proposal = _lesson(home, rid)
    assert selfcheck._check_steward_queue(home)[0] is selfcheck.Verdict.PASS
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca06")
    verdict, text = selfcheck._check_steward_queue(home)
    assert verdict is selfcheck.Verdict.FAIL and rid in text


def test_the_overseer_is_told_the_census(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = "lrn-ca0e0007"
    record_blob, _proposal = _lesson(home, rid)
    _publish(home, rid, record_blob, "reject", "run-aaaa0000ca07")
    row = health.stranded_lessons_row(home)
    assert row["kind"] == "stranded-lessons" and row["state"] == "ok"
    assert row["count"] == 1 and row["lessons"][0]["record"] == rid
    assert "run-aaaa0000ca07" in row["lessons"][0]["reason"]
    assert "stranded-lessons" in [r["kind"] for r in health.gather(home)]

    def _broken(h):
        raise OSError("git is wedged")

    monkeypatch.setattr(steward, "stranded_lessons", _broken)
    row = health.stranded_lessons_row(home)
    assert row["state"] == "unavailable" and "count" not in row
