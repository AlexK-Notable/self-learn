"""The overseer corrects a decision that failed once to apply (2026-10-05).

The live chain for lesson `lrn-19f82fc5` (a rule against `pkill -f`/`pgrep -f`
matching its own command line), read from the ledger on 2026-10-05:

1. The steward parked it for the overseer (`case-43852101`, kind parked,
   parked_reason hook).
2. Run `ec93fb36` (09-28) decided it with a `kind: resolution` successor
   (`case-5257d97d`, outcome route) whose `route dest: hook` was refused at
   apply time -- "record lrn-19f82fc5 is 'routed' -- route needs
   pending/deferred". That consumed the parked case and changed nothing.
3. Run `03a07173` (10-04) wrote a `kind: reconsider` successor naming
   `case-5257d97d`, carrying a `dest: hook` `mode: warn` line. The runner
   dropped it at phase B: "supersedes must name a verified parked case",
   because `case-5257d97d` is a resolution, not parked.

U3b's `test_the_overseer_moves_a_routed_lesson_to_a_hook_the_ec93fb36_shape`
passed although the live run failed: its reconsider successor supersedes
the steward's PARKED case directly, which is still open in that test. It
never builds step 2 -- a first, refused overseer resolution that consumes
the parked case -- so the second run's reconsider never has to name a case
that is not parked.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir) with the overseer's fake sessions; the runner, `batch` and
`cases` are the real code. No real model call is made.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases
from self_learn.hook_compiler import script_name
from self_learn.ledger_ops import find_record_path
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from support import make_env
from test_failstate_overseer import _dump, _ok, _phase_a, _phase_b_common, _successor
from test_hook_activation import _real_claude_dir_never_touched  # noqa: F401 -- the real-~/.claude control
from test_overseer_run import _enabled
from test_steward_refusals import _case
from test_u3b_steward_authority import HOOK_TRIGGER, _record_case, _route_through_a_case, _skill_md

RID = "lrn-a5000001"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def _load_yaml(text: str):
    return YAML(typ="safe").load(text)


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _case_fm(home: Path, case_id: str) -> dict:
    return cases.show(home, case_id, evidence_only=False).frontmatter


def _refused_section(home: Path) -> str:
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "## Refused / could not do" in report  # positive control: the section rendered
    return report.split("## Refused / could not do", 1)[1]


def _warn_hook_line(rid: str) -> dict:
    """The live 10-04 line's shape: `route dest: hook` carrying a
    `mode: warn` PreToolUse hook on Bash (the formats example, which is
    itself the pkill/pgrep self-match shape)."""
    line = _load_yaml(formats.phase_b_examples()["sheet-redecide-example.yaml"])["items"][0]
    line["id"] = rid
    assert line["hook"]["hook"]["mode"] == "warn"  # control: the warn shape, not deny
    return line


def _seed_the_chain_up_to_the_refused_resolution(home: Path, tmp_path: Path, monkeypatch) -> tuple[str, str]:
    """Steps 1 and 2 of the live chain. Returns (parked id, resolution id)."""
    setup = tmp_path / "setup"
    setup.mkdir()
    _route_through_a_case(home, setup, RID)
    parked = _case([RID], "parked", "route", scope="user")
    parked.update(kind="parked", parked_for="overseer", parked_reason="hook")
    parked_id = _record_case(home, setup, parked)

    # Run `ec93fb36`: a RESOLUTION successor of the parked case routing the
    # (already routed) lesson to a hook. The live sheet also carried a
    # `note` item; it is left out here because a sheet with one refusal and
    # one commit ends its first attempt unfinished (exit 8) and needs a
    # resume to close, which is not what this test is about.
    first = _successor(RID, parked_id)
    first.update(outcome="route", scope="user")
    first["decision"]["verb"] = "route"
    first_sheet = {"version": 1, "items": [_warn_hook_line(RID)]}

    def invoke_first(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-pkill-hook.yaml", first)
            _dump(spec.cwd / "sheet-pkill-hook.yaml", first_sheet)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke_first)
    first_result = overseer_run.run(home, no_push=True)
    assert overseer_run._unfinished_manifest(home) is None, first_result  # run 1 completed

    resolution_id = _case_fm(home, parked_id).get("superseded_by")
    assert resolution_id, "run 1 consumed the parked case"  # positive control
    resolution = _case_fm(home, resolution_id)
    assert (resolution["kind"], resolution["actor"], resolution["outcome"]) == (
        "resolution", "overseer", "route",
    )
    assert resolution["supersedes"] == parked_id
    application = cases.show(home, resolution_id, evidence_only=False).sections["Application"]
    assert "route → refused" in application, application  # the live refusal at apply
    assert (_record(home, RID).routing or {}).get("destination") == "skill-md"  # nothing changed
    return parked_id, resolution_id


def _second_run(home: Path, monkeypatch, resolution_id: str, case: dict, sheet: dict) -> overseer_run.RunResult:
    """Run `03a07173`: phase A selects the resolution case (as the live
    run did) and phase B writes the given successor pair."""
    def invoke_second(spec):
        if spec.label == "phase-a":
            _dump(spec.cwd / "selection.yaml", {
                "cases": [{"id": resolution_id}],
                "why_these": "the refused hook decision",
                "why_stopped": "the rest read as settled",
            })
            _dump(spec.cwd / "initial-views.yaml", {"cases": [{
                "id": resolution_id,
                "what_i_would_do": "move the lesson to a warning hook",
                "why": "loaded and broken twice",
                "what_evidence_decides_it": "a hook on Bash cannot see the command",
                "confidence": "clear",
            }]})
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "findings.yaml", {"findings": [{
                "case": resolution_id, "kind": "examined",
                "text": "right decision; its route was refused because the case was not a reconsider",
            }]})
            _dump(spec.cwd / "case-pkill-hook.yaml", case)
            _dump(spec.cwd / "sheet-pkill-hook.yaml", sheet)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke_second)
    return overseer_run.run(home, no_push=True, manual=True)


def _reconsider_of(resolution_id: str) -> dict:
    case = _load_yaml(formats.phase_b_examples()["case-redecide-example.yaml"])
    case.update(records=[RID], scope="user", supersedes=resolution_id)
    case["evidence"] = [{"ref": f"record:{RID}", "quote": "status: routed"}]
    return case


def test_the_live_chain_a_reconsider_naming_the_refused_resolution_moves_the_lesson_to_a_warn_hook(
    tmp_path, monkeypatch, claude_dir
):
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    assert RID in _skill_md(env)  # positive control: run 1 left it where it was

    result = _second_run(
        home, monkeypatch, resolution_id,
        _reconsider_of(resolution_id),
        {"version": 1, "items": [_warn_hook_line(RID)]},
    )

    assert resolution_id in result.examined, result  # control: a fresh run that examined it
    refused = _refused_section(home)
    assert "verified parked case" not in refused, refused
    assert "case-pkill-hook.yaml: dropped" not in refused, refused
    reconsider_id = _case_fm(home, resolution_id).get("superseded_by")
    assert reconsider_id, (result, refused)
    reconsider = _case_fm(home, reconsider_id)
    assert (reconsider["kind"], reconsider["actor"], reconsider["supersedes"]) == (
        "reconsider", "overseer", resolution_id,
    )
    record = _record(home, RID)
    assert record.status == "routed"
    routing = record.routing or {}
    assert routing.get("destination") == "hook" and routing.get("by") == "overseer"
    assert (routing.get("hook") or {}).get("mode") == "warn"
    assert RID not in _skill_md(env)  # the old placement was retired
    assert (claude_dir / "hooks" / script_name(RID, HOOK_TRIGGER)).is_symlink()  # placed
    assert not (claude_dir / "settings.json").exists()  # never registered: activation is off
    entry = next(h for h in reversed(record.history) if h.get("event") == "hook-activated")
    assert "switched off" in (entry.get("note") or "")  # the delegated receipt
