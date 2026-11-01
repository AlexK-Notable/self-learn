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


def test_work_being_carried_out_has_its_own_counted_group(tmp_path, monkeypatch):
    """Gate r1 MINOR 5 (M14) and NIT 9. Mutations: drop the "Being carried
    out" section -> red; no count on its heading -> red."""
    from test_inbox import APPROVED, ID_APPROVED

    _fixed_now(monkeypatch)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7, APPROVED), {ID_OO7: OO7_PACKET}))
    listing = _list(client.get(f"/inbox/{ID_OO7}").text)
    assert 'id="inbox-approved-h">Being carried out (1)</h2>' in listing
    group = listing[listing.index('data-group="approved"'):].split("</ul>")[0]
    assert f'data-inbox-item="{ID_APPROVED}"' in group and "Approved, not started" in group


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
    """Gate r1 NIT 10: the exact span. Mutations: first and last day swapped
    -> red; no month on a cross-month span -> red; a one-day span written
    as a range -> red."""
    def at(day: str) -> dict:
        it = _run(1, days=0)
        it["updated_at"] = it["since"] = f"{day}T19:00:00Z"
        return it

    def local(day: str) -> datetime:
        return datetime.fromisoformat(day + "T19:00:00+00:00").astimezone()

    span = inbox_routes._day_span  # noqa: SLF001
    a, b = local("2026-10-26"), local("2026-10-31")
    assert span([at("2026-10-31"), at("2026-10-26")]) == f"{a.day}–{b.day} {b.strftime('%b')}"
    c, d = local("2026-09-28"), local("2026-10-03")
    assert span([at("2026-10-03"), at("2026-09-28")]) == (
        f"{c.day} {c.strftime('%b')} – {d.day} {d.strftime('%b')}")
    e = local("2026-11-01")
    assert span([at("2026-11-01"), at("2026-11-01")]) == f"{e.day} {e.strftime('%b')}"


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
            "title": f"About to do thing {n}", "verb": verb, "group": group,
            "carried_out": group != "refused", "reason": f"Short reason {n}."}


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
    assert '<th scope="col">Decisions</th>' in run  # gate r1 MAJOR 2: the unit, named truly
    # Three groups hold decisions, so three bar segments: none for the empty one.
    assert run.count('class="run-seg run-seg-') == 3 and "run-seg run-seg-kept" not in run
    shown = run[:run.index("data-run-rest")]
    assert shown.count("data-run-decision ") == 6
    assert "Show all 8 (2 more)" in run
    assert "About to do thing 0" in shown and "Put to use · Short reason 0." in shown
    assert "<summary>Its ids, for an agent</summary><code>case-0000c000</code>" in run
    # "Why?" fetches the case when opened (gate r1 MAJOR 3).
    assert 'hx-get="/inbox/case/case-0000c000" hx-trigger="toggle once"' in run
    # The full case files fold on a nightly review.
    assert "data-evidence-fold" in page
    # And "What was decided" (the title again) is not printed.
    assert 'id="ws-decided-h"' not in page


def test_a_refused_decision_reads_as_refused_never_as_done(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1 on the page. Mutation: draw a refused row with its
    verb's words ("Put to use") -> red; no refused group in the split -> red."""
    rows = [_row(0, "use", "route"), _row(1, "refused", "route"), _row(2, "no", "reject")]
    packet = {**RUN_PACKET, "run": {"decisions": rows, "other": 0, "error": None,
                                    "counts": {"use": 1, "no": 1, "later": 0, "kept": 0, "refused": 1}}}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(RUN_ITEM), {RUN_ID: packet}))
    page = client.get(f"/inbox/{RUN_ID}").text
    run = page[page.index("data-run-decisions"):].split("</section>")[0]
    assert "Put to use <strong>1</strong>" in run  # control: the split rendered
    assert "Refused by the ledger, nothing changed <strong>1</strong>" in run
    assert run.count('class="run-seg run-seg-refused"') == 1
    line = run[run.index("About to do thing 1"):].split("</summary>")[0]
    assert "data-run-refused" in line and "it was to be: Put to use" in line
    assert '<span class="run-decision-line">Put to use' not in line


def test_decisions_left_out_for_size_are_said_to_be_counted(tmp_path, monkeypatch):
    """Gate r1 MAJOR 3: a run too large for its budget lists fewer lines and
    says so; its counts still cover every decision. Mutation: drop the
    line -> red."""
    packet = {**RUN_PACKET, "run": {**RUN_PACKET["run"], "omitted": 3}}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(RUN_ITEM), {RUN_ID: packet}))
    run = client.get(f"/inbox/{RUN_ID}").text
    run = run[run.index("data-run-decisions"):].split("</section>")[0]
    assert "Put to use <strong>4</strong>" in run  # control
    assert "data-run-omitted" in run and "3 more decisions of this review are counted above" in run


def test_why_opens_the_case_told_once(tmp_path, monkeypatch):
    """GET /inbox/case/<id>, the "Why?" of a decision line. Mutations: print
    the Decision list raw -> red; accept any id -> red."""
    from types import SimpleNamespace

    from self_learn import cases

    shown = []

    def show(home, case_id, *, evidence_only=True):
        shown.append((case_id, evidence_only))
        if case_id == "case-0000dead":
            raise cases.CaseError("case show: case-0000dead failed its freeze-hash check")
        return SimpleNamespace(frontmatter={"outcome": "reject"}, sections={
            "Identity and scope": "- records: lrn-1\n- question: Should it stand?",
            "Decision": f"- verb: reject\n- because: {CASE_BECAUSE}\n- confidence: settled"})

    monkeypatch.setattr(cases, "show", show)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc()))
    body = client.get("/inbox/case/case-0000beef").text
    assert "<strong>Question:</strong> Should it stand?" in body  # control
    assert "<strong>Decision:</strong> Turned down (held firmly)" in body
    outside = body[:body.index("The case file as written")]
    assert outside.count(CASE_BECAUSE) == 1 and "- verb:" not in outside
    assert shown == [("case-0000beef", False)]
    bad = client.get("/inbox/case/..%2Fetc")
    assert bad.status_code == 404 and len(shown) == 1
    tampered = client.get("/inbox/case/case-0000dead")
    assert tampered.status_code == 404 and "failed its freeze-hash check" in tampered.text


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


def test_a_path_holding_a_hash_is_one_placeholder(tmp_path, monkeypatch):
    """Gate r1 MINOR 4: no markup inside a placeholder's title. Mutation:
    the hash pass run over the path's placeholder -> red."""
    html = report_view.fold_machine_text(
        "<ul>\n<li>wrote /home/user/.cache/stage/" + "a" * 64 + "/x.yaml today</li>\n</ul>")
    line = html.split("<details")[0]
    assert 'data-fold="path"' in line  # control
    assert line.count("rv-token") == 1
    title = line[line.index('title="'):].split('"')[1]
    assert "<" not in title and "a" * 64 in title


def _questions_page(tmp_path, monkeypatch, states: dict, date: str | None = None) -> str:
    from self_learn import weekly_facts

    monkeypatch.setattr(weekly_facts, "question_states", lambda home, ids: {
        i: states.get(i, {"state": "closed", "answer": None, "at": None}) for i in ids})
    client = _report_client(tmp_path, monkeypatch,
                            "- q-hook-activation: register the generated hooks?\n"
                            "- um-c4e5@r1: confirm or correct the reading.")
    if date:
        home = tmp_path / "home"
        (home / "overseer" / f"{date}-report.md").write_text(
            (home / "overseer" / "latest-report.md").read_text())
        return client.get(f"/overseer-report/{date}").text
    return client.get("/overseer-report").text


def test_answered_questions_show_their_answer_and_ask_nothing(tmp_path, monkeypatch):
    """Gate r1 MINOR 6. Mutations: always "Questions for you" -> red;
    always the inbox link -> red; drop the answer -> red."""
    page = _questions_page(tmp_path, monkeypatch, {
        "q-hook-activation": {"state": "answered", "answer": "yes to both: hooks on.",
                              "at": "2026-10-06T05:34:13Z"}}, date="2026-10-04")
    q = page[page.index("data-report-questions"):].split("</section>")[0]
    assert "The questions it asked" in q and 'data-asking="no"' in q
    assert "register the generated hooks?" in q  # control: the questions are listed
    assert "You answered" in q and "“yes to both: hooks on.”" in q
    assert "No longer asked; no answer is on record." in q
    assert 'href="/inbox"' not in q and "Questions for you" not in q
    assert "q-hook-activation:" not in q  # the id is not running text


def test_an_open_question_still_asks_to_be_answered(tmp_path, monkeypatch):
    """Gate r1 MINOR 6, the other side. Mutation: never ask -> red."""
    page = _questions_page(tmp_path, monkeypatch, {
        "um-c4e5@r1": {"state": "open", "answer": None, "at": None}})
    q = page[page.index("data-report-questions"):].split("</section>")[0]
    assert "Questions for you" in q and 'href="/inbox"' in q and "(still open)" in q
