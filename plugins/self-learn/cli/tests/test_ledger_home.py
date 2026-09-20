"""U4b -- a session's settings come from the LEDGER home, not from the
directory the session happens to run in.

Found by a real `self-learn steward run --dry-run` on 2026-09-19: three
model calls, all three answered `API Error: 400 Claude Code 2.1.226 does
not support this model; version 2.1.251 or newer is required` -- the
Agent SDK's own BUNDLED binary -- although the ledger's `config.yaml`
set `sdk.cli_path` to a 2.1.278 one. `SessionSpec` had no ledger-home
field, so the seam used `spec.cwd` AS the ledger home in seven lookups.
The worker, the miner-reader and the analyst pass `cwd=home` and were
therefore fine; the steward passes `cwd=<run dir>` and the overseer
passes `cwd=<stage>`, both cache-stage directories with no `config.yaml`
at all, so for exactly those two surfaces the binary, the model, the
turn bound, the spend bound, the provider resolution and the backend
choice all silently resolved to their defaults.

Every expectation below is stated from the RULE -- "the settings come
from the ledger home" -- and never from what the code returns. Nothing
here mocks `settings.resolve_setting`: each test writes a real
`config.yaml` into a real scratch ledger and drives the real option
builder.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import invocation, provider, settings, steward
from self_learn.invocation import registry
from self_learn.invocation.contract import Outcome, SessionSpec
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.overseer import run as overseer_run

from support import commit_all, make_home
from test_steward import _seed_fresh_proposals, _write_decision_stage

# Both faces of every setting these tests read: an env var left over
# from the operator's shell would mask the defect (`sdk.cli_path` is
# env-first), and a leaked backend pin would change which backend the
# registry picks.
_ENV_VARS = (
    "SELF_LEARN_PROVIDER",
    "SELF_LEARN_BEDROCK_REGION",
    "SELF_LEARN_BEDROCK_PROFILE",
    "SELF_LEARN_SDK_CLI_PATH",
    "SELF_LEARN_SDK_MAX_BUDGET_USD",
    "SELF_LEARN_SDK_MAX_TURNS_STEWARD",
    "SELF_LEARN_SDK_MAX_TURNS_OVERSEER",
    "SELF_LEARN_SDK_MAX_TURNS_WORKER",
    "SELF_LEARN_WORKER_MODEL",
    "SELF_LEARN_STEWARD_MODEL",
    "SELF_LEARN_OVERSEER_MODEL",
    "SELF_LEARN_BACKEND",
    "SELF_LEARN_BACKEND_WORKER",
    "SELF_LEARN_BACKEND_STEWARD",
    "SELF_LEARN_BACKEND_OVERSEER",
)


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------- fixtures


def _write_config(home: Path, data: dict) -> None:
    """`home/config.yaml`, written whole (these ledgers start without
    one) and committed, so the tree the runners see is clean."""
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    (home / "config.yaml").write_text(buf.getvalue(), encoding="utf-8")
    commit_all(home, "u4b: ledger settings")


def _anthropic_settings(home: Path, surface_key: str, cli_path: Path) -> dict:
    """The four scalar settings the seam reads, each given a value no
    default could produce, so one reverted lookup fails one named
    assertion rather than blurring into the others."""
    return {
        "sdk": {
            "cli_path": str(cli_path),
            "max_turns": {surface_key: 7},
            "max_budget_usd": 1.25,
        },
        "models": {surface_key: f"u4b-{surface_key}-model"},
    }


def _bedrock_settings(surface_key: str) -> dict:
    """Bedrock is the only way to make the PROVIDER leg observable: under
    `anthropic`, `provider.session_env` returns `{}` from the ledger and
    `{}` from the stage, so an equality assertion would pass on the
    broken build too. The model id deliberately does not start with
    `claude-` -- `provider.BEDROCK_ALIAS_RE` would otherwise make the
    resolution a refusal rather than an environment."""
    return {
        "provider": {
            "name": "bedrock",
            "bedrock": {
                "region": "us-east-1",
                "models": {surface_key: "us.anthropic.claude-example-v0:0"},
            },
        }
    }


def _steward_spec(home: Path, run_dir: Path) -> SessionSpec:
    """The REAL steward session spec, from the shipped constructor."""
    return steward._session_spec(home, run_dir, "PROMPT", label="u4b")


def _overseer_spec(home: Path, stage: Path, monkeypatch) -> SessionSpec:
    """The REAL overseer session spec. `overseer/run.py::_invoke` builds
    and dispatches in one expression, so the spec is captured from the
    seam rather than returned."""
    captured: list[SessionSpec] = []

    def capture(spec):
        captured.append(spec)
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(overseer_run.invocation, "write_session", capture)
    overseer_run._invoke(home, stage, "PROMPT", 30.0, "u4b", "run-u4b")
    assert len(captured) == 1
    return captured[0]


class _OptionsRecordingBackend:
    """A backend installed BELOW `invocation.write_session` -- at
    `registry.backend_for`, the lowest point that still sees the options
    the real builder produced. `write_session` at the seam is ABOVE the
    defect: a stub there sees the `SessionSpec` but never the lookups
    that read it."""

    def __init__(self, seen: list[dict], delegate) -> None:
        self._seen = seen
        self._delegate = delegate

    def write_session(self, spec: SessionSpec) -> Outcome:
        self._seen.append(backend_mod.options_kwargs(spec))
        return self._delegate(spec)

    def text_session(self, spec: SessionSpec) -> Outcome:
        return self.write_session(spec)


def _install_recording_backend(monkeypatch, delegate) -> list[dict]:
    seen: list[dict] = []
    monkeypatch.setattr(
        registry,
        "backend_for",
        lambda surface, *, home=None: _OptionsRecordingBackend(seen, delegate),
    )
    return seen


# ------------------------------------------- the stage is not the ledger


def test_a_stage_directory_answers_nothing_about_the_ledgers_settings(tmp_path):
    """The positive control every test below leans on: a cache stage
    directory really does carry no `config.yaml`, so "resolved from the
    stage" and "resolved from nowhere" are the same answer, and the
    ledger's own answer is genuinely different."""
    home = make_home(tmp_path)
    stage = tmp_path / "stage-u4b"
    stage.mkdir()
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "steward", cli))

    assert not (stage / "config.yaml").exists()
    assert settings.resolve_setting(home, settings.by_name("sdk.cli_path")) == (
        str(cli),
        "config:sdk.cli_path",
    )
    assert settings.resolve_setting(stage, settings.by_name("sdk.cli_path")) == (None, "default")


# ------------------------------------------------- the four scalar leaks


def test_a_steward_session_reads_its_settings_from_the_ledger_not_the_stage(tmp_path):
    home = make_home(tmp_path)
    run_dir = tmp_path / "steward-run-u4b"
    run_dir.mkdir()
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "steward", cli))

    spec = _steward_spec(home, run_dir)
    kwargs = backend_mod.options_kwargs(spec)

    # Where the session RUNS is unchanged -- this fix moves the SETTINGS
    # lookup only.
    assert kwargs["cwd"] == str(run_dir)
    assert spec.cwd == run_dir
    # ... and every setting comes from the ledger.
    assert kwargs["cli_path"] == str(cli)
    # The literal pairing the doctor's `sdk` row needs: the binary a
    # session will launch IS the one `provider.resolve(<ledger>, ...)`
    # reports, which is what `doctor invocation` prints. Those two
    # disagreed on 2026-09-19 and the doctor called the machine healthy.
    assert kwargs["cli_path"] == provider.resolve(home, "steward").cli_path
    assert kwargs["model"] == "u4b-steward-model"
    assert kwargs["max_turns"] == 7
    assert kwargs["max_budget_usd"] == 1.25


def test_an_overseer_session_reads_its_settings_from_the_ledger_not_the_stage(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    stage = tmp_path / "overseer-stage-u4b"
    stage.mkdir()
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "overseer", cli))

    spec = _overseer_spec(home, stage, monkeypatch)
    kwargs = backend_mod.options_kwargs(spec)

    assert kwargs["cwd"] == str(stage)
    assert spec.cwd == stage
    assert kwargs["cli_path"] == str(cli)
    # Same pairing as the steward's: session and doctor read one place.
    assert kwargs["cli_path"] == provider.resolve(home, "overseer").cli_path
    assert kwargs["model"] == "u4b-overseer-model"
    assert kwargs["max_turns"] == 7
    assert kwargs["max_budget_usd"] == 1.25


def test_a_worker_session_whose_cwd_is_the_home_resolves_exactly_as_before(tmp_path):
    """The positive control for the fallback: the worker, the
    miner-reader and the analyst still pass `cwd=home` and NO
    `ledger_home`, and must keep resolving from that `cwd`."""
    home = make_home(tmp_path)
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "worker", cli))

    spec = SessionSpec(
        surface="worker",
        prompt="PROMPT",
        cwd=home,
        timeout=30.0,
        containment=invocation.containment_for(
            "worker", home=str(home), stage_dir=home / "stage", stage_on=False
        ),
        log=lambda _msg: None,
    )
    assert spec.ledger_home is None
    kwargs = backend_mod.options_kwargs(spec)

    assert kwargs["cwd"] == str(home)
    assert kwargs["cli_path"] == str(cli)
    assert kwargs["model"] == "u4b-worker-model"
    assert kwargs["max_turns"] == 7
    assert kwargs["max_budget_usd"] == 1.25


# ------------------------------------------------------ the provider leg


def test_a_steward_session_resolves_its_provider_from_the_ledger_not_the_stage(tmp_path):
    home = make_home(tmp_path)
    run_dir = tmp_path / "steward-run-u4b"
    run_dir.mkdir()
    _write_config(home, _bedrock_settings("steward"))

    # Control first: from the stage this ledger's Bedrock configuration
    # is invisible, so `env` would be `{}` and the model an Anthropic
    # alias.
    assert provider.resolve(run_dir, "steward").provider == "anthropic"
    assert provider.session_env(provider.resolve(run_dir, "steward"), home=run_dir) == {}

    kwargs = backend_mod.options_kwargs(_steward_spec(home, run_dir))

    assert kwargs["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert kwargs["env"]["AWS_REGION"] == "us-east-1"
    assert kwargs["model"] == "us.anthropic.claude-example-v0:0"


def test_an_overseer_session_resolves_its_provider_from_the_ledger_not_the_stage(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    stage = tmp_path / "overseer-stage-u4b"
    stage.mkdir()
    _write_config(home, _bedrock_settings("overseer"))

    assert provider.resolve(stage, "overseer").provider == "anthropic"
    assert provider.session_env(provider.resolve(stage, "overseer"), home=stage) == {}

    kwargs = backend_mod.options_kwargs(_overseer_spec(home, stage, monkeypatch))

    assert kwargs["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert kwargs["env"]["AWS_REGION"] == "us-east-1"
    assert kwargs["model"] == "us.anthropic.claude-example-v0:0"


# ------------------------------------------------------ the backend leg


def test_the_backend_choice_is_made_against_the_ledger_home(tmp_path, monkeypatch):
    """`registry._dispatch` picks the backend with
    `backend_for(surface, home=...)`. Asserted on the argument the
    dispatcher passes rather than on a resolved backend: letting the
    real resolution run would build a live `SdkBackend` and start a real
    session on the broken build, which this suite must never do."""
    home = make_home(tmp_path)
    run_dir = tmp_path / "steward-run-u4b"
    stage = tmp_path / "overseer-stage-u4b"
    run_dir.mkdir()
    stage.mkdir()
    seen: list[object] = []

    class _Backend:
        def write_session(self, spec):
            return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

        def text_session(self, spec):
            return self.write_session(spec)

    def fake_backend_for(surface, *, home=None):
        seen.append(home)
        return _Backend()

    monkeypatch.setattr(registry, "backend_for", fake_backend_for)

    registry.write_session(_steward_spec(home, run_dir))
    registry.write_session(_overseer_spec(home, stage, monkeypatch))

    assert seen == [home, home]


# ------------------------------------------------- the repair round


def test_the_steward_repair_round_keeps_the_ledger_home(tmp_path):
    """`_repair_spec` rebuilds the spec field by field; a rebuild that
    forgot `ledger_home` would send the SECOND call of a two-call packet
    back to the bundled binary."""
    home = make_home(tmp_path)
    run_dir = tmp_path / "steward-run-u4b"
    run_dir.mkdir()
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "steward", cli))

    repair = steward._repair_spec(_steward_spec(home, run_dir), "validation failed")

    assert repair.cwd == run_dir
    assert backend_mod.options_kwargs(repair)["cli_path"] == str(cli)


# --------------------------------------------------- end to end per runner


def test_a_steward_dry_run_launches_the_binary_the_ledger_names(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "steward", cli))
    seen = _install_recording_backend(monkeypatch, _write_decision_stage)

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run"
    assert seen, "the steward made no model call, so this proves nothing"
    assert [kwargs["cli_path"] for kwargs in seen] == [str(cli)] * len(seen)
    assert [kwargs["model"] for kwargs in seen] == ["u4b-steward-model"] * len(seen)


def _overseer_two_phase(spec) -> Outcome:
    """The stage files each overseer phase must find, mirroring
    `test_overseer_run.py::_fake_two_phase`'s shape."""
    stage = spec.cwd
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    if not (stage / "selection.yaml").exists():
        for name, data in (
            ("selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "empty"}),
            ("initial-views.yaml", {"cases": []}),
        ):
            buf = io.StringIO()
            yaml.dump(data, buf)
            (stage / name).write_text(buf.getvalue(), encoding="utf-8")
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    lines = ["# model draft"]
    for heading in (
        "Examined",
        "Decided in the user's stead",
        "Hooks",
        "User model",
        "Catalogue health",
        "Questions for you",
        "Refused / could not do",
    ):
        lines.extend([f"## {heading}", "- none"])
    (stage / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, data in (
        ("sheet.yaml", {"version": 1, "items": []}),
        ("findings.yaml", {"findings": []}),
        ("questions.yaml", {"questions": []}),
        ("user-model-delta.yaml", {"updates": []}),
    ):
        buf = io.StringIO()
        yaml.dump(data, buf)
        (stage / name).write_text(buf.getvalue(), encoding="utf-8")
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def test_an_overseer_dry_run_launches_the_binary_the_ledger_names(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    cli = tmp_path / "u4b-claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_config(home, _anthropic_settings(home, "overseer", cli))
    seen = _install_recording_backend(monkeypatch, _overseer_two_phase)

    overseer_run.run(home, dry_run=True)

    assert seen, "the overseer made no model call, so this proves nothing"
    assert [kwargs["cli_path"] for kwargs in seen] == [str(cli)] * len(seen)
    assert [kwargs["model"] for kwargs in seen] == ["u4b-overseer-model"] * len(seen)
