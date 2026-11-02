"""Real SSE, real settings holds, and observed navigation requests in Chromium."""
import pytest
from playwright.sync_api import Error

from test_js_settings import server, browser, page, _save, ROW  # noqa: F401


pytestmark = pytest.mark.js


def _requests(page):
    requests = []
    page.on("request", lambda r: requests.append(r) if r.is_navigation_request() else None)
    return requests


def test_change_burst_waits_for_quiet_then_reloads_once(page, server):
    assert page.is_visible("#settings-q")
    requests = _requests(page)
    for _ in range(5):
        server.push_refresh()
        page.wait_for_timeout(400)
    assert len(requests) == 0
    page.wait_for_timeout(1800)
    assert len(requests) == 1


def test_refresh_does_not_restart_a_navigation_in_flight(page, server):
    from test_js_dom import _wrap_event_source
    _wrap_event_source(page)
    page.reload(wait_until="load")
    server.wait_for_subscriber()
    assert page.is_visible("#settings-q")
    assert page.evaluate("window.__esInstances.length") == 1
    held = []
    page.route("**/settings", lambda route: held.append(route))
    try:
        # Queue late frames before navigation: Playwright evaluation itself
        # waits for navigation once the response is held. Browser timers can
        # still deliver queued events to the old document.
        page.evaluate("""() => {
            for (const delay of [2200, 2600, 3000]) {
                setTimeout(() => window.__esInstances[0].dispatchEvent(new MessageEvent(
                    'message', {data: JSON.stringify({type: 'refresh', scope: 'front'})})), delay);
            }
        }""")
        server.push_refresh()
        page.wait_for_timeout(1800)
        assert len(held) == 1  # positive control: the reload really started
        page.wait_for_timeout(3200)
        assert len(held) == 1
    finally:
        for route in held:
            try:
                route.fulfill(status=200, body="<html><body>Reload completed</body></html>")
            except Error:
                pass  # a broken in-flight guard may have cancelled an earlier request
        page.unroute("**/settings")
    page.wait_for_selector("text=Reload completed")


def test_dismiss_releases_a_refresh_after_the_quiet_period(page, server):
    _save(page, server)
    assert page.is_visible(f"{ROW} [data-setting-message]")
    requests = _requests(page)
    server.push_refresh()
    page.wait_for_timeout(1800)
    assert len(requests) == 0
    page.click(f"{ROW} [data-setting-dismiss]")
    page.wait_for_timeout(800)
    assert len(requests) == 1


def test_unsaved_value_survives_burst_until_taken_back(page, server):
    page.fill(f"{ROW} input[name=value]", "11")
    assert page.locator(f"{ROW} form[data-setting-dirty]").count() == 1
    requests = _requests(page)
    for _ in range(3):
        server.push_refresh()
        page.wait_for_timeout(200)
    page.wait_for_timeout(1800)
    assert len(requests) == 0
    assert page.input_value(f"{ROW} input[name=value]") == "11"
    page.fill(f"{ROW} input[name=value]", "8.0")
    page.wait_for_timeout(800)
    assert len(requests) == 1
