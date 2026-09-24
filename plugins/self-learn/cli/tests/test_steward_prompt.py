"""U9 (code half) — `steward_prompt.py`: packet assembly, §4.1's seven
blocks in order, evidence before advice, the withheld list.

Every test relies on the suite-wide autouse `SELF_LEARN_HOME`/
`XDG_CACHE_HOME`/`XDG_CONFIG_HOME`/`SELF_LEARN_CLAUDE_DIR` sandboxing in
`conftest.py`.

N5 (fold r1): the `test_negative_control_*` functions below monkeypatch
a BROKEN implementation and assert the mutated, wrong behaviour -- they
permanently document a defect shape for a future reader, they do not
guard against a regression the way every other test here does. Do not
read a green `test_negative_control_*` as coverage of the real code
path; the real guard is the un-prefixed test right above each one."""

from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, conditions, steward_prompt, user_model
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


def test_negative_control_swapped_blocks_fails_the_offset_check(tmp_path, monkeypatch):
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


def test_negative_control_bypassing_render_brief_with_dict_order_fails(tmp_path, monkeypatch):
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


def test_negative_control_dropping_current_lapsed_split_fails(tmp_path, monkeypatch):
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


def test_negative_control_including_tampered_rows_fails_the_exclusion_check(tmp_path, monkeypatch):
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


def test_negative_control_dropping_one_withheld_entry_fails(monkeypatch):
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


def test_negative_control_full_view_in_open_cases_leaks_decision_section(tmp_path, monkeypatch):
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


# ------------------------------------------------ fold r1: S1 (since filter)


def _tamper_observation_timestamp(home: Path, case_id: str, marker: str, new_ts: str) -> None:
    """Rewrite one "Later observations" bullet's timestamp in place, the
    same technique the gate probe used (gate-u9-r1-probe.py.txt P4):
    section 6 is append-only and NOT covered by the frozen-sections hash
    (`_hash_frozen` only spans sections 1-4), so this never trips a
    tamper/`frozen_ok` check."""
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    out = []
    for ln in text.splitlines():
        if ln.startswith("- obs-") and marker in ln:
            parts = ln.split()
            parts[2] = new_ts
            ln = " ".join(parts)
        out.append(ln)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def test_later_observations_since_filter_only_renders_newer_entries(tmp_path):
    home = make_home(tmp_path)
    case_id = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    cases.observe(home, case_id, "examined", text="OLD-OBSERVATION-S1", by="human")
    cases.observe(home, case_id, "examined", text="NEW-OBSERVATION-S1", by="human")
    _tamper_observation_timestamp(home, case_id, "OLD-OBSERVATION-S1", "2026-09-01T00:00:00Z")
    _tamper_observation_timestamp(home, case_id, "NEW-OBSERVATION-S1", "2026-09-10T00:00:00Z")

    run = _run(tmp_path, last_run_at="2026-09-05T00:00:00Z")
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    oc = dict(packet.blocks)["open_cases"]
    assert "NEW-OBSERVATION-S1" in oc
    assert "OLD-OBSERVATION-S1" not in oc

    # last_run_at None: no prior run, both render (fail-open for "never").
    run2 = _run(tmp_path)
    packet2 = steward_prompt.assemble(home, tmp_path / "cache", run2, [])
    oc2 = dict(packet2.blocks)["open_cases"]
    assert "NEW-OBSERVATION-S1" in oc2 and "OLD-OBSERVATION-S1" in oc2


# ------------------------------------------------- fold r1: S2 (prior case)


def test_prior_case_for_record_precedes_brief_and_is_blind(tmp_path):
    home = make_home(tmp_path)
    case_id = _record_case(tmp_path, home, records=["lrn-aa00beef"])
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal("lrn-aa00beef")])
    briefs = dict(packet.blocks)["briefs"]
    assert "### prior case for lrn-aa00beef" in briefs
    assert briefs.index("### prior case") < briefs.index("### brief:")
    assert case_id in briefs
    # blind view: no Decision section content
    assert "outcome: reject" not in briefs
    assert "verb: reject" not in briefs


# ------------------------------------------- fold r1: S3 (container order)


def test_user_model_container_order_is_a_b_e_before_c_then_lapsed(tmp_path):
    # Container B is only ever populated by `mark_seen` (`add_entry`
    # refuses a direct B add — §3a.4); this second A-container entry
    # stands in for "A/B" collectively, the same shape the gate probe
    # (P1) used.
    home = make_home(tmp_path)
    a_id = user_model.add_entry(
        home, container="A", title="own words S3", because="x",
        source="own-words", by="human", ref="stmt-a-s3",
    )
    user_model.lapse_entry(home, a_id, changed_condition="report.destinations", by="human")
    b_id = user_model.add_entry(
        home, container="A", title="second own words S3", because="x",
        source="own-words", by="human", ref="stmt-b-s3",
    )
    c_id = user_model.add_entry(
        home, container="C", title="provisional reading S3", because="x",
        source="system-reading", by="steward", ref="case-s3",
        statements=["stmt-c-s3"],
    )
    e_id = user_model.add_entry(
        home, container="E", title="declared.some.key.s3: yes", because="x",
        source="own-words", by="human", ref="stmt-e-s3",
    )
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    um = dict(packet.blocks)["user_model"]

    # A, B and E (in that container order) all precede C.
    assert um.index(b_id) < um.index(c_id)
    assert um.index(e_id) < um.index(c_id)
    # the LAPSED A entry renders after every CURRENT entry, including C.
    assert um.index(a_id) > um.index(c_id)
    assert "the user has not yet seen this" in um


# --------------------------------------------------- fold r1: S5 (superseded)


def test_superseded_parked_case_is_not_rendered_only_the_successor_is(tmp_path):
    home = make_home(tmp_path)
    first = _record_case(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    second = _record_case(
        tmp_path, home, kind="parked", outcome="parked", supersedes=first,
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    run = _run(tmp_path)
    oc = dict(steward_prompt.assemble(home, tmp_path / "cache", run, []).blocks)["open_cases"]
    assert f"case: {second}" in oc
    assert f"case: {first}" not in oc


# ------------------------------------ fold r1: S6 (tampered prior case)


def test_tampered_prior_case_is_excluded_with_a_line_not_silently(tmp_path):
    home = make_home(tmp_path)
    case_id = _record_case(tmp_path, home, records=["lrn-aa00beef"])
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    tampered = text.replace("settled", "settleD")
    assert tampered != text
    path.write_text(tampered, encoding="utf-8")

    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal("lrn-aa00beef")])
    briefs = dict(packet.blocks)["briefs"]
    assert case_id not in briefs
    assert "1 prior cases excluded: freeze hash mismatch" in briefs


def test_negative_control_dropping_the_prior_case_exclusion_line_fails(tmp_path, monkeypatch):
    """Mutation for S6: restore the pre-fold behaviour (`only_ok=True`,
    no exclusion count at all) and confirm the previous test's positive
    assertion -- the exclusion line's presence -- now fails."""
    home = make_home(tmp_path)
    case_id = _record_case(tmp_path, home, records=["lrn-aa00beef"])
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("settled", "settleD"), encoding="utf-8")

    def _no_exclusion_line(home, record_id):
        if not record_id:
            return [], 0
        return cases.list_cases(home, record_id=record_id, only_ok=True), 0

    monkeypatch.setattr(steward_prompt, "_existing_cases_for_record", _no_exclusion_line)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [_proposal("lrn-aa00beef")])
    briefs = dict(packet.blocks)["briefs"]
    assert "prior cases excluded" not in briefs  # RED: the count is gone


# --------------------------------------------------- fold r1: S7 (withheld)


def test_withheld_provisional_entries_text_has_no_review_date(tmp_path):
    items = steward_prompt.withheld()
    joined = " ".join(items)
    assert "review date" not in joined.lower()
    assert "review_by" not in joined.lower() or "no review_by" in joined.lower()
    assert "has not yet seen" in joined.lower()


def test_negative_control_reintroducing_a_review_date_phrase_is_caught(monkeypatch):
    real = steward_prompt.withheld

    def _with_review_date():
        items = list(real())
        items[2] = items[2].replace(
            "the user has not yet seen -- there is no review_by field and no expiry",
            "with a review date",
        )
        return tuple(items)

    monkeypatch.setattr(steward_prompt, "withheld", _with_review_date)
    joined = " ".join(steward_prompt.withheld())
    assert "review date" in joined.lower()  # RED under the mutation


# --------------------------------------------------------- fold r1: N3


def test_conditions_table_escapes_pipe_and_newline_in_a_cell(tmp_path):
    home = make_home(tmp_path)
    items = conditions.feed(home)
    poisoned = conditions.Item(
        "test.poison", "a|value\nwith a newline", "2026-01-01T00:00:00Z", "src|with|pipes"
    )
    table = steward_prompt._render_conditions(items + [poisoned])
    lines = table.splitlines()
    # header + separator + one row per item -- the poisoned item's `|`
    # and `\n` must not have split it across rows or columns.
    assert len(lines) == 2 + len(items) + 1
    assert any("a\\|value\\nwith a newline" in ln and "src\\|with\\|pipes" in ln for ln in lines)


# --------------------------------------------------------- fold r1: N4


def test_render_briefs_preserves_the_callers_proposal_order(tmp_path):
    home = make_home(tmp_path)
    run = _run(tmp_path)
    packet = steward_prompt.assemble(
        home, tmp_path / "cache", run,
        [_proposal("lrn-bb00beef"), _proposal("lrn-aa00beef")],
    )
    briefs = dict(packet.blocks)["briefs"]
    # caller order (bb before aa), never re-sorted (e.g. alphabetically).
    assert briefs.index("### brief: lrn-bb00beef") < briefs.index("### brief: lrn-aa00beef")


# ---------------- 2026-09-22: what the first real run went looking for


def test_output_contract_states_the_formats_the_first_real_run_went_looking_for():
    """The 2026-09-21 run grepped the source tree for the `covered_by`
    grammar, where a route's rules keys come from, and which status each
    verb needs. The contract now states them, from the same constants the
    verbs read."""
    from self_learn import ledger_ops, records, verbs

    text = steward_prompt._render_output_contract()
    assert "`covered_by` is `<kind>:<name>`" in text
    for kind in records.COVERAGE_KINDS:
        assert f"`{kind}:" in text, kind
    assert "`rules_topic` and `rules_paths`" in text
    assert "WHERE A ROUTE LANDS." in text
    assert "WHAT EACH VERB NEEDS THE LESSON'S STATUS TO BE" in text
    for status in ledger_ops.RESOLVABLE_STATUSES:
        assert status in text
    assert "reopen:" in text and all(s in text for s in verbs.REOPEN_ADMITTED_STATUSES)
    # a negative control on the generator: an invented status is not there
    assert "frobnicated" not in text


def test_method_block_quotes_the_standing_rulings_verbatim_from_the_spec():
    """The same run grepped `docs/specs` five times for "always-loaded".
    The method block now quotes the two rulings' headlines; this checks the
    quotes against the design authority so they can never drift."""
    spec = Path(__file__).resolve().parents[4] / "docs" / "specs" / "self-learn" / "03-decisions.md"
    if not spec.is_file():
        pytest.skip("spec corpus not beside this checkout")
    spec_text = spec.read_text(encoding="utf-8")
    rendered = steward_prompt._render_method()
    assert "STANDING RULINGS YOU WOULD OTHERWISE GO LOOKING FOR" in rendered
    for number, headline in steward_prompt.STANDING_RULINGS:
        assert headline in spec_text, (number, headline)
        assert f"| {number} |" in spec_text, number
        assert headline in rendered, number
    assert "always-loaded-user-scope" in rendered


def test_assemble_uses_the_conditions_items_it_is_given(tmp_path, monkeypatch):
    """A run of several packets builds the feed once and hands it to every
    `assemble`; left out, `assemble` still builds its own."""
    home = make_home(tmp_path)
    run = steward_prompt.RunContext(
        run_id="run-feed0001", stage_dir=tmp_path / "stage", packet_index=1,
        packet_count=2, last_run_at=None, verbs_the_runner_executes=("batch",),
    )
    calls = []
    real_feed = conditions.feed

    def counted(home_, cache_dir=None):
        calls.append(home_)
        return real_feed(home_, cache_dir)

    monkeypatch.setattr(steward_prompt.conditions, "feed", counted)
    given = [conditions.Item("ledger.head", "deadbeefcafe", "2026-09-22T00:00:00Z", "handed in")]

    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [], conditions_items=given)

    assert calls == [], "the feed was not rebuilt"
    assert "deadbeefcafe" in dict(packet.blocks)["conditions"]

    steward_prompt.assemble(home, tmp_path / "cache", run, [])
    assert calls == [home], "positive control: without the argument, assemble builds the feed"


def test_where_a_route_lands_is_what_the_route_verb_really_does(tmp_path, monkeypatch):
    """2026-09-23: the brief said a route's variant comes from the proposal
    and "no sheet key sets or overrides" it, and its example sheet wrote
    `dest: claude-md`. Two real steward sheets then wrote a bare `dest`
    meaning to keep a `local` / `rules` proposal, and both resolved to the
    committed CLAUDE.md (parked only because the host was plain). Each
    sentence the brief now states is checked here against `route` itself,
    so the text cannot drift from the verb again."""
    from self_learn import ledger_ops, verbs
    from support import make_behavior, make_env, proposal_dict

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    sandbox = make_env(tmp_path)
    home, host = sandbox.ledger, sandbox.host
    (host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
    record_id = "lrn-0000de57"
    ledger_ops.create_record(
        home, make_behavior(scope="project", record_id=record_id), project_path=host
    )
    ledger_ops.write_proposal(
        home, record_id,
        proposal_dict(scope="project", destination="claude-md", variant="local"),
    )

    left_out = verbs.route_dry_run(home, record_id)
    bare = verbs.route_dry_run(home, record_id, dest="claude-md")
    spelled = verbs.route_dry_run(home, record_id, dest="claude-md:local")
    # positive control first: the proposal's variant is live at all
    assert (left_out.variant, left_out.target) == ("local", str(host / "CLAUDE.local.md"))
    assert (bare.variant, bare.target) == (None, str(host / "CLAUDE.md"))
    assert spelled.target == str(host / "CLAUDE.local.md")  # the preview reports only the proposal's variant

    text = " ".join(steward_prompt._render_output_contract().split())
    assert "Leave `route`'s `dest` out to take the lesson's proposal exactly as written" in text
    assert "Writing `dest` REPLACES the proposal's whole destination, variant included" in text
    assert "a bare `dest: claude-md` is the host's plain CLAUDE.md" in text
    assert "`claude-md:local`, or `claude-md:rules:<topic>`" in text
    assert "no sheet key sets or overrides them" not in text
    for destination in ledger_ops.PROPOSAL_DESTINATIONS:
        assert destination in text, destination
    # the worked example no longer teaches a bare dest on a route
    assert "dest:" not in steward_prompt.STAGE_EXAMPLES["sheets/shell-quoting.yaml"]
