"""Humane UI lane 5 (proposal §7, S-140): the "In short" box.

The box shows the overseer's own scheduled summary, a nightly review's
counted summary, or a summary written on request ("Summarise this"),
saved in the ledger against the report's exact text. Nothing starts on a
page view: only the button's POST reaches the runner.

Page reads are monkeypatched (``Reads``); the summary verb is the scripted
``FakeAskRunner`` (``summary_calls`` records every start); a saved summary
is a real file written by the CLI's own ``summarise.save`` into the test's
scratch ledger. Every absence assertion follows a positive control that
its region rendered. Each test names the mutation it was checked against.
"""

from __future__ import annotations

import json

from self_learn import summarise

from test_inbox import (  # noqa: F401 -- person is an autouse fixture
    HOOK,
    HOOK_PACKET,
    ID_HOOK,
    HX,
    Reads,
    _doc,
    _item,
    make_client,
    person,
)

REPORT = """# Overseer report — 2026-11-01   run 92d6fec6   actor overseer   model claude-x

## Examined
- The steward's decisions hold on 33 of the 35 cases it read.

## Questions for you
- none

## Refused / could not do
- none
"""
IN_SHORT = "The overseer checked 35 decisions and agreed with 33. Nothing needs you."
RUN_ID = "att-0000000005a1"
RUN_ITEM = {**_item(RUN_ID, "decided.steward-run", "decided", None,
                    "Nightly review, 31 October: 27 lessons decided"),
            "source": {"by": "steward", "run": "run-1", "report": None}}
COUNTED = "Put 9 lessons to use, turned 4 down and left 3 for later."
RUN_PACKET = {"item": RUN_ITEM, "question": RUN_ITEM["title"], "options": [], "evidence": [],
              "more": [], "pointers": [], "look_at": [],
              "run": {"decisions": [], "counts": {"use": 9, "no": 4, "later": 3, "kept": 0},
                      "other": 0, "error": None, "in_short": COUNTED}}


def _client(tmp_path, monkeypatch, report: str = REPORT, *, ask=None, manifest=None,
            enter=False):
    client, runner, ask, hub = make_client(
        tmp_path, monkeypatch, Reads(_doc(RUN_ITEM, HOOK), {RUN_ID: RUN_PACKET, ID_HOOK: HOOK_PACKET}),
        ask=ask, enter=enter)
    home = tmp_path / "home"
    (home / "overseer").mkdir(parents=True, exist_ok=True)
    (home / "overseer" / "latest-report.md").write_text(report, encoding="utf-8")
    (home / "overseer" / "2026-11-01-report.md").write_text(report, encoding="utf-8")
    if manifest is not None:
        (home / "cases" / "runs").mkdir(parents=True, exist_ok=True)
        (home / "cases" / "runs" / "92d6fec6.json").write_text(json.dumps(manifest))
    return client, ask, home


def _box(page: str) -> str:
    start = page.index('id="in-short-box"')
    return page[start:page.index("</section>", start)]


def _save(home, kind, ref, text, **extra):
    src = summarise.source(home, kind, ref)
    record = {"schema": 1, "kind": kind, "ref": src.ref, "source_sha256": src.sha256,
              "source_chars": len(src.text), "text": text, "model": "sonnet",
              "created_at": "2026-11-01T16:02:00Z", "by": "on request", "cost_usd": 0.04,
              "duration_secs": 12.0, "session": None, **extra}
    # The CLI's own writer; the scratch home is not a git ledger, so the
    # summary waits in the cache exactly as under a STOPPED ledger -- the
    # read path is the same either way.
    path = summarise.pending_path(home, kind, src.sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


# --------------------------------------------------------- page views


def test_a_report_with_no_summary_offers_the_button_and_starts_nothing(tmp_path, monkeypatch):
    """Mutation: start the run from the GET (the page view) -> red."""
    client, ask, _home = _client(tmp_path, monkeypatch)
    page = client.get("/overseer-report").text
    box = _box(page)
    assert "This report has no summary yet." in box
    assert 'hx-post="/summary/overseer-report/2026-11-01"' in box and "data-in-short-start" in box
    assert "Summarise this report" in box and "no API charge" in box
    # Gate r1 MINOR 1: a plain view never polls (only a run in flight does).
    assert "hx-trigger" not in box and "hx-get" not in box and "aria-busy" not in box
    client.get("/overseer-report/2026-11-01")
    client.get("/summary/overseer-report/2026-11-01")
    assert ask.summary_calls == []


def test_the_overseers_own_in_short_is_shown_and_lifted_out_of_the_body(tmp_path, monkeypatch):
    """Mutations: leave the section in the body -> red; offer the button on a
    report that has its own summary -> red."""
    report = REPORT.replace("## Examined", f"## In short\n{IN_SHORT}\n\n## Examined", 1)
    client, ask, _home = _client(tmp_path, monkeypatch, report)
    page = client.get("/overseer-report").text
    box = _box(page)
    assert IN_SHORT in box and "data-in-short-scheduled" in box
    assert "with no extra model call" in box
    assert "data-in-short-start" not in box
    assert "hx-trigger" not in box and "hx-get" not in box
    body = page[page.index("rv-body"):]
    assert "<h2>Examined</h2>" in body  # control: the body rendered
    assert "<h2>In short</h2>" not in body and IN_SHORT not in body
    assert ask.summary_calls == []


def test_a_summary_saved_for_the_exact_text_is_shown_with_no_call(tmp_path, monkeypatch):
    """Mutation: look the summary up by ref, not by the text's hash -> red
    in the next test; drop the saved lookup -> red here."""
    client, ask, home = _client(tmp_path, monkeypatch)
    _save(home, "overseer-report", "2026-11-01", "Saved words about the week.")
    box = _box(client.get("/overseer-report").text)
    assert "Saved words about the week." in box and "data-in-short-summary" in box
    assert "Summary written on request" in box and "by sonnet" in box
    assert "$0.04 notional" in box and "Write it again" in box
    assert "data-in-short-start" not in box
    assert "hx-trigger" not in box and "hx-get" not in box
    assert ask.summary_calls == []


def test_a_changed_report_shows_the_old_summary_greyed_and_waits_for_a_click(tmp_path, monkeypatch):
    """Mutation: reuse the old summary for the changed text -> red."""
    client, ask, home = _client(tmp_path, monkeypatch)
    _save(home, "overseer-report", "2026-11-01", "Words for the first version.")
    changed = REPORT.replace("33 of the 35", "34 of the 35")
    for name in ("latest-report.md", "2026-11-01-report.md"):
        (home / "overseer" / name).write_text(changed, encoding="utf-8")
    box = _box(client.get("/overseer-report").text)
    assert "Words for the first version." in box and "data-in-short-stale" in box
    assert "written for an earlier version of this report" in box
    assert "Summarise again" in box
    assert "data-in-short-summary" not in box
    assert "hx-trigger" not in box and "hx-get" not in box
    assert ask.summary_calls == []


def test_a_nightly_review_shows_its_counts_and_offers_words(tmp_path, monkeypatch):
    """Mutation: drop the counted text -> red; no box on a hook item is
    checked after the review's box rendered."""
    client, ask, _home = _client(tmp_path, monkeypatch)
    page = client.get(f"/inbox/{RUN_ID}").text
    box = _box(page)
    assert COUNTED in box and "Counted from the run's own record. No model call." in box
    assert "Summarise this in words" in box
    assert f'hx-post="/summary/inbox-item/{RUN_ID}"' in box
    assert "hx-trigger" not in box and "hx-get" not in box
    hook = client.get(f"/inbox/{ID_HOOK}").text
    assert 'id="ws-question"' in hook  # control
    assert 'id="in-short-box"' not in hook
    assert ask.summary_calls == []


# --------------------------------------------------------- the click


def test_the_button_starts_exactly_one_run_and_a_second_click_gets_the_running_one(
        tmp_path, monkeypatch):
    """Mutations: no refusal while one runs -> red (two starts); the page
    view starts one -> red (calls before the click)."""
    from self_learn_ui.ask_runner import FakeAskRunner

    client, ask, _home = _client(tmp_path, monkeypatch, enter=True,
                                 ask=lambda hub: FakeAskRunner(publish=hub.publish_nowait, hold=True))
    client.get("/overseer-report")
    assert ask.summary_calls == []
    first = client.post("/summary/overseer-report/2026-11-01", headers=HX)
    assert first.status_code == 200
    assert ask.summary_calls == [("overseer-report", "2026-11-01", False)]
    box = _box(first.text)
    assert 'aria-busy="true"' in box and "Writing a summary of this report" in box
    assert 'hx-trigger="every 1s"' in box and "data-in-short-stop" in box
    second = client.post("/summary/overseer-report/2026-11-01", headers=HX)
    assert second.status_code == 409
    assert "Writing a summary of this report" in _box(second.text)
    assert len(ask.summary_calls) == 1
    poll = client.get("/summary/overseer-report/2026-11-01")
    assert "Writing a summary of this report" in poll.text and len(ask.summary_calls) == 1
    stopped = client.post("/summary/overseer-report/2026-11-01/stop", headers=HX)
    assert stopped.status_code == 200
    assert ask.stops == ["summary:overseer-report:2026-11-01"]


def test_after_the_run_the_summary_shows_and_a_reload_starts_nothing(tmp_path, monkeypatch):
    client, ask, _home = _client(tmp_path, monkeypatch, enter=True)
    client.post("/summary/overseer-report/2026-11-01", headers=HX)
    client.portal.call(ask.wait, "summary:overseer-report:2026-11-01")
    box = _box(client.get("/overseer-report").text)
    box = _box(client.get("/overseer-report").text)  # a reload
    assert "(Sandbox: this summary is scripted." in box
    assert "data-in-short-start" not in box
    assert len(ask.summary_calls) == 1


def test_write_it_again_passes_again(tmp_path, monkeypatch):
    client, ask, home = _client(tmp_path, monkeypatch)
    _save(home, "overseer-report", "2026-11-01", "Saved words.")
    assert "Write it again" in _box(client.get("/overseer-report").text)
    client.post("/summary/overseer-report/2026-11-01", data={"again": "1"}, headers=HX)
    assert ask.summary_calls == [("overseer-report", "2026-11-01", True)]


def test_a_setup_that_would_bill_money_says_summaries_are_off(tmp_path, monkeypatch):
    """Mutation: show the verb's raw error and the button again -> red."""
    client, ask, _home = _client(tmp_path, monkeypatch, enter=True)
    ask.summary_script = [{"ev": "error", "code": "money", "message": "not summarised: x",
                           "fix": None}]
    client.post("/summary/overseer-report/2026-11-01", headers=HX)
    client.portal.call(ask.wait, "summary:overseer-report:2026-11-01")
    box = _box(client.get("/overseer-report").text)
    assert "data-in-short-failed" in box
    assert "Summaries are off: this setup would bill money." in box
    assert "data-in-short-start" not in box


def test_a_bad_target_is_refused_without_a_start(tmp_path, monkeypatch):
    client, ask, _home = _client(tmp_path, monkeypatch)
    assert client.post("/summary/overseer-report/..%2Fetc", headers=HX).status_code == 404
    assert client.post("/summary/elsewhere/x", headers=HX).status_code == 404
    assert client.get("/summary/inbox-item/not-an-id").status_code == 404
    assert ask.summary_calls == []


# ------------------------------------------- the weekly report's two new tiles


def test_the_review_tiles_show_when_the_record_has_them_and_not_otherwise(tmp_path, monkeypatch):
    """Mutation: drop the `review` read in weekly_facts -> red."""
    base = {"actor": "overseer", "run_id": "92d6fec6", "status": "complete",
            "progress_at": "2026-11-01T15:21:43Z", "population_count": 70,
            "findings": [{"kind": "examined"}] * 35,
            "decisions": {"staged": 7, "dropped": 1}, "questions": {"questions": []}}
    client, _ask, _home = _client(tmp_path, monkeypatch, manifest=base)
    tiles = client.get("/overseer-report").text
    tiles = tiles[tiles.index("data-report-tiles"):].split("</ul>")[0]
    assert "Past decisions re-checked" in tiles  # control: the tiles rendered
    assert "data-tile-agreed" not in tiles and "data-tile-findings-dropped" not in tiles
    review = {**base, "review": {"examined": 35, "agreed": 33, "disagreed": 2, "no_verdict": 0,
                                 "findings_dropped": 5}}
    other = tmp_path / "other"
    other.mkdir()
    client, _ask, _home = _client(other, monkeypatch, manifest=review)
    page = client.get("/overseer-report").text
    tiles = page[page.index("data-report-tiles"):].split("</ul>")[0]
    agreed = tiles[tiles.index("data-tile-agreed"):].split("</li>")[0]
    assert '<span class="rv-tile-value">33</span>' in agreed and "(2 not)" in agreed
    dropped = tiles[tiles.index("data-tile-findings-dropped"):].split("</li>")[0]
    assert '<span class="rv-tile-value">5</span>' in dropped


def test_a_run_that_cannot_save_ends_and_says_so(tmp_path, monkeypatch):
    """Seen live in the scratch walk: the walk world's fake raised while
    saving and the box said "Writing…" forever. A turn always ends.
    Mutation: drop the fake's `except Exception` -> red (the turn never
    ends)."""
    from self_learn_ui.ask_runner import FakeAskRunner

    def boom(home, record):
        raise RuntimeError("no git identity")

    monkeypatch.setattr(summarise, "save", boom)
    holder = {}

    def factory(hub):
        holder["ask"] = FakeAskRunner(publish=hub.publish_nowait, home=tmp_path / "home", seal=True)
        return holder["ask"]

    client, ask, _home = _client(tmp_path, monkeypatch, ask=factory, enter=True)
    client.post("/summary/overseer-report/2026-11-01", headers=HX)
    client.portal.call(ask.wait, "summary:overseer-report:2026-11-01")
    box = _box(client.get("/overseer-report").text)
    assert "data-in-short-failed" in box and "could not be saved" in box
    assert 'aria-busy="true"' not in box and "data-in-short-start" in box


# --------------------------------------------------------- gate r1 fold


def test_a_summary_an_agent_asked_for_says_so(tmp_path, monkeypatch):
    """Gate r1 NIT 1. Mutation: always "on request" -> red."""
    client, _ask, home = _client(tmp_path, monkeypatch)
    _save(home, "overseer-report", "2026-11-01", "Agent words.", by="an agent's request")
    box = _box(client.get("/overseer-report").text)
    assert "Agent words." in box  # control
    assert "Summary written on an agent's request" in box


def test_a_persons_stop_is_a_plain_note_not_a_failure(tmp_path, monkeypatch):
    """Gate r1 NIT 4. Mutation: show "interrupted" as a failure -> red."""
    from self_learn_ui.ask_runner import FakeAskRunner

    client, ask, _home = _client(tmp_path, monkeypatch, enter=True,
                                 ask=lambda hub: FakeAskRunner(publish=hub.publish_nowait, hold=True))
    client.post("/summary/overseer-report/2026-11-01", headers=HX)
    client.post("/summary/overseer-report/2026-11-01/stop", headers=HX)
    client.portal.call(ask.wait, "summary:overseer-report:2026-11-01")
    box = _box(client.get("/overseer-report").text)
    assert "Stopped before the summary was written. Nothing was saved." in box
    assert "data-in-short-failed" not in box and 'role="alert"' not in box
    assert "data-in-short-start" in box  # it can be tried again


def test_an_inbox_item_that_is_not_a_report_has_no_summary_route(tmp_path, monkeypatch):
    """Gate r1 NIT 5. Mutations: drop the POST's kind check -> red (a start);
    the GET falls back to a nightly review -> red."""
    client, ask, _home = _client(tmp_path, monkeypatch)
    assert client.get(f"/summary/inbox-item/{RUN_ID}").status_code == 200  # control
    assert client.post(f"/summary/inbox-item/{ID_HOOK}", headers=HX).status_code == 404
    assert client.get(f"/summary/inbox-item/{ID_HOOK}").status_code == 404
    assert ask.summary_calls == []
