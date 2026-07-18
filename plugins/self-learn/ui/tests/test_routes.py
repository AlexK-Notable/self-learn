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

    def test_unknown_verb_raises(self) -> None:
        with pytest.raises(ValueError):
            build_argv("frobnicate", "lrn-aa000001")


class TestCycleDestination:
    def test_from_none_starts_at_first(self) -> None:
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        assert cycle_destination(None) == PARAMETER_FREE_DESTINATIONS[0]

    def test_cycles_through_the_whole_set_and_wraps(self) -> None:
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        seen = []
        current = None
        for _ in range(len(PARAMETER_FREE_DESTINATIONS) + 1):
            current = cycle_destination(current)
            seen.append(current)
        assert seen[: len(PARAMETER_FREE_DESTINATIONS)] == list(PARAMETER_FREE_DESTINATIONS)
        assert seen[-1] == PARAMETER_FREE_DESTINATIONS[0]  # wrapped

    def test_parameterized_destinations_are_never_produced(self) -> None:
        # "hook" / "new-skill" are never in the cycle set at all — this
        # IS the "skip" (there's nothing to skip past).
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        for start in ("hook", "new-skill:foo", None, "bogus"):
            result = cycle_destination(start)
            assert result in PARAMETER_FREE_DESTINATIONS


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
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/?notice=resolved-elsewhere")
        assert "resolved elsewhere" in r.text.lower()

    def test_notice_bucket_clear_renders_banner(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _runner = make_client(sb)
        r = c.get("/?notice=bucket-clear")
        assert "bucket clear" in r.text.lower()


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

    def test_resolved_elsewhere_redirects_to_bucket_with_banner(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 303
        assert "/bucket/skill/s" in r.headers["location"]
        assert "resolved-elsewhere" in r.headers["location"]
        r2 = c.get(r.headers["location"])
        assert "resolved elsewhere" in r2.text.lower()

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
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md", "note": "good call"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert runner.calls == [
            ["route", rec.id, "--dest", "skill-md", "--note", "good call"]
        ]

    def test_confirm_reject_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail", "note": "not worth it"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["reject", rec.id, "--note", "not worth it"]]

    def test_confirm_defer_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "defer", "kind": "detail", "until": "2026-08-01"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["defer", rec.id, "--until", "2026-08-01"]]

    def test_confirm_graduate_argv(self, tmp_path: Path) -> None:
        sb, rec = self._seed(tmp_path)
        c, runner = make_client(sb)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "graduate", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert runner.calls == [["graduate", rec.id]]

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


class TestOCycle:
    def test_cycle_destination_endpoint_returns_parameter_free_destination(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/cycle-destination",
            data={"current": ""},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        from self_learn_ui.models import PARAMETER_FREE_DESTINATIONS

        assert any(d in r.text for d in PARAMETER_FREE_DESTINATIONS)
        assert "hook" not in r.text.split("Destination:")[-1].split("<")[0]


class TestAdvanceAndBucketClear:
    def test_advance_to_next_record_in_same_bucket(self, tmp_path: Path) -> None:
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
        redirect = r.headers.get("hx-redirect")
        assert redirect == f"/record/{newer.id}"

    def test_bucket_clear_redirects_front_with_notice(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert r.headers.get("hx-redirect") == "/?notice=bucket-clear"


class TestNextRecordUrlPure:
    def test_next_record_url_picks_remaining_record(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        a = make_behavior(scope="skill:s")
        b = make_behavior(scope="skill:s")
        seed_record(sb.ledger, a)
        seed_record(sb.ledger, b)
        url = next_record_url(sb.ledger, "s", a.id)
        assert url == f"/record/{b.id}"

    def test_next_record_url_bucket_clear_when_nothing_remains(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        a = make_behavior(scope="skill:s")
        seed_record(sb.ledger, a)
        url = next_record_url(sb.ledger, "s", a.id)
        assert url == "/?notice=bucket-clear"


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
        assert runner.calls == [["route", rec1.id, "--collapse", "merge-deadbeef"]]


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

    def test_route_without_contradicts_advances_directly(self, tmp_path: Path) -> None:
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
        assert r.headers.get("hx-redirect") == "/?notice=bucket-clear"


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
