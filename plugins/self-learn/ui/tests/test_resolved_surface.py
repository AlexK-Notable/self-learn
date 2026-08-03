"""U-grad-ui (docs/specs/self-learn/drafts/u-grad-ui-resolved-surface-spec.md
r3): a resolved lesson must be reachable, and retirable, from the GUI.

This file covers the criteria (§3) that are NOT one of the five incumbent
tests the spec re-contracts in place (criterion 11 — those stay in their
own files: test_routes.py, test_proposals.py, test_degradation_walk.py,
test_resolution_evidence.py) and are NOT already covered, untouched, by
an existing test (criterion 10's both legs — `test_proposals.py::
test_bulk_graduate_sweeps_a_stale_proposal` for `:1253`,
`test_stale_arm_after_external_resolution_renders_gone` for `:2117`).

§3.0 fixture note: `resolve_record_directly` never writes
`superseded_by`, so it cannot mint a GRADUATED record on its own —
`_graduate_directly` below does the extra re-read + `set_superseded_by`
step the spec pins, on top of the shared helper (not inside it — it is
shared with the concurrent CLI wave and is deliberately not extended).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui import routes
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner, RunResult

from self_learn.ledger_ops import defer_record
from self_learn.records import Record

from support import make_behavior, make_env, resolve_record_directly, seed_record

TOKEN = "test-token"
HX = {"HX-Request": "true"}
TRIGGER = "About to edit .storage while HA is running."

STYLE_CSS_PATH = Path(__file__).resolve().parents[1] / "static" / "style.css"


def make_client(sb, *, runner: FakeRunner | None = None) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


def _bucket_dir(sb, scope: str = "skill", name: str = "s") -> Path:
    if scope == "user":
        return sb.ledger / "user"
    return sb.ledger / f"{scope}s" / name


def _graduate_directly(sb, bucket_dir: Path, rec: Record) -> None:
    """§3.0: mint a genuinely GRADUATED record (`superseded_by: canon`),
    which the shared `resolve_record_directly` helper cannot produce on
    its own — it never writes `superseded_by`, so a `superseded` record
    it mints alone is one replaced by a successor, not graduated into
    canon (`report.gather` counts the two differently, and criterion 7
    would be vacuous against a `None` record). Re-reads the file
    `resolve_record_directly` just wrote and finishes the mint in place
    — NOT an extension of the shared helper itself (it is shared with
    the concurrent CLI wave)."""
    resolve_record_directly(sb.ledger, bucket_dir, rec, status="superseded")
    path = bucket_dir / "resolved" / f"{rec.id}.md"
    graduated = Record.from_path(path)
    graduated.set_superseded_by("canon")
    graduated.write(path)


def _archive_section(html: str) -> str:
    """The Bucket page's B1 archive section only — scoping assertions to
    this substring is what makes a presence/absence check about the
    ARCHIVE specifically, not the whole page (a pending row also prints
    its own id elsewhere on the page)."""
    match = re.search(r'<details class="archive-section">.*?</details>', html, re.S)
    return match.group(0) if match else ""


# ===================================================================== #
# Criterion 1 — the link-walk (M18's discriminator)
# ===================================================================== #


class TestLinkWalkReachability:
    def test_link_walk_from_front_reaches_the_routed_record(self, tmp_path: Path) -> None:
        """No URL is hand-constructed after the first `GET "/"` — every
        hop is an href actually present in the previous response."""
        sb = make_env(tmp_path)
        pending = make_behavior(scope="skill:s")
        seed_record(sb.ledger, pending)
        routed = make_behavior(scope="skill:s")
        seed_record(sb.ledger, routed)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), routed)
        c, _runner = make_client(sb)

        front_html = c.get("/").text
        bucket_link = re.search(r'href="(/bucket/skill/s)"', front_html)
        assert bucket_link, "no bucket link found on the front page"

        bucket_html = c.get(bucket_link.group(1)).text
        archive = _archive_section(bucket_html)
        assert archive, "no archive section rendered on the bucket page"
        record_link = re.search(r'href="(/record/lrn-[0-9a-f]{8})"', archive)
        assert record_link, "no record link found inside the archive section"
        assert record_link.group(1) == f"/record/{routed.id}"

        # follow_redirects=False: a redirect (the deleted P1-9c banner
        # path — M1's own regression) must fail this assertion outright,
        # never be silently followed to a DIFFERENT (also-200) page.
        detail = c.get(record_link.group(1), follow_redirects=False)
        assert detail.status_code == 200


# ===================================================================== #
# Criterion 2 — the index lists INDEX-SET and nothing else
# ===================================================================== #


class TestIndexListsIndexSetOnly:
    def test_archive_contains_routed_and_excludes_pending_rejected_graduated(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)

        pending = make_behavior(scope="skill:s")
        seed_record(sb.ledger, pending)

        routed = make_behavior(scope="skill:s")
        seed_record(sb.ledger, routed)
        resolve_record_directly(sb.ledger, bucket_dir, routed)

        rejected = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rejected)
        resolve_record_directly(sb.ledger, bucket_dir, rejected, status="rejected")

        graduated = make_behavior(scope="skill:s")
        seed_record(sb.ledger, graduated)
        _graduate_directly(sb, bucket_dir, graduated)

        c, _runner = make_client(sb)
        archive = _archive_section(c.get("/bucket/skill/s").text)

        assert routed.id in archive
        assert pending.id not in archive
        assert rejected.id not in archive
        assert graduated.id not in archive
        assert "Routed here (1)" in archive


# ===================================================================== #
# Criterion 3 — the index does not cross buckets
# ===================================================================== #


class TestIndexDoesNotCrossBuckets:
    def test_two_differently_named_buckets_stay_separate(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s", "t"))
        rec_s = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec_s)
        resolve_record_directly(sb.ledger, _bucket_dir(sb, "skill", "s"), rec_s)

        rec_t = make_behavior(scope="skill:t")
        seed_record(sb.ledger, rec_t)
        resolve_record_directly(sb.ledger, _bucket_dir(sb, "skill", "t"), rec_t)

        c, _runner = make_client(sb)
        archive_s = _archive_section(c.get("/bucket/skill/s").text)
        archive_t = _archive_section(c.get("/bucket/skill/t").text)

        assert rec_s.id in archive_s
        assert rec_t.id not in archive_s
        assert rec_t.id in archive_t
        assert rec_s.id not in archive_t

    def test_skill_named_user_does_not_collide_with_the_user_bucket(
        self, tmp_path: Path
    ) -> None:
        """The one constructible collision shape (§5): `discover_buckets`
        names the user bucket by the literal constant "user", while a
        skill directory can ALSO be named "user" — both routed records
        carry `bucket == "user"` in `report --json`'s `routed_live`, so
        a name-only filter would show both in both sections. Guarded by
        M2."""
        sb = make_env(tmp_path, skills=("user",))
        rec_skill = make_behavior(scope="skill:user")
        seed_record(sb.ledger, rec_skill)
        resolve_record_directly(sb.ledger, _bucket_dir(sb, "skill", "user"), rec_skill)

        rec_user = make_behavior(scope="user")
        seed_record(sb.ledger, rec_user)
        resolve_record_directly(sb.ledger, _bucket_dir(sb, "user"), rec_user)

        c, _runner = make_client(sb)
        skill_archive = _archive_section(c.get("/bucket/skill/user").text)
        user_archive = _archive_section(c.get("/bucket/user/user").text)

        assert rec_skill.id in skill_archive
        assert rec_user.id not in skill_archive
        assert rec_user.id in user_archive
        assert rec_skill.id not in user_archive


# ===================================================================== #
# Criterion 4 — row honesty (a) and selection hygiene (c)
# (4(b), the slot clear + its ordering, is the incumbent
# test_proposals.py::TestProposalRoutes::test_resolved_elsewhere_clears_
# slot_on_detail_render, updated in place — not duplicated here.)
# ===================================================================== #


class TestArchiveRowHonestyAndSelectionHygiene:
    def test_row_anchor_text_is_leading_text_not_the_id(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        c, _runner = make_client(sb)
        archive = _archive_section(c.get("/bucket/skill/s").text)

        # Scoped to the `.record-row-lead` ELEMENT specifically (§4's own
        # wording) — never row-scoped or page-scoped, which would be
        # wrong here: the id legitimately appears elsewhere in the row,
        # in its own `.record-row-id` span (below). Matched on the CLASS,
        # not the tag, so this stays a criterion-4(a)-only assertion even
        # under M18 (which drops the `<a href>` but keeps the class) —
        # M18's own table entry is "criterion 1 only".
        lead = re.search(r'class="record-row-lead"[^>]*>([^<]*)<', archive)
        assert lead, "no archive row leading-text element found"
        assert lead.group(1) == TRIGGER
        assert rec.id not in lead.group(1)
        # Code-gate MAJOR 2: `rec.id in archive` alone is satisfied by
        # the anchor's OWN `href` — it proves nothing about the
        # `.record-row-id` span §4 calls load-bearing. Pin the span (and
        # the fact-line, which was equally unpinned) directly: deleting
        # either leaves every criterion-2/3/4(a) test green (verified —
        # this is FOLD A's exact collapse), and turns M18 into a
        # four-criterion mutation instead of one.
        assert re.search(rf'<span class="record-row-id">{rec.id}</span>', archive)
        assert re.search(r'class="archive-row-facts">routed \d+d ago → ', archive)

    def test_archive_rows_carry_no_data_row_pending_rows_still_do(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        pending = make_behavior(scope="skill:s")
        seed_record(sb.ledger, pending)
        routed = make_behavior(scope="skill:s")
        seed_record(sb.ledger, routed)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), routed)

        c, _runner = make_client(sb)
        page = c.get("/bucket/skill/s").text
        archive = _archive_section(page)

        assert archive, "no archive section rendered"
        assert "data-row" not in archive
        # Control: the pending row's OWN data-row is still there — this
        # isn't passing because the page has no `data-row` rows at all.
        pending_row = re.search(
            rf'<div class="record-row[^"]*" data-row>\s*<a href="/record/{pending.id}"',
            page,
        )
        assert pending_row, "the pending row lost its own data-row attribute"


# ===================================================================== #
# Criterion 5 — VIEWABLE renders every status
# ===================================================================== #


class TestViewableRendersEveryStatus:
    def test_get_record_returns_200_with_trigger_text_for_every_status(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)

        routed = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, routed)
        resolve_record_directly(sb.ledger, bucket_dir, routed)

        rejected = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, rejected)
        resolve_record_directly(sb.ledger, bucket_dir, rejected, status="rejected")

        graduated = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, graduated)
        _graduate_directly(sb, bucket_dir, graduated)

        pending = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, pending)

        deferred = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, deferred)
        defer_record(sb.ledger, deferred.id, "2026-09-01")

        c, _runner = make_client(sb)
        for rec in (routed, rejected, graduated, pending, deferred):
            r = c.get(f"/record/{rec.id}", follow_redirects=False)
            assert r.status_code == 200, rec.id
            assert TRIGGER in r.text, rec.id


# ===================================================================== #
# Criterion 6 — RESOLVED-VERBS offered, and nothing else
# ===================================================================== #


class TestResolvedVerbsOfferedAndNothingElse:
    def test_routed_record_offers_exactly_one_graduate_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        c, _runner = make_client(sb)
        page = c.get(f"/record/{rec.id}", follow_redirects=False).text

        assert page.count('data-key-action="graduate"') == 1
        for verb in ("route", "reject", "defer", "iterate"):
            assert f'data-key-action="{verb}"' not in page, verb
        # F5-1's singleton-cycle branch renders the control under
        # data-noop-action only — assert BOTH halves absent, or a
        # data-key-action-only check would pass vacuously.
        assert 'data-key-action="cycle_destination"' not in page
        assert 'data-noop-action="cycle_destination"' not in page


# ===================================================================== #
# Criterion 7 — the action is not offered twice (GET side)
# ===================================================================== #


class TestActionNotOfferedTwiceGetSide:
    def test_graduated_record_offers_no_graduate_control(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)
        rec = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, rec)
        _graduate_directly(sb, bucket_dir, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        assert TRIGGER in r.text  # criterion 5's control, reused
        assert 'data-key-action="graduate"' not in r.text

    def test_rejected_record_offers_no_graduate_control(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)
        rec = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec, status="rejected")
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        assert TRIGGER in r.text  # criterion 5's control, reused
        assert 'data-key-action="graduate"' not in r.text


# ===================================================================== #
# Criterion 8 — end to end: the verb runs, the receipt renders, the
# control does not come back
# ===================================================================== #


def _envelope(**overrides) -> dict:
    base = {
        "action": "graduate",
        "record_id": "lrn-aa000001",
        "canon_path": None,  # always None for graduate (verbs.py:2960-2972)
        "host_commit_sha": "abcdef0123456789",
        "ledger_paths": [],
        "commit_message": "graduate",
        "destination": None,
        "variant": None,
        "deferred_until": None,
        "warnings": [],
        "created": None,
        "outcome_state": "landed",
        "over_cap": None,
        "pushed": "pushed",
        "host_pushed": "pushed",
    }
    base.update(overrides)
    return base


class TestGraduateEndToEnd:
    def test_argv_evidence_and_no_reoffer(self, tmp_path: Path) -> None:
        """(a) argv, with nothing hand-written: parsed off the rendered
        Graduate control's own hx-vals/hx-post, then the SAME discipline
        against the armed confirm form's own hidden fields. (b)
        envelope-sourced evidence: the 7-char host_commit_sha comes from
        the QUEUED envelope, not a URL/argv value. (c) no re-offer: the
        same confirm response's own absence of the control, controlled
        by (b)'s presence assertion on that same response."""
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec)

        env_dict = _envelope(record_id=rec.id, host_commit_sha="abcdef0123456789")
        runner = FakeRunner()
        runner.queue_result(RunResult(0, stdout=json.dumps(env_dict)))
        c, _runner = make_client(sb, runner=runner)

        page = c.get(f"/record/{rec.id}", follow_redirects=False).text
        button = re.search(
            r'<button type="button" data-key-action="graduate"\s+'
            r'hx-post="([^"]+)"\s+hx-vals=\'([^\']+)\'',
            page,
        )
        assert button, "no rendered Graduate control found"
        hx_post, hx_vals_raw = button.group(1), button.group(2)
        vals = json.loads(hx_vals_raw)

        arm_resp = c.post(hx_post, data=vals, headers=HX)
        assert arm_resp.status_code == 200

        confirm_form = re.search(
            r'<form hx-post="(/record/[^"]+/action/confirm)"[^>]*>(.*?)</form>',
            arm_resp.text,
            re.S,
        )
        assert confirm_form, "no armed confirm form found"
        confirm_url = confirm_form.group(1)
        confirm_fields = dict(
            re.findall(
                r'<input type="hidden" name="([^"]+)" value="([^"]*)"',
                confirm_form.group(2),
            )
        )

        confirm_resp = c.post(confirm_url, data=confirm_fields, headers=HX)
        assert confirm_resp.status_code == 200

        # (a) argv — no verb/kind string written literally above; every
        # value came off the rendered page itself.
        assert runner.calls == [["graduate", rec.id, "--json"]]

        # (b) envelope-sourced evidence — the sha's 7-char prefix, from
        # the QUEUED envelope.
        assert "abcdef0" in confirm_resp.text

        # (c) no re-offer — same response, controlled by (b) above.
        assert 'data-key-action="graduate"' not in confirm_resp.text

    def test_evidence_ctx_carries_canon_path_and_host_commit_sha_from_the_envelope(
        self,
    ) -> None:
        """Unit-level companion to (b): `_evidence_ctx` itself threads
        BOTH fields straight off `run_result.evidence` — guarded by M10
        (`envelope = None`), which would null both out AND flip
        `degraded` to True."""
        result = RunResult(
            0,
            evidence=_envelope(
                record_id="lrn-aa000001",
                canon_path="/host/plugins/s-plugin/skills/s/SKILL.md",
                host_commit_sha="feedfacecafe",
            ),
        )
        ctx = routes._evidence_ctx(
            verb="graduate",
            record_id="lrn-aa000001",
            run_result=result,
            next_url=None,
            bucket_url=None,
        )
        assert ctx["canon_path"] == "/host/plugins/s-plugin/skills/s/SKILL.md"
        assert ctx["host_commit_sha"] == "feedfacecafe"
        assert ctx["degraded"] is False


# ===================================================================== #
# Criterion 9 — the fossil comment is corrected
# ===================================================================== #


class TestFossilCommentCorrected:
    def test_redirect_rationale_no_longer_appears_in_source(self) -> None:
        """Code-gate MINOR 3/4: MINOR 3's positive control — an empty or
        wrong read would satisfy every absence assertion below trivially,
        the exact "PASS when the target is invisible" shape this project
        keeps re-learning — so this first asserts the read actually
        landed inside `_evidence_ctx`. MINOR 4 widens the scan to
        `templates/partials/evidence.html`, which carried the SAME
        fossil rationale ("303-redirects to the bucket's
        resolved-elsewhere ... banner") independently of routes.py's own
        copy, plus a second routes.py site
        (`action_cycle_destination`'s "SSE refresh lands the
        resolved-elsewhere banner")."""
        routes_source = Path(routes.__file__).read_text(encoding="utf-8")
        evidence_html_path = (
            Path(__file__).resolve().parents[1] / "templates" / "partials" / "evidence.html"
        )
        evidence_source = evidence_html_path.read_text(encoding="utf-8")

        # Positive control (MINOR 3): the read landed on the right
        # file/function. `evidence_source` had none of its own — it is
        # self-controlling only because a wrong path raises — so pin its
        # content too (delta-gate wording nit).
        assert "def _evidence_ctx(" in routes_source
        assert "evidence-nav" in evidence_source

        for source in (routes_source, evidence_source):
            assert "record_detail`'s GET redirects" not in source
            assert "resolved-elsewhere banner" not in source
            assert "303-redirects" not in source


# ===================================================================== #
# Criterion 13 — the title fix is guarded
# ===================================================================== #


class TestResolvedTitleFix:
    def test_resolved_record_heading_shows_the_trigger_text(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s", trigger=TRIGGER)
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False).text
        assert f"<h2>{TRIGGER}</h2>" in r
        assert "(untitled)" not in r

    def test_resolved_record_with_blank_trigger_section_falls_back_to_untitled(
        self, tmp_path: Path
    ) -> None:
        """§3.0's empty-case control: `record_title` returns `""` (not
        `"(untitled)"`) when the Trigger SECTION has no non-blank
        content line — the heading is still required to exist at least
        once by `Record.validate()`, so this is a blank body under a
        present heading, not a missing section outright (the only shape
        `Record`'s own validation allows to reach this render at all).
        `_build_finding`'s `title or "(untitled)"` supplies the
        fallback."""
        sb = make_env(tmp_path)
        bucket_dir = _bucket_dir(sb)
        rec = make_behavior(scope="skill:s")
        rec.set_body("\n## Trigger\n\n## Instruction\nStop the container first.\n")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, bucket_dir, rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False).text
        assert "<h2>(untitled)</h2>" in r


# ===================================================================== #
# Criterion 14 — the distinct page_kind is guarded, and `g` is
# advertised there
# ===================================================================== #


class TestDistinctPageKindAdvertisesGraduate:
    def test_markup_and_stylesheet_pin_advertised_iff_present(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        c, _runner = make_client(sb)
        page = c.get(f"/record/{rec.id}", follow_redirects=False).text

        # (a) markup: a distinct page_kind — neither "detail" nor empty.
        match = re.search(r'<body data-page="([^"]*)"', page)
        assert match, "no data-page attribute rendered"
        page_kind = match.group(1)
        assert page_kind not in ("detail", "")

        # (b) stylesheet: the ONE action is advertised, the pending
        # quad's five-key context rule is not — both halves, so this
        # pins "advertised iff present" in both directions (criterion 6
        # already pins the five controls absent from the page itself).
        css = STYLE_CSS_PATH.read_text(encoding="utf-8")
        assert (
            f'body[data-page="{page_kind}"] .keymap-footer-entry[data-action="graduate"]'
            in css
        )
        assert (
            f'body[data-page="{page_kind}"] .keymap-footer-entry[data-context="detail"]'
            not in css
        )


# ===================================================================== #
# Criterion 15 (code-gate finding 6 / user ruling 2026-08-02) — a FAILED
# archive read shows a failure line, never a silent omission. The bug
# report behind this whole unit was "a thing I needed was invisible with
# no indication it existed" — a section that vanishes on a failed CLI
# read reproduces that same experience one layer up. Three legs: the
# model must carry the failed-read state as something DISTINCT from
# "read succeeded, nothing routed" (a conflation test — both must exist
# and differ); the rendered page must show "Routed here (unavailable)"
# on a genuine failure, never silence (M21); and — delta-gate MAJOR,
# the leg that was missing — the rendered page must NOT show that line
# on a healthy, genuinely-empty read, because `{% if not model.archive
# %}` in place of `{% if model.archive_error %}` inverts the ruling
# (tells the user a healthy read failed) while leaving every other test
# in this file green. Guarded by M21 (failure→silence) and the new
# span-check mutation below (healthy→false-failure).
# ===================================================================== #


class TestArchiveReadFailureShowsAFailureLine:
    def test_model_distinguishes_failed_read_from_genuinely_empty(self) -> None:
        from self_learn_ui.models import build_bucket_model

        failed = build_bucket_model(
            "s",
            "skill",
            [],
            {},
            [],
            [],
            host_registered=True,
            host_add_command=None,
            archive_entries=None,
            archive_error="self-learn report --json exited 1",
        )
        assert failed.archive == ()
        assert failed.archive_error == "self-learn report --json exited 1"

        empty_but_ok = build_bucket_model(
            "s",
            "skill",
            [],
            {},
            [],
            [],
            host_registered=True,
            host_add_command=None,
            archive_entries=[],
            archive_error=None,
        )
        assert empty_but_ok.archive == ()
        assert empty_but_ok.archive_error is None

    def test_bucket_page_shows_failure_header_not_silence(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from self_learn_ui.models import CliRead

        sb = make_env(tmp_path)
        # A pending record so the rest of the page has something to
        # prove it still rendered — a failed archive read must not take
        # down the pending queue above it.
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)

        def failing_report(home, *, env=None):
            return CliRead(data=None, error="self-learn report --json exited 1")

        monkeypatch.setattr(routes.ledger, "report", failing_report)

        page = c.get("/bucket/skill/s").text
        assert "Routed here (unavailable)" in page
        assert "self-learn report --json exited 1" in page
        assert rec.id in page

    def test_healthy_bucket_with_nothing_routed_renders_no_failure_line(
        self, tmp_path: Path
    ) -> None:
        """The other half of the ruling: read SUCCEEDED, nothing routed.
        The model-level test above pins this distinction in the model; this
        pins that the TEMPLATE honours it. `{% if not model.archive %}` in
        place of `{% if model.archive_error %}` leaves every other test in
        this file green while telling the user a healthy read failed."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)
        page = c.get("/bucket/skill/s").text
        assert "Routed here (unavailable)" not in page
        assert "archive-section" not in page
        assert rec.id in page  # presence control: the page did render

    def test_wrong_shape_report_data_fails_loud_not_500(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Delta-gate MINOR: a fifth `CliRead` failure mode — `ok=True`
        with the wrong JSON shape (CLI version skew) — is none of the
        four the dataclass models (spawn error, timeout, non-zero exit,
        decode error). Unguarded, `report_read.data` being a bare list
        reaches `.get("routed_live")` and raises `AttributeError`,
        500ing a page that never used to touch `report` at all. Must
        degrade to the SAME failure-line posture as a genuine read
        failure, not a crash and not silence."""
        from self_learn_ui.models import CliRead

        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        c, _runner = make_client(sb)

        def wrong_shape_report(home, *, env=None):
            return CliRead(data=[1, 2], error=None)

        monkeypatch.setattr(routes.ledger, "report", wrong_shape_report)

        resp = c.get("/bucket/skill/s")
        assert resp.status_code == 200
        assert "Routed here (unavailable)" in resp.text
        assert "list" in resp.text
        assert rec.id in resp.text
