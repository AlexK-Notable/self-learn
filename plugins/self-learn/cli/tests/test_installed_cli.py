"""U4c -- with `sdk.cli_path` unset, self-learn passes the Claude Code
the PERSON has installed; the SDK's bundled copy is only the fallback.

Before this unit an unset `sdk.cli_path` meant self-learn passed no
`cli_path` at all, and `claude_agent_sdk`'s own `_find_cli` then picked
its BUNDLED binary first (2.1.226 in the pinned SDK). `claude-fable-5-1`
-- the steward's and the overseer's model -- needs 2.1.251 or later, so a
default install could not run either of them: that is the 2026-09-14
outage. The rule now is: an explicit setting wins; otherwise the
installed binary (PATH first, then the locations the SDK itself looks
in); otherwise nothing is passed and the SDK falls back to its bundled
copy exactly as before.

Every expectation below is written from that rule, never from what the
code returns.

**No real `claude` is ever found, spawned, or probed here.** Two
mechanisms keep that true. First, `tests/conftest.py` replaces
`SubprocessCLITransport._find_cli` with a tripwire for the whole
session, and `provider.resolve_cli_choice` consults that resolver before
it will override the SDK's choice -- so a test that does not deliberately
answer for the SDK gets today's behaviour (`cli_path=None`) and the
developer's own `claude` never reaches a session. Every test below that
wants the new rule exercised says so out loud with `_sdk_answers`.
Second, PATH and HOME are redirected at empty scratch directories by
`_nothing_installed`, so `shutil.which("claude")` and the known-location
sweep can only ever find a file the test itself wrote. The `--version`
probe is stubbed at `subprocess.run`, the same seam
`test_doctor_invocation.py` uses.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import types
from pathlib import Path

import pytest
from ruamel.yaml import YAML

import claude_agent_sdk._internal.transport.subprocess_cli as subprocess_cli_mod
from self_learn import provider, settings, steward
from self_learn.invocation.contract import SessionSpec, containment_for
from self_learn.invocation_sdk import backend as backend_mod

from support import commit_all, make_home

_ENV_VARS = (
    "SELF_LEARN_SDK_CLI_PATH",
    "SELF_LEARN_SDK_PREFER_INSTALLED_CLI",
    "SELF_LEARN_SDK_MODEL_CLI_FLOORS",
    "SELF_LEARN_PROVIDER",
    "SELF_LEARN_BACKEND",
    "SELF_LEARN_STEWARD_MODEL",
    "SELF_LEARN_WORKER_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch):
    """`sdk.cli_path` is env-first and `sdk.prefer_installed_cli` reads
    the same channel: a leftover variable in the operator's own shell
    would mask every assertion in this file."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------- helpers


def _write_config(home: Path, data: dict) -> None:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    (home / "config.yaml").write_text(buf.getvalue(), encoding="utf-8")
    commit_all(home, "u4c: ledger settings")


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho 'u4c-fake (Claude Code)'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture()
def _nothing_installed(tmp_path, monkeypatch) -> Path:
    """An empty PATH and an empty HOME: no `claude` is installed
    anywhere this machine's real filesystem would be consulted for.
    Returns the scratch HOME, so a test can plant a binary inside it.

    This is the POSITIVE CONTROL for every "found it" assertion below --
    without it, the developer's own `/home/.../claude` would satisfy
    them and the tests would pass on a build that resolved nothing.

    The scratch PATH carries a symlink to the real `git` and nothing
    else: the ledger fixtures below run real git commands, and a
    genuinely empty PATH would fail them for an unrelated reason.

    **One known location cannot be redirected by an environment
    variable: `/usr/local/bin/claude` is absolute.** On a machine that
    has one, it would be found by every test below and two of them
    would report the wrong binary — so the search list is narrowed HERE
    to the entries that live under the scratch `HOME`. The real list's
    own shape is pinned separately, by
    `test_the_mirrored_install_locations_are_the_sdks_own_list`, so
    narrowing it here hides nothing."""
    real_git = shutil.which("git")
    assert real_git, "no git on PATH"
    scratch_bin = tmp_path / "scratch-bin"
    scratch_bin.mkdir()
    (scratch_bin / "git").symlink_to(real_git)
    assert shutil.which("claude", path=str(scratch_bin)) is None
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("PATH", str(scratch_bin))
    monkeypatch.setenv("HOME", str(fake_home))

    real_locations = provider._installed_cli_locations
    monkeypatch.setattr(
        provider,
        "_installed_cli_locations",
        lambda: tuple(p for p in real_locations() if str(p).startswith(str(fake_home))),
    )
    assert provider._installed_cli_locations(), "the scratch HOME must keep some locations"
    return fake_home


def _sdk_answers(monkeypatch, tmp_path) -> Path:
    """Answer for the SDK's own resolver, which `tests/conftest.py`
    otherwise hard-blocks for the whole session. Returns the path that
    stands in for the SDK's bundled binary -- what would run if
    self-learn passed nothing."""
    bundled = _executable(tmp_path / "sdk-bundled" / "claude")
    monkeypatch.setattr(
        subprocess_cli_mod.SubprocessCLITransport, "_find_cli", lambda self: str(bundled)
    )
    return bundled


def _on_path(tmp_path, monkeypatch) -> Path:
    """An installed `claude`, reachable on PATH and nowhere else. The
    scratch PATH `_nothing_installed` built is kept behind it, so the
    ledger fixtures' real git calls keep working."""
    binary = _executable(tmp_path / "path-dir" / "claude")
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ['PATH']}")
    return binary


def _spec(home: Path, cwd: Path) -> SessionSpec:
    """A worker-shaped spec whose `cwd` IS the ledger -- the simple
    case. The steward's (whose `cwd` is not the ledger) is built from
    the shipped constructor in the agreement test below."""
    return SessionSpec(
        surface="worker",
        prompt="ok",
        cwd=cwd,
        timeout=20.0,
        containment=containment_for(
            "worker",
            allowed_tools="Read",
            disallowed_tools="Bash",
            home=str(home),
            stage_dir=home / "stage",
            stage_on=False,
        ),
        log=lambda _msg: None,
        ledger_home=home,
    )


_FAKE_SDK = types.SimpleNamespace(
    __version__="0.2.999",
    _cli_version=types.SimpleNamespace(__cli_version__="2.1.226"),
)


def _importer():
    return _FAKE_SDK


def _stub_version(monkeypatch, version: str):
    """Pin what the operative binary reports without running one -- the
    seam `test_doctor_invocation.py`'s own U4 tests stub."""
    monkeypatch.setattr(
        provider, "_operative_cli_version", lambda home=None: (version, "")
    )


# ------------------------------------------------- rule 1: PATH is first


def test_an_unset_setting_takes_the_claude_on_path(tmp_path, monkeypatch, _nothing_installed):
    """Rule: with `sdk.cli_path` unset, the binary the person has
    installed is used, PATH first. The session must carry THAT path, and
    the doctor row must name it and say which rule chose it."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    installed = _on_path(tmp_path, monkeypatch)

    choice = provider.resolve_cli_choice(home)
    assert choice.path == str(installed)
    assert choice.rule == "installed (PATH)"

    kwargs = backend_mod.options_kwargs(_spec(home, home))
    assert kwargs["cli_path"] == str(installed)

    _stub_version(monkeypatch, "2.1.278")
    row = provider._sdk_row(home, importer=_importer)
    assert str(installed) in row.detail
    assert "installed (PATH)" in row.detail
    # The floor is met by 2.1.278, so the row is no longer loud -- which
    # is the whole point of the change.
    assert row.verdict in ("PASS", "INFO"), row.detail


# -------------------------------------- rule 1: then the known locations


def test_a_known_install_location_is_used_when_path_has_nothing(
    tmp_path, monkeypatch, _nothing_installed
):
    """Rule: PATH first, then the same install locations the SDK itself
    falls back to. `~/.local/bin/claude` is one of them; with HOME
    pointed at a scratch directory it is the only `claude` in
    existence."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    installed = _executable(_nothing_installed / ".local" / "bin" / "claude")

    choice = provider.resolve_cli_choice(home)
    assert choice.path == str(installed)
    assert choice.rule == f"installed ({installed})"

    kwargs = backend_mod.options_kwargs(_spec(home, home))
    assert kwargs["cli_path"] == str(installed)

    _stub_version(monkeypatch, "2.1.278")
    row = provider._sdk_row(home, importer=_importer)
    assert str(installed) in row.detail


def test_path_beats_a_known_location(tmp_path, monkeypatch, _nothing_installed):
    """The ORDER, not merely the membership: with a binary in both
    places the PATH one wins. A resolver that swept the locations first
    would pass every other test in this file."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    at_location = _executable(_nothing_installed / ".local" / "bin" / "claude")
    on_path = _on_path(tmp_path, monkeypatch)

    choice = provider.resolve_cli_choice(home)
    assert choice.path == str(on_path)
    assert choice.path != str(at_location)


def test_the_mirrored_install_locations_are_the_sdks_own_list(tmp_path, monkeypatch):
    """The list is copied from the SDK by hand, so its shape is pinned
    here rather than left to the tests that happen to exercise one
    entry: six locations, in the SDK's own order, five under `HOME` and
    one absolute — and rebuilt per call, so `HOME` is honoured.

    (`_nothing_installed` narrows this list to the `HOME`-relative
    entries; this test does not use that fixture, so it sees the real
    one.)"""
    fake_home = tmp_path / "list-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    assert provider._installed_cli_locations() == (
        fake_home / ".npm-global/bin/claude",
        Path("/usr/local/bin/claude"),
        fake_home / ".local/bin/claude",
        fake_home / "node_modules/.bin/claude",
        fake_home / ".yarn/bin/claude",
        fake_home / ".claude/local/claude",
    )


# ------------------------------------------ rule 1: nothing installed


def test_nothing_installed_passes_nothing_and_a_floor_still_fails(
    tmp_path, monkeypatch, _nothing_installed
):
    """Rule: when no installed binary exists, self-learn passes nothing
    and the SDK falls back to its bundled copy exactly as before -- and
    the doctor must still FAIL when that bundled copy is below a
    selected model's floor, now also telling the reader to install or
    update Claude Code."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)

    choice = provider.resolve_cli_choice(home)
    assert choice.path is None
    assert choice.rule == "bundled fallback (no installed claude found)"

    kwargs = backend_mod.options_kwargs(_spec(home, home))
    assert kwargs["cli_path"] is None

    # The steward's and the overseer's default model is `claude-fable-5-1`,
    # whose registered floor is 2.1.251; the bundled copy reports 2.1.226.
    _stub_version(monkeypatch, "2.1.226")
    row = provider._sdk_row(home, importer=_importer)
    assert row.verdict == "FAIL", row.detail
    assert "bundled fallback (no installed claude found)" in row.detail
    assert "install or update Claude Code" in row.detail
    assert "sdk.cli_path" in row.detail  # the old fix is still offered


# ------------------------------------- rule 2: an explicit setting wins


def test_an_explicit_cli_path_beats_an_installed_binary_from_config_yaml(
    tmp_path, monkeypatch, _nothing_installed
):
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    _on_path(tmp_path, monkeypatch)
    pinned = _executable(tmp_path / "pinned" / "claude")
    _write_config(home, {"sdk": {"cli_path": str(pinned)}})

    choice = provider.resolve_cli_choice(home)
    assert choice.path == str(pinned)
    assert choice.rule == "explicit sdk.cli_path"
    assert backend_mod.options_kwargs(_spec(home, home))["cli_path"] == str(pinned)


def test_an_explicit_cli_path_beats_an_installed_binary_from_the_env_var(
    tmp_path, monkeypatch, _nothing_installed
):
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    _on_path(tmp_path, monkeypatch)
    pinned = _executable(tmp_path / "pinned-env" / "claude")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(pinned))

    choice = provider.resolve_cli_choice(home)
    assert choice.path == str(pinned)
    assert choice.rule == "explicit sdk.cli_path"
    assert backend_mod.options_kwargs(_spec(home, home))["cli_path"] == str(pinned)


# ------------------------------------------------ rule 3: the opt-out


def test_prefer_installed_cli_false_restores_the_old_order(
    tmp_path, monkeypatch, _nothing_installed
):
    """The opt-out exists because an installed binary updates itself
    while the SDK was built against the bundled one. `false` must
    restore exactly today's behaviour: pass nothing, let the SDK
    choose."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    installed = _on_path(tmp_path, monkeypatch)
    _write_config(home, {"sdk": {"prefer_installed_cli": False}})

    choice = provider.resolve_cli_choice(home)
    assert choice.path is None
    assert "sdk.prefer_installed_cli" in choice.rule
    assert backend_mod.options_kwargs(_spec(home, home))["cli_path"] is None

    # Positive control: the same ledger with the setting left alone DOES
    # take the installed binary, so the assertions above are about the
    # setting and not about a resolver that never worked.
    (home / "config.yaml").unlink()
    commit_all(home, "u4c: drop the opt-out")
    assert provider.resolve_cli_choice(home).path == str(installed)


def test_the_opt_out_is_a_registered_setting(tmp_path):
    """Registry shape, not behaviour: config-first, boolean, default
    true, with its own config.yaml rung -- the pattern
    `runs.attempt_cap` and `sdk.model_cli_floors` follow."""
    entry = settings.by_name("sdk.prefer_installed_cli")
    assert entry.kind == "bool"
    assert entry.default is True
    assert entry.direction == "config-first"
    assert (entry.config_section, entry.config_key) == ("sdk", "prefer_installed_cli")
    home = make_home(tmp_path)
    assert settings.resolve_setting(home, entry) == (True, "default")


# ------------------------------- one resolver: the two faces must agree


def test_the_launcher_and_the_doctor_choose_the_same_binary(
    tmp_path, monkeypatch, _nothing_installed
):
    """The 2026-09-19 defect in one sentence: the doctor reported one
    binary while a session launched another. A steward session's `cwd`
    is a run directory, NOT the ledger -- the case that broke -- so this
    drives the real steward spec and asserts that what the session
    carries, what `doctor invocation` probes, and what the row prints
    are all the one binary."""
    home = make_home(tmp_path)
    _sdk_answers(monkeypatch, tmp_path)
    installed = _on_path(tmp_path, monkeypatch)

    run_dir = tmp_path / "steward-run-u4c"
    run_dir.mkdir()
    spec = steward._session_spec(home, run_dir, "PROMPT", label="u4c")
    kwargs = backend_mod.options_kwargs(spec)

    assert kwargs["cwd"] == str(run_dir)  # where it RUNS is unchanged
    assert kwargs["cli_path"] == str(installed)

    # What the doctor probes: the argv, captured at `subprocess.run`, no
    # binary ever executed.
    argvs: list[list[str]] = []

    def _fake_run(argv, *a, **kw):
        argvs.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "2.1.278 (Claude Code)\n", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    version, reason = provider._operative_cli_version(home)
    assert (version, reason) == ("2.1.278", "")
    assert argvs == [[str(installed), "--version"]], argvs

    row = provider._sdk_row(home, importer=_importer)
    assert str(installed) in row.detail


# ------------------------------------------- the suite's own safety net


def test_self_learn_never_overrides_a_sdk_resolver_that_did_not_answer(tmp_path, monkeypatch):
    """Deliberate, and the reason `test_invocation_sdk.py`'s armored
    `test_op15` stays green: self-learn only substitutes its own choice
    when `claude_agent_sdk`'s own resolver actually answered. In
    production it always does -- the wheel bundles a binary, found
    first -- so this leg costs nothing there. In the test suite
    `tests/conftest.py` hard-blocks that resolver, so no test can be
    handed the developer's real, credentialed `claude` by accident.

    Note the PATH here is the real one: `claude` genuinely is installed
    on this machine, and the point is that it is still not used."""
    home = make_home(tmp_path)
    choice = provider.resolve_cli_choice(home)
    assert choice.path is None
    assert "did not answer" in choice.rule
    assert backend_mod.options_kwargs(_spec(home, home))["cli_path"] is None
