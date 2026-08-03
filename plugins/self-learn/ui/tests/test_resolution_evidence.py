"""Resolution-evidence unit (docs/specs/self-learn/drafts/
resolution-evidence-spec.md) — UI-side (§2.2/§3.2/§3.3/§3.4/§3.6):
the success leg, its verb/outcome-state-shaped content, redirect
suppression at every site, offer composition, and the keymap uniqueness
invariant with the leg up.

FakeRunner-driven: every test queues a `RunResult` whose `stdout` is a
JSON envelope shaped exactly like `self_learn.cli`'s real `--json`
output (verified against plugins/self-learn/cli/tests/
test_resolution_evidence.py) — `RunResult.__post_init__` parses it into
`.evidence` automatically, the SAME path a real subprocess's stdout
takes through :class:`RealRunner`.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner, RunResult

from self_learn.ledger_ops import create_record, defer_record

from support import (
    commit_all,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    resolve_record_directly,
    seed_proposal,
    seed_record,
)

TOKEN = "test-token"
HX = {"HX-Request": "true"}


def make_client(sb, *, runner: FakeRunner | None = None) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


def envelope(
    *,
    action: str = "route",
    record_id: str = "lrn-aa000001",
    canon_path: str | None = None,
    host_commit_sha: str | None = None,
    ledger_paths: list[str] | None = None,
    commit_message: str = "self-learn: route lrn-aa000001 → skill-md",
    destination: str | None = None,
    variant: str | None = None,
    deferred_until: str | None = None,
    warnings: list[str] | None = None,
    created: bool | None = None,
    outcome_state: str = "landed",
    over_cap: str | None = None,
    pushed: str = "pushed",
    host_pushed: str | None = "pushed",
) -> dict:
    """The exact CLI envelope shape (§2.1) — mirrors
    plugins/self-learn/cli/src/self_learn/cli.py's `_verb_envelope`."""
    return {
        "action": action,
        "record_id": record_id,
        "canon_path": canon_path,
        "host_commit_sha": host_commit_sha,
        "ledger_paths": ledger_paths or [],
        "commit_message": commit_message,
        "destination": destination,
        "variant": variant,
        "deferred_until": deferred_until,
        "warnings": warnings or [],
        "created": created,
        "outcome_state": outcome_state,
        "over_cap": over_cap,
        "pushed": pushed,
        "host_pushed": host_pushed,
    }


def _seed(tmp_path: Path, *, scope: str = "skill:s"):
    sb = make_env(tmp_path)
    rec = make_behavior(scope=scope)
    project_path = sb.host if scope == "project" else None
    seed_record(sb.ledger, rec, project_path=project_path)
    return sb, rec


# ===================================================================== #
# §3.2/§3.3: verb-shaped, outcome-state-shaped content
# ===================================================================== #


class TestRouteEvidenceRendering:
    def test_landed_shows_the_canon_path_and_host_sha(self, tmp_path: Path) -> None:
        """Mutation guard (§8 row 3): "Make RunResult.evidence always
        None -> the path/sha CONTENT assertion (not merely 'a success
        leg rendered') [must fail]" — this test asserts the actual
        text, not just the marker's presence."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="deadbeefcafe",
            destination="skill-md",
            created=True,
            outcome_state="landed",
            commit_message=f"self-learn: route {rec.id} → skill-md",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert r.status_code == 200
        assert 'data-verb-success="true"' in r.text
        assert "/host/plugins/s-plugin/skills/s/SKILL.md" in r.text
        assert "deadbee" in r.text  # host_commit_sha[:7]
        assert "new section" in r.text  # created=True

    def test_landed_with_no_canon_path_never_prints_none(self, tmp_path: Path) -> None:
        """Code-gate finding 1 (BLOCKER): a `reference` route is
        reachable via the `o` cycler and — before the CLI-side
        `_canon_path` fallback landed — could report `canon_path=None`
        on a genuine `landed` success (`TargetSpec.target` is never set
        for `reference`). The CLI fix means this shape should no longer
        occur for `reference` specifically, but the render layer must
        not silently regress to interpolating `None` if any OTHER
        destination shape ever reports it too — mutation guard: revert
        the `{% if evidence.canon_path %}` guards on the `landed`/
        `no_op`/`wrote_uncommitted`/`drift` branches and this fails."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path=None,
            host_commit_sha="deadbeefcafe",
            destination="reference",
            created=True,
            outcome_state="landed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "reference"},
            headers=HX,
        )
        assert r.status_code == 200
        assert "<code>None</code>" not in r.text
        assert "the target" in r.text

    def test_landed_appended_says_appended_not_created(self, tmp_path: Path) -> None:
        """§2.1's "distinguish the two" instruction: bootstrapped=False
        must never read as "created"."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="cafebabe00",
            destination="skill-md",
            created=False,
            outcome_state="landed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "appended" in r.text
        assert "new section" not in r.text

    def test_no_op_shows_nothing_changed_and_the_existing_file(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha=None,
            destination="skill-md",
            outcome_state="no_op",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "nothing changed" in r.text
        assert "/host/plugins/s-plugin/skills/s/SKILL.md" in r.text

    def test_wrote_uncommitted_local_names_it_a_privacy_feature(self, tmp_path: Path) -> None:
        """§3.3 state 3: `claude-md:local` must render as state 3, never
        as `no_op` — and the privacy framing is explicit ("not
        committing it is the feature")."""
        sb, rec = _seed(tmp_path, scope="project")
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/CLAUDE.local.md",
            host_commit_sha=None,
            destination="claude-md",
            variant="local",
            outcome_state="wrote_uncommitted",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md:local"},
            headers=HX,
        )
        assert "not committed" in r.text
        assert "the feature" in r.text
        assert "chezmoi" not in r.text  # the OTHER (user-scope) branch's wording

    def test_wrote_uncommitted_user_scope_names_chezmoi(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path, scope="user")
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/home/u/.claude/CLAUDE.md",
            host_commit_sha=None,
            destination="claude-md",
            variant=None,
            outcome_state="wrote_uncommitted",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers=HX,
        )
        assert "not committed" in r.text
        assert "chezmoi" in r.text
        assert "the feature" not in r.text  # the OTHER (local) branch's wording

    def test_drift_names_the_target_but_never_as_written(self, tmp_path: Path) -> None:
        """DoD #4/§3.3 state 4: the path must not be presented as
        written, but must still be NAMED as the file to check."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha=None,
            destination="skill-md",
            outcome_state="drift",
            warnings=[
                "HOST PHASE FAILED after the ledger commit (broken markers) — "
                "canon is stale, never lost (H-2); run `self-learn recompile` "
                "to repair"
            ],
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "/host/plugins/s-plugin/skills/s/SKILL.md" in r.text
        assert "did NOT land" in r.text
        assert "self-learn recompile" in r.text  # the repair, verbatim from warnings
        # Never the landed branch's affirmative phrasing for the SAME path.
        assert "new section" not in r.text
        assert "appended" not in r.text

    def test_unknown_outcome_says_so_explicitly(self, tmp_path: Path) -> None:
        """§3.3's closing line: "Silence standing in for success is the
        defect being fixed; do not reintroduce it one level down." —
        `unknown` must render VISIBLE text, never nothing."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha=None,
            destination="skill-md",
            outcome_state="unknown",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "outcome unknown" in r.text


class TestOtherVerbsEvidenceRendering:
    def test_graduate_landed(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            action="graduate",
            record_id=rec.id,
            host_commit_sha="feedface12",
            outcome_state="landed",
            commit_message=f"self-learn: graduate {rec.id}",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "graduate", "kind": "detail"},
            headers=HX,
        )
        assert "Graduated" in r.text
        assert "feedfac" in r.text  # host_commit_sha[:7]

    def test_defer_shows_the_snooze_date_never_a_path(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            action="defer",
            record_id=rec.id,
            deferred_until="2026-09-01",
            outcome_state="landed",
            commit_message=f"self-learn: defer {rec.id} until 2026-09-01",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "defer", "kind": "detail"},
            headers=HX,
        )
        assert "2026-09-01" in r.text

    def test_reject_shows_moved_to_resolved(self, tmp_path: Path) -> None:
        """§3.2: reject's content is `ledger_paths` — the LEDGER path —
        never `staged`/`canon_path` confusion (§0's "single most
        important thing")."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            action="reject",
            record_id=rec.id,
            ledger_paths=[f"skills/s/resolved/{rec.id}.md"],
            outcome_state="landed",
            commit_message=f"self-learn: reject {rec.id}",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers=HX,
        )
        assert f"skills/s/resolved/{rec.id}.md" in r.text


# ===================================================================== #
# Code-gate finding 2 (MAJOR): "View what changed (v)" pointed at
# `/record/{id}` unconditionally, but `route`/`reject`/`graduate` all
# commit the ledger phase (record leaves pending/deferred) BEFORE the
# success leg ever renders — `/record/{id}` then 303-redirects to the
# bucket's resolved-elsewhere banner, not a diff. Only `defer` leaves the
# record genuinely viewable there. Two halves, deliberately NOT one test
# spanning both (same discipline as the drift-state split, §5): the FIRST
# pins the underlying redirect with a REAL status change — no FakeRunner,
# which is exactly why this was invisible before (FakeRunner never
# touches ledger state) — and the SECOND, which needs a real POST/render
# cycle to produce the success leg's markup at all, checks the button
# itself never targets that dead end.
# ===================================================================== #


class TestResolvedRecordRedirectsAwayFromItsOwnDetailPage:
    """U-grad-ui spec criterion 11: the class name and this docstring
    both described the redirect as the reason the `v` button is
    suppressed — that reason changed (§2.1 VIEWABLE deletes the
    redirect; §6.2's own comment fix, criterion 9, states the surviving
    one), so the prose changes with it. The `v`-button behaviour ITSELF
    does not change (§6.2) — `_evidence_ctx`'s `record_url` still omits
    a link for route/reject/graduate; see
    `TestViewLinkNeverTargetsARecordItWouldRedirectAway` below, untouched.
    Pinned directly with a REAL status change (`resolve_record_directly`/
    `defer_record` — no FakeRunner involved)."""

    def test_a_routed_record_no_longer_resolves_at_record_id(
        self, tmp_path: Path
    ) -> None:
        """New contract (was: 303 to the bucket's resolved-elsewhere
        banner): the record's OWN Detail page renders it directly, 200,
        carrying its Trigger text — the resolved view §2.1 adds."""
        sb, rec = _seed(tmp_path)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        # `_seed`'s make_behavior() default trigger (support.py) — the
        # record's own Trigger text, not merely `200` on an empty page.
        assert "About to edit .storage while HA is running." in r.text

    def test_a_deferred_record_still_resolves_at_record_id(
        self, tmp_path: Path
    ) -> None:
        """The one verb the button still points at — `defer_record`
        leaves the file in `pending/`, status "deferred", which
        `record_detail`'s viewable set (`("pending", "deferred")`)
        accepts."""
        sb, rec = _seed(tmp_path)
        defer_record(sb.ledger, rec.id, "2026-09-01")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        assert rec.id in r.text


class TestViewLinkNeverTargetsARecordItWouldRedirectAway:
    """The fix, at the render layer — needs a real POST/response cycle
    (FakeRunner-driven, since the marker/link only exist in the
    rendered success leg), unlike the class above."""

    def test_route_offers_no_view_link(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id, destination="skill-md", outcome_state="landed",
            host_commit_sha="a1b2c3d4e5",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert 'data-key-action="success_view"' not in r.text

    def test_reject_offers_no_view_link(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(action="reject", record_id=rec.id, outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers=HX,
        )
        assert 'data-key-action="success_view"' not in r.text

    def test_graduate_offers_no_view_link(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            action="graduate", record_id=rec.id, host_commit_sha="feedface12",
            outcome_state="landed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "graduate", "kind": "detail"},
            headers=HX,
        )
        assert 'data-key-action="success_view"' not in r.text

    def test_defer_still_offers_the_view_link(self, tmp_path: Path) -> None:
        """The one verb this leaves reachable — the negative-space
        assertions above would be trivially satisfiable by deleting the
        link everywhere; this proves that didn't happen."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            action="defer", record_id=rec.id, deferred_until="2026-09-01",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "defer", "kind": "detail"},
            headers=HX,
        )
        assert f'data-key-action="success_view">View the record (v)</a>' in r.text
        assert f'href="/record/{rec.id}"' in r.text


# ===================================================================== #
# Code-gate finding 6 (MINOR): `pushed`/`host_pushed` are derived and
# transported by the CLI/runner but were never rendered — "nowhere to
# push" (no_remote) and `--no-push` (not_requested) read identically to
# "pushed" silence. "failed" is excluded: a push failure moves the exit
# code and routes to the error leg before evidence is ever built
# (routes.py's `if not result.ok`), so the success leg never sees it.
# ===================================================================== #


class TestPushStateRendering:
    def test_no_remote_is_named_for_the_ledger_push(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="deadbeefcafe",
            destination="skill-md",
            outcome_state="landed",
            pushed="no_remote",
            host_pushed="pushed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "no remote is configured" in r.text
        assert "nothing was pushed" in r.text
        # host_pushed=="pushed" stays silent — only host's own exceptional
        # states get a line, not the routine case.
        assert "canon was not pushed" not in r.text
        assert "--no-push" not in r.text

    def test_no_push_flag_is_named_for_the_host_push(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="deadbeefcafe",
            destination="skill-md",
            outcome_state="landed",
            pushed="not_requested",
            host_pushed="not_requested",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert r.text.count("<code>--no-push</code>") == 2
        assert "not pushed" in r.text

    def test_the_routine_pushed_case_stays_silent(self, tmp_path: Path) -> None:
        """Mutation guard: proves the two tests above are actually
        conditional on the exceptional states, not always-on copy."""
        sb, rec = _seed(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
            host_commit_sha="deadbeefcafe",
            destination="skill-md",
            outcome_state="landed",
            pushed="pushed",
            host_pushed="pushed",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert "no remote is configured" not in r.text
        assert "--no-push" not in r.text
        assert "not pushed" not in r.text


class TestDegradedEvidence:
    def test_missing_envelope_still_shows_a_success_leg(self, tmp_path: Path) -> None:
        """§3.1: "A missing, truncated or unparseable envelope must not
        move the outcome. The action still succeeded; the surface
        degrades to generic success text and says the details could not
        be read." — never silence (the exact defect this unit fixes)."""
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()  # default RunResult(0) — empty stdout
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert 'data-verb-success="true"' in r.text
        assert "could not be read" in r.text


# ===================================================================== #
# DoD #6/§3.4/§8 row 11: redirect suppression at EVERY site,
# independently — "a single combined test would pass with three of them
# still broken." Counts deliberately omitted from this banner and from
# the class name: the spec said four, a fifth existed, and the stale
# number is what let W3-F1 hide.
# ===================================================================== #


def _routes_src() -> str:
    """Read `routes.py` through the module object, not a path guess."""
    from self_learn_ui import routes as _routes

    return Path(_routes.__file__).read_text()


def _count_calls(src: str, name: str) -> int:
    """Count real call sites of `name`, via AST — never a regex.

    A text match counts prose: adding `_evidence_ctx()` to a docstring —
    the most natural way to name a function in a comment — turned an
    earlier version of this guard RED, with a message telling the reader
    to bump the count, which is the reflex the guard exists to prevent.
    `routes.py:1732` already mentions the name in prose today."""
    return sum(
        1
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


class TestRedirectSuppressionEverySite:
    """Every site that builds evidence must suppress the redirect.

    NAMED WITHOUT A COUNT ON PURPOSE. This class was
    `TestRedirectSuppressionFourSites` and enumerated exactly the four
    sites the resolution-evidence spec listed — then `commit_drift_confirm`
    became a fifth, kept redirecting, and shipped the silent teleport that
    two source-blind UI walks found (W3-F1, 2026-07-26). The class had
    zero occurrences of `commit_drift` for that whole period. **The
    enumeration was the hole, not the assertions.**

    `test_every_evidence_call_site_is_covered` below is the guard: it
    derives the number of sites from the source instead of trusting this
    class to have kept up.
    """

    def test_evidence_call_site_count_is_pinned(self) -> None:
        """Pins how many places build evidence, so ADDING one stops a human.

        **What this does NOT cover, measured:** it is blind to the
        direction that actually caused W3-F1. A first version of this
        guard claimed to catch "the exact drift that hid W3-F1"; the code
        gate reproduced that defect — a new confirm route that dispatches
        `route` and sets `HX-Redirect` without ever calling
        `_evidence_ctx` — and this assertion stayed GREEN. It counts
        sites that DO call the function; the defect was a site that did
        NOT. Had it existed before that unit it would have read `== 2`
        and stayed green through the whole defect window.

        `test_redirect_site_count_is_pinned` below covers the omission
        direction. Keep both: this one catches "evidence was ripped out
        or added"; that one catches "a new route teleports silently"."""
        call_sites = _count_calls(_routes_src(), "_evidence_ctx")
        assert call_sites == 3, (
            f"routes.py has {call_sites} _evidence_ctx call sites; this guard "
            "knows about 3 (action_confirm, commit_drift_confirm, "
            "pane-proposal confirm). If you ADDED one, write its "
            "redirect-suppression test before touching this number."
        )

    def test_redirect_site_count_is_pinned(self) -> None:
        """Pins how many places still send `HX-Redirect`.

        This is the guard that would have caught W3-F1: before that unit
        `commit_drift_confirm` set an `HX-Redirect` on its SUCCESS leg,
        and nothing anywhere objected. A new route that resolves a record
        and teleports the user must add one of these, which turns this
        red and forces the question.

        If this fails because you added a redirect: confirm it is not on
        a leg that just resolved a record. That is the W3-F1 shape."""
        redirects = _routes_src().count('headers["HX-Redirect"]')
        assert redirects == 8, (
            f"routes.py assigns HX-Redirect in {redirects} places; this guard "
            "knows about 8. A NEW one on a leg that just resolved a record is "
            "W3-F1 — the user is teleported with no acknowledgement."
        )

    def test_site_1_plain_confirm_no_offer(self, tmp_path: Path) -> None:
        """action_confirm's plain HX-Redirect (no contradicts, no
        adopt)."""
        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers=HX,
        )
        assert r.headers.get("HX-Redirect") is None
        assert 'data-verb-success="true"' in r.text

    def test_site_2_contradicts_offer_still_shows_evidence(self, tmp_path: Path) -> None:
        """action_confirm's contradicts-offer branch."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(sb.ledger, rec.id, destination="skill-md", contradicts=["skills/other/SKILL.md"])
        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert r.headers.get("HX-Redirect") is None
        assert "data-contradicts-offer" in r.text
        assert 'data-verb-success="true"' in r.text  # composes WITH the offer

    def test_site_2b_multi_edge_offer_renders_evidence_exactly_once(
        self, tmp_path: Path
    ) -> None:
        """Code-gate finding 4 (MAJOR): a single-edge fixture cannot see
        `contradicts_offer.html` looping the whole `evidence` include
        once per edge — DoD #8's uniqueness invariant made false in a
        reachable (multi-edge) shape. Two edges, straight assertion on
        the raw response: `data-verb-success` and the success-leg nav
        keys must appear exactly once, and `data-key-action` overall
        must stay unique."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        seed_proposal(
            sb.ledger,
            rec.id,
            destination="skill-md",
            contradicts=["skills/other/SKILL.md", "skills/third/SKILL.md"],
        )
        env_dict = envelope(record_id=rec.id, destination="skill-md", outcome_state="landed")
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert r.text.count('data-verb-success="true"') == 1
        assert r.text.count('data-key-action="success_bucket"') == 1
        # Two edges DID render (the fix must not have deleted the offer
        # itself) — one "Link contradiction" button per target. (Each
        # target string legitimately appears 3x WITHIN its own edge —
        # the <p>, the hx-vals JSON, and the button label — so this
        # counts buttons, not substring occurrences of the path.)
        assert r.text.count('data-key-action="link_contradicts"') == 2
        assert "skills/other/SKILL.md" in r.text
        assert "skills/third/SKILL.md" in r.text
        # The uniqueness invariant this finding is actually about: the
        # keymap-bound success_* keys, which — unlike `link_contradicts`
        # (unbound, one legitimate button per edge by design) —
        # participate in app.js's GLOBAL first-match dispatch and so
        # must stay singular regardless of edge count.
        actions = re.findall(r'data-key-action="([^"]+)"', r.text)
        success_actions = [a for a in actions if a.startswith("success_")]
        dupes = sorted({a for a in success_actions if success_actions.count(a) > 1})
        assert not dupes, f"duplicate success_* data-key-action targets: {dupes}"

    def test_site_3_adopt_offer_still_shows_evidence(self, tmp_path: Path) -> None:
        """action_confirm's adopt-offer branch."""
        from self_learn.chezmoi import adopt_command

        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        target = "/home/u/.claude/rules/subagents.md"
        hint_stderr = (
            f"self-learn: wrote {target} — not tracked by chezmoi, so it "
            f"will not sync to your other machines. To sync it: "
            f"{adopt_command(target)}\n"
        )
        env_dict = envelope(
            record_id=rec.id, destination="claude-md", variant="rules",
            outcome_state="wrote_uncommitted",
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict), stderr=hint_stderr))
        c, _runner = make_client(sb, runner=runner)
        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md:rules:subagents"},
            headers=HX,
        )
        assert r.headers.get("HX-Redirect") is None
        assert "data-adopt-offer" in r.text
        assert 'data-verb-success="true"' in r.text

    def test_site_4_pane_proposal_confirm(self, tmp_path: Path) -> None:
        """proposal_confirm — "its own build_argv, runner.run, offer
        branches and HX-Redirect" (§3.4's own description of why this
        is a DISTINCT site from action_confirm)."""
        import self_learn_ui.pane as pane
        from self_learn_ui.proposals import VerbProposal

        sb, rec = _seed(tmp_path)
        env_dict = envelope(action="defer", record_id=rec.id, deferred_until="2026-09-01")
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        env = load_env(sb.env)
        app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
        manager = app.state.pane_manager
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)

        prop = VerbProposal(
            verb="defer", record_id=rec.id, bucket_scope="skill", bucket_name="s",
            session_key=pane.bucket_session_key("skill", "s"),
        )
        manager.proposal_slot.occupy(prop)
        armed = manager.proposal_slot.arm(rec.id)
        assert armed is not None
        r = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed.nonce},
            headers=HX,
        )
        assert r.headers.get("HX-Redirect") is None
        assert 'data-verb-success="true"' in r.text
        assert "2026-09-01" in r.text


# ===================================================================== #
# §3.6/DoD #8/§8 row 16: `data-key-action` uniqueness in the rendered
# document with the success leg up, on Detail and Bucket, alongside
# `host_add_bar.html`. `app.js:55` dispatches ONE global
# `document.querySelector('[data-key-action="…"]')` — first match,
# document order, no context filter (keymap.py pins this: every key
# unique across the whole table). The historical `c` defect was never a
# missing entry — three co-rendered partials all carried
# `data-key-action="confirm"` and document order silently resolved to
# the wrong one. "every printed key resolves to A handler" passes even
# with a duplicate present (it resolves — just to the wrong element), so
# these tests assert uniqueness in the POST-SWAP document instead.
#
# There is no browser here, so the swap is simulated: take a real page
# GET, then splice in the real fragment each `hx-swap="outerHTML"`
# button would have installed (host-add armed; the record's action-bar
# with its success leg up), by matching the target element's id and its
# balanced `<div>` nesting — not a flat string search, since
# `evidence.html`'s own `<div class="verb-success">` nests one level
# inside `action_bar.html`'s outer div. Splicing in the REAL swap
# target — rather than concatenating the whole page — matters: the
# unarmed quad the success leg suppresses would otherwise still be in
# the page text and could be miscounted as a live duplicate.
# ===================================================================== #

_KEY_ACTION_RE = re.compile(r'data-key-action="([^"]+)"')


def _key_actions(html: str) -> list[str]:
    return _KEY_ACTION_RE.findall(html)


def _swap_outer_html(page_html: str, dom_id: str, fragment_html: str) -> str:
    """Simulate htmx's ``hx-swap="outerHTML"``: replace the element
    with ``id="{dom_id}"`` in *page_html* with *fragment_html*, tracking
    `<div>` nesting depth to find the TRUE matching close tag (a flat
    regex cannot, since both `action_bar.html` and its nested
    `evidence.html` include are `<div>`s)."""
    start_marker = f'<div id="{dom_id}"'
    start = page_html.index(start_marker)
    pos = page_html.index(">", start) + 1
    depth = 1
    while depth > 0:
        next_open = page_html.find("<div", pos)
        next_close = page_html.find("</div>", pos)
        assert next_close != -1, f"unbalanced <div> looking for the close of #{dom_id}"
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + len("<div")
        else:
            depth -= 1
            pos = next_close + len("</div>")
    return page_html[:start] + fragment_html + page_html[pos:]


def _foreign_project(tmp_path: Path):
    """An unregistered project bucket (host_add_bar's live-fire case,
    mirrors test_routes.py's TestArmedHostAdd._foreign_sandbox) holding
    one pending record — the exact page shape where host-add's own
    `confirm`/`disarm` buttons and a record's success leg can be up at
    the same time."""
    sb = make_env(tmp_path)
    foreign = tmp_path / "foreign-repo"
    init_repo(foreign)
    (foreign / "CLAUDE.md").write_text("# foreign project\n", encoding="utf-8")
    commit_all(foreign, "foreign seed")
    rec = make_knowledge(
        scope="project", fact="Keymap-uniqueness fixture: the router stays foreign."
    )
    create_record(sb.ledger, rec, project_path=foreign)
    bucket_name = next((sb.ledger / "projects").iterdir()).name
    return sb, foreign, rec, bucket_name


class TestKeymapUniquenessWithSuccessLegUp:
    def test_detail_page(self, tmp_path: Path) -> None:
        """Uses `defer` (not `route`): finding 2's fix means `route`'s
        success leg carries no `success_view` link at all (the record
        is no longer viewable at `/record/{id}` once the ledger phase
        has moved it — see `_evidence_ctx`'s comment), so `defer` is
        the shape that actually exercises all THREE success_* keys
        alongside host-add's armed confirm/disarm — the strongest
        version of this uniqueness check."""
        sb, foreign, rec, name = _foreign_project(tmp_path)
        env_dict = envelope(
            action="defer",
            record_id=rec.id,
            deferred_until="2026-09-01",
        )
        runner = FakeRunner()
        c, _runner = make_client(sb, runner=runner)

        page = c.get(f"/record/{rec.id}", headers=HX).text
        assert f'id="action-bar-{rec.id}"' in page
        assert 'id="host-add-bar"' in page

        armed_host_add = c.post(
            f"/bucket/project/{name}/host-add/arm",
            data={"record_id": rec.id},
            headers=HX,
        ).text
        assert 'data-key-action="confirm"' in armed_host_add
        assert 'data-key-action="disarm"' in armed_host_add

        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        confirmed_bar = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "defer", "kind": "detail"},
            headers=HX,
        ).text
        assert 'data-verb-success="true"' in confirmed_bar

        merged = _swap_outer_html(page, "host-add-bar", armed_host_add)
        merged = _swap_outer_html(merged, f"action-bar-{rec.id}", confirmed_bar)

        actions = _key_actions(merged)
        assert actions
        dupes = sorted({a for a in actions if actions.count(a) > 1})
        assert not dupes, f"duplicate data-key-action targets: {dupes}"
        # host-add's ARMED confirm/disarm (action_bar.html:99/107 is the
        # `{% if armed %}` branch — host_add_bar.html's own armed state
        # reuses those two names, NOT the record's unarmed quad, which
        # carries route/reject/defer/graduate/cycle_destination instead)
        # must be the ONLY confirm/disarm on the page.
        assert actions.count("confirm") == 1
        assert actions.count("disarm") == 1
        # Code-gate finding 5 (MINOR): the two counts above are VACUOUS
        # against the actual guard — "confirm"/"disarm" never appear in
        # the record's own unarmed quad in the first place, so they stay
        # 1 whether or not `{% if not evidence %}` (action_bar.html:166)
        # does anything at all. THIS is the assertion that actually
        # exercises it: the quad's own keys, which WOULD be here if the
        # guard were removed (this record is post-confirm and unarmed —
        # exactly the state that renders the bare quad when no evidence
        # suppresses it).
        for quad_action in ("route", "reject", "defer", "graduate", "cycle_destination"):
            assert quad_action not in actions, (
                f"{quad_action!r} rendered alongside the success leg — "
                "the unarmed quad's {% if not evidence %} guard is not "
                "suppressing it"
            )
        # `success_next` is absent: this fixture's bucket holds only
        # this one record, so nothing remains pending once it resolves
        # (`_next_pending_id` -> None) — incidental to this fixture, not
        # to the verb. `success_bucket`/`success_view` are unconditional.
        assert "success_bucket" in actions
        assert "success_view" in actions

    def test_bucket_page(self, tmp_path: Path) -> None:
        sb, foreign, rec, name = _foreign_project(tmp_path)
        env_dict = envelope(
            record_id=rec.id,
            canon_path=str(foreign / "CLAUDE.md"),
            host_commit_sha=None,
            destination="claude-md",
            outcome_state="no_op",
        )
        runner = FakeRunner()
        c, _runner = make_client(sb, runner=runner)

        page = c.get(f"/bucket/project/{name}", headers=HX).text
        assert f'id="action-bar-{rec.id}"' in page
        assert 'id="host-add-bar"' in page

        armed_host_add = c.post(
            f"/bucket/project/{name}/host-add/arm",
            data={"record_id": rec.id},
            headers=HX,
        ).text
        assert 'data-key-action="confirm"' in armed_host_add

        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        confirmed_bar = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "claude-md"},
            headers=HX,
        ).text
        assert 'data-verb-success="true"' in confirmed_bar

        merged = _swap_outer_html(page, "host-add-bar", armed_host_add)
        merged = _swap_outer_html(merged, f"action-bar-{rec.id}", confirmed_bar)

        actions = _key_actions(merged)
        assert actions
        dupes = sorted({a for a in actions if actions.count(a) > 1})
        assert not dupes, f"duplicate data-key-action targets: {dupes}"
        assert actions.count("confirm") == 1
        assert actions.count("disarm") == 1
        # Code-gate finding 5 (MINOR): see test_detail_page's comment —
        # the confirm/disarm counts above are vacuous against the guard;
        # this is the assertion that actually exercises it.
        for quad_action in ("route", "reject", "defer", "graduate", "cycle_destination"):
            assert quad_action not in actions, (
                f"{quad_action!r} rendered alongside the success leg — "
                "the unarmed quad's {% if not evidence %} guard is not "
                "suppressing it"
            )
        assert "success_bucket" in actions
        # finding 2's fix, pinned here too: `route` never gets a
        # `success_view` link (the record is no longer viewable at
        # `/record/{id}` once the ledger phase has moved it).
        assert "success_view" not in actions

    def test_duplicate_data_key_action_is_actually_caught(self, tmp_path: Path) -> None:
        """Mutation guard (§8 row 16): if the merge/assertion machinery
        above can never fail, it is worthless (`lrn-ea833a5b`) — prove it
        catches a real duplicate, the exact historical `c` shape, without
        touching the merge helper itself."""
        actions = _key_actions(
            '<button data-key-action="confirm">A</button>'
            '<button data-key-action="confirm">B</button>'
        )
        dupes = sorted({a for a in actions if actions.count(a) > 1})
        assert dupes == ["confirm"]
