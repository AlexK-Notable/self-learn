"""O-7 catalogue-health facts and catalogue-sheet boundary guards."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import batch, conditions, settings
from self_learn.ledger_ops import create_record
from self_learn.overseer import health
from self_learn.overseer import run as overseer_run
from support import make_behavior, make_home


def test_report_fact_functions_are_plain_projections() -> None:
    gathered = {
        "context_budget": {
            "crowding": {"flagged": True, "basis": "token pressure"},
            "conditional": {"reference": {"read_rate_state": "ok"}},
        },
        "surface_reach": {"reachable": 3, "rows": [{"id": "lrn-a"}]},
        "recurrence_suspects": [
            {"id": "lrn-a", "nonce": "n1", "basis": "fire-violated"}
        ],
    }
    assert health.context_budget_crowding(gathered) == {
        "kind": "context-budget-crowding",
        "value": {"flagged": True, "basis": "token pressure"},
    }
    assert health.reference_read_verdict(gathered)["value"]["read_rate_state"] == "ok"
    assert health.surface_reach(gathered)["value"]["reachable"] == 3
    assert health.recurrence_suspects(gathered)["value"] == [
        {"id": "lrn-a", "nonce": "n1", "basis": "fire-violated"}
    ]


@pytest.mark.parametrize(
    ("fired", "expected"),
    [
        ({"lrn-a"}, ["lrn-b"]),
        (set(), ["lrn-a", "lrn-b"]),
        ({"lrn-a", "lrn-b"}, []),
    ],
)
def test_never_fired_always_loaded_has_silence_caution(fired, expected) -> None:
    row = health.never_fired_always_loaded(["lrn-a", "lrn-b"], fired)
    assert row["value"] == expected
    assert "Silence is not retirement evidence" in row["caution"]


def test_conditions_diff_names_host_model_and_capability_changes() -> None:
    current = [
        conditions.Item("host./repo/a.mode", "plain", "now", "hosts"),
        conditions.Item("models.overseer", "model-b", "now", "settings"),
        conditions.Item("overseer.enabled", False, "now", "settings"),
        conditions.Item("status.total_pending", 4, "now", "status"),
    ]
    row = health.conditions_diff(
        previous_hosts={"projects": ["/repo/a"]},
        current_hosts={"projects": [{"path": "/repo/a", "mode": "plain"}]},
        previous_config={"models": {"overseer": "model-a"}, "overseer": {"enabled": True}},
        current_config={"models": {"overseer": "model-b"}, "overseer": {"enabled": False}},
        current=current,
        baseline="abc123",
    )
    assert row["hosts_changed"] is True
    assert row["models_changed"] == ["models.overseer"]
    assert row["capability_flags_changed"] == ["overseer.enabled"]
    assert {item["key"] for item in row["current"]} == {
        "host./repo/a.mode",
        "models.overseer",
        "overseer.enabled",
    }
    assert "status.total_pending" not in str(row)


def test_full_inputs_puts_catalogue_rows_beside_conditions(tmp_path, monkeypatch) -> None:
    home = make_home(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    item = conditions.Item("models.overseer", "m", "now", "settings")
    monkeypatch.setattr(overseer_run.conditions, "feed", lambda _home: [item])
    monkeypatch.setattr(overseer_run.health, "gather", lambda _home: [{"kind": "health", "value": 1}])
    overseer_run._full_inputs(home, stage, (), [])
    data = YAML(typ="safe").load((stage / "health.yaml").read_text(encoding="utf-8"))
    assert data == {
        "facts": [{"key": "models.overseer", "value": "m", "observed_at": "now", "source": "settings"}],
        "catalogue_health": [{"kind": "health", "value": 1}],
    }


def _fake_caseless_phases(monkeypatch, record_id: str) -> None:
    calls = 0

    def invoke(spec):
        nonlocal calls
        calls += 1
        stage = spec.cwd
        yaml = YAML()
        if calls == 1:
            for name, data in (
                ("selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "none"}),
                ("initial-views.yaml", {"cases": []}),
            ):
                with (stage / name).open("w", encoding="utf-8") as fh:
                    yaml.dump(data, fh)
        else:
            headings = (
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            )
            (stage / "report.md").write_text(
                "# report\n" + "".join(f"\n## {h}\n- none\n" for h in headings),
                encoding="utf-8",
            )
            for name, data in (
                ("findings.yaml", {"findings": []}),
                ("questions.yaml", {"questions": []}),
                ("user-model-delta.yaml", {"updates": []}),  # O-3b's fifth phase-B file
                (
                    "sheet.yaml",
                    {"version": 1, "items": [{"id": record_id, "verb": "note", "append": "catalogue change"}]},
                ),
            ):
                with (stage / name).open("w", encoding="utf-8") as fh:
                    yaml.dump(data, fh)
        return type(
            "SdkLike",
            (),
            {
                "ok": True,
                "rc": 0,
                "stdout": "",
                "detail": "",
                "failure": None,
                "turns": 1,
            },
        )()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def test_runner_refuses_caseless_catalogue_sheet_before_batch_run(tmp_path, monkeypatch) -> None:
    home = make_home(tmp_path)
    rid = "lrn-0a0b0c0d"
    create_record(home, make_behavior(record_id=rid))
    real_resolve = settings.resolve_setting

    def enabled(given_home, setting):
        if setting.name == "overseer.enabled":
            return True, "test"
        return real_resolve(given_home, setting)

    monkeypatch.setattr(settings, "resolve_setting", enabled)
    _fake_caseless_phases(monkeypatch, rid)
    monkeypatch.setattr(
        batch,
        "run",
        lambda *args, **kwargs: pytest.fail("caseless sheet reached batch.run"),
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "refused"
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "needs a paired successor case" in report
