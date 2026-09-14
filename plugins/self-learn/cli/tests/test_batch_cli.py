"""U3 (build-u3.md, lane so-batch) -- ``cli._cmd_batch``'s own wiring:
when a sheet names a case and the run is not ``--dry-run``,
``cases.receipt`` is called once, AFTER `batch.run`'s own locked
section has already closed (a second, non-nested `intents.ledger_write`
acquisition — `cases.receipt` opens its own), with the already-applied
items filtered out so a re-run of a fully applied sheet appends nothing
(`cases.receipt` itself has no dedupe, cases.py:1036-1038).

CLI-level tests only (``cli.main([...])`` / ``cli._cmd_batch`` through
argparse) -- module-level `batch.*` behaviour is `test_batch.py`.
Neither file existed before this build."""

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

        def fake_dispatch(home_, item):
            if item.n == 1:
                return batch_mod.ItemResult(
                    n=item.n, id=item.id, verb=item.verb, rc=7,
                    state="refused", detail="simulated git failure",
                )
            return real_dispatch(home_, item)

        monkeypatch.setattr(batch_mod, "_dispatch", fake_dispatch)
        rc = cli.main(["batch", str(sheet), "--no-push", "--json"])
        capsys.readouterr()
        assert rc == 7
        lines = _application_lines(home, case_id)
        assert len(lines) == 2
        assert "item=1" in lines[0] and "refused" in lines[0]
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
        assert lines2 == lines1  # NOT four lines -- no duplicate receipt
