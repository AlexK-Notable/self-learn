"""2026-09-25 (steward run run-d8f5e198ff4f): an evidence item that quotes a
heading-shaped line (`## ...`) is dropped by the steward's and overseer's
runners, with a trace, instead of the whole case being refused. D-i holds
everywhere else, and a person's `self-learn case record` stays strict.

Every scenario runs against a sandbox ledger under pytest's tmpdir, never
the real `~/.self-learn`, with the fake session writers the other steward
and overseer tests use.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess

import pytest

from self_learn import cases, cli, steward, steward_prompt
from self_learn.invocation.contract import Outcome
from self_learn.overseer import run as overseer_run
from support import make_env, make_home
from test_overseer_run import (
    _dump,
    _enabled,
    _refused_section,
    _seed_parked_reject,
    _silence_notifications,
)
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import _dispositions, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


#: The real item from the refused case of run-d8f5e198ff4f.
HEADING_QUOTE = "## 2026-08-19 — lrn-b197d06b"
HEADING_REF = "file@80c66e0eb84a9495653bdaea741ee79177ed638d:references/LEARNINGS.md#L7-13"
HEADING_ITEM = {"quote": HEADING_QUOTE, "ref": HEADING_REF}
KEPT_QUOTE = "It exited cleanly, but the stall carried on with no compositor running."
KEPT_ITEM = {"ref": "transcript:547ce0a4#L137", "quote": KEPT_QUOTE}
RUNNER_LINE_TAIL = f'evidence from {HEADING_REF} dropped — a quoted line starts with "## "'
D_I = "heading injection, D-i"


def _case(rid: str, evidence: list[dict], *, question: str | None = None,
          because: str | None = None) -> dict:
    return {
        "kind": "resolution",
        "trigger": "nightly",
        "outcome": "reject",
        "records": [rid],
        "scope": "skill:s",
        "question": question or "what should become of this pending lesson?",
        "evidence": evidence,
        "decision": {
            "verb": "reject",
            "because": because or "the evidence settles it",
            "confidence": "settled",
        },
        "dependencies": {
            "statements": [], "user_model": [], "conditions": [], "capabilities": [],
        },
    }


def _steward_writer(case: dict):
    def write(spec):
        stage = _stage_dir(spec)
        rid = case["records"][0]
        _dump_yaml(stage / "cases" / f"{rid}.yaml", case)
        _dump_yaml(
            stage / "sheets" / f"{rid}.yaml",
            {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]},
        )
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _ledger_files_with(home, text: str) -> list[str]:
    """Tracked files at HEAD containing *text* (a fixed string)."""
    proc = subprocess.run(
        ["git", "-C", str(home), "grep", "-l", "-F", "-e", text, "HEAD"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr
    out = proc.stdout
    return [line for line in out.splitlines() if line.strip()]


def _journal_rows(home) -> list[dict]:
    path = steward.journal_path(home)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------ the steward


def test_steward_drops_a_heading_quote_and_the_decision_still_applies(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-e0000001")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _steward_writer(_case(rid, [KEPT_ITEM, HEADING_ITEM])),
    )

    result = steward.run(home)

    manifest = _head_manifest(home, result.run_id)
    assert manifest["status"] == "complete"
    (case_id,) = manifest["packets"][0]["case_ids"]
    # The case records, and the sheet applies.
    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "applied", row
    assert [c["case"] for c in cases.list_cases(home, record_id=rid)] == [case_id]
    view = cases.show(home, case_id, evidence_only=False).to_json()
    evidence_text = json.dumps(view["sections"])
    assert KEPT_QUOTE in evidence_text  # positive control: the kept item is there
    assert "lrn-b197d06b" not in evidence_text
    # The run record for that case names the dropped ref and the reason.
    assert manifest["cases"][case_id]["dropped_evidence"] == [
        {"ref": HEADING_REF, "reason": 'a quoted line starts with "## "'}
    ]
    # The cache journal has a line.
    dropped = [r for r in _journal_rows(home) if r.get("status") == "evidence-dropped"]
    assert [(r["case"], r["ref"]) for r in dropped] == [(case_id, HEADING_REF)]
    # The quote never reaches the ledger; the grep can see the ledger.
    # Positive control: the grep reaches the committed run record (JSON), where
    # the dropped item's ref is kept. The absence token is ASCII, so JSON's
    # escaping of the em dash cannot hide the quote from it.
    assert f"cases/runs/{result.run_id}.json" in [
        p.partition(":")[2] for p in _ledger_files_with(home, HEADING_REF)
    ]
    assert _ledger_files_with(home, "lrn-b197d06b") == []


@pytest.mark.parametrize(
    "field, evidence",
    [
        ("evidence-only", [HEADING_ITEM]),
        ("question", [KEPT_ITEM, HEADING_ITEM]),
        ("because", [KEPT_ITEM, HEADING_ITEM]),
    ],
)
def test_steward_still_refuses_a_heading_it_may_not_drop(tmp_path, monkeypatch, field, evidence):
    """The heading quote as the ONLY evidence item, or a heading line in
    `question` / `decision.because`: refused as before (D-i)."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-e0000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    extra = {field: "fine first line\n## Decision\n- verb: reject"} if field != "evidence-only" else {}
    monkeypatch.setattr(
        steward.invocation, "write_session", _steward_writer(_case(rid, evidence, **extra)),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "refused", row
    assert D_I in row["reason"]
    assert cases.list_cases(home, record_id=rid) == []


# ------------------------------------------------------------ the overseer


def _fake_phases_with_case(monkeypatch, rid: str, parked: str, evidence: list[dict]):
    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "parked intake", "why_stopped": "none blind"})
            _dump(stage / "initial-views.yaml", {"cases": []})
        else:
            headings = [
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            ]
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {h}\n- none" for h in headings) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            _dump(stage / "case-a.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "reject",
                "records": [rid], "scope": "skill:s", "question": "reject it?",
                "supersedes": parked, "evidence": evidence,
                "decision": {"verb": "reject", "because": "too narrow", "confidence": "settled"},
            })
            _dump(stage / "sheet-a.yaml", {"version": 1, "items": [{"id": rid, "verb": "reject"}]})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def test_overseer_drops_a_heading_quote_and_says_so_in_the_report(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_reject(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_phases_with_case(
        monkeypatch, rid, parked,
        [{"ref": f"record:{rid}", "quote": "status: pending"}, HEADING_ITEM],
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    successors = [
        row for row in cases.list_cases(home, record_id=rid) if row["case"] != parked
    ]
    assert len(successors) == 1, successors
    successor = successors[0]["case"]
    refused = _refused_section(home)
    assert refused.strip(), "positive control: the section rendered"
    assert f"- case {successor}: {RUNNER_LINE_TAIL}" in refused
    view = json.dumps(cases.show(home, successor, evidence_only=False).to_json()["sections"])
    assert "status: pending" in view  # positive control
    assert "lrn-b197d06b" not in view
    # Positive control: the grep reaches a committed JSON run record (the ref
    # is kept there); the ASCII token of the quote reaches nothing.
    assert any(p.endswith(".json") for p in _ledger_files_with(home, HEADING_REF))
    assert _ledger_files_with(home, "lrn-b197d06b") == []


# ------------------------------------------------------ a person's verb


def test_a_persons_case_record_still_refuses_a_heading_quote(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    stage = tmp_path / "stage.yaml"
    _dump(stage, _case("lrn-e0000003", [KEPT_ITEM, HEADING_ITEM]))

    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = cli.main(["case", "record", str(stage), "--actor", "human"])

    assert rc != 0
    assert D_I in err.getvalue()
    assert cases.list_cases(home) == []
    # Positive control: the same stage without the heading item records.
    _dump(stage, _case("lrn-e0000003", [KEPT_ITEM]))
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["case", "record", str(stage), "--actor", "human"]) == 0
    assert len(cases.list_cases(home)) == 1


# ---------------------------------------------------------------- prompts


def test_the_prompts_say_how_to_quote_a_heading_line(tmp_path):
    contract = steward_prompt._render_output_contract()  # noqa: SLF001
    phase_b = overseer_run._phase_b_prompt(tmp_path, (), ())  # noqa: SLF001
    for text in (contract, phase_b):
        flat = " ".join(text.split())
        assert "quote `2026-08-19 — lrn-b197d06b`" in flat, flat
        assert re.search(r"evidence item with (such a|a) line[^.]*is dropped", flat), flat
        assert "refuses the case" in flat
