"""U9 (code half) — `steward_prompt.py`: packet assembly, §4.1's seven
blocks in order, evidence before advice, the withheld list.

Every test relies on the suite-wide autouse `SELF_LEARN_HOME`/
`XDG_CACHE_HOME`/`XDG_CONFIG_HOME`/`SELF_LEARN_CLAUDE_DIR` sandboxing in
`conftest.py`."""

from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, steward_prompt, user_model
from support import make_home

STAGE_BASE = {
    "kind": "resolution",
    "trigger": "nightly",
    "outcome": "reject",
    "records": ["lrn-08ed825b"],
    "scope": "project:~/.config",
    "question": "should this become a standing rule?",
    "evidence": [
        {"ref": "transcript:9c1e#L2210", "quote": "push to where?"},
    ],
    "decision": {
        "verb": "reject",
        "because": "the standing order is about the hypr subrepo",
        "confidence": "settled",
    },
}


def _write_stage(tmp_path, overrides=None, **kw) -> Path:
    data = copy.deepcopy(STAGE_BASE)
    data.update(kw)
    if overrides:
        for path, value in overrides.items():
            obj = data
            keys = path.split(".")
            for k in keys[:-1]:
                obj = obj[k]
            obj[keys[-1]] = value
    stage = tmp_path / f"stage-{len(list(tmp_path.glob('stage-*.yaml')))}.yaml"
    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    stage.write_text(buf.getvalue(), encoding="utf-8")
    return stage


def _record_case(tmp_path, home, *, actor="steward", **kw) -> str:
    stage = _write_stage(tmp_path, **kw)
    return cases.record(home, stage, actor=actor)


def _run(tmp_path, **overrides) -> steward_prompt.RunContext:
    kw = dict(
        run_id="run-test1",
        stage_dir=tmp_path / "stage",
        packet_index=1,
        packet_count=1,
        last_run_at=None,
        verbs_the_runner_executes=("case record", "batch"),
    )
    kw.update(overrides)
    return steward_prompt.RunContext(**kw)


FULL_PROPOSAL_CARD = {
    "headline": "What this is about.",
    "provenance": "September 14th, U9.",
    "impact": "next time this fires, behavior changes.",
    "already_kept": "not found elsewhere.",
    "evidence": "the record body quote (evidence text).",
    "questions": "none",
    "discuss": "nothing contentious.",
    "lint": "a fresh session would catch this.",
    "conflict": "may clash with an existing rule.",
    "advice": "route to skill-md (advice text).",
}


def _proposal(record_id="lrn-aa00beef", **card_overrides):
    card = dict(FULL_PROPOSAL_CARD)
    card.update(card_overrides)
    return {"id": record_id, "recommendation": "route", "card": card}


def _block_offsets(text: str) -> dict:
    return {name: text.index(f"=== {name} ===") for name in steward_prompt._BLOCK_ORDER}


# ------------------------------------------------------- test 1: order


def test_block_order_by_offset(tmp_path):
    home = make_home(tmp_path)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal()])

    assert [name for name, _ in packet.blocks] == list(steward_prompt._BLOCK_ORDER)
    offsets = _block_offsets(packet.text)
    ordered = [offsets[n] for n in steward_prompt._BLOCK_ORDER]
    assert ordered == sorted(ordered)

    # For every brief, evidence offset < advice offset.
    briefs_text = dict(packet.blocks)["briefs"]
    ev = briefs_text.index("[evidence]")
    ad = briefs_text.index("[advice]")
    assert ev < ad


def test_mutation_swapped_blocks_fails_the_offset_check(tmp_path, monkeypatch):
    """Mutation for test 1: swap two blocks via `_ordered_blocks` (the
    one seam `assemble` calls) and confirm the SAME offset check the
    previous test used now fails -- proving that check is not vacuous."""
    home = make_home(tmp_path)
    run = _run(tmp_path)

    real = steward_prompt._ordered_blocks

    def _swapped(home, run, proposals, items):
        blocks = list(real(home, run, proposals, items))
        # swap user_model (idx 2) and conditions (idx 3)
        blocks[2], blocks[3] = blocks[3], blocks[2]
        return tuple(blocks)

    monkeypatch.setattr(steward_prompt, "_ordered_blocks", _swapped)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal()])
    offsets = _block_offsets(packet.text)
    ordered = [offsets[n] for n in steward_prompt._BLOCK_ORDER]
    assert ordered != sorted(ordered)  # RED under the mutation


# ------------------------------------------ test 2: registry order wins


def test_brief_evidence_before_advice_even_if_card_dict_lists_advice_first(tmp_path):
    home = make_home(tmp_path)
    run = _run(tmp_path)
    # Dict insertion order: advice BEFORE evidence -- the point is that
    # render_brief's REGISTRY order wins, never the dict's own order.
    card = {"advice": "advice text.", "evidence": "evidence text."}
    proposal = {"id": "lrn-aa00cafe", "recommendation": "route", "card": card}

    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [proposal])
    briefs_text = dict(packet.blocks)["briefs"]
    assert briefs_text.index("[evidence]") < briefs_text.index("[advice]")


def test_mutation_bypassing_render_brief_with_dict_order_fails(tmp_path, monkeypatch):
    """Mutation for test 2: replace `worker.render_brief` (as
    `steward_prompt` sees it) with a dict-order-preserving stand-in and
    confirm the ordering the previous test pins now fails."""
    home = make_home(tmp_path)
    run = _run(tmp_path)
    card = {"advice": "advice text.", "evidence": "evidence text."}
    proposal = {"id": "lrn-aa00cafe", "recommendation": "route", "card": card}

    def _dict_order_brief(proposal):
        return list(proposal.get("card", {}).items())

    monkeypatch.setattr(steward_prompt.worker, "render_brief", _dict_order_brief)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [proposal])
    briefs_text = dict(packet.blocks)["briefs"]
    assert briefs_text.index("[advice]") < briefs_text.index("[evidence]")  # RED


# --------------------------------------------- test 3: CURRENT/LAPSED


def test_user_model_lapsed_a_entry_renders_after_current_d_entry(tmp_path):
    home = make_home(tmp_path)
    a_id = user_model.add_entry(
        home, container="A", title="own words test", because="test",
        source="own-words", by="human", ref="stmt-test-a",
    )
    user_model.lapse_entry(
        home, a_id, changed_condition="report.destinations", by="human"
    )
    d_id = user_model.add_entry(
        home, container="D", title="observed regularity", because="test",
        source="system-reading", by="overseer", ref="case-test1",
    )
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal()])
    um_text = dict(packet.blocks)["user_model"]

    assert d_id in um_text and a_id in um_text
    assert um_text.index(d_id) < um_text.index(a_id)
    assert "LAPSED" in um_text
    assert "changed_condition: report.destinations" in um_text


def test_mutation_dropping_current_lapsed_split_fails(tmp_path, monkeypatch):
    """Mutation for test 3: render containers in fixed order WITHOUT
    splitting CURRENT before LAPSED -- since A precedes D in
    `_USER_MODEL_CONTAINER_ORDER`, A's LAPSED entry would then render
    BEFORE D's CURRENT entry, the opposite of the previous test's pin."""
    home = make_home(tmp_path)
    a_id = user_model.add_entry(
        home, container="A", title="own words test", because="test",
        source="own-words", by="human", ref="stmt-test-a",
    )
    user_model.lapse_entry(
        home, a_id, changed_condition="report.destinations", by="human"
    )
    d_id = user_model.add_entry(
        home, container="D", title="observed regularity", because="test",
        source="system-reading", by="overseer", ref="case-test1",
    )

    def _no_split_render_user_model(home):
        containers = user_model.show(home)["containers"]
        rendered = []
        for letter in steward_prompt._USER_MODEL_CONTAINER_ORDER:
            for entry in containers.get(letter, []):
                rendered.append(
                    steward_prompt._render_user_model_entry(letter, entry)
                )
        return "\n\n".join(rendered)

    monkeypatch.setattr(
        steward_prompt, "_render_user_model", _no_split_render_user_model
    )
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal()])
    um_text = dict(packet.blocks)["user_model"]
    assert um_text.index(a_id) < um_text.index(d_id)  # RED: A-lapsed now first


# ------------------------------------------------ test 4: open cases


def test_open_cases_excludes_tampered_and_shows_intact(tmp_path):
    home = make_home(tmp_path)
    intact_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    tampered_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "hook"},
    )
    path = next((home / "cases").glob(f"*/{tampered_id}.md"))
    text = path.read_text(encoding="utf-8")
    tampered = text.replace("settled", "settleD")
    assert tampered != text
    path.write_text(tampered, encoding="utf-8")

    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    open_cases_text = dict(packet.blocks)["open_cases"]

    assert intact_id in open_cases_text
    assert tampered_id not in open_cases_text
    assert "1 cases excluded: freeze hash mismatch" in open_cases_text


def test_mutation_including_tampered_rows_fails_the_exclusion_check(tmp_path, monkeypatch):
    """Mutation for test 4: stop filtering by `frozen_ok` (the
    `only_ok=False`-shaped bug the brief names) and confirm the
    tampered case now surfaces (as an 'unavailable' stub, since
    `cases.show` itself still refuses a bad hash) where the previous
    test asserts it does not."""
    home = make_home(tmp_path)
    intact_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    tampered_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "hook"},
    )
    path = next((home / "cases").glob(f"*/{tampered_id}.md"))
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("settled", "settleD"), encoding="utf-8")

    def _unfiltered_open_cases(home, run):
        all_rows = cases.list_cases(home, parked_for="overseer", only_ok=False)
        blocks = []
        for row in all_rows:  # BUG: no frozen_ok filter at all
            case_id = row["case"]
            try:
                view = cases.show(home, case_id)
            except cases.CaseError as exc:
                blocks.append(f"case {case_id}: unavailable ({exc})")
                continue
            blocks.append(view.to_text())
        return "\n\n".join(blocks)

    monkeypatch.setattr(steward_prompt, "_render_open_cases", _unfiltered_open_cases)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    open_cases_text = dict(packet.blocks)["open_cases"]
    assert intact_id in open_cases_text
    assert tampered_id in open_cases_text  # RED: the tampered case now surfaces


# ------------------------------------------------------- test 8: withheld


def test_withheld_names_the_digest_and_transcript_text():
    items = steward_prompt.withheld()
    assert any("_digest" in s for s in items)
    assert any("transcript" in s.lower() for s in items)


def test_mutation_dropping_one_withheld_entry_fails(monkeypatch):
    real = steward_prompt.withheld

    def _missing_transcript_entry():
        return tuple(s for s in real() if "transcript" not in s.lower())

    monkeypatch.setattr(steward_prompt, "withheld", _missing_transcript_entry)
    items = steward_prompt.withheld()
    assert not any("transcript" in s.lower() for s in items)  # RED


# --------------------------------------------- own mutation (blind view)


def test_open_cases_blind_view_never_leaks_outcome_or_decision_section(tmp_path):
    home = make_home(tmp_path)
    case_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    open_cases_text = dict(packet.blocks)["open_cases"]
    assert case_id in open_cases_text  # positive control: the case IS shown
    assert "outcome: parked" not in open_cases_text
    assert "verb: reject" not in open_cases_text  # section 3 (Decision) content


def test_mutation_full_view_in_open_cases_leaks_decision_section(tmp_path, monkeypatch):
    """Own extra mutation (brief: at least one of the builder's own
    choosing) -- the behaviour least protected by the brief's own eight
    named tests is the BLIND default itself: flip `cases.show`'s
    `evidence_only` to False inside `_render_open_cases` and confirm
    `outcome:`/the Decision section's own text now leaks -- proving the
    blind default in the shipped code is load-bearing, not incidental."""
    home = make_home(tmp_path)
    case_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )

    def _full_view_open_cases(home, run):
        rows = cases.list_cases(home, parked_for="overseer", only_ok=True)
        blocks = []
        for row in rows:
            view = cases.show(home, row["case"], evidence_only=False)  # BUG
            blocks.append(view.to_text())
        return "\n\n".join(blocks)

    monkeypatch.setattr(steward_prompt, "_render_open_cases", _full_view_open_cases)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    open_cases_text = dict(packet.blocks)["open_cases"]
    assert case_id in open_cases_text
    assert "outcome: parked" in open_cases_text  # RED: section leaked


# --------------------------------------------------------- smoke tests


def test_output_contract_is_a_module_constant_dict():
    assert isinstance(steward_prompt.OUTPUT_CONTRACT, dict)
    for name in (
        "cases/*.yaml", "sheets/*.yaml", "parked.yaml", "revisions.yaml",
        "model-updates.yaml", "statements.yaml",
    ):
        assert name in steward_prompt.OUTPUT_CONTRACT


def test_assemble_never_touches_hosts_or_settings_directly(tmp_path, monkeypatch):
    """assemble() reads hosts/settings ONLY through conditions.feed --
    poisoning hosts.load_hosts/settings.resolve_setting at the
    steward_prompt module's own bound names (which don't exist, since
    it never imports them) would be a false test; instead this asserts
    the module has no such names bound at all."""
    assert not hasattr(steward_prompt, "load_hosts")
    assert not hasattr(steward_prompt, "resolve_setting")


def test_assemble_with_empty_home_does_not_raise(tmp_path):
    home = make_home(tmp_path)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    assert packet.text
    assert packet.withheld == steward_prompt.withheld()
