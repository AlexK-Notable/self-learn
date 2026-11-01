"""Humane UI lane 3 (proposal §4, §5, §10): what the CLI hands the inbox and
the weekly report page.

- a nightly review's packet carries one row per case the run wrote, with its
  outcome group (``series.OUTCOME_GROUPS``) and the count per group;
- a case entry carries its decision's verb and confidence as fields, so a
  page never prints the Decision section's list as one paragraph;
- run titles are in words ("Nightly review, 31 October: 2 lessons
  decided"), never "lesson(s)";
- :func:`self_learn.weekly_facts.run_facts` counts from the run's record.

Person's-shell tests: the fixture deletes every agent marker. Each test
names the mutation it was checked against.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import attention, attention_packet, settings, weekly_facts

LESSONS = ("lrn-0000aa01", "lrn-0000aa02", "lrn-0000aa03", "lrn-0000aa04", "lrn-0000aa05",
           "lrn-0000aa06", "lrn-0000aa07", "lrn-0000aa08")


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_world(tmp_path: Path, monkeypatch, outcomes: tuple[str, ...], *,
               phases: dict[int, dict] | None = None, records_per_case: int = 1,
               because: str | None = None, trigger: str | None = None,
               lessons: tuple[str, ...] | None = None) -> tuple[Path, list[str]]:
    """A ledger with one lesson per outcome and a case deciding each, plus
    a steward run manifest naming the cases. Returns ``(ledger, case ids)``."""
    from ruamel.yaml import YAML

    from self_learn import cases
    from self_learn.ledger_ops import create_record
    from support import commit_all, make_behavior, make_env

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    case_ids: list[str] = []
    names = lessons or LESSONS
    made: list[str] = []
    for index in range(len(outcomes) * records_per_case):
        create_record(env.ledger, make_behavior(
            scope="user", record_id=names[index],
            trigger=trigger or f"About to do thing number {index // records_per_case}.",
            instruction="Do it carefully."))
        made.append(names[index])
    commit_all(env.ledger, "seed the lessons")
    for index, outcome in enumerate(outcomes):
        lesson = made[index * records_per_case]
        records = made[index * records_per_case:(index + 1) * records_per_case]
        stage = tmp_path / f"case-{index}.yaml"
        with stage.open("w", encoding="utf-8") as fh:
            YAML().dump({
                "kind": "resolution", "trigger": "nightly", "outcome": outcome,
                "records": records, "scope": "user", "question": f"Should rule {index} stand?",
                "evidence": [{"ref": "transcript:s#L1", "quote": "the words"}],
                "decision": {"verb": outcome,
                             "because": because or (f"Reason {index} opens here. It goes on with more "
                                                    "detail that the line leaves out."),
                             "confidence": "settled"},
                "dependencies": {"statements": [], "user_model": [], "conditions": [],
                                 "capabilities": []},
            }, fh)
        case_ids.append(cases.record(env.ledger, stage, actor="human"))
    runs = env.ledger / "cases" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-cccccccccccc.json").write_text(json.dumps({
        "actor": "steward", "run_id": "run-cccccccccccc", "completed_at": _now(),
        "decided": made,
        "cases": {c: {"phase": "complete", **((phases or {}).get(i) or {})}
                  for i, c in enumerate(case_ids)},
    }), encoding="utf-8")
    return env.ledger, case_ids


def test_a_nightly_reviews_packet_counts_its_decisions_by_outcome_group(tmp_path, monkeypatch):
    """Mutations: count every row under `use` -> red; drop the lesson title
    from a row -> red; take the reason from the question -> red."""
    ledger, case_ids = _run_world(tmp_path, monkeypatch, ("route", "reject", "defer", "reject"))
    item_id = attention.item_id("decided.steward-run", "run-cccccccccccc")
    packet = attention_packet.build(ledger, item_id)
    run = packet["run"]
    assert run["counts"] == {"use": 1, "no": 2, "later": 1, "kept": 0, "refused": 0}
    assert run["other"] == 0 and run["error"] is None
    rows = {r["case"]: r for r in run["decisions"]}
    assert set(rows) == set(case_ids)
    first = rows[case_ids[0]]
    assert first["verb"] == "route" and first["group"] == "use"
    assert first["record"] == LESSONS[0]
    assert first["title"] == "About to do thing number 0."
    assert first["reason"] == "Reason 0 opens here. It goes on with more detail that the line leaves out."
    assert first["carried_out"] is True
    # Rows come in group order: use, then no, then later.
    assert [r["group"] for r in run["decisions"]] == ["use", "no", "no", "later"]


def test_only_a_nightly_review_carries_a_run_block(tmp_path, monkeypatch):
    """Mutation: build the block for every item -> red."""
    ledger, case_ids = _run_world(tmp_path, monkeypatch, ("route",))
    item = attention._new_item(  # noqa: SLF001
        "ask.system-change", "q-x", title="Bind it?", since=_now(), by="overseer",
        refs=[case_ids[0]], question="Bind it?")
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    packet = attention_packet.build(ledger, item["id"])
    assert packet["evidence"][0]["kind"] == "case"  # control: the case rendered
    assert packet["run"] is None


def test_a_case_entry_carries_its_decisions_verb_and_confidence(tmp_path, monkeypatch):
    """Mutation: drop the `verb` field -> red."""
    ledger, case_ids = _run_world(tmp_path, monkeypatch, ("reject",))
    item_id = attention.item_id("decided.steward-run", "run-cccccccccccc")
    case = next(e for e in attention_packet.build(ledger, item_id)["evidence"] if e["kind"] == "case")
    assert case["verb"] == "reject" and case["confidence"] == "settled"
    assert case["because"].startswith("Reason 0 opens here.")


def test_a_short_first_sentence_takes_the_next_one_with_it():
    """Mutation: return the first sentence alone -> red."""
    assert attention_packet._first_sentence("Evidence check. The quote is in the one entry.") == (  # noqa: SLF001
        "Evidence check. The quote is in the one entry.")
    long = "A first sentence that is already long enough to say something useful. More."
    assert attention_packet._first_sentence(long) == (  # noqa: SLF001
        "A first sentence that is already long enough to say something useful.")


def test_run_titles_are_in_words(tmp_path, monkeypatch):
    """Proposal §4, §10. Mutations: the old "decided N lesson(s)" title ->
    red; no singular -> red."""
    ledger, _ = _run_world(tmp_path, monkeypatch, ("route",))
    items = attention.collect(ledger, all_items=True)
    title = next(i["title"] for i in items if i["kind"] == "decided.steward-run")
    assert title.startswith("Nightly review, ") and title.endswith(": 1 decision")
    assert "lesson(s)" not in title
    assert attention.plural(27, "lesson") == "27 lessons"
    assert attention.day_words("2026-11-01") == "1 November"
    assert attention.day_words("not a date") == "not a date"


def test_run_facts_count_from_the_runs_record(tmp_path):
    """Mutations: count every finding as examined -> red; report staged as
    decided -> red; a non-overseer record -> must be None."""
    home = tmp_path / "ledger"
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True)
    (runs / "92d6fec6.json").write_text(json.dumps({
        "actor": "overseer", "run_id": "92d6fec6", "model": "m-1", "date": "2026-11-01",
        "status": "complete", "started": "2026-11-01T14:54:30Z",
        "progress_at": "2026-11-01T15:21:43Z", "population_count": 70,
        "findings": [{"kind": "examined"}, {"kind": "examined"}, {"kind": "dependency-moved"}],
        "decisions": {"staged": 7, "dropped": 1, "lines_dropped": 0},
        "questions": {"questions": [{"id": "q-1"}]},
    }), encoding="utf-8")
    facts = weekly_facts.run_facts(home, "92d6fec6")
    assert facts is not None
    assert facts["examined"] == 2 and facts["population"] == 70
    assert facts["decided"] == 6 and facts["decisions_written"] == 7 and facts["decisions_dropped"] == 1
    assert facts["questions"] == 1
    assert facts["finished_at"] == "2026-11-01T15:21:43Z" and facts["model"] == "m-1"
    assert weekly_facts.run_facts(home, "deadbeef") is None
    assert weekly_facts.run_facts(home, "../etc") is None
    (runs / "aaaaaaaa.json").write_text(json.dumps({"actor": "steward"}), encoding="utf-8")
    assert weekly_facts.run_facts(home, "aaaaaaaa") is None


def test_the_report_heading_parses():
    """Mutation: drop the run group from the pattern -> red."""
    heading = weekly_facts.parse_heading(
        "# Overseer report — 2026-11-01   run 92d6fec6   actor overseer   model claude-x\n\n## Examined\n")
    assert heading == {"date": "2026-11-01", "run": "92d6fec6", "actor": "overseer", "model": "claude-x"}
    assert weekly_facts.parse_heading("# Overseer report\n") is None


# ------------------------------------------------------------ gate r1 fold


def test_a_refused_decision_is_counted_as_refused_never_as_done(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1, the shape of att-73a9e25f8c62: a case whose run
    record says `phase: refused` (its outcome still `route`), and one whose
    result applied nothing and refused one. Mutations: ignore the phase ->
    red; ignore the result's summary -> red."""
    ledger, case_ids = _run_world(tmp_path, monkeypatch, ("route", "replaced", "reject"), phases={
        0: {"phase": "refused"},
        1: {"phase": "complete", "result": {"summary": {"applied": 0, "refused": 1, "total": 1}}},
    })
    run = attention_packet.build(ledger, attention.item_id("decided.steward-run", "run-cccccccccccc"))["run"]
    assert run["counts"] == {"use": 0, "no": 1, "later": 0, "kept": 0, "refused": 2}
    rows = {r["case"]: r for r in run["decisions"]}
    assert rows[case_ids[0]]["group"] == "refused" and rows[case_ids[0]]["verb"] == "route"
    assert rows[case_ids[0]]["carried_out"] is False
    assert rows[case_ids[1]]["group"] == "refused"
    assert rows[case_ids[2]]["group"] == "no" and rows[case_ids[2]]["carried_out"] is True


def test_the_title_counts_the_same_decisions_as_the_page(tmp_path, monkeypatch):
    """Gate r1 MAJOR 2: two cases deciding four lessons -- the title says 2
    decisions and the run block holds 2 rows whose group counts sum to 2.
    Mutation: the title counts the decided lessons -> red."""
    ledger, _ = _run_world(tmp_path, monkeypatch, ("route", "reject"), records_per_case=2)
    item = next(i for i in attention.collect(ledger, all_items=True) if i["kind"] == "decided.steward-run")
    run = attention_packet.build(ledger, item["id"])["run"]
    shown = len(run["decisions"])
    assert shown == 2 and sum(run["counts"].values()) + run["other"] == shown
    assert item["title"].endswith(f": {shown} decisions")


def test_a_large_run_keeps_the_packet_within_its_cap(tmp_path, monkeypatch):
    """Gate r1 MAJOR 3: eight cases with long titles and reasons. At the
    real budget the block fits whole with its lines shortened; at a budget
    too small for eight rows it drops rows from the end and says how many,
    while the counts still cover every decision; the packet stays within
    MAX_BYTES with its evidence there. Mutations: no budget (`_fit_run` a
    no-op) -> red; the old 600-character `because` per row -> red."""
    long_reason = "This opening sentence is long enough to be kept whole. " + "Detail. " * 300
    ledger, _ = _run_world(tmp_path, monkeypatch, ("route",) * 8, because=long_reason,
                           trigger="About to " + "do a long and specific thing " * 20)
    item_id = attention.item_id("decided.steward-run", "run-cccccccccccc")
    packet = attention_packet.build(ledger, item_id)
    rows = packet["run"]["decisions"]
    assert len(rows) == 8 and packet["run"]["omitted"] == 0  # control: every row is there
    assert all(len(r["title"]) <= attention_packet.MAX_RUN_TITLE_CHARS for r in rows)
    assert all("because" not in r and "question" not in r for r in rows)
    assert packet["limits"]["bytes"] <= attention_packet.MAX_BYTES and packet["evidence"]

    monkeypatch.setattr(attention_packet, "MAX_RUN_BYTES", 1200)
    small = attention_packet.build(ledger, item_id)["run"]
    block = len(json.dumps(small["decisions"], ensure_ascii=False).encode("utf-8"))
    assert block <= 1200
    assert small["omitted"] > 0 and len(small["decisions"]) + small["omitted"] == 8
    assert sum(small["counts"].values()) == 8


def test_a_reason_reads_without_ids_or_line_references():
    """Gate r1 NIT 8. Mutation: return the text unchanged -> red."""
    plain = attention_packet._plain_reason(  # noqa: SLF001
        "What the user said (L17432, typed): yes; at L20505 they agreed; "
        "since case-1f29abaf the reading um-c4e5@r1 held, as stmt-46ca2ac9 says.")
    assert plain == ("What the user said: yes; they agreed; since an earlier case the reading held, "
                     "as your statement says.")


def test_question_states_say_where_each_question_stands(tmp_path, monkeypatch):
    """Gate r1 MINOR 6. Mutations: every question open -> red; the older of
    two answers kept -> red."""
    from self_learn import statements
    from self_learn.overseer import conversation

    monkeypatch.setattr(conversation, "_load_questions", lambda home: [{"id": "q-still"}])
    monkeypatch.setattr(conversation, "_unanswered", lambda home, rows: (list(rows), set()))
    monkeypatch.setattr(conversation, "choice_rows", lambda home: [])
    monkeypatch.setattr(statements, "list_statements", lambda home: [
        {"id": "stmt-1", "at": "2026-10-06T05:00:00Z", "verbatim": "first",
         "answers": {"kind": "question", "ref": "q-done"}},
        {"id": "stmt-2", "at": "2026-10-07T05:00:00Z", "verbatim": "yes to both",
         "answers": {"kind": "question", "ref": "q-done"}},
    ])
    states = weekly_facts.question_states(tmp_path, ["q-done", "q-still", "q-gone", "not an id"])
    assert states["q-done"] == {"state": "answered", "answer": "yes to both", "at": "2026-10-07T05:00:00Z"}
    assert states["q-still"]["state"] == "open"
    assert states["q-gone"] == {"state": "closed", "answer": None, "at": None}
    assert "not an id" not in states
