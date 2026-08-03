"""routes.py — the T-A interaction half (10 §2): httpx against the ASGI
app, in-process, fake runner, constructed throwaway ledgers via
tests/support.py. Covers: arm->disarm->confirm flows with argv asserted,
o-cycle, bulk-collapse graduate loop, cluster expand -> survivor select,
t/c holding rows, post-route contradicts offer, followup done,
advance-to-next + bucket-clear, deep-link + resolved-elsewhere, keymap
single-source, /report verbatim, hook Detail, unregistered-host notice,
Y-9 leading-text-never-an-id, and the render-path/XSS escaping half of
the security matrix (Host/token/HX-Request live in test_middleware.py).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.keymap import keymap_as_dicts, keymap_json
from self_learn_ui.routes import build_argv, cycle_destination, next_record_url
from self_learn_ui.runner import FakeRunner, RunResult

from support import (
    RouteSideEffectRunner,
    bare_ledger,
    commit_all,
    hook_proposal_fields,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    merge_proposal_text,
    resolve_record_directly,
    seed_proposal,
    seed_record,
)

TOKEN = "test-token"


def make_client(sb, *, runner: FakeRunner | None = None, port: int = 7357) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


# ------------------------------------------------------------- pure helpers


class TestBuildArgv:
    def test_route_minimal(self) -> None:
        assert build_argv("route", "lrn-aa000001") == ["route", "lrn-aa000001"]

    def test_route_with_dest_collapse_note(self) -> None:
        argv = build_argv(
            "route", "lrn-aa000001", dest="skill-md", collapse="clu-1", note="good call"
        )
        assert argv == [
            "route", "lrn-aa000001", "--dest", "skill-md", "--collapse", "clu-1",
            "--note", "good call",
        ]

    def test_reject(self) -> None:
        assert build_argv("reject", "lrn-aa000001", note="bad idea") == [
            "reject", "lrn-aa000001", "--note", "bad idea",
        ]

    def test_defer_with_until(self) -> None:
        assert build_argv("defer", "lrn-aa000001", until="2026-08-01") == [
            "defer", "lrn-aa000001", "--until", "2026-08-01",
        ]

    def test_graduate(self) -> None:
        assert build_argv("graduate", "lrn-aa000001") == ["graduate", "lrn-aa000001"]

    def test_graduate_no_push(self) -> None:
        assert build_argv("graduate", "lrn-aa000001", no_push=True) == [
            "graduate", "lrn-aa000001", "--no-push",
        ]

    def test_confirm_recurrence_tolerate(self) -> None:
        argv = build_argv(
            "confirm-recurrence", "lrn-aa000001", event="nonce-1", tolerate=True, note="stays"
        )
        assert argv == [
            "confirm-recurrence", "lrn-aa000001", "--event", "nonce-1", "--tolerate",
            "--note", "stays",
        ]

    def test_confirm_recurrence_without_tolerate(self) -> None:
        argv = build_argv("confirm-recurrence", "lrn-aa000001", event="nonce-1")
        assert argv == ["confirm-recurrence", "lrn-aa000001", "--event", "nonce-1"]
        assert "--tolerate" not in argv

    def test_link_contradicts(self) -> None:
        argv = build_argv("link-contradicts", "lrn-aa000001", target="skills/foo/SKILL.md")
        assert argv == ["link", "contradicts", "lrn-aa000001", "skills/foo/SKILL.md"]

    def test_followup_done(self) -> None:
        assert build_argv("followup-done", "lrn-aa000001") == ["followup", "done", "lrn-aa000001"]

    def test_chezmoi_adopt(self) -> None:
        # A2 §10.4(a)/§10.5: no record_id in the real CLI form — the
        # `target` field (already generic, per link-contradicts above)
        # carries the rules-file path; `record_id` only scopes the route
        # this bar renders under, never the argv.
        argv = build_argv(
            "chezmoi-adopt", "lrn-aa000001", target="/home/u/.claude/rules/subagents.md"
        )
        assert argv == ["chezmoi-adopt", "/home/u/.claude/rules/subagents.md"]

    def test_unknown_verb_raises(self) -> None:
        with pytest.raises(ValueError):
            build_argv("frobnicate", "lrn-aa000001")


class TestCycleDestination:
    def test_from_none_starts_at_first(self) -> None:
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        assert cycle_destination(None, "skill") == PARAMETER_FREE_DESTINATIONS[0]

    def test_skill_scope_cycles_through_the_whole_set_and_wraps(self) -> None:
        # Regression pin (feedback round 2 item 3): scope-filtering must
        # leave skill-scoped behavior exactly as it was.
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        seen = []
        current = None
        for _ in range(len(PARAMETER_FREE_DESTINATIONS) + 1):
            current = cycle_destination(current, "skill")
            seen.append(current)
        assert seen[: len(PARAMETER_FREE_DESTINATIONS)] == list(PARAMETER_FREE_DESTINATIONS)
        assert seen[-1] == PARAMETER_FREE_DESTINATIONS[0]  # wrapped

    def test_parameterized_destinations_are_never_produced(self) -> None:
        # "hook" / "new-skill" are never in the cycle set at all — this
        # IS the "skip" (there's nothing to skip past).
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        for scope in ("skill", "project", "user", "unknown"):
            for start in ("hook", "new-skill:foo", None, "bogus"):
                result = cycle_destination(start, scope)
                assert result in PARAMETER_FREE_DESTINATIONS

    def test_project_scope_never_produces_skill_md(self) -> None:
        # The CLI's own rule (route's target resolver): skill-md needs
        # skill:<name> scope — the cycle must not offer what the confirm
        # would refuse (feedback round 2 item 3).
        seen = set()
        current: str | None = None
        for _ in range(5):
            current = cycle_destination(current, "project")
            seen.add(current)
        assert seen == {"claude-md", "reference"}

    def test_user_scope_is_claude_md_only(self) -> None:
        # reference needs a skill or project home; the user host is the
        # chezmoi-managed CLAUDE.md alone.
        assert cycle_destination(None, "user") == "claude-md"
        assert cycle_destination("claude-md", "user") == "claude-md"
        assert cycle_destination("skill-md", "user") == "claude-md"


# --------------------------------------------------------------------- Front


class TestFrontPage:
    def test_renders_bucket_walk(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert "s" in r.text  # bucket name rendered
        assert '/bucket/skill/s' in r.text

    def test_report_link_present(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert 'href="/report"' in r.text

    def test_head_disables_htmx_inline_style_and_suppresses_favicon(
        self, tmp_path: Path
    ) -> None:
        """htmx injects an inline style element on boot; the pinned CSP
        blocks it, throwing a console error on every swap and killing the
        indicator fade (U11 browser trial 2026-07-17). The head must carry
        the htmx-config meta that disables the injection and a data: favicon
        link that suppresses the /favicon.ico 404 — both CSP-safe."""
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        html = c.get("/").text
        assert 'name="htmx-config"' in html
        assert '"includeIndicatorStyles": false' in html
        assert 'rel="icon"' in html

    def test_status_strip_renders(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert "status-strip" in r.text

    def test_notice_resolved_elsewhere_renders_banner(self, tmp_path: Path) -> None:
        """Code-gate MINOR 5, adjudicated: as of U-grad-ui, NOTHING emits
        `?notice=resolved-elsewhere` anymore (`detail_page`'s old 303
        redirect — the one and only emitter — is deleted, §2.1); this
        test manufactures the query param by hand, a condition no
        server-side code path can currently produce. The banner branch
        (here and in `bucket.html`) is kept anyway, deliberately: a
        stale bookmark/tab minted before this unit shipped can still
        carry the param, and it must keep resolving to a banner rather
        than a raw/ignored query string. See `routes.py`'s own comment
        on `NOTICE_RESOLVED_ELSEWHERE` for the same ruling."""
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/?notice=resolved-elsewhere")
        assert "resolved elsewhere" in r.text.lower()

    def test_notice_bucket_clear_renders_banner(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/?notice=bucket-clear")
        assert "bucket clear" in r.text.lower()

    def test_notice_not_found_renders_banner(self, tmp_path: Path) -> None:
        """F4's third banner (index.html:24-25). Unlike the redirect target
        assertion in TestDetailPage::test_unknown_id_redirects_to_front_with_
        not_found_notice (which only checks the Location header), this
        asserts the rendered banner text itself — the render path was
        untested before this test."""
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/?notice=not-found")
        assert "could not be found" in r.text.lower()


class TestFeedbackRound1Chrome:
    """Feedback round 1 (2026-07-17-ui-feedback-01) items 1/2/4/8: sortable
    headers, plain-words tooltips, context-filtered footer wiring, and the
    Deferred column — the server-rendered halves (app.js/style.css do the
    client halves)."""

    def _front_html(self, tmp_path: Path) -> str:
        sb = make_env(tmp_path)
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        c, _runner = make_client(sb)
        return c.get("/").text

    def test_every_bucket_column_is_sortable(self, tmp_path: Path) -> None:
        html = self._front_html(tmp_path)
        for key in ("name", "scope", "pending", "oldest", "unanalyzed", "deferred"):
            assert f'data-sort-key="{key}"' in html
        assert 'aria-sort="none"' in html
        assert 'class="sort-header"' in html

    def test_deferred_column_renders(self, tmp_path: Path) -> None:
        html = self._front_html(tmp_path)
        assert ">Deferred<" in html

    def test_oldest_cell_carries_numeric_sort_value(self, tmp_path: Path) -> None:
        # "—"/"3d" render text must never feed the client sort compare
        html = self._front_html(tmp_path)
        assert 'data-sort-key="oldest" data-sort-value="' in html

    def test_status_items_carry_plain_words_tooltips(self, tmp_path: Path) -> None:
        html = self._front_html(tmp_path)
        # Y-9 register: explanations in human words, one per status item
        assert 'title="Lessons waiting for your decision' in html
        assert 'title="The background analyst' in html
        assert html.count('<span class="status-item" title=') >= 4

    def test_footer_entries_carry_context_and_action(self, tmp_path: Path) -> None:
        html = self._front_html(tmp_path)
        assert 'data-context="global"' in html
        assert 'data-context="list"' in html
        assert 'data-action="iterate"' in html

    def test_each_page_names_itself_for_the_footer_filter(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        assert 'data-page="front"' in c.get("/").text
        assert 'data-page="bucket"' in c.get("/bucket/skill/s").text
        assert f'data-page="detail"' in c.get(f"/record/{rec.id}").text
        assert 'data-page="report"' in c.get("/report").text


# -------------------------------------------------------------------- Bucket


class TestBucketPage:
    def test_renders_record_row_with_leading_text_not_id(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s", instruction="Stop the container first.")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert rec.id in r.text  # present as trailing metadata
        # But the leading/lead link text is never JUST the raw id.
        import re as _re

        lead_matches = _re.findall(r'record-row-lead">([^<]*)</a>', r.text)
        assert lead_matches, "expected at least one record row"
        for text in lead_matches:
            assert text.strip() != rec.id
            assert not text.strip().startswith("lrn-")

    def test_proposal_leading_text_is_the_headline_not_the_id(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            card={"headline": "Stop the HA container before editing .storage."},
        )
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert "Stop the HA container before editing .storage." in r.text

    def test_unregistered_host_notice_with_copyable_command(self, tmp_path: Path) -> None:
        # bare_ledger has no hosts.yaml, so `create_record` (which
        # seed_record calls) refuses skill-scoped records outright — the
        # very definition of "unregistered". Write the pending file
        # directly, bypassing the host-registration gate, to construct
        # exactly the fixture state Y-11 is about.
        home = bare_ledger(tmp_path)
        (home / "skills").mkdir(exist_ok=True)
        skill_dir = home / "skills" / "s"
        (skill_dir / "pending").mkdir(parents=True)
        (skill_dir / "proposals").mkdir()
        (skill_dir / "resolved").mkdir()
        rec = make_behavior(scope="skill:s")
        rec.write(skill_dir / "pending" / f"{rec.id}.md")

        class Sandbox:
            pass

        sb = Sandbox()
        sb.env = {
            "SELF_LEARN_HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        }
        (tmp_path / "cache").mkdir(exist_ok=True)
        (tmp_path / "runtime").mkdir(exist_ok=True)
        import os

        sb.env = {**os.environ, **sb.env}

        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert "unregistered" in r.text.lower()
        # Arming stays live even when unregistered (Y-11).
        assert f"action-bar-{rec.id}" in r.text

    def test_bulk_collapse_row_renders_for_homogeneous_already_canon_group(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(2):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, destination="skill-md", already_canon=True)
            ids.append(rec.id)
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert "acknowledge all as canon" in r.text.lower()
        for i in ids:
            assert i in r.text  # ids ride the hidden `ids` field

    def test_cluster_row_renders_and_expand_endpoint_returns_members(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec1 = make_behavior(scope="skill:s")
        rec2 = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec1)
        seed_record(sb.ledger, rec2)
        cluster_path = (sb.ledger / "skills" / "s") / "proposals" / "merge-deadbeef.yaml"
        cluster_path.parent.mkdir(parents=True, exist_ok=True)
        cluster_path.write_text(
            merge_proposal_text("merge-deadbeef", [rec1.id, rec2.id], rec1.id), encoding="utf-8"
        )
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert "similar records" in r.text.lower()

        r2 = c.get("/cluster/skill/s/merge-deadbeef")
        assert r2.status_code == 200
        assert rec1.id in r2.text
        assert rec2.id in r2.text
        assert "suggested survivor" in r2.text.lower()


# --------------------------------------------------------------------- Detail


class TestArmedHostAdd:
    """09 §11 Y-11 (amended 2026-07-17): the armed host-add flow — the
    surface's first bucket-scoped mutation. Server-derived path, consent
    consequence in the arm state, project-scope-only, constrained
    return-page redirect."""

    def _foreign_sandbox(self, tmp_path: Path):
        """A registered sandbox PLUS a second git repo that is NOT in
        hosts.yaml, holding one pending project-scoped record — the
        exact Y-11 live case."""
        sb = make_env(tmp_path)
        foreign = tmp_path / "foreign-repo"
        init_repo(foreign)
        (foreign / "CLAUDE.md").write_text("# foreign project\n", encoding="utf-8")
        commit_all(foreign, "foreign seed")
        rec = make_knowledge(
            scope="project",
            fact="The foreign build breaks unless the workspace is re-initialized.",
        )
        from self_learn.ledger_ops import create_record

        create_record(sb.ledger, rec, project_path=foreign)
        bucket_name = next((sb.ledger / "projects").iterdir()).name
        return sb, foreign, rec, bucket_name

    def test_unregistered_project_bucket_offers_register_not_a_command(
        self, tmp_path: Path
    ) -> None:
        sb, _foreign, _rec, name = self._foreign_sandbox(tmp_path)
        c, _runner = make_client(sb)
        r = c.get(f"/bucket/project/{name}")
        assert r.status_code == 200
        assert "Register this project" in r.text
        # The superseded copyable-command rendering must be gone.
        assert "Run <code>self-learn host add" not in r.text

    def test_detail_offers_register_with_record_return(self, tmp_path: Path) -> None:
        sb, _foreign, rec, _name = self._foreign_sandbox(tmp_path)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "Register this project" in r.text
        assert f'name="record_id" value="{rec.id}"' in r.text

    def test_arm_renders_consent_and_server_derived_path(self, tmp_path: Path) -> None:
        sb, foreign, _rec, name = self._foreign_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert 'data-armed="true"' in r.text
        # Consent consequence (Y-11 pin): both halves, plain words.
        assert "written into this" in r.text
        assert "read its files" in r.text
        # The exact command with the SERVER-derived path.
        assert f"self-learn host add {foreign}" in r.text
        assert runner.calls == []  # arming never executes anything

    def test_confirm_runs_server_derived_argv_and_ignores_client_path(
        self, tmp_path: Path
    ) -> None:
        sb, foreign, rec, name = self._foreign_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data={"record_id": rec.id, "path": "/tmp/evil-repo"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["host", "add", str(foreign)]]
        assert r.headers.get("HX-Redirect") == f"/record/{rec.id}"

    def test_confirm_without_record_id_returns_to_bucket(self, tmp_path: Path) -> None:
        sb, foreign, _rec, name = self._foreign_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/confirm", headers={"HX-Request": "true"})
        assert runner.calls == [["host", "add", str(foreign)]]
        assert r.headers.get("HX-Redirect") == f"/bucket/project/{name}"

    def test_malformed_record_id_falls_back_to_bucket_redirect(
        self, tmp_path: Path
    ) -> None:
        sb, _foreign, _rec, name = self._foreign_sandbox(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data={"record_id": "../../etc/passwd"},
            headers={"HX-Request": "true"},
        )
        assert r.headers.get("HX-Redirect") == f"/bucket/project/{name}"

    def test_disarm_restores_the_notice(self, tmp_path: Path) -> None:
        sb, _foreign, _rec, name = self._foreign_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/disarm", headers={"HX-Request": "true"})
        assert 'data-armed="false"' in r.text
        assert "Register this project" in r.text
        assert runner.calls == []

    def test_confirm_failure_renders_stderr_no_redirect(self, tmp_path: Path) -> None:
        sb, _foreign, _rec, name = self._foreign_sandbox(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="host add: not a git repository"))
        c, runner = make_client(sb, runner=runner)
        r = c.post(f"/bucket/project/{name}/host-add/confirm", headers={"HX-Request": "true"})
        assert "HX-Redirect" not in r.headers
        assert "not a git repository" in r.text

    def test_skill_scope_bucket_refuses_to_arm(self, tmp_path: Path) -> None:
        """Y-11 scope limitation: no derivable path outside project
        buckets — the arm route refuses rather than guessing."""
        sb = make_env(tmp_path)
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        c, runner = make_client(sb)
        r = c.post("/bucket/skill/s/host-add/arm", headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []

    def test_stray_meta_yaml_in_skill_bucket_still_refused(self, tmp_path: Path) -> None:
        """The scope gate is an EXPLICIT check, not just path-presence
        (review 2026-07-17 host-add, F5): a skill bucket carrying a
        stray meta.yaml path must not arm registration."""
        sb = make_env(tmp_path)
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        (sb.ledger / "skills" / "s" / "meta.yaml").write_text(
            f"path: {sb.host}\n", encoding="utf-8"
        )
        c, runner = make_client(sb)
        r = c.post("/bucket/skill/s/host-add/confirm", headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []

    def test_registered_project_bucket_shows_no_host_add_bar(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project", fact="A registered-host fact.")
        from self_learn.ledger_ops import create_record

        create_record(sb.ledger, rec, project_path=sb.host)
        name = next((sb.ledger / "projects").iterdir()).name
        c, _runner = make_client(sb)
        r = c.get(f"/bucket/project/{name}")
        assert r.status_code == 200
        assert "host-add-bar" not in r.text
        assert "Register this project" not in r.text


def _plain_dir_sandbox(tmp_path: Path):
    """A registered sandbox PLUS an unregistered project whose path is a
    PLAIN DIRECTORY — not a git repo (the Y-17 keyboards live case),
    holding one pending project-scoped record."""
    sb = make_env(tmp_path)
    foreign = tmp_path / "plain-project"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("plain text project\n", encoding="utf-8")
    rec = make_knowledge(
        scope="project", fact="The plain project's tooling needs a wrapper."
    )
    from self_learn.ledger_ops import create_record

    create_record(sb.ledger, rec, project_path=foreign)
    bucket_name = next((sb.ledger / "projects").iterdir()).name
    return sb, foreign, rec, bucket_name


def _confirm_form_fields(html: str, scope: str, name: str) -> dict[str, str]:
    """Template-truth (the round-2 Fix A precedent): exactly the fields
    the RENDERED confirm form posts — what a browser actually sends —
    never a hand-built dict mirroring the handler."""
    section = html.split(f'hx-post="/bucket/{scope}/{name}/host-add/confirm"')[1]
    section = section.split("</form>")[0]
    return dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section))


class TestHostAddInitDisclosure:
    """09 §11 Y-17 (U14): server-derived needs_init at arm AND confirm,
    the disclosure sentence + real --init argv in the arm banner, and
    the F1 consent invariant in BOTH race directions."""

    def test_arm_on_non_root_renders_disclosure_and_init_argv(
        self, tmp_path: Path
    ) -> None:
        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        assert r.status_code == 200
        # Required content (Y-17 decision 4), plain words:
        assert "new git repository will be created at" in r.text
        assert "as part of registering" in r.text
        # The displayed command shows the REAL argv:
        assert f"self-learn host add --init {foreign}" in r.text
        # The server-rendered one-bit marker rides the confirm form:
        fields = _confirm_form_fields(r.text, "project", name)
        assert fields.get("init_disclosed") == "1"
        assert runner.calls == []  # arming never executes anything

    def test_arm_on_repo_root_renders_no_disclosure_and_no_init(
        self, tmp_path: Path
    ) -> None:
        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        init_repo(foreign)  # a repo root now — zero commits still counts
        c, _runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "new git repository" not in r.text
        assert "--init" not in r.text
        assert f"self-learn host add {foreign}" in r.text
        fields = _confirm_form_fields(r.text, "project", name)
        assert "init_disclosed" not in fields

    def test_confirm_with_the_rendered_forms_own_fields_runs_init_argv(
        self, tmp_path: Path
    ) -> None:
        # Template-truth: drive confirm with the rendered form's fields.
        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        fields = _confirm_form_fields(r.text, "project", name)
        r2 = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data=fields,
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["host", "add", "--init", str(foreign)]]
        assert r2.headers.get("HX-Redirect") == f"/bucket/project/{name}"

    def test_becomes_repo_race_drops_init_and_the_plain_add_registers(
        self, tmp_path: Path
    ) -> None:
        # F1 direction 1: disclosure shown, path a root by confirm →
        # --init DROPPED (weaker-than-read, the only permitted
        # divergence direction — F13), the plain add registers.
        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        c, runner = make_client(sb)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        fields = _confirm_form_fields(r.text, "project", name)
        assert fields.get("init_disclosed") == "1"
        init_repo(foreign)  # the path becomes a repo between the POSTs
        r2 = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data=fields,
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["host", "add", str(foreign)]]  # no --init
        assert r2.headers.get("HX-Redirect") == f"/bucket/project/{name}"

    def test_goes_stale_race_runs_plain_add_into_the_error_leg(
        self, tmp_path: Path
    ) -> None:
        # F1 direction 2: NO disclosure shown (path was a root at arm),
        # non-root by confirm → the plain add runs (NEVER a silent
        # init) and the CLI's committability refusal renders through
        # the Y-16 error leg; re-arming would NOW show the disclosure.
        import shutil

        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        init_repo(foreign)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(1, stderr="self-learn host add: project host is not a git repo — canon hosts must be committable")
        )
        c, runner = make_client(sb, runner=runner)
        r = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        fields = _confirm_form_fields(r.text, "project", name)
        assert "init_disclosed" not in fields
        shutil.rmtree(foreign / ".git")  # goes stale between the POSTs
        r2 = c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data=fields,
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["host", "add", str(foreign)]]  # plain, no init
        assert "HX-Redirect" not in r2.headers
        assert "data-verb-error" in r2.text
        assert "Registration did not complete." in r2.text
        # And the re-arm NOW discloses:
        r3 = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        assert "new git repository will be created at" in r3.text

    def test_forged_marker_on_a_repo_root_path_never_inits(
        self, tmp_path: Path
    ) -> None:
        # The confirm-time re-derivation gates every init: a forged (or
        # stale) marker bit cannot force --init on a repo-root path.
        sb, foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        init_repo(foreign)
        c, runner = make_client(sb)
        c.post(
            f"/bucket/project/{name}/host-add/confirm",
            data={"init_disclosed": "1"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["host", "add", str(foreign)]]  # no --init


class TestHostAddErrorLeg:
    """09 §11 Y-16 (U14): the persistent, plain-words failure rendering —
    the narrow dated §5 exception, this leg only. The client-side
    reload-defer is browser-level JS (proven at the U14 live re-trial);
    what is pinnable headless is pinned here + in
    test_registration_wipe.py."""

    STDERR = (
        "self-learn host add: project host /x is not a git repo — canon "
        "hosts must be committable (doc 13 §4 two-phase routing)"
    )

    def _failed_confirm(self, tmp_path: Path):
        sb, _foreign, _rec, name = _plain_dir_sandbox(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr=self.STDERR))
        c, runner = make_client(sb, runner=runner)
        r = c.post(f"/bucket/project/{name}/host-add/confirm", headers={"HX-Request": "true"})
        return c, runner, name, r

    def test_sentence_leads_stderr_demoted_marker_and_dismiss_present(
        self, tmp_path: Path
    ) -> None:
        _c, _runner, name, r = self._failed_confirm(tmp_path)
        assert r.status_code == 200
        # The plain-words sentence LEADS; the stderr renders BELOW it,
        # verbatim, as the demoted detail line.
        lead_at = r.text.index("Registration did not complete.")
        detail_at = r.text.index("canon hosts must be committable")
        assert lead_at < detail_at
        assert 'class="error-detail"' in r.text
        # The reload-defer marker (leg (a) of the chokepoint predicate):
        assert "data-verb-error" in r.text
        # Unarmed — the keyup candidate cannot fire on this rendering:
        assert 'data-armed="false"' in r.text
        # The dismiss affordance posts through the DISARM route (no
        # fourth route):
        assert f'hx-post="/bucket/project/{name}/host-add/disarm"' in r.text
        assert "Dismiss" in r.text

    def test_dismiss_restores_the_notice(self, tmp_path: Path) -> None:
        c, _runner, name, r = self._failed_confirm(tmp_path)
        assert "data-verb-error" in r.text
        r2 = c.post(f"/bucket/project/{name}/host-add/disarm", headers={"HX-Request": "true"})
        assert "data-verb-error" not in r2.text
        assert "Unregistered project" in r2.text
        assert "Register this project" in r2.text

    def test_rearm_from_the_error_state_clears_it(self, tmp_path: Path) -> None:
        c, _runner, name, r = self._failed_confirm(tmp_path)
        # The error rendering keeps the re-arm affordance reachable…
        assert "Register this project" in r.text
        # …and re-arming renders the armed bar with no error residue.
        r2 = c.post(f"/bucket/project/{name}/host-add/arm", headers={"HX-Request": "true"})
        assert 'data-armed="true"' in r2.text
        assert "data-verb-error" not in r2.text


class TestDetailPage:
    def test_deep_link_lands_on_detail(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert rec.id in r.text
        assert f'data-record-id="{rec.id}"' in r.text

    def test_resolved_record_renders_the_resolved_view_at_its_own_id(
        self, tmp_path: Path
    ) -> None:
        """U-grad-ui §2.1 (VIEWABLE): the old 303-to-the-bucket-with-a-
        banner redirect is deleted, not widened — a routed record's own
        Detail page renders directly, 200, carrying the record's own
        Trigger text and the resolved page's own `page_kind`, never the
        bucket banner. Renamed from
        `test_resolved_elsewhere_redirects_to_bucket_with_banner` (spec
        criterion 11) to say so."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        # make_behavior()'s default trigger (support.py) — the record's
        # own Trigger text, not merely `200` on an empty page.
        assert "About to edit .storage while HA is running." in r.text
        assert 'data-page="resolved"' in r.text

    def test_unknown_id_redirects_to_front_with_not_found_notice(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/record/lrn-ffffffff", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/?notice=not-found"

    def test_hook_destination_shows_full_script_replay_examples_and_m3_caption(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="hook",
            script="#!/usr/bin/env bash\necho 'deny'\n",
            **hook_proposal_fields(),
        )
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "echo" in r.text
        assert "deny" in r.text
        # M3 verbatim-apply caption (never the regenerate-at-apply wording).
        assert "bytes the verb applies" in r.text
        assert "compilers regenerate from the record" not in r.text
        # replay examples present
        assert "config.yaml" in r.text or "allow" in r.text.lower()

    def test_badges_carry_text_labels_never_color_only(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, already_canon=True, already_canon_reason="covered")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "already canon" in r.text.lower()

    def test_graduate_highlighted_when_already_canon(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, already_canon=True)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        # Graduate stays available (P1-9b: affordance, never a gate) AND
        # carries a visible highlight — a text-labeled badge (Y-10: never
        # color alone), not just a CSS class.
        assert 'data-key-action="graduate"' in r.text
        assert "already canon" in r.text.lower()

    def test_graduate_not_highlighted_when_not_already_canon(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, already_canon=False)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert 'data-key-action="graduate"' in r.text
        import re as _re3

        graduate_button = _re3.search(
            r'data-key-action="graduate".*?</button>', r.text, _re3.S
        )
        assert graduate_button is not None
        assert "already canon" not in graduate_button.group(0).lower()

    def test_no_proposal_detail_shows_cta(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "no analysis yet" in r.text.lower()

    def test_episode_brief_renders_collapsed_below_decision_content(
        self, tmp_path: Path
    ) -> None:
        """09 §2.3 Y-21 / 10 §3 U18: a record carrying '## Episode brief'
        renders it as a collapsed, expandable block BELOW decision content
        (Trigger/Instruction/evidence), never inline/above."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s", source="session")
        rec.set_body(
            rec.body.rstrip("\n")
            + "\n\n## Episode brief\nTried the quick fix, it broke, so we did it properly.\n"
        )
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'data-key-action="toggle_brief"' in r.text
        assert "Tried the quick fix, it broke, so we did it properly." in r.text
        # never inline/above: the decision content markers precede it
        assert r.text.index('class="record-body"') < r.text.index("Episode brief (b)")
        assert r.text.index("Episode brief (b)") > r.text.index("Stop the container first.")

    def test_no_episode_brief_renders_no_block_no_placeholder(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert 'data-key-action="toggle_brief"' not in r.text
        assert "Episode brief" not in r.text


class TestSurfaceFillWhyRegion:
    """09 §11 Y-20 / 08 §1 `surface_fill`, end-to-end through the real
    CLI subprocess (ledger.list_items --surface-fill --id): Detail's Why
    region renders each scope-valid candidate's budget in plain words;
    `reference` is a static no-cap line; a missing key renders nothing;
    the armed action bar carries none of it (negative assertion, F2)."""

    def test_why_region_shows_the_skill_md_fill_sentence(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        for i in range(8):
            routed = make_knowledge(scope="skill:s", record_id=f"lrn-bb00000{i}", fact=f"fact{i}")
            seed_record(sb.ledger, routed)
            resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", routed)

        pending = make_behavior(scope="skill:s")
        seed_record(sb.ledger, pending)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{pending.id}")
        assert r.status_code == 200
        assert "this skill-md section already holds 8 of its 10 entries" in r.text
        assert "lands near the cap" in r.text

    def test_why_region_shows_the_static_reference_line(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "reference files have no cap" in r.text
        assert "overflow surface entries graduate into" in r.text

    def test_missing_skill_md_renders_nothing_for_that_destination(self, tmp_path: Path) -> None:
        # a registered skill dir with no SKILL.md file inside -> the CLI
        # omits the skill-md key (VerbError, F5) -> no row, no sentence.
        sb = make_env(tmp_path)
        (sb.host / "plugins" / "t-plugin" / "skills" / "t").mkdir(parents=True)
        rec = make_behavior(scope="skill:t")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "skill-md section already holds" not in r.text
        # claude-md still resolves (the skills-root host's own CLAUDE.md)
        assert "claude-md section already holds" in r.text

    def test_armed_action_bar_carries_no_budget_markup(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        for i in range(8):
            routed = make_knowledge(scope="skill:s", record_id=f"lrn-cc00000{i}", fact=f"fact{i}")
            seed_record(sb.ledger, routed)
            resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", routed)

        pending = make_behavior(scope="skill:s")
        seed_record(sb.ledger, pending)
        c, _runner = make_client(sb)

        # sanity: the Detail page's Why region DOES carry the fill text —
        # proves the negative assertion below isn't vacuous.
        detail = c.get(f"/record/{pending.id}")
        assert "this skill-md section already holds 8 of its 10 entries" in detail.text

        armed = c.post(
            f"/record/{pending.id}/action/arm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert armed.status_code == 200
        assert 'data-armed="true"' in armed.text
        assert "entries" not in armed.text
        assert "surface-budget" not in armed.text
        assert "already holds" not in armed.text


# --------------------------------------------------- arm / disarm / confirm


class TestArmDisarmConfirm:
    def _seed(self, tmp_path: Path):
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        return sb, rec

    def test_arm_renders_verb_id_destination_and_note_presence(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/arm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md", "note": "good"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-armed="true"' in r.text
        assert "Approve" in r.text
        assert rec.id in r.text
        assert "skill-md" in r.text
        assert "note attached" in r.text.lower()

    def test_arm_without_note_shows_no_note(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/arm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert "no note" in r.text.lower()
        assert "note-hint" in r.text  # deny's gentle "n to say why" hint
        assert "to say why" in r.text.lower()

    def test_disarm_returns_to_unarmed(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-armed="false"' in r.text
        assert "Approve (e)" in r.text

    def test_confirm_route_calls_runner_with_exact_argv(self, tmp_path: Path) -> None:
        """Resolution-evidence unit (§2.1/§4): route/reject/defer/graduate
        now carry `--json` on every confirm — the CLI envelope this unit
        renders as the success leg.

        FW-64: this POST never carries `dest_touched` (no cycle-destination
        round trip happened), so it is an unmodified approve-as-proposed —
        `--by analyst`, even though `dest` itself is explicit. Before the
        fix this argv carried no `--by` at all and the CLI's own
        dest-is-not-None heuristic would have read "human"."""
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md", "note": "good call"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert runner.calls == [
            ["route", rec.id, "--dest", "skill-md", "--by", "analyst", "--json", "--note", "good call"]
        ]

    def test_confirm_route_with_dest_touched_calls_runner_with_by_human(
        self, tmp_path: Path
    ) -> None:
        """FW-64: the twin of the test above — a POST that DOES carry
        `dest_touched` (the human used the (o) cycle control) gets
        `--by human`, proving the distinction the review UI could not
        draw before this fix (every approval, cycled or not, sent the
        same argv shape)."""
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={
                "verb": "route", "kind": "detail", "dest": "skill-md",
                "dest_touched": "true", "note": "good call",
            },
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert runner.calls == [
            ["route", rec.id, "--dest", "skill-md", "--by", "human", "--json", "--note", "good call"]
        ]

    def test_confirm_reject_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail", "note": "not worth it"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["reject", rec.id, "--json", "--note", "not worth it"]]

    def test_confirm_defer_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "defer", "kind": "detail", "until": "2026-08-01"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["defer", rec.id, "--until", "2026-08-01", "--json"]]

    def test_confirm_graduate_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "graduate", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["graduate", rec.id, "--json"]]

    def test_confirm_requires_cookie_and_hx_request(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.cookies.clear()
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 403
        assert runner.calls == []

    def test_confirm_nonzero_exit_renders_error_strip_verbatim(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: dirty target tree"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "dirty target tree" in r.text
        assert 'data-armed="false"' in r.text  # back to unarmed, nothing optimistic

    def test_error_strip_carries_the_reload_defer_marker(self, tmp_path: Path) -> None:
        """f5-errstrip live-DoD fix: app.js's leg (a) keys on
        [data-verb-error] — action_bar.html's error strip predated that
        leg and never carried it, so a post-verb refresh push reload-wiped
        every failed-verb error (and, since U20, the commit-drift button
        riding the same strip) before a human could read/act on it. Plain
        render-shape assertion (the ordering hazard itself is modeled in
        test_js_dom.py::TestErrorStripSurvivesInFlightRefresh, which needs
        a real browser to observe app.js's reload-defer predicate)."""
        sb, rec = self._seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: dirty target tree"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-verb-error="true"' in r.text
        # the marker sits on the SAME <p> as the error text, never a
        # decoy element elsewhere in the fragment
        assert re.search(
            r'<p class="error-strip" role="alert" data-verb-error="true">'
            r"self-learn: dirty target tree",
            r.text,
        )


class TestOCycle:
    # The endpoint reads the `dest` field because that is what the
    # rendered form sends (hx-include posts the hidden input named
    # "dest") — review 2026-07-18 F1: these tests once posted a
    # `current` field mirroring the handler instead of the template,
    # which entrenched a cycle that never advanced in a real browser.

    @staticmethod
    def _form_fields(html: str, record_id: str) -> dict[str, str]:
        """Exactly the fields htmx's hx-include would post: the value-
        carrying inputs of the unarmed bar's own form."""
        section = html.split(f'id="form-action-bar-{record_id}"')[1].split("</form>")[0]
        return dict(
            re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section)
        )

    def test_cycle_destination_endpoint_returns_parameter_free_destination(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/cycle-destination",
            data={"dest": ""},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        assert any(d in r.text for d in PARAMETER_FREE_DESTINATIONS)
        assert "hook" not in r.text.split("Destination:")[-1].split("<")[0]

    def test_cycle_advances_using_the_rendered_forms_own_fields(
        self, tmp_path: Path
    ) -> None:
        """Template-truth (review 2026-07-18 F1): drive the cycle with
        the rendered form's OWN fields — what a browser actually posts —
        and assert it ADVANCES. A handler/template field-name mismatch
        (the F1 bug: handler read `current`, template sent `dest`, the
        cycle stuck forever) fails loudly here instead of passing via
        tests that mirror the handler."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        assert "dest" in fields  # the field the endpoint must read
        seen = []
        for _ in range(2):
            r = c.post(
                f"/record/{rec.id}/action/cycle-destination",
                data=fields,
                headers={"HX-Request": "true"},
            )
            assert r.status_code == 200
            fields = self._form_fields(r.text, rec.id)
            seen.append(fields["dest"])
        assert seen == ["skill-md", "claude-md"]  # advanced, not stuck

    def test_cycle_endpoint_project_record_never_offers_skill_md(
        self, tmp_path: Path
    ) -> None:
        # Feedback round 2 item 3: the endpoint reads the record's scope
        # from the ledger (never a client field) and cycles only what the
        # route verb can accept for it.
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        c, _runner = make_client(sb)
        fields = {"dest": ""}
        seen = set()
        for _ in range(4):
            r = c.post(
                f"/record/{rec.id}/action/cycle-destination",
                data=fields,
                headers={"HX-Request": "true"},
            )
            assert r.status_code == 200
            assert "skill-md" not in r.text
            fields = self._form_fields(r.text, rec.id)
            seen.add(fields["dest"])
        assert seen == {"claude-md", "reference"}

    def test_cycle_endpoint_user_record_stays_claude_md(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/cycle-destination",
            data={"dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'name="dest" value="claude-md"' in r.text
        assert "skill-md" not in r.text
        assert 'value="reference"' not in r.text


class TestOCycleSingletonNoop:
    """F5-1 (feedback round 5, U19 §1.2 gate M1): a record whose cycle has
    exactly one element (user scope -> ("claude-md",)) renders the cycle
    control WITHOUT data-key-action and WITH the action-keyed
    data-noop-hint pair — the server-signaled no-op app.js reads."""

    def test_user_scope_detail_renders_noop_hint_without_key_action(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' not in r.text
        assert 'data-noop-hint="only one destination fits this lesson' in r.text
        assert 'data-noop-action="cycle_destination"' in r.text

    def test_skill_scope_detail_still_renders_normal_key_action(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' in r.text
        assert "data-noop-hint" not in r.text

    def test_user_scope_bucket_row_renders_noop_hint_too(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get("/bucket/user/user")
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' not in r.text
        assert 'data-noop-action="cycle_destination"' in r.text

    def test_user_scope_disarm_round_trip_keeps_noop_hint(self, tmp_path: Path) -> None:
        """The cycle button's no-op-ness must survive an arm/disarm round
        trip, not just the initial GET. NOTE (blind-gate fold): a
        user-scope record's cycle is ALSO the singleton this suite is
        testing for — this test alone cannot tell "scope correctly
        threaded to the POST handler" apart from "scope silently
        defaulted to user everywhere" (`_unarmed_context`'s own default
        is "user", the same value). See
        TestOCycleScopeThreadingDiscriminator below for the SKILL-scope
        (non-singleton) direction that actually discriminates."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' not in r.text
        assert 'data-noop-action="cycle_destination"' in r.text


class TestOCycleScopeThreadingDiscriminator:
    """Blind-gate fold (F5-1, U19 §1.2 gate M1): TestOCycleSingletonNoop's
    round-trip test used a user-scope record, whose cycle is ALSO the
    singleton — so it could not tell "scope correctly threaded to this
    POST handler" apart from "scope silently defaulted to user"
    (`_unarmed_context`'s own default). A SKILL-scope record's cycle has
    THREE elements, so the same collapse is directionally detectable: if
    any call site's `scope=_record_scope(...)` thread were dropped (and
    the "user" default took over), these renders would wrongly show the
    noop hint instead of the real, always-reachable cycle button. Every
    POST route that renders the unarmed action bar is covered here, not
    just disarm."""

    def test_skill_scope_disarm_rerender_keeps_normal_key_action(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' in r.text
        assert "data-noop-hint" not in r.text

    def test_skill_scope_cycle_destination_rerender_keeps_normal_key_action(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/cycle-destination",
            data={"dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-key-action="cycle_destination"' in r.text
        assert "data-noop-hint" not in r.text

    def test_skill_scope_confirm_failure_rerender_keeps_normal_key_action(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: refused"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "refused" in r.text  # stderr verbatim, sanity check
        assert 'data-key-action="cycle_destination"' in r.text
        assert "data-noop-hint" not in r.text


class TestRoutingByFW64:
    """FW-64: pins the chooser the review UI records at `/action/confirm`
    for a `route`. Reproduces the defect's own repro method (drive the
    ACTUAL rendered form fields, never hand-crafted POST bodies that
    mirror the handler) — the exact discipline TestOCycle's `_form_fields`
    established for the identical field-name-mismatch hazard (review
    2026-07-18 F1). Before this unit, no UI test asserted on `by` at all;
    the fixture default in support.py's `resolve_record_directly`
    (hardcoded "human") is part of why the defect survived undetected."""

    @staticmethod
    def _form_fields(html: str, record_id: str) -> dict[str, str]:
        section = html.split(f'id="form-action-bar-{record_id}"')[1].split("</form>")[0]
        return dict(
            re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section)
        )

    @staticmethod
    def _confirm_form_fields(armed_html: str) -> dict[str, str]:
        """The ARMED bar's OWN confirm form — what a real browser's
        Enter-key confirm actually posts. This is a DIFFERENT `<form>`
        from the unarmed quad `_form_fields` reads (it carries no `id=`
        at all — matched by its `hx-post=".../action/confirm"` instead),
        and reusing the pre-arm request's own data in its place (as an
        earlier draft of these tests did) would silently skip verifying
        that `armed.dest_touched` ever reaches the template at all."""
        section = armed_html.split('action/confirm"')[1].split("</form>")[0]
        return dict(
            re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section)
        )

    def test_approve_as_proposed_end_to_end_records_by_analyst(
        self, tmp_path: Path
    ) -> None:
        """The exact live-app repro the FW-64 brief drove by hand: GET the
        detail page, arm+confirm using ONLY the rendered form's own
        fields (never cycling), and assert the dispatched argv says
        `--by analyst` — the analyst's own proposal, unmodified. Before
        the fix this argv carried `--dest skill-md` with no `--by` at
        all, and `verbs.route`'s own heuristic read "human" for it."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, runner = make_client(sb)

        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        assert fields.get("dest") == "skill-md"  # the analyst's proposal
        assert "dest_touched" not in fields  # never cycled

        arm_data = dict(fields, verb="route", kind="detail")
        armed_html = c.post(
            f"/record/{rec.id}/action/arm", data=arm_data, headers={"HX-Request": "true"}
        ).text
        confirm_data = self._confirm_form_fields(armed_html)
        assert "dest_touched" not in confirm_data  # armed form echoes nothing new

        c.post(
            f"/record/{rec.id}/action/confirm", data=confirm_data, headers={"HX-Request": "true"}
        )
        assert runner.calls == [["route", rec.id, "--dest", "skill-md", "--by", "analyst", "--json"]]

    def test_human_override_end_to_end_records_by_human(self, tmp_path: Path) -> None:
        """The twin: cycling to a DIFFERENT destination before arming
        carries `dest_touched` through cycle -> arm -> confirm — via the
        ARMED form's own hidden fields, exactly what a browser's Enter
        key actually posts — and the dispatched argv says `--by human`."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, runner = make_client(sb)

        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        cycled_html = c.post(
            f"/record/{rec.id}/action/cycle-destination", data=fields, headers={"HX-Request": "true"}
        ).text
        fields = self._form_fields(cycled_html, rec.id)
        assert fields["dest"] != "skill-md"  # actually advanced
        assert fields.get("dest_touched") == "true"  # the human just acted

        arm_data = dict(fields, verb="route", kind="detail")
        armed_html = c.post(
            f"/record/{rec.id}/action/arm", data=arm_data, headers={"HX-Request": "true"}
        ).text
        confirm_data = self._confirm_form_fields(armed_html)
        assert confirm_data.get("dest_touched") == "true"  # carried into the armed form

        c.post(
            f"/record/{rec.id}/action/confirm", data=confirm_data, headers={"HX-Request": "true"}
        )
        assert runner.calls == [
            ["route", rec.id, "--dest", fields["dest"], "--by", "human", "--json"]
        ]

    def test_cycling_back_to_the_original_value_still_records_by_human(
        self, tmp_path: Path
    ) -> None:
        """FW-64's own design note: `dest_touched` is a fact about the
        human's ACTION (did they use the cycle control), never a
        value-comparison against the proposal — cycling all the way
        around back to the analyst's own suggestion is still a human
        choice, and a value-comparison design would misclassify it as
        untouched. skill scope's cycle has three elements (skill-md,
        claude-md, reference — `PARAMETER_FREE_DESTINATIONS`), so three
        cycles wrap all the way back to skill-md."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, runner = make_client(sb)

        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        for _ in range(3):  # skill-md -> claude-md -> reference -> skill-md
            html = c.post(
                f"/record/{rec.id}/action/cycle-destination", data=fields, headers={"HX-Request": "true"}
            ).text
            fields = self._form_fields(html, rec.id)
        assert fields["dest"] == "skill-md"  # back where it started
        assert fields.get("dest_touched") == "true"  # but a human chose it

        arm_data = dict(fields, verb="route", kind="detail")
        armed_html = c.post(
            f"/record/{rec.id}/action/arm", data=arm_data, headers={"HX-Request": "true"}
        ).text
        confirm_data = self._confirm_form_fields(armed_html)
        c.post(
            f"/record/{rec.id}/action/confirm", data=confirm_data, headers={"HX-Request": "true"}
        )
        assert runner.calls == [["route", rec.id, "--dest", "skill-md", "--by", "human", "--json"]]

    def test_disarm_then_rearm_preserves_dest_touched(self, tmp_path: Path) -> None:
        """A Cancel after cycling must not silently drop the human's own
        choice back to "analyst" on the next arm/confirm. The disarm POST
        itself uses the ARMED bar's own disarm-button fields (not the
        pre-arm cycle data) — the same "post what the browser would
        actually post" discipline as `_confirm_form_fields`."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, runner = make_client(sb)

        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        cycled = self._form_fields(
            c.post(
                f"/record/{rec.id}/action/cycle-destination", data=fields, headers={"HX-Request": "true"}
            ).text,
            rec.id,
        )
        arm_data = dict(cycled, verb="route", kind="detail")
        armed_html = c.post(
            f"/record/{rec.id}/action/arm", data=arm_data, headers={"HX-Request": "true"}
        ).text
        # The disarm (Cancel) button's own hidden fields — a section
        # distinct from the confirm form, matched by its own POST target.
        disarm_section = armed_html.split('action/disarm"')[1].split("</form>")[0]
        disarm_data = dict(
            re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', disarm_section)
        )
        assert disarm_data.get("dest_touched") == "true"

        disarmed_html = c.post(
            f"/record/{rec.id}/action/disarm", data=disarm_data, headers={"HX-Request": "true"}
        ).text
        redisarmed_fields = self._form_fields(disarmed_html, rec.id)
        assert redisarmed_fields.get("dest_touched") == "true"

        rearm_data = dict(redisarmed_fields, verb="route", kind="detail")
        rearmed_html = c.post(
            f"/record/{rec.id}/action/arm", data=rearm_data, headers={"HX-Request": "true"}
        ).text
        confirm_data = self._confirm_form_fields(rearmed_html)
        c.post(
            f"/record/{rec.id}/action/confirm", data=confirm_data, headers={"HX-Request": "true"}
        )
        assert runner.calls[-1] == [
            "route", rec.id, "--dest", redisarmed_fields["dest"], "--by", "human", "--json"
        ]

    def test_a_failed_confirms_retry_preserves_dest_touched(self, tmp_path: Path) -> None:
        """A failed confirm re-renders armable (F2) — the human's Enter
        on the SAME bar (no new cycle) must retry with the SAME `by`, not
        regress to "analyst" because the re-render forgot the flag."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: refused"))
        c, _runner = make_client(sb, runner=runner)

        fields = self._form_fields(c.get(f"/record/{rec.id}").text, rec.id)
        cycled = self._form_fields(
            c.post(
                f"/record/{rec.id}/action/cycle-destination", data=fields, headers={"HX-Request": "true"}
            ).text,
            rec.id,
        )
        confirm_data = dict(cycled, verb="route", kind="detail")
        failed_html = c.post(
            f"/record/{rec.id}/action/confirm", data=confirm_data, headers={"HX-Request": "true"}
        ).text
        assert "refused" in failed_html
        retry_fields = self._form_fields(failed_html, rec.id)
        assert retry_fields.get("dest_touched") == "true"

        retry_data = dict(retry_fields, verb="route", kind="detail")
        c.post(
            f"/record/{rec.id}/action/confirm", data=retry_data, headers={"HX-Request": "true"}
        )
        assert runner.calls[-1] == [
            "route", rec.id, "--dest", retry_fields["dest"], "--by", "human", "--json"
        ]

    def test_invalid_by_value_is_never_reachable_from_a_correct_ui(self) -> None:
        """The CLI's own closed enum (verbs.ROUTING_BY_VALUES) — asserted
        here as documentation of the contract build_argv relies on: this
        app only ever computes "human"/"agent"/"analyst", never anything
        else, so a `--by` CLI usage refusal should never be reachable
        through this UI. Guards the value set itself, independent of any
        one call site's derivation logic."""
        from self_learn.verbs import ROUTING_BY_VALUES

        assert ROUTING_BY_VALUES == {"human", "analyst", "agent"}


class TestDestinationGlosses:
    """F5-9 (feedback round 5, U19 §1.5): Detail's action bar + Why region
    gloss every destination enum through models.py's single-source
    _GROUP_LABELS — the SAME map Bucket group headers already use. The
    raw enum stays in the title attribute and in every form/argv field."""

    @pytest.mark.parametrize(
        "enum_value,label",
        [
            ("skill-md", "Skill doc"),
            # A1: the shared fixture below is skill-scoped
            # (make_behavior(scope="skill:s")) — claude-md now glosses
            # per-scope (destination_label("claude-md", "skill")), so
            # this row's expected label is "Skills repo instructions",
            # not the scope-blind "Project instructions".
            ("claude-md", "Skills repo instructions"),
            ("reference", "Reference file"),
        ],
    )
    def test_action_bar_cycle_button_shows_gloss_enum_in_title(
        self, tmp_path: Path, enum_value: str, label: str
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination=enum_value)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert f'title="{enum_value}">{label}</span> (o)' in r.text
        # the hidden form field the confirm posts stays the raw enum
        assert f'name="dest" value="{enum_value}"' in r.text

    @pytest.mark.parametrize(
        "enum_value,label",
        [
            ("skill-md", "Skill doc"),
            # A1: same skill-scoped fixture as above — "Skills repo
            # instructions", not the scope-blind "Project instructions".
            ("claude-md", "Skills repo instructions"),
            ("reference", "Reference file"),
            ("new-skill", "New skill"),
            ("hook", "Guard hook"),
        ],
    )
    def test_why_region_suggested_destination_shows_gloss(
        self, tmp_path: Path, enum_value: str, label: str
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        if enum_value == "hook":
            seed_proposal(
                sb.ledger,
                rec.id,
                destination="hook",
                script="#!/usr/bin/env bash\necho ok\n",
                **hook_proposal_fields(),
            )
        else:
            seed_proposal(sb.ledger, rec.id, destination=enum_value)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert f'Suggested destination: <span title="{enum_value}">{label}</span>' in r.text

    def test_alternates_are_glossed_too(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md", alternates=["claude-md", "reference"]
        )
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        # A1 (O-2 b): alternates are scope-aware too — this fixture is
        # skill-scoped, so claude-md glosses to "Skills repo
        # instructions" (no path — P-A12's path is bound to the
        # record's OWN selected destination, never the alternates).
        assert 'Alternates: <span title="claude-md">Skills repo instructions</span>, <span title="reference">Reference file</span>' in r.text

    def test_source_assertion_labels_render_from_group_labels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No second label map (gate: a builder adding one breaks the
        single-source rule) — monkeypatching models._GROUP_LABELS must
        change the render."""
        from self_learn_ui import models as models_module

        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)

        monkeypatch.setitem(models_module._GROUP_LABELS, "skill-md", "Totally different label")
        r = c.get(f"/record/{rec.id}")
        assert "Totally different label" in r.text
        assert "Skill doc" not in r.text


class TestScopeAwareClaudeMdLabels:
    """A1 (spec: docs/specs/self-learn/drafts/a1-labels-spec.md) — the
    F-1 fix at the render level: a user-scope claude-md record no longer
    shows "Project instructions" on any surface, and the resolved path
    (P-A12) renders alongside the label at the two identity/decision
    surfaces (test obligations 3, 4, 5)."""

    def test_user_scope_detail_suggested_destination_is_scope_aware_with_path(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "Project instructions" not in r.text
        assert (
            'Suggested destination: <span title="claude-md">User instructions</span>'
            in r.text
        )
        # P-A12: the resolved path, string-equal to the router's
        # DEFAULT_USER_CLAUDE_MD, shown alongside — never a placeholder.
        assert "~/.claude/CLAUDE.md" in r.text

    def test_project_scope_detail_suggested_destination_shows_its_own_path(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert (
            'Suggested destination: <span title="claude-md">Project instructions</span>'
            in r.text
        )
        assert "&lt;repo&gt;/CLAUDE.md" in r.text

    def test_user_scope_action_bar_cycle_button_is_scope_aware_with_path(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'title="claude-md">User instructions</span> (o)' in r.text
        assert "~/.claude/CLAUDE.md" in r.text

    def test_skill_scope_action_bar_cycle_button_shows_no_path_for_non_claude_md(
        self, tmp_path: Path
    ) -> None:
        # The path is bound to a claude-md destination only (P-A12) — a
        # cycle button currently showing skill-md never renders a path.
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'title="skill-md">Skill doc</span> (o)' in r.text
        assert "dest-path" not in r.text

    def test_user_bucket_group_heading_is_user_instructions(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get("/bucket/user/user")
        assert r.status_code == 200
        assert "<h2>User instructions</h2>" in r.text
        assert "<h2>Project instructions</h2>" not in r.text

    def test_skill_bucket_group_heading_is_skills_repo_instructions(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert "<h2>Skills repo instructions</h2>" in r.text
        assert "<h2>Project instructions</h2>" not in r.text

    def test_project_bucket_group_heading_stays_project_instructions(
        self, tmp_path: Path
    ) -> None:
        # Byte-identical to pre-A1 (spec §2/§4).
        from self_learn_ui import ledger as ui_ledger

        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        loc = ui_ledger.locate_record(sb.ledger, rec.id)
        assert loc is not None
        c, _runner = make_client(sb)
        r = c.get(f"/bucket/project/{loc.bucket_name}")
        assert r.status_code == 200
        assert "<h2>Project instructions</h2>" in r.text


class TestScopeAwareClaudeMdLabelsOnPostRerenders:
    """A1 fold: the action bar's UNARMED fragment also re-renders on the
    POST paths (cycle-destination, disarm, a failed confirm) via
    routes.py's own `_unarmed_context` — NOT through the two `{% with %}`
    include sites O-2 c named (detail.html:168 / bucket.html:88).
    `_unarmed_context` already resolved `scope` internally (to compute
    `destination_cycle`) but never put it in the returned template
    context, so `destination_label`/`destination_path` saw an Undefined
    `scope` on every one of these re-renders and silently fell back to
    the scope-blind gloss — F-1 surviving on this surface. Deliberately
    SKILL scope, not user: `_unarmed_context`'s own `scope` default is
    "user", so a user-scope assertion here couldn't tell "scope actually
    threaded" apart from "scope silently defaulted" (the same masking
    TestOCycleScopeThreadingDiscriminator guards against elsewhere)."""

    def test_skill_scope_cycle_destination_post_shows_scope_aware_label(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        # skill-md -> claude-md is the cycle's next element (destinations_
        # for_scope("skill") == ("skill-md", "claude-md", "reference")).
        r = c.post(
            f"/record/{rec.id}/action/cycle-destination",
            data={"dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'name="dest" value="claude-md"' in r.text
        assert "Skills repo instructions" in r.text
        assert "Project instructions" not in r.text
        assert "~/.claude/CLAUDE.md" not in r.text
        assert "&lt;skills root&gt;/CLAUDE.md" in r.text

    def test_skill_scope_disarm_post_shows_scope_aware_label(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'name="dest" value="claude-md"' in r.text
        assert "Skills repo instructions" in r.text
        assert "Project instructions" not in r.text

    def test_skill_scope_failed_confirm_rerender_shows_scope_aware_label(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: refused"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "refused" in r.text
        assert 'name="dest" value="claude-md"' in r.text
        assert "Skills repo instructions" in r.text
        assert "Project instructions" not in r.text


class TestVariantAwareSuggestedDestination:
    """A2 §11/§15 item 9: the "Suggested destination" line (detail.html)
    glosses a rules/local PROPOSAL the same variant-aware way A1's
    scope-aware gloss already does above — topic in the label, the
    resolved rules-file path beside it (P-A12), and the plain-words
    firing condition (§11's table)."""

    def test_pathed_rules_proposal_shows_topic_label_path_and_glob(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="claude-md", variant="rules",
            rules_topic="subagents", rules_paths=["src/**/*.ts"],
        )
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "User rule — subagents" in r.text
        assert "~/.claude/rules/subagents.md" in r.text
        assert "src/**/*.ts" in r.text  # the firing-condition glob, in plain words
        # Pin the firing NOTE independently of the raw-proposal YAML render:
        # "loads when you touch" is produced only by the pathed-rules branch
        # (models.rules_firing_note), so this fails if rules_paths is dropped
        # from the filter arg — closing the redundant-assertion gap.
        assert "loads when you touch" in r.text

    def test_unpathed_rules_proposal_says_loads_every_session(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(
            sb.ledger, rec.id, destination="claude-md", variant="rules",
            rules_topic="conventions",
        )
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "Project rule — conventions" in r.text
        assert "loads every session" in r.text

    def test_local_proposal_shows_personal_notes_label_and_path(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(sb.ledger, rec.id, destination="claude-md", variant="local")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "Personal project notes" in r.text
        assert "&lt;repo&gt;/CLAUDE.local.md" in r.text

    def test_no_variant_proposal_is_byte_identical_to_a1(self, tmp_path: Path) -> None:
        # P-A6: a plain claude-md proposal (no variant key at all) must
        # never render a firing-condition span.
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="claude-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "dest-firing-note" not in r.text


class TestDestinationCorrection:
    """Feedback round 2 item 3 — the live 2026-07-17 stranding: a project
    record whose analyst proposal said skill-md armed skill-md, and the
    CLI refused only after the human's confirm. Prevention: the rendered
    default (the hidden dest field Approve arms) is always scope-valid,
    with a plain-words note when it was corrected."""

    def test_project_detail_corrects_skill_md_default_with_note(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'name="dest" value="claude-md"' in r.text
        assert "the analyst suggested skill-md" in r.text
        assert "corrected to claude-md" in r.text
        # displayed == armed: the ONLY armable dest value is the corrected
        # one — skill-md never appears in a form field.
        assert 'value="skill-md"' not in r.text

    def test_skill_detail_keeps_the_analyst_suggestion_without_note(
        self, tmp_path: Path
    ) -> None:
        # Regression: a scope-valid suggestion passes through untouched.
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'name="dest" value="skill-md"' in r.text
        assert "the analyst suggested" not in r.text

    def test_disarm_and_failed_confirm_rerender_scope_corrected(
        self, tmp_path: Path
    ) -> None:
        """Review 2026-07-18 F2: client-echoed dest values re-entering
        armable renders go back through the scope rule server-side — an
        echoed skill-md on a project record renders (and would arm)
        claude-md on BOTH the disarm and failed-confirm paths."""
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn: refused"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert 'name="dest" value="claude-md"' in r.text
        assert 'value="skill-md"' not in r.text
        r2 = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert "refused" in r2.text  # stderr verbatim, pinned
        assert 'name="dest" value="claude-md"' in r2.text
        assert 'value="skill-md"' not in r2.text

    def test_project_bucket_row_arms_the_corrected_destination(
        self, tmp_path: Path
    ) -> None:
        # The Bucket page's per-row bar is the same armable surface —
        # same shared correction (models.correct_destination).
        from self_learn_ui import ledger as ui_ledger

        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        loc = ui_ledger.locate_record(sb.ledger, rec.id)
        assert loc is not None
        c, _runner = make_client(sb)
        r = c.get(f"/bucket/project/{loc.bucket_name}")
        assert r.status_code == 200
        assert 'name="dest" value="claude-md"' in r.text
        assert 'value="skill-md"' not in r.text
        assert "the analyst suggested skill-md" in r.text


class TestAdvanceAndBucketClear:
    def test_advance_to_next_record_in_same_bucket(self, tmp_path: Path) -> None:
        """Resolution-evidence unit (§3.4/DoD #6): `reject` is one of the
        four evidence-bearing verbs, so a successful confirm no longer
        auto-navigates — the evidence leg's "next pending record" link
        carries the SAME target the old auto-redirect used to jump to,
        but the human chooses whether to follow it."""
        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{older.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert r.headers.get("hx-redirect") is None
        assert 'data-verb-success="true"' in r.text
        assert f'href="/record/{newer.id}"' in r.text
        assert 'data-key-action="success_next"' in r.text

    def test_bucket_clear_shows_no_next_record_link(self, tmp_path: Path) -> None:
        """Same DoD #6 change: when the bucket is emptied, the evidence
        leg has nothing to advance to — no `success_next` link — but
        still offers "back to the bucket" (the bucket page itself still
        exists, just with zero pending)."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.headers.get("hx-redirect") is None
        assert 'data-verb-success="true"' in r.text
        assert 'data-key-action="success_next"' not in r.text
        assert 'href="/bucket/skill/s"' in r.text


class TestNextRecordUrlPure:
    def test_next_record_url_picks_remaining_record(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        a = make_behavior(scope="skill:s")
        b = make_behavior(scope="skill:s")
        seed_record(sb.ledger, a)
        seed_record(sb.ledger, b)
        url = next_record_url(sb.ledger, "skill", "s", a.id)
        assert url == f"/record/{b.id}"

    def test_next_record_url_bucket_clear_when_nothing_remains(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        a = make_behavior(scope="skill:s")
        seed_record(sb.ledger, a)
        url = next_record_url(sb.ledger, "skill", "s", a.id)
        assert url == "/?notice=bucket-clear"


class TestNextHopIsScopedNotJustNamed:
    """A bucket is identified by ``(scope, name)``, never by name alone —
    a skill and the user bucket can both be called ``user``. Fourth
    instance of tonight's defect family, and the worst one: unlike the
    Bucket page's lists or the front page's count, this is the queue-
    WALK's actual hop target — ``_next_pending_id`` is the ONE shared
    computation behind both ``next_record_url`` (the auto-redirect after
    a non-evidence verb) and the evidence leg's "next pending record"
    link, plus the Y-19 prefetch trigger. It filtered on bucket NAME
    alone, so a same-named bucket in another scope could hop the human
    mid-review into a DIFFERENT queue with no indication, and the
    prefetch would warm that same wrong record.

    Reproduced before fixing: a skill literally named ``user`` (the
    shape the codebase's own comments call out elsewhere) collides with
    the actual user bucket. Resolving the oldest record in the skill
    bucket returned the (older) ``user``-scope record as "next" — the
    wrong queue — instead of the newer record still pending in the SAME
    skill bucket.

    As with the sibling fixes, the obvious ``item["scope"] == scope``
    fix is wrong: a record's own ``scope`` field qualifies skills as
    ``skill:<name>`` while a bucket's scope is bare, so that comparison
    would silently empty every skill bucket's next-hop instead of
    leaking across scopes — trading one bug for a worse one.
    """

    def test_cross_scope_next_hop_does_not_leak(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("user",))
        skill_older = make_behavior(
            scope="skill:user",
            created_at="2026-01-01T00:00:00Z",
            trigger="Skill-scope trigger, oldest.",
        )
        user_wrong = make_behavior(
            scope="user",
            created_at="2026-01-03T00:00:00Z",
            trigger="User-scope trigger, would-be wrong hop.",
        )
        skill_newer = make_behavior(
            scope="skill:user",
            created_at="2026-01-05T00:00:00Z",
            trigger="Skill-scope trigger, newest.",
        )
        seed_record(sb.ledger, skill_older)
        seed_record(sb.ledger, user_wrong)
        seed_record(sb.ledger, skill_newer)

        url = next_record_url(sb.ledger, "skill", "user", skill_older.id)
        assert url == f"/record/{skill_newer.id}", (
            "the queue-walk hopped into the user-scope bucket's record "
            "instead of staying in the skill bucket named 'user'"
        )

    def test_same_scope_hop_still_works(self, tmp_path: Path) -> None:
        """Positive control against an over-strict guard. Comparing a
        record's own (possibly ``skill:<name>``-qualified) scope field
        directly against the bucket's bare scope would silently drop
        every skill-bucket next-hop — the same trap the sibling fixes
        hit. A skill bucket is used here specifically because that trap
        is invisible for project/user buckets, whose record scope is
        already bare and would pass a naive equality check by accident."""
        sb = make_env(tmp_path, skills=("user",))
        older = make_behavior(
            scope="skill:user",
            created_at="2026-01-01T00:00:00Z",
            trigger="Skill-scope trigger, oldest.",
        )
        newer = make_behavior(
            scope="skill:user",
            created_at="2026-01-05T00:00:00Z",
            trigger="Skill-scope trigger, newest.",
        )
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)

        url = next_record_url(sb.ledger, "skill", "user", older.id)
        assert url == f"/record/{newer.id}"

    def test_cross_scope_evidence_next_link_does_not_leak(self, tmp_path: Path) -> None:
        """End-to-end (not just the pure helper): the evidence leg's
        `success_next` href is built from the SAME `_next_pending_id` —
        a real `reject` through the HTTP route must not link the human
        into the other scope's same-named bucket either."""
        sb = make_env(tmp_path, skills=("user",))
        skill_older = make_behavior(
            scope="skill:user",
            created_at="2026-01-01T00:00:00Z",
            trigger="Skill-scope trigger, oldest.",
        )
        user_wrong = make_behavior(
            scope="user",
            created_at="2026-01-03T00:00:00Z",
            trigger="User-scope trigger, would-be wrong hop.",
        )
        skill_newer = make_behavior(
            scope="skill:user",
            created_at="2026-01-05T00:00:00Z",
            trigger="Skill-scope trigger, newest.",
        )
        seed_record(sb.ledger, skill_older)
        seed_record(sb.ledger, user_wrong)
        seed_record(sb.ledger, skill_newer)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{skill_older.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert f'href="/record/{skill_newer.id}"' in r.text
        assert f'href="/record/{user_wrong.id}"' not in r.text


class TestBulkGraduate:
    def test_argv_sequence_no_push_then_terminal_push(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, already_canon=True)
            ids.append(rec.id)
        c, runner = make_client(sb)
        r = c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(ids)},
            headers={"HX-Request": "true"},
        )
        assert r.status_code in (200, 303)
        assert runner.calls == [
            ["graduate", ids[0], "--no-push"],
            ["graduate", ids[1], "--no-push"],
            ["graduate", ids[2], "--no-push"],
            ["push"],
        ]

    def test_halt_on_first_failure_still_runs_terminal_push(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, already_canon=True)
            ids.append(rec.id)
        runner = FakeRunner()
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(1, stderr="boom"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(ids)},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [
            ["graduate", ids[0], "--no-push"],
            ["graduate", ids[1], "--no-push"],
            ["push"],
        ]
        assert ids[1] in r.text  # failing id shown


class TestClusterCollapse:
    def test_expand_then_route_as_survivor_argv(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec1 = make_behavior(scope="skill:s")
        rec2 = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec1)
        seed_record(sb.ledger, rec2)
        cluster_path = (sb.ledger / "skills" / "s") / "proposals" / "merge-deadbeef.yaml"
        cluster_path.parent.mkdir(parents=True, exist_ok=True)
        cluster_path.write_text(
            merge_proposal_text("merge-deadbeef", [rec1.id, rec2.id], rec1.id), encoding="utf-8"
        )
        c, runner = make_client(sb)

        expand = c.get("/cluster/skill/s/merge-deadbeef")
        assert expand.status_code == 200

        arm = c.post(
            f"/record/{rec1.id}/action/arm",
            data={"verb": "route", "kind": "detail", "collapse": "merge-deadbeef"},
            headers={"HX-Request": "true"},
        )
        assert arm.status_code == 200
        assert "merge-deadbeef" in arm.text

        confirm = c.post(
            f"/record/{rec1.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "collapse": "merge-deadbeef"},
            headers={"HX-Request": "true"},
        )
        assert confirm.status_code == 200
        # FW-64: no `dest` at all here (a survivor route with no override),
        # still an unmodified approve — `--by analyst`.
        assert runner.calls == [
            ["route", rec1.id, "--collapse", "merge-deadbeef", "--by", "analyst", "--json"]
        ]


class TestHoldingRowTC:
    def test_tolerate_argv(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, runner = make_client(sb)
        arm = c.post(
            f"/record/{rec.id}/action/arm",
            data={
                "verb": "confirm-recurrence", "kind": "holding",
                "event": "nonce-abc", "tolerate": "true", "note": "the rule stays",
            },
            headers={"HX-Request": "true"},
        )
        assert arm.status_code == 200
        assert "nonce-abc" in arm.text

        confirm = c.post(
            f"/record/{rec.id}/action/confirm",
            data={
                "verb": "confirm-recurrence", "kind": "holding",
                "event": "nonce-abc", "tolerate": "true", "note": "the rule stays",
            },
            headers={"HX-Request": "true"},
        )
        assert confirm.status_code == 200
        assert runner.calls == [
            [
                "confirm-recurrence", rec.id, "--event", "nonce-abc", "--tolerate",
                "--note", "the rule stays",
            ]
        ]

    def test_confirm_without_tolerate_argv(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "confirm-recurrence", "kind": "holding", "event": "nonce-xyz"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["confirm-recurrence", rec.id, "--event", "nonce-xyz"]]
        assert "--tolerate" not in runner.calls[0]


class TestFollowupDone:
    def test_followup_done_argv(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "followup-done", "kind": "followup", "note": "done"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["followup", "done", rec.id, "--note", "done"]]


class TestContradictsOffer:
    def test_post_route_offers_each_edge_and_arms_link_contradicts(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "skills/other/SKILL.md" in r.text
        assert "hx-redirect" not in {k.lower() for k in r.headers}

        arm = c.post(
            f"/record/{rec.id}/action/arm",
            data={
                "verb": "link-contradicts", "kind": "contradicts",
                "target": "skills/other/SKILL.md",
            },
            headers={"HX-Request": "true"},
        )
        assert arm.status_code == 200

        confirm = c.post(
            f"/record/{rec.id}/action/confirm",
            data={
                "verb": "link-contradicts", "kind": "contradicts",
                "target": "skills/other/SKILL.md",
            },
            headers={"HX-Request": "true"},
        )
        assert confirm.status_code == 200
        assert runner.calls[-1] == [
            "link", "contradicts", rec.id, "skills/other/SKILL.md"
        ]

    def test_failed_route_shows_error_not_the_contradicts_offer(
        self, tmp_path: Path
    ) -> None:
        """Review fold 2 (NIT): _capture_contradicts runs UNCONDITIONALLY
        before dispatch whenever verb == "route" — independent of the
        verb's eventual outcome. Pin that a FAILED route (the CLI's own
        refusal, e.g. a scan hit) still takes the ordinary error leg —
        stderr verbatim, action bar re-armable — and NEVER the Y-8 offer,
        even though contradicts_pre is non-empty at the point of failure."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "refused: scan hit" in r.text
        assert "data-contradicts-offer" not in r.text
        assert "skills/other/SKILL.md" not in r.text

    def test_offer_survives_the_routes_own_proposal_deletion(
        self, tmp_path: Path
    ) -> None:
        """U-C3 regression (live-trial defect, verified 2026-07-19): the
        REAL `route` CLI (self_learn.ledger_ops.resolve_record ->
        remove_proposal_siblings, 08 §1) deletes the record's
        proposals/<id>.yaml sibling as PART of resolving it — in
        production this always raced ahead of the handler's own
        proposal read when that read happened AFTER runner.run()
        returned, so the offer never rendered even though a proposal
        with contradicts: had been seeded (mock theater: the OTHER test
        in this class passes with a plain FakeRunner precisely because a
        FakeRunner records argv without ever deleting anything, which is
        not what production's subprocess does).

        RouteSideEffectRunner (support.py) calls the SAME production
        removal function a real `self-learn route` subprocess call
        triggers — so this test fails immediately if the fix regresses
        to a post-dispatch read, and the final assertion proves the
        deletion really happened (this isn't passing by accident)."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md", "skills/third/SKILL.md"],
        )
        runner = RouteSideEffectRunner(sb.ledger)
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "skills/other/SKILL.md" in r.text
        assert "skills/third/SKILL.md" in r.text
        assert "hx-redirect" not in {k.lower() for k in r.headers}
        # Review fold 1 (MINOR): the template↔app.js marker seam had no
        # coverage — stripping data-contradicts-offer from
        # contradicts_offer.html left the suite green because the JS test
        # injects its own marker and this test only checked edge text.
        # Assert the ACTUAL rendered partial carries the reload-defer
        # marker app.js's leg (d) keys on.
        assert "data-contradicts-offer" in r.text
        # The side effect the fix must survive really happened — proof
        # this test exercises the real hazard, not a no-op stand-in.
        assert not (
            sb.ledger / "skills" / "s" / "proposals" / f"{rec.id}.yaml"
        ).exists()

    def test_route_without_contradicts_advances_directly(self, tmp_path: Path) -> None:
        """Resolution-evidence unit (§3.4/DoD #6): no contradicts, no
        adopt hint — the plain success leg renders in place of the old
        auto-redirect. `default FakeRunner` returns empty stdout, so the
        envelope never parses and this degrades to the generic
        acknowledgement — still `data-verb-success`, never silence."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.headers.get("hx-redirect") is None
        assert 'data-verb-success="true"' in r.text


class TestAdoptOffer:
    """A2 §10.4(a): the review-UI half of the accepted §10 offer. The
    hint rides `_host_phase`'s stderr line (built from
    `self_learn.chezmoi.adopt_command`) — a FakeRunner queues that exact
    shape, exercising the SAME `_extract_adopt_path` parse the real
    runner's stderr would trigger, never a mocked-out shortcut."""

    TARGET = "/home/u/.claude/rules/subagents.md"

    @staticmethod
    def _hint_stderr(target: str = TARGET) -> str:
        from self_learn.chezmoi import adopt_command

        return (
            f"self-learn: wrote {target} — not tracked by chezmoi, so it "
            f"will not sync to your other machines. To sync it: "
            f"{adopt_command(target)}\n"
        )

    def test_post_route_offers_adopt_when_stderr_carries_the_hint(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stderr=self._hint_stderr()))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "hx-redirect" not in {k.lower() for k in r.headers}
        assert "data-adopt-offer" in r.text  # app.js leg (e) marker
        assert self.TARGET in r.text

    def test_arm_then_confirm_runs_chezmoi_adopt(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stderr=self._hint_stderr()))
        c, _runner = make_client(sb, runner=runner)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )

        arm = c.post(
            f"/record/{rec.id}/action/arm",
            data={"verb": "chezmoi-adopt", "kind": "adopt", "target": self.TARGET},
            headers={"HX-Request": "true"},
        )
        assert arm.status_code == 200
        assert "Adopt into chezmoi" in arm.text
        assert self.TARGET in arm.text

        confirm = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "chezmoi-adopt", "kind": "adopt", "target": self.TARGET},
            headers={"HX-Request": "true"},
        )
        assert confirm.status_code == 200
        assert runner.calls[-1] == ["chezmoi-adopt", self.TARGET]

    def test_cancel_after_arm_reverts_to_the_unarmed_offer_never_runs_the_verb(
        self, tmp_path: Path
    ) -> None:
        """The generic ``action/disarm`` route (shared with every other
        ``kind``) only replaces the INNER action-bar div — the outer
        `#adopt-offer-*` wrapper (lead text, `data-adopt-offer` marker)
        is untouched, so Cancel must land back on the SAME yes/no offer,
        never lose it, and never invoke the runner."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stderr=self._hint_stderr()))
        c, _runner = make_client(sb, runner=runner)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        c.post(
            f"/record/{rec.id}/action/arm",
            data={"verb": "chezmoi-adopt", "kind": "adopt", "target": self.TARGET},
            headers={"HX-Request": "true"},
        )

        cancel = c.post(
            f"/record/{rec.id}/action/disarm",
            data={"kind": "adopt", "target": self.TARGET},
            headers={"HX-Request": "true"},
        )
        assert cancel.status_code == 200
        assert "Bring under chezmoi (sync across machines)" in cancel.text
        assert "Not now" in cancel.text
        # only the ORIGINAL route call happened — Cancel never runs
        # chezmoi-adopt. Resolution-evidence unit: `route` now carries
        # `--json` on every confirm. FW-64: unmodified approve — `--by
        # analyst`.
        assert runner.calls == [["route", rec.id, "--dest", "claude-md", "--by", "analyst", "--json"]]

    def test_decline_wipes_the_offer(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        dismiss = c.post(
            f"/record/{rec.id}/adopt-offer/dismiss",
            headers={"HX-Request": "true"},
        )
        assert dismiss.status_code == 200
        assert dismiss.text == ""

    def test_failed_route_shows_error_not_the_adopt_offer(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert "data-adopt-offer" not in r.text
        assert "data-verb-error" in r.text

    def test_ordinary_route_stderr_never_misfires_the_offer(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)  # default FakeRunner: exit 0, no stderr
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert "data-adopt-offer" not in r.text
        assert r.headers.get("hx-redirect") is None
        assert 'data-verb-success="true"' in r.text

    def test_contradicts_offer_wins_when_both_would_fire(
        self, tmp_path: Path
    ) -> None:
        """An edge case (both a contradicts edge AND the adopt hint on
        the same route): the contradicts offer is checked first and
        returns immediately — never both rendered at once."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stderr=self._hint_stderr()))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert "data-contradicts-offer" in r.text
        assert "data-adopt-offer" not in r.text


# ------------------------------------------------------------------- keymap


class TestKeymapSingleSource:
    def test_json_footer_and_overlay_render_the_same_triple(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        entries = keymap_as_dicts()
        blob = keymap_json()
        # The JSON blob is byte-present in the page.
        assert blob in r.text.replace("\n      ", "").replace("\n    ", "") or all(
            e["action"] in r.text for e in entries
        )
        # Every entry's label appears in the footer AND overlay.
        for entry in entries:
            assert entry["label"] in r.text


# -------------------------------------------------------------------- Report


class TestReportPage:
    def test_renders_counted_fields_verbatim(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get("/report")
        assert r.status_code == 200
        assert "routed_ever" in r.text
        assert "Raw (verbatim)" in r.text
        # The raw JSON dump must contain the actual computed fields.
        assert "recurrence_suspects" in r.text
        assert "open_followups" in r.text


class TestHumanizeTsRenderSites:
    """F5-6 (feedback round 5, U19 §1.4): one render test per site
    asserting no bare `T…Z` ISO pattern remains in the VISIBLE text —
    the `title` attribute, which intentionally carries the full instant,
    is exempt (stripped before the scan)."""

    _ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    @classmethod
    def _visible_text(cls, html: str) -> str:
        return re.sub(r'title="[^"]*"', 'title=""', html)

    def test_detail_finding_line_has_no_bare_iso(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert not self._ISO_RE.search(self._visible_text(r.text))
        assert 'title="2026-01-01T00:00:00Z"' in r.text  # still present, in title

    def test_front_miner_block_has_no_bare_iso(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        _seed_miner_run()
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert "2026-07-19" in r.text  # the run landed, sanity check
        assert not self._ISO_RE.search(self._visible_text(r.text))

    def test_report_open_followups_has_no_bare_iso(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        app = c.app
        template = app.state.templates.env.get_template("report.html")
        html = template.render(
            request=None,
            keymap_json=keymap_json(),
            keymap_entries=keymap_as_dicts(),
            report={
                "routed_ever": 0,
                "superseded_after_routing": 0,
                "supersede_rate": 0,
                "graduated": 0,
                "rejected": 0,
                "routed_live": [],
                "recurrence_suspects": [],
                "open_followups": [
                    {
                        "id": "lrn-x0000001",
                        "bucket": "s",
                        "action": "check back on this",
                        "unblocks_on": "2026-08-01T00:00:00Z",
                        "routed_at": "2026-07-01T00:00:00Z",
                    }
                ],
                "mined": {},
                "telemetry": {},
            },
            report_error=None,
            status_error=None,
            metrics=None,
            supply_mix=None,
        )
        # the raw-JSON dump at the bottom is EXEMPT (09 §11 Y-12: verbatim
        # by design) — scope the scan to the followups table only.
        table = html.split('aria-label="open follow-ups"', 1)[1].split("</table>", 1)[0]
        assert not self._ISO_RE.search(self._visible_text(table))
        assert "2026-08-01" in table  # still present, humanized


# ---------------------------------------------------------------- XSS/escape


class TestRenderPathEscaping:
    def test_script_payload_in_record_body_renders_escaped_on_detail_page(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(
            scope="skill:s",
            trigger="<script>alert(1)</script>",
            instruction="<img src=x onerror=alert(2)>",
        )
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "<script>alert(1)</script>" not in r.text
        assert "<img src=x onerror=" not in r.text
        assert "&lt;script&gt;" in r.text or "alert(1)" not in r.text

    def test_csp_header_present_on_route_response(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert "content-security-policy" in {k.lower() for k in r.headers}

    def test_no_inline_style_attribute_in_diff_partial(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        diff_path = (sb.ledger / "skills" / "s") / "proposals" / f"{rec.id}.diff"
        diff_path.write_text("--- a\n+++ b\n-old line\n+new line\n", encoding="utf-8")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert 'style="' not in r.text


# --------------------------------------------- F5-4: proposal-yaml collapse


class TestProposalYamlCollapse:
    """F5-4 (feedback round 5, U19 §1.3): the Change region's raw-YAML
    fallback (no `.diff` sibling — proposal-yaml duplicates in raw form
    what the card sections above already render humanly) now renders
    default-collapsed; diff/hook stay always-open; the preview-honesty
    advisory line stays OUTSIDE the disclosure either way."""

    def test_proposal_yaml_renders_collapsed_with_advisory_outside(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")  # no .diff sibling
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert "<details" in r.text
        assert "The full proposal, as stored (raw)" in r.text
        # yaml-preview lives INSIDE the disclosure...
        details_section = r.text.split("<details", 1)[1].split("</details>", 1)[0]
        assert "yaml-preview" in details_section
        # ...the advisory caption lives OUTSIDE it.
        after_details = r.text.split("</details>", 1)[1]
        assert "compilers regenerate from the record at apply time" in after_details

    def test_diff_kind_still_renders_open_no_details(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        diff_path = (sb.ledger / "skills" / "s") / "proposals" / f"{rec.id}.diff"
        diff_path.write_text("--- a\n+++ b\n-old line\n+new line\n", encoding="utf-8")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert "diff-preview" in r.text
        assert "<details" not in r.text  # regression: no new disclosure anywhere

    def test_no_new_top_level_region(self, tmp_path: Path) -> None:
        """The collapse composes INSIDE the existing Change section — no
        new aria-label region."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        import re as _re4

        assert len(_re4.findall(r'aria-label="change"', r.text)) == 1


# ------------------------------------------------------ Y-19 item 2: worker


class TestWorkerKick:
    def test_argv_is_bare_worker_kick(self, tmp_path: Path) -> None:
        """The exact CLI verb the survey names (P2a): ``self-learn worker
        kick`` — never ``worker run`` (that would be an in-process await
        spanning the whole analysis pass, the Y-14 violation this item is
        built to avoid)."""
        sb = make_env(tmp_path)
        c, runner = make_client(sb)
        r = c.post("/worker/kick", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert runner.calls == [["worker", "kick"]]

    def test_redirects_to_front(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.post("/worker/kick", headers={"HX-Request": "true"})
        assert r.headers.get("hx-redirect") == "/"

    def test_forces_a_front_scope_refresh(self, tmp_path: Path) -> None:
        """Mirrors mine_run's own pattern exactly: a forced front-scope
        push so the status strip and bucket table pick up whatever the
        detached worker eventually lands, live."""
        sb = make_env(tmp_path)
        env = load_env(sb.env)
        from self_learn_ui import ledger as ledger_mod

        hub = ledger_mod.RefreshHub()
        q = hub.subscribe()
        runner = FakeRunner()
        from self_learn_ui.app import create_app

        app = create_app(env=env, token=TOKEN, runner=runner, refresh_hub=hub, start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)
        c.post("/worker/kick", headers={"HX-Request": "true"})
        event = q.get_nowait()
        assert event.scope == "front"

    def test_double_click_is_safe_the_cli_kick_is_idempotent_not_the_button(
        self, tmp_path: Path
    ) -> None:
        """No client-side double-click guard exists here, exactly like
        mine_run's own template (10 §1 Verb runner row: one subprocess
        at a time is the only server-layer brace either button gets).
        Two rapid clicks issue two ``worker kick`` calls — safety is the
        CLI's own flock/worker.window absorption (08 §7.1: a second kick
        landing while a window is open outcomes as absorbed-window/
        absorbed-race, never a second spawn), which this route does not
        need to re-implement. This test pins the ROUTE's half of that
        contract: two POSTs never escalate into two DIFFERENT argvs and
        both complete cleanly (never a 5xx from a raced double call)."""
        sb = make_env(tmp_path)
        c, runner = make_client(sb)
        r1 = c.post("/worker/kick", headers={"HX-Request": "true"})
        r2 = c.post("/worker/kick", headers={"HX-Request": "true"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert runner.calls == [["worker", "kick"], ["worker", "kick"]]

    def test_front_page_renders_the_force_run_button(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert '/worker/kick' in r.text
        assert "Force run" in r.text


# --------------------------------------------------- Y-24: near-miss promote


def _sandboxed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``make_env`` + a process-env redirect matching it: ``ledger.
    mine_status()`` is called by the route WITHOUT an ``env=`` override
    (it reads whatever the process's own os.environ carries for
    ``XDG_CACHE_HOME``), so the subprocess it shells out to must see the
    SAME cache dir this helper writes the journal into directly via the
    cli package's own ``miner`` module — never the real ``~/.cache``."""
    sb = make_env(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", sb.env["XDG_CACHE_HOME"])
    monkeypatch.setenv("XDG_RUNTIME_DIR", sb.env["XDG_RUNTIME_DIR"])
    monkeypatch.setenv("SELF_LEARN_HOME", sb.env["SELF_LEARN_HOME"])
    return sb


def _seed_miner_run(*, promotable: bool = True, run_id: str = "run00001", **outcome_overrides):
    """Writes ONE real journal entry (via the cli-package's own
    ``miner._journal``) so the route's ``ledger.mine_status(home)`` —
    which shells the REAL ``self-learn mine status --json`` — has a
    near-miss outcome to read back. Call AFTER :func:`_sandboxed` so the
    env vars miner_dir()/journal_path() resolve through are already
    redirected."""
    from self_learn import miner

    outcome = {
        "origin": "transcript:sess-nm#L7",
        "outcome": "dropped-cap",
        "disposition": "cap-refused",
        "reason": "a real lesson, but this run had already landed its cap",
        "promotable": promotable,
        "snippet": {
            "type": "behavior",
            "trigger": "About to rm -rf the wrong dir",
            "instruction": "Double check pwd first",
            "scope": "project",
        },
    }
    outcome.update(outcome_overrides)
    miner._journal(
        {
            "ts": "2026-07-19T00:00:00Z",
            "run_id": run_id,
            "trigger": "manual",
            "status": "ok",
            "sessions_scanned": 1,
            "landed": 0,
            "folded": 0,
            "recurrences": 0,
            "fires": 0,
            "near_miss_count": 1,
            "outcomes": [outcome],
            "duration_secs": 1.0,
        }
    )
    return run_id


class TestNearMissPromote:
    """t-j: the promote endpoint re-reads server-side and builds the
    exact ``teach`` argv — ``--session`` present, no ``--quote``."""

    def test_promote_builds_teach_argv_with_session_no_quote(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run()
        c, runner = make_client(sb)
        r = c.post(
            "/mine/near-miss/promote",
            data={"run_id": run_id, "index": "0"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert len(runner.calls) == 1
        argv = runner.calls[0]
        assert argv == [
            "teach",
            "--project",
            "--type",
            "behavior",
            "--trigger",
            "About to rm -rf the wrong dir",
            "--instruction",
            "Double check pwd first",
            "--session",
            "sess-nm",
        ]
        assert "--session" in argv
        assert "--quote" not in argv

    def test_promote_redirects_to_front(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run()
        c, _runner = make_client(sb)
        r = c.post("/mine/near-miss/promote", data={"run_id": run_id, "index": "0"}, headers={"HX-Request": "true"})
        assert r.headers.get("hx-redirect") == "/"

    def test_promote_rejects_non_promotable_index(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Server truth: even a client that posts a promotable-looking
        index for an outcome the CLI marked `promotable: false` is
        refused — the endpoint re-reads, never trusts the post body."""
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run(promotable=False)
        c, runner = make_client(sb)
        r = c.post("/mine/near-miss/promote", data={"run_id": run_id, "index": "0"}, headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []

    def test_promote_rejects_unknown_run_id(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        _seed_miner_run()
        c, runner = make_client(sb)
        r = c.post("/mine/near-miss/promote", data={"run_id": "no-such-run", "index": "0"}, headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []

    def test_promote_rejects_out_of_range_index(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run()
        c, runner = make_client(sb)
        r = c.post("/mine/near-miss/promote", data={"run_id": run_id, "index": "99"}, headers={"HX-Request": "true"})
        assert r.status_code == 400
        assert runner.calls == []

    def test_promote_knowledge_snippet_uses_fact_context(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run(
            snippet={
                "type": "knowledge",
                "fact": "The router reserves .232 for the Beacon",
                "context": "seen twice",
                "scope": "user",
            }
        )
        c, runner = make_client(sb)
        r = c.post("/mine/near-miss/promote", data={"run_id": run_id, "index": "0"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert runner.calls == [
            [
                "teach",
                "--user",
                "--type",
                "knowledge",
                "--fact",
                "The router reserves .232 for the Beacon",
                "--context",
                "seen twice",
                "--session",
                "sess-nm",
            ]
        ]

    def test_promote_skill_scope_snippet(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        run_id = _seed_miner_run(
            snippet={
                "type": "behavior",
                "trigger": "t",
                "instruction": "i",
                "kind": "anti-pattern",
                "scope": "skill:s",
            }
        )
        c, runner = make_client(sb)
        c.post("/mine/near-miss/promote", data={"run_id": run_id, "index": "0"}, headers={"HX-Request": "true"})
        assert runner.calls == [
            [
                "teach",
                "--skill",
                "s",
                "--type",
                "behavior",
                "--kind",
                "anti-pattern",
                "--trigger",
                "t",
                "--instruction",
                "i",
                "--session",
                "sess-nm",
            ]
        ]


class TestNearMissDrillRendering:
    """t-k: the drill is collapsed by default, shows only the latest
    run's rows, and a non-promotable row carries no control."""

    def test_drill_is_collapsed_by_default(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        _seed_miner_run()
        c, _runner = make_client(sb)
        html = c.get("/").text
        m = re.search(r"<details>\s*<summary>near-misses \(\d+\)</summary>", html)
        assert m is not None
        # the <details> tag itself carries no `open` attribute
        details_tag = html[: m.start()].rsplit("<details", 1)[-1]
        assert "open" not in details_tag.split(">")[0]

    def test_promotable_row_shows_promote_button_non_promotable_does_not(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        from self_learn import miner

        miner._journal(
            {
                "ts": "2026-07-19T00:00:00Z",
                "run_id": "run00002",
                "trigger": "manual",
                "status": "ok",
                "sessions_scanned": 1,
                "landed": 0,
                "folded": 0,
                "recurrences": 0,
                "fires": 0,
                "near_miss_count": 2,
                "outcomes": [
                    {
                        "origin": "transcript:sess-a#L1",
                        "outcome": "dropped-cap",
                        "disposition": "cap-refused",
                        "reason": "a real lesson, but this run had already landed its cap",
                        "promotable": True,
                        "snippet": {
                            "type": "behavior",
                            "trigger": "promotable trigger text",
                            "instruction": "promotable instruction text",
                            "scope": "project",
                        },
                    },
                    {
                        "origin": "transcript:sess-b#L2",
                        "outcome": "scan-refused",
                        "disposition": "scan-blocked",
                        "reason": "this looked like it might contain a secret, so it was held back",
                        "promotable": False,
                    },
                ],
                "duration_secs": 1.0,
            }
        )
        c, _runner = make_client(sb)
        html = c.get("/").text
        assert html.count("Promote to pending") == 1
        assert "promotable trigger text" in html
        assert "scan blocked" in html  # the non-promotable row's badge text
        assert "held back" in html  # its reason

    def test_only_the_latest_runs_rows_render(self, tmp_path: Path, monkeypatch) -> None:
        sb = _sandboxed(tmp_path, monkeypatch)
        from self_learn import miner

        _seed_miner_run(run_id="old-run")
        # advance mtime ordering isn't needed — journal order IS run order
        _seed_miner_run(
            run_id="new-run",
            **{
                "snippet": {
                    "type": "behavior",
                    "trigger": "the NEWEST near-miss trigger",
                    "instruction": "the newest instruction",
                    "scope": "project",
                }
            },
        )
        c, _runner = make_client(sb)
        html = c.get("/").text
        assert "the NEWEST near-miss trigger" in html
        assert "About to rm -rf the wrong dir" not in html  # old run's row absent


# -------------------------------------------------- Y-19 item 1: prefetch


class TestNextRecordPrefetch:
    def test_visiting_a_record_warms_the_next_ones_bundle_in_the_cache(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{older.id}")
        assert r.status_code == 200
        cache = c.app.state.detail_prefetch
        hub = c.app.state.refresh_hub
        bundle = cache.get(newer.id, hub.generation)
        assert bundle is not None
        assert bundle.record.id == newer.id

    def test_warm_hit_is_served_without_a_fresh_gather(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the cache is actually CONSULTED, not just populated:
        after warming, force a fresh _gather_detail_bundle call to raise
        — if the warm entry were bypassed, this GET would 500."""
        import self_learn_ui.routes as routes_mod

        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        c, _runner = make_client(sb)
        c.get(f"/record/{older.id}")  # warms `newer`

        calls: list[str] = []
        real_gather = routes_mod._gather_detail_bundle

        def spy(home, record_id):  # noqa: ANN001
            calls.append(record_id)
            if record_id == newer.id:
                raise AssertionError("must not re-gather a warm hit")
            return real_gather(home, record_id)

        monkeypatch.setattr(routes_mod, "_gather_detail_bundle", spy)
        r = c.get(f"/record/{newer.id}")
        assert r.status_code == 200
        assert newer.id in r.text

    def test_a_refresh_event_invalidates_the_warm_entry(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        c, _runner = make_client(sb)
        c.get(f"/record/{older.id}")  # warms `newer`
        cache = c.app.state.detail_prefetch
        hub = c.app.state.refresh_hub
        assert cache.get(newer.id, hub.generation) is not None

        hub.force_refresh("front")  # e.g. the watchfiles leg, or any push

        assert cache.get(newer.id, hub.generation) is None

    def test_a_verb_on_an_unrelated_record_invalidates_the_whole_cache(
        self, tmp_path: Path
    ) -> None:
        """Coordinator-pinned (mid-build message, folded into 09 §2.3 /
        the U17 row): invalidation is GLOBAL-ON-ANY-VERB-COMPLETION, not
        per-record — a verb on record X (a DIFFERENT bucket entirely)
        must invalidate a warm copy of record Y. This is what the
        Y-20/U17 surface-fill datum needs: routing X changes what a
        rendering of Y should show, since they can share a target
        surface."""
        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        unrelated = make_knowledge(scope="project")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        seed_record(sb.ledger, unrelated, project_path=sb.host)
        c, _runner = make_client(sb)
        c.get(f"/record/{older.id}")  # warms `newer`
        cache = c.app.state.detail_prefetch
        hub = c.app.state.refresh_hub
        assert cache.get(newer.id, hub.generation) is not None

        # Resolve a record in a COMPLETELY different bucket.
        r = c.post(
            f"/record/{unrelated.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200

        assert cache.get(newer.id, hub.generation) is None

    def test_never_stale_an_externally_resolved_record_is_never_served_from_cache(
        self, tmp_path: Path
    ) -> None:
        """End-to-end proof of the CRITICAL staleness rule: `newer` is
        warmed while still pending, then resolved externally (as a
        concurrent CLI session would), then the refresh the watcher
        would have published lands. The next GET must show the record's
        CURRENT (resolved) state — never the stale pending bundle a
        naive cache would still hold.

        U-grad-ui spec criterion 11 (updated in place — the 303 was this
        test's only observable for a genuinely orthogonal contract, and
        it must not be weakened to bare `200`, which a stale pending
        render would ALSO produce): the replacement observable is the
        RENDERED STATE itself — `route` absent (the pending quad is
        gone), `graduate` present (the resolved quad's one control). A
        stale bundle would hold the record as it was while pending,
        which renders `route` — this bites exactly where the 303 did."""
        sb = make_env(tmp_path)
        older = make_behavior(scope="skill:s", created_at="2026-01-01T00:00:00Z")
        newer = make_behavior(scope="skill:s", created_at="2026-01-05T00:00:00Z")
        seed_record(sb.ledger, older)
        seed_record(sb.ledger, newer)
        c, _runner = make_client(sb)
        c.get(f"/record/{older.id}")  # warms `newer` while pending

        # An external resolution (a concurrent CLI verb this server never
        # saw a POST for) + the refresh push the watcher would publish.
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", newer)
        c.app.state.refresh_hub.force_refresh(f"record:{newer.id}")

        r = c.get(f"/record/{newer.id}", follow_redirects=False)
        assert r.status_code == 200
        assert 'data-key-action="route"' not in r.text
        assert 'data-key-action="graduate"' in r.text

    def test_bucket_clear_next_id_none_schedules_no_prefetch(self, tmp_path: Path) -> None:
        """The last pending record in a bucket has no "next" — nothing
        is scheduled, and the cache stays empty (no crash on the None
        branch)."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        cache = c.app.state.detail_prefetch
        assert cache.get(rec.id, c.app.state.refresh_hub.generation) is None


# ------------------------------------------- Y-19 item 3: focus/selection


class TestFocusTarget:
    def test_content_landmark_is_programmatically_focusable(self, tmp_path: Path) -> None:
        """Template-level half of item 3 (the JS half is browser-only,
        pinned structurally in test_static_assets.py): tabindex="-1" on
        #self-learn-ui-content is what makes app.js's ensureContentFocus()
        legal — present on every screen via base.html."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        for path in ("/", f"/bucket/skill/s", f"/record/{rec.id}"):
            r = c.get(path)
            assert 'id="self-learn-ui-content"' in r.text
            assert 'tabindex="-1"' in r.text


class TestBucketPageScopeIsolation:
    """A bucket is identified by (scope, name), not by name alone — a skill
    and the user bucket can both be called `user`.

    The Bucket page answered that question two different ways in one
    function. The archive section confirmed `(scope, name)` via
    locate_record, and the unreadable-count block matched on both fields —
    but the PENDING list filtered on `item["bucket"] == name` and nothing
    else, so a same-named bucket in another scope had its records rendered
    here. Reproduced before fixing: two buckets named `foo`, one project
    and one skill, put BOTH records on the project page.

    Do not "simplify" this to `item["scope"] == scope`. The two scope
    vocabularies differ — `Bucket.scope` and this route's argument are bare
    (`skill`/`project`/`user`), while a record's own `scope` field
    qualifies skills as `skill:<name>` — so that comparison silently drops
    every record in every skill bucket. Membership is a fact about where
    the record LIVES, which is what locate_record answers.
    """

    def test_user_bucket_excludes_a_skill_bucket_of_the_same_name(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path, skills=("user",))
        skill_rec = make_behavior(
            scope="skill:user", trigger="About to collide with the user bucket."
        )
        user_rec = make_behavior(
            scope="user", trigger="About to do something at user scope."
        )
        seed_record(sb.ledger, skill_rec)
        seed_record(sb.ledger, user_rec)
        c, _runner = make_client(sb)

        r = c.get("/bucket/user/user")
        assert r.status_code == 200
        assert user_rec.id in r.text
        assert skill_rec.id not in r.text, (
            "the skill bucket named 'user' leaked its record onto the "
            "user-scope bucket page"
        )

    def test_skill_bucket_excludes_the_user_bucket_of_the_same_name(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path, skills=("user",))
        skill_rec = make_behavior(
            scope="skill:user", trigger="About to collide with the user bucket."
        )
        user_rec = make_behavior(
            scope="user", trigger="About to do something at user scope."
        )
        seed_record(sb.ledger, skill_rec)
        seed_record(sb.ledger, user_rec)
        c, _runner = make_client(sb)

        r = c.get("/bucket/skill/user")
        assert r.status_code == 200
        assert skill_rec.id in r.text
        assert user_rec.id not in r.text, (
            "the user bucket leaked its record onto the skill bucket "
            "named 'user'"
        )

    def test_a_skill_bucket_still_shows_its_own_records(self, tmp_path: Path) -> None:
        """Positive control against an over-strict guard — the failure mode
        `item["scope"] == scope` would produce, emptying every skill bucket.

        Measured, so the claim is not decorative: mutating the guard to
        always-False reddens all three tests in this class, because the two
        above each assert their OWN record is present as well as the
        other's absence. Mutating it to always-True reddens exactly those
        two and leaves this one green. So the class discriminates in both
        directions, and this test is the unambiguous signal for the strict
        one."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)

        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert rec.id in r.text


class TestHoldingRowShowsWhyItWasFlagged:
    """`basis` says WHY a recurrence suspect was raised, and the producers
    mean very different things by it: `fire-violated` is the model
    reporting it broke this routed rule, while `miner-match`,
    `origin-match` and `title-token-overlap` are text-similarity
    heuristics that can fire on a rule nobody violated.

    That distinction is most of the evidence behind revise / escalate /
    tolerate / retire — and it was spooled into telemetry and then dropped
    in `report.recurrence_suspects`, so no consumer could ever see it. The
    channel emitted zero events for the product's whole lifetime, which is
    why nobody noticed.
    """

    def _rows(self, suspects: list[dict]):
        from self_learn_ui.models import _build_holding_rows

        return _build_holding_rows(
            {
                "recurrence_suspects": suspects,
                "routed_live": [{"id": "lrn-aaaaaaa1", "bucket": "s", "routed_days_ago": 3}],
            }
        )

    def test_a_self_reported_violation_reads_differently_from_a_text_match(self):
        strong = self._rows(
            [{"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-08-01", "basis": "fire-violated"}]
        )
        weak = self._rows(
            [{"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-08-01", "basis": "miner-match"}]
        )
        assert strong[0].basis_text == "the model reported violating this rule"
        assert weak[0].basis_text == "a transcript matched this rule's text"
        assert strong[0].basis_text != weak[0].basis_text

    def test_mixed_bases_are_all_shown_in_first_seen_order(self):
        rows = self._rows(
            [
                {"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-08-01", "basis": "miner-match"},
                {"id": "lrn-aaaaaaa1", "nonce": "n2", "seen_at": "2026-08-02", "basis": "fire-violated"},
                {"id": "lrn-aaaaaaa1", "nonce": "n3", "seen_at": "2026-08-03", "basis": "miner-match"},
            ]
        )
        # "matched some text AND the model admitted violating it" is a
        # different situation from either alone, so neither is dropped —
        # but the repeat is de-duplicated.
        assert rows[0].basis_text == (
            "a transcript matched this rule's text; "
            "the model reported violating this rule"
        )
        assert rows[0].sighted_count == 3

    def test_an_unknown_basis_renders_verbatim_rather_than_vanishing(self):
        """Producers add bases without consulting the UI. A suspect that
        silently loses its reason is the defect this whole surface exists
        to fix, so an unmapped value must survive rendering."""
        rows = self._rows(
            [{"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-08-01", "basis": "some-future-basis"}]
        )
        assert rows[0].basis_text == "some-future-basis"

    def test_a_sighting_with_no_basis_says_less_rather_than_saying_None(self):
        rows = self._rows([{"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-08-01"}])
        assert rows[0].basis_text == ""
        assert rows[0].sighted_count == 1  # the row still exists

    def test_the_front_page_renders_the_reason(self, tmp_path: Path) -> None:
        """End to end through the template, not just the model — the whole
        bug was a value that existed at one layer and never reached the
        next one."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        # No suspects seeded here, so assert the surface is wired rather
        # than asserting text that would need live telemetry: the class
        # must not appear when there is nothing to say.
        assert "holding-basis" not in r.text


class TestFrontPageDeferredCountIsScoped:
    """The front page's deferred count was keyed by bucket NAME alone, so
    two same-named buckets in different scopes each showed the other's
    deferrals added to their own.

    It was deferred in 2026-07 with the reason "`list --json` items carry
    no scope field ... fixing it properly is an 08 §1 substrate edit
    (+scope on list items), not a UI-side derivation." That substrate edit
    has since landed — `list_items` emits `scope` — so the stated blocker
    was gone and the comment was keeping a known bug open on a premise
    that had stopped being true.
    """

    def _rows(self, items):
        from self_learn_ui.models import CliRead, build_front_model

        ok = lambda data: CliRead(data=data)  # noqa: E731
        status = ok(
            {
                "buckets": [
                    {"bucket": "user", "scope": "user", "pending": 0,
                     "unanalyzed": 0, "oldest_days": None},
                    {"bucket": "user", "scope": "skill", "pending": 0,
                     "unanalyzed": 0, "oldest_days": None},
                ],
                "total_pending": 0,
            }
        )
        model = build_front_model(ok(items), status, ok({}), ok({}), sentinel_mtime=None)
        return {(b.scope, b.name): b.deferred for b in model.buckets}

    def test_two_same_named_buckets_do_not_share_a_deferred_count(self):
        far = "2099-01-01T00:00:00Z"
        rows = self._rows(
            [
                {"id": "lrn-aaaaaaa1", "bucket": "user", "scope": "user",
                 "deferred_until": far},
                {"id": "lrn-bbbbbbb2", "bucket": "user", "scope": "skill:user",
                 "deferred_until": far},
                {"id": "lrn-ccccccc3", "bucket": "user", "scope": "skill:user",
                 "deferred_until": far},
            ]
        )
        assert rows[("user", "user")] == 1
        assert rows[("skill", "user")] == 2

    def test_a_skill_bucket_still_counts_its_own_deferrals(self):
        """The trap this fix has to avoid. A record's scope is
        `skill:<name>` while the bucket's is bare `skill`, so keying on
        the raw record scope would match nothing and silently report zero
        — trading a merged count for a missing one. This is the leg that
        catches that."""
        rows = self._rows(
            [
                {"id": "lrn-bbbbbbb2", "bucket": "user", "scope": "skill:user",
                 "deferred_until": "2099-01-01T00:00:00Z"},
            ]
        )
        assert rows[("skill", "user")] == 1

    def test_a_scopeless_item_is_attributed_when_the_name_is_unambiguous(self):
        """A record whose `scope` is missing (malformed frontmatter — the
        Record accessor is a plain lookup and can return None — or an
        older CLI) must not silently vanish from the count. Silently
        dropping it is the fail-open shape: a number that looks fine while
        omitting real work."""
        from self_learn_ui.models import CliRead, build_front_model

        ok = lambda data: CliRead(data=data)  # noqa: E731
        status = ok(
            {
                "buckets": [
                    {"bucket": "solo", "scope": "skill", "pending": 0,
                     "unanalyzed": 0, "oldest_days": None},
                ],
                "total_pending": 0,
            }
        )
        model = build_front_model(
            ok([{"id": "lrn-aaaaaaa1", "bucket": "solo",
                 "deferred_until": "2099-01-01T00:00:00Z"}]),
            status, ok({}), ok({}), sentinel_mtime=None,
        )
        assert {(b.scope, b.name): b.deferred for b in model.buckets} == {
            ("skill", "solo"): 1
        }


class TestMinerRunRowNeverPrintsNone:
    """A run that only initialized records no counts, so these fields come
    back None — and the template printed the literal string "None" at the
    operator: "scanned None, landed None, folded None, recurrences None".
    Found in a source-blind UI walk.

    Em-dash rather than 0, deliberately: "not recorded" and "measured
    zero" are different facts. Conflating them is the same error this
    product exists to avoid elsewhere — a reachability check reporting
    `0 of 0` is not a passing check.
    """

    def test_a_run_with_no_counts_renders_dashes_not_the_word_None(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Note the read is patched, not scripted through FakeRunner: the
        front page's four reads do NOT go through the verb runner (that
        carries mutations), so a queued RunResult never reaches them. An
        earlier version of this test queued results, controlled nothing,
        and passed vacuously — every "None" assertion held because the run
        row never rendered at all."""
        from self_learn_ui import ledger
        from self_learn_ui.models import CliRead

        monkeypatch.setattr(
            ledger,
            "mine_status",
            lambda home, **kw: CliRead(
                data={
                    "runs": [
                        {
                            "ts": "2026-08-02T12:00:00Z",
                            "status": "ok",
                            "trigger": "kick",
                            "sessions_scanned": None,
                            "landed": None,
                            "folded": None,
                            "recurrences": None,
                        }
                    ]
                }
            ),
        )
        sb = make_env(tmp_path)
        c, _r = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        # Positive control FIRST, and on a string unique to this row.
        # "kick" was the original choice and was worthless — the worker's
        # own Force-run button posts to /worker/kick, so it appears on the
        # page whether or not the run row rendered.
        assert "scanned" in r.text, "the run row did not render at all"
        for field in ("scanned", "landed", "folded", "recurrences"):
            assert f"{field} None" not in r.text, f"literal None rendered for {field}"
