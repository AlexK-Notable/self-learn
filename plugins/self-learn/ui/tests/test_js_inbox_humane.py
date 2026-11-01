"""Humane UI lane 3 (proposal §4) in a real browser: `j`/`k` walk the rows
a person can see, a folded group of nightly reviews is one stop until it is
opened, and on a narrow window the list sits behind "All items".

Driven through test_js_inbox.py's in-process server (page reads
monkeypatched, verbs to a FakeRunner). Each test names the mutation it was
checked against.
"""

from __future__ import annotations

import pytest

from test_js_inbox import (  # noqa: F401 -- fixtures
    ID_OO7,
    OO7,
    _doc,
    _open,
    _wait_for,
    browser,
    page,
    server,
)

pytestmark = pytest.mark.js

RUN_IDS = ("att-0000000003a1", "att-0000000003a2", "att-0000000003a3")


def _runs() -> list[dict]:
    out = []
    for n, item_id in enumerate(RUN_IDS):
        out.append({
            **OO7, "id": item_id, "class": "decided", "kind": "decided.steward-run",
            "because": None, "title": f"Nightly review {n}", "state": "done", "options": [],
            "seen": True, "flagged": False,
            "since": f"2026-10-0{n + 2}T10:00:00Z", "updated_at": f"2026-10-0{n + 2}T10:00:00Z",
            "source": {"by": "steward", "run": f"run-{n}", "report": None},
        })
    return out


def _focused(page) -> str:
    return page.evaluate(
        "() => { const a = document.activeElement; if (!a) return '';"
        " if (a.tagName === 'SUMMARY') return 'summary';"
        " const li = a.closest('[data-inbox-item]'); return li ? li.getAttribute('data-inbox-item') : a.tagName; }")


def test_j_stops_on_a_closed_fold_once_and_walks_into_it_when_open(page, server):
    """Mutation: listStops() returns every link, as listLinks() did (rows
    inside a closed fold count as stops) -> red: `j` lands on a hidden row."""
    server.state.doc = _doc(OO7, *_runs())
    _open(page, server, ID_OO7)
    page.wait_for_selector("[data-inbox-fold] details:not([open])")
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("j")  # from the selected row, the next stop: the fold
    assert _focused(page) == "summary"
    page.keyboard.press("j")
    assert _focused(page) == "summary"  # the hidden rows are not stops
    page.keyboard.press("k")
    assert _focused(page) == ID_OO7
    page.keyboard.press("j")
    page.keyboard.press("Enter")
    _wait_for(lambda: page.evaluate("() => document.querySelector('[data-inbox-fold] details').open"))
    page.keyboard.press("j")
    assert _focused(page) in RUN_IDS
    page.keyboard.press("k")
    assert _focused(page) == "summary"


def test_on_a_narrow_window_the_item_comes_first_and_the_list_is_one_click_away(page, server):
    """Mutations: no narrow rule hiding the list -> red; the button does not
    toggle it -> red; opening an item leaves the list over it -> red."""
    server.state.doc = _doc(OO7, *_runs())
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, server, ID_OO7)
    button = page.locator("[data-show-list]")
    assert button.is_visible()  # control: the narrow layout is in effect
    assert not page.locator("#inbox-list").is_visible()
    button.click()
    _wait_for(lambda: page.locator("#inbox-list").is_visible())
    assert button.get_attribute("aria-expanded") == "true"
    page.locator("[data-inbox-fold] summary").click()
    page.locator(f'[data-inbox-item="{RUN_IDS[1]}"] a').click()
    page.wait_for_selector(f'#ws[data-item-id="{RUN_IDS[1]}"]')
    _wait_for(lambda: not page.locator("#inbox-list").is_visible())
    assert page.locator("[data-show-list]").get_attribute("aria-expanded") == "false"
