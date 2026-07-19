"""U20 — the commit-drift UI leg (F5-5 guided commit-first,
f5-round-spec.md §2.2).

When a `route` confirm fails AND the stderr matches one of the two
pinned DIRTY-specific refusal clauses, the error strip gains ONE action
button ("Commit that repo's changes, then retry"), armed two-step,
composing inside the existing error-strip/action-bar machinery. The
drift refusal (gate M2) must NEVER grow the button.

Marker tests import the ACTUAL constants (self_learn.chezmoi.
CHEZMOI_DIRTY_MARKER / self_learn.verbs.GITOPS_DIRTY_MARKER) — never a
hand-copied substring (gate n12). The armed leg (dry-run file list) runs
against a REAL sandboxed dirty repo, same as every other read route
here (ledger._invoke_json shells the real `self-learn` console script);
the commit + auto-retry legs run against a FakeRunner so the argv
sequence is asserted exactly.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from self_learn.chezmoi import CHEZMOI_DIRTY_MARKER
from self_learn.verbs import GITOPS_DIRTY_MARKER

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.routes import COMMIT_DRIFT_MARKERS, _commit_drift_eligible
from self_learn_ui.runner import FakeRunner, RunResult

from support import make_behavior, make_env, seed_proposal, seed_record

TOKEN = "test-token"
RID = "lrn-0000c0de"


def make_client(sb, *, runner: FakeRunner | None = None, port: int = 7357):
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


def _seed(tmp_path: Path):
    sb = make_env(tmp_path)
    rec = make_behavior(scope="skill:s", record_id=RID)
    seed_record(sb.ledger, rec)
    seed_proposal(sb.ledger, rec.id, destination="skill-md")
    return sb, rec


def _seed_dirty(tmp_path: Path):
    sb, rec = _seed(tmp_path)
    sb.skill_md.write_text(
        sb.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
        encoding="utf-8",
    )
    return sb, rec


# --------------------------------------------------------- marker/eligibility


class TestMarkerImport:
    """gate n12: the marker match imports the SAME constants the CLI raise
    sites use — never a hand-copied substring."""

    def test_module_constants_are_the_real_pinned_markers(self) -> None:
        assert COMMIT_DRIFT_MARKERS == (GITOPS_DIRTY_MARKER, CHEZMOI_DIRTY_MARKER)

    def test_eligible_on_either_marker(self) -> None:
        assert _commit_drift_eligible("route", f"boom {GITOPS_DIRTY_MARKER} boom")
        assert _commit_drift_eligible("route", f"boom {CHEZMOI_DIRTY_MARKER} boom")

    def test_ineligible_on_drift_or_other_verb_or_empty(self) -> None:
        assert not _commit_drift_eligible(
            "route", "chezmoi reports pre-existing drift on X: fix drift / …"
        )
        assert not _commit_drift_eligible("reject", GITOPS_DIRTY_MARKER)
        assert not _commit_drift_eligible("route", None)
        assert not _commit_drift_eligible("route", "")


class TestButtonEligibility:
    def test_gitops_dirty_marker_shows_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(
                1,
                stderr=f"self-learn route: compile target X {GITOPS_DIRTY_MARKER} "
                "— commit/stash first, then re-run",
            )
        )
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "Commit that repo" in r.text
        assert f"/record/{rec.id}/action/commit-drift/arm" in r.text

    def test_chezmoi_dirty_marker_shows_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(
                1,
                stderr=f"self-learn route: {CHEZMOI_DIRTY_MARKER}: fix drift / "
                "commit dotfiles first, or route to project scope; the record "
                "stays pending",
            )
        )
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert "Commit that repo" in r.text

    def test_drift_refusal_shows_no_button(self, tmp_path: Path) -> None:
        """gate M2 — the load-bearing negative: drift never grows a button."""
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(
                1,
                stderr="self-learn route: chezmoi reports pre-existing drift on "
                "/x/CLAUDE.md: fix drift / commit dotfiles first, or route to "
                "project scope; the record stays pending",
            )
        )
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers={"HX-Request": "true"},
        )
        assert "commit-drift/arm" not in r.text
        assert "Commit that repo" not in r.text

    def test_generic_failure_shows_no_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn route: no proposal"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert "commit-drift/arm" not in r.text

    def test_non_route_verb_never_shows_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(
            RunResult(1, stderr=f"self-learn reject: {GITOPS_DIRTY_MARKER}")
        )
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert "commit-drift/arm" not in r.text


# ------------------------------------------------------------------- armed


class TestArmedFlow:
    def test_arm_shows_the_dry_run_file_list(self, tmp_path: Path) -> None:
        sb, rec = _seed_dirty(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/arm",
            data={"kind": "detail", "error_text": "boom", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "SKILL.md" in r.text
        assert 'data-armed="true"' in r.text
        assert "Confirm" in r.text

    def test_arm_race_fails_safe_to_plain_error(self, tmp_path: Path) -> None:
        """The repo went clean between the refusal and the tap — arm must
        NOT render a fabricated armed state."""
        sb, rec = _seed(tmp_path)  # clean repo — commit-drift dry-run refuses
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/arm",
            data={"kind": "detail", "error_text": "boom", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert 'data-armed="true"' not in r.text
        assert "nothing to commit" in r.text

    def test_disarm_returns_to_error_with_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, _runner = make_client(sb)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/disarm",
            data={"kind": "detail", "error_text": "the original stderr", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "the original stderr" in r.text
        assert "commit-drift/arm" in r.text
        assert 'data-armed="false"' in r.text


# -------------------------------------------------------------- commit+retry


class TestCommitAndRetry:
    def test_confirm_runs_commit_then_auto_retries_the_original_route(
        self, tmp_path: Path
    ) -> None:
        sb, rec = _seed_dirty(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0))  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert runner.calls == [
            ["host", "commit-drift", rec.id, "--dest", "skill-md"],
            ["route", rec.id, "--dest", "skill-md"],
        ]
        assert r.headers.get("hx-redirect")

    def test_commit_verb_failure_renders_stderr_verbatim_no_retry(
        self, tmp_path: Path
    ) -> None:
        sb, rec = _seed_dirty(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="self-learn host commit-drift: boom"))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "boom" in r.text
        assert runner.calls == [["host", "commit-drift", rec.id, "--dest", "skill-md"]]
        assert "commit-drift/arm" not in r.text

    def test_second_dirty_refusal_after_commit_renders_plainly_no_loop(
        self, tmp_path: Path
    ) -> None:
        sb, rec = _seed_dirty(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift succeeds
        runner.queue_result(
            RunResult(
                1,
                stderr=f"self-learn route: compile target X {GITOPS_DIRTY_MARKER} "
                "— commit/stash first, then re-run",
            )
        )  # the retry itself hits ANOTHER dirty refusal
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert len(runner.calls) == 2  # exactly one retry — never a loop
        assert "commit-drift/arm" not in r.text  # never re-offers the button
        assert GITOPS_DIRTY_MARKER in r.text  # rendered plainly
