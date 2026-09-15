"""O-1 · the overseer's blind population listing, coverage nudges, and
coverage record (`plan-overseer-2026-09-12.md` §O-1; `02-schema.md`
§3a.2's blind view; `03-decisions.md` S-66; O-1 fold r1: `scope_kind`
on the index row, `home` refused from `coverage_update`, offered/taken
computed by code with no free text in the coverage record, both blind-
view call sites guarded, one lineage one cell).

`self_learn.overseer.population` is a PURE module: no ledger writes.
Every test below builds its own throwaway sandbox ledger
(`support.make_env`) — never the real `~/.self-learn`.

Mutations are recorded red-then-green in the fold report (a manual
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

from self_learn import cases, telemetry, user_model
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import population as pop
from self_learn.records import Record
from support import make_env, make_behavior, make_knowledge


def test_coverage_top_level_run_dates_are_forward_only(tmp_path):
    prior = pop._empty_coverage()
    prior["last_run_at"] = "2026-09-15T00:00:00Z"
    prior["last_examined_at"] = "2026-09-14T00:00:00Z"
    result = pop.coverage_update(
        prior,
        {"cases": []},
        [],
        [],
        now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result["last_run_at"] == "2026-09-15T00:00:00Z"
    assert result["last_examined_at"] == "2026-09-14T00:00:00Z"
    text = pop.render_coverage(result)
    path = tmp_path / "coverage.yaml"
    path.write_text(text, encoding="utf-8")
    assert pop.load_coverage(path)["last_run_at"] == "2026-09-15T00:00:00Z"


def test_population_consumers_request_only_freeze_verified_cases(monkeypatch, tmp_path):
    calls = []

    def listed(home, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(pop.cases_mod, "list_cases", listed)
    pop.population(tmp_path, "2026-09-01T00:00:00Z")
    monkeypatch.setattr(
        pop.user_model_mod,
        "show",
        lambda home: {"containers": {"B": [{"id": "um-00000001"}], "C": []}},
    )
    pop._untouched_system_reading_nudges(tmp_path)
    assert calls == [
        {"since": "2026-09-01T00:00:00Z", "only_ok": True},
        {"only_ok": True},
    ]

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
    `cases._record_scope_and_bucket`'s lookup resolves — pending is
    enough, the coverage stratum only reads `record.scope`, never
    `status`. Project scope needs the sandbox host's own path (per-
    project buckets, doc 13 §3) — `make_env`'s host repo, never a bare
    `make_home`."""
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


# ===================== PROBE A — blindness end to end, listing AND FILE
#
# Ported from the gate's own probe (gap 2 / B3): T2 above proves every
# case gets A file, never that the file's CONTENT is blind — flipping
# `write_blind_views`'s `evidence_only` to `False` (gate mutation M8)
# left T2 green. This test is the missing content check.


def test_probe_a_blindness_listing_and_staged_file_content(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-08ed825b", scope="project", project_path=env.host)
    case_id = _record(tmp_path, home)
    cases.receipt(
        home, case_id,
        {"sheet": "01.yaml", "stopped_at": None,
         "items": [{"n": 1, "id": "lrn-08ed825b", "verb": "reject",
                    "state": "applied", "rc": 0}]},
    )
    cases.observe(
        home, case_id, "presented", text="shown in the weekly conversation",
        by="overseer", to="human", covering="all", outcome="agreed",
        via="overseer-conversation",
    )

    # ---- positive control FIRST: the full view really carries all four.
    full = cases.show(home, case_id, evidence_only=False)
    full_text = full.to_text()
    assert full.frontmatter["outcome"] == "reject"
    assert "the standing order is about the hypr subrepo" in full_text
    assert "applied" in full_text
    assert full.frontmatter.get("presented"), "positive control: presented entry recorded"
    assert "shown in the weekly conversation" in full_text

    listing = pop.population(home, since="")
    listing_text = pop.render_population(listing) + repr([bc.to_dict() for bc in listing])

    stage_dir = tmp_path / "stage"
    pop.write_blind_views(home, stage_dir, listing)
    staged = (stage_dir / f"{case_id}.md").read_text(encoding="utf-8")

    for blob, label in ((listing_text, "listing"), (staged, "staged blind view")):
        assert "the standing order is about the hypr subrepo" not in blob, f"{label} leaked the Decision reason"
        assert "outcome" not in blob, f"{label} leaked the outcome key"
        assert "applied" not in blob, f"{label} leaked a receipt line"
        assert "presented" not in blob, f"{label} leaked the presented entry"
        assert "shown in the weekly conversation" not in blob, f"{label} leaked presentation text"


def test_both_case_show_call_sites_always_request_the_blind_view(tmp_path, monkeypatch):
    """B3 + S4: the gate's M8 (`write_blind_views`) and M9
    (`population()`) mutations both flip `cases.show(...,
    evidence_only=True)` to `False` at their OWN call site. M8's flip is
    caught on CONTENT by the probe above; M9's is NOT observable in
    `population()`'s output today — it only ever reads
    `sections["Identity and scope"]`, which the full view also carries
    (S4) — so this pins the CONTRACT instead: wrap `cases.show`, record
    the `evidence_only` kwarg every call received, drive both
    `population()` and `write_blind_views()`, and assert every call
    passed `True`."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-08ed825b", scope="project", project_path=env.host)
    _record(tmp_path, home)

    calls: list[bool] = []
    real_show = cases.show

    def spy(home_arg, case_id_arg, *, evidence_only=True):
        calls.append(evidence_only)
        return real_show(home_arg, case_id_arg, evidence_only=evidence_only)

    monkeypatch.setattr(pop.cases_mod, "show", spy)

    listing = pop.population(home, since="")
    pop.write_blind_views(home, tmp_path / "stage", listing)

    assert calls, "no cases.show call observed — fixture is broken"
    assert all(v is True for v in calls), f"a call site requested the FULL view: {calls!r}"


# ============ N1 — write_blind_views refuses a stage_dir inside home ====


def test_write_blind_views_refuses_a_stage_dir_inside_home(tmp_path):
    """N1. The brief's own wording ("refuses a `stage_dir` outside the
    run's stage root") names no stage-root parameter this function has
    to compare against — this implements the gate's concrete mechanism
    instead (`if home in stage_dir.parents: raise`), both lines quoted
    in the fold report rather than resolved silently."""
    env = make_env(tmp_path)
    home = env.ledger
    with pytest.raises(pop.PopulationError):
        pop.write_blind_views(home, home / "sneaky-stage", [])


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
    assert row["outcome"] == "reject"          # positive control
    assert row["scope_kind"] == "project"      # positive control

    # A clean selection — there is no per-case key left the model could
    # even use to steer the stratum (B2's `_SELECTION_CASE_ALLOWED_KEYS`
    # is `{"id"}` only; see the refusal test below for the other half).
    selection = {"cases": [{"id": case_id}]}
    result = pop.coverage_update(None, selection, [row], [])

    assert result["strata"]["reject/project"]["status"] == "examined"
    assert result["strata"]["reject/project"]["cumulative_count"] == 1
    assert result["strata"]["route/user"]["status"] == "empty"


def test_selection_case_entry_with_unknown_key_is_refused(tmp_path):
    """B2/gate check (b), the other half of T3: the model's selection
    file cannot smuggle a `stratum` override in through a per-case
    entry either — an unknown key there is refused, never silently
    ignored."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    selection = {"cases": [{"id": case_id, "stratum": "route/user"}]}
    with pytest.raises(pop.CoverageError):
        pop.coverage_update(None, selection, [row], [])


def test_selection_yaml_unknown_top_level_key_is_refused(tmp_path):
    """B2 / gap 3: under the OLD code, `nudges_offered` was read straight
    out of `selection_yaml` — the model's own file. The signature change
    closes that vector at the door: any unknown top-level key, that one
    included, is refused outright."""
    home = make_env(tmp_path).ledger
    with pytest.raises(pop.CoverageError):
        pop.coverage_update(None, {"cases": [], "nudges_offered": ["x"]}, [], [])


# =============== B1/S1 — scope_kind on the row, never re-derived here ===


def test_row_missing_scope_kind_is_refused(tmp_path):
    """B1/S1: `coverage_update` no longer accepts `home` and never
    guesses — a row that cannot report a usable `scope_kind` is a hard
    refusal, not a silent `*/project` miscount."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    assert row["scope_kind"] == "project"      # positive control

    del row["scope_kind"]
    with pytest.raises(pop.CoverageError):
        pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], [])


def test_skill_scoped_case_with_deleted_record_still_files_by_cached_scope_kind(tmp_path):
    """B1/S1's other named test: `scope_kind` is computed ONCE, by
    `cases._index_row`, at index-build time — a record deleted
    AFTERWARD never erases the classification an already-fetched row
    carries, because `coverage_update` trusts the row as given and never
    re-derives anything itself (it has no `home` to look anything up
    with any more)."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000dddd", scope="skill:s")
    case_id = _record(
        tmp_path, home, outcome="retire",
        overrides={"records": ["lrn-0000dddd"], "scope": "skill:s"},
    )
    row = _full_row(home, case_id)
    assert row["outcome"] == "retire"          # positive control
    assert row["scope_kind"] == "skill"        # positive control: computed while the record existed

    find_record_path(home, "lrn-0000dddd").unlink()  # now gone

    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], [])
    assert result["strata"]["retire/skill"]["status"] == "examined", (
        "a skill-scoped case whose cited record is unreadable was filed as "
        + next(k for k, v in result["strata"].items() if v["status"] == "examined")
    )


# ========================================== T4 — empty strata recorded


def test_empty_strata_recorded_not_dropped(tmp_path):
    result = pop.coverage_update(None, {"cases": []}, [], [])
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
    result = pop.coverage_update(previous, {"cases": [{"id": case_id}]}, [row], [], now=now)

    entry = result["strata"]["reject/project"]
    assert entry["cumulative_count"] == 4  # 3 (merged) + 1 (this run)
    assert entry["last_examined_at"] == "2026-09-14T12:00:00Z"


# ================================ S2 — last_examined_at forward only ===


def test_last_examined_at_moves_forward_only(tmp_path):
    """S2 / gate check (c): re-running an OLDER `now` (a replay, a
    re-run of a stored selection, a clock-skewed run) must never make a
    just-examined stratum's `last_examined_at` step BACKWARD."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)

    previous = pop._empty_coverage()
    previous["strata"]["reject/project"] = {
        "outcome": "reject", "scope": "project", "cumulative_count": 3,
        "last_examined_at": "2026-09-14T12:00:00Z", "status": "examined",
    }
    stale = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)  # EARLIER
    result = pop.coverage_update(previous, {"cases": [{"id": case_id}]}, [row], [], now=stale)
    assert result["strata"]["reject/project"]["last_examined_at"] == "2026-09-14T12:00:00Z", (
        "last_examined_at moved BACKWARD: "
        f"{result['strata']['reject/project']['last_examined_at']}"
    )


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


def test_worktree_bucket_nudge_carries_an_id_field(tmp_path):
    """S3's own prerequisite: the fold brief asks `_worktree_bucket_
    nudges` to "give it `id: <bucket>`" so the taken logic can treat it
    like every other kind — this is that field's own existence check,
    separate from the D3-style "does the nudge fire at all" probe."""
    home = make_env(tmp_path).ledger
    bucket = home / "projects" / "somerepo-worktree"
    bucket.mkdir(parents=True)
    fake = tmp_path / "somerepo" / ".claude" / "worktrees" / "lane-x"
    fake.mkdir(parents=True)
    (bucket / "meta.yaml").write_text(f"path: {fake}\n", encoding="utf-8")

    out = pop.nudges(home, pop._empty_coverage(), week="2020-01-01T00:00:00Z")
    wt = [n for n in out if n["kind"] == "worktree-bucket"]
    assert wt and wt[0]["id"] == "somerepo-worktree" == wt[0]["bucket"]


# ================================= own choice — the unexamined branch (M7)


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
    result = pop.coverage_update(None, {"cases": []}, [row], [])
    entry = result["strata"]["reject/project"]
    assert entry["status"] == "unexamined"
    assert entry["cumulative_count"] == 0
    assert entry["last_examined_at"] is None


# ========================= B2/S3 — offered/taken, per nudge kind =======


def test_free_text_and_unknown_fields_dropped_from_offered(tmp_path):
    """02-schema.md §3a.1 item 2: coverage.yaml carries no free text at
    all. Adapted from the gate's probe F: the OLD vector (reading
    `nudges_offered` back out of `selection.yaml`) is closed at the door
    by the signature change (see the top-level-key refusal test above)
    — this exercises the remaining one, `offered` itself, which a
    future caller could still pass malformed content through."""
    home = make_env(tmp_path).ledger
    offered = [
        "I looked at everything and decided the retire/skill cell was "
        "fine, because the steward's reasoning there was persuasive.",
        {"kind": "stratum", "key": "route/user", "why_i_skipped_it": "felt healthy"},
    ]
    result = pop.coverage_update(None, {"cases": []}, [], offered)
    rendered = pop.render_coverage(result)
    assert "persuasive" not in rendered, f"free text reached coverage.yaml:\n{rendered}"
    assert "felt healthy" not in rendered, f"free text reached coverage.yaml:\n{rendered}"
    # the legitimate half of the second entry survives, sanitized.
    assert result["nudges_offered"] == [{"kind": "stratum", "key": "route/user"}]


def test_stratum_nudge_taken_when_its_stratum_gets_examined(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    offered = [{"kind": "stratum", "key": "reject/project", "last_examined_at": None}]
    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], offered)
    taken_keys = {n.get("key") for n in result["nudges_taken"] if n.get("kind") == "stratum"}
    assert "reject/project" in taken_keys


def test_recurrence_and_zero_fire_nudges_taken_via_records(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    offered = [
        {"kind": "recurrence-suspect", "id": "lrn-0000cccc", "nonce": "n1", "basis": "miner-match"},
        {"kind": "always-loaded-zero-fire", "id": "lrn-0000cccc"},
    ]
    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], offered)
    taken_kinds = {n.get("kind") for n in result["nudges_taken"]}
    assert {"recurrence-suspect", "always-loaded-zero-fire"} <= taken_kinds


def test_system_reading_nudge_taken_via_dependency_refs(tmp_path):
    """B2/S3, gate probe E adapted: `system-reading-untouched` nudges
    carry `um-…` ids, which appear only in `dependency_refs[]`, never in
    `records[]` — matching against `records[]` (the OLD, wrong branch
    every non-stratum kind used to share) would never mark this taken."""
    env = make_env(tmp_path)
    home = env.ledger
    um_id = user_model.add_entry(
        home, container="C", title="load cost dominates",
        because="three sessions in a row said so", source="system-reading",
        by="steward", statements=["stmt-0000aaaa"], ref="stmt-0000aaaa",
    )
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
        dependencies={"user_model": [um_id]},
    )
    row = _full_row(home, case_id)
    assert um_id in row["dependency_refs"]  # positive control

    offered = [{"kind": "system-reading-untouched", "id": um_id}]
    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], offered)
    taken_kinds = {n.get("kind") for n in result["nudges_taken"]}
    assert "system-reading-untouched" in taken_kinds, (
        "a system reading the examined case actually cites is never counted taken: "
        f"{result['nudges_taken']!r}"
    )


def test_worktree_bucket_nudge_taken_via_record_bucket(tmp_path):
    """B2/S3: `worktree-bucket` nudges carry no `id` at all under the
    old code, so `None in {...records...}` never matched. Matched here
    against `record_bucket` — the bucket the examined case's first
    cited record physically lives in (`cases._index_row`'s own field,
    O-1 fold r1) — which is how this fold reads the brief's "an examined
    case's scope names that bucket" (a project record's own controlled
    `scope` is just the literal string "project"; it never names a
    bucket, so this operationalizes it as physical bucket membership)."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    row = _full_row(home, case_id)
    bucket_name = row["record_bucket"]
    assert bucket_name, f"fixture did not resolve a record_bucket: {row!r}"  # positive control

    offered = [{"kind": "worktree-bucket", "id": bucket_name, "bucket": bucket_name, "path": "/x"}]
    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row], offered)
    taken_kinds = {n.get("kind") for n in result["nudges_taken"]}
    assert "worktree-bucket" in taken_kinds


# =========================================== S6 — one lineage, one cell


def test_parked_case_decided_later_counts_only_under_successors_outcome(tmp_path):
    """S6 ruling: a case row with `superseded_by` set is NOT a member of
    any stratum; its successor carries the lineage under the
    SUCCESSOR's own outcome. `parked/<scope>` is the CURRENT backlog of
    undecided parked cases, never a history of every case ever parked —
    examining the parked row must not also increment `parked/*`."""
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    parked_id = _record(
        tmp_path, home,
        kind="parked", outcome="parked",
        parked_for="overseer", parked_reason="hook",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    successor_id = _record(
        tmp_path, home,
        actor="overseer", outcome="reject", supersedes=parked_id,
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    parked_row = _full_row(home, parked_id)
    successor_row = _full_row(home, successor_id)
    assert parked_row["superseded_by"] == successor_id  # positive control

    result = pop.coverage_update(
        None,
        {"cases": [{"id": parked_id}, {"id": successor_id}]},
        [parked_row, successor_row],
        [],
    )
    assert result["strata"]["parked/project"]["status"] == "empty"
    assert result["strata"]["parked/project"]["cumulative_count"] == 0
    assert result["strata"]["reject/project"]["status"] == "examined"
    assert result["strata"]["reject/project"]["cumulative_count"] == 1


# ==================================================== N2 — render_coverage


def test_render_coverage_refuses_an_unknown_top_level_key(tmp_path):
    data = pop._empty_coverage()
    data["bogus"] = "nope"
    with pytest.raises(pop.CoverageError):
        pop.render_coverage(data)


# ============================== N3 — examined_count / population_count


def test_coverage_record_carries_examined_and_population_counts(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _seed_record(home, "lrn-0000cccc", scope="project", project_path=env.host)
    case_id = _record(
        tmp_path, home, outcome="reject",
        overrides={"records": ["lrn-0000cccc"], "scope": "project:~/.config"},
    )
    _seed_record(home, "lrn-08ed825b", scope="project", project_path=env.host)
    other_id = _record(tmp_path, home, outcome="defer")  # part of the population, not selected
    row1 = _full_row(home, case_id)
    row2 = _full_row(home, other_id)

    result = pop.coverage_update(None, {"cases": [{"id": case_id}]}, [row1, row2], [])
    assert result["examined_count"] == 1
    assert result["population_count"] == 2

    # round-trip through the actual file text, like O-3 will.
    path = tmp_path / "coverage.yaml"
    path.write_text(pop.render_coverage(result), encoding="utf-8")
    reloaded = pop.load_coverage(path)
    assert reloaded["examined_count"] == 1
    assert reloaded["population_count"] == 2
