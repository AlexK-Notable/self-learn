"""O-1 · the overseer's blind population listing, coverage nudges, and
coverage record (`plan-overseer-2026-09-12.md` §O-1; `02-schema.md`
§3a.2's blind view; `03-decisions.md` S-66).

`self_learn.overseer.population` is a PURE module: no ledger writes.
Every test below builds its own throwaway sandbox ledger
(`support.make_env`) — never the real `~/.self-learn`.

Six pinned mutations (build-o1.md §Tests) plus one of this file's own
choosing, each recorded red-then-green in the build report (a manual
edit/run/revert cycle against THIS file's tests — not a second,
self-contained "mutation test" function; a test that reproduces its own
bug inline proves nothing about whether the real code is guarded).
"""

from __future__ import annotations

import copy
import io
from datetime import datetime, timezone

import pytest
from ruamel.yaml import YAML

from self_learn import cases, telemetry
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import population as pop
from self_learn.records import Record
from support import make_env, make_behavior, make_knowledge

# ------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _actor(monkeypatch):
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# --------------------------------------------------- case-stage helpers
#
# Copied from test_cases.py (common-builder-rules.md: a test file owns
# its own fixture helpers rather than importing a sibling test module).

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


def _write_stage(tmp_path, overrides=None, **kw):
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


def _record(tmp_path, home, *, actor="steward", **kw) -> str:
    stage = _write_stage(tmp_path, **kw)
    return cases.record(home, stage, actor=actor)


def _seed_record(home, record_id, *, scope="project", project_path=None):
    """A real ledger record a case's `records: [...]` can point at, so
    `_record_scope_kind`'s lookup resolves — pending is enough, the
    coverage stratum only reads `record.scope`, never `status`. Project
    scope needs the sandbox host's own path (per-project buckets, doc 13
    §3) — `make_env`'s host repo, never a bare `make_home`."""
    maker = make_behavior if scope.startswith("skill:") else make_knowledge
    create_record(home, maker(record_id=record_id, scope=scope), project_path=project_path)


def _route_directly(home, record_id):
    """Move a pending record straight to `resolved/`, status `routed` —
    bypasses the full CLI `route` flow (host repo, compilation, commit)
    that this pure module has no reason to depend on for a fixture."""
    path = find_record_path(home, record_id)
    record = Record.from_path(path)
    record.set_status("routed")
    resolved_dir = path.parent.parent / "resolved"
    resolved_dir.mkdir(parents=True, exist_ok=True)
    record.write(resolved_dir / path.name)
    path.unlink()


def _full_row(home, case_id) -> dict:
    rows = cases.list_cases(home)
    return next(r for r in rows if r["case"] == case_id)


# =================================================== T1 — blind listing


def test_blind_listing_hides_outcome_decision_and_receipts(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-08ed825b", scope="project", project_path=env.host)
    case_id = _record(tmp_path, home)
    cases.receipt(
        home,
        case_id,
        {
            "sheet": "01.yaml",
            "stopped_at": None,
            "items": [{"n": 1, "id": "lrn-08ed825b", "verb": "reject", "state": "applied", "rc": 0}],
        },
    )

    # Positive control FIRST: the full view really does carry the
    # verb/outcome/reason/receipt text this test asserts is hidden.
    full = cases.show(home, case_id, evidence_only=False)
    assert full.frontmatter["outcome"] == "reject"
    assert "the standing order is about the hypr subrepo" in full.sections["Decision"]
    assert "applied" in full.sections["Application"]

    listing = pop.population(home, since="")
    assert [bc.case for bc in listing] == [case_id]
    text = pop.render_population(listing) + repr(listing[0].to_dict())
    assert "reject" not in text
    assert "the standing order is about the hypr subrepo" not in text
    assert "applied" not in text


# ============================================ T2 — every case gets a view


def test_every_case_of_the_week_gets_a_blind_view_file(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-08ed825b", scope="project", project_path=env.host)
    ordinary = _record(tmp_path, home)
    parked = _record(
        tmp_path,
        home,
        kind="parked",
        outcome="parked",
        overrides={"parked_for": "overseer", "parked_reason": "hook"},
    )

    listing = pop.population(home, since="")
    assert {bc.case for bc in listing} == {ordinary, parked}

    stage_dir = tmp_path / "stage"
    result = pop.write_blind_views(home, stage_dir, listing)
    assert set(result["written"]) == {ordinary, parked}
    assert result["skipped"] == []
    assert (stage_dir / f"{ordinary}.md").is_file()
    assert (stage_dir / f"{parked}.md").is_file()


# ==================================== T3 — strata computed by code only


def test_coverage_strata_computed_by_code_not_selection(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home,
        outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    assert row["outcome"] == "reject"

    # The model's selection.yaml carries a `stratum` key that does NOT
    # match this case's real cell — it must be ignored entirely.
    selection = {"cases": [{"id": case_id, "stratum": "route/user"}]}
    result = pop.coverage_update(None, selection, [row], home=home)

    assert result["strata"]["reject/project"]["status"] == "examined"
    assert result["strata"]["reject/project"]["cumulative_count"] == 1
    assert result["strata"]["route/user"]["status"] == "empty"


# ========================================== T4 — empty strata recorded


def test_empty_strata_recorded_not_dropped(tmp_path):
    home = make_env(tmp_path).ledger
    result = pop.coverage_update(None, {"cases": []}, [], home=home)
    assert len(result["strata"]) == 27
    assert all(entry["status"] == "empty" for entry in result["strata"].values())


# ================================== T5 — cumulative counts survive a run


def test_cumulative_counts_merge_not_overwrite(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home,
        outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)

    previous = pop._empty_coverage()
    previous["strata"]["reject/project"] = {
        "outcome": "reject", "scope": "project",
        "cumulative_count": 3, "last_examined_at": "2026-01-01T00:00:00Z",
        "status": "examined",
    }

    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    result = pop.coverage_update(previous, {"cases": [{"id": case_id}]}, [row], now=now, home=home)

    entry = result["strata"]["reject/project"]
    assert entry["cumulative_count"] == 4  # 3 (merged) + 1 (this run)
    assert entry["last_examined_at"] == "2026-09-14T12:00:00Z"


# ======================================================== T6 — nudges


def test_nudges_order_and_recurrence_suspects(tmp_path):
    home = make_env(tmp_path).ledger

    coverage = pop._empty_coverage()
    coverage["strata"]["route/user"]["last_examined_at"] = None  # never examined
    coverage["strata"]["reject/project"] = {
        "outcome": "reject", "scope": "project",
        "cumulative_count": 1, "last_examined_at": "2026-01-01T00:00:00Z",
        "status": "examined",
    }
    coverage["strata"]["retire/skill"] = {
        "outcome": "retire", "scope": "skill",
        "cumulative_count": 1, "last_examined_at": "2026-06-01T00:00:00Z",
        "status": "examined",
    }

    # Seed one routed record + one recurrence-suspect telemetry event.
    rid = "lrn-0000aaaa"
    _seed_record(home, rid, scope="skill:s")
    _route_directly(home, rid)

    telemetry.spool_event("recurrence-suspect", record=rid, origin="lrn-0000eeee", basis="miner-match")
    telemetry.flush(home)

    result = pop.nudges(home, coverage, week="2020-01-01T00:00:00Z")
    stratum_nudges = [n for n in result if n["kind"] == "stratum"]
    keys_in_order = [n["key"] for n in stratum_nudges]
    assert keys_in_order.index("route/user") < keys_in_order.index("reject/project")
    assert keys_in_order.index("reject/project") < keys_in_order.index("retire/skill")

    recurrence = [n for n in result if n["kind"] == "recurrence-suspect"]
    assert any(n["id"] == rid and n["basis"] == "miner-match" for n in recurrence)


# ============================= own choice — the unexamined branch (M7)


def test_populated_but_unexamined_stratum_is_distinct_from_empty(tmp_path):
    """This unit's own mutation (common-builder-rules.md: "run at least
    one of your own choosing against the behaviour you think is least
    protected"). Tests 4/5 pin the `empty` and `examined` branches;
    nothing pins the THIRD branch — a stratum with real members this
    week that the model simply did not select. Collapsing it into
    `empty` would silently erase the "known cases exist, still
    untouched" signal the coverage record exists to carry."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home,
        outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)

    # Nothing selected this run.
    result = pop.coverage_update(None, {"cases": []}, [row], home=home)
    entry = result["strata"]["reject/project"]
    assert entry["status"] == "unexamined"
    assert entry["cumulative_count"] == 0
    assert entry["last_examined_at"] is None
