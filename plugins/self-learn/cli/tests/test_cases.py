"""U2 · Decision-case store (`02-schema.md` §3a.2, S-65).

Mutation checks pinned here (each recorded red-then-green in the U2
report): (a) freeze-hash tamper detection, (b) `provisional` covering
rule, (d) `receipt` not-attempted tail, (e) index rebuild == incremental,
(f) the evidence-only view is blind.
"""

from __future__ import annotations

import json

import pytest

from self_learn import cases, user_model, worker
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


def _write_stage(tmp_path, overrides=None, **kw) -> "Path":  # noqa: F821
    import copy

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
    from ruamel.yaml import YAML

    y = YAML(typ="safe")
    y.default_flow_style = False
    import io

    buf = io.StringIO()
    y.dump(data, buf)
    stage.write_text(buf.getvalue(), encoding="utf-8")
    return stage


def _record(tmp_path, home, *, actor="steward", **kw) -> str:
    stage = _write_stage(tmp_path, **kw)
    return cases.record(home, stage, actor=actor)


# ---------------------------------------------------------------- basics


def test_record_creates_cases_dir_on_demand(tmp_path):
    """U1 gate hand-off: `make_home` never creates `cases/` — the FIRST
    write path must create it (and its month subdir) itself, never
    refuse."""
    home = make_home(tmp_path)
    assert not (home / "cases").exists()
    case_id = _record(tmp_path, home)
    assert cases.CASE_ID_RE.match(case_id)
    assert (home / "cases").is_dir()
    month_dirs = list((home / "cases").iterdir())
    assert len(month_dirs) == 1
    assert (month_dirs[0] / f"{case_id}.md").is_file()


def test_record_rejects_unknown_closed_set_values(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseUsageError):
        _record(tmp_path, home, kind="not-a-kind")
    with pytest.raises(cases.CaseUsageError):
        _record(tmp_path, home, actor="reviewer")
    with pytest.raises(cases.CaseUsageError):
        _record(tmp_path, home, outcome="maybe")


def test_record_parked_requires_overseer_and_reason(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseError):
        _record(
            tmp_path, home, kind="parked", outcome="parked",
            overrides={"parked_for": "human", "parked_reason": "hook"},
        )
    case_id = _record(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "hook"},
    )
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["parked_reason"] == "hook"


def test_record_secret_scan_refuses_evidence_quote(tmp_path):
    home = make_home(tmp_path)
    token = "ghp_" + "Ab1" * 12
    with pytest.raises(cases.CaseError):
        _record(
            tmp_path, home,
            overrides={"evidence": [{"ref": "transcript:x#L1", "quote": token}]},
        )
    # nothing written
    assert not (home / "cases").exists() or not list((home / "cases").glob("*/case-*.md"))


def test_supersedes_sets_superseded_by_on_the_target(tmp_path):
    home = make_home(tmp_path)
    parked = _record(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "authority-unclear"},
    )
    successor = _record(
        tmp_path, home, actor="overseer", kind="resolution", outcome="reject",
        overrides={"supersedes": parked},
    )
    parked_view = cases.show(home, parked, evidence_only=False)
    assert parked_view.frontmatter["superseded_by"] == successor
    # double supersession refused
    with pytest.raises(cases.CaseError):
        _record(tmp_path, home, actor="overseer", overrides={"supersedes": parked})


# ------------------------------------------------------- (a) freeze hash


def test_a_tamper_after_commit_refuses_observe(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    path = home / "cases"
    path = next(path.glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    # flip one byte inside section 3 (Decision), well inside the frozen span
    tampered = text.replace("settled", "settleD")
    assert tampered != text
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(cases.CaseError):
        cases.observe(home, case_id, "examined", text="checking", by="overseer")
    with pytest.raises(cases.CaseError):
        cases.show(home, case_id, evidence_only=False)


# --------------------------------------------------------- (b) provisional


def test_b_provisional_clears_on_decision_or_all_covering_any_outcome(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is True

    cases.observe(
        home, case_id, "presented", text="shown", by="steward",
        to="human", covering="decision", outcome="noted",
    )
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is False


def test_b_covering_all_also_clears_provisional(tmp_path):
    """`covering: all` is the other member of the spec's decision/all
    pair (02-schema.md §3a.2) — a mutation that narrows the index's
    clearing check to `covering == "decision"` only (dropping `all`)
    must go red here; `test_b_provisional_clears_on_decision_or_all_…`
    above only exercises `decision` and would not catch that narrowing
    alone."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    cases.observe(
        home, case_id, "presented", text="shown in full", by="steward",
        to="human", covering="all", outcome="agreed",
    )
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is False


def test_b_dependencies_covering_leaves_it_provisional(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    cases.observe(
        home, case_id, "presented", text="deps only", by="steward",
        to="human", covering="dependencies", outcome="noted",
    )
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is True, (
        "plan-steward-2026-09-12.md §U2's mutation (b) says the flag "
        "flips 'only on an affirmed presentation covering decision' — "
        "the APPLIED SPEC (02-schema.md §3a.2) says ANY outcome clears "
        "it when covering is decision/all, and a covering:dependencies "
        "presentation must leave the case provisional. Followed here."
    )


def test_b_human_case_is_never_provisional(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, actor="human")
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is False


# ----------------------------------------------------------- (d) receipt


def _batch_result(stopped_at):
    return {
        "sheet": "01.yaml",
        "stopped_at": stopped_at,
        "code": 6,
        "items": [
            {"n": 1, "id": "lrn-08ed825b", "verb": "reject", "state": "applied", "rc": 0},
            {"n": 2, "id": "lrn-e8b13ee8", "verb": "defer", "state": "refused", "rc": 1},
            {"n": 3, "id": "lrn-aaaaaaaa", "verb": "route"},
            {"n": 4, "id": "lrn-bbbbbbbb", "verb": "reject"},
            {"n": 5, "id": "lrn-cccccccc", "verb": "retire"},
        ],
    }


def test_d_receipt_not_attempted_after_stopped_at(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    cases.receipt(home, case_id, _batch_result(2), by="human")
    view = cases.show(home, case_id, evidence_only=False)
    app = view.sections["Application"]
    assert app.count("not-attempted") == 3
    assert app.count("applied (exit 0)") == 1
    assert app.count("refused (exit 1)") == 1


# ------------------------------------------------------------- (e) index


def test_e_rebuild_equals_incremental_byte_for_byte(tmp_path):
    home = make_home(tmp_path)
    c1 = _record(tmp_path, home)
    c2 = _record(tmp_path, home, actor="human")
    cases.observe(home, c1, "examined", text="looked at it", by="steward")

    cache_dir = worker.cache_dir(home)
    incremental_bytes = cases._index_path(cache_dir).read_bytes()

    rebuilt_path = cases.rebuild_index(cache_dir, home)
    rebuilt_bytes = rebuilt_path.read_bytes()

    assert incremental_bytes == rebuilt_bytes
    assert json.loads(rebuilt_bytes)["cases"][0]["case"] in (c1, c2)


# --------------------------------------------------------------- (f) blind


def test_f_full_view_carries_outcome_and_decision_positive_control(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, overrides={"decision.because": "NONCE-NOT-TO-LEAK-8f3f"})
    full = cases.show(home, case_id, evidence_only=False)
    assert full.frontmatter["outcome"] == "reject"
    assert "Decision" in full.sections
    assert "NONCE-NOT-TO-LEAK-8f3f" in full.sections["Decision"]
    assert "Application" in full.sections


def test_f_evidence_only_view_is_blind(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, overrides={"decision.because": "NONCE-NOT-TO-LEAK-8f3f"})
    blind = cases.show(home, case_id, evidence_only=True)
    assert "outcome" not in blind.frontmatter
    assert "superseded_by" not in blind.frontmatter
    assert "parked_for" not in blind.frontmatter
    assert "parked_reason" not in blind.frontmatter
    assert "Decision" not in blind.sections
    assert "Application" not in blind.sections
    assert "Later observations" not in blind.sections
    assert "Identity and scope" in blind.sections
    assert "Evidence" in blind.sections
    assert "Dependencies" in blind.sections
    # the nonce lives only in section 3 — never leaks into the blind view
    assert "NONCE-NOT-TO-LEAK-8f3f" not in json.dumps(blind.to_json())


def test_f_evidence_only_is_the_cli_default_flag_behavior(tmp_path):
    """`case show <id>` with NO flag is the FULL view; `--evidence-only`
    is what's blind — `show()`'s own keyword default (`evidence_only=True`)
    matches the brief's Python signature, but the CLI passes
    `args.evidence_only` (argparse default `False` for a `store_true`
    flag) so the no-flag CLI invocation is full, matching 02-schema.md
    §3a.2's "`case show` (no flag) is the full view, everything" —
    the brief's own acceptance line #1 ("`case show` is blind by
    default") and the spec disagree here; the spec wins (see report)."""
    from self_learn import cli

    home = make_home(tmp_path)
    case_id = _record(tmp_path, home, overrides={"decision.because": "NONCE-CLI-8f3f"})
    parser = cli._build_parser()
    args_no_flag = parser.parse_args(["case", "show", case_id])
    assert args_no_flag.evidence_only is False
    args_flag = parser.parse_args(["case", "show", case_id, "--evidence-only"])
    assert args_flag.evidence_only is True


# -------------------------------------------------- observe -> user_model


def test_observe_presented_with_entries_threads_into_user_model(tmp_path):
    """`case observe --kind presented --entries um-...` calls
    `user_model.mark_seen` for each named entry — the case file and
    user-model.md land as two separate commits inside one held lock
    (see `cases.observe`'s own docstring)."""
    home = make_home(tmp_path)
    um_id = user_model.add_entry(
        home, container="C", title="a reading", because="because text",
        source="system-reading", by="steward", ref="case-00000000",
        statements=["stmt-11112222"],
    )
    case_id = _record(tmp_path, home)
    cases.observe(
        home, case_id, "presented", text="shown with the reading",
        by="steward", to="human", covering="all", entries=[um_id],
        outcome="agreed",
    )
    doc = user_model.show(home)
    assert not any(e["id"] == um_id for e in doc["containers"]["C"])
    seen = [e for e in doc["containers"]["B"] if e["id"] == um_id]
    assert seen and seen[0]["provisional"] is False


def test_observe_presented_with_no_entries_flips_nothing(tmp_path):
    home = make_home(tmp_path)
    um_id = user_model.add_entry(
        home, container="C", title="untouched reading", because="because text",
        source="system-reading", by="steward", ref="case-00000000",
        statements=["stmt-11112222"],
    )
    case_id = _record(tmp_path, home)
    cases.observe(
        home, case_id, "presented", text="shown without naming any entry",
        by="steward", to="human", covering="decision", entries=[],
        outcome="agreed",
    )
    doc = user_model.show(home)
    still_there = [e for e in doc["containers"]["C"] if e["id"] == um_id]
    assert still_there and still_there[0]["provisional"] is True


# ------------------------------------------------------------ list/filter


def test_list_filters_by_record_and_parked_reason(tmp_path):
    home = make_home(tmp_path)
    c1 = _record(tmp_path, home, overrides={"records": ["lrn-11111111"]})
    c2 = _record(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={
            "records": ["lrn-22222222"],
            "parked_for": "overseer",
            "parked_reason": "hook",
        },
    )
    only_c1 = cases.list_cases(home, record_id="lrn-11111111")
    assert [r["case"] for r in only_c1] == [c1]
    only_parked = cases.list_cases(home, parked_reason="hook")
    assert [r["case"] for r in only_parked] == [c2]
