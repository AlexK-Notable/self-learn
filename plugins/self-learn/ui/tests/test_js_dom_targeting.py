"""U-target §6.1 Playwright group — `T1`-`T7`, `A1`-`A5`, `D1`-`D3b`,
`F1`/`F1b`/`F2`, `R1`, and `B2`/`B3`.

These are ORDERINGS — which row a keypress acts on, what a deferred fire
does, whether a refusal is visible — so every one is driven through the
REAL served page in a REAL browser running the REAL `app.js`. Never by
calling a helper in isolation: the whole class of defect this unit fixes
is invisible to a unit test of the resolver, because the resolver was
never the thing that was wrong. `document.querySelector` did exactly
what it says; the page had more than one match.

Three rules this module holds to, each earned:

  * **Selection is moved with REAL key presses** (`s`/`w`) and asserted
    in the DOM BEFORE the acting key is pressed — never by injecting
    `.selected` from script. An injected selection proves the resolver
    reads a class; it proves nothing about whether the keyboard can put
    the class where the operator meant.
  * **Requests are captured off the WIRE**, not inferred from DOM
    changes. "Row 2's bar armed" and "a POST went to row 2" are
    different claims, and only the second is what the operator's ledger
    experiences.
  * **Console output is captured for every criterion that asserts a
    warning OR asserts silence.** A dropped keystroke that says nothing
    is indistinguishable from a key that does nothing, which is half of
    what this unit is about.

The structural/render-shape halves (`B1`, `B4`, `C1`, `S1`, `S1b`, `S2`,
`SIG1`) live in `test_target_scoping.py`; a browser would add nothing
there.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn

from self_learn.verbs import GITOPS_DIRTY_MARKER

from self_learn_ui.app import create_app
from self_learn_ui.env import EnvConfig
from self_learn_ui.runner import FakeRunner, RunResult

from support import (
    make_behavior,
    make_env,
    merge_proposal_text,
    resolve_record_directly,
    seed_proposal,
    seed_record,
)

from conftest import _browser_or_sentinel

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

# Pin Playwright's browser registry to its REAL location NOW, at import —
# before any fixture redirects XDG_CACHE_HOME under a tmpdir (which would
# send Playwright looking for Chromium in the sandbox and never finding
# it). `conftest.py`'s `_browser_gate`/`_floor_playwright_browsers_path`
# reassert the identical value at fixture time (U-browserfail) -- this
# module-level copy stays, since it is what makes THIS constant correct
# even when this module is the ONLY one of the Playwright trio collected.
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"),
)

# Playwright's python package is an optional dev extra; the whole module
# skips cleanly when it is missing. A missing Chromium BUILD is a
# different matter (U-browserfail): `conftest.py`'s `browser`/
# `_browser_gate` fixtures now FAIL every dependent test below instead
# of skipping it.
sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.js

TOKEN = "u-target-js-token"
_STARTUP_TIMEOUT_S = 15.0
_SHUTDOWN_TIMEOUT_S = 10.0
#: How long to wait before concluding a keystroke issued NO request.
#: Loopback-fast; a real POST lands in single-digit ms here.
_QUIET_S = 0.6


# --------------------------------------------------------------- server


class ServerHandle:
    def __init__(self, base_url: str, app) -> None:
        self.base_url = base_url
        self._app = app

    @property
    def runner(self) -> FakeRunner:
        return self._app.state.runner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(ledger: Path, thread_name: str) -> Iterator[ServerHandle]:
    """The same uvicorn-in-thread bring-up `test_js_dom.py` uses (10 §0
    rules 7/8 — SELF_LEARN_HOME + XDG all under a pytest tmpdir, no
    network beyond 127.0.0.1, no global `os.environ` mutation: the route
    handlers shell `self-learn … --json` and `ledger._invoke_json` pins
    the sandbox home per call)."""
    port = _free_port()
    env = EnvConfig(
        self_learn_home=ledger,
        ui_port=port,
        ui_browser=None,
        pane_model="test-model",
        pane_budget_usd=1.0,
        pane_max_turns=5,
        pane_engine="sdk",
    )
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    uv_server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(uv_server.serve())

    thread = threading.Thread(target=_run, name=thread_name, daemon=True)
    thread.start()
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while not uv_server.started:
        if time.monotonic() > deadline:
            uv_server.should_exit = True
            raise AssertionError("in-process uvicorn never started")
        time.sleep(0.02)
    try:
        yield ServerHandle(f"http://127.0.0.1:{port}", app)
    finally:
        uv_server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT_S)


# -------------------------------------------------------------- ledgers

HOLD_A = "lrn-d1000001"
HOLD_B = "lrn-d1000002"


def _seed_front_ledger(tmp_path: Path, holding_ids: tuple[str, ...]) -> Path:
    """Front carrying *len(holding_ids)* holding rows. A holding row is a
    ROUTED record with an unconfirmed `recurrence-suspect` telemetry
    event — only the real `self-learn report --json` CLI computes them
    (`report.recurrence_suspects()` reads the tracked telemetry plane),
    so this builds the tracked files directly, the same way
    `test_js_dom.py::_seed_holding_ledger` does.

    Front's FIRST `[data-row]` is a bucket-table row, which owns no
    action at all — that is what `ensureRowSelected()` selects on load,
    and it is why the page-wide fallback exists (§4.2). `T2`/`T3`/`F2`/
    `D3`/`D3b` all act from that default position deliberately."""
    sb = make_env(tmp_path, skills=("s",))
    bucket_dir = sb.ledger / "skills" / "s"
    for rid in holding_ids:
        rec = make_behavior(scope="skill:s", record_id=rid, trigger=f"Holding {rid}.")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec, status="routed")
    tel = sb.ledger / "telemetry"
    tel.mkdir(parents=True, exist_ok=True)
    tel.joinpath("2026-07.u-target.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "kind": "recurrence-suspect",
                    "record": rid,
                    "nonce": f"u-target-nonce-{rid}",
                    "ts": "2026-07-20T00:00:00Z",
                }
            )
            + "\n"
            for rid in holding_ids
        ),
        encoding="utf-8",
    )
    return sb.ledger


@pytest.fixture(scope="module")
def front2_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    ledger = _seed_front_ledger(tmp_path_factory.mktemp("ut-front2"), (HOLD_A, HOLD_B))
    yield from _start_server(ledger, "ut-front2-uvicorn")


@pytest.fixture(scope="module")
def front1_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    ledger = _seed_front_ledger(tmp_path_factory.mktemp("ut-front1"), (HOLD_A,))
    yield from _start_server(ledger, "ut-front1-uvicorn")


PLAIN_A = "lrn-d2000001"
PLAIN_B = "lrn-d2000002"
CLUSTER_ID = "merge-deadbeef"
CLUS_M1 = "lrn-d3000001"
CLUS_M2 = "lrn-d3000002"
CLUS_P1 = "lrn-d3100001"
CLUS_P2 = "lrn-d3100002"
B2_CANON = "lrn-d4000001"
B2_ROW = "lrn-d4100001"
B3_CANON = "lrn-d5000001"
B3_ROW1 = "lrn-d5100001"
B3_ROW2 = "lrn-d5100002"
DRIFT_ROW1 = "lrn-d6000001"
DRIFT_ROW2 = "lrn-d6000002"


def _seed_bucket_ledger(tmp_path: Path) -> Path:
    """One ledger, five buckets — bucket pages are per-bucket, so they do
    not perturb each other the way a shared Front page would.

      skill:s  two plain pending rows                     (`T4`, `T5`)
      skill:t  a merge cluster over 2 records + 2 plain    (`T6`, `T7`,
               rows                                         CO-ARM)
      skill:u  a bulk-collapse group + exactly ONE record   (`B2`)
               row in another group
      skill:v  a bulk-collapse group in `skill-md` + TWO    (`B3`)
               record rows in `no-analysis`
      skill:d  two plain rows; row 1 is driven into the     (`F1b`)
               failed-route commit-drift state at test time

    `B3`'s destinations are PINNED rather than incidental (gate r2
    MINOR-2): `skill-md` is FIRST and `no-analysis` LAST in
    `_GROUP_ORDER` (`models.py:534`), so the bulk row provably precedes
    both record rows in document order and the group ordering cannot
    rescue the mutant. A bulk row renders only for a group whose EVERY
    row is `already_canon`, and `models.py` excludes `no-analysis` and
    `malformed` from bulk collapse entirely — so a record with NO
    proposal is guaranteed to stay a real, separate row."""
    sb = make_env(tmp_path, skills=("s", "t", "u", "v", "d"))

    for rid in (PLAIN_A, PLAIN_B):
        seed_record(sb.ledger, make_behavior(scope="skill:s", record_id=rid))

    for rid in (CLUS_M1, CLUS_M2, CLUS_P1, CLUS_P2):
        seed_record(sb.ledger, make_behavior(scope="skill:t", record_id=rid))
    pdir = sb.ledger / "skills" / "t" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{CLUSTER_ID}.yaml").write_text(
        merge_proposal_text(CLUSTER_ID, [CLUS_M1, CLUS_M2], CLUS_M1), encoding="utf-8"
    )

    seed_record(sb.ledger, make_behavior(scope="skill:u", record_id=B2_CANON))
    seed_proposal(
        sb.ledger, B2_CANON, scope="skill:u", destination="skill-md",
        already_canon=True, already_canon_reason="SKILL.md already says this",
    )
    seed_record(sb.ledger, make_behavior(scope="skill:u", record_id=B2_ROW))

    seed_record(sb.ledger, make_behavior(scope="skill:v", record_id=B3_CANON))
    seed_proposal(
        sb.ledger, B3_CANON, scope="skill:v", destination="skill-md",
        already_canon=True, already_canon_reason="SKILL.md already says this",
    )
    for rid in (B3_ROW1, B3_ROW2):
        seed_record(sb.ledger, make_behavior(scope="skill:v", record_id=rid))

    for rid in (DRIFT_ROW1, DRIFT_ROW2):
        seed_record(sb.ledger, make_behavior(scope="skill:d", record_id=rid))
    return sb.ledger


@pytest.fixture(scope="module")
def bucket_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    ledger = _seed_bucket_ledger(tmp_path_factory.mktemp("ut-bucket"))
    yield from _start_server(ledger, "ut-bucket-uvicorn")


@pytest.fixture(scope="module")
def browser(request, _browser_gate) -> Iterator["Browser"]:
    """U-browserfail: see `test_js_dom.py`'s identical `browser`
    fixture -- the launch/probe/escape-hatch logic lives once in
    `conftest.py`'s `_browser_or_sentinel`."""
    yield from _browser_or_sentinel(_browser_gate)


def _page_for(browser: "Browser") -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    try:
        yield pg
    finally:
        context.close()


@pytest.fixture
def front2_page(browser: "Browser", front2_server) -> Iterator["Page"]:
    yield from _page_for(browser)


@pytest.fixture
def front1_page(browser: "Browser", front1_server) -> Iterator["Page"]:
    yield from _page_for(browser)


@pytest.fixture
def bucket_page(browser: "Browser", bucket_server) -> Iterator["Page"]:
    yield from _page_for(browser)


# -------------------------------------------------------------- helpers


def _open(page: "Page", server: ServerHandle, path: str) -> None:
    if not page.context.cookies():
        page.goto(f"{server.base_url}/?token={TOKEN}", wait_until="load")
    page.goto(f"{server.base_url}{path}", wait_until="load")


def _posts(page: "Page") -> list[tuple[str, str | None]]:
    """Capture every POST off the wire. Returned list is LIVE — it keeps
    filling as the page runs, which is what the quiet-window assertions
    below read."""
    out: list[tuple[str, str | None]] = []

    def on_request(request) -> None:
        if request.method == "POST":
            out.append((request.url, request.post_data))

    page.on("request", on_request)
    return out


def _warnings(page: "Page") -> list[str]:
    out: list[str] = []
    page.on("console", lambda m: out.append(m.text) if m.type == "warning" else None)
    return out


def _stub(page: "Page", glob: str) -> None:
    """Fulfil a POST with `204 No Content` so htmx performs NO swap: the
    request still leaves the browser (and is captured), but the DOM is
    left exactly as it was, so several keys can be exercised against the
    SAME rendered page without a re-render between them."""
    page.route(glob, lambda route: route.fulfill(status=204))


def _row_ids(page: "Page") -> list[str | None]:
    """The record id each `[data-row]` owns, read from its action bar's
    id. `None` for a row that owns no bar (Front's bucket-table rows)."""
    return page.evaluate(
        """() => Array.from(
              document.querySelectorAll('#self-learn-ui-content [data-row]')
           ).map(r => {
              const bar = r.querySelector('.action-bar');
              return bar ? bar.id.replace('action-bar-', '') : null;
           })"""
    )


def _selection(page: "Page") -> list[bool]:
    return page.evaluate(
        """() => Array.from(
              document.querySelectorAll('#self-learn-ui-content [data-row]')
           ).map(r => r.classList.contains('selected'))"""
    )


def _selected_index(page: "Page") -> int:
    sel = _selection(page)
    assert sel.count(True) == 1, f"expected exactly one .selected row, got {sel}"
    return sel.index(True)


def _select(page: "Page", index: int) -> None:
    """Move `.selected` to *index* with REAL `s`/`w` presses, then assert
    it landed. Never injects the class."""
    for _ in range(40):
        current = _selected_index(page)
        if current == index:
            break
        page.keyboard.press("s" if current < index else "w")
    assert _selected_index(page) == index, (
        f"selection never reached row {index} (stuck at {_selected_index(page)})"
    )


def _quiet(page: "Page") -> None:
    """Let a would-be request land before concluding none did. A pure
    sleep lags CDP delivery on this host, so keep the channel active."""
    deadline = time.monotonic() + _QUIET_S
    while time.monotonic() < deadline:
        page.evaluate("() => true")
        time.sleep(0.02)


def _hint_text(page: "Page") -> str | None:
    return page.evaluate(
        """() => {
              const el = document.querySelector('[data-noop-hint-active]');
              return el ? el.textContent : null;
           }"""
    )


def _arm_urls(posts) -> list[str]:
    return [u for u, _ in posts if u.endswith("/action/arm")]


# ------------------------------------------------------- group T: scope


class TestTScopedDispatch:
    def test_t1_front_four_keys_act_on_the_selected_holding_row(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`T1` — Front, 2 holding rows, selection moved to holding row 2
        by real `s` presses (asserted in the DOM first). Each of `t`,
        `c`, `g`, `k` issues exactly one POST to row 2's arm URL, and the
        body carries ROW 2's `event` nonce.

        This is the defect as measured on the wire: all four used to POST
        row 1, with row 1's nonce, console empty."""
        _open(front2_page, front2_server, "/")
        _stub(front2_page, "**/action/arm")
        ids = _row_ids(front2_page)
        holding = [i for i, rid in enumerate(ids) if rid in (HOLD_A, HOLD_B)]
        assert len(holding) == 2, f"need 2 holding rows, got rows {ids}"
        row2 = holding[1]
        row2_id = ids[row2]
        _select(front2_page, row2)
        nonce = front2_page.evaluate(
            """(rid) => document.querySelector(
                   '#action-bar-' + rid + ' input[name="event"]'
               ).value""",
            row2_id,
        )
        assert nonce, "row 2 has no event nonce — the criterion cannot distinguish rows"

        posts = _posts(front2_page)
        for key in ("t", "c", "g", "k"):
            before = len(posts)
            front2_page.keyboard.press(key)
            _quiet(front2_page)
            fired = posts[before:]
            assert len(fired) == 1, f"{key!r} issued {len(fired)} POSTs: {fired}"
            url, body = fired[0]
            assert url.endswith(f"/record/{row2_id}/action/arm"), (
                f"{key!r} POSTed {url} — the selected row is {row2_id}"
            )
            assert f"event={nonce}" in (body or ""), (
                f"{key!r} carried the wrong nonce: {body!r}"
            )
            assert _selected_index(front2_page) == row2

    def test_t2_front_ambiguous_refuses_with_zero_requests_and_a_hint(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`T2` — BOTH halves asserted. Zero network requests AND a
        visible `[data-noop-hint-active]` line. A one-half criterion
        passes on a dead keyboard, which is why both are required."""
        _open(front2_page, front2_server, "/")
        assert _row_ids(front2_page)[_selected_index(front2_page)] is None, (
            "the load-default selection owns an action — this criterion "
            "needs the bucket-table row that owns none"
        )
        posts = _posts(front2_page)
        front2_page.keyboard.press("t")
        _quiet(front2_page)
        assert posts == [], f"the refusal still issued requests: {posts}"
        hint = _hint_text(front2_page)
        assert hint and "more than one row" in hint.lower(), (
            f"no visible refusal line (got {hint!r}) — a silent refusal is "
            "the same dead key, only quieter"
        )

    def test_t3_front_single_target_fallback_does_not_regress(
        self, front1_page: "Page", front1_server: ServerHandle
    ) -> None:
        """`T3` — Front with EXACTLY ONE holding row, selection at the
        load default (a bucket-table row, which owns no `tolerate`): `t`
        POSTs to that holding row. Today's correct single-target
        behaviour must not regress into a refusal."""
        _open(front1_page, front1_server, "/")
        _stub(front1_page, "**/action/arm")
        ids = _row_ids(front1_page)
        assert ids.count(HOLD_A) == 1 and ids.count(HOLD_B) == 0, (
            f"need exactly one holding row, got {ids}"
        )
        assert ids[_selected_index(front1_page)] is None
        posts = _posts(front1_page)
        front1_page.keyboard.press("t")
        _quiet(front1_page)
        assert _arm_urls(posts) == [
            f"{front1_server.base_url}/record/{HOLD_A}/action/arm"
        ], f"the single-target fallback did not fire: {posts}"

    def test_t4_bucket_four_keys_act_on_the_selected_record_row(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`T4` — the live one. The `user` bucket holds 14 pending
        records today, and every one of `e`/`x`/`f`/`g` acted on row 1
        regardless of which row the operator selected."""
        _open(bucket_page, bucket_server, "/bucket/skill/s")
        _stub(bucket_page, "**/action/arm")
        ids = _row_ids(bucket_page)
        assert len([i for i in ids if i]) == 2, f"need 2 record rows, got {ids}"
        row2 = 1
        row2_id = ids[row2]
        _select(bucket_page, row2)
        posts = _posts(bucket_page)
        for key in ("e", "x", "f", "g"):
            before = len(posts)
            bucket_page.keyboard.press(key)
            _quiet(bucket_page)
            fired = posts[before:]
            assert len(fired) == 1, f"{key!r} issued {len(fired)} POSTs: {fired}"
            assert fired[0][0].endswith(f"/record/{row2_id}/action/arm"), (
                f"{key!r} POSTed {fired[0][0]} — the selected row is {row2_id}"
            )

    def test_t5_detail_page_has_no_rows_and_still_dispatches(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`T5` — Detail has NO `[data-row]` at all (asserted in this same
        test), so resolution reaches the page-wide fallback. A rule that
        refused without a selection would make `e` dead on every Detail
        page — a targeting defect traded for a dead keyboard."""
        _open(bucket_page, bucket_server, f"/record/{PLAIN_A}")
        _stub(bucket_page, "**/action/arm")
        assert bucket_page.evaluate(
            "() => document.querySelectorAll('[data-row]').length"
        ) == 0, "the Detail page grew a [data-row] — this fixture no longer tests it"
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("e")
        _quiet(bucket_page)
        assert _arm_urls(posts) == [
            f"{bucket_server.base_url}/record/{PLAIN_A}/action/arm"
        ], posts

    def test_t6_expanded_cluster_row_refuses(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`T6` — the members share ONE `[data-row]`, so no selection can
        pick between them: `e` refuses. Acting on member 1 would carry
        `collapse=merge-…`, i.e. a MERGE, retiring the cluster's other
        members into a survivor the operator never chose."""
        _open(bucket_page, bucket_server, "/bucket/skill/t")
        _expand_cluster(bucket_page)
        cluster_idx = bucket_page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('#self-learn-ui-content [data-row]')
               ).findIndex(r => r.classList.contains('cluster-row'))"""
        )
        assert cluster_idx >= 0
        _select(bucket_page, cluster_idx)
        assert bucket_page.evaluate(
            """() => document.querySelectorAll(
                  '#self-learn-ui-content [data-row].selected '
                  + '[data-key-action="route"]'
               ).length"""
        ) >= 2, "the selected cluster row does not hold >=2 route buttons"
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("e")
        _quiet(bucket_page)
        assert posts == [], f"`e` acted on a cluster member: {posts}"
        assert (_hint_text(bucket_page) or "").lower().startswith("more than one row")

    def test_t7_record_row_on_a_cluster_page_never_hits_a_member(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`T7` — same page, a PENDING RECORD row selected instead. `e`
        POSTs that record's arm URL — never a cluster member's, and never
        with `collapse` in the body. `bucket.html` renders clusters
        BEFORE the groups, so document order used to hand this keystroke
        to member 1."""
        _open(bucket_page, bucket_server, "/bucket/skill/t")
        _expand_cluster(bucket_page)
        _stub(bucket_page, "**/action/arm")
        ids = _row_ids(bucket_page)
        record_rows = [i for i, rid in enumerate(ids) if rid in (CLUS_P1, CLUS_P2)]
        assert len(record_rows) == 2, f"expected 2 plain record rows, got {ids}"
        target = record_rows[1]
        target_id = ids[target]
        _select(bucket_page, target)
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("e")
        _quiet(bucket_page)
        assert len(posts) == 1, posts
        url, body = posts[0]
        assert url.endswith(f"/record/{target_id}/action/arm"), url
        assert "collapse" not in (body or ""), (
            f"the POST carried a merge collapse: {body!r}"
        )


def _expand_cluster(page: "Page") -> None:
    page.locator('.cluster-row button[data-key-action="drill_in"]').click()
    page.wait_for_selector(".cluster-expanded", state="attached")
    assert page.evaluate(
        """() => document.querySelectorAll(
              '.cluster-expanded [data-key-action="route"]'
           ).length"""
    ) >= 2, "the expanded cluster did not render >=2 member route buttons"


# ------------------------------------------------- group B: the bulk row


class TestBBulkCollapseDispatch:
    def test_b2_bulk_row_selected_refuses_instead_of_falling_through(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`B2` — the subtlest trap in the unit. A bulk-collapse group and
        EXACTLY ONE pending record row in another group, bulk row
        selected. `g` must show the bulk row's own hint and issue zero
        requests.

        The mutation that reddens it: drop the
        `[data-noop-hint][data-noop-action]` clause from
        `targetSelector`. The selected row then holds no `graduate`
        target at all, resolution falls through page-wide, finds the lone
        record row — and GRADUATES a record the operator never
        selected."""
        _open(bucket_page, bucket_server, "/bucket/skill/u")
        ids = _row_ids(bucket_page)
        assert len([i for i in ids if i]) == 1, (
            f"`B2` needs exactly ONE record row page-wide, got {ids} — with "
            "two, the mutation's page-wide lookup would be ambiguous and "
            "the criterion would pass for the wrong reason"
        )
        bulk_idx = bucket_page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('#self-learn-ui-content [data-row]')
               ).findIndex(r => r.classList.contains('bulk-collapse-row'))"""
        )
        assert bulk_idx >= 0, "no bulk-collapse row on this page"
        _select(bucket_page, bulk_idx)
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("g")
        _quiet(bucket_page)
        assert posts == [], f"`g` on the bulk row issued requests: {posts}"
        hint = _hint_text(bucket_page)
        assert hint and "click-only" in hint, (
            f"the bulk row's own hint is not what showed: {hint!r}"
        )

    def test_b3_bulk_row_precedes_the_rows_and_g_still_acts_on_row_2(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`B3` — its own fixture with the group destinations PINNED
        (gate r2 MINOR-2): the bulk group is `skill-md` (FIRST in
        `_GROUP_ORDER`) and the two record rows are `no-analysis` (LAST),
        so the bulk row provably precedes both and the ordering cannot
        rescue the mutant. Selection on record row 2.

        The "never `graduate-bulk`" half is a composite assertion guarded
        by `B1`/`B2`, not something `B3` claims to redden on its own."""
        _open(bucket_page, bucket_server, "/bucket/skill/v")
        _stub(bucket_page, "**/action/arm")
        ids = _row_ids(bucket_page)
        record_rows = [i for i, rid in enumerate(ids) if rid in (B3_ROW1, B3_ROW2)]
        assert len(record_rows) == 2, f"`B3` needs 2 record rows, got {ids}"
        bulk_idx = bucket_page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('#self-learn-ui-content [data-row]')
               ).findIndex(r => r.classList.contains('bulk-collapse-row'))"""
        )
        assert bulk_idx >= 0 and bulk_idx < record_rows[0], (
            f"the bulk row does not precede the record rows (bulk at "
            f"{bulk_idx}, rows at {record_rows}) — the mutant would be "
            "rescued by document order"
        )
        row2 = record_rows[1]
        row2_id = ids[row2]
        row1_id = ids[record_rows[0]]
        _select(bucket_page, row2)
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("g")
        _quiet(bucket_page)
        assert len(posts) == 1, posts
        url = posts[0][0]
        assert url.endswith(f"/record/{row2_id}/action/arm"), url
        assert "graduate-bulk" not in url
        assert row1_id not in url


# ------------------------------------------------ group A: the armed bar


def _co_arm(page: "Page", server: ServerHandle, *, select: str):
    """FIXTURE CO-ARM (§6.4) — the ONLY buildable two-armed state.

    `style.css:433` has set every `.action-bar[data-armed="false"]`
    button `visibility: hidden` while any bar is armed since 2026-07-17,
    so a real mouse click on a second BAR's trigger times out with
    "element is not visible". The one remaining door is the cluster
    member's "Route as survivor" button, which lives outside any
    `.action-bar` and so is not covered by that rule.

    ORDERING IS LOAD-BEARING: `.selected` is positioned BEFORE anything
    is armed, because `onKeyDown` consults the armed bar and returns
    before the `KEYMAP` switch — while a bar is armed, `s`/`w` reach
    `clickAction("disarm")` instead of moving the selection.

    The two-armed PRECONDITION is asserted explicitly. If `style.css` is
    ever widened to cover the cluster button these fixtures stop being
    buildable, and they must fail LOUDLY rather than silently degrade
    into one-armed tests that pass for the wrong reason."""
    _open(page, server, "/bucket/skill/t")
    _expand_cluster(page)
    ids = _row_ids(page)
    record_rows = [i for i, rid in enumerate(ids) if rid in (CLUS_P1, CLUS_P2)]
    assert len(record_rows) == 2, f"CO-ARM needs 2 plain record rows, got {ids}"
    armed_row, other_row = record_rows[0], record_rows[1]
    armed_id = ids[armed_row]
    selected_row = armed_row if select == "armed" else other_row

    # (1) selection first — before anything is armed.
    _select(page, selected_row)

    # (2) arm a RECORD row's bar with a real mouse click on its Approve.
    page.locator(f'#action-bar-{armed_id} [data-key-action="route"]').click()
    page.wait_for_selector(f'#action-bar-{armed_id}[data-armed="true"]')

    # (3) arm a CLUSTER MEMBER's bar — the click style.css:433 does not
    #     prevent, because the button has no .action-bar ancestor.
    page.locator(
        f'.cluster-expanded button[hx-post="/record/{CLUS_M1}/action/arm"]'
    ).click()
    # `wait_for_function` takes an ARROW-FUNCTION STRING, never a bare
    # expression: the app's CSP is `script-src 'self'` with no
    # `unsafe-eval`, and Playwright's bare-expression form uses `eval`
    # (spec §8.3). Measured while building this fixture: a
    # `wait_for_selector` on the member's own bar returns while the
    # outerHTML swap is still landing, so an immediate count read saw
    # ONE armed bar and the precondition failed spuriously ~0.25s before
    # it would have held.
    try:
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'.action-bar[data-armed=\"true\"]').length === 2",
            timeout=10000,
        )
    except Exception as exc:  # pragma: no cover - fixture-integrity path
        armed_now = page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('.action-bar[data-armed="true"]')
               ).map(e => e.id)"""
        )
        raise AssertionError(
            "the two-armed precondition does not hold — CO-ARM is no longer "
            f"buildable (armed bars: {armed_now}). If style.css:433 was "
            "widened to cover the cluster-member button, A1/A2/A3/A5 must be "
            "re-anchored or retired WITH the hazard (§10.4), never left "
            "silently passing as one-armed tests."
        ) from exc

    armed = page.evaluate(
        """() => Array.from(
              document.querySelectorAll('.action-bar[data-armed="true"]')
           ).map(e => e.id)"""
    )
    assert sorted(armed) == sorted([f"action-bar-{armed_id}", f"action-bar-{CLUS_M1}"]), (
        f"two bars are armed but not the expected two: {armed}"
    )
    assert _selected_index(page) == selected_row, (
        "arming moved the selection — the swap replaced the [data-row], not "
        "just the bar, and this fixture's model is wrong"
    )
    return {"ids": ids, "record_rows": record_rows, "armed_row": armed_row,
            "other_row": other_row, "armed_id": armed_id, "member_id": CLUS_M1}


class TestAArmedBranch:
    def test_a1_disarm_goes_to_the_selected_rows_bar(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`A1` — CO-ARM with `.selected` on the record row whose bar is
        armed. Any non-`Enter`, non-`n` key reaches the armed branch: the
        POST is THAT record's disarm, never the cluster member's.

        Page-wide resolution puts the cluster above the groups
        (`bucket.html:48` vs `:61`), so the key would disarm the MERGE
        arm instead of the record's."""
        state = _co_arm(bucket_page, bucket_server, select="armed")
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("t")
        _quiet(bucket_page)
        disarms = [u for u, _ in posts if "/action/disarm" in u]
        assert disarms == [
            f"{bucket_server.base_url}/record/{state['armed_id']}/action/disarm"
        ], f"the key disarmed the wrong bar: {posts}"

    def test_a2_two_armed_and_no_tiebreak_refuses(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`A2` — `.selected` on the SECOND, unarmed record row. `Enter`
        issues zero requests AND renders a `[data-noop-hint-active]`
        element. Both halves asserted.

        A deliberate behaviour change on a state that today resolves by
        document order: `Enter` POSTed the cluster member's confirm
        carrying `collapse=merge-…` — it EXECUTED A MERGE the operator
        never armed."""
        _co_arm(bucket_page, bucket_server, select="unarmed")
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("Enter")
        _quiet(bucket_page)
        assert posts == [], f"the refusal still issued requests: {posts}"
        hint = _hint_text(bucket_page)
        assert hint and "more than one action is armed" in hint.lower(), (
            f"no visible refusal line: {hint!r}"
        )

    def test_a3_escape_is_exempt_from_the_multi_armed_refusal(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`A3` — in `A2`'s exact state, `Escape` issues no
        confirm/disarm POST AND is not swallowed: the page navigates.
        Without the exemption the keyboard is TRAPPED until a mouse
        click — every key refused, no way out. `Escape` cannot
        disambiguate WHICH bar to cancel, but leaving abandons both
        harmlessly: arming renders a partial and issues no write."""
        _co_arm(bucket_page, bucket_server, select="unarmed")
        posts = _posts(bucket_page)
        before_url = bucket_page.url
        bucket_page.keyboard.press("Escape")
        bucket_page.wait_for_url(lambda u: u != before_url, timeout=10000)
        writes = [u for u, _ in posts if "/action/confirm" in u or "/action/disarm" in u]
        assert writes == [], f"Escape issued a confirm/disarm: {writes}"
        assert bucket_page.url != before_url, "Escape was swallowed — keyboard trapped"

    def test_a4_one_armed_bar_stays_reachable_from_an_unrelated_selection(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`A4` — Front, 2 holding rows, row 2 armed by a real mouse
        click (while nothing else is armed) and the selection left on
        row 1, positioned BEFORE arming: `Enter` POSTs row 2's confirm.
        This is the mouse-arm case, and it is why §1's non-objective 5
        rejects selection-follows-arming.

        *Honesty note carried from the spec: today's build also passes
        `A4`. It is a DESIGN pin, not a defect pin — its job is to forbid
        a plausible over-correction (armed resolution with no page-wide
        fallback), and its mutation is that over-correction rather than a
        revert to today.*"""
        _open(front2_page, front2_server, "/")
        ids = _row_ids(front2_page)
        holding = [i for i, rid in enumerate(ids) if rid in (HOLD_A, HOLD_B)]
        assert len(holding) == 2, ids
        _select(front2_page, holding[0])
        row2_id = ids[holding[1]]
        front2_page.locator(
            f'#action-bar-{row2_id} [data-key-action="dismiss_suspect"]'
        ).click()
        front2_page.wait_for_selector(f'#action-bar-{row2_id}[data-armed="true"]')
        assert _selected_index(front2_page) == holding[0]
        _stub(front2_page, "**/action/confirm")
        posts = _posts(front2_page)
        front2_page.keyboard.press("Enter")
        _quiet(front2_page)
        assert [u for u, _ in posts] == [
            f"{front2_server.base_url}/record/{row2_id}/action/confirm"
        ], f"the armed bar was not reachable from an unrelated selection: {posts}"

    def test_a5_selection_breaks_the_tie_toward_the_armed_row(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`A5` — CO-ARM with `.selected` on the record row whose bar is
        armed: `Enter` POSTs THAT record's confirm, never the cluster
        member's, and the body carries NO `collapse=`. The selection
        breaks the tie.

        The mutation's wire behaviour was measured at the gate:
        `/record/<cluster member 1>/action/confirm collapse=merge-…` —
        a WRITE THAT MERGES RECORDS."""
        state = _co_arm(bucket_page, bucket_server, select="armed")
        _stub(bucket_page, "**/action/confirm")
        posts = _posts(bucket_page)
        bucket_page.keyboard.press("Enter")
        _quiet(bucket_page)
        assert len(posts) == 1, posts
        url, body = posts[0]
        assert url.endswith(f"/record/{state['armed_id']}/action/confirm"), url
        assert "collapse" not in (body or ""), (
            f"the confirm carried a merge collapse: {body!r}"
        )


# --------------------------------------------- group D: the deferred fire


def _outstanding_swap(page: "Page") -> None:
    """Put ONE unresolved swap token in the bag, so the next dispatch
    defers instead of firing. Same synthetic `htmx:` CustomEvent seam the
    shipped `test_js_dom.py` uses; `detail: {}` on both halves keeps
    `pendingSwapKey`'s `===` comparison on the same (undefined) xhr."""
    page.evaluate(
        "document.dispatchEvent(new CustomEvent('htmx:afterSwap', {detail: {}}))"
    )


def _drop_warnings(warnings: list[str]) -> list[str]:
    return [w for w in warnings if "dropped" in w.lower()]


def _await_drop(page: "Page", warnings: list[str], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _drop_warnings(warnings):
            return
        page.evaluate("() => true")
        time.sleep(0.02)
    raise AssertionError(f"no drop warning arrived; console said: {warnings}")


class TestDDeferredFire:
    def test_d1_selection_moved_before_the_settle_drops_the_fire(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`D1` — with a swap outstanding, press `k` while row 2 is
        selected; before releasing the settle, move `.selected` to row 1;
        then release. The deferred fire is DROPPED: zero requests,
        exactly one `console.warn` naming the action.

        The DOM change and the releasing `afterSettle` go in ONE
        `page.evaluate` round trip — a deferred dispatch drops itself
        fail-closed 500 ms after deferring (N17), so a second round trip
        would race that bound."""
        _open(front2_page, front2_server, "/")
        ids = _row_ids(front2_page)
        holding = [i for i, rid in enumerate(ids) if rid in (HOLD_A, HOLD_B)]
        _select(front2_page, holding[1])
        warnings = _warnings(front2_page)
        posts = _posts(front2_page)
        _outstanding_swap(front2_page)
        front2_page.keyboard.press("k")
        front2_page.evaluate(
            """(idx) => {
                  const rows = Array.from(
                      document.querySelectorAll('#self-learn-ui-content [data-row]')
                  );
                  rows.forEach(r => r.classList.remove('selected'));
                  rows[idx].classList.add('selected');
                  document.dispatchEvent(
                      new CustomEvent('htmx:afterSettle', {detail: {}})
                  );
               }""",
            holding[0],
        )
        _await_drop(front2_page, warnings)
        assert posts == [], f"the stale deferred fire still POSTed: {posts}"
        drops = _drop_warnings(warnings)
        assert len(drops) == 1, f"expected exactly one drop warning: {warnings}"
        assert "dismiss_suspect" in drops[0], drops[0]

    def test_d2_replaced_bar_does_not_relocate_the_fire_onto_another_row(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`D2` — selection on row 1. Defer `k`; replace row 1's action
        bar with one that has no `dismiss_suspect` button (the shape an
        arm/confirm swap really produces); release. The fire is dropped
        with one warn and ZERO clicks — in particular it does not
        relocate onto row 2.

        Without the signature comparison the click lands on row 2 with
        ZERO console output, which is precisely today's measured
        behaviour."""
        _open(front2_page, front2_server, "/")
        ids = _row_ids(front2_page)
        holding = [i for i, rid in enumerate(ids) if rid in (HOLD_A, HOLD_B)]
        _select(front2_page, holding[0])
        row1_id = ids[holding[0]]
        warnings = _warnings(front2_page)
        posts = _posts(front2_page)
        _outstanding_swap(front2_page)
        front2_page.keyboard.press("k")
        front2_page.evaluate(
            """(barId) => {
                  const bar = document.getElementById(barId);
                  bar.outerHTML =
                      '<div id="' + barId + '" class="action-bar" '
                      + 'data-armed="false"><p>swapped</p></div>';
                  document.dispatchEvent(
                      new CustomEvent('htmx:afterSettle', {detail: {}})
                  );
               }""",
            f"action-bar-{row1_id}",
        )
        _await_drop(front2_page, warnings)
        assert posts == [], f"the fire relocated onto another row: {posts}"
        assert len(_drop_warnings(warnings)) == 1, warnings

    def test_d3_fire_time_ambiguity_drops_with_a_warning(
        self, front1_page: "Page", front1_server: ServerHandle
    ) -> None:
        """`D3` — the `ambiguous` leg, with a fixture that can actually
        produce it (gate r1 MINOR-2). ONE holding row, selection at the
        load default (a bucket-table row, so resolution at defer time is
        the page-wide fallback). Defer `t`; then, in the SAME
        `page.evaluate` round trip, inject a second holding row carrying
        its own `tolerate` button and release the settle. At fire time
        the page-wide count is 2 and the selected row still owns none ->
        `ambiguous` -> drop."""
        _open(front1_page, front1_server, "/")
        assert _row_ids(front1_page)[_selected_index(front1_page)] is None
        warnings = _warnings(front1_page)
        posts = _posts(front1_page)
        _outstanding_swap(front1_page)
        front1_page.keyboard.press("t")
        front1_page.evaluate(
            """() => {
                  const host = document.querySelector('.holding-row').parentNode;
                  const clone = document.createElement('div');
                  clone.className = 'holding-row';
                  clone.setAttribute('data-row', '');
                  clone.innerHTML =
                      '<div id="action-bar-injected" class="action-bar" '
                      + 'data-armed="false">'
                      + '<button type="button" data-key-action="tolerate">'
                      + 'Tolerate (t)</button></div>';
                  host.appendChild(clone);
                  document.dispatchEvent(
                      new CustomEvent('htmx:afterSettle', {detail: {}})
                  );
               }"""
        )
        _await_drop(front1_page, warnings)
        assert posts == [], f"an ambiguous re-resolution still fired: {posts}"
        drops = _drop_warnings(warnings)
        assert len(drops) == 1, warnings
        assert "ambiguous" in drops[0], drops[0]

    def test_d3b_fire_time_absence_drops_with_a_warning_not_silence(
        self, front1_page: "Page", front1_server: ServerHandle
    ) -> None:
        """`D3b` — the `none` leg, with ITS OWN fixture, deliberately NOT
        `D2`'s. ONE holding row, selection at the load default; defer `k`
        (resolution at defer time is `one`, via the page-wide fallback),
        then strip that row's `dismiss_suspect` button and release. At
        fire time the selected row has 0 matches AND the page-wide count
        is 0 -> `none`.

        `D2` does NOT produce this state and must not be reused for it:
        with two holding rows, fire-time re-resolution falls through to
        row 2 and returns `one` — `D2`'s drop comes from the SIGNATURE
        leg, never the `none` leg. Reusing it would ship this branch
        untested while the criterion went green off a different leg."""
        _open(front1_page, front1_server, "/")
        assert _row_ids(front1_page)[_selected_index(front1_page)] is None
        warnings = _warnings(front1_page)
        posts = _posts(front1_page)
        _outstanding_swap(front1_page)
        front1_page.keyboard.press("k")
        front1_page.evaluate(
            """() => {
                  document
                      .querySelectorAll('[data-key-action="dismiss_suspect"]')
                      .forEach(el => el.remove());
                  document.dispatchEvent(
                      new CustomEvent('htmx:afterSettle', {detail: {}})
                  );
               }"""
        )
        _await_drop(front1_page, warnings)
        assert posts == [], posts
        drops = _drop_warnings(warnings)
        assert len(drops) == 1, warnings
        assert '"none"' in drops[0], drops[0]


# ------------------------------------------------- group F: the note key


class TestFNoteInput:
    def test_f1_note_focuses_the_selected_rows_visible_input(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`F1` — Front, 2 holding rows, selection on row 2: `n` puts
        focus in ROW 2's note input, and that input is VISIBLE."""
        _open(front2_page, front2_server, "/")
        ids = _row_ids(front2_page)
        holding = [i for i, rid in enumerate(ids) if rid in (HOLD_A, HOLD_B)]
        _select(front2_page, holding[1])
        row2_id = ids[holding[1]]
        front2_page.keyboard.press("n")
        active = front2_page.evaluate(
            """() => {
                  const el = document.activeElement;
                  const bar = el ? el.closest('.action-bar') : null;
                  return {
                      name: el ? el.getAttribute('name') : null,
                      type: el ? el.getAttribute('type') : null,
                      bar: bar ? bar.id : null,
                  };
               }"""
        )
        assert active == {
            "name": "note", "type": "text", "bar": f"action-bar-{row2_id}"
        }, active

    def test_f1b_hidden_retry_note_never_takes_the_focus(
        self, bucket_page: "Page", bucket_server: ServerHandle
    ) -> None:
        """`F1b` — THE ONE CRITERION THAT REDDENS ON THE SELECTOR
        NARROWING ALONE.

        Row 1 is driven into the state `action_bar.html:67` needs: a
        FAILED `route` whose stderr carries the pinned dirty marker
        (`_commit_drift_eligible`) AND whose retry carried a note (`{% if
        commit_drift.retry.note %}`). The failed-verb re-render builds an
        UNARMED context with no `evidence`, so row 1's bar renders BOTH
        note inputs: the hidden retry one and the unarmed quad's text
        one.

        Selection is on ROW 1 — the row that owns both (gate r2 MAJOR-1:
        acting from row 2, which carries exactly one in-row `name=note`,
        made a correctly-scoped build with a WIDE selector pass `F1`,
        `F1b` and `F2` alike, leaving §4.2's `input[type="text"]` mandate
        unenforced anywhere in the 30).

        Widening the selector back to `input[name="note"]` with the row
        scoping intact gives 2 in-row matches -> `ambiguous` -> refuse ->
        nothing focused."""
        _open(bucket_page, bucket_server, "/bucket/skill/d")
        ids = _row_ids(bucket_page)
        assert len([i for i in ids if i]) == 2, f"`F1b` needs 2 record rows: {ids}"
        row1_id = ids[0]
        # Type a note into row 1's field, then blur so keys are live again.
        bucket_page.locator(
            f'#action-bar-{row1_id} input[type="text"][name="note"]'
        ).fill("retry note for the drift branch")
        bucket_page.evaluate("() => document.activeElement.blur()")
        _select(bucket_page, 0)
        bucket_page.keyboard.press("e")
        bucket_page.wait_for_selector(f'#action-bar-{row1_id}[data-armed="true"]')
        bucket_server.runner.queue_result(
            RunResult(1, stderr=f"self-learn route: target {GITOPS_DIRTY_MARKER} present")
        )
        bucket_page.keyboard.press("Enter")
        bucket_page.wait_for_selector('[data-key-action="commit_drift_arm"]')

        # PRECONDITION, stated in full: row 1's bar carries exactly one
        # hidden and exactly one text note input. Without both, this
        # criterion cannot redden on the narrowing.
        counts = bucket_page.evaluate(
            """(barId) => {
                  const bar = document.getElementById(barId);
                  return {
                      hidden: bar.querySelectorAll(
                          'input[type="hidden"][name="note"]').length,
                      text: bar.querySelectorAll(
                          'input[type="text"][name="note"]').length,
                  };
               }""",
            f"action-bar-{row1_id}",
        )
        assert counts == {"hidden": 1, "text": 1}, (
            f"row 1's bar does not carry both note inputs ({counts}) — the "
            "narrowing has nothing to be measured against"
        )
        assert _selected_index(bucket_page) == 0, "the confirm swap moved the selection"

        bucket_page.keyboard.press("n")
        active = bucket_page.evaluate(
            """() => {
                  const el = document.activeElement;
                  const bar = el ? el.closest('.action-bar') : null;
                  return {
                      name: el ? el.getAttribute('name') : null,
                      type: el ? el.getAttribute('type') : null,
                      bar: bar ? bar.id : null,
                  };
               }"""
        )
        assert active == {
            "name": "note", "type": "text", "bar": f"action-bar-{row1_id}"
        }, active

    def test_f2_ambiguous_note_leaves_focus_alone_and_hints(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`F2` — Front, 2 holding rows, selection on a bucket-table row:
        `n` leaves `document.activeElement` UNCHANGED and shows the
        multi-note hint. Both halves."""
        _open(front2_page, front2_server, "/")
        assert _row_ids(front2_page)[_selected_index(front2_page)] is None
        before = front2_page.evaluate("() => document.activeElement.tagName")
        front2_page.keyboard.press("n")
        after = front2_page.evaluate("() => document.activeElement.tagName")
        assert after == before, f"focus moved: {before} -> {after}"
        hint = _hint_text(front2_page)
        assert hint and "more than one note field" in hint.lower(), hint


# --------------------------------------------- group R: the return contract


class TestRReturnContract:
    def test_r1_absent_target_still_reports_not_handled(
        self, front2_page: "Page", front2_server: ServerHandle
    ) -> None:
        """`R1` — Front renders NO `data-key-action="up"` (asserted in
        this same test), so resolution returns `none`, which must keep
        reporting NOT handled: `Escape` falls through to
        `window.history.back()` and the page navigates. Reporting
        *handled* for `none` would leave `Escape` dead on Front.

        Test mechanics: a fresh page with a single navigation has no
        history entry to go back to, so this navigates TWICE (`/report`,
        then `/`). Without the second navigation the test would read "no
        navigation happened" on a CORRECT build."""
        _open(front2_page, front2_server, "/report")
        front2_page.goto(f"{front2_server.base_url}/", wait_until="load")
        assert front2_page.evaluate(
            "() => document.querySelectorAll('[data-key-action=\"up\"]').length"
        ) == 0, "Front grew an `up` target — this criterion no longer tests `none`"
        front2_page.keyboard.press("Escape")
        front2_page.wait_for_url(lambda u: u.endswith("/report"), timeout=10000)
        assert front2_page.url.endswith("/report")
