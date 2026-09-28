"""Batch 2026-09-28, unit D: the steward's YAML errors never carry the
model's text.

The user's words (2026-09-28 11:54 PDT, on the list of small items): "fix
the rest of 3". The steward's stage reader put the parser's own message
into its errors, and that message quotes a snippet of the file around the
error -- the model's own words. When no case/sheet pair passes, that error
is committed to the run record. The overseer already keeps only the file,
the problem cut at its first quote, and the position; the steward now
shares that one helper.

Every scenario runs on a pytest sandbox ledger with a fake model session;
the ids and texts are synthetic.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from ruamel.yaml import YAML, YAMLError

from self_learn import scan, steward
from self_learn.invocation.contract import Outcome
from self_learn.overseer import run as overseer_run
from support import make_env
from test_heading_evidence import KEPT_ITEM, _case
from test_steward import _dump_yaml, _enable_steward, _stage_dir
from test_steward_refusals import _dispositions, _notifications, _seed

#: A phrase only the fake model writes; it appears in the stage file's
#: unparseable line, so a parser snippet would carry it.
MODEL_WORDS = "zebra-quartz-lantern"
BAD_SHEET = f"version: 1\ncase: $CASE_ID\nnote: the {MODEL_WORDS}: said so\nitems: []\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _committed_run_record(home, run_id) -> str:
    listing = subprocess.run(
        ["git", "-C", str(home), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    paths = [p for p in listing if run_id in p]
    assert paths, "the run record is committed"
    texts = []
    for p in paths:
        raw = subprocess.run(
            ["git", "-C", str(home), "show", f"HEAD:{p}"], capture_output=True, text=True,
            check=True,
        ).stdout
        try:  # a JSON record escapes the em dash; compare decoded text
            raw = json.dumps(json.loads(raw), ensure_ascii=False)
        except ValueError:
            pass
        texts.append(raw)
    return "\n".join(texts)


def test_an_unparseable_sheet_reaches_the_run_record_without_the_models_text(
    tmp_path, monkeypatch
):
    """One lesson; the model writes its sheet with a plain value holding
    ``": "`` on both the decision call and the repair turn, so no pair
    passes and the packet's error is committed. Before: the committed
    record carried ``note: the zebra-quartz-lantern: said so``. Now it
    carries the file, the problem and the position only."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d0000001")
    _enable_steward(home)
    _notifications(monkeypatch)
    calls = []

    def session(spec):
        calls.append(spec.prompt)
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / f"{rid}.yaml", _case(rid, [KEPT_ITEM]))
        (stage / "sheets").mkdir(parents=True, exist_ok=True)
        (stage / "sheets" / f"{rid}.yaml").write_text(BAD_SHEET, encoding="utf-8")
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    assert len(calls) == 2  # the decision call and its repair turn
    assert _dispositions(home, result.run_id)[rid]["state"] == "unfinished"
    record = _committed_run_record(home, result.run_id)
    # Positive control: the parse error itself IS in the committed record.
    assert f"{rid}.yaml: cannot parse — mapping values are not allowed here at line 3" in record
    assert MODEL_WORDS not in record
    # The repair turn was told the same, without the text either.
    assert "cannot parse — mapping values are not allowed here at line 3" in calls[1]
    assert MODEL_WORDS not in calls[1].split("=== repair ===", 1)[1]
    journal = steward.journal_path(home).read_text(encoding="utf-8")
    assert result.run_id in journal  # positive control: this run's journal
    assert MODEL_WORDS not in journal


def _parse_error(text: str) -> YAMLError:
    try:
        YAML(typ="safe").load(text)
    except YAMLError as exc:
        return exc
    raise AssertionError("expected a parse error")


def test_the_steward_and_the_overseer_share_one_rule():
    """One helper: the overseer's name is the shared function, and a
    problem that still matches the secret scan after the cut becomes a
    fixed phrase in both. The scan-shaped problem is built at runtime."""
    assert overseer_run._yaml_error_text is scan.yaml_error_text
    exc = _parse_error(BAD_SHEET)
    assert scan.yaml_error_text("x.yaml", exc) == (
        "x.yaml: cannot parse — mapping values are not allowed here at line 3, column 31"
    )
    fake = type("Fake", (), {})()
    fake.problem = "found " + "ghp_" + "A1b2C3d4" * 5
    fake.problem_mark = None
    assert scan.scan(fake.problem)  # positive control: the problem is scan-shaped
    assert scan.yaml_error_text("x.yaml", fake) == "x.yaml: cannot parse — not valid YAML"
    # The steward's reader uses it.
    assert steward.yaml_error_text is scan.yaml_error_text
