"""Humane UI lane 5 (proposal §7b) in a real browser: the "Summarise this"
button is the only thing that starts a summary. Loading the page starts
none; one click starts one, the box shows it working and then the summary;
a reload starts nothing more and still shows the summary.

Driven through test_js_inbox.py's in-process server (page reads
monkeypatched; the summary verb is its scripted FakeAskRunner, so no model
is ever called).
"""

from __future__ import annotations

import pytest

from test_js_inbox import (  # noqa: F401 -- fixtures
    _wait_for,
    browser,
    page,
    server,
)

pytestmark = pytest.mark.js

REPORT = """# Overseer report — 2026-11-01   run 92d6fec6   actor overseer   model claude-x

## Examined
- The steward's decisions hold on 33 of the 35 cases it read.

## Questions for you
- none

## Refused / could not do
- none
"""


def test_only_the_button_starts_a_summary_and_a_reload_reuses_it(page, server):
    """Mutations: the GET starts the run (a page view calls the model) ->
    red at the first count; the box never polls (`hx-trigger` dropped) ->
    red: the summary never appears without a reload."""
    home = server.app.state.env.self_learn_home
    (home / "overseer").mkdir(parents=True, exist_ok=True)
    (home / "overseer" / "latest-report.md").write_text(REPORT, encoding="utf-8")
    ask = server.app.state.ask_runner
    ask.summary_calls.clear()

    page.goto(f"{server.base_url}/overseer-report", wait_until="load")
    page.wait_for_selector("#in-short-box [data-in-short-start]")
    assert ask.summary_calls == []

    page.click("#in-short-box [data-in-short-start]")
    page.wait_for_selector("#in-short-box [data-in-short-summary]", timeout=10_000)
    assert "Sandbox: this summary is scripted" in page.inner_text("#in-short-box")
    _wait_for(lambda: len(ask.summary_calls) == 1)
    assert ask.summary_calls == [("overseer-report", "2026-11-01", False)]

    page.reload(wait_until="load")
    page.wait_for_selector("#in-short-box [data-in-short-summary]")
    assert page.locator("#in-short-box [data-in-short-start]").count() == 0
    assert len(ask.summary_calls) == 1
