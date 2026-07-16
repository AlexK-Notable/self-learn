"""CLI `list` / `status` wiring (T3): pinned --json shapes (08 §1 `--json`
stubs pin incl. the G-3 hardening), defer hiding, unanalyzed counts."""

import json

import pytest

from self_learn import cli
from self_learn.ledger_ops import create_record, defer_record, stamp_proposal, write_proposal

from support import days_ago, make_behavior, make_home, make_knowledge, proposal_dict

PINNED_ITEM_KEYS = [
    "id",
    "type",
    "scope",
    "kind",
    "status",
    "created_at",
    "age_days",
    "deferred_until",
    "sightings",
    "has_proposal",
    "title",
    "proposal_fresh",
    "destination",
    "already_canon",
]


@pytest.fixture
def home(monkeypatch, tmp_path):
    h = make_home(tmp_path, skills=("home-assistant",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


def _list_json(capsys, *flags):
    rc = cli.main(["list", "--json", *flags])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_list_json_full_pinned_shape(home, capsys):
    rec = make_behavior(
        scope="skill:home-assistant",
        record_id="lrn-aa000001",
        created_at=days_ago(3),
        trigger="About to edit .storage while HA is running.\nSecond line ignored.",
    )
    create_record(home, rec)
    write_proposal(
        home,
        "lrn-aa000001",
        proposal_dict(destination="hook", already_canon=True, already_canon_reason="in canon"),
    )
    stamp_proposal(home, "lrn-aa000001")

    (item,) = _list_json(capsys)
    assert list(item.keys()) == PINNED_ITEM_KEYS
    assert item["id"] == "lrn-aa000001"
    assert item["type"] == "behavior"
    assert item["scope"] == "skill:home-assistant"
    assert item["kind"] == "anti-pattern"
    assert item["status"] == "pending"
    assert item["age_days"] == 3
    assert item["deferred_until"] is None
    assert item["sightings"] == 1
    assert item["has_proposal"] is True
    assert item["title"] == "About to edit .storage while HA is running."
    assert item["proposal_fresh"] is True
    assert item["destination"] == "hook"
    assert item["already_canon"] is True


def test_list_json_no_proposal_defaults(home, capsys):
    create_record(
        home, make_knowledge(scope="user", record_id="lrn-aa000001", fact="The fact line.")
    )
    (item,) = _list_json(capsys)
    assert item["kind"] is None
    assert item["title"] == "The fact line."
    assert item["has_proposal"] is False
    assert item["proposal_fresh"] is False
    assert item["destination"] is None
    assert item["already_canon"] is False


def test_list_json_stale_proposal_not_fresh(home, capsys):
    create_record(home, make_behavior(scope="skill:home-assistant", record_id="lrn-aa000001"))
    write_proposal(home, "lrn-aa000001", proposal_dict(record_sha="sha256:000000000000"))
    (item,) = _list_json(capsys)
    assert item["has_proposal"] is True
    assert item["proposal_fresh"] is False
    assert item["destination"] == "skill-md"  # still surfaced from the sibling


def test_list_json_hides_future_deferred_by_default(home, capsys):
    create_record(home, make_knowledge(scope="user", record_id="lrn-aa000001"))
    create_record(home, make_knowledge(scope="user", record_id="lrn-bb000002"))
    defer_record(home, "lrn-bb000002", "2099-01-01")

    items = _list_json(capsys)
    assert [i["id"] for i in items] == ["lrn-aa000001"]

    superset = _list_json(capsys, "--include-deferred")
    assert [i["id"] for i in superset] == ["lrn-aa000001", "lrn-bb000002"]
    deferred = superset[1]
    assert deferred["status"] == "deferred"
    assert deferred["deferred_until"] == "2099-01-01"


def test_list_json_past_deferred_visible_again(home, capsys):
    create_record(home, make_knowledge(scope="user", record_id="lrn-aa000001"))
    defer_record(home, "lrn-aa000001", "2020-01-01")
    items = _list_json(capsys)
    assert [i["id"] for i in items] == ["lrn-aa000001"]


def test_list_json_empty_is_empty_array(home, capsys):
    assert _list_json(capsys) == []


def test_list_human_table(home, capsys):
    create_record(
        home,
        make_behavior(
            scope="skill:home-assistant",
            record_id="lrn-aa000001",
            trigger="Trigger line.",
        ),
    )
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lrn-aa000001" in out
    assert "Trigger line." in out


def test_list_human_zero_state(home, capsys):
    rc = cli.main(["list"])
    assert rc == 0
    assert "0 records" in capsys.readouterr().out


# ------------------------------------------------------------------ status


def test_status_json_pinned_shape_with_unanalyzed(home, capsys):
    # skill bucket: 1 analyzed-fresh + 1 unanalyzed + 1 future-deferred
    create_record(
        home,
        make_behavior(
            scope="skill:home-assistant", record_id="lrn-aa000001", created_at=days_ago(5)
        ),
    )
    write_proposal(home, "lrn-aa000001", proposal_dict())
    stamp_proposal(home, "lrn-aa000001")
    create_record(
        home,
        make_behavior(
            scope="skill:home-assistant", record_id="lrn-bb000002", created_at=days_ago(2)
        ),
    )
    create_record(
        home, make_behavior(scope="skill:home-assistant", record_id="lrn-cc000003")
    )
    defer_record(home, "lrn-cc000003", "2099-01-01")
    # user bucket: 1 unanalyzed (the "project+user" combined scope is dead;
    # doc 13 §3 splits it into separate project and user buckets)
    create_record(home, make_knowledge(scope="user", record_id="lrn-dd000004"))

    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "buckets": [
            {
                "bucket": "home-assistant",
                "scope": "skill",
                "pending": 2,  # future-deferred excluded from all counts
                "oldest_days": 5,
                "unanalyzed": 1,
            },
            {
                "bucket": "user",
                "scope": "user",
                "pending": 1,
                "oldest_days": 0,
                "unanalyzed": 1,
            },
        ],
        "total_pending": 3,
        "open_followups": 0,
        "worker_last_run": None,
    }


def test_status_human_mentions_unanalyzed(home, capsys):
    create_record(home, make_knowledge(scope="user", record_id="lrn-aa000001"))
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 pending" in out
    assert "1 unanalyzed" in out
