"""U2 · Decision-case store (`02-schema.md` §3a.2, S-65).

Mutation checks pinned here (each recorded red-then-green in the U2
report): (a) freeze-hash tamper detection, (b) `provisional` covering
rule, (d) `receipt` not-attempted tail, (e) index rebuild == incremental,
(f) the evidence-only view is blind.
"""

from __future__ import annotations

import fcntl
import json
import threading
from pathlib import Path

import pytest

from self_learn import cases, intents, user_model, worker
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
        to="human", covering="decision", outcome="noted", via="cli",
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
        to="human", covering="all", outcome="agreed", via="cli",
    )
    rows = cases.list_cases(home)
    assert rows[0]["provisional"] is False


def test_b_dependencies_covering_leaves_it_provisional(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    cases.observe(
        home, case_id, "presented", text="deps only", by="steward",
        to="human", covering="dependencies", outcome="noted", via="cli",
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
    cases.receipt(home, case_id, _batch_result(2))
    view = cases.show(home, case_id, evidence_only=False)
    app = view.sections["Application"]
    assert app.count("not-attempted") == 3
    assert app.count("applied (exit 0)") == 1
    assert app.count("refused (exit 1)") == 1


# ------------------------------------------------- fold r1 (F1, F8): receipt


def test_fold_r1_f8_zero_item_shape_receipts_one_line(tmp_path):
    """F8: a whole-sheet refusal (the sheet-level preflight STOPPED
    before item 1 ever dispatched, `items: []`) still receipts -- ONE
    line, keyed (sheet_sha, 0), naming the reason. This used to raise
    `gitops.HalfWrittenError` out of a dead 'commit produced nothing'
    guard (gate-u3-r1.md F8, probe5) instead of writing anything."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    result = cases.receipt(home, case_id, {
        "sheet": "x.yaml", "sheet_sha": "deadbeef", "stopped_at": None,
        "code": 6, "stop_message": "a live intent is STOPPED", "items": [],
    })
    assert result == case_id
    view = cases.show(home, case_id, evidence_only=False)
    app = view.sections["Application"]
    assert "refused before item 1: a live intent is STOPPED" in app
    assert "item=" not in app  # F8's zero-item shape carries no item= key


def test_fold_r1_f8_empty_items_is_a_true_no_op_on_rerun(tmp_path):
    """A second call with the SAME sheet_sha and the SAME rendered text
    is a genuine no-op -- no duplicate line, no raise (F8's
    `allow_empty=True` fix)."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    batch_result = {
        "sheet": "x.yaml", "sheet_sha": "deadbeef", "at": "2026-01-01T00:00:00Z",
        "stopped_at": None, "code": 6, "stop_message": "stopped", "items": [],
    }
    cases.receipt(home, case_id, batch_result)
    cases.receipt(home, case_id, batch_result)  # must not raise
    view = cases.show(home, case_id, evidence_only=False)
    app = view.sections["Application"]
    assert app.count("refused before item 1") == 1


def test_fold_r1_f1_keyed_replace_not_append(tmp_path):
    """F1: a re-run of the SAME sheet (same sheet_sha) REPLACES the
    line for each key rather than appending -- a different sheet
    (different sheet_sha) against the same case adds its OWN block."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    run1 = {
        "sheet": "01.yaml", "sheet_sha": "aaaa1111", "stopped_at": None, "code": 0,
        "items": [{"n": 1, "id": "lrn-08ed825b", "verb": "reject", "state": "applied", "rc": 0}],
    }
    cases.receipt(home, case_id, run1)
    run2 = {
        "sheet": "01.yaml", "sheet_sha": "aaaa1111", "stopped_at": None, "code": 0,
        "items": [{"n": 1, "id": "lrn-08ed825b", "verb": "reject", "state": "already-applied", "rc": 0}],
    }
    cases.receipt(home, case_id, run2)
    view = cases.show(home, case_id, evidence_only=False)
    lines = [ln for ln in view.sections["Application"].splitlines() if ln.strip()]
    assert len(lines) == 1  # replaced, not appended
    assert "already-applied" in lines[0]

    # a DIFFERENT sheet (different sheet_sha) against the SAME case adds
    # its own block rather than colliding on item index alone.
    run3 = {
        "sheet": "02.yaml", "sheet_sha": "bbbb2222", "stopped_at": None, "code": 0,
        "items": [{"n": 1, "id": "lrn-e8b13ee8", "verb": "defer", "state": "applied", "rc": 0}],
    }
    cases.receipt(home, case_id, run3)
    view2 = cases.show(home, case_id, evidence_only=False)
    lines2 = [ln for ln in view2.sections["Application"].splitlines() if ln.strip()]
    assert len(lines2) == 2


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
    """`case observe --kind presented --entries um-...` flips each named
    entry via `user_model._mark_seen_locked` — the case file and
    user-model.md land in ONE commit inside one held lock (fold-u2-r1
    item 1 / B1; see `cases.observe`'s own docstring)."""
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
        outcome="agreed", via="cli",
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
        outcome="agreed", via="cli",
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


# ============================================================ fold-u2-r1
#
# New mutation checks pinned here (each recorded red-then-green in the
# U2 round-2 report): (1) B1 validate-before-write on presented entries,
# (2) B2 the newly-covered free-text fields, (3) D-i heading-injection
# refusal + S4's multi-line-quote/literal-marker cases, (4) S6 the
# index's frozen_ok, (5) Astra 6 the stale-index rebuild, (7) Astra 9 no
# phantom case, (8) D-d/D-g/D-h, (9) N5, plus N6's own view label.

_TOKEN = "ghp_" + "Ab1" * 12


# --------------------------------------------------------------- (1) B1


def test_1_b1_unknown_entry_in_presented_refuses_before_any_flip(tmp_path):
    home = make_home(tmp_path)
    good_id = user_model.add_entry(
        home, container="C", title="a reading", because="because text",
        source="system-reading", by="steward", ref="case-00000000",
        statements=["stmt-11112222"],
    )
    case_id = _record(tmp_path, home)
    with pytest.raises(user_model.UserModelUsageError):
        cases.observe(
            home, case_id, "presented", text="shown with two entries",
            by="steward", to="human", covering="all",
            entries=[good_id, "um-dead"], outcome="agreed", via="cli",
        )
    doc = user_model.show(home)
    still_c = next(e for e in doc["containers"]["C"] if e["id"] == good_id)
    assert still_c["provisional"] is True
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"] == []


# --------------------------------------------------------------- (2) B2


@pytest.mark.parametrize("kw", [
    {"overrides": {"scope": _TOKEN}},
    {"overrides": {"decision.verb": _TOKEN}},
    {"overrides": {"decision.covered_by": _TOKEN}},
    {"evidence": [{"ref": _TOKEN, "quote": "fine text"}]},
    {"dependencies": {"statements": [_TOKEN]}},
    {"run_id": _TOKEN},  # gate r2 S6
])
def test_2_b2_record_scans_every_newly_covered_field(tmp_path, kw):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseError):
        _record(tmp_path, home, **kw)
    assert not (home / "cases").exists() or not list((home / "cases").glob("*/case-*.md"))


def test_2_b2_observe_scans_ref(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseError):
        cases.observe(home, case_id, "examined", text="fine text", by="steward", ref=_TOKEN)
    view = cases.show(home, case_id, evidence_only=False)
    assert view.sections["Later observations"] == "(none)"


def test_2_b2_receipt_scans_every_line(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    bad_result = {
        "sheet": "01.yaml", "stopped_at": None, "code": None,
        "items": [{"n": 1, "id": "lrn-08ed825b", "verb": _TOKEN, "state": "applied", "rc": 0}],
    }
    with pytest.raises(cases.CaseError):
        cases.receipt(home, case_id, bad_result)
    view = cases.show(home, case_id, evidence_only=False)
    assert view.sections["Application"] == "(none)"


# ----------------------------------------------------------- (3) D-i/S4


def test_3_di_heading_in_because_refused_at_record(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseError):
        _record(tmp_path, home, overrides={
            "decision.because": "harmless prefix\n\n## Evidence\nLEAKED-REASONING-NONCE",
        })
    assert not (home / "cases").exists() or not list((home / "cases").glob("*/case-*.md"))


def test_3_di_heading_in_examined_observation_refused(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseError):
        cases.observe(
            home, case_id, "examined", text="prefix\n\n## Evidence\nLEAK", by="steward",
        )
    view = cases.show(home, case_id, evidence_only=False)
    assert view.sections["Later observations"] == "(none)"


def test_3_s4_multiline_evidence_quote_roundtrips_byte_exact(tmp_path):
    home = make_home(tmp_path)
    quote = "they wrote:\nline two of the quote\nline three"
    case_id = _record(tmp_path, home, overrides={
        "evidence": [{"ref": "transcript:x#L1", "quote": quote}],
    })
    blind = cases.show(home, case_id, evidence_only=True)
    assert quote in blind.sections["Evidence"]


def test_3_di_because_containing_the_literal_marker_is_refused(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseError):
        _record(tmp_path, home, overrides={
            "decision.because": "sneaky\n\n## Application\nfoo",
        })
    assert not (home / "cases").exists() or not list((home / "cases").glob("*/case-*.md"))


# --------------------------------------------------------------- (4) S6


def test_4_s6_tampered_case_gets_frozen_ok_false_and_is_excluded(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    tampered = text.replace("settled", "settleD")
    assert tampered != text
    path.write_text(tampered, encoding="utf-8")

    cache_dir = worker.cache_dir(home)
    rebuilt = cases.rebuild_index(cache_dir, home)
    rows = json.loads(rebuilt.read_bytes())["cases"]
    row = next(r for r in rows if r["case"] == case_id)
    assert row["frozen_ok"] is False

    ok_rows = cases.list_cases(home, only_ok=True)
    assert not any(r["case"] == case_id for r in ok_rows)
    all_rows = cases.list_cases(home, only_ok=False)
    assert any(r["case"] == case_id for r in all_rows)


# ---------------------------------------------------------- (5) Astra 6


def test_5_astra6_list_cases_rebuilds_when_stale(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    c1 = _record(tmp_path, home)
    cases.list_cases(home)  # index built once, current

    # A write that bypasses the incremental upsert (`_update_index`
    # no-op'd) simulates a restored/copied ledger, or a write from
    # elsewhere the incremental path never saw — item 5's OWN staleness
    # detection (case-file count vs index row count) must still catch it.
    monkeypatch.setattr(cases, "_update_index", lambda home, case_id: None)
    c2 = _record(tmp_path, home)

    rows = cases.list_cases(home)
    assert {r["case"] for r in rows} == {c1, c2}


def test_o1_fold_r1_index_missing_scope_kind_forces_rebuild(tmp_path):
    """O-1 fold r1: `scope_kind`/`record_bucket` are new index-row keys
    (`overseer.population.coverage_update` refuses a row that lacks
    `scope_kind` rather than guessing). An index cached by code from
    BEFORE this fold has the right mtime and the right row count, so
    the two PRE-EXISTING staleness checks (mtime, row count) alone
    would never catch it, and every row would stay `scope_kind`-less
    forever — a real O-3-facing failure, not a hypothetical one."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    cases.list_cases(home)  # index built once, current, WITH scope_kind

    cache_dir = worker.cache_dir(home)
    index_path = cache_dir / "cases" / "index.json"
    data = json.loads(index_path.read_bytes())
    for row in data["cases"]:
        row.pop("scope_kind", None)
        row.pop("record_bucket", None)
    index_path.write_text(json.dumps(data), encoding="utf-8")  # same mtime-or-newer, same row count

    rows = cases.list_cases(home)
    row = next(r for r in rows if r["case"] == case_id)
    assert "scope_kind" in row, "a pre-fold cached index row was trusted forever"


# ---------------------------------------------------------- (7) Astra 9


def test_7_astra9_refused_supersedes_leaves_no_phantom_case(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseUsageError):
        _record(tmp_path, home, overrides={"supersedes": "case-deadbeef"})
    assert not (home / "cases").exists() or not list((home / "cases").glob("*/case-*.md"))


# ------------------------------------------------------ (8) D-d/D-g/D-h


def test_8_dd_case_index_rebuild_cli_verb(tmp_path):
    from self_learn import cli

    parser = cli._build_parser()
    args = parser.parse_args(["case", "index", "--rebuild"])
    assert args.case_command == "index"
    assert args.rebuild is True
    with pytest.raises(SystemExit):
        parser.parse_args(["case", "rebuild-index"])
    with pytest.raises(SystemExit):
        parser.parse_args(["case", "index"])  # --rebuild is required


def test_8_dd_receipt_by_flag_is_gone(tmp_path):
    from self_learn import cli

    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "case", "receipt", "case-11112222", "--from-batch", "x.json", "--by", "human",
        ])
    args = parser.parse_args(["case", "receipt", "case-11112222", "--from-batch", "x.json"])
    assert args.id == "case-11112222"


def test_8_dg_presented_to_other_than_human_is_refused(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseError):
        cases.observe(
            home, case_id, "presented", text="shown", by="steward",
            to="robot", covering="decision", outcome="agreed", via="cli",
        )
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"] == []


def test_8_dg_via_is_a_closed_set(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseUsageError):
        cases.observe(
            home, case_id, "presented", text="shown", by="steward",
            to="human", covering="decision", outcome="agreed", via="carrier-pigeon",
        )
    obs_id = cases.observe(
        home, case_id, "presented", text="shown again", by="steward",
        to="human", covering="decision", outcome="agreed", via="cli",
    )
    assert obs_id


def test_r2_s5_via_is_required_on_a_presented_observation(tmp_path):
    """Gate r2 S5 (settled ruling 3): `via` on a `presented` observation
    used to be checked only for closed-set MEMBERSHIP when given — never
    for PRESENCE. Probe V (the gate's own): a presentation with no
    `--via` at all must now be refused, not merely accepted with
    `via: None`."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseUsageError):
        cases.observe(
            home, case_id, "presented", text="shown", by="steward",
            to="human", covering="decision", outcome="agreed",
        )
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"] == []


def test_8_dh_blind_view_frontmatter_key_set(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    blind = cases.show(home, case_id, evidence_only=True)
    assert set(blind.frontmatter.keys()) == {
        "case", "opened_at", "actor", "kind", "records", "supersedes",
    }


# --------------------------------------------------------------- (9) N5


def test_9_n5_presented_outcome_on_non_presented_kind_is_refused(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    with pytest.raises(cases.CaseUsageError):
        cases.observe(
            home, case_id, "examined", text="looked at it", by="steward",
            outcome="agreed",
        )


# --------------------------------------------------------------- N6


def test_n6_to_text_prints_which_view(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    blind_text = cases.show(home, case_id, evidence_only=True).to_text()
    full_text = cases.show(home, case_id, evidence_only=False).to_text()
    assert "evidence-only" in blind_text.lower()
    assert "full" in full_text.lower()


# ============================================================ gate r2


# --------------------------------------------------------------- S1


def test_r2_s1_receipt_heading_injection_refused(tmp_path):
    """Gate r2 S1: `record`/`observe` refuse a heading-shaped line in
    their free text (D-i); `receipt` scanned its lines (B2) but never
    refused one. The gate's own probe R: a batch item's `verb` embeds a
    `## Later observations` line, forging an append-only entry
    attributed to `human` with a fabricated `obs-` id."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    bad_result = {
        "sheet": "01.yaml", "stopped_at": None, "code": None,
        "items": [{
            "n": 1, "id": "lrn-08ed825b",
            "verb": (
                "reject\n\n## Later observations\n"
                "- obs-deadbeef 2026-01-01T00:00:00Z human examined: FORGED"
            ),
            "state": "applied", "rc": 0,
        }],
    }
    with pytest.raises(cases.CaseError):
        cases.receipt(home, case_id, bad_result)
    view = cases.show(home, case_id, evidence_only=False)
    assert view.sections["Application"] == "(none)"
    assert view.sections["Later observations"] == "(none)"


def test_r2_astra1_locate_headings_refuses_a_seventh_heading_line(tmp_path):
    """Astra r2 finding 1: `_refuse_headings` at write time is only half
    of D-i's guarantee — a reader must not TRUST that every writer went
    through it. A case file hand-edited (or written by a bypassed path)
    to carry a SEVENTH `^## ` line — here a `## Bogus` heading stitched
    into the unfrozen Application span, sections 5-6, so the freeze
    hash over sections 1-4 still verifies and this test exercises the
    heading count, not the hash check — must be refused by every
    reader with a clear error, and must degrade `rebuild_index`'s row
    to `frozen_ok=False` rather than raise past it and hide the whole
    population (S4's guarantee composes with Astra 1's)."""
    home = make_home(tmp_path)
    case_id = _record(tmp_path, home)
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    marker = "## Application\n"
    idx = text.index(marker) + len(marker)
    tampered = text[:idx] + "## Bogus\nforged\n\n" + text[idx:]
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(cases.CaseError, match="expected exactly"):
        cases.show(home, case_id, evidence_only=False)
    with pytest.raises(cases.CaseError, match="expected exactly"):
        cases.observe(home, case_id, "statement", text="x", by="steward")

    cache_dir = worker.cache_dir(home)
    rebuilt = cases.rebuild_index(cache_dir, home)  # must not raise
    rows = json.loads(rebuilt.read_bytes())["cases"]
    assert len(rows) == 1
    assert rows[0]["case"] == case_id
    assert rows[0]["frozen_ok"] is False


# --------------------------------------------------------------- S2


def test_r2_s2_crash_between_case_write_and_user_model_flip_recovers_fully(tmp_path, monkeypatch):
    """Gate r2 S2 / probe A: a crash between `observe`'s two writes used
    to leave the user-model flip permanently stranded, discoverable only
    on the NEXT unrelated write — with the docstring wrongly claiming
    this could never happen. Fixed with an `intents.begin`/`complete`/
    `finish` bracket. `user_model._apply_seen` is made to raise,
    simulating a crash exactly at the boundary the gate's check (a)
    names (case file already written, user-model flip not yet applied);
    `intents.recover(home)` is called directly, per the brief's own
    acceptance text, and must produce a FULLY restored ledger — never a
    flip without its presentation."""
    home = make_home(tmp_path)
    um_id = user_model.add_entry(
        home, container="C", title="a reading", because="because text",
        source="system-reading", by="steward", ref="case-00000000",
        statements=["stmt-11112222"],
    )
    case_id = _record(tmp_path, home)

    real_apply_seen = user_model._apply_seen

    def boom(*a, **kw):
        raise RuntimeError("simulated crash between the case write and the user-model flip")

    monkeypatch.setattr(user_model, "_apply_seen", boom)

    with pytest.raises(RuntimeError):
        cases.observe(
            home, case_id, "presented", text="shown", by="steward",
            to="human", covering="all", entries=[um_id], outcome="agreed",
            via="cli",
        )

    result = intents.recover(home)
    assert result.restored, f"expected a full restore, got {result!r}"

    # fully unpublished: the entry is still provisional, the case has
    # zero presentations.
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"] == []
    doc = user_model.show(home)
    still_c = next(e for e in doc["containers"]["C"] if e["id"] == um_id)
    assert still_c["provisional"] is True

    # a later unrelated mark_seen (the crash injection lifted — this is
    # a NORMAL write, not another crash) must not commit a stray flip
    # left over from the crashed transaction — the ledger is clean, not
    # wedged.
    monkeypatch.setattr(user_model, "_apply_seen", real_apply_seen)
    user_model.mark_seen(home, um_id)
    doc = user_model.show(home)
    seen = next(e for e in doc["containers"]["B"] if e["id"] == um_id)
    assert seen["provisional"] is False
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"] == [], "the crashed presentation must never reappear"


def test_r2_s2_crash_between_successor_and_predecessor_write_recovers_fully(tmp_path, monkeypatch):
    """Gate r2 S2 / Astra 9's crash leg: the same recoverable
    two-file-publication fix, for `record --supersedes`'s successor +
    predecessor pair. A crash after the new successor file lands, before
    the predecessor's `superseded_by` write, is recovered fully — no
    phantom successor readable, the predecessor untouched."""
    home = make_home(tmp_path)
    parked = _record(
        tmp_path, home, kind="parked", outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "hook"},
    )
    parked_path = next((home / "cases").glob(f"*/{parked}.md"))
    real_atomic_write = cases.fsops.atomic_write
    state = {"crashed": False}

    def boom(path, *a, **kw):
        # Fire exactly once — the crash-simulated write, never recovery's
        # OWN later (legitimate) rewrite of `parked_path` back to its
        # original content.
        if not state["crashed"] and Path(path) == parked_path:
            state["crashed"] = True
            raise RuntimeError("simulated crash before the predecessor write")
        return real_atomic_write(path, *a, **kw)

    monkeypatch.setattr(cases.fsops, "atomic_write", boom)

    with pytest.raises(RuntimeError):
        _record(tmp_path, home, actor="overseer", overrides={"supersedes": parked})

    result = intents.recover(home)
    assert result.restored, f"expected a full restore, got {result!r}"

    remaining = {p.stem for p in (home / "cases").glob("*/case-*.md")}
    assert remaining == {parked}, "the phantom successor must be gone, not just uncommitted"
    parked_view = cases.show(home, parked, evidence_only=False)
    assert parked_view.frontmatter["superseded_by"] is None

    # a later unrelated record must see exactly the surviving population
    other = _record(tmp_path, home)
    rows = cases.list_cases(home)
    assert {r["case"] for r in rows} == {parked, other}


# --------------------------------------------------------------- S3


def test_r2_s3_update_index_is_a_full_rebuild_so_a_bypassed_writers_row_self_heals(tmp_path, monkeypatch):
    """Gate r2 S3 / probe C: the old incremental upsert propagated a
    STALE row AND erased `_index_is_stale`'s own signal (rewriting the
    file gave it a newer mtime than every case file, so the count/mtime
    checks never fired again). Reproduces the gate's own sequence:
    writer A's presentation lands with its OWN index update bypassed
    (simulating any writer whose upsert never ran); writer B then writes
    NORMALLY. `_update_index` now always delegates to a full
    `rebuild_index`, so B's own (unbypassed) call picks up A's real
    on-disk state too."""
    home = make_home(tmp_path)
    c1 = _record(tmp_path, home)
    real_update_index = cases._update_index
    monkeypatch.setattr(cases, "_update_index", lambda home, case_id: None)
    cases.observe(
        home, c1, "presented", text="shown", by="steward",
        to="human", covering="decision", outcome="agreed", via="cli",
    )
    monkeypatch.setattr(cases, "_update_index", real_update_index)

    c2 = _record(tmp_path, home)

    rows = cases.list_cases(home)
    row_c1 = next(r for r in rows if r["case"] == c1)
    assert row_c1["provisional"] is False, "A's real presentation must be reflected, not a stale row"
    assert {r["case"] for r in rows} == {c1, c2}


# --------------------------------------------------------------- S4


def test_r2_s4_one_bad_case_never_hides_the_population(tmp_path):
    """Gate r2 S4 / Astra 11: `_index_row` caught only `CaseError` — a
    case whose YAML itself will not parse raised a bare `ruamel.yaml`
    error PAST it, killing the whole rebuild. The gate's own probe X.
    Reproduced with a valid case, a missing-frontmatter case (already
    caught: `CaseError`), and a malformed-YAML case (the new fix, a
    `YAMLError` subclass) — three rows, two flagged, no exception."""
    home = make_home(tmp_path)
    good = _record(tmp_path, home)
    good_path = next((home / "cases").glob(f"*/{good}.md"))
    cases_dir = good_path.parent

    no_fm_path = cases_dir / "case-00000001.md"
    no_fm_path.write_text("not frontmatter at all\n", encoding="utf-8")

    bad_yaml_path = cases_dir / "case-00000002.md"
    bad_yaml_path.write_text("---\ncase: [unclosed\n---\nbody\n", encoding="utf-8")

    cache_dir = worker.cache_dir(home)
    rebuilt = cases.rebuild_index(cache_dir, home)  # must not raise
    rows = json.loads(rebuilt.read_bytes())["cases"]
    assert len(rows) == 3
    flagged = [r for r in rows if r["frozen_ok"] is False]
    assert len(flagged) == 2
    ok_rows = [r for r in rows if r["frozen_ok"] is True]
    assert len(ok_rows) == 1 and ok_rows[0]["case"] == good
    assert {r["case"] for r in flagged} == {"case-00000001", "case-00000002"}

    listed = cases.list_cases(home, only_ok=False)  # must not raise either
    assert len(listed) == 3


def test_r2_s4_non_utf8_case_file_also_degrades_instead_of_raising(tmp_path):
    """S4's fix widened `_index_row`'s catch to `YAMLError`, but
    `path.read_text(encoding="utf-8")` itself was still called BEFORE
    that `try` block — a case file that is not valid UTF-8 (or a lost
    file mid-rebuild) would raise `UnicodeDecodeError`/`OSError` past
    `_index_row` exactly like the pre-fix YAML bug did. The read is now
    inside the `try`, caught alongside `CaseError`/`YAMLError`."""
    home = make_home(tmp_path)
    good = _record(tmp_path, home)
    good_path = next((home / "cases").glob(f"*/{good}.md"))
    cases_dir = good_path.parent

    bad_bytes_path = cases_dir / "case-00000004.md"
    bad_bytes_path.write_bytes(b"\xff\xfe not valid utf-8 \x00\x01")

    cache_dir = worker.cache_dir(home)
    rebuilt = cases.rebuild_index(cache_dir, home)  # must not raise
    rows = json.loads(rebuilt.read_bytes())["cases"]
    assert len(rows) == 2
    flagged = [r for r in rows if r["frozen_ok"] is False]
    assert len(flagged) == 1 and flagged[0]["case"] == "case-00000004"
    ok_rows = [r for r in rows if r["frozen_ok"] is True]
    assert len(ok_rows) == 1 and ok_rows[0]["case"] == good


# --------------------------------------------------------------- Astra 5


def test_r2_astra5_case_list_text_output_marks_a_tampered_row(monkeypatch, tmp_path):
    """Astra r2 finding 5 / gate r2 decision 6: `_index_row` (S4) always
    carries `frozen_ok` and the JSON view of `case list` already shows
    it — but the TEXT view (what a human actually reads at a terminal)
    silently dropped the flag. One good case and one hand-tampered case
    (frontmatter that will not parse at all, forcing `frozen_ok: false`
    the same way `test_r2_s4_...` does), driven through `cli.main`
    end-to-end: the tampered row's printed line must carry a visible
    `TAMPERED` marker and the good row's must not (positive control
    checked first, so an always-on marker can't pass silently)."""
    from self_learn import cli

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    good = _record(tmp_path, home)
    good_path = next((home / "cases").glob(f"*/{good}.md"))
    cases_dir = good_path.parent

    bad_path = cases_dir / "case-00000003.md"
    bad_path.write_text("not frontmatter at all\n", encoding="utf-8")

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["case", "list"])
    assert rc == 0
    out = buf.getvalue()
    lines = {ln.split("  ")[0]: ln for ln in out.splitlines() if ln.strip()}

    assert good in lines
    assert "TAMPERED" not in lines[good]  # positive control first
    assert "case-00000003" in lines
    assert "TAMPERED" in lines["case-00000003"]


# --------------------------------------------------------------- N5


def test_r2_n5_index_lock_is_mutually_exclusive_across_two_writers(tmp_path):
    """Gate r2 N5: `_index_lock` had no test of its own — the raw-write
    gate only pins that the `open()` call exists and is accounted for;
    nothing exercised two concurrent index writers. Proven the same way
    `test_recover_or_refuse.py` proves `commit_lock` mutual exclusion: a
    SEPARATE file descriptor holds the lock exclusively; a second
    acquisition (here, `cases._index_lock` on a background thread, since
    its own `flock` call blocks rather than raising) must stay blocked
    until the outside holder releases — never interleave."""
    home = make_home(tmp_path)
    cache_dir = worker.cache_dir(home)
    lock_path = cases._index_path(cache_dir).parent / "index.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    outside_fh = open(lock_path, "w", encoding="utf-8")
    fcntl.flock(outside_fh.fileno(), fcntl.LOCK_EX)

    acquired = threading.Event()
    events: list[str] = []

    def writer():
        with cases._index_lock(cache_dir):
            events.append("acquired")
        acquired.set()

    t = threading.Thread(target=writer)
    t.start()
    try:
        t.join(timeout=0.3)
        assert not acquired.is_set(), "the second writer must still be blocked"
        assert events == []
    finally:
        fcntl.flock(outside_fh.fileno(), fcntl.LOCK_UN)
        outside_fh.close()

    t.join(timeout=5)
    assert acquired.is_set(), "the second writer must acquire once released"
    assert events == ["acquired"]


# =================================================== fold r1 (U5): F6a


def test_require_reconsider_case_refuses_when_predecessor_link_is_broken(tmp_path):
    """Fold r1 (F6a): the predecessor-link check
    (`old_fm.get("superseded_by") != case_id`) had no test pinning it
    -- gate mutation F neutralised it and the whole committed suite
    stayed green (only an ad-hoc probe went red). `cases.record` would
    refuse a SECOND write through its own `supersedes` path (a case is
    superseded once), so the only way to reach a mismatched link is to
    hand-corrupt it after a valid supersession -- simulating a stale
    or tampered link, not a state reachable through the ordinary CLI."""
    home = make_home(tmp_path)
    predecessor = _record(tmp_path, home, kind="resolution", outcome="route")
    reconsider_case = _record(
        tmp_path, home, actor="steward", kind="reconsider", outcome="reject",
        overrides={"supersedes": predecessor},
    )
    view = cases.show(home, predecessor, evidence_only=False)
    assert view.frontmatter["superseded_by"] == reconsider_case  # fixture sanity

    # Hand-corrupt the predecessor's OWN frontmatter link. Frontmatter
    # sits OUTSIDE the frozen body span the tamper check hashes, so
    # this does not trip that check first.
    cases_dir = home / "cases"
    predecessor_path = next(cases_dir.glob(f"*/{predecessor}.md"))
    text = predecessor_path.read_text(encoding="utf-8")
    corrupted = text.replace(
        f"superseded_by: {reconsider_case}", "superseded_by: case-deadbeef"
    )
    assert corrupted != text  # sanity: the substitution actually matched
    predecessor_path.write_text(corrupted, encoding="utf-8")

    with pytest.raises(cases.CaseError, match="predecessor link is broken"):
        cases.require_reconsider_case(home, reconsider_case, "lrn-08ed825b")
