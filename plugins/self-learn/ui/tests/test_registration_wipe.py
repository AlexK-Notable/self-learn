"""U14 empirical wipe-pin (10 §3 U14: "empirical wipe-pin FIRST"; 09 §11
Y-16: "The wipe mechanism must be PINNED EMPIRICALLY at build ... BEFORE
fixing").

Reproduces the failed-registration error wipe end-to-end at the server
seam — a REAL :class:`RealRunner` (fake failing ``self-learn``
subprocess) wired to the app's REAL :class:`RefreshHub`, driven through
the REAL host-add confirm route — and pins the facts the 10-appendix
U14 entry records:

1. **The wipe path** (code-read prime suspect, CONFIRMED): a failed
   ``host add`` carries no ``lrn-`` id on argv, so the runner's
   UNCONDITIONAL post-verb refresh push (success and failure alike) is
   scope ``front`` — the broadcast every connected page answers with a
   full ``window.location.reload()`` at app.js's chokepoint, which
   re-renders the bar from files and erases the just-swapped error
   partial.

2. **The F4 ordering** (SSE frame vs htmx swap): the ``RefreshEvent``
   is queued for the SSE writer BEFORE the confirm handler renders the
   error partial — the frame is on its way while the error HTML does
   not yet exist, so client-side it can beat the htmx swap; a
   marker-only defer predicate would re-create the original symptom.
   This is why the Y-16 defer predicate carries the in-flight leg (b)
   (flag set at form submit, cleared on completion/error/abort).

3. **The keyup candidate, ruled implausible**: the error leg renders
   ``data-armed="false"``, so the keydown handler's armed branch (the
   any-key-disarms path) cannot fire on the post-confirm keyup. Braced
   anyway — the chokepoint defer covers both mechanisms.

The browser-level halves (the observed vanish pre-fix; the error
surviving a forced push once the defer lands) are the U14 DoD live
re-trial items — this module is the headless seam pin the appendix
entry cites.
"""

from __future__ import annotations

import sys
from pathlib import Path

from starlette.testclient import TestClient

import self_learn_ui.routes as routes_mod
from self_learn_ui import ledger as ui_ledger
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import RealRunner

from support import make_env, make_knowledge

FAKE_SELF_LEARN = Path(__file__).parent / "fixtures" / "fake_self_learn.py"
TOKEN = "test-token"

#: The live case's stderr, near-verbatim (hosts.py's committability
#: refusal — the exact text the user's keyboards registration hit).
COMMITTABILITY_STDERR = (
    "self-learn host add: project host /home/user/repos/keyboards is not "
    "a git repo — canon hosts must be committable (doc 13 §4 two-phase "
    "routing); fix hosts.yaml via `self-learn host add` / `host rebind`"
)


def _failing_runner_env() -> dict[str, str]:
    return {
        "FAKE_SELF_LEARN_EXIT_CODE": "2",
        "FAKE_SELF_LEARN_STDERR": COMMITTABILITY_STDERR,
    }


def _unregistered_plain_dir_sandbox(tmp_path: Path):
    """The keyboards reproduction: an unregistered project whose path is
    a PLAIN DIRECTORY (not a git repo), holding one pending record."""
    sb = make_env(tmp_path)
    foreign = tmp_path / "keyboards"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("plain project, no .git\n", encoding="utf-8")
    from self_learn.ledger_ops import create_record

    rec = make_knowledge(
        scope="project", fact="The inner keymap repo is an untracked boundary."
    )
    create_record(sb.ledger, rec, project_path=foreign)
    bucket_name = next((sb.ledger / "projects").iterdir()).name
    return sb, foreign, rec, bucket_name


class TestWipePin:
    async def test_failed_host_add_push_is_front_scoped(self, tmp_path: Path) -> None:
        """Fact 1's first half, at the runner seam: the post-verb push
        fires on FAILURE, and `host add` argv (no lrn- token) scopes it
        `front` — the broadcast scope app.js reloads every page for."""
        scopes: list[str] = []
        runner = RealRunner(
            home=tmp_path / "ledger-home",
            argv_prefix=[sys.executable, str(FAKE_SELF_LEARN)],
            env=_failing_runner_env(),
            refresh_callback=scopes.append,
        )
        result = await runner.run(["host", "add", str(tmp_path / "keyboards")])
        assert result.ok is False
        assert COMMITTABILITY_STDERR in result.stderr
        assert scopes == ["front"]  # broadcast — every page reloads

    def test_wipe_chain_queues_the_frame_before_the_error_renders(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The end-to-end chain through the REAL confirm route, plus the
        F4 ordering ruling: the RefreshEvent is queued on the hub (i.e.
        handed to the SSE writer) BEFORE the error partial is rendered —
        timeline asserted ``push → render``. Client-side the frame can
        therefore beat the htmx swap, so a marker-only defer predicate
        is insufficient (leg (b) required)."""
        sb, _foreign, _rec, name = _unregistered_plain_dir_sandbox(tmp_path)

        hub = ui_ledger.RefreshHub()
        timeline: list[tuple[str, str]] = []

        def push_spy(scope: str = "front") -> None:
            timeline.append(("push", scope))
            hub.force_refresh(scope)

        runner = RealRunner(
            home=sb.ledger,
            argv_prefix=[sys.executable, str(FAKE_SELF_LEARN)],
            env=_failing_runner_env(),
            refresh_callback=push_spy,
        )
        real_render = routes_mod._render

        def render_spy(request, template_name, ctx, status_code=200):
            timeline.append(("render", template_name))
            return real_render(request, template_name, ctx, status_code)

        monkeypatch.setattr(routes_mod, "_render", render_spy)

        app = create_app(
            env=load_env(sb.env),
            token=TOKEN,
            runner=runner,
            refresh_hub=hub,
            start_watcher=False,
        )
        q = hub.subscribe()  # a connected SSE consumer, subscribed pre-POST
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)

        r = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        # The stderr made it into the rendered bar — the error partial
        # the reload then erases browser-side.
        assert "canon hosts must be committable" in r.text
        # THE ORDERING RULING (F4): the push was queued before the error
        # partial existed — frame-before-swap is guaranteed server-side.
        assert timeline == [
            ("push", "front"),
            ("render", "partials/host_add_bar.html"),
        ]
        # And the frame really is sitting in the SSE consumer's queue.
        assert q.get_nowait().scope == "front"

    def test_error_leg_renders_unarmed_so_keyup_cannot_disarm_it(
        self, tmp_path: Path
    ) -> None:
        """Fact 3: the second wipe candidate (any-key-disarms keyup) is
        implausible — the error rendering is NOT an armed bar, and
        app.js's disarm-on-any-key branch only runs while a
        [data-armed="true"] bar exists."""
        sb, _foreign, _rec, name = _unregistered_plain_dir_sandbox(tmp_path)
        hub = ui_ledger.RefreshHub()
        runner = RealRunner(
            home=sb.ledger,
            argv_prefix=[sys.executable, str(FAKE_SELF_LEARN)],
            env=_failing_runner_env(),
            refresh_callback=hub.force_refresh,
        )
        app = create_app(
            env=load_env(sb.env),
            token=TOKEN,
            runner=runner,
            refresh_hub=hub,
            start_watcher=False,
        )
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)
        r = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-armed="true"' not in r.text
        assert 'data-armed="false"' in r.text
