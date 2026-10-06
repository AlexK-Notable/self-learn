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


def test_the_drop_line_names_the_real_reason_when_a_reconsider_names_the_wrong_case(
    tmp_path, monkeypatch, claude_dir
):
    """S-76: the run's "Refused / could not do" line for a dropped
    reconsider names why (here: its predecessor does not cover the
    record), not the parked-only rule that no longer applies to it."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    wrong = _reconsider_of(resolution_id)
    wrong["records"] = ["lrn-a5000002"]

    _second_run(home, monkeypatch, resolution_id, wrong,
                {"version": 1, "items": [_warn_hook_line("lrn-a5000002")]})

    refused = _refused_section(home)
    assert "case-pkill-hook.yaml: dropped with sheet-pkill-hook.yaml" in refused, refused
    assert f"reconsider: {resolution_id} does not cover lrn-a5000002" in refused, refused
    assert "verified parked case" not in refused, refused
    assert _case_fm(home, resolution_id).get("superseded_by") is None


# ------------------------------------- the successor guards, one by one


@pytest.fixture
def decided(tmp_path):
    """A sandbox ledger with a routed lesson and the steward's (non-parked)
    case that routed it, plus a second lesson that case does not cover."""
    from support import commit_all, make_behavior
    from self_learn.ledger_ops import create_record

    env = make_env(tmp_path)
    home = env.ledger
    setup = tmp_path / "setup"
    setup.mkdir()
    prior = _route_through_a_case(home, setup, RID)
    create_record(home, make_behavior(record_id="lrn-a5000002"))
    commit_all(home, "seed lrn-a5000002")
    return home, setup, prior


def _staged(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / f"case-{len(list(tmp_path.glob('case-*.yaml')))}.yaml"
    _dump(path, data)
    return path


def test_a_reconsider_may_supersede_a_decided_case_that_covers_its_records(tmp_path, decided):
    home, _setup, prior = decided
    assert _case_fm(home, prior)["kind"] == "resolution"  # not parked
    overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(prior)), set(), home)


def test_a_resolution_successor_still_supersedes_only_a_parked_case(tmp_path, decided):
    home, _setup, prior = decided
    plain = _reconsider_of(prior)
    plain["kind"] = "resolution"
    with pytest.raises(overseer_run.OverseerError, match="verified parked case"):
        overseer_run._validate_successor(_staged(tmp_path, plain), set(), home)
    # control: the same successor naming a parked case passes
    overseer_run._validate_successor(_staged(tmp_path, plain), {prior}, home)


def test_a_reconsider_whose_predecessor_does_not_cover_its_records_is_refused(tmp_path, decided):
    home, _setup, prior = decided
    wrong = _reconsider_of(prior)
    wrong["records"] = [RID, "lrn-a5000002"]
    with pytest.raises(overseer_run.OverseerError, match=f"{prior} does not cover lrn-a5000002"):
        overseer_run._validate_successor(_staged(tmp_path, wrong), set(), home)
    # Parked or not, a reconsider's predecessor must cover every record it
    # names (S-76). For a parked predecessor this is stricter than before
    # S-76 and than a resolution of the same parked case (gate nit 3); it
    # matters most for a routed record, whose line apply time would refuse.
    with pytest.raises(overseer_run.OverseerError, match="does not cover"):
        overseer_run._validate_successor(_staged(tmp_path, wrong), {prior}, home)


def test_a_reconsider_of_a_case_already_superseded_is_refused(tmp_path, decided):
    home, setup, prior = decided
    first = _reconsider_of(prior)
    first["trigger"] = "nightly"
    taken = _record_case(home, setup, first)
    assert _case_fm(home, prior)["superseded_by"] == taken  # control
    with pytest.raises(overseer_run.OverseerError, match=f"already superseded by {taken}"):
        overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(prior)), set(), home)


def test_a_reconsider_of_a_tampered_or_unknown_case_is_refused(tmp_path, decided):
    home, _setup, prior = decided
    with pytest.raises(overseer_run.OverseerError, match="no such case"):
        overseer_run._validate_successor(_staged(tmp_path, _reconsider_of("case-0000ffff")), set(), home)
    path = next((home / "cases").glob(f"*/{prior}.md"))
    text = path.read_text(encoding="utf-8")
    assert "the evidence settles it" in text  # control: the frozen text is there to change
    path.write_text(text.replace("the evidence settles it", "the evidence settles nothing"), encoding="utf-8")
    with pytest.raises(overseer_run.OverseerError, match="freeze-hash"):
        overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(prior)), set(), home)


def test_a_reconsider_successor_cannot_remain_parked_or_miss_a_field(tmp_path, decided):
    home, _setup, prior = decided
    parked = _reconsider_of(prior)
    parked["outcome"] = "parked"
    with pytest.raises(overseer_run.OverseerError, match="cannot remain parked"):
        overseer_run._validate_successor(_staged(tmp_path, parked), set(), home)
    missing = _reconsider_of(prior)
    del missing["evidence"]
    with pytest.raises(overseer_run.OverseerError, match="missing successor field"):
        overseer_run._validate_successor(_staged(tmp_path, missing), set(), home)


def test_the_formats_carry_a_reconsider_correcting_a_case_that_is_not_parked(tmp_path, decided):
    """The overseer's instructions say a reconsider may name a non-parked
    case it is correcting, with one example that passes the runner's own
    checks once its placeholder ids stand for a real decided case."""
    home, _setup, prior = decided
    root = formats.write(tmp_path / "ws", "B")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "case-correct-example.yaml" in readme
    assert "is NOT parked" in readme
    assert "case-correct-example.yaml" in overseer_run._phase_b_prompt(tmp_path, (), ())
    example = _load_yaml((root / "case-correct-example.yaml").read_text(encoding="utf-8"))
    assert example["kind"] == "reconsider"
    assert example["supersedes"] == formats.EXAMPLE_CASE != formats.EXAMPLE_PARKED_CASE
    example.update(records=[RID], supersedes=prior)
    path = _staged(tmp_path, example)
    overseer_run._validate_successor(path, set(), home)
    assert overseer_run._case_rule_problem(path, "abcd1234") is None
    # broken twin: the same example over a record its predecessor does not cover
    example["records"] = ["lrn-a5000002"]
    with pytest.raises(overseer_run.OverseerError, match="does not cover"):
        overseer_run._validate_successor(_staged(tmp_path, example), set(), home)


#: S-76 as the code checks it (`_reconsider_predecessor_problem`): coverage,
#: not superseded, freeze hash -- and nothing about this run's selection.
_CODE_TERMS = (
    "covers every record the reconsider names, has not been superseded, "
    "passes its freeze hash, and was recorded by the steward or the overseer"
)


@pytest.mark.parametrize("name", ["phase B prompt", "formats README"])
def test_the_overseer_is_told_the_reconsider_rule_in_the_codes_terms(tmp_path, name):
    """The coordinator's ruling, 2026-10-05: the words match the code. The
    rule names the three things `_validate_successor` checks of a non-parked
    predecessor and never says the case must be one the run examined."""
    if name == "phase B prompt":
        raw = overseer_run._phase_b_prompt(tmp_path, (), ())
    else:
        raw = (formats.write(tmp_path / "ws", "B") / "README.md").read_text(encoding="utf-8")
    text = " ".join(raw.split())
    assert "kind: reconsider successor" in text  # control: the S-76 sentence rendered
    assert _CODE_TERMS in text, name
    # the sentence that states the rule: from the sentence start before
    # "not parked" through the code's terms
    lowered = text.lower()
    at = lowered.index("not parked")
    sentence = lowered[lowered.rfind(". ", 0, at):lowered.index(_CODE_TERMS, at) + len(_CODE_TERMS)]
    assert "kind: reconsider" in sentence, sentence  # control: it is the S-76 sentence
    assert "examined" not in sentence, sentence


def test_the_dry_run_preview_counts_a_reconsider_reroute_as_would_apply(
    tmp_path, monkeypatch, claude_dir
):
    """Phase B previews each pair with `batch.dry_run`. Without the records
    the staged reconsider covers (`reconsidered=`, S-73 item 6, as the
    steward's preview passes them), its route line on the routed lesson
    previewed as the routed-status refusal apply time no longer makes, and
    the dry-run report counted it "would refuse"."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    head_before = _case_fm(home, resolution_id)

    def invoke(spec):
        if spec.label == "phase-a":
            _dump(spec.cwd / "selection.yaml", {
                "cases": [{"id": resolution_id}], "why_these": "x", "why_stopped": "y",
            })
            _dump(spec.cwd / "initial-views.yaml", {"cases": [{
                "id": resolution_id, "what_i_would_do": "a", "why": "b",
                "what_evidence_decides_it": "c", "confidence": "clear",
            }]})
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-pkill-hook.yaml", _reconsider_of(resolution_id))
            _dump(spec.cwd / "sheet-pkill-hook.yaml", {"version": 1, "items": [_warn_hook_line(RID)]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, dry_run=True, no_push=True)

    assert result.status == "dry-run", result
    report = Path(result.report).read_text(encoding="utf-8")
    assert "- Dry-run preview: 1 sheet(s);" in report, report  # control: the pair was previewed
    assert "1 would apply; 0 would refuse" in report, report
    # a dry run writes nothing: the lesson and the case it would correct are unchanged
    assert _case_fm(home, resolution_id) == head_before
    assert (_record(home, RID).routing or {}).get("destination") == "skill-md"


# --------------- 2026-10-05 fold: who recorded the case being corrected


def test_a_reconsider_never_supersedes_a_case_a_person_recorded(tmp_path, decided):
    """The gate's risk 1 (probe E): before S-76 the overseer could never
    supersede a case a person recorded, because such a case is never in
    the parked queue. A reconsider of a non-parked case now needs a
    predecessor the steward or the overseer recorded; a person's case is
    a per-pair drop that names the actor."""
    home, setup, prior = decided
    human = _case([RID], "route", "route", scope="user")
    human_id = _record_case(home, setup, human, actor="human")
    assert _case_fm(home, human_id)["actor"] == "human"  # control: a person's case
    with pytest.raises(overseer_run.OverseerError, match=f"{human_id}, a case recorded by actor 'human'"):
        overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(human_id)), set(), home)


def test_a_reconsider_of_a_steward_or_overseer_case_is_accepted(tmp_path, decided):
    home, setup, prior = decided
    assert _case_fm(home, prior)["actor"] == "steward"
    overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(prior)), set(), home)
    first = _reconsider_of(prior)
    first["trigger"] = "nightly"
    by_overseer = _record_case(home, setup, first, actor="overseer")
    assert _case_fm(home, by_overseer)["actor"] == "overseer"
    overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(by_overseer)), set(), home)


def test_the_actor_guard_is_for_cases_outside_the_parked_queue_only(tmp_path, decided):
    """A parked case is decided through the parked queue, whoever recorded
    it; the guard reads `actor` only for a predecessor outside it."""
    home, setup, _prior = decided
    human_id = _record_case(home, setup, _case([RID], "route", "route", scope="user"), actor="human")
    overseer_run._validate_successor(_staged(tmp_path, _reconsider_of(human_id)), {human_id}, home)


def test_the_correctable_actors_are_the_case_actors_but_a_person():
    from self_learn import cases as cases_mod

    assert "human" in cases_mod.ACTORS  # control: the closed set has a person in it
    assert overseer_run._CORRECTABLE_ACTORS == cases_mod.ACTORS - {"human"}


# ------------- 2026-10-05 fold: a reconsider that would change nothing


def _moved_to_a_hook(home: Path, tmp_path: Path, monkeypatch) -> tuple[str, str]:
    """The chain through its second run: the lesson moved to a warn hook by
    reconsider R1. Returns (resolution id, R1 id)."""
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    _second_run(home, monkeypatch, resolution_id, _reconsider_of(resolution_id),
                {"version": 1, "items": [_warn_hook_line(RID)]})
    r1 = _case_fm(home, resolution_id).get("superseded_by")
    assert r1 and (_record(home, RID).routing or {}).get("destination") == "hook"
    return resolution_id, r1


def test_a_reconsider_whose_preview_refuses_a_line_is_dropped_at_phase_b(
    tmp_path, monkeypatch, claude_dir
):
    """The gate's risk 2 (probe D): a reconsider rejecting a lesson routed
    to a hook previews "would refuse" (hook and reference routes are
    corrected by hand). It used to be recorded anyway, superseding R1 and
    changing nothing. Now the pair is dropped at phase B, R1 stays open,
    and the drop names the refused line in the report and the journal.
    The positive control is R1 itself: a reconsider whose preview applies
    was recorded and applied (`_moved_to_a_hook`)."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _resolution_id, r1 = _moved_to_a_hook(home, tmp_path, monkeypatch)
    reject = _reconsider_of(r1)
    reject["outcome"] = "reject"
    reject["decision"] = dict(reject["decision"], verb="reject")

    _second_run(home, monkeypatch, r1, reject, {"version": 1, "items": [
        {"id": RID, "verb": "reject", "note": "narrow", "close_call": False},
    ]})

    refused = _refused_section(home)
    assert "case-pkill-hook.yaml: dropped with sheet-pkill-hook.yaml" in refused, refused
    assert f"item 1 (reject {RID}) would be refused" in refused, refused
    assert _case_fm(home, r1).get("superseded_by") is None  # R1 is still open
    record = _record(home, RID)
    assert (record.status, (record.routing or {}).get("destination")) == ("routed", "hook")
    dropped = [row for row in overseer_run.read_journal(home, limit=200)
               if row.get("status") == "pair-dropped"]
    assert any(f"item 1 (reject {RID}) would be refused" in (row.get("reason") or "") for row in dropped), dropped


def test_a_resolution_pair_whose_preview_refuses_a_line_is_still_recorded(tmp_path, monkeypatch, claude_dir):
    """The drop is for reconsider pairs only: run 1 of the chain is a
    resolution whose route previews and applies as refused, and it is
    recorded (the live first decision, `case-5257d97d`)."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    assert _case_fm(home, resolution_id)["supersedes"] == parked_id
    assert "would be refused" not in _refused_section(home)


# -------------- 2026-10-05 fold: a list `supersedes` costs the pair only


def test_a_resolution_naming_a_list_of_cases_is_a_per_pair_drop(tmp_path, decided):
    home, _setup, prior = decided
    listed = _reconsider_of(prior)
    listed.update(kind="resolution", supersedes=[prior])
    with pytest.raises(overseer_run.OverseerError, match="supersedes must name one case id, not a list"):
        overseer_run._validate_successor(_staged(tmp_path, listed), {prior}, home)


def test_a_list_supersedes_does_not_end_the_run(tmp_path, monkeypatch, claude_dir):
    """End to end: the pair is dropped and named, the other pair of the
    run applies, and the parked case it named stays open."""
    from test_failstate_overseer import _two_parked

    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    listed = _successor(rid_a, parked_a)
    listed["supersedes"] = [parked_a]

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-a.yaml", listed)
            _dump(spec.cwd / "sheet-a.yaml", {"version": 1, "items": [{"id": rid_a, "verb": "reject"}]})
            _dump(spec.cwd / "case-b.yaml", _successor(rid_b, parked_b))
            _dump(spec.cwd / "sheet-b.yaml", {"version": 1, "items": [{"id": rid_b, "verb": "reject"}]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    refused = _refused_section(home)
    assert "case-a.yaml: dropped with sheet-a.yaml" in refused, refused
    assert "supersedes must name one case id, not a list" in refused, refused
    assert _record(home, rid_b).status == "rejected", result  # the other pair applied
    assert _record(home, rid_a).status == "pending"
    assert _case_fm(home, parked_a).get("superseded_by") is None


# ------------------- 2026-10-05 fold: tests the blind gate found missing


def test_a_reconsider_with_null_records_is_a_per_pair_drop(tmp_path, decided):
    """Gate nit 4 (its mutation 9 survived): without the records type
    check, `records: null` raised TypeError out of `_validate_successor`,
    which the pair loop does not catch."""
    home, _setup, prior = decided
    for records in (None, 7, RID, [RID, 7]):
        bad = dict(_reconsider_of(prior), records=records)
        with pytest.raises(overseer_run.OverseerError, match="records must be a list of record ids"):
            overseer_run._validate_successor(_staged(tmp_path, bad), set(), home)


def test_a_resolution_naming_a_non_parked_case_drops_with_the_s76_line(
    tmp_path, monkeypatch, claude_dir
):
    """Gate nit 5 (its mutation 7 survived): the drop line the S-76 row
    quotes, end to end, as the literal text."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    plain = dict(_reconsider_of(resolution_id), kind="resolution")

    _second_run(home, monkeypatch, resolution_id, plain, {"version": 1, "items": [_warn_hook_line(RID)]})

    refused = _refused_section(home)
    assert "case-pkill-hook.yaml: dropped with sheet-pkill-hook.yaml" in refused, refused
    assert (
        "supersedes must name a verified parked case (only a kind: reconsider "
        "successor may correct a case that is not parked)"
    ) in refused, refused
    assert _case_fm(home, resolution_id).get("superseded_by") is None


def test_two_reconsiders_of_one_non_parked_case_the_second_is_dropped_alone(
    tmp_path, monkeypatch, claude_dir
):
    """Gate probe B: a case is superseded once. The second reconsider of
    the same non-parked case is dropped ("a second successor for"); the
    first applies."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    hook = {"version": 1, "items": [_warn_hook_line(RID)]}

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            for name in ("a-hook", "b-hook"):
                _dump(spec.cwd / f"case-{name}.yaml", _reconsider_of(resolution_id))
                _dump(spec.cwd / f"sheet-{name}.yaml", hook)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True, manual=True)

    refused = _refused_section(home)
    assert f"case-b-hook.yaml: dropped with sheet-b-hook.yaml — case-b-hook.yaml: a second successor for {resolution_id}" in refused, refused
    assert "case-a-hook.yaml" not in refused, refused
    successors = [row["case"] for row in cases.list_cases(home) if row.get("supersedes") == resolution_id]
    assert successors == [_case_fm(home, resolution_id)["superseded_by"]], successors
    assert (_record(home, RID).routing or {}).get("destination") == "hook"
    assert (result.status, result.decisions_dropped) == ("applied", 1), result


def test_a_reconsider_refused_at_apply_is_itself_corrected_by_a_later_reconsider(
    tmp_path, monkeypatch, claude_dir
):
    """Gate probe C, under this fold's phase-B drop: a line the preview
    passes but apply time refuses (injected here: `verbs.reroute` raises
    at apply) leaves reconsider R1 recorded with its line refused. A later
    run's reconsider naming R1 -- not selected that run -- applies."""
    from self_learn import verbs

    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    _parked_id, resolution_id = _seed_the_chain_up_to_the_refused_resolution(home, tmp_path, monkeypatch)
    real_reroute = verbs.reroute

    def refused_at_apply(*args, **kwargs):
        raise verbs.VerbError("injected: refused at apply time")

    monkeypatch.setattr(verbs, "reroute", refused_at_apply)
    _second_run(home, monkeypatch, resolution_id, _reconsider_of(resolution_id),
                {"version": 1, "items": [_warn_hook_line(RID)]})
    r1 = _case_fm(home, resolution_id).get("superseded_by")
    assert r1 and _case_fm(home, r1)["kind"] == "reconsider"  # R1 was recorded (the preview passed)
    application = cases.show(home, r1, evidence_only=False).sections["Application"]
    assert "route → refused" in application, application
    assert (_record(home, RID).routing or {}).get("destination") == "skill-md"  # nothing changed

    monkeypatch.setattr(verbs, "reroute", real_reroute)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)  # R1 is not selected this run
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-r2.yaml", _reconsider_of(r1))
            _dump(spec.cwd / "sheet-r2.yaml", {"version": 1, "items": [_warn_hook_line(RID)]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True, manual=True)

    r2 = _case_fm(home, r1).get("superseded_by")
    assert r2 and _case_fm(home, r2)["kind"] == "reconsider", _refused_section(home)
    routing = _record(home, RID).routing or {}
    assert routing.get("destination") == "hook" and (routing.get("hook") or {}).get("mode") == "warn"


# ---- the live shape: claude-md, user scope, routed by a person (Sunday's run)

LIVE_RID = "lrn-a5000009"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """`~/.claude` for this test: HOME and SELF_LEARN_CLAUDE_DIR both point
    into tmp_path, so the user CLAUDE.md and the hooks folder are scratch
    (the module's `_real_claude_dir_never_touched` is the control)."""
    home_dir = tmp_path / "fake-home"
    (home_dir / ".claude" / "hooks").mkdir(parents=True)
    (home_dir / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(home_dir / ".claude"))
    return home_dir / ".claude"


def test_the_live_shape_a_human_routed_claude_md_line_moves_to_a_warn_hook(
    tmp_path, monkeypatch, fake_home
):
    """`lrn-19f82fc5` as it is on disk: user scope, routed to the user
    CLAUDE.md `by: human`; the steward parked it as `hook`; an overseer
    resolution's route was refused at apply. A reconsider naming that
    resolution (an overseer case, so the actor guard admits it) moves the
    lesson to a warn hook and retires the always-loaded line."""
    from self_learn import ledger_ops, verbs
    from support import commit_all, make_behavior

    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    user_claude_md = fake_home / "CLAUDE.md"
    ledger_ops.create_record(home, make_behavior(record_id=LIVE_RID, scope="user", trigger=HOOK_TRIGGER))
    commit_all(home, f"seed {LIVE_RID}")
    verbs.route(home, LIVE_RID, dest="claude-md", no_push=True)
    routing = _record(home, LIVE_RID).routing or {}
    assert (routing.get("destination"), routing.get("by")) == ("claude-md", "human"), routing
    assert LIVE_RID in user_claude_md.read_text(encoding="utf-8")  # control: the line is loaded

    setup = tmp_path / "setup"
    setup.mkdir()
    parked = _case([LIVE_RID], "parked", "route", scope="user")
    parked.update(kind="parked", parked_for="overseer", parked_reason="hook")
    parked_id = _record_case(home, setup, parked)
    first = _successor(LIVE_RID, parked_id)
    first.update(outcome="route", scope="user")
    first["decision"]["verb"] = "route"
    line = _warn_hook_line(LIVE_RID)

    def invoke_first(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-pkill-hook.yaml", first)
            _dump(spec.cwd / "sheet-pkill-hook.yaml", {"version": 1, "items": [line]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke_first)
    overseer_run.run(home, no_push=True)
    resolution_id = _case_fm(home, parked_id).get("superseded_by")
    assert resolution_id and _case_fm(home, resolution_id)["actor"] == "overseer"
    application = cases.show(home, resolution_id, evidence_only=False).sections["Application"]
    assert "route → refused" in application, application

    reconsider = _reconsider_of(resolution_id)
    reconsider.update(records=[LIVE_RID])
    reconsider["evidence"] = [{"ref": f"record:{LIVE_RID}", "quote": "status: routed"}]
    _second_run(home, monkeypatch, resolution_id, reconsider, {"version": 1, "items": [line]})

    refused = _refused_section(home)
    assert "dropped" not in refused, refused
    reconsider_id = _case_fm(home, resolution_id).get("superseded_by")
    assert reconsider_id and _case_fm(home, reconsider_id)["kind"] == "reconsider", refused
    record = _record(home, LIVE_RID)
    routing = record.routing or {}
    assert (record.status, routing.get("destination"), routing.get("by")) == ("routed", "hook", "overseer")
    assert (routing.get("hook") or {}).get("mode") == "warn"
    assert LIVE_RID not in user_claude_md.read_text(encoding="utf-8")  # the always-loaded line retired
    assert (fake_home / "hooks" / script_name(LIVE_RID, HOOK_TRIGGER)).is_symlink()  # placed
    assert not (fake_home / "settings.json").exists()  # never registered: activation is off
    entry = next(h for h in reversed(record.history) if h.get("event") == "hook-activated")
    assert "switched off" in (entry.get("note") or "")
