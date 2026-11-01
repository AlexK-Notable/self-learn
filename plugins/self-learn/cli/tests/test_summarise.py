"""Humane UI lane 5 (S-NEXT-humane-l5, proposal §7): report summaries.

- `self-learn summarise` (the on-demand "Summarise this"): one model call on
  a miss, none on a summary saved for the exact text, a new call for a
  changed text, refused before any spawn when it would bill money, saved in
  the ledger under the lock (in the cache while it is STOPPED), its cost
  recorded;
- the overseer's optional "## In short" heading (scheduled, no extra call);
- a nightly review's counted "In short" (no model at all).

Every model session runs on `invocation.FakeBackend` (`ask._backend`) or a
scripted backend object; no test crosses the real model boundary. Sandbox
ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import io
import json

import pytest

from self_learn import (
    ask, attention, attention_packet, intents, miner, settings, settings_plain, summarise,
)
from self_learn.invocation import Outcome
from self_learn.invocation.fake import Exits, FakeBackend, Streams, Text
from self_learn.overseer import run as overseer_run
from support import git, make_home
from test_recover_or_refuse import _plant_stop

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX")
REPORT = """# Overseer report — 2026-10-25   run 1a2b3c4d   actor overseer   model m

## Examined
- The steward's decisions hold on 33 of the cases it read.

## Decided in the user's stead
- none

## Hooks
- none

## User model
- none

## Catalogue health
- none

## Questions for you
- none

## Refused / could not do
- none
"""
ANSWER = ("The overseer re-checked 33 of the steward's decisions and agreed with them. "
          "It changed nothing. Nothing needs you.")


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    for var in (*BILLING_VARS, "SELF_LEARN_PROVIDER", "SELF_LEARN_SUMMARY_MODEL",
                "SELF_LEARN_ASK_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    person_home = tmp_path / "person-home"
    (person_home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(person_home))
    monkeypatch.setattr(attention, "_systemctl_active", lambda unit: True)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    (h / "overseer").mkdir(exist_ok=True)
    (h / "overseer" / "2026-10-25-report.md").write_text(REPORT, encoding="utf-8")
    git(h, "add", "--", "overseer/2026-10-25-report.md")
    git(h, "commit", "-q", "-m", "a weekly report")
    return h


def _run(monkeypatch, home, target, steps, **kw):
    backend = FakeBackend(steps)
    monkeypatch.setattr(ask, "_backend", backend)
    out, err = io.StringIO(), io.StringIO()
    code, emitter = summarise.run_summarise(home, target, stream=True, out=out, err=err, **kw)
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    return code, events, backend, err.getvalue()


def _saved_files(home):
    return sorted((home / "summaries").rglob("*.json")) if (home / "summaries").exists() else []


# ------------------------------------------------------------ the verb


def test_a_miss_makes_exactly_one_call_and_saves_the_summary_in_the_ledger(monkeypatch, home):
    """Mutation: never save -> red (no file, no commit); the model is the
    surface's -> red (`spec.model`)."""
    code, events, backend, err = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                      [Text(ANSWER)])
    assert code == 0, err
    assert len(backend.specs) == 1
    spec = backend.specs[0]
    assert (spec.surface, spec.max_turns, spec.model) == ("ask", 1, "sonnet")
    assert spec.containment.allowed_tools in ("", None)
    assert spec.prompt.startswith(f"{summarise.SESSION_OPENING}overseer-report:2026-10-25.")
    assert "33 of the cases it read" in spec.prompt
    assert spec.prompt.startswith(miner.SELF_PROMPT_HEADERS), "the miner must halt this session"
    sha = summarise.source(home, "overseer-report", "2026-10-25").sha256
    path = summarise.summary_path(home, "overseer-report", sha)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["text"] == ANSWER and record["source_sha256"] == sha
    assert record["ref"] == "2026-10-25" and record["model"] == "sonnet"
    assert record["by"] == summarise.BY_PERSON
    tracked = git(home, "ls-files", "--", str(path.relative_to(home))).stdout.strip()
    assert tracked, "the summary is committed to the ledger"
    assert git(home, "status", "--porcelain").stdout.strip() == ""
    assert [e["ev"] for e in events][0] == "start" and events[-1]["ev"] == "done"
    assert events[-1]["written"] is True


def test_a_summary_saved_for_the_exact_text_is_printed_with_no_model_call(monkeypatch, home):
    """Mutation: drop the saved-hash check -> red (the empty FakeBackend
    has no step, and `specs` records the call)."""
    assert _run(monkeypatch, home, "overseer-report:2026-10-25", [Text(ANSWER)])[0] == 0
    head = git(home, "rev-parse", "HEAD").stdout
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25", [])
    assert code == 0
    assert backend.specs == []
    assert events[-1]["ev"] == "done" and events[-1]["text"] == ANSWER
    assert events[-1]["written"] is False
    assert git(home, "rev-parse", "HEAD").stdout == head  # nothing written either
    # The latest report is the same bytes: it shares the dated summary.
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:latest", [])
    (home / "overseer" / "latest-report.md").write_text(REPORT, encoding="utf-8")
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:latest", [])
    assert code == 0 and backend.specs == [] and events[-1]["text"] == ANSWER


def test_a_changed_report_does_not_reuse_the_old_summary(monkeypatch, home):
    """Mutation: key the summary by ref instead of the text's hash -> red."""
    assert _run(monkeypatch, home, "overseer-report:2026-10-25", [Text(ANSWER)])[0] == 0
    report = home / "overseer" / "2026-10-25-report.md"
    report.write_text(REPORT.replace("33 of", "34 of"), encoding="utf-8")
    view = summarise.state(home, "overseer-report", "2026-10-25")
    assert view["summary"] is None
    assert view["stale"] is not None and view["stale"]["text"] == ANSWER  # shown greyed
    code, _events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                     [Text("A newer summary.")])
    assert code == 0 and len(backend.specs) == 1
    assert "34 of" in backend.specs[0].prompt
    view = summarise.state(home, "overseer-report", "2026-10-25")
    assert view["summary"]["text"] == "A newer summary." and view["stale"] is None
    assert len(_saved_files(home)) == 2


def test_again_spends_a_second_call_on_the_same_text(monkeypatch, home):
    assert _run(monkeypatch, home, "overseer-report:2026-10-25", [Text(ANSWER)])[0] == 0
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                    [Text("Written again.")], again=True)
    assert code == 0 and len(backend.specs) == 1
    sha = summarise.source(home, "overseer-report", "2026-10-25").sha256
    assert summarise.saved(home, "overseer-report", sha)["text"] == "Written again."


@pytest.mark.parametrize("var,value", [("ANTHROPIC_API_KEY", "x" * 12),
                                       ("CLAUDE_CODE_USE_BEDROCK", "1")])
def test_a_setup_that_would_bill_money_is_refused_before_any_call(monkeypatch, home, var, value):
    """Mutation: skip `ask.spec_billing` -> red (a call is made)."""
    monkeypatch.setenv(var, value)
    code, events, backend, err = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                      [Text(ANSWER)])
    assert code == summarise.EXIT_MONEY == 4
    assert backend.specs == []
    assert events[-1]["ev"] == "error" and events[-1]["code"] == "money"
    assert "subscription" in err
    assert _saved_files(home) == []


def test_the_report_goes_out_redacted_and_an_answer_with_a_secret_is_not_saved(monkeypatch, home):
    report = home / "overseer" / "2026-10-25-report.md"
    report.write_text(REPORT.replace("- none\n", f"- a token {TOKEN} was seen\n", 1),
                      encoding="utf-8")
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                    [Text(f"It found {TOKEN}.")])
    assert TOKEN not in backend.specs[0].prompt and "[redacted:" in backend.specs[0].prompt
    assert code == 1 and events[-1]["code"] == "secret"
    assert all(TOKEN not in json.dumps(e) for e in events)
    assert _saved_files(home) == []


def test_unknown_and_malformed_targets(monkeypatch, home):
    assert _run(monkeypatch, home, "overseer-report:2026-01-01", [])[0] == 2
    assert _run(monkeypatch, home, "overseer-report:../etc", [])[0] == 64
    assert _run(monkeypatch, home, "something:else", [])[0] == 64
    assert _run(monkeypatch, home, "inbox-item:att-000000000000", [])[0] == 2


def test_a_failed_call_saves_nothing_and_says_why(monkeypatch, home):
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                    [Exits(1, "boom")])
    assert code == 1 and len(backend.specs) == 1
    assert events[-1]["ev"] == "error" and "could not be written" in events[-1]["message"]
    assert _saved_files(home) == []


class _CostBackend:
    """A scripted backend whose outcome carries a cost, as `SdkOutcome` does."""

    def __init__(self):
        self.specs = []

    def write_session(self, spec):
        self.specs.append(spec)
        return _Costed(ok=True, rc=0, stdout=ANSWER, detail="", failure=None)


from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class _Costed(Outcome):
    cost_usd: float | None = 0.0312
    session_id: str | None = "sess-1"


def test_the_real_cost_of_a_run_is_recorded_with_the_summary_and_in_the_journal(monkeypatch, home):
    """Mutation: drop `cost_usd` from the record -> red."""
    backend = _CostBackend()
    monkeypatch.setattr(ask, "_backend", backend)
    code, _emitter = summarise.run_summarise(home, "overseer-report:2026-10-25",
                                             out=io.StringIO(), err=io.StringIO())
    assert code == 0 and len(backend.specs) == 1
    sha = summarise.source(home, "overseer-report", "2026-10-25").sha256
    record = summarise.saved(home, "overseer-report", sha)
    assert record["cost_usd"] == pytest.approx(0.0312)
    assert record["session"] == "sess-1" and isinstance(record["duration_secs"], float)
    rows = [json.loads(line) for line in
            summarise.journal_path(home).read_text(encoding="utf-8").splitlines()]
    assert [(r["outcome"], r["cost_usd"]) for r in rows] == [("saved", pytest.approx(0.0312))]


def test_a_summary_written_while_the_ledger_is_stopped_waits_in_the_cache(monkeypatch, home):
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    code, _events, _backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                      [Text(ANSWER)])
    assert code == 0
    sha = summarise.source(home, "overseer-report", "2026-10-25").sha256
    assert not summarise.summary_path(home, "overseer-report", sha).exists()
    assert summarise.pending_path(home, "overseer-report", sha).exists()
    # Reads see it meanwhile, so a reload never asks again.
    assert summarise.saved(home, "overseer-report", sha)["text"] == ANSWER
    code, _events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25", [])
    assert code == 0 and backend.specs == []


def test_a_pending_summary_moves_into_the_ledger_with_the_next_save(home):
    record = {"schema": 1, "kind": "overseer-report", "ref": "2026-10-25",
              "source_sha256": "a" * 64, "text": "kept while stopped", "created_at": "x"}
    pending = summarise.pending_path(home, "overseer-report", "a" * 64)
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps(record), encoding="utf-8")
    fresh = {**record, "source_sha256": "b" * 64, "text": "new"}
    assert summarise.save(home, fresh) == "ledger"
    assert not pending.exists()
    assert summarise.summary_path(home, "overseer-report", "a" * 64).exists()
    assert git(home, "status", "--porcelain").stdout.strip() == ""


def _steward_run(home, n_cases=3, decided=2):
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-a.json").write_text(json.dumps({
        "actor": "steward", "run_id": "run-a", "started_at": "2026-10-31T03:00:00Z",
        "completed_at": "2026-10-31T03:10:00Z",
        "decided": [f"lrn-0000000{n}" for n in range(decided)],
        "cases": {f"case-0000{n:04x}": {"phase": "applied"} for n in range(n_cases)}}),
        encoding="utf-8")
    items = [i for i in attention.collect(home, all_items=True)
             if i["kind"] == "decided.steward-run"]
    assert len(items) == 1
    return items[0]


def test_an_inbox_items_source_is_the_same_from_the_pages_packet(monkeypatch, home):
    """The page hashes the packet it already has (`attention packet --json`);
    the verb hashes the packet it builds. They must agree, or a saved
    summary is never found again."""
    from self_learn import cases

    item_id = _steward_run(home)["id"]
    packet = json.loads(json.dumps(attention_packet.build(home, item_id,
                                                          decided_reader=cases.decided_text)))
    assert (summarise.source_from_packet(item_id, packet).sha256
            == summarise.source(home, "inbox-item", item_id).sha256)
    view = summarise.state(home, "inbox-item", item_id, packet=packet)
    assert view["summary"] is None and view["sha256"]


def test_an_inbox_item_that_is_not_a_report_is_refused_without_a_call(monkeypatch, home):
    """Gate r1 NIT 5. Mutation: drop the report-kind check -> red (a call
    is made for a login hold)."""
    at = "2026-10-31T03:00:00Z"
    journal = attention.cache_dir(home) / "steward" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"ts": at, "status": "held-environment",
                                   "cause": "Failed to authenticate"}) + "\n", encoding="utf-8")
    item_id = attention.item_id("hold.credentials", f"credentials@{at}")
    assert attention.find(home, item_id) is not None  # control: the item exists
    code, events, backend, _ = _run(monkeypatch, home, f"inbox-item:{item_id}", [Text(ANSWER)])
    assert code == 2 and backend.specs == []
    assert "not a report" in events[-1]["message"]
    code, _events, backend, _ = _run(monkeypatch, home,
                                     f"inbox-item:{_steward_run(home)['id']}", [Text(ANSWER)])
    assert code == 0 and len(backend.specs) == 1  # control: a report item is summarised


def test_show_reads_files_only(monkeypatch, home, capsys):
    """`--show` never reaches a backend."""
    monkeypatch.setattr(ask, "_backend", FakeBackend([]))
    import argparse

    code = summarise.dispatch(argparse.Namespace(target="overseer-report:2026-10-25", show=True,
                                                 again=False, stream=False, as_json=False))
    assert code == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["summary"] is None and shown["sha256"]


def test_models_summary_defaults_to_sonnet_with_plain_words():
    setting = settings.by_name("models.summary")
    assert setting.default() == "sonnet" and setting.tier == "A"
    words = settings_plain.plain_for("models.summary")
    assert words.group == "models" and words.label == "Summaries"


# ------------------------------------------------------ scheduled "In short"


def _with_in_short(report: str, where: str = "first") -> str:
    section = "## In short\nThe overseer checked the week. Nothing needs you.\n\n"
    if where == "first":
        return report.replace("## Examined", section + "## Examined", 1)
    return report.rstrip("\n") + "\n\n" + section


def test_the_overseer_report_accepts_an_in_short_first_and_does_not_require_it(tmp_path):
    """Mutation: drop the optional orders from `_heading_orders` -> red."""
    path = tmp_path / "report.md"
    path.write_text(_with_in_short(REPORT), encoding="utf-8")
    overseer_run._validate_model_report(path)
    assert overseer_run._repair_report_headings(path) == []
    path.write_text(REPORT, encoding="utf-8")
    overseer_run._validate_model_report(path)


def test_an_in_short_written_last_is_moved_first(tmp_path):
    path = tmp_path / "report.md"
    path.write_text(_with_in_short(REPORT, "last"), encoding="utf-8")
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._validate_model_report(path)
    notes = overseer_run._repair_report_headings(path)
    assert any("out of order" in n for n in notes)
    text = path.read_text(encoding="utf-8")
    headings = [line[3:] for line in text.splitlines() if line.startswith("## ")]
    assert headings[0] == "In short" and headings[1] == "Examined"
    assert summarise.scheduled_in_short(text) == "The overseer checked the week. Nothing needs you."


def test_a_published_report_keeps_the_overseers_in_short(tmp_path, monkeypatch):
    from test_report_headings import _published, _run_with_report

    home, result = _run_with_report(tmp_path, monkeypatch, _with_in_short)
    assert (result.status, result.code) == ("applied", 0), result
    report = _published(home)
    assert summarise.scheduled_in_short(report) == (
        "The overseer checked the week. Nothing needs you.")
    headings = [line[3:].partition(" (")[0] for line in report.splitlines()
                if line.startswith("## ")]
    assert headings[0] == "In short"


def test_the_phase_b_prompt_asks_for_in_short_first(tmp_path):
    """Mutation: drop "In short" from the prompt's heading list -> red."""
    from self_learn.overseer import formats

    flat = " ".join(overseer_run._phase_b_prompt(tmp_path, (), ()).split())  # noqa: SLF001
    assert "in this exact order: In short; Examined;" in flat
    assert "holds is true when the steward's decision stands" in flat
    assert formats.closed_sets()["report_in_short_heading"] == "In short"
    assert "holds" in formats.closed_sets()["findings"]["entry_keys"]


def test_scheduled_in_short_is_none_without_the_section():
    assert summarise.scheduled_in_short(REPORT) is None
    assert summarise.scheduled_in_short(None) is None
    assert summarise.scheduled_in_short("## In short\n- none\n## Examined\n") is None


# ------------------------------------------------- counted nightly review


def test_a_nightly_reviews_in_short_is_counted_in_words():
    """Gate r1 MINOR 4: one unit, decisions, so the total is the title's;
    the not-carried-out group is said apart. Mutations: count every verb
    under `use` -> red; say a zero group -> red; leave the refused group
    out of the total -> red."""
    words = attention_packet.counted_in_short(
        {"use": 9, "no": 4, "later": 3, "kept": 11, "refused": 2})
    assert words == ("29 decisions: 9 put to use, 4 turned down, 3 left for later and 11 "
                     "looked at and kept as they are. 2 were not carried out, so nothing "
                     "changed for them.")
    words = attention_packet.counted_in_short({"use": 0, "no": 1, "later": 0, "kept": 0},
                                              hooks_on=2)
    assert words == ("1 decision: 1 turned down. It turned on 2 warnings that run before "
                     "matching commands.")
    assert "for later" not in words and "to use" not in words
    assert attention_packet.counted_in_short({}) == "The run's record lists no decisions."


def test_the_counted_total_is_the_titles_count_with_a_parked_case(tmp_path, monkeypatch):
    """Gate r1 MINOR 4, live: a run with 14 decided lessons and 15 cases
    (one parked) read "14 lessons decided" over a box totalling 15. The
    title and the box now count the same cases. Mutation: total the box
    from `decided` -> red."""
    import re as _re

    from support import make_home as _mk

    h = _mk(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    item = _steward_run(h, n_cases=3, decided=2)
    packet = attention_packet.build(h, item["id"])
    title_n = int(_re.search(r": (\d+) decision", item["title"]).group(1))
    box_n = int(_re.match(r"(\d+) decision", packet["run"]["in_short"]).group(1))
    assert title_n == box_n == 3


# ----------------------------------------- the week's review, in counts


def test_review_counts_read_the_verdicts_and_the_dropped_findings():
    """Mutations: count every examined finding as agreed -> red; count the
    dropped findings from the kept ones -> red."""
    written = {"findings": [
        {"case": "case-00000001", "kind": "examined", "text": "a", "holds": True},
        {"case": "case-00000002", "kind": "examined", "text": "b", "holds": True},
        {"case": "case-00000003", "kind": "examined", "text": "c", "holds": False},
        {"case": "case-00000004", "kind": "examined", "text": "d"},
        {"case": "case-00000005", "kind": "examined", "text": "e", "holds": "yes"},
        {"case": "case-99999999", "kind": "examined", "text": "f", "holds": True},
    ]}
    selected = tuple(f"case-0000000{n}" for n in range(1, 6))
    clean, examined, dropped = overseer_run._validate_findings(written, selected)
    assert len(clean) == 4 and any("holds must be true or false" in d for d in dropped)
    counts = overseer_run.review_counts(written, clean)
    assert counts == {"examined": 4, "agreed": 2, "disagreed": 1, "no_verdict": 1,
                      "findings_dropped": 2}
    assert overseer_run.review_counts({"findings": []}, [], parsed=False)["findings_dropped"] is None
    assert overseer_run.review_counts({"findings": []}, [], withheld=True)["findings_dropped"] is None


def test_a_published_run_records_its_review_counts(tmp_path, monkeypatch):
    """The run record carries `review` (read by the weekly report's tiles).
    Mutation: never pass `review` to the record -> red."""
    from self_learn import weekly_facts
    from test_report_headings import _run_with_report

    home, result = _run_with_report(tmp_path, monkeypatch, lambda text: text)
    assert (result.status, result.code) == ("applied", 0), result
    record = json.loads((home / "cases" / "runs" / f"{result.run}.json").read_text())
    review = record["review"]
    assert set(review) == {"examined", "agreed", "disagreed", "no_verdict", "findings_dropped"}
    assert review["findings_dropped"] == 0
    facts = weekly_facts.run_facts(home, result.run)
    assert facts["agreed"] == review["agreed"]
    assert facts["findings_dropped"] == 0


def test_weekly_facts_leave_the_review_counts_out_for_an_older_record(tmp_path):
    from self_learn import weekly_facts

    runs = tmp_path / "cases" / "runs"
    runs.mkdir(parents=True)
    base = {"actor": "overseer", "run_id": "1a2b3c4d", "findings": []}
    (runs / "1a2b3c4d.json").write_text(json.dumps(base))
    facts = weekly_facts.run_facts(tmp_path, "1a2b3c4d")
    assert facts["examined"] == 0  # control: the record was read
    assert facts["agreed"] is None and facts["findings_dropped"] is None
    (runs / "1a2b3c4d.json").write_text(json.dumps(
        {**base, "review": {"agreed": 33, "disagreed": 2, "no_verdict": 0, "findings_dropped": 5}}))
    facts = weekly_facts.run_facts(tmp_path, "1a2b3c4d")
    assert (facts["agreed"], facts["disagreed"], facts["findings_dropped"]) == (33, 2, 5)


def test_a_commit_the_ledger_refuses_is_undone_at_once_and_shows_as_not_saved(
        monkeypatch, home):
    """Gate r1 MINOR 3 (seen live: a ledger with no git identity refused the
    commit, the summary stayed staged and the page showed it as saved).
    Mutation: drop the undo -> red (file left, staged, shown as saved)."""
    from self_learn import gitops

    def refuse(*args, **kwargs):
        raise gitops.GitOpsError("commit refused (test)")

    monkeypatch.setattr(gitops, "stage_and_commit", refuse)
    code, events, backend, _ = _run(monkeypatch, home, "overseer-report:2026-10-25",
                                    [Text(ANSWER)])
    assert code == 1 and len(backend.specs) == 1  # control: the model was called
    assert events[-1]["ev"] == "error" and "nothing was kept" in events[-1]["message"]
    assert git(home, "status", "--porcelain").stdout.strip() == ""
    assert not list(intents.intents_dir(home).glob("*.json"))
    view = summarise.state(home, "overseer-report", "2026-10-25")
    assert view["sha256"] and view["summary"] is None  # not shown as saved
    rows = [json.loads(line) for line in
            summarise.journal_path(home).read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "not-saved"


def test_a_summary_rolled_forward_after_a_crash_does_not_ask_for_a_recompile(
        monkeypatch, home, capsys):
    """Gate r1 MINOR 3: a summary has no host phase. Mutation: drop the op
    from `NO_HOST_PHASE_OPS` -> red."""
    from self_learn import gitops

    real = gitops.stage_and_commit

    class Crash(BaseException):
        """The process dies between the write and the commit."""

    def crash(*args, **kwargs):
        raise Crash()

    record = {"schema": 1, "kind": "overseer-report", "ref": "2026-10-25",
              "source_sha256": "c" * 64, "text": "written before the crash", "created_at": "x"}
    monkeypatch.setattr(gitops, "stage_and_commit", crash)
    with pytest.raises(Crash):
        summarise.save(home, record)
    monkeypatch.setattr(gitops, "stage_and_commit", real)
    assert list(intents.intents_dir(home).glob("*.json"))  # control: the intent is left
    capsys.readouterr()
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
    err = capsys.readouterr().err
    assert "rolled forward: its commit landed" in err
    assert "recompile" not in err
    assert git(home, "status", "--porcelain").stdout.strip() == ""
