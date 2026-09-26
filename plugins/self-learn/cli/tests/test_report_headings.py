"""2026-09-26 (agenda item 19): a missing or misordered required heading in
the overseer's report.md is repaired by the runner, not fatal. A missing
heading is inserted with an empty body that says so, misordered ones are put
back in order, and each repair is one line in "Refused / could not do".
Only headings are repaired: a heading that is not a required one, or one
written twice, still refuses the run as before (see also
test_overseer_run.py's `test_invalid_raw_report_refuses_before_any_decision_and_leaves_a_trace`).

Sandbox ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import pytest

from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import _enabled, _fake_two_phase, _refused_block, _silence_notifications

HEADINGS = overseer_run._REPORT_SECTIONS


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _run_with_report(tmp_path, monkeypatch, rewrite):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch)
    _silence_notifications(monkeypatch)
    real_invoke = overseer_run.invocation.write_session

    def invoke(spec):
        outcome = real_invoke(spec)
        if spec.label == "phase-b":
            report = spec.cwd / "report.md"
            report.write_text(rewrite(report.read_text(encoding="utf-8")), encoding="utf-8")
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return home, overseer_run.run(home, dry_run=False, no_push=True)


def _published(home) -> str:
    return (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")


def _heading_order(text: str) -> list[str]:
    return [line[3:].partition(" (")[0] for line in text.splitlines() if line.startswith("## ")]


def test_a_missing_heading_is_inserted_and_the_run_goes_on(tmp_path, monkeypatch):
    home, result = _run_with_report(
        tmp_path, monkeypatch, lambda text: text.replace("## Hooks\n- none\n", "")
    )

    assert (result.status, result.code) == ("applied", 0), result
    report = _published(home)
    assert _heading_order(report) == list(HEADINGS)
    hooks = report.split("## Hooks\n", 1)[1].split("\n## ", 1)[0]
    assert hooks.strip() == "(the overseer wrote nothing under this heading)", hooks
    block = _refused_block(home)
    assert 'report: the heading "Hooks" was missing; the runner added it, empty' in block, block


def test_misordered_headings_are_put_back_in_order_with_their_text(tmp_path, monkeypatch):
    def swap(text: str) -> str:
        text = text.replace("## Examined\n- none\n", "## Examined\n- the examined line\n")
        hooks = "## Hooks\n- none\n"
        examined = "## Examined\n- the examined line\n"
        return text.replace(examined, "@@E@@").replace(hooks, examined).replace("@@E@@", hooks)

    home, result = _run_with_report(tmp_path, monkeypatch, swap)

    assert (result.status, result.code) == ("applied", 0), result
    report = _published(home)
    assert _heading_order(report) == list(HEADINGS)
    examined = report.split("## Examined\n", 1)[1].split("\n## ", 1)[0]
    assert "- the examined line" in examined, examined
    block = _refused_block(home)
    assert "report: the headings were out of order; the runner put them back in order" in block
    assert "was missing" not in block


@pytest.mark.parametrize("rewrite", [
    pytest.param(lambda text: text.replace("## Hooks\n", "## Hooks\n- x\n## Hooks\n"), id="twice"),
    pytest.param(lambda text: text.replace("## Hooks\n", "## Notes\n- x\n## Hooks\n"), id="unknown"),
])
def test_a_shape_the_runner_cannot_repair_still_refuses(tmp_path, monkeypatch, rewrite):
    home, result = _run_with_report(tmp_path, monkeypatch, rewrite)

    assert (result.status, result.code) == ("refused", 1), result
    assert not (home / "overseer" / "latest-report.md").exists()


def test_a_report_already_in_shape_is_left_byte_for_byte(tmp_path):
    report = tmp_path / "report.md"
    text = "# draft\n" + "".join(f"## {h}\n- none\n" for h in HEADINGS)
    report.write_text(text, encoding="utf-8")
    assert overseer_run._repair_report_headings(report) == []
    assert report.read_text(encoding="utf-8") == text
