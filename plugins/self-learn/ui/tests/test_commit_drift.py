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

commit-drift-evidence-spec.md (§4): the commit-drift evidence tests
below live in this module rather than a new one — this IS the
commit-drift path — and import `envelope` from `test_resolution_evidence`
rather than re-deriving the envelope shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.testclient import TestClient

from self_learn.chezmoi import CHEZMOI_DIRTY_MARKER
from self_learn.verbs import GITOPS_DIRTY_MARKER

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.routes import COMMIT_DRIFT_MARKERS, _commit_drift_eligible
from self_learn_ui.runner import FakeRunner, RunResult

from support import make_behavior, make_env, seed_proposal, seed_record
from test_resolution_evidence import envelope

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


def _scrape_hidden_fields(html: str, form_marker: str) -> dict[str, str]:
    """Isolate ONE of the commit-drift arm/disarm/confirm forms (they
    coexist in the same rendered partial) by its distinguishing
    ``hx-post`` substring, then scrape that form's own hidden
    ``<input>`` fields. FW-64/UM8: this is what closes the gap a
    hand-crafted POST body cannot — it proves `_commit_drift_retry_ctx`'s
    `dest_touched` field actually reaches the rendered form a real
    browser would re-submit, not just the handler's own Form param."""
    section = html.split(form_marker)[1].split("</form>")[0]
    return dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section))


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
        """commit-drift-evidence-spec.md §3 acceptance item 1 (the W3-F1
        reproduction): the evidence leg renders on the retry's success —
        carrying the queued envelope's `canon_path` and 7-char
        `host_commit_sha` — in place of the pre-unit silent HX-Redirect
        teleport. §2.3: this test USED to assert the defect as the
        contract (`assert r.headers.get("hx-redirect")` and an argv
        without `--json`); both are superseded here, not worked around.
        The argv assertion matters on its own (§2.1): `FakeRunner.run`
        ignores argv entirely and pops the queued `RunResult` regardless
        of what was sent, so without this assertion the test would still
        pass on a build that never sends `--json` — the exact gap the
        blocker round caught."""
        sb, rec = _seed_dirty(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="deadbeefcafe",
            destination="skill-md",
            created=True,
            outcome_state="landed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        # FW-64: no `dest_touched` on this POST (the ORIGINAL failed
        # confirm never cycled the destination either), so the retry's
        # `by` reads "analyst", same as the original confirm would have
        # sent had it succeeded outright.
        assert runner.calls == [
            ["host", "commit-drift", rec.id, "--dest", "skill-md"],
            ["route", rec.id, "--dest", "skill-md", "--by", "analyst", "--json"],
        ]
        assert r.headers.get("hx-redirect") is None
        assert 'data-verb-success="true"' in r.text
        assert "/host/plugins/s-plugin/skills/s/SKILL.md" in r.text
        assert "deadbee" in r.text  # host_commit_sha[:7]

    def test_confirm_carries_dest_touched_into_the_retry_as_by_human(
        self, tmp_path: Path
    ) -> None:
        """FW-64: `dest_touched` rides the commit-drift retry fields
        exactly like `dest`/`collapse`/`note` already do (§2.2's own
        discipline, extended) — a route the human overrode via the (o)
        cycle control, that THEN hit a dirty-target refusal, must retry
        with `--by human`, never silently fall back to "analyst" because
        this leg forgot to carry the flag."""
        sb, rec = _seed_dirty(tmp_path)
        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md", "dest_touched": "true"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert runner.calls == [
            ["host", "commit-drift", rec.id, "--dest", "skill-md"],
            ["route", rec.id, "--dest", "skill-md", "--by", "human", "--json"],
        ]

    def test_dest_touched_survives_arm_then_confirm_via_rendered_forms(
        self, tmp_path: Path
    ) -> None:
        """FW-64/UM8: the test above pins `commit_drift_confirm`'s OWN
        `dest_touched` Form param, but `_commit_drift_retry_ctx` is a
        SEPARATE thing — it must also carry `dest_touched` into the
        rendered arm/confirm forms so a human who arms (or disarms) the
        guided commit before confirming still gets `--by human` on the
        eventual retry. Drive the REAL rendered arm form, then the REAL
        rendered confirm form it produces — a hand-crafted POST body
        standing in for either would hide a regression in the ctx dict
        itself (confirmed empirically: hardcoding
        `_commit_drift_retry_ctx`'s own `dest_touched` field to `False`
        leaves every other commit-drift test green)."""
        sb, rec = _seed_dirty(tmp_path)
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
            data={
                "verb": "route",
                "kind": "detail",
                "dest": "skill-md",
                "dest_touched": "true",
            },
            headers={"HX-Request": "true"},
        )
        assert "Commit that repo" in r.text
        arm_fields = _scrape_hidden_fields(r.text, 'commit-drift/arm"')
        assert arm_fields.get("dest_touched") == "true"

        r2 = c.post(
            f"/record/{rec.id}/action/commit-drift/arm",
            data=arm_fields,
            headers={"HX-Request": "true"},
        )
        assert 'data-armed="true"' in r2.text
        confirm_fields = _scrape_hidden_fields(r2.text, 'commit-drift/confirm"')
        assert confirm_fields.get("dest_touched") == "true"

        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))  # route retry
        r3 = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data=confirm_fields,
            headers={"HX-Request": "true"},
        )
        assert r3.status_code == 200
        assert runner.calls[-1] == [
            "route", rec.id, "--dest", "skill-md", "--by", "human", "--json"
        ]

    def test_evidence_composes_with_contradicts_offer(self, tmp_path: Path) -> None:
        """§3 acceptance item 2 — the offer COMPOSES with the evidence
        (§3.4's ruling, carried by this spec) rather than suppressing
        it. Mutation guard (§3.1): passing `evidence=None` to
        `_contradicts_offer_response` must fail this."""
        sb, rec = _seed_dirty(tmp_path)
        seed_proposal(
            sb.ledger,
            rec.id,
            destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "data-contradicts-offer" in r.text
        assert 'data-verb-success="true"' in r.text

    def test_evidence_composes_with_adopt_offer(self, tmp_path: Path) -> None:
        """§3 acceptance item 3 — likewise for the adopt offer. Mutation
        guard (§3.1): passing `evidence=None` to `_adopt_offer_response`
        must fail this."""
        from self_learn.chezmoi import adopt_command

        sb, rec = _seed_dirty(tmp_path)
        target = "/home/u/.claude/rules/subagents.md"
        hint_stderr = (
            f"self-learn: wrote {target} — not tracked by chezmoi, so it "
            f"will not sync to your other machines. To sync it: "
            f"{adopt_command(target)}\n"
        )
        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(
            RunResult(0, stdout=json.dumps(env_dict), stderr=hint_stderr)
        )  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "data-adopt-offer" in r.text
        assert 'data-verb-success="true"' in r.text

    def test_cleared_bucket_omits_next_pending_link(self, tmp_path: Path) -> None:
        """§3 acceptance item 4 — a cleared bucket omits the "next
        pending record" link rather than linking the front page under
        that label. Mutation guard (§3.1): building `next_url` with
        `next_record_url` instead of the raw next-pending id must fail
        this — that helper always returns SOME string (a bucket-clear
        front-page URL when nothing remains), which would render here
        under the misleading "Next pending record" label."""
        sb, rec = _seed_dirty(tmp_path)  # the only pending record in this bucket
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="cafed00d00",
            destination="skill-md",
            outcome_state="landed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0))  # host commit-drift
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))  # route retry
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/commit-drift/confirm",
            data={"kind": "detail", "dest": "skill-md"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        # POSITIVE CONTROL FIRST (lrn-ea833a5b). The two negative
        # assertions below are true of an empty response body, so on
        # their own they cannot tell "the link is correctly absent" from
        # "nothing rendered at all" — measured: this test stayed GREEN
        # both with the whole evidence surface deleted and with the
        # success leg returning `HTMLResponse("")`. These two assert the
        # leg rendered AND that its content came from the queued
        # envelope, so the absence below is an absence *within* a
        # rendered evidence leg.
        assert 'data-verb-success="true"' in r.text
        assert "cafed00" in r.text
        assert 'data-key-action="success_next"' not in r.text
        assert "/?notice=" not in r.text

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
        # commit-drift-evidence-spec.md §3.1: without this, "add evidence
        # to the retry-failure leg" survives — `_evidence_ctx(run_result=
        # retry)` with `retry.evidence is None` (non-zero exit) renders a
        # DEGRADED "route succeeded…" block above the error strip while
        # the two assertions above both stay true.
        assert "data-verb-success" not in r.text
