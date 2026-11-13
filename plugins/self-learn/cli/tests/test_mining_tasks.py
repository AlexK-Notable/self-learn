"""Unfinished work found in sessions (S-155): the session call's optional
``tasks`` list, its checks, the cache store, the nightly check-and-file step,
and the bounded backfill.

No model is called (the engine tests' backend stands in for the seam) and no
znote daemon is reached: an autouse fixture points the tracker client at a
port nothing listens on, and every test that files passes a fake tracker.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from self_learn import miner
from self_learn.mining import contract, engine
from self_learn.mining import tasks as mt
from self_learn.mining.tracker import Project, TrackerError
from test_mining_engine import (  # noqa: F401 -- fixtures
    PROJECT,
    FakeOutcome,
    Backend,
    asst,
    backend,
    home,
    host,
    lesson,
    pending,
    root,
    run,
    typed,
    write_session,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_live_znote(monkeypatch):
    monkeypatch.setenv("ZNOTE_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("ZNOTE_HTTP_PORT", "9")


# ------------------------------------------------------------------ helpers


@dataclass
class FakeTracker:
    projects_list: list[Project] = field(default_factory=lambda: [Project("host-repo", "host-repo", "the export tool")])
    existing: dict[str, list[dict]] = field(default_factory=dict)
    created: list[dict] = field(default_factory=list)
    fail_projects: bool = False
    fail_create: bool = False

    def projects(self):
        if self.fail_projects:
            raise TrackerError("the znote daemon did not answer (URLError)")
        return list(self.projects_list)

    def items(self, project, include_closed=True, limit=150):
        return list(self.existing.get(project, [])) + [
            {"id": c["id"], "stage": "idea", "status": "open", "title": c["title"], "owner": "self-learn"}
            for c in self.created if c["project"] == project
        ]

    def search_notes(self, query, project=None, limit=5):
        return "Searched notes\n\n## Notes (0)\n"

    def create_idea(self, *, project, title, why, quote=None):
        if self.fail_create:
            raise TrackerError("the znote daemon did not answer (URLError)")
        wid = f"W-{900 + len(self.created)}"
        self.created.append({"id": wid, "project": project, "title": title, "why": why, "quote": quote})
        return wid


def task_rows(sid: str, cwd: str) -> list[dict]:
    return [
        typed(sid, 1, "add a --dry-run flag to export.sh and update the README", cwd),          # L1 T1
        asst(sid, 2, "I added --dry-run to export.sh. I'll update the README next.", cwd),      # L2
        typed(sid, 3, "stop. you never ran make check, the log is empty", cwd),                  # L3 T2
        asst(sid, 4, "You're right. The README still does not mention --dry-run.", cwd),        # L4
    ]


def task(**over) -> dict:
    out = {
        "title": "Document the --dry-run flag in the export README",
        "left_undone": "The session added --dry-run to export.sh but never updated the README to mention it.",
        "evidence": {"line": 4, "quote": "The README still does not mention --dry-run."},
    }
    out.update(over)
    return out


def answer(lessons=(), tasks=None) -> str:
    doc: dict[str, Any] = {"contract": contract.MODEL_CONTRACT, "lessons": list(lessons), "sightings": [],
                           "rule_checks": []}
    if tasks is not None:
        doc["tasks"] = tasks
    return json.dumps(doc)


def decisions(*ds) -> str:
    return json.dumps({"decisions": list(ds)})


def file_it(tid="T1", project="host-repo", title="Document the --dry-run flag in the export README") -> dict:
    return {"id": tid, "file": True, "reason": "still-open", "project": project, "title": title,
            "why": "export.sh gained a --dry-run flag that the README never mentions.", "note": "no later session"}


class CheckBackend(Backend):
    """The engine tests' backend, which also answers the unfinished-work
    check (its prompt has no SESSION header) with ``check_answer``."""

    check_answer: str = ""
    check_prompts: list

    def text_session(self, spec):
        if "self-learn unfinished-work check." in spec.prompt:
            self.check_prompts.append(spec)
            return FakeOutcome(ok=True, stdout=self.check_answer, cost_usd=0.05)
        return super().text_session(spec)


@pytest.fixture()
def cbackend(monkeypatch):
    from self_learn import invocation

    b = CheckBackend()
    b.check_prompts = []
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    return b


@pytest.fixture()
def fake_tracker(monkeypatch):
    from self_learn.mining import tracker as tracker_mod

    t = FakeTracker()
    monkeypatch.setattr(tracker_mod, "Tracker", lambda *a, **k: t)
    return t


def store() -> mt.Store:
    return mt.Store.load(mt.store_path(miner.miner_dir()))


def item(key="s1#L4", *, when="2026-11-01T10:00:00Z", role="assistant", status="held", **over) -> dict:
    out = {"key": key, "session": key.split("#")[0], "transcript": "/nowhere/s1.jsonl", "project_dir": PROJECT,
           "cwd": "/work/host-repo", "line": 4, "uuid": None, "entry_ts": when, "role": role,
           "quote": "The README still does not mention --dry-run.",
           "title": "Document the --dry-run flag", "left_undone": "The README was never updated.",
           "found_run": "r0", "found_at": when, "status": status, "checks": 0, "decision": None,
           "item": None, "filed_at": None}
    out.update(over)
    return out


# ============================================================ the contract


def test_a_task_item_is_validated_on_its_own():
    assert contract.validate_model_task(task()) == []
    assert contract.validate_model_task(task(title="short"))  # under 8 characters
    assert contract.validate_model_task(task(evidence={"line": 4}))  # no quote
    assert contract.validate_model_task(task(evidence={"line": 4, "quote": "x", "subagent": "a1"}))  # main file only
    assert contract.validate_model_task({**task(), "extra": 1})


def test_the_schema_and_the_method_carry_tasks_only_while_it_is_on():
    assert "tasks" in contract.model_output_json_schema()["properties"]
    assert "tasks" not in contract.model_output_json_schema(tasks=False)["properties"]
    on, version = engine.shared_instructions(tasks=True)
    off, _ = engine.shared_instructions(tasks=False)
    assert version == "3"
    assert "## Unfinished work" in on and "## Unfinished work" not in off
    assert "<!-- tasks:" not in on and "<!-- tasks:" not in off
    # off, the method reads exactly as it did before the section existed
    method = (Path(miner.worker.package_skill_refs()) / "miner-method.md").read_text()
    before = re.sub(r"\n*<!-- tasks:begin -->.*?<!-- tasks:end -->\n*", "\n\n", method, flags=re.S)
    assert off.startswith(before.rstrip("\n"))
    assert "\n\n\n## Subagent causes" not in off and "\n\n## Subagent causes" in off


# ================================================= the session call's tasks


def test_a_found_task_is_kept_in_the_store_and_lessons_land_as_before(home, root, cbackend, fake_tracker, tmp_path):
    sid = "s1aaaaaa-0000"
    write_session(root, sid, task_rows(sid, host(tmp_path)))
    cbackend.answers[sid] = answer(
        lessons=[lesson(evidence=[{"line": 3, "quote": "you never ran make check"}], steps=[],
                        verification=None, incident_cost=None)],
        tasks=[task()],
    )
    cbackend.check_answer = decisions({"id": "T1", "file": False, "reason": "unsure", "project": None,
                                       "title": None, "why": None, "note": "not sure"})
    result = run(home)
    assert result.status == "ok", result.engine
    assert len(pending(home)) == 1
    items = list(store().items.values())
    assert [i["key"] for i in items] == [f"{sid}#L4"]
    it = items[0]
    assert it["role"] == "assistant" and it["quote"] == "The README still does not mention --dry-run."
    assert it["title"] == task()["title"] and it["session"] == sid
    # the transcript's dates are old, so tonight's check already decided it
    assert it["status"] == "skipped" and it["decision"]["reason"] == "unsure"
    assert result.engine["tasks_found"] == 1
    assert result.engine["tasks"]["checked"] == 1


def test_a_bad_task_is_dropped_and_never_costs_the_session_its_lessons(home, root, cbackend, tmp_path):
    sid = "s1aaaaaa-0000"
    write_session(root, sid, task_rows(sid, host(tmp_path)))
    cbackend.answers[sid] = answer(
        lessons=[lesson(evidence=[{"line": 3, "quote": "you never ran make check"}], steps=[],
                        verification=None, incident_cost=None)],
        tasks=[task(title="x"), task(evidence={"line": 4, "quote": "words that are not there"}), "nonsense",
               task(evidence={"line": 2, "quote": "I'll update the README next."})],
    )
    result = run(home)
    assert result.status == "ok", result.engine
    assert len(pending(home)) == 1
    out = json.loads((miner.miner_dir() / "runs" / result.run_id / "out" / f"{sid}.tasks.json").read_text())
    reasons = [d["reason"] for d in out["drops"]]
    assert reasons == ["bad-output", "quote-not-found", "bad-output", "over-count"]
    assert out["tasks"] == []
    assert store().items == {}


def test_tasks_that_are_not_a_list_drop_only_themselves(home, root, cbackend, tmp_path):
    sid = "s1aaaaaa-0000"
    write_session(root, sid, task_rows(sid, host(tmp_path)))
    cbackend.answers[sid] = answer(
        lessons=[lesson(evidence=[{"line": 3, "quote": "you never ran make check"}], steps=[],
                        verification=None, incident_cost=None)],
        tasks={"not": "a list"},
    )
    result = run(home)
    assert result.status == "ok" and len(pending(home)) == 1


def test_with_tasks_off_the_section_is_not_sent_and_nothing_is_kept(home, root, cbackend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_TASKS_ENABLED", "0")
    sid = "s1aaaaaa-0000"
    write_session(root, sid, task_rows(sid, host(tmp_path)))
    cbackend.answers[sid] = answer(tasks=[task()])
    result = run(home)
    assert result.status == "ok", result.engine
    shared = Path(cbackend.specs[0].append_system_prompt_file).read_text()
    assert "## Unfinished work" not in shared
    assert store().items == {}
    assert cbackend.check_prompts == []
    assert "tasks" not in result.engine


# ================================================================ the store


def test_the_store_keeps_one_item_per_line_and_per_title(tmp_path):
    s = mt.Store(tmp_path / "t.json", {})
    ref = {"line": 4, "project_dir": PROJECT, "cwd": "/w", "uuid": "u4", "entry_ts": "2026-11-01T10:00:00Z",
           "role": "assistant"}
    found = [{"title": "Document the flag", "left_undone": "x" * 30, "evidence": {"ref": ref, "quote": "q"}}]
    assert s.add(found, session="s1", transcript="/t", cwd="/w", run_id="r1", now=NOW) == 1
    assert s.add(found, session="s1", transcript="/t", cwd="/w", run_id="r2", now=NOW) == 0
    other_line = [{**found[0], "title": "document  the FLAG!", "evidence": {"ref": {**ref, "line": 9}, "quote": "q"}}]
    assert s.add(other_line, session="s1", transcript="/t", cwd="/w", run_id="r2", now=NOW) == 0
    s.save()
    assert oct(s.path.stat().st_mode & 0o777) == "0o600"
    assert mt.Store.load(s.path).items.keys() == {"s1#L4"}


def test_an_item_waits_two_days_and_expires_after_thirty(tmp_path):
    s = mt.Store(tmp_path / "t.json", {
        "a#L1": item("a#L1", when=(NOW - timedelta(days=1)).isoformat()),
        "b#L1": item("b#L1", when=(NOW - timedelta(days=3)).isoformat()),
        "c#L1": item("c#L1", when=(NOW - timedelta(days=40)).isoformat()),
        # an old session found today is not stale
        "d#L1": item("d#L1", when=(NOW - timedelta(days=60)).isoformat(), found_at=NOW.isoformat()),
    })
    assert s.expire(NOW) == 1
    assert [i["key"] for i in s.ripe(NOW)] == ["d#L1", "b#L1"]
    assert s.items["c#L1"]["status"] == "expired"


# =============================================================== the check


def test_parse_decisions_keeps_only_valid_ones():
    good = file_it()
    text = "prose first " + decisions(
        good,
        {**file_it("T2"), "reason": "done-later"},          # file but not still-open
        {**file_it("T3"), "project": "elsewhere"},          # project not listed
        {**file_it("T4"), "title": "short"},                # title too short
        {"id": "T5", "file": False, "reason": "set-aside", "note": "declined in a later session"},
        {"id": "T9", "file": False, "reason": "unsure"},    # not in the batch
        {**file_it("T1"), "title": "a second decision for T1"},
    )
    out = mt.parse_decisions(text, ["T1", "T2", "T3", "T4", "T5"], ["host-repo"])
    assert sorted(out) == ["T1", "T5"]
    assert out["T1"]["project"] == "host-repo" and out["T5"]["reason"] == "set-aside"
    assert mt.parse_decisions("not json", ["T1"], ["host-repo"]) == {}


def _spec_maker(calls):
    def make(prompt, toolset, k):
        calls.append((prompt, toolset, k))
        return {"prompt": prompt, "toolset": toolset}
    return make


def test_the_check_prompt_opens_as_a_miner_session_and_lists_items_and_projects():
    prompt = mt.check_prompt({"T1": item()}, [Project("host-repo", "Host", "the export tool")])
    assert any(prompt.startswith(h) for h in miner.SELF_PROMPT_HEADERS)
    assert "T1: session s1" in prompt and "“The README still does not mention --dry-run.”" in prompt
    assert "- host-repo: Host — the export tool" in prompt


def test_night_checks_ripe_items_files_approved_ones_and_respects_the_cap(tmp_path):
    s = mt.Store(tmp_path / "t.json", {
        "s1#L4": item("s1#L4", role="user"),
        "s2#L4": item("s2#L4", title="Fix the export path check"),
        "s3#L4": item("s3#L4", title="Add a changelog entry"),
        "s4#L4": item("s4#L4", when=(NOW - timedelta(hours=5)).isoformat()),  # not ripe yet
    })
    tr = FakeTracker()
    made: list = []
    answer_text = decisions(
        file_it("T1"),
        file_it("T2", title="Fix the export path check in export.sh"),
        {"id": "T3", "file": False, "reason": "done-later", "project": None, "title": None, "why": None,
         "note": "session s9 added it"},
    )
    rep = mt.night(s, tracker=tr, root=tmp_path, make_spec=_spec_maker(made),
                   call=lambda spec: FakeOutcome(ok=True, stdout=answer_text, cost_usd=0.1),
                   run_id="r1", cap=1, now=NOW)
    assert rep.ripe == 3 and rep.checked == 3 and rep.approved == 2 and rep.skipped == 1
    assert rep.filed == ["W-900"]
    assert s.items["s1#L4"]["status"] == "filed" and s.items["s1#L4"]["item"] == "W-900"
    assert s.items["s2#L4"]["status"] == "approved"  # over tonight's cap: filed next night
    assert s.items["s3#L4"]["status"] == "skipped" and s.items["s3#L4"]["decision"]["reason"] == "done-later"
    assert s.items["s4#L4"]["status"] == "held"
    created = tr.created[0]
    assert created["project"] == "host-repo"
    assert "Found by self-learn in session s1 (/work/host-repo, 2026-11-01), line 4" in created["why"]
    assert "“The README still does not mention --dry-run.”" in created["why"]
    assert created["quote"] == "The README still does not mention --dry-run."  # a line the person typed
    toolset = made[0][1]
    assert toolset.qualified_names == ("mcp__tasks__search_later_sessions", "mcp__tasks__tracker_items",
                                       "mcp__tasks__search_notes")
    # the next night files the one left over first, without a check call
    made.clear()
    rep2 = mt.night(s, tracker=tr, root=tmp_path, make_spec=_spec_maker(made),
                    call=lambda spec: pytest.fail("no ripe item: no call"), run_id="r2", cap=5, now=NOW)
    assert rep2.filed == ["W-901"] and made == []
    assert tr.created[1]["quote"] is None  # the assistant's words are never stored as the person's


def test_a_title_the_project_already_has_is_skipped_not_filed(tmp_path):
    s = mt.Store(tmp_path / "t.json", {"s1#L4": item()})
    tr = FakeTracker(existing={"host-repo": [{"id": "W-5", "stage": "task", "status": "accepted",
                                              "title": "Document the --dry-run flag in the export README"}]})
    rep = mt.night(s, tracker=tr, root=tmp_path, make_spec=_spec_maker([]),
                   call=lambda spec: FakeOutcome(ok=True, stdout=decisions(file_it())), run_id="r1", cap=5, now=NOW)
    assert rep.filed == [] and rep.duplicates == 1 and tr.created == []
    assert s.items["s1#L4"]["status"] == "skipped" and s.items["s1#L4"]["decision"]["reason"] == "already-tracked"


def test_a_tracker_that_does_not_answer_leaves_every_item_waiting(tmp_path):
    s = mt.Store(tmp_path / "t.json", {"s1#L4": item()})
    rep = mt.night(s, tracker=FakeTracker(fail_projects=True), root=tmp_path, make_spec=_spec_maker([]),
                   call=lambda spec: pytest.fail("no check without the tracker"), run_id="r1", cap=5, now=NOW)
    assert rep.failure and s.items["s1#L4"]["status"] == "held"
    # approved but the create fails: it stays approved
    s.items["s1#L4"].update(status="approved", decision={"file": True, "reason": "still-open", "project": "host-repo",
                                                         "title": "Document the flag", "why": "w" * 30, "note": ""})
    rep = mt.night(s, tracker=FakeTracker(fail_create=True), root=tmp_path, make_spec=_spec_maker([]),
                   call=lambda spec: pytest.fail("nothing ripe"), run_id="r2", cap=5, now=NOW)
    assert rep.filed == [] and rep.failure and s.items["s1#L4"]["status"] == "approved"


def test_a_failed_check_call_is_not_counted_against_its_items(tmp_path):
    s = mt.Store(tmp_path / "t.json", {"s1#L4": item()})
    rep = mt.night(s, tracker=FakeTracker(), root=tmp_path, make_spec=_spec_maker([]),
                   call=lambda spec: FakeOutcome(ok=False, failure="timed out"), run_id="r1", cap=5, now=NOW)
    assert rep.failure and s.items["s1#L4"]["status"] == "held" and s.items["s1#L4"]["checks"] == 0
    for n in range(3):  # three answers with no decision for it: given up on
        mt.night(s, tracker=FakeTracker(), root=tmp_path, make_spec=_spec_maker([]),
                 call=lambda spec: FakeOutcome(ok=True, stdout=decisions()), run_id=f"r{n}", cap=5, now=NOW)
    assert s.items["s1#L4"]["status"] == "skipped" and s.items["s1#L4"]["decision"]["reason"] == "unchecked"


def test_dry_run_checks_and_files_nothing(tmp_path):
    s = mt.Store(tmp_path / "t.json", {"s1#L4": item()})
    tr = FakeTracker()
    rep = mt.night(s, tracker=tr, root=tmp_path, make_spec=_spec_maker([]),
                   call=lambda spec: FakeOutcome(ok=True, stdout=decisions(file_it())), run_id="r1", cap=5,
                   dry_run=True, now=NOW)
    assert rep.approved == 1 and rep.filed == [] and tr.created == []


# ============================================================ search tool


def _line(kind, ts, text, n, **extra):
    if kind == "user":
        msg = {"role": "user", "content": text}
    else:
        msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return json.dumps({"type": kind, "uuid": f"u{n}", "timestamp": ts, "message": msg, **extra})


def test_search_later_sessions_reads_only_after_the_item_and_in_its_folders(tmp_path):
    rootdir = tmp_path / "projects"
    own = rootdir / "-w-repo" / "s1.jsonl"
    own.parent.mkdir(parents=True)
    own.write_text("\n".join([
        _line("assistant", "2026-11-01T10:00:00Z", "the README needs the dry-run flag", 1),
        _line("assistant", "2026-11-01T10:05:00Z", "I will document dry-run in the README", 2),
        _line("assistant", "2026-11-01T11:00:00Z", "README now documents dry-run", 3),
    ]) + "\n")
    wt = rootdir / "-w-repo--claude-worktrees-x" / "s2.jsonl"
    wt.parent.mkdir(parents=True)
    wt.write_text(_line("user", "2026-11-03T09:00:00Z", "did the README dry-run section land?", 1) + "\n"
                  + _line("assistant", "2026-10-01T09:00:00Z", "README dry-run old talk", 2) + "\n")
    other = rootdir / "-w-other" / "s3.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(_line("assistant", "2026-11-04T09:00:00Z", "README dry-run elsewhere", 1) + "\n")
    worker = rootdir / "-home-x--cache-self-learn-stage" / "s4.jsonl"
    worker.parent.mkdir(parents=True)
    worker.write_text(_line("assistant", "2026-11-04T09:00:00Z", "README dry-run in a worker", 1) + "\n")
    it = item(transcript=str(own), project_dir="-w-repo", line=2, entry_ts="2026-11-01T10:05:00Z")
    tools = mt.CheckTools({"T1": it}, rootdir, FakeTracker(), frozenset({"host-repo"}))
    text = tools.search_later_sessions("T1", "README dry-run")
    assert "same session" in text and "L3, AGENT: README now documents dry-run" in text
    assert "I will document" not in text and "needs the dry-run" not in text
    assert "session s2" in text and "YOU: did the README" in text and "old talk" not in text
    assert "elsewhere" not in text and "worker" not in text
    wide = tools.search_later_sessions("T1", "README dry-run", all_folders=True)
    assert "elsewhere" in wide and "in a worker" not in wide
    assert tools.dispatch("search_later_sessions", {"item": "T7", "words": "x y z"}).is_error
    assert tools.dispatch("tracker_items", {"project": "nope"}).is_error
    assert "No tracker items" in tools.tracker_items("host-repo")


# ================================================================ backfill


def test_backfill_dry_run_reads_whole_sessions_and_writes_nothing_live(home, root, cbackend, fake_tracker, tmp_path):
    sid = "s1aaaaaa-0000"
    path = write_session(root, sid, task_rows(sid, host(tmp_path)))
    cursors_before = miner._load_cursors()  # pyright: ignore[reportPrivateUsage]
    cbackend.answers[sid] = answer(tasks=[task()])
    cbackend.check_answer = decisions(file_it())
    report = miner.backfill_tasks(home, 14, dry_run=True)
    assert report["status"] == "ok" and report["sessions_read"] == 1 and report["found"] == 1
    assert report["check"]["approved"] == 1 and report["check"]["filed"] == []
    assert fake_tracker.created == []
    assert store().items == {}  # the live store is untouched
    assert miner._load_cursors() == cursors_before  # pyright: ignore[reportPrivateUsage]
    assert pending(home) == []
    assert Path(report["run_folder"], "tasks-report.json").is_file()
    assert path.is_file()


def test_backfill_files_into_the_live_store_and_respects_its_cap(home, root, cbackend, fake_tracker, tmp_path):
    sid = "s1aaaaaa-0000"
    write_session(root, sid, task_rows(sid, host(tmp_path)))
    cbackend.answers[sid] = answer(tasks=[task()])
    cbackend.check_answer = decisions(file_it())
    report = miner.backfill_tasks(home, 14, file_cap=0)
    assert report["check"]["filed"] == [] and store().items[f"{sid}#L4"]["status"] == "approved"
    report = miner.backfill_tasks(home, 14)
    assert report["found"] == 0  # already in the store
    assert report["check"]["filed"] == ["W-900"]
    assert fake_tracker.created[0]["title"] == "Document the --dry-run flag in the export README"


def test_backfill_refuses_days_out_of_range_and_runs_nothing_when_off(home, monkeypatch):
    with pytest.raises(ValueError):
        miner.backfill_tasks(home, 0)
    with pytest.raises(ValueError):
        miner.backfill_tasks(home, 31)
    monkeypatch.setenv("SELF_LEARN_MINER_TASKS_ENABLED", "0")
    assert miner.backfill_tasks(home, 3)["status"] == "disabled"
