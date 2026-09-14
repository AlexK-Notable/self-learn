"""U3 (build-u3.md, lane so-batch) -- ``cli._cmd_batch``'s own wiring:
when a sheet names a case and the run is not ``--dry-run``,
``cases.receipt`` is called once, AFTER `batch.run`'s own locked
section has already closed (a second, non-nested `intents.ledger_write`
acquisition — `cases.receipt` opens its own). Fold r1 (F1): EVERY item
rides the call now, `already-applied` included — idempotence is
`cases.receipt`'s own job, keyed on `(sheet_sha, item index)` and
REPLACING a key's line on a re-run rather than appending, not this
module's "exclude already-applied, skip when nothing remains" filter
(that filter was itself the bug gate-u3-r1.md F1 found: a pre-applied
item never got a line at all, and a refused item's line duplicated on
every re-run).

CLI-level tests only (``cli.main([...])`` / ``cli._cmd_batch`` through
argparse) -- module-level `batch.*` behaviour is `test_batch.py`.
Neither file existed before U3; fold r1 (this build) is layered on top.
"""

from __future__ import annotations

import io
import json

import pytest
from ruamel.yaml import YAML

from self_learn import cases, cli
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import commit_all, make_behavior, make_home, proposal_dict


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


def _env(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


def _seed_pending(home, rid, *, scope="skill:s", with_proposal=True):
    create_record(home, make_behavior(record_id=rid, scope=scope))
    if with_proposal:
        from self_learn.ledger_ops import write_proposal

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
        "question": "U3 CLI test case",
        "evidence": [{"ref": "transcript:u3cli#L1", "quote": "u3 quote"}],
        "decision": {"verb": outcome, "because": "u3 cli test", "confidence": "settled"},
    }
    stage = tmp_path / f"cli-stage-{n[0]}.yaml"
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


def _application_lines(home, case_id):
    """Every non-blank line of the case's Application section, with the
    empty-section placeholder (`cases._rebuild_body`'s own `"(none)"`)
    normalized away — an untouched section renders that literal, not an
    empty string."""
    view = cases.show(home, case_id, evidence_only=False)
    text = view.sections.get("Application", "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [] if lines == ["(none)"] else lines


# ============================================================== dry-run


class TestDryRunNoReceipt:
    def test_dry_run_with_case_writes_no_receipt(self, tmp_path, monkeypatch, capsys):
        """Positive control FIRST: the case exists and its Application
        section is empty before asserting `--dry-run` left it that
        way."""
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e0000001")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        assert _application_lines(home, case_id) == []  # positive control

        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        rc = cli.main(["batch", str(sheet), "--dry-run", "--json"])
        capsys.readouterr()
        assert rc == 0
        assert _application_lines(home, case_id) == []
        # and nothing applied either -- true dry-run
        assert Record.from_path(find_record_path(home, rid)).status == "pending"


# ================================================================ real run


class TestRealRunReceipt:
    def test_legacy_graduate_warning_reaches_json_stderr_and_case_receipt(
        self, tmp_path, monkeypatch, capsys
    ):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-e00000f9")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid}\n    verb: graduate\n",
            name="legacy-graduate.yaml",
        )

        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        notice = (
            "`graduate` is `retire` now; covering surface unrecorded — "
            "name it with --covered-by"
        )

        assert rc == 0
        assert payload["items"][0]["warnings"] == [notice]
        assert notice in captured.err
        record = Record.from_path(find_record_path(home, rid))
        assert record.superseded_by == "canon"
        lines = _application_lines(home, case_id)
        assert len(lines) == 1
        assert notice in lines[0]

    def test_real_run_writes_one_line_per_item(self, tmp_path, monkeypatch, capsys):
        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-e0000002")
        rid2 = _seed_pending(home, "lrn-e0000003")
        case_id = _seed_case(home, tmp_path, records=[rid1, rid2], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid1}\n    verb: reject\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["case"] == case_id
        lines = _application_lines(home, case_id)
        assert len(lines) == 2
        assert f"item=1 {rid1} reject" in lines[0]
        assert f"item=2 {rid2} reject" in lines[1]

    def test_real_run_includes_not_attempted_in_receipt(
        self, tmp_path, monkeypatch, capsys
    ):
        """A mid-sheet stop still writes a receipt line for every item,
        `not-attempted` ones included (build-u3.md Tests: "a real run
        writes one line per item including the `not-attempted` ones")
        -- driven the same way `test_batch.py`'s equivalent does (a
        monkeypatched `_dispatch` simulating a ledger-level STOP,
        rc=7), through the real CLI path this time so the receipt
        wiring itself is exercised."""
        from self_learn import batch as batch_mod

        home = _env(tmp_path, monkeypatch)
        ids = [f"lrn-e000010{i}" for i in range(2)]
        for rid in ids:
            _seed_pending(home, rid)
        case_id = _seed_case(home, tmp_path, records=ids, outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {ids[0]}\n    verb: reject\n"
            f"  - id: {ids[1]}\n    verb: reject\n",
        )
        real_dispatch = batch_mod._dispatch

        def fake_dispatch(home_, item, *, case=None, **kw):
            # O-2b: accept/forward the new `actor`/`hook_activation`
            # keywords `run` now always passes.
            if item.n == 1:
                return batch_mod.ItemResult(
                    n=item.n, id=item.id, verb=item.verb, rc=7,
                    state="refused", detail="simulated git failure",
                )
            return real_dispatch(home_, item, case=case, **kw)

        monkeypatch.setattr(batch_mod, "_dispatch", fake_dispatch)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 7
        lines = _application_lines(home, case_id)
        assert len(lines) == 2
        # Fold r1 (F9): item 1 is the one that actually stopped the
        # sheet -- its receipt line says `stopped`, not the generic
        # `refused` an ordinary per-verb refusal gets.
        assert "item=1" in lines[0] and "stopped" in lines[0]
        assert "item=2" in lines[1] and "not-attempted" in lines[1]


# ============================================================== idempotence


class TestIdempotentReceipt:
    def test_rerun_of_applied_sheet_appends_no_duplicate_lines(
        self, tmp_path, monkeypatch, capsys
    ):
        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-e0000201")
        rid2 = _seed_pending(home, "lrn-e0000202")
        case_id = _seed_case(home, tmp_path, records=[rid1, rid2], outcome="route")
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid1}\n    verb: route\n    dest: skill-md\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )
        rc1 = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc1 == 0
        lines1 = _application_lines(home, case_id)
        assert len(lines1) == 2

        rc2 = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc2 == 0  # every item already-applied -> a clean 0, nothing refused
        lines2 = _application_lines(home, case_id)
        # Fold r1 (F1): NOT four lines -- no duplicate receipt; the key
        # for each item is unchanged (same sheet, same item index), so
        # the second run's `already-applied` rendering REPLACES the
        # first run's `applied` line in place rather than adding a
        # third and fourth -- the count is pinned, not byte-identity
        # (the state word itself is EXPECTED to change, applied ->
        # already-applied, once a second run finds the item done).
        assert len(lines2) == len(lines1) == 2
        assert f"item=1 {rid1} route" in lines1[0] and "applied (exit 0)" in lines1[0]
        assert f"item=2 {rid2} reject" in lines1[1] and "applied (exit 0)" in lines1[1]
        assert f"item=1 {rid1} route" in lines2[0] and "already-applied (exit 0)" in lines2[0]
        assert f"item=2 {rid2} reject" in lines2[1] and "already-applied (exit 0)" in lines2[1]


# ========================================================= fold r1: F1

class TestF1KeyedReceipts:
    """gate-u3-r1.md F1: the old filter ('exclude already-applied,
    skip the call once nothing remains') was this module's own broken
    idempotence mechanism. `cases.receipt` is idempotent BY KEY now
    (sheet_sha, item index) -- these reproduce the gate's three
    measured shapes."""

    def test_pre_applied_item_by_hand_still_gets_a_receipt_line(
        self, tmp_path, monkeypatch, capsys
    ):
        """Probe A: item 1 applied BY HAND before a two-item sheet
        naming the case runs -- the Application section must carry a
        line for it too, not just item 2."""
        from self_learn import verbs as verbs_mod

        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-f0000001")
        rid2 = _seed_pending(home, "lrn-f0000002")
        case_id = _seed_case(home, tmp_path, records=[rid1, rid2], outcome="reject")
        verbs_mod.reject(home, rid1, note="done by hand", no_push=True)
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid1}\n    verb: reject\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 0
        lines = _application_lines(home, case_id)
        assert len(lines) == 2
        assert any(
            f"item=1 {rid1} reject" in ln and "already-applied (exit 0)" in ln
            for ln in lines
        )
        assert any(
            f"item=2 {rid2} reject" in ln and "applied (exit 0)" in ln
            for ln in lines
        )

    def test_refused_item_over_three_identical_runs_does_not_grow(
        self, tmp_path, monkeypatch, capsys
    ):
        """Probe B: a sheet whose second item refuses (not a STOP,
        rc=1) every single time -- three runs must leave ONE line for
        it, never three."""
        from self_learn import verbs as verbs_mod

        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-f0000101")
        rid2 = _seed_pending(home, "lrn-f0000102")
        case_id = _seed_case(home, tmp_path, records=[rid1, rid2], outcome="reject")
        verbs_mod.route(home, rid2, dest="skill-md", no_push=True)  # reject on this refuses
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid1}\n    verb: reject\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )
        for _ in range(3):
            cli.main(["batch", str(sheet), "--no-push", "--json"])
            capsys.readouterr()
        lines = _application_lines(home, case_id)
        assert len(lines) == 2
        assert sum(1 for ln in lines if "refused" in ln) == 1

    def test_receipt_repaired_on_retry_after_transient_failure(
        self, tmp_path, monkeypatch, capsys
    ):
        """Probe G: `cases.receipt` fails once, AFTER the batch already
        applied and committed. F2: the exit code stays the batch's own
        (0, not the receipt error's code). F1: a later re-run of the
        SAME sheet repairs the missing Application line -- the call is
        never skipped just because the item now classifies
        already-applied."""
        from self_learn import cases as cases_mod
        from self_learn import cli as cli_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000601")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        real_receipt = cases_mod.receipt
        calls = {"n": 0}

        def flaky(home_, case_id_, batch_result):
            calls["n"] += 1
            if calls["n"] == 1:
                raise cases_mod.CaseError("simulated transient receipt failure")
            return real_receipt(home_, case_id_, batch_result)

        monkeypatch.setattr(cli_mod.cases, "receipt", flaky)

        rc1 = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc1 == 0  # F2: the batch's OWN process_code, untouched
        assert Record.from_path(find_record_path(home, rid)).status == "rejected"
        assert _application_lines(home, case_id) == []  # not yet repaired

        rc2 = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc2 == 0
        assert calls["n"] == 2
        lines = _application_lines(home, case_id)
        assert len(lines) == 1
        assert "already-applied" in lines[0]  # retried: the record is already resolved


# ========================================================= fold r1: F2

class TestF2ReceiptFailureNeverRewritesExitCode:
    def test_receipt_failure_does_not_change_a_zero_exit(
        self, tmp_path, monkeypatch, capsys
    ):
        from self_learn import cases as cases_mod
        from self_learn import cli as cli_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000501")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        def always_fail(*a, **kw):
            raise cases_mod.CaseError("simulated")

        monkeypatch.setattr(cli_mod.cases, "receipt", always_fail)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["process_code"] == 0
        assert payload["receipt"] == {"state": "failed", "reason": "simulated"}

    def test_receipt_failure_does_not_change_an_eight_exit(
        self, tmp_path, monkeypatch, capsys
    ):
        from self_learn import cases as cases_mod
        from self_learn import cli as cli_mod
        from self_learn import verbs as verbs_mod

        home = _env(tmp_path, monkeypatch)
        rid1 = _seed_pending(home, "lrn-f0000502")
        rid2 = _seed_pending(home, "lrn-f0000503")
        case_id = _seed_case(home, tmp_path, records=[rid1, rid2], outcome="reject")
        verbs_mod.route(home, rid2, dest="skill-md", no_push=True)  # makes item 2 refuse
        sheet = _write_sheet(
            tmp_path,
            "version: 1\n"
            f"case: {case_id}\n"
            "items:\n"
            f"  - id: {rid1}\n    verb: reject\n"
            f"  - id: {rid2}\n    verb: reject\n",
        )

        def always_fail(*a, **kw):
            raise cases_mod.CaseError("simulated")

        monkeypatch.setattr(cli_mod.cases, "receipt", always_fail)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        out = capsys.readouterr().out
        assert rc == 8  # >=1 applied, >=1 refused -> EXIT_BATCH_PARTIAL, untouched
        payload = json.loads(out)
        assert payload["process_code"] == 8
        assert payload["receipt"]["state"] == "failed"

    def test_nonexistent_case_refused_before_item_1(self, tmp_path, monkeypatch, capsys):
        """F2: 'a case id that does not exist is refused at load_sheet
        time, before item 1 (usage, 64), so it can never fail after a
        commit.'"""
        import subprocess

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000504")
        head_before = subprocess.run(
            ["git", "-C", str(home), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: case-deadbeef\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 64
        head_after = subprocess.run(
            ["git", "-C", str(home), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert head_after == head_before
        assert Record.from_path(find_record_path(home, rid)).status == "pending"


# ========================================================= fold r1: F4

class TestF4ReceiptOrdering:
    def test_receipt_commit_lands_after_and_separate_from_sheet_commits(
        self, tmp_path, monkeypatch, capsys
    ):
        import subprocess

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000201")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 0
        subjects = subprocess.run(
            ["git", "-C", str(home), "log", "--format=%s", "-2"],
            capture_output=True, text=True,
        ).stdout.splitlines()
        assert subjects[0] == f"self-learn: case receipt {case_id} (sheet=sheet.yaml)"
        assert subjects[1] == f"self-learn: reject {rid}"

    def test_receipt_is_called_after_batch_run_returns_not_from_inside_it(
        self, tmp_path, monkeypatch, capsys
    ):
        """A call-order spy, not just a commit-order assertion: probe C
        showed the commit-order check alone does not distinguish a
        receipt called from INSIDE `batch.run`'s own span from one
        called after it returns, when the sheet produces no separate
        flush commit (gate-u3-r1.md's own M1 finding) -- this test
        would still be green under that mutation, so it does not stand
        in for it. This one watches ORDER OF CALLS directly."""
        from self_learn import batch as batch_mod
        from self_learn import cases as cases_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000202")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        events: list[str] = []
        real_run = batch_mod.run
        real_receipt = cases_mod.receipt

        def spy_run(*a, **kw):
            out = real_run(*a, **kw)
            events.append("run-returned")
            return out

        def spy_receipt(*a, **kw):
            events.append("receipt-called")
            return real_receipt(*a, **kw)

        monkeypatch.setattr(batch_mod, "run", spy_run)
        monkeypatch.setattr(cases_mod, "receipt", spy_receipt)

        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 0
        assert events == ["run-returned", "receipt-called"]


# ========================================================= fold r1: F5

class TestF5ReceiptExceptionBreadth:
    def test_gitops_error_from_receipt_is_caught_not_raised(
        self, tmp_path, monkeypatch, capsys
    ):
        """F5: `cases.receipt` can raise more than `cases.CaseError` --
        `gitops.GitOpsError` (the shared base of `HalfWrittenError` and
        `intents.LedgerStoppedError` too) must be caught here as well,
        or it escapes to `main`'s last-resort net and reports a FALSE
        half-written alarm over a batch whose own items already
        committed cleanly."""
        from self_learn import cli as cli_mod
        from self_learn import gitops as gitops_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000801")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        def boom(*a, **kw):
            raise gitops_mod.GitOpsError("simulated git failure")

        monkeypatch.setattr(cli_mod.cases, "receipt", boom)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        out = capsys.readouterr().out
        assert rc == 0  # F2: the batch's own decision, untouched
        payload = json.loads(out)
        assert payload["receipt"]["state"] == "failed"
        assert Record.from_path(find_record_path(home, rid)).status == "rejected"


# ========================================================= fold r1: F6

class TestF6ReceiptCommitIsPushed:
    def test_receipt_commit_is_pushed_when_not_no_push(
        self, tmp_path, monkeypatch, capsys
    ):
        from self_learn import verbs as verbs_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000901")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        calls: list = []
        real_push = verbs_mod.push_pending

        def spy_push(home_):
            calls.append(home_)
            return real_push(home_)

        monkeypatch.setattr(verbs_mod, "push_pending", spy_push)
        rc = cli.main(["batch", str(sheet), "--json"])  # note: no --no-push
        capsys.readouterr()
        assert rc == 0
        # once inside batch.run's own single push, once more for the
        # receipt commit that landed strictly after it.
        assert len(calls) == 2

    def test_receipt_commit_is_not_pushed_under_no_push(
        self, tmp_path, monkeypatch, capsys
    ):
        from self_learn import verbs as verbs_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000902")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        calls: list = []
        real_push = verbs_mod.push_pending

        def spy_push(home_):
            calls.append(home_)
            return real_push(home_)

        monkeypatch.setattr(verbs_mod, "push_pending", spy_push)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 0
        assert calls == []


# ========================================================= fold r1: F7

class TestF7TextSummaryCountsWholeSheet:
    def test_text_mode_summary_includes_stopped_and_not_attempted(
        self, tmp_path, monkeypatch, capsys
    ):
        from self_learn import batch as batch_mod

        home = _env(tmp_path, monkeypatch)
        ids = [f"lrn-f100010{i}" for i in range(2)]
        for rid in ids:
            _seed_pending(home, rid)
        sheet = _write_sheet(
            tmp_path,
            "version: 1\nitems:\n"
            f"  - id: {ids[0]}\n    verb: reject\n"
            f"  - id: {ids[1]}\n    verb: reject\n",
        )
        real_dispatch = batch_mod._dispatch

        def fake_dispatch(home_, item, *, case=None, **kw):
            # O-2b: accept/forward the new `actor`/`hook_activation`
            # keywords `run` now always passes.
            if item.n == 1:
                return batch_mod.ItemResult(
                    n=item.n, id=item.id, verb=item.verb, rc=7,
                    state="refused", detail="simulated git failure",
                )
            return real_dispatch(home_, item, case=case, **kw)

        monkeypatch.setattr(batch_mod, "_dispatch", fake_dispatch)
        rc = cli.main(["batch", str(sheet), "--no-push"])
        err = capsys.readouterr().err
        assert rc == 7
        assert (
            "self-learn batch: 0 applied, 0 already-applied, 0 refused, "
            "1 stopped, 1 not-attempted (of 2)" in err
        )


# ========================================================= fold r1: F8

class TestF8WholeSheetRefusalReceipt:
    def test_cli_receipts_a_synthetic_whole_sheet_stop(
        self, tmp_path, monkeypatch, capsys
    ):
        """A sheet-level preflight STOP (before item 1 ever dispatched)
        is expensive to manufacture for real (a live intent left
        STOPPED by a second process — `test_recover_or_refuse.py`'s own
        territory); `batch.run` is monkeypatched here to return exactly
        the zero-item `BatchResult` shape that path produces, so this
        integration-tests `_cmd_batch`'s OWN wiring for it (the
        mechanism itself is unit-tested directly against `cases.receipt`
        in `test_cases.py`)."""
        from self_learn import batch as batch_mod

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0001301")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )

        def fake_run(home_, items, *, no_push=False):
            return batch_mod.BatchResult(
                case=case_id, sheet_sha="deadbeef", process_code=6,
                stop_message="a live intent is STOPPED (simulated)",
            )

        monkeypatch.setattr(batch_mod, "run", fake_run)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 6
        lines = _application_lines(home, case_id)
        assert len(lines) == 1
        assert "refused before item 1: a live intent is STOPPED (simulated)" in lines[0]


# ============================================== O-2b test 6: no CLI flag


class TestNoCliFlagExposesOverseerParameters:
    """O-2b (13 §7.4 "The path"): "`batch` keeps refusing a hook route
    on every ordinary sheet, unchanged... this is the one caller
    [the overseer's own runner] that lifts the refusal, and only for
    its own call" -- the CLI `batch` verb must never be able to pass
    either `actor` or `hook_activation` to `batch.run`/`batch.dry_run`.

    `cli._main` does not use argparse's default `parse_args` (which
    raises `SystemExit` on an unrecognized flag) -- it calls
    `parser.parse_known_args` itself and turns any leftover `_extra`
    into a printed message plus a returned `EXIT_USAGE` (64), not a
    raised `SystemExit` (confirmed empirically: the first version of
    this test asserted `pytest.raises(SystemExit)` and failed with
    "DID NOT RAISE" even though the flag was correctly refused --
    `cli.main` returned 64 having already printed "unrecognized
    arguments" to stderr). These two tests assert the REAL contract:
    `cli.main(...)` returns `cli.EXIT_USAGE`, prints the unrecognized-
    arguments message naming the flag, and never dispatches the verb.

    Mutation witness: adding
    ``batch_p.add_argument("--actor")``/``batch_p.add_argument(
    "--hook-activation", action="store_true")`` to `cli.py`'s parser
    setup (and threading them into the two calls below) would redden
    BOTH assertions here (argparse would accept the flag, `_extra`
    would stay empty, and `cli.main` would return the verb's own exit
    code instead of `EXIT_USAGE`, and the record would move off
    `pending`) -- verified by hand-adding the two lines, running RED,
    reverting, confirming GREEN (recorded in this build's report; not
    left as a live toggle, since it would require a real argparse
    wiring change to demonstrate rather than a monkeypatch)."""

    def test_actor_flag_does_not_parse(self, tmp_path, monkeypatch, capsys):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-d0000001")
        sheet = _write_sheet(
            tmp_path, f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n"
        )
        rc = cli.main(["batch", str(sheet), "--actor", "overseer"])
        err = capsys.readouterr().err
        assert rc == cli.EXIT_USAGE
        assert "unrecognized arguments" in err and "--actor" in err
        # nothing ran -- the verb was never dispatched
        assert Record.from_path(find_record_path(home, rid)).status == "pending"

    def test_hook_activation_flag_does_not_parse(self, tmp_path, monkeypatch, capsys):
        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-d0000002")
        sheet = _write_sheet(
            tmp_path, f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n"
        )
        rc = cli.main(["batch", str(sheet), "--hook-activation"])
        err = capsys.readouterr().err
        assert rc == cli.EXIT_USAGE
        assert "unrecognized arguments" in err and "--hook-activation" in err
        assert Record.from_path(find_record_path(home, rid)).status == "pending"
