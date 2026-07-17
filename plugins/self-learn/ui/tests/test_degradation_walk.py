"""U9 — degradation walk (09 §5, 10 §3 U9 row): closes gaps the existing
suite left in the 09 §5 table that U2-U8 didn't already cover as a
byproduct of their own feature work. See the U9 build report for the
full row-by-row ledger; this file holds only what was GENUINELY missing:

- SSE reconnect strip markup + poll-fallback wiring (CI-limited per the
  build brief — asserts markup/JS hooks exist and the poll constant is
  wired; the live reconnect behavior is a U11 browser-trial item).
- A real bug this walk found and fixed: the SSE scope-matching logic
  (static/app.js's old ``currentScope()``) never matched a page to its
  OWN bucket's watcher-driven refresh events — ``body.dataset.bucket``
  was read but never written by any template, so Bucket pages only ever
  matched literal "front"-scoped events and Detail pages only matched
  their own exact ``record:<id>`` scope (explicit post-action pushes),
  never their bucket's scope (external mutations — a concurrent
  ``/self-learn:review`` CLI session bypassing this server entirely,
  exactly 09 §3's "External mutations ... surface the same way" and the
  "resolved elsewhere" row's P3-8 case). Front page had the same
  problem in reverse: it never matched a *bucket*-scoped event even
  though it aggregates every bucket's counts. Fixed by rendering
  ``data-bucket`` on Bucket/Detail (a new ``body_attrs`` template block)
  and rewriting app.js's scope match to a set-membership check
  (``currentScopes()``) where the Front page matches every scope.
- Worker-overdue status-strip alarm, end to end through a real route
  render (the model-level logic was already exhaustively covered in
  test_models_front.py; this closes the "does the ROUTE actually print
  the text label" gap — Y-10's text-label-not-color-alone rule).
- Bulk-graduate resume idempotency (10 §5 playbook: "re-running the
  bulk row is idempotent — already-resolved ids vanish from the
  group") through a REAL bucket model rebuild, not just the FakeRunner
  argv-sequence test test_routes.py already has.
- Port-in-use fails cleanly (10 §5 playbook: "override + one-line log")
  — a real ``self-learn-ui serve`` subprocess against an already-bound
  port, via the same real-subprocess harness test_serve.py established.
- Stale proposal (``record_sha`` mismatch) still leaves approve armable
  (09 §5: "Badge + hint to Iterate; approve stays available") — proven
  end to end through the REAL CLI's own freshness computation, not a
  constructed model dict.

httpx against the ASGI app for route-level checks (T-A's established
pattern); static content assertions for the JS/markup-only rows (CI
cannot execute app.js — 10 §2's stated CI/live split); one real
subprocess for the port-in-use row (test_serve.py's own pattern). No
network beyond 127.0.0.1; no real model; throwaway homes + XDG
redirects throughout (10 §0 rules 7/8).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui import ledger
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner

from support import bare_ledger, make_behavior, make_env, resolve_record_directly, seed_proposal, seed_record

TOKEN = "test-token"
HX = {"HX-Request": "true"}

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def make_client(sb, *, runner: FakeRunner | None = None, port: int = 7357) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


# ------------------------------------------------ SSE reconnect / poll row


class TestSSEReconnectMarkupAndPollWiring:
    """09 §5: "SSE disconnects ... Client falls back to the 10s poll and
    retries SSE; a thin 'live updates reconnecting' strip shows
    meanwhile." The behavioral half (does a real browser actually swap
    the strip in/out) is a U11 live-browser item; this is the CI-level
    half — the markup exists, is wired into every page (base.html), and
    app.js references the exact same element id + a bounded poll
    interval."""

    def test_reconnect_strip_markup_present_on_a_real_rendered_page(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert 'id="self-learn-ui-reconnect-strip"' in r.text
        assert "reconnecting" in r.text.lower()

    def test_reconnect_strip_starts_hidden(self, tmp_path: Path) -> None:
        # Y-10 posture check by proxy: the strip must not be permanently
        # visible chrome — it is a transient degradation notice.
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert '<div id="self-learn-ui-reconnect-strip" class="reconnect-strip" hidden>' in r.text

    def test_app_js_wires_the_reconnect_strip_toggle_to_sse_lifecycle(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        assert "self-learn-ui-reconnect-strip" in app_js
        assert "onerror" in app_js
        assert "onopen" in app_js
        assert "showReconnectStrip" in app_js

    def test_app_js_wires_a_bounded_ten_second_poll_fallback(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        assert "POLL_FALLBACK_MS = 10000" in app_js
        assert "setInterval" in app_js
        assert "clearInterval" in app_js


# ------------------------------------------ SSE scope-matching (bug found)


class TestSSEScopeMatchesOwnBucket:
    """A genuine gap this walk found while verifying the "resolved
    elsewhere mid-view" row (09 §5/§3 P3-8): the watcher only ever
    emits "front" or "bucket:<name>" scopes (ledger.py's
    _scope_for_path has no per-record granularity — a directory watch
    event can't know which file inside it changed), so a passive
    Bucket/Detail viewer MUST match on its own bucket's scope to notice
    an external mutation (a concurrent CLI verb this server never gets
    a POST for). Before this fix, no template ever wrote
    ``data-bucket`` and app.js's old ``currentScope()`` read
    ``body.dataset.bucket`` — always undefined — so Bucket pages only
    ever matched the literal "front" scope, Detail pages only matched
    their own exact record scope, and Front page (which aggregates
    every bucket's counts) never matched a bucket-scoped event either.
    Fixed: templates render ``data-bucket``; app.js matches a scope set
    where the Front page matches everything. These are the CI-provable
    halves (markup presence + the exact bucket-name string the watcher
    would emit); the live "does a real SSE frame actually trigger the
    reload" check is a U11 browser-trial item, same CI/live split as
    the reconnect strip above.
    """

    def test_bucket_page_renders_its_own_bucket_name_as_a_data_attribute(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)  # the bucket must exist on disk to be discoverable
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert 'data-bucket="s"' in r.text

    def test_detail_page_renders_both_its_record_and_its_bucket_scope(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert f'data-record-id="{rec.id}"' in r.text
        assert 'data-bucket="s"' in r.text

    def test_rendered_bucket_name_matches_what_the_watcher_would_emit(
        self, tmp_path: Path
    ) -> None:
        """Cross-check: the value app.js reads off the DOM
        (``data-bucket="s"`` -> client builds "bucket:s") must be
        byte-identical to what ``ledger._scope_for_path`` computes for a
        real filesystem change under that bucket — otherwise the fix is
        silently inert even though both halves look right in
        isolation."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert 'data-bucket="s"' in r.text

        pending_path = sb.ledger / "skills" / "s" / "pending" / f"{rec.id}.md"
        server_side_scope = ledger._scope_for_path(sb.ledger, pending_path)
        client_side_scope = "bucket:" + "s"  # what app.js builds from data-bucket="s"
        assert server_side_scope == client_side_scope == "bucket:s"

    def test_app_js_scope_match_considers_record_and_bucket_and_front_matches_all(
        self,
    ) -> None:
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        assert "currentScopes" in app_js
        assert "data-bucket" in app_js
        assert 'scopes.push("record:"' in app_js
        assert 'scopes.push("bucket:"' in app_js
        # The Front-page-matches-everything rule (it aggregates every
        # bucket) — the fix that closes the reverse half of the bug.
        assert 'mine.indexOf("front")' in app_js

    def test_base_template_has_a_body_attrs_extension_point(self) -> None:
        base_html = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
        assert "block body_attrs" in base_html


# --------------------------------------------------- worker-overdue strip


class TestWorkerOverdueRendersAsATextLabel:
    """09 §5: "Worker overdue / never ran -> Status strip alarm (reuses
    the worker's own escalation thresholds)." The model-level logic
    (test_models_front.py) is exhaustively covered; what was missing is
    confirming the ROUTE actually prints the text label (Y-10: "every
    badge/status distinction carries a text label or glyph — hue alone
    is forbidden" — this is the strip's own instance of that rule)."""

    def test_unanalyzed_supply_with_no_worker_run_shows_the_overdue_label(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)  # no proposal seeded -> unanalyzed supply
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert "worker overdue" in r.text.lower()

    def test_no_unanalyzed_supply_never_alarms_even_on_a_fresh_ledger(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)  # nothing seeded at all
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert "worker overdue" not in r.text.lower()


# ---------------------------------------------- stale proposal, approve live


class TestStaleProposalStillAllowsApprove:
    """09 §5: "Proposal stale (record_sha mismatch) -> Badge + hint to
    Iterate; approve stays available (the verb re-validates
    authoritatively at apply — the badge is advisory UI, the CLI is the
    enforcer)." test_models_detail.py proves the badge at the model
    level with a CONSTRUCTED ``proposal_fresh=False`` dict; what was
    missing is an end-to-end check through the REAL CLI's own
    freshness computation (``seed_proposal``'s default ``record_sha``
    is a dummy value that never matches a real record's computed hash
    -- i.e. every proposal seeded without an explicit correct sha is
    ALREADY stale from the CLI's point of view; several existing route
    tests rely on this incidentally without asserting it) — and that
    the action bar's approve/route key renders regardless, since
    nothing in detail.html gates it on freshness."""

    def test_stale_badge_renders_and_route_action_key_still_present(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")  # dummy sha -> stale
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "stale" in r.text.lower()
        assert 'data-key-action="route"' in r.text


# ------------------------------------------------- bulk-graduate resume


class TestBulkGraduateResumeIdempotency:
    """10 §5 playbook: "Bulk loop interrupted by machine sleep/crash ...
    re-running the bulk row is idempotent (already-resolved ids vanish
    from the group)." test_routes.py's TestBulkGraduate already proves
    the argv sequence (halt-on-failure, terminal push) against a FAKE
    runner; what neither file had was a check that the underlying
    BUCKET MODEL — rebuilt fresh from a REAL ledger, as it would be on
    the next page load after a crash mid-loop — actually drops an
    already-resolved id from the homogeneous group, and that the
    remaining ids alone still resolve cleanly through the route."""

    def test_already_resolved_id_vanishes_from_the_bulk_collapse_group(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, destination="skill-md", already_canon=True)
            ids.append(rec.id)

        # Simulate: the bulk loop graduated ids[0] for real before the
        # machine slept/crashed mid-loop (bypassing the fake runner —
        # this is a direct ledger mutation, same helper the
        # resolved-elsewhere test uses).
        first = ids[0]
        rec0 = make_behavior(scope="skill:s", record_id=first)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec0, destination="skill-md")

        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert "2 already-canon records" in r.text.lower()
        assert first not in r.text
        assert ids[1] in r.text
        assert ids[2] in r.text

    def test_rerunning_the_bulk_row_with_only_the_remaining_ids_succeeds(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, destination="skill-md", already_canon=True)
            ids.append(rec.id)

        first = ids[0]
        rec0 = make_behavior(scope="skill:s", record_id=first)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec0, destination="skill-md")

        c, runner = make_client(sb)
        remaining = ids[1:]
        r = c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(remaining)},
            headers=HX,
        )
        assert r.status_code in (200, 303)
        # Only the two SURVIVING ids are dispatched — the already-resolved
        # id never re-enters the loop because the re-rendered page never
        # offered it in the hidden `ids` field (the test above proves
        # that half); this proves the loop itself is clean given that
        # input, with no special-casing needed for a stale id.
        assert runner.calls == [
            ["graduate", remaining[0], "--no-push"],
            ["graduate", remaining[1], "--no-push"],
            ["push"],
        ]


# --------------------------------------------------------- port in use


class _FreePort:
    @staticmethod
    def pick() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class TestPortInUseFailsCleanly:
    """10 §5 playbook: "Port in use: SELF_LEARN_UI_PORT override +
    one-line log." The override half is exercised by every test in
    test_serve.py (each picks its own free port via the env var); what
    was missing is proof that binding an ALREADY-occupied port fails
    fast and visibly rather than hanging or silently exiting 0 (uvicorn
    could, in principle, swallow a bind error internally — it does
    not, verified here against the real subprocess, same process
    boundary systemd's ExecStart uses)."""

    def test_serve_exits_nonzero_with_a_clear_bind_error_on_an_occupied_port(
        self, tmp_path: Path
    ) -> None:
        port = _FreePort.pick()
        # Hold the port for the whole test — a real bind conflict, not a
        # simulated one.
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        try:
            home = bare_ledger(tmp_path)
            runtime_dir = tmp_path / "runtime"
            cache_home = tmp_path / "cache"
            runtime_dir.mkdir()
            cache_home.mkdir()

            env = dict(os.environ)
            env["SELF_LEARN_HOME"] = str(home)
            env["XDG_RUNTIME_DIR"] = str(runtime_dir)
            env["XDG_CACHE_HOME"] = str(cache_home)
            env["SELF_LEARN_UI_PORT"] = str(port)

            proc = subprocess.run(
                [sys.executable, "-m", "self_learn_ui.cli", "serve"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert proc.returncode != 0, (
                f"serve exited 0 on an occupied port — stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}"
            )
            stderr_lower = proc.stderr.lower()
            assert "already in use" in stderr_lower or "address" in stderr_lower, (
                f"expected a clear bind-error log line, got stderr={proc.stderr!r}"
            )
        finally:
            holder.close()
