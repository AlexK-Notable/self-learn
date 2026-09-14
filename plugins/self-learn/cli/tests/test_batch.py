"""U3 (build-u3.md, lane so-batch) -- the batch sheet's top-level
``case:`` key, receipts that carry the WHOLE sheet (including
``not-attempted`` items past a stop), and ``by:`` on every resolution
verb (02-schema.md §3a.1 rule 5 / §3a.2 §5, S-54 as amended;
`commands/review.md` ~:145-194).

Module-level tests against ``batch.load_sheet`` / ``batch.run`` /
``batch.classify`` / ``batch.dry_run`` directly -- CLI-level (`--json`,
the receipt wiring in ``cli._cmd_batch``) tests live in
``test_batch_cli.py``. Neither file existed before this build (U3's
brief names both paths; nothing at either was ever pinned by
``test_armor.py``).

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(``support.make_home``) -- never the real ``~/.self-learn``.
"""

from __future__ import annotations

import io

import pytest
from ruamel.yaml import YAML

from self_learn import batch, cases, verbs
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_home, proposal_dict


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# --------------------------------------------------------------- helpers


def _env(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


def _seed_pending(home, rid, *, scope="skill:s", with_proposal=True):
    create_record(home, make_behavior(record_id=rid, scope=scope))
    if with_proposal:
        write_proposal(home, rid, proposal_dict(scope=scope))
    commit_all(home, "pending seed")
    return rid


def _seed_case(home, tmp_path, *, records, outcome="route", actor="steward", n=[0]):
    n[0] += 1
    data = {
        "kind": "resolution",
        "trigger": "nightly",
        "outcome": outcome,
        "records": list(records),
        "scope": "skill:s",
        "question": "U3 test case",
        "evidence": [{"ref": "transcript:u3test#L1", "quote": "u3 quote"}],
        "decision": {"verb": outcome, "because": "u3 test", "confidence": "settled"},
    }
    stage = tmp_path / f"stage-{n[0]}.yaml"
    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    stage.write_text(buf.getvalue(), encoding="utf-8")
    return cases.record(home, stage, actor=actor)


def _write_sheet(tmp_path, body, *, name="sheet.yaml"):
    sheet = tmp_path / name
    sheet.write_text(body, encoding="utf-8")
    return sheet


# =========================================================== top-level case


class TestTopLevelCase:
    """`load_sheet` reads an optional top-level ``case:`` key and
    refuses any OTHER unknown top-level key before item 1
    (02-schema.md §3a.1: "An unknown top-level key — including a
    hand-written `actor:` — is refused before item 1 runs, the same
    way an unknown item key is refused today")."""

    def test_sheet_without_case_parses_unchanged(self, tmp_path, monkeypatch):
        """Positive control, checked FIRST: an old sheet with no
        `case:` key still loads and its `.case` is `None` -- U3 never
        breaks a pre-existing sheet."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-a0000001")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        assert isinstance(items, batch.Sheet)
        assert items.case is None
        result = batch.run(home, items, no_push=True)
        assert result.case is None
        assert result.summary["applied"] == 1

    def test_sheet_with_case_round_trips_into_json(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-a0000002")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        assert items.case == case_id
        result = batch.run(home, items, no_push=True)
        assert result.case == case_id
        assert result.to_json()["case"] == case_id

    def test_malformed_case_id_refused(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-a0000003")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: not-a-case-id\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        with pytest.raises(batch.BatchError, match="malformed case id"):
            batch.load_sheet(sheet)

    def test_unknown_top_level_key_refused_before_item_1(self, tmp_path, monkeypatch):
        """`actor:` -- explicitly named by the spec as the motivating
        example -- is refused the same as any other unknown top-level
        key, and NOTHING applies (the record stays pending)."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-a0000004")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nactor: human\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        with pytest.raises(batch.BatchError, match="unknown top-level key"):
            batch.load_sheet(sheet)
        assert Record.from_path(find_record_path(home, rid)).status == "pending"

    def test_unknown_top_level_key_message_names_it(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-a0000005")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nbogus: 1\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        with pytest.raises(batch.BatchError, match=r"\['bogus'\]"):
            batch.load_sheet(sheet)


# ============================================================ not-attempted


class TestNotAttempted:
    """A mid-sheet STOP (a ledger-level failure, rc in {5, 6, 7}) still
    carries the WHOLE sheet in the result: every item after the stop
    point is reported ``state: not-attempted`` rather than silently
    dropped (02-schema.md §3a.1 rule 5 / `commands/review.md` :151)."""

    def test_stop_at_item_2_of_5_yields_three_not_attempted(
        self, tmp_path, monkeypatch
    ):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-b0000001")
        # A malformed `--to` on `rehome` refuses with a USAGE error (64)
        # at dispatch -- not a STOP code. To reach an actual STOP
        # (5/6/7) without a second real process, use S-62's own
        # sheet-level preflight: an intent left STOPPED before item 1
        # is the cheapest reliable STOP to manufacture, but it refuses
        # the WHOLE sheet (nothing dispatches at all, `stopped_at`
        # stays associated with the PREFLIGHT, not an item n). The
        # per-item STOP path this test needs is a live intent stopped
        # mid-flight by a second process -- exercised for real by
        # `test_recover_or_refuse.py`. Here, `decision_code`/the
        # not-attempted APPEND are pure functions of
        # `_STOP_CODES = {5, 6, 7}` and `item_result.rc`, so a
        # monkeypatched `_dispatch` that returns rc=7 (git failed) on
        # item 2 exercises the exact same code path `run` takes on a
        # real STOP, without needing a second process.
        ids = [rid] + [f"lrn-b000000{i}" for i in range(2, 6)]
        for other in ids[1:]:
            _seed_pending(home, other)
        sheet_lines = ["version: 1", "items:"]
        for i in ids:
            sheet_lines.append(f"  - id: {i}")
            sheet_lines.append("    verb: reject")
        sheet = _write_sheet(tmp_path, "\n".join(sheet_lines) + "\n")
        items = batch.load_sheet(sheet)
        assert len(items) == 5

        real_dispatch = batch._dispatch
        calls = {"n": 0}

        def fake_dispatch(home_, item):
            calls["n"] += 1
            if item.n == 2:
                return batch.ItemResult(
                    n=item.n, id=item.id, verb=item.verb, rc=7,
                    state="refused", detail="simulated git failure",
                )
            return real_dispatch(home_, item)

        monkeypatch.setattr(batch, "_dispatch", fake_dispatch)
        result = batch.run(home, items, no_push=True)
        assert result.stopped_at == 2
        assert calls["n"] == 2  # item 3-5 never reached `_dispatch`
        states = [(it.n, it.state, it.rc) for it in result.items]
        assert states == [
            (1, "applied", 0),
            # Fold r1 (F9): item 2 is the ONE item whose rc actually
            # stopped the sheet -- `run` gives it `state="stopped"`,
            # not the generic `"refused"` `fake_dispatch` returned,
            # distinct from an ordinary per-verb refusal (02-schema.md
            # §3a.2 §5 names `stopped` as its own receipt state).
            (2, "stopped", 7),
            (3, "not-attempted", -1),
            (4, "not-attempted", -1),
            (5, "not-attempted", -1),
        ]
        summary = result.summary
        assert summary["not_attempted"] == 3
        assert summary["stopped"] == 1
        assert (
            summary["applied"] + summary["already_applied"]
            + summary["refused"] + summary["stopped"] + summary["not_attempted"]
            == summary["total"]
            == 5
        )
        # a `not-attempted` item's rc=-1 never changes the sheet's own
        # decision code -- decision_code only inspects rc in (3,4,6,7);
        # the STOP here is item 2's rc=7.
        assert result.process_code == 7

    def test_not_attempted_absent_when_nothing_stops(self, tmp_path, monkeypatch):
        """Positive control for the above: a sheet that runs clean end
        to end carries NO `not-attempted` items at all."""
        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-b0000101")
        rid2 = _seed_pending(home, "lrn-b0000102")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {rid1}\n    verb: reject\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.stopped_at is None
        assert all(it.state != "not-attempted" for it in result.items)
        assert result.summary["not_attempted"] == 0


# =================================================================== by:


class TestByAttribution:
    """``by`` joins every resolution verb's permitted-key set
    (02-schema.md §3a.1 rule 5). It observably PERSISTS for `route`
    (`routing.by`) and `revise` (the proposal's `revised_by`, U4's own
    sink) -- the two verbs whose underlying `verbs.*` function already
    accepts a `by` parameter. For the other eight (`reject` et al.),
    `by` is accepted at the sheet-grammar level (spec-compliant) but
    has no persistence sink today (`verbs.reject` etc. take no `by`
    parameter) -- see batch.py's own `PERMITTED_KEYS` comment and this
    build's report for the spec-vs-brief note (build-u3.md's Tests
    bullet says a non-route `by` "lands in the record's routing
    block", which is not buildable without repurposing
    `Record.routing` for non-routed statuses -- a change with a much
    wider blast radius than this build's scope; not made here)."""

    def test_by_on_route_lands_in_routing_block(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000001")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {rid}\n    verb: route\n    dest: skill-md\n    by: steward\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1
        after = Record.from_path(find_record_path(home, rid))
        assert after.routing["by"] == "steward"

    def test_by_on_revise_lands_in_proposal_revised_by(self, tmp_path, monkeypatch):
        """`revise`'s sink is the proposal sibling's `revised_by`
        (`verbs.revise`'s own contract, verbs.py:8045-8053, carried
        from U4) -- the "one other non-route verb" this build's Tests
        bullet asks for."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000002")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {rid}\n    verb: revise\n    section: Trigger\n"
            "    text: Reworded by the sheet.\n"
            "    because: batch attribution test\n"
            "    by: steward\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1
        proposal_path = (
            find_record_path(home, rid).parent.parent / "proposals" / f"{rid}.yaml"
        )
        from self_learn.ledger_ops import read_proposal

        assert read_proposal(proposal_path)["revised_by"] == "steward"

    def test_by_permitted_on_reject_and_loads(self, tmp_path, monkeypatch):
        """`by` is a PERMITTED key on `reject` (a resolution verb) even
        though nothing persists it -- the sheet parses and the item
        applies exactly as it would without `by`."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000003")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n    by: steward\n",
        )
        items = batch.load_sheet(sheet)  # must not raise
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1
        assert Record.from_path(find_record_path(home, rid)).status == "rejected"

    def test_actor_and_activate_stay_unknown_item_keys(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000004")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n    actor: steward\n",
        )
        with pytest.raises(batch.BatchError, match="unknown key"):
            batch.load_sheet(sheet)
        sheet2 = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: route\n    "
            "dest: skill-md\n    activate: true\n",
            name="sheet2.yaml",
        )
        with pytest.raises(batch.BatchError, match="unknown key"):
            batch.load_sheet(sheet2)


# ================================================================ revise


class TestReviseDispatch:
    """Carried from the U4 gate (gate-u4-r1.md F5): `revise` joined
    PERMITTED_VERBS without dispatch wiring, so a sheet naming it
    crashed `_dispatch`'s `else: raise AssertionError` on the SECOND
    item — this lane's own scope (build-u3.md's final section)."""

    def test_revise_classify_already_applied_on_rerun(self, tmp_path, monkeypatch):
        """Idempotence (S-54): a second run of an applied `revise`
        item classifies already-applied instead of reaching
        `verbs.revise` and getting its "nothing to revise" refusal."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-d0000001")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {rid}\n    verb: revise\n    section: Trigger\n"
            "    text: Reworded once.\n    because: first pass\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1

        items2 = batch.load_sheet(sheet)
        result2 = batch.run(home, items2, no_push=True)
        assert result2.summary == {
            "applied": 0, "already_applied": 1, "refused": 0,
            "stopped": 0, "not_attempted": 0, "total": 1,
        }

    def test_revise_classify_false_on_wrong_status(self, tmp_path, monkeypatch):
        """A revise item against a ROUTED record is never
        already-applied — it reaches `_dispatch` and refuses there,
        naming the actual status (same precedent as rehome/rescope)."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-d0000002")
        result = verbs.route(home, rid, dest="skill-md", no_push=True)
        assert result.action == "route"
        path = find_record_path(home, rid)
        item = batch.SheetItem(
            n=1, id=rid, verb="revise",
            fields={"section": "Trigger", "text": "x", "because": "y"},
        )
        assert batch.classify(home, item) is False

    def test_revise_dry_run_status_gate(self, tmp_path, monkeypatch):
        """`dry_run`'s generic status-gate check now covers `revise`
        (`_STATUS_GATE["revise"]`) -- a routed record's revise item
        previews `would-refuse`, not `would-apply`."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-d0000003")
        verbs.route(home, rid, dest="skill-md", no_push=True)
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {rid}\n    verb: revise\n    section: Trigger\n"
            "    text: x\n    because: y\n",
        )
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(home, items)
        assert dr.items[0].state == "would-refuse"


# ========================================================= fold r1: F3


class TestByValidation:
    """gate-u3-r1.md F3: `by`, where permitted, is validated against
    `verbs.ROUTING_BY_VALUES` at `load_sheet` time -- `by: bogus` is
    refused on `reject` exactly as it already was on `route`, before
    item 1, never silently accepted and dropped at dispatch."""

    def test_by_bogus_refused_on_reject(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000001")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n    by: bogus\n",
        )
        with pytest.raises(batch.BatchError, match="by=") :
            batch.load_sheet(sheet)

    def test_by_bogus_refused_on_defer(self, tmp_path, monkeypatch):
        """A second non-route verb, as build-u3.md's own Tests bullet
        asks for."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000002")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: defer\n    by: bogus\n",
        )
        with pytest.raises(batch.BatchError, match="by="):
            batch.load_sheet(sheet)

    def test_by_valid_value_loads_on_reject(self, tmp_path, monkeypatch):
        """Positive control: a real `ROUTING_BY_VALUES` member loads
        fine -- the validation only refuses OUTSIDE the closed set."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000003")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n    by: steward\n",
        )
        items = batch.load_sheet(sheet)  # must not raise
        assert items[0].fields["by"] == "steward"


class TestByTrailer:
    """F3: `by`, on any of the eight non-route/non-revise resolution
    verbs, rides the LEDGER commit body as its own final paragraph --
    ``By: <actor>``, git trailer semantics -- never the record's own
    `resolution.note` (F3(c): not an attribution slot)."""

    def test_by_trailer_is_its_own_final_paragraph_on_reject(
        self, tmp_path, monkeypatch
    ):
        import subprocess

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000010")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n    by: steward\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1

        body = subprocess.run(
            ["git", "-C", str(home), "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert body.strip().splitlines()[-1] == "By: steward"
        trailer = subprocess.run(
            ["git", "-C", str(home), "log", "-1", "--format=%(trailers:key=By,valueonly)"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert trailer == "steward"
        # the resolution note field itself is untouched (F3(c)) -- no
        # note was ever given, so the record must not have acquired one
        # just because `by` did.
        record = Record.from_path(find_record_path(home, rid))
        assert record.resolution_note in (None, "")

    def test_note_ending_in_key_value_does_not_merge_into_by_trailer(
        self, tmp_path, monkeypatch
    ):
        """F3(b): a `--note` whose own last line already looks
        trailer-shaped (`Key: value`) must not let its forged line ride
        along as part of the `By:` block -- the blank line this fold
        always inserts keeps them in separate paragraphs, and git's
        trailer scan (`%(trailers)`) only reads the LAST one."""
        import subprocess

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000011")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n"
            "    by: steward\n"
            '    note: "Reason: this line looks like a trailer"\n',
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1

        trailers = subprocess.run(
            ["git", "-C", str(home), "log", "-1", "--format=%(trailers)"],
            capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()
        assert trailers == ["By: steward"]  # the forged "Reason:" line never joins it

    def test_by_absent_leaves_commit_body_untouched(self, tmp_path, monkeypatch):
        """Positive control: no `by:` on the item -> no trailer
        paragraph at all -- every pre-existing single-verb commit body
        stays byte-identical to before this fold."""
        import subprocess

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000012")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n"
            '    note: "a plain note, no by at all"\n',
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1
        body_only = subprocess.run(
            ["git", "-C", str(home), "log", "-1", "--format=%b"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "By:" not in body_only
        assert body_only.strip() == "a plain note, no by at all"


# ========================================================= fold r1: F9


class TestDecisionCodeStoppedItem:
    """F9's regression trap: `decision_code` used to spot a stop purely
    by `item.state == "refused"`. Now that `run` gives the item that
    actually stopped the sheet `state="stopped"` instead, `decision_code`
    must count `stopped` as a refusal too, or an rc=5 stop with nothing
    landed would silently decide 0 ("nothing refused") instead of 1
    ("refused, nothing written")."""

    def test_rc5_stop_with_nothing_landed_is_one(self):
        results = [
            batch.ItemResult(n=1, id="lrn-h0000001", verb="reject", rc=5, state="stopped"),
        ]
        assert batch.decision_code(results) == 1

    def test_rc5_stop_after_something_landed_is_eight(self):
        results = [
            batch.ItemResult(n=1, id="lrn-h0000001", verb="reject", rc=0, state="applied"),
            batch.ItemResult(n=2, id="lrn-h0000002", verb="reject", rc=5, state="stopped"),
        ]
        assert batch.decision_code(results) == 8


# ========================================================= fold r1: F2 load


class TestLoadSheetCaseExistence:
    def test_nonexistent_case_refused_when_home_given(self, tmp_path, monkeypatch):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000020")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: case-deadbeef\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        with pytest.raises(batch.BatchError, match="case"):
            batch.load_sheet(sheet, home=home)

    def test_nonexistent_case_accepted_when_home_omitted(self, tmp_path, monkeypatch):
        """Positive control: every pre-existing caller passes no
        `home` and gets exactly today's behaviour -- a malformed-
        SHAPE-only check, no existence check at all."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000021")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: case-deadbeef\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)  # must not raise
        assert items.case == "case-deadbeef"

    def test_real_case_accepted_when_home_given(self, tmp_path, monkeypatch):
        """Positive control: a case that DOES exist loads fine with
        `home` given -- the existence check only refuses a missing
        one."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000022")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet, home=home)  # must not raise
        assert items.case == case_id
