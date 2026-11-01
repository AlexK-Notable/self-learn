"""Humane UI lane 3 (proposal §4, §5, §10): the inbox list in time groups
with the nightly reviews folded, the item page that tells a case once and
lists a nightly review's decisions, ids and machine text folded away, and
the weekly report's layout.

Page reads are monkeypatched (``FakeRunner`` carries verbs only). Every
absence assertion follows a positive control that its region rendered.
Each test names the mutation it was checked against.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from self_learn_ui import inbox_routes, report_view

from test_inbox import (  # noqa: F401 -- person is an autouse fixture
    HOOK,
    HOOK_PACKET,
    ID_HOOK,
    ID_OO7,
    OO7,
    OO7_PACKET,
    Reads,
    _doc,
    _item,
    make_client,
    person,
)

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)


def _at(days: float = 0.0, hours: float = 0.0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(n: int, *, days: float, seen: bool = True, flagged: bool = False) -> dict:
    it = _item(f"att-0000000003{n:02x}", "decided.steward-run", "decided", None,
               f"Nightly review {n}", since=_at(days), flagged=flagged, seen=seen)
    it["source"] = {"by": "steward", "run": f"run-{n}", "report": None}
    return it


def _fixed_now(monkeypatch) -> None:
    monkeypatch.setattr(inbox_routes, "_now", lambda: NOW)


def _list(page: str) -> str:
    start = page.index('id="inbox-list"')
    return page[start:page.index("inbox-list-actions", start)]


# ------------------------------------------------------------ the list


def test_the_list_groups_by_time_under_needs_you(tmp_path, monkeypatch):
    """Mutations: put every decided item under one heading -> red; drop
    the empty "Needs you" line -> red."""
    _fixed_now(monkeypatch)
    today = {**HOOK, "since": _at(hours=1), "updated_at": _at(hours=1)}
    week = _run(1, days=3, seen=False)
    old = _run(2, days=20, seen=False)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(today, week, old)))
    listing = _list(client.get(f"/inbox/{ID_HOOK}").text)
    assert 'id="inbox-needs-you-h">Needs you</h2>' in listing
    assert "data-nothing-needs-you" in listing and "Nothing needs you right now." in listing
    for key in ("today", "week", "older"):
        assert f'data-group="{key}"' in listing
    assert listing.index(ID_HOOK) < listing.index(week["id"]) < listing.index(old["id"])
    today_ul = listing[listing.index('data-group="today"'):listing.index('data-group="week"')]
    assert ID_HOOK in today_ul and week["id"] not in today_ul


def test_a_needs_you_item_is_listed_with_its_count_and_no_empty_line(tmp_path, monkeypatch):
    """Mutation: always print the empty line -> red."""
    _fixed_now(monkeypatch)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7, HOOK), {ID_OO7: OO7_PACKET}))
    listing = _list(client.get(f"/inbox/{ID_OO7}").text)
    assert "Needs you (1)" in listing and 'data-group="needs-you"' in listing  # control
    assert "data-nothing-needs-you" not in listing


def test_a_decided_row_has_no_decided_chip_and_says_who_and_when(tmp_path, monkeypatch):
    """Mutations: keep the "Decided" chip -> red; drop the who-and-when line
    -> red."""
    _fixed_now(monkeypatch)
    hook = {**HOOK, "since": _at(hours=2), "updated_at": _at(hours=2)}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(hook, OO7), {ID_OO7: OO7_PACKET}))
    listing = _list(client.get(f"/inbox/{ID_OO7}").text)
    row = listing[listing.index(f'data-inbox-item="{ID_HOOK}"'):].split("</li>")[0]
    assert 'class="inbox-item-by">overseer · ' in row  # control: the row rendered
    assert "chip-decided" not in row
    needs = listing[listing.index(f'data-inbox-item="{ID_OO7}"'):].split("</li>")[0]
    assert "chip-needs-you" in needs


def test_the_nightly_reviews_of_a_group_fold_into_one_row(tmp_path, monkeypatch):
    """Two or more nightly reviews not flagged for attention fold, seen or
    not; the fold counts the unseen ones; a lone review and a flagged one
    stay rows of their own. Mutations: fold only the seen ones -> red;
    fold a flagged review -> red; FOLD_MIN 1 -> red."""
    _fixed_now(monkeypatch)
    a, b, c = _run(1, days=2), _run(2, days=3, seen=False), _run(3, days=4)
    flagged = _run(4, days=5, seen=False, flagged=True)
    lone = _run(5, days=30)
    client, *_ = make_client(tmp_path, monkeypatch,
                             Reads(_doc(OO7, a, b, c, flagged, lone), {ID_OO7: OO7_PACKET}))
    listing = _list(client.get(f"/inbox/{ID_OO7}").text)
    week = listing[listing.index('data-group="week"'):listing.index('data-group="older"')]
    assert week.count("data-inbox-fold") == 1
    fold = week[week.index("data-inbox-fold"):week.index("</details>")]
    assert "<details>" in fold  # closed: it holds nothing selected
    for it in (a, b, c):
        assert f'data-inbox-item="{it["id"]}"' in fold
    assert "3 reviews, 1 not seen yet" in fold
    assert f'data-inbox-item="{flagged["id"]}"' in week and flagged["id"] not in fold
    older = listing[listing.index('data-group="older"'):]
    assert f'data-inbox-item="{lone["id"]}"' in older and "data-inbox-fold" not in older


def test_a_fold_holding_the_open_item_is_drawn_open(tmp_path, monkeypatch):
    """Mutation: never draw the fold open -> red."""
    _fixed_now(monkeypatch)
    a, b = _run(1, days=2), _run(2, days=3)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(a, b)))
    listing = _list(client.get(f"/inbox/{a['id']}").text)
    assert "data-inbox-fold" in listing  # control
    assert "<details open>" in listing
    assert 'aria-current="page"' in listing


def test_the_fold_label_names_the_days():
    """Mutation: no month on a cross-month span -> red."""
    items = [_run(1, days=0.5), _run(2, days=3), _run(3, days=6)]
    span = inbox_routes._day_span(items)  # noqa: SLF001
    assert span.endswith("Nov") or span.endswith("Oct")
    assert "–" in span


def test_the_unseen_mark_is_one_dot_with_its_word_for_a_screen_reader(tmp_path, monkeypatch):
    """Proposal §4: "new" and "unseen" become one blue dot with the word in
    its accessible name. Mutation: drop the hidden word -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET}))
    row = client.get(f"/inbox/{ID_HOOK}").text
    row = row[row.index(f'data-inbox-item="{ID_HOOK}"'):].split("</li>")[0]
    assert '<span class="dot-new" title="not seen yet"><span class="visually-hidden">new</span></span>' in row


def test_the_narrow_window_has_an_all_items_button(tmp_path, monkeypatch):
    """Mutation: drop the button -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert "data-show-list" in page and "All items (1)" in page


# ------------------------------------------------------------ the item page

CASE_BECAUSE = "The line costs more than it saves; one sighting, no harm."
CASE = {"kind": "case", "id": "case-0000beef", "question": "Should the rule stand?",
        "decision": f"- verb: reject\n- because: {CASE_BECAUSE}\n- confidence: settled",
        "verb": "reject", "confidence": "settled", "because": CASE_BECAUSE,
        "excerpt": f"## Decision\n- verb: reject\n- because: {CASE_BECAUSE}"}


def test_a_case_is_told_once(tmp_path, monkeypatch):
    """Question, Decision in words, Because; the file as written folds.
    Mutations: print `ev.decision` raw -> red; drop the case-file fold
    (excerpt printed open) -> red; drop the verb words -> red."""
    packet = {**HOOK_PACKET, "evidence": [CASE]}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: packet}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    ev = page[page.index('data-evidence-kind="case"'):]
    ev = ev[:ev.index("</section>")]
    assert "<strong>Question:</strong> Should the rule stand?" in ev  # control
    assert "<strong>Decision:</strong> Turned down (held firmly)" in ev
    outside = ev[:ev.index("data-case-file")]
    assert outside.count(CASE_BECAUSE) == 1
    assert "- verb:" not in outside
    assert "<summary>The case file as written</summary>" in ev
    # The id is folded away for an agent, not in running text.
    assert "case-0000beef" not in outside
    assert "Its id, for an agent" in ev and "case-0000beef" in ev


def test_an_old_case_entry_without_a_verb_still_says_its_decision(tmp_path, monkeypatch):
    """A packet from before the verb field (a one-word decision) keeps it;
    a list-shaped one is never printed as a paragraph. Mutation: ignore
    `ev.decision` without `ev.verb` -> red."""
    plain = {k: v for k, v in CASE.items() if k not in ("verb", "confidence")}
    one_word = {**plain, "id": "case-0000bee1", "decision": "parked"}
    packet = {**HOOK_PACKET, "evidence": [one_word, {**plain, "id": "case-0000bee2"}]}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: packet}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert "<strong>Decision:</strong> Left for the weekly check" in page
    second = page[page.index("case-0000bee2") - 2000:page.index("case-0000bee2")]
    assert "<strong>Because:</strong>" in second  # control
    assert "<strong>Decision:</strong> - verb" not in page


def test_machine_text_reads_in_words_with_the_ids_folded(tmp_path, monkeypatch):
    """Mutations: the old "Shortened to fit: <fields>" line -> red; the old
    "More the agent can open for you" line -> red."""
    more = [{"kind": "lesson", "id": "lrn-00000001"}, {"kind": "lesson", "id": "lrn-00000002"},
            {"kind": "case", "id": "case-00000003"}]
    packet = {**HOOK_PACKET, "more": more,
              "limits": {"bytes": 1, "truncated": ["evidence[0].because", "evidence[2].excerpt"]}}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: packet}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert "data-shortened" in page and "Some long passages are shortened here" in page
    assert "evidence[0].because" not in page and "Shortened to fit" not in page
    assert "The agent can also open 2 lessons and 1 case that belong to this item." in page
    fold = page[page.index("data-more"):].split("</details>")[0]
    assert "lrn-00000001" in fold and "case-00000003" in fold
    assert "More the agent can open for you" not in page


RUN_ID = "att-000000000301"
RUN_ITEM = {**_item(RUN_ID, "decided.steward-run", "decided", None,
                    "Nightly review, 31 October: 3 lessons decided", seen=True),
            "source": {"by": "steward", "run": "run-1", "report": None}}


def _row(n: int, group: str, verb: str) -> dict:
    return {"case": f"case-0000c0{n:02d}", "record": f"lrn-0000c0{n:02d}", "records": 1,
            "title": f"About to do thing {n}", "question": f"Question {n}?", "verb": verb,
            "group": group, "reason": f"Short reason {n}.", "because": f"Short reason {n}. And more."}


RUN_PACKET = {
    **HOOK_PACKET, "item": RUN_ITEM, "question": RUN_ITEM["title"], "undo": None,
    "decided": {"what": RUN_ITEM["title"], "by": "steward", "at": "2026-10-31T10:00:00Z",
                "because": None, "changes_now": None},
    "run": {"decisions": [_row(n, g, v) for n, (g, v) in enumerate(
        [("use", "route")] * 4 + [("no", "reject")] * 2 + [("later", "defer")] * 2)],
        "counts": {"use": 4, "no": 2, "later": 2, "kept": 0}, "other": 0, "error": None},
    "evidence": [CASE],
}


def test_a_nightly_review_lists_each_decision_with_counts_and_a_table(tmp_path, monkeypatch):
    """Mutations: legend from the rows rather than the CLI's counts (drop
    `counts`) -> red; show every line open (no "Show all" fold) -> red;
    no table view -> red; SVG segment for a zero group -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(RUN_ITEM), {RUN_ID: RUN_PACKET}))
    page = client.get(f"/inbox/{RUN_ID}").text
    run = page[page.index("data-run-decisions"):]
    run = run[:run.index("</section>")]
    assert "What the steward decided" in run  # control
    assert 'data-group="use"><span class="run-swatch run-seg-use" aria-hidden="true"></span>Put to use <strong>4</strong>' in run
    assert "Turned down <strong>2</strong>" in run and "Looked at, kept as is <strong>0</strong>" in run
    assert "<summary>Show as a table</summary>" in run and "<th scope=\"row\">All</th><td>8</td>" in run
    # Three groups hold decisions, so three bar segments: none for the empty one.
    assert run.count('class="run-seg run-seg-') == 3 and "run-seg run-seg-kept" not in run
    shown = run[:run.index("data-run-rest")]
    assert shown.count("data-run-decision ") == 6
    assert "Show all 8 (2 more)" in run
    assert "About to do thing 0" in shown and "Put to use · Short reason 0." in shown
    assert "<summary>Its ids, for an agent</summary><code>case-0000c000</code>" in run
    # The full case files fold on a nightly review.
    assert "data-evidence-fold" in page
    # And "What was decided" (the title again) is not printed.
    assert 'id="ws-decided-h"' not in page


def test_the_in_short_slot_is_only_on_report_items(tmp_path, monkeypatch):
    """Mutation: drop the kind check -> red."""
    over = _item("att-000000000302", "decided.overseer-run", "decided", None, "Weekly report, 1 November")
    client, *_ = make_client(tmp_path, monkeypatch,
                             Reads(_doc(RUN_ITEM, over, HOOK), {RUN_ID: RUN_PACKET, ID_HOOK: HOOK_PACKET}))
    assert "data-in-short-slot" in client.get(f"/inbox/{RUN_ID}").text
    assert "data-in-short-slot" in client.get("/inbox/att-000000000302").text
    hook = client.get(f"/inbox/{ID_HOOK}").text
    assert 'id="ws-question"' in hook  # control
    assert "data-in-short-slot" not in hook


# ------------------------------------------------------------ the weekly report

REPORT = """# Overseer report — 2026-11-01   run 92d6fec6   actor overseer   model claude-x

## Examined
- Cases examined: case-040cc72e, case-08193f9d, case-46a827ed, case-ab739239 (4 of 70)
- Two cases (case-3cd3b128, case-fbda8fab) wrote probes.
- placed: symlinked /home/user/.claude/hooks/x.sh; sha256 b5706d8efff0b8e132634e95c0d1cdfc46785b35cea126d68b04b5f54af18226; {"hooks": [{"type": "command"}], "matcher": "Bash"}
- undo: `self-learn host remove /home/user/repos/x --project`

## Questions for you
{questions}

## Refused / could not do
- one
- two
- three
"""


def _report_client(tmp_path, monkeypatch, questions: str, manifest: dict | None = None):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc()))
    home = tmp_path / "home"
    (home / "overseer").mkdir(parents=True, exist_ok=True)
    (home / "overseer" / "latest-report.md").write_text(REPORT.replace("{questions}", questions))
    (home / "overseer" / "2026-10-25-report.md").write_text("# Older\n")
    if manifest is not None:
        (home / "cases" / "runs").mkdir(parents=True, exist_ok=True)
        (home / "cases" / "runs" / "92d6fec6.json").write_text(json.dumps(manifest))
    return client


def test_the_weekly_report_has_a_title_in_words_and_the_run_folded(tmp_path, monkeypatch):
    """Mutations: keep the raw first line as the heading -> red; drop the
    "About this run" fold -> red."""
    page = _report_client(tmp_path, monkeypatch, "- none").get("/overseer-report").text
    assert "<h1>Weekly report · Sunday 1 November</h1>" in page
    about = page[page.index("data-about-run"):].split("</details>")[0]
    assert "<code>92d6fec6</code>" in about and "claude-x" in about
    head = page[page.index("rv-head"):page.index("data-about-run")]
    assert "92d6fec6" not in head and "Overseer report —" not in page
    assert "/overseer-report/2026-10-25" in page  # the earlier reports menu
    assert "data-in-short-slot" in page


def test_nothing_needs_you_is_said_first_and_questions_are_never_folded(tmp_path, monkeypatch):
    """Mutations: leave "Questions for you" in the body -> red; fold the
    questions -> red."""
    none = _report_client(tmp_path, monkeypatch, "- none").get("/overseer-report").text
    assert "Nothing needs you this week." in none
    assert none.index("Nothing needs you this week.") < none.index("<h2>Examined</h2>")
    asked = _report_client(tmp_path, monkeypatch, "- Should the npm hook warn on pnpm too?").get(
        "/overseer-report").text
    q = asked[asked.index("data-report-questions"):].split("</section>")[0]
    assert "Should the npm hook warn on pnpm too?" in q and 'href="/inbox"' in q
    assert "<details" not in q
    assert asked.index("data-report-questions") < asked.index("<h2>Examined</h2>")
    assert "Nothing needs you this week." not in asked


def test_machine_text_in_a_bullet_reads_as_a_placeholder_with_the_original_folded(tmp_path, monkeypatch):
    """Mutations: no id-run fold -> red; no path fold -> red; the path
    shown absolute -> red; fold inside `code` -> red."""
    monkeypatch.setattr(report_view, "_home_prefix", lambda: "/home/user")
    page = _report_client(tmp_path, monkeypatch, "- none").get("/overseer-report").text
    body = page[page.index("rv-body"):]
    assert "Cases examined: <span class=\"rv-token\" data-fold=\"ids\"" in body
    assert ">the 4 cases</span>" in body
    assert "<summary>Show the ids in full</summary>" in body
    # Two ids stay as written.
    assert "Two cases (case-3cd3b128, case-fbda8fab) wrote probes." in body
    line = body[body.index("placed: symlinked"):].split("</li>")[0]
    assert 'title="~/.claude/hooks/x.sh">a path</span>' in line
    assert ">a hash</span>" in line and ">a settings entry</span>" in line
    assert "Show the paths, hashes and settings entries in full" in line
    # A command to copy is left as written, with no placeholder and no fold.
    undo = body[body.index("undo: <code>"):].split("</li>")[0]
    assert "<code>self-learn host remove /home/user/repos/x --project</code>" in undo
    assert "rv-token" not in undo and "rv-fold" not in undo


def test_refused_folds_with_its_count(tmp_path, monkeypatch):
    """Mutation: draw Refused open -> red."""
    page = _report_client(tmp_path, monkeypatch, "- none").get("/overseer-report").text
    folded = page[page.index("data-report-folded"):]
    assert "Refused / could not do (3)" in folded.split("</summary>")[0]


def test_the_tiles_count_from_the_runs_record(tmp_path, monkeypatch):
    """Mutations: no tiles -> red; tiles from the prose ("4 of 70" in the
    text) rather than the record -> red."""
    manifest = {"actor": "overseer", "run_id": "92d6fec6", "status": "complete",
                "progress_at": "2026-11-01T15:21:43Z", "population_count": 70,
                "findings": [{"kind": "examined"}] * 35,
                "decisions": {"staged": 7, "dropped": 1}, "questions": {"questions": []}}
    page = _report_client(tmp_path, monkeypatch, "- none", manifest).get("/overseer-report").text
    tiles = page[page.index("data-report-tiles"):].split("</ul>")[0]
    assert '<span class="rv-tile-value">35</span><span class="rv-tile-of"> of 70</span>' in tiles
    assert '<span class="rv-tile-value">6</span>' in tiles and "1 more dropped" in tiles
    assert "finished" in page
    other = tmp_path / "x"
    other.mkdir()
    no_record = _report_client(other, monkeypatch, "- none").get("/overseer-report").text
    assert "<h1>Weekly report · Sunday 1 November</h1>" in no_record  # control
    assert "data-report-tiles" not in no_record
