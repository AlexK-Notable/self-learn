"""U-bedrock — `DC` criteria: `self-learn doctor invocation` (see
`docs/specs/self-learn/drafts/u-bedrock-provider-spec.md` §3.8/§4).

Fixtures never carry a real Bedrock model id or anything credential-
shaped (`D-6`, `SEC-1`) — see `test_provider.py`'s module docstring for
the placeholder table; `MD6` enforces the boundary over both test files.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from self_learn import cli as cli_mod
from self_learn import provider

BEDROCK_ID = "us.anthropic.claude-example-v0:0"
BEDROCK_ID_2 = "us.anthropic.example-model-v0:0"
ALIAS = "claude-sonnet-5"
BEDROCK_ARN = "arn:aws:bedrock:us-east-1:000000000000:inference-profile/example-profile"
SANDBOX_PROFILE = "sandbox-profile"

_PROVIDER_ENV_VARS = (
    "SELF_LEARN_PROVIDER",
    "SELF_LEARN_BEDROCK_REGION",
    "SELF_LEARN_BEDROCK_PROFILE",
    "SELF_LEARN_SDK_CLI_PATH",
    "SELF_LEARN_WORKER_MODEL",
    "SELF_LEARN_MINER_MODEL",
    "SELF_LEARN_ANALYST_MODEL",
    "SELF_LEARN_BACKEND",
    "SELF_LEARN_BACKEND_WORKER",
    "SELF_LEARN_BACKEND_MINER",
    "SELF_LEARN_BACKEND_ANALYST",
    # U4 (S-68): the floor setting's own env rung, plus the two model
    # selectors whose default (`claude-fable-5-1`) is the ONE model with
    # a shipped floor — a host that exports either would silently change
    # which surfaces this file's floor assertions are about.
    "SELF_LEARN_SDK_MODEL_CLI_FLOORS",
    "SELF_LEARN_STEWARD_MODEL",
    "SELF_LEARN_OVERSEER_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


def _write_provider_yaml(home: Path, *, name: str | None = None, bedrock: dict | None = None) -> None:
    home.mkdir(parents=True, exist_ok=True)
    lines = ["provider:"]
    if name is not None:
        lines.append(f"  name: {name}")
    if bedrock:
        lines.append("  bedrock:")
        if "region" in bedrock:
            lines.append(f"    region: {bedrock['region']}")
        if "profile" in bedrock:
            lines.append(f"    profile: {bedrock['profile']}")
        if "models" in bedrock:
            lines.append("    models:")
            for key, value in bedrock["models"].items():
                lines.append(f"      {key}: {value}")
    (home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(argv, capsys):
    rc = cli_mod.main(argv)
    out = capsys.readouterr().out
    return rc, out


def _rows_by_name(out: str, name: str) -> list[str]:
    prefix = f"doctor: "
    lines = [ln for ln in out.splitlines() if ln.startswith(prefix)]
    result = []
    for ln in lines:
        body = ln[len(prefix) :]
        if body.startswith("---") or body.startswith("handoff:"):
            continue
        verdict, _, rest = body.partition(" ")
        row_name, _, detail = rest.partition(" — ")
        if row_name == name:
            result.append(f"{verdict} {detail}")
    return result


def test_dc1_pristine_home_zero_fail_all_rows_once(capsys):
    rc, out = _run(["doctor", "invocation"], capsys)
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.startswith("doctor: ") and "---" not in ln and "handoff" not in ln]
    for ln in lines:
        assert " FAIL " not in ln
    single_line_rows = ("switches", "provider", "config", "sdk", "rollout", "region", "credentials", "orphans", "ui")
    for row in single_line_rows:
        assert len(_rows_by_name(out, row)) == 1, row
    assert len(_rows_by_name(out, "models")) == 7  # 6 surfaces + small_fast (U8: +steward/+overseer)
    assert len(_rows_by_name(out, "env")) == 6  # U8: +steward/+overseer
    assert len(_rows_by_name(out, "consistency")) == 0

    # row order
    seen_order = []
    for ln in lines:
        body = ln[len("doctor: ") :]
        _verdict, _, rest = body.partition(" ")
        name, _, _detail = rest.partition(" — ")
        if not seen_order or seen_order[-1] != name:
            seen_order.append(name)
    # consistency never appears (0 lines); every other row does, in order
    expected = [r for r in provider.DOCTOR_ROWS if r != "consistency"]
    assert seen_order == expected


def test_dc2_switches_names_all_surfaces_and_changes_with_rung(monkeypatch, capsys):
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    # U-sdka flipped the analyst's default to sdk (§9 E7); U-flip flipped
    # the remaining three (worker/worker-repair/miner-reader) the same
    # way -- every surface now shows "sdk (default)".
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        assert f"{surface}: backend=sdk (default)" in line

    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    assert "worker: backend=sdk (env:SELF_LEARN_BACKEND_WORKER)" in line
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")

    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    assert "worker: backend=sdk (env:SELF_LEARN_BACKEND)" in line
    monkeypatch.delenv("SELF_LEARN_BACKEND")


def test_dc3_rollout_four_states(monkeypatch, capsys, _home):
    # wholly-inert -> FAIL. U-sdka flipped the analyst's default to sdk;
    # U-flip flipped the remaining three the same way, so every surface
    # now defaults to sdk. This state must now be CONSTRUCTED by pinning
    # ALL FOUR surfaces back to cli -- the general env rung does that in
    # one shot (no more specific selector pin is set) -- without it no
    # surface is cli by default, and the rollout is no longer wholly
    # inert (see DR3, test_u_sdka.py).
    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    _write_provider_yaml(_home, name="bedrock")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "rollout")
    assert line.startswith("FAIL")
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # mixed -> no FAIL row anywhere, exit 0. worker/worker-repair/
    # miner-reader/steward/overseer (U8: joins this pin -- its sdk
    # default would otherwise FAIL the "models" row too, same reason as
    # worker/miner below) are pinned back to cli so only the analyst
    # resolves sdk, matching the bedrock config below (which names a
    # model for "analyst" only).
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_STEWARD", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_OVERSEER", "cli")
    rc, out = _run(["doctor", "invocation"], capsys)
    assert rc == 0
    body_lines = [ln for ln in out.splitlines() if ln.startswith("doctor: ") and "handoff" not in ln]
    assert not any(" FAIL " in ln for ln in body_lines)
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")
    monkeypatch.delenv("SELF_LEARN_BACKEND_STEWARD")
    monkeypatch.delenv("SELF_LEARN_BACKEND_OVERSEER")

    # all-sdk -> PASS
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={
            "region": "us-east-1",
            "models": {
                "worker": BEDROCK_ID,
                "miner": BEDROCK_ID,
                "analyst": BEDROCK_ID,
                "steward": BEDROCK_ID,
                "overseer": BEDROCK_ID,
            },
        },
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "rollout")
    assert line.startswith("PASS")
    # U8 fold r1 (gate S1): the detail text counts and names every surface —
    # a stale "four" survived the widening to six because only the verdict
    # prefix was asserted here.
    assert f"all {len(provider.SURFACES)} surfaces resolve backend=sdk" in line
    for s in provider.SURFACES:
        assert s in line, s
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # anthropic -> SKIP regardless of backend
    _write_provider_yaml(_home, name="anthropic")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "rollout")
    assert line.startswith("SKIP")


def test_dc4_sdk_row_injected_importer(monkeypatch):
    fake = types.SimpleNamespace(__version__="0.2.999", _cli_version=types.SimpleNamespace(__cli_version__="2.1.999"))

    def _match_importer():
        return fake

    def _operative_match(home=None):
        return "2.1.999", ""

    monkeypatch.setattr(provider, "_operative_cli_version", _operative_match)
    row = provider._sdk_row(importer=_match_importer)
    assert row.verdict == "PASS"

    def _operative_differ(home=None):
        return "2.1.212", ""

    monkeypatch.setattr(provider, "_operative_cli_version", _operative_differ)
    row2 = provider._sdk_row(importer=_match_importer)
    # U4 (S-68): bundled-vs-operative inequality ALONE is INFO now, not
    # WARN — pointing `sdk.cli_path` at a newer system binary than the
    # wheel bundles is the normal state on a machine that updates Claude
    # Code independently. The loud verdicts belong to the version FLOOR
    # (see the `test_u4_*` tests below).
    assert row2.verdict == "INFO"

    def _raises_import_error():
        raise ImportError("no sdk")

    row3 = provider._sdk_row(importer=_raises_import_error)
    assert row3.verdict == "SKIP"

    # `B-5`: the operative pair (SDK-resolved cli vs the declared
    # bundled requirement) decides the verdict -- the host `claude` on
    # PATH is a labeled context line ONLY, never a WARN source. A host
    # that differs wildly from the bundled requirement must still PASS
    # when the operative probe matches it.
    #
    # MUTATION that turns this red: revert `_sdk_row` to compare
    # `_host_cli_context()` (or the old `_host_cli_version()`) against
    # `bundled` instead of `_operative_cli_version()` -- this sub-test
    # would then read WARN (host "9.9.9-unrelated-tool" != bundled
    # "2.1.999"), not PASS.
    monkeypatch.setattr(provider, "_operative_cli_version", _operative_match)
    monkeypatch.setattr(provider, "_host_cli_context", lambda: "9.9.9-unrelated-tool")
    row_host_differs = provider._sdk_row(importer=_match_importer)
    assert row_host_differs.verdict == "PASS"
    assert "9.9.9-unrelated-tool" in row_host_differs.detail  # still surfaced, as context

    # the real importer must not raise
    row4 = provider._sdk_row()
    assert row4.verdict in provider.VERDICTS


def test_dc4b_operative_probe_executes_the_binary_a_session_would_launch(monkeypatch, tmp_path):
    """B-5 MAJOR (gate r1 on M-L): every assertion in `test_dc4` above
    stubs `_operative_cli_version` itself -- one seam above the real
    resolution and the real `subprocess.run` call -- so none of them ever
    exercise the SDK integration or observe WHICH binary actually gets
    executed. This test instead fakes only the SDK's own `_find_cli`
    (`tests/conftest.py` otherwise blocks it for the whole session) and
    `shutil.which("claude")`, lets `resolve_cli_choice`,
    `_operative_cli_version` and `_sdk_row` all run for real, and spies
    on `subprocess.run` to pin the literal argv executed.

    **The rule this pins changed on 2026-09-19 (U4c, S-70), and the
    change is the point of that unit.** B-5's original rule was "the
    operative binary is what `_find_cli` resolves, NEVER whatever
    `claude` is on PATH" -- correct while an unset `sdk.cli_path` meant
    the SDK chose, bundled copy first. With the installed binary now
    preferred by default, the PATH `claude` IS what a session launches,
    so the doctor must probe exactly that; probing the SDK's bundled
    copy instead would recreate the disagreement B-5 exists to prevent,
    pointing the other way. The invariant is unchanged and is what both
    halves below assert: **the doctor probes the binary a session would
    launch.** Case 3 keeps the ORIGINAL expectation under the opt-out,
    where the SDK's order is restored and B-5's literal wording again
    describes the behaviour.

    MUTATION that turns this red: make `_operative_cli_version` resolve
    anything other than `resolve_cli_choice`'s answer -- model
    `_find_cli` directly again (cases 1 and 2 execute the wrong script),
    or read `shutil.which("claude")` unconditionally (case 3 does)."""
    import claude_agent_sdk._internal.transport.subprocess_cli as subprocess_cli_mod

    def _make_fake_cli(name: str, version_line: str) -> Path:
        script = tmp_path / name
        script.write_text(f"#!/bin/sh\necho '{version_line}'\n")
        script.chmod(0o755)
        return script

    calls: list[list[str]] = []
    real_run = subprocess.run

    def _spy_run(argv, *a, **kw):
        calls.append(list(argv))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _spy_run)

    sdk_script_x = _make_fake_cli("sdk-claude-x", "1.0.0 (Claude Code)")
    path_script_y = _make_fake_cli("path-claude-y", "9.9.9 (Claude Code)")
    real_which = shutil.which

    def _fake_which(name, *a, **kw):
        if name == "claude":
            return str(path_script_y)
        return real_which(name, *a, **kw)

    monkeypatch.setattr(shutil, "which", _fake_which)

    fake = types.SimpleNamespace(
        __version__="0.2.999",
        _cli_version=types.SimpleNamespace(__cli_version__="9.9.9"),
    )

    # -- Case 1 (U4c): nothing pins the binary, so the INSTALLED one --
    # the PATH `claude`, "9.9.9" -- is what a session launches and what
    # the probe must execute. The bundled requirement is "9.9.9" here,
    # so the pair matches and the row PASSes.
    monkeypatch.setattr(
        subprocess_cli_mod.SubprocessCLITransport, "_find_cli", lambda self: str(sdk_script_x)
    )
    row = provider._sdk_row(importer=lambda: fake)
    assert row.verdict == "PASS", row.detail
    assert calls == [[str(path_script_y), "--version"]], calls
    assert "installed (PATH)" in row.detail
    assert str(path_script_y) in row.detail

    # -- Case 2 (U4c): an EXPLICIT `sdk.cli_path` still outranks the
    # installed binary, and the probe follows it -- "1.0.0" against a
    # "9.9.9" bundled requirement, so the row is INFO naming both.
    calls.clear()
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(sdk_script_x))
    row2 = provider._sdk_row(importer=lambda: fake)
    assert row2.verdict == "INFO", row2.detail
    assert "1.0.0" in row2.detail and "9.9.9" in row2.detail
    assert calls == [[str(sdk_script_x), "--version"]], calls
    assert "explicit sdk.cli_path" in row2.detail
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH")

    # -- Case 3: B-5's ORIGINAL expectation, preserved where it still
    # applies. With `sdk.prefer_installed_cli` off the SDK's own order is
    # restored, so the SDK-resolved script runs and the PATH `claude`
    # ("9.9.9") is never touched even though `shutil.which` answers for
    # it -- the row surfaces it as context only.
    calls.clear()
    monkeypatch.setenv("SELF_LEARN_SDK_PREFER_INSTALLED_CLI", "0")
    sdk_script_z = _make_fake_cli("sdk-claude-z", "2.0.0 (Claude Code)")
    monkeypatch.setattr(
        subprocess_cli_mod.SubprocessCLITransport, "_find_cli", lambda self: str(sdk_script_z)
    )
    row3 = provider._sdk_row(importer=lambda: fake)
    assert row3.verdict == "INFO", row3.detail
    assert "2.0.0" in row3.detail and "9.9.9" in row3.detail
    assert calls == [[str(sdk_script_z), "--version"]], calls
    assert str(path_script_y) in row3.detail  # context, never executed


# ------------------------------------------------------------------ U4
# (S-68): the `sdk` row knows what Claude Code version the SELECTED model
# needs. On 2026-09-14 this row said PASS while the steward could not run
# at all: the SDK launched its bundled 2.1.226 and `claude-fable-5-1`
# needs 2.1.251 ("API Error: 400 Claude Code 2.1.226 does not support
# this model"). Nothing compared the operative binary against what the
# model needs; equality with the bundled copy was the only test.
#
# No test below spawns a real `claude`: every one stubs
# `provider._operative_cli_version`, the same seam `test_dc4` uses.

_U4_SDK = types.SimpleNamespace(
    __version__="0.2.999",
    _cli_version=types.SimpleNamespace(__cli_version__="2.1.226"),
)


def _u4_importer():
    return _U4_SDK


def _u4_operative(monkeypatch, version, reason=""):
    """Pin what the operative binary reports, without running one."""
    monkeypatch.setattr(
        provider, "_operative_cli_version", lambda home=None: (version, reason)
    )


def _write_yaml(home: Path, text: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(text, encoding="utf-8")


def test_u4_floor_fail_names_surface_model_operative_version_and_the_fix(monkeypatch, _home):
    """The 2026-09-14 state, reproduced: a pristine home selects
    `claude-fable-5-1` for the steward and overseer surfaces, and the
    operative binary is the SDK's bundled 2.1.226.

    MUTATION that turns this red: drop the floor comparison from
    `_sdk_row` (or compare `bundled` instead of `resolved`) — the row
    reads PASS, exactly as it did on the day the steward could not run."""
    _u4_operative(monkeypatch, "2.1.226")
    row = provider._sdk_row(_home, importer=_u4_importer)

    assert row.verdict == "FAIL", row.detail
    assert "steward" in row.detail
    assert "overseer" in row.detail
    assert "claude-fable-5-1" in row.detail
    assert "2.1.226" in row.detail  # the operative version
    assert "2.1.251" in row.detail  # the floor
    assert "sdk.cli_path" in row.detail  # the fix


def test_u4_operative_at_or_above_the_floor_is_not_a_fail(monkeypatch, _home):
    """The state on this machine once `sdk.cli_path` points at the system
    binary: floor satisfied, bundled still older — INFO, never FAIL and
    never WARN."""
    _u4_operative(monkeypatch, "2.1.278")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "INFO", row.detail
    assert "2.1.278" in row.detail

    # exactly AT the floor is satisfied, not violated
    _u4_operative(monkeypatch, "2.1.251")
    at_floor = provider._sdk_row(_home, importer=_u4_importer)
    assert at_floor.verdict == "INFO", at_floor.detail


def test_u4_version_comparison_is_numeric_per_component_not_lexicographic(monkeypatch, _home):
    """`2.1.30 < 2.1.251` numerically, but `"2.1.30" > "2.1.251"` as
    strings — a string compare reports the broken binary as fine.

    MUTATION that turns this red: compare the raw strings (`resolved <
    floor`) instead of the parsed tuples — the first leg below reads
    INFO instead of FAIL."""
    _u4_operative(monkeypatch, "2.1.30")
    older = provider._sdk_row(_home, importer=_u4_importer)
    assert older.verdict == "FAIL", older.detail

    # a bigger MINOR component wins over a bigger patch component
    _write_yaml(_home, "sdk:\n  model_cli_floors: claude-fable-5-1=2.9.9\n")
    _u4_operative(monkeypatch, "2.10.0")
    newer = provider._sdk_row(_home, importer=_u4_importer)
    assert newer.verdict == "INFO", newer.detail

    # the helper's own boundary cases, including zero padding
    assert provider._parse_cli_version("2.1.251") == (2, 1, 251)
    assert provider._parse_cli_version("2.1.251-rc1") is None
    assert provider._parse_cli_version("") is None
    assert provider._version_older((2, 1, 30), (2, 1, 251)) is True
    assert provider._version_older((2, 1, 251), (2, 1, 226)) is False
    assert provider._version_older((2, 10, 0), (2, 9, 9)) is False
    assert provider._version_older((2, 1), (2, 1, 0)) is False
    assert provider._version_older((2, 1, 0), (2, 1)) is False


def test_u4_a_model_with_no_registered_floor_never_fails_and_never_warns(monkeypatch, _home):
    """The Sonnet/Opus surfaces today. "No floor is registered" is a
    different fact from "the floor is satisfied", and it must not become
    loud in either direction.

    MUTATION that turns this red: treat a missing floor as `"0"`-and-
    compare, or make any unregistered model WARN — this reads WARN or
    FAIL instead of PASS."""
    _write_yaml(
        _home,
        "models:\n  steward: claude-sonnet-5\n  overseer: claude-sonnet-5\n",
    )
    _u4_operative(monkeypatch, "2.1.226")  # equal to bundled
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "PASS", row.detail
    assert "claude-fable-5-1" not in row.detail

    # and an ancient operative binary with no floor in play is still not
    # a FAIL — there is nothing registered to compare it against
    _u4_operative(monkeypatch, "1.0.0")
    ancient = provider._sdk_row(_home, importer=_u4_importer)
    assert ancient.verdict == "INFO", ancient.detail


def test_u4_bundled_vs_operative_difference_alone_is_info_not_warn(monkeypatch, _home):
    """Nothing but the two versions differing, with no floor in play.

    MUTATION that turns this red: restore the old `if resolved !=
    bundled: WARN` — this reads WARN."""
    _write_yaml(
        _home,
        "models:\n  steward: claude-sonnet-5\n  overseer: claude-sonnet-5\n",
    )
    _u4_operative(monkeypatch, "2.1.278")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "INFO", row.detail
    assert "differ" in row.detail


def test_u4_unprobed_operative_with_a_floor_warns_and_never_passes(monkeypatch, _home):
    """The probe could not run. A floor that was not checked is not a
    floor that was met.

    MUTATION that turns this red: keep the old unconditional SKIP for an
    unprobed operative version — this reads SKIP, which (unlike WARN)
    says nothing about the floor at all."""
    _u4_operative(monkeypatch, None, "resolved cli binary not found")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "WARN", row.detail
    assert "NOT be verified" in row.detail
    assert "2.1.251" in row.detail
    assert "resolved cli binary not found" in row.detail

    # with no floor registered there is nothing to verify: still SKIP
    _write_yaml(
        _home,
        "models:\n  steward: claude-sonnet-5\n  overseer: claude-sonnet-5\n",
    )
    no_floor = provider._sdk_row(_home, importer=_u4_importer)
    assert no_floor.verdict == "SKIP", no_floor.detail


def test_u4_unparseable_operative_version_warns_and_never_passes(monkeypatch, _home):
    """A `--version` that prints something this code cannot read is
    "could not be verified", never PASS.

    MUTATION that turns this red: fall through to the equality compare
    when `_parse_cli_version` returns `None` — this reads INFO."""
    _u4_operative(monkeypatch, "banana")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "WARN", row.detail
    assert "NOT be verified" in row.detail


def test_u4_the_floor_map_is_user_editable_in_config_yaml(monkeypatch, _home):
    """S-58's rung order for this entry: config.yaml over the env var
    over the code default. The number 2.1.251 came from one API error
    string, so an operator who learns better must be able to correct it
    without a code change.

    MUTATION that turns this red: hardcode the floor map in
    `provider.py` instead of reading `sdk.model_cli_floors` — the
    config-set floor below is ignored and the row reads PASS."""
    _write_yaml(_home, "sdk:\n  model_cli_floors: claude-sonnet-5=9.9.9\n")
    _u4_operative(monkeypatch, "2.1.226")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "FAIL", row.detail
    assert "claude-sonnet-5" in row.detail
    assert "9.9.9" in row.detail
    # the shipped fable floor is REPLACED by the config value, not merged
    assert "claude-fable-5-1" not in row.detail

    # the env rung answers when config.yaml has no `sdk:` section
    _write_yaml(_home, "provider:\n  name: anthropic\n")
    monkeypatch.setenv("SELF_LEARN_SDK_MODEL_CLI_FLOORS", "claude-sonnet-5=9.9.9")
    env_row = provider._sdk_row(_home, importer=_u4_importer)
    assert env_row.verdict == "FAIL", env_row.detail
    assert "claude-sonnet-5" in env_row.detail


def test_u4_a_malformed_floor_entry_warns_rather_than_reading_as_no_floor(monkeypatch, _home):
    """A typo in the setting must not fail open into silence.

    MUTATION that turns this red: drop the malformed fragment silently in
    `_parse_model_cli_floors` — the row reads PASS with no mention of
    the unreadable entry."""
    _write_yaml(_home, "sdk:\n  model_cli_floors: claude-fable-5-1 2.1.251\n")
    _u4_operative(monkeypatch, "2.1.226")
    row = provider._sdk_row(_home, importer=_u4_importer)
    assert row.verdict == "WARN", row.detail
    assert "unreadable entries" in row.detail
    assert "claude-fable-5-1 2.1.251" in row.detail

    # a floor whose VERSION is unreadable is the same class of problem
    _write_yaml(_home, "sdk:\n  model_cli_floors: claude-fable-5-1=two.one\n")
    bad_version = provider._sdk_row(_home, importer=_u4_importer)
    assert bad_version.verdict == "WARN", bad_version.detail
    assert "NOT be verified" in bad_version.detail


def test_u4_the_handoff_parser_still_reads_every_new_row_shape(monkeypatch, capsys, _home):
    """`_handoff_sdk_fields` parses the `key=value` tokens ahead of the
    first `" — "`. Every new verdict must keep that prefix intact, or
    `doctor invocation`'s handoff block silently degrades to its
    "(not probed…)" placeholders.

    MUTATION that turns this red: move `sdk=`/`bundled-cli=`/
    `operative-cli=` after the em-dash separator in any branch below."""
    for version, expected_verdict in (
        ("2.1.226", "FAIL"),
        ("2.1.278", "INFO"),
        ("banana", "WARN"),
    ):
        _u4_operative(monkeypatch, version)
        row = provider._sdk_row(_home, importer=_u4_importer)
        assert row.verdict == expected_verdict, row.detail
        sdk_version, bundled, _host = provider._handoff_sdk_fields([row])
        assert sdk_version == "0.2.999", row.detail
        assert bundled == "2.1.226", row.detail

    # and the end-to-end printed handoff block, through the real verb.
    # `_default_sdk_importer` calls `importlib.import_module`, so the
    # substitution goes through `sys.modules` (the seam `test_dc9` uses)
    # rather than through the default argument, which binds at def time.
    _u4_operative(monkeypatch, "2.1.226")
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", _U4_SDK)
    rc = cli_mod.main(["doctor", "invocation"])
    out = capsys.readouterr().out
    assert rc == 1, out  # a FAIL row makes the verb exit 1
    assert "doctor: FAIL sdk —" in out
    assert "handoff: sdk-version = 0.2.999" in out
    assert "handoff: cli-version.bundled = 2.1.226" in out


def test_dc5_region_row(monkeypatch, capsys, _home):
    _write_provider_yaml(_home, name="bedrock")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "region")
    assert line.startswith("FAIL")

    _write_provider_yaml(_home, name="bedrock", bedrock={"region": "us-east-1"})
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "region")
    assert line.startswith("PASS")
    assert "AWS_REGION" in line and "AWS_DEFAULT_REGION" in line

    rc, out = _run(["doctor", "invocation"], capsys)  # provider unset -> anthropic
    _write_provider_yaml(_home, name="anthropic")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "region")
    assert line.startswith("SKIP")


def test_dc6_id_shapes_and_doc_i_gating(monkeypatch, capsys, _home):
    # every model unset -> every surface's model_for() returns the alias
    # (Mod-3/MD4). U-flip flipped worker/worker-repair/miner-reader's
    # default to sdk alongside the analyst's (U-sdka), so the three
    # `cli`-surface legs below are now CONSTRUCTED by pinning them back
    # to cli explicitly -- without the pin all four resolve sdk and all
    # four FAIL instead of showing the INFO gating this test is about.
    _write_provider_yaml(_home, name="bedrock", bedrock={"region": "us-east-1"})
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    assert rc == 1  # the sdk-surface alias FAILs the run

    # direct, unambiguous per-surface check via provider.preflight
    rows = provider.preflight(_home)
    analyst_row = next(r for r in rows if r.name == "models" and r.surface == "analyst")
    assert analyst_row.verdict == "FAIL"
    assert "Anthropic alias, not a Bedrock id" in analyst_row.detail

    for cli_surface in ("worker", "worker-repair", "miner-reader"):
        cli_row = next(r for r in rows if r.name == "models" and r.surface == cli_surface)
        assert cli_row.verdict == "INFO"
        # U-cleanup-B (§8.1, MAJOR-5 extension): "backend=cli" corrected
        # to the SEL6 pattern ("REFUSED (cli retired)") in provider.py.
        assert "backend=REFUSED (cli retired)" in cli_row.detail

    verdict, note = provider._id_verdict(ALIAS)
    assert verdict == "FAIL" and "Anthropic alias, not a Bedrock id" in note
    verdict2, _ = provider._id_verdict(BEDROCK_ID)
    assert verdict2 != "FAIL"
    verdict3, _ = provider._id_verdict(BEDROCK_ARN)
    assert verdict3 != "FAIL"
    verdict4, _ = provider._id_verdict("vendor.model")
    assert verdict4 != "FAIL"
    verdict5, note5 = provider._id_verdict("totally-unrecognized-shape")
    assert verdict5 == "WARN"

    _write_provider_yaml(_home, name="anthropic")
    rows_anthropic = provider.preflight(_home)
    for r in rows_anthropic:
        if r.name == "models":
            assert r.verdict == "SKIP"


def test_dc7_ambient_bedrock_key_warns_under_anthropic(monkeypatch, _home):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    rows = provider.preflight(_home)
    env_rows = [r for r in rows if r.name == "env"]
    assert all(r.verdict == "WARN" for r in env_rows)
    assert all("CLAUDE_CODE_USE_BEDROCK" in r.detail for r in env_rows)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK")

    rows2 = provider.preflight(_home)
    env_rows2 = [r for r in rows2 if r.name == "env"]
    assert all(r.verdict == "PASS" or r.verdict == "SKIP" for r in env_rows2)


def test_dc8_orphans_row(monkeypatch, capsys):
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "orphans")
    assert line.startswith("SKIP")

    import sys as _sys

    fake_module = types.SimpleNamespace(orphan_report=lambda: "no orphan pids")
    monkeypatch.setitem(_sys.modules, "self_learn.invocation_sdk", fake_module)
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "orphans")
    assert "no orphan pids" in line

    import ast
    import inspect

    banned = ("os.kill", "os.killpg", "signal.", ".unlink(", ".write_text(", ".rmdir(", "shutil.rmtree")
    preflight_src = inspect.getsource(provider.preflight)
    doctor_src = inspect.getsource(cli_mod._cmd_doctor)
    for token in banned:
        assert token not in preflight_src
        assert token not in doctor_src


def test_dc9_handoff_block_fixed_fields_and_no_leak_and_equality(monkeypatch, capsys, _home, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "not-a-real-key-DO-NOT-USE")
    # NOTE (code gate, 2026-08-19): `M17`'s "second reader" claim (Doc-d's
    # `DC9` docstring) covers the block byte-for-byte, but a bare env-var
    # secret alone never reaches `_credential_mechanisms`'s FILE-reading
    # branch (`_profile_section_present`) -- seed a credentials file too,
    # so the file leg is genuinely under this fixture's reach.
    creds_file = tmp_path / "fake-aws-credentials"
    creds_file.write_text(
        f"[{SANDBOX_PROFILE}]\naws_secret_access_key = not-a-real-key-DO-NOT-USE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(creds_file))
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "profile": SANDBOX_PROFILE, "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    assert "doctor: ---" in out
    handoff_lines = [ln for ln in out.splitlines() if ln.startswith("doctor: handoff: ")]
    # DC9 asks for the FIXED field set, transcribed — a literal, not
    # `provider.SURFACES`, so a surface added to the tuple trips this test
    # instead of being silently followed (U8 fold r1, gate S2).
    _HANDOFF_SURFACES = ("worker", "worker-repair", "miner-reader", "analyst", "steward", "overseer")
    assert tuple(provider.SURFACES) == _HANDOFF_SURFACES
    expected_fields = (
        ["provider"]
        + [f"backend.{s}" for s in _HANDOFF_SURFACES]
        + ["region", "profile", "credential-mechanisms"]
        + [f"model.{s}" for s in _HANDOFF_SURFACES]
        + ["model.small_fast"]
        + [f"env-keys.{s}" for s in _HANDOFF_SURFACES]
        + ["sdk-version", "cli-version.bundled", "cli-version.host"]
    )
    got_fields = [ln[len("doctor: handoff: ") :].split(" = ", 1)[0] for ln in handoff_lines]
    assert got_fields == expected_fields
    # NOTE-a (code gate, 2026-08-19): checking the PREFIX-FILTERED line
    # list is blind to a leak that embeds a newline -- exactly the shape
    # of a credential-file section body -- because only the FIRST
    # physical line of such a leak starts with "doctor: handoff: "; every
    # continuation line is dropped by the `startswith` filter before this
    # assertion ever sees it. Assert over the RAW text from the handoff
    # block's own marker onward instead, so a multi-line leak has nowhere
    # to hide.
    handoff_block_raw = out[out.index("doctor: ---") :]
    assert "not-a-real-key-DO-NOT-USE" not in handoff_block_raw

    # Doc-d1: env-keys.<surface> equals the env row's own detail
    rows = provider.preflight(_home)
    env_by_surface = {r.surface: r.detail for r in rows if r.name == "env" and r.surface is not None}
    for ln in handoff_lines:
        field, _, value = ln[len("doctor: handoff: ") :].partition(" = ")
        if field.startswith("env-keys."):
            surface = field.split(".", 1)[1]
            assert value == env_by_surface[surface], (surface, value, env_by_surface[surface])

    # Doc-d0: zero-spawn path placeholders
    monkeypatch.setenv("SELF_LEARN_HOME", str(_home))

    def _monkey_preflight(home):
        return [provider.Row(name="switches", verdict="PASS", detail="synthetic")]

    monkeypatch.setattr(provider, "preflight", _monkey_preflight)
    rc, out = _run(["doctor", "invocation"], capsys)
    assert "(not probed — sdk not installed)" in out
    assert "(not probed — sdk row skipped)" in out


def test_dc10_no_network_no_extra_spawn(monkeypatch, capsys, _home, tmp_path):
    import socket
    import types as _types

    def _socket_fail(*a, **kw):
        pytest.fail("socket.socket() was called")

    monkeypatch.setattr(socket, "socket", _socket_fail)

    # BLOCKER-1(b) -- `subprocess.run` alone was patched here before; the
    # ONE permitted spawn (`_operative_cli_version`, née `_host_cli_version`)
    # uses `run`, but nothing guarded `Popen`, and `Popen` at the top of
    # `preflight` (reached on every default-posture run) survived
    # undetected. Guard both.
    def _popen_fail(*a, **kw):
        pytest.fail("subprocess.Popen() was called")

    monkeypatch.setattr(subprocess, "Popen", _popen_fail)

    recorded = []
    real_run = subprocess.run

    def _recording_run(argv, *a, **kw):
        recorded.append(list(argv))
        if argv != [argv[0], "--version"] or len(argv) != 2:
            pytest.fail(f"unexpected subprocess argv: {argv}")
        raise FileNotFoundError("no claude on PATH in this sandbox")

    monkeypatch.setattr(subprocess, "run", _recording_run)

    # BLOCKER-1(a) -- a pristine anthropic home never reaches
    # `_credentials_row`'s `_credential_mechanisms` call: it SKIPs
    # immediately on `provider != "bedrock"`, so the one place a live AWS
    # STS call or an IMDS socket connect (`Doc-a`) would live was never
    # actually executed under this recorder, no matter how well-guarded
    # `run`/`Popen`/`socket.socket` were. Drive both legs under a
    # genuinely bedrock+sdk posture instead, with region and a model set,
    # so the credentials row actually runs. `Path.home` is patched to an
    # empty sandbox dir so the presence-only file probes inside it never
    # touch this host's real `~/.aws/*` as a side effect.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fake-aws-home"))
    key = provider.MODEL_KEY_FOR_SURFACE["worker"]
    _write_provider_yaml(
        _home, name="bedrock", bedrock={"region": "us-east-1", "models": {key: BEDROCK_ID}}
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")

    # SDK importer absent: recorder fires zero times. Forced via
    # `sys.modules` (this venv may or may not have `claude_agent_sdk`
    # installed for real -- `B-7`'s premise does not hold on every host).
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "claude_agent_sdk", None)
    rc, out = _run(["doctor", "invocation"], capsys)
    assert recorded == []
    monkeypatch.delitem(_sys.modules, "claude_agent_sdk", raising=False)

    # fake importer present: recorder fires exactly once
    fake_sdk = _types.SimpleNamespace(__version__="0.2.999")
    monkeypatch.setitem(_sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/opt/claude")
    rc, out = _run(["doctor", "invocation"], capsys)
    assert len(recorded) == 1
    assert recorded[0] == ["/opt/claude", "--version"]

    # BLOCKER-1(a) positive control: the credentials row genuinely ran
    # under this posture rather than SKIPping for "provider=anthropic".
    credentials_lines = _rows_by_name(out, "credentials")
    assert credentials_lines
    assert "provider=anthropic" not in credentials_lines[0]


def test_dc11_selftest_row(monkeypatch, capsys, _home, tmp_path):
    from self_learn import selfcheck

    rows = provider.preflight(_home)
    assert not any(r.verdict == "FAIL" for r in rows)
    ok, reason = selfcheck._check_invocation(_home)
    assert ok is selfcheck.Verdict.PASS
    assert "self-learn doctor invocation" in reason

    _write_provider_yaml(_home, name="bedrock")
    ok2, reason2 = selfcheck._check_invocation(_home)
    assert ok2 is selfcheck.Verdict.FAIL
    assert "self-learn doctor invocation" in reason2

    # `M27`'s target: a healthy MID-ROLLOUT install (one surface flipped
    # to sdk with a real id, the rest still on cli with correct aliases)
    # must stay green -- `Doc-i`'s gating is what keeps it so. U-flip
    # flipped worker/worker-repair/miner-reader's default to sdk too, so
    # "the rest still on cli" is now CONSTRUCTED by an explicit pin --
    # without it their unset models would FAIL under an sdk default.
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    # U8: steward/overseer join the "rest still on cli" pin too -- their
    # sdk default would otherwise FAIL here the same way worker/miner
    # would without their own pin above.
    monkeypatch.setenv("SELF_LEARN_BACKEND_STEWARD", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_OVERSEER", "cli")
    ok3, reason3 = selfcheck._check_invocation(_home)
    assert ok3 is selfcheck.Verdict.PASS, reason3
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")
    monkeypatch.delenv("SELF_LEARN_BACKEND_STEWARD")
    monkeypatch.delenv("SELF_LEARN_BACKEND_OVERSEER")
    _write_provider_yaml(_home, name="anthropic")

    # the printed selftest output, end to end (DC11's "PASS invocation" leg)
    import support

    env = support.make_env(tmp_path / "dc11")
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rc = cli_mod.main(["--selftest"])
    out = capsys.readouterr().out
    # fold r1, 2026-09-04: no worker placeholder row -- this fresh env's
    # 9 real checks all PASS, so the run exits 0.
    assert rc == 0
    assert "PASS invocation" in out


def test_dc12_mixed_rollout_info_lines_per_surface(monkeypatch, _home):
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={
            "region": "us-east-1",
            "models": {"analyst": BEDROCK_ID, "miner": BEDROCK_ID_2},
        },
    )
    # U-flip flipped worker/worker-repair's default to sdk alongside
    # miner-reader/analyst's; pin them back to cli explicitly to keep
    # this "mixed" fixture's shape (two surfaces cli, two sdk).
    # U8: steward/overseer also default to sdk with no model configured
    # here -- pinned to cli too, same reason as worker/worker-repair, so
    # this fixture's "no FAIL anywhere" bar still holds with six surfaces.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_STEWARD", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_OVERSEER", "cli")
    rows = provider.preflight(_home)
    rollout_rows = {r.surface: r for r in rows if r.name == "rollout"}
    assert len(rollout_rows) == 6
    # U-cleanup-B (§8.1, MAJOR-5 extension): the rollout row's non-sdk
    # wording was "backend=cli" (a value that can no longer be literally
    # true post-collapse) -- corrected to the SEL6 pattern, matching the
    # switches row.
    assert rollout_rows["worker"].detail == "worker: backend=REFUSED (cli retired) — provider does not apply"
    assert rollout_rows["worker-repair"].detail == "worker-repair: backend=REFUSED (cli retired) — provider does not apply"
    assert "backend=sdk provider=bedrock" in rollout_rows["analyst"].detail
    assert "backend=sdk provider=bedrock" in rollout_rows["miner-reader"].detail
    assert rollout_rows["steward"].detail == "steward: backend=REFUSED (cli retired) — provider does not apply"
    assert rollout_rows["overseer"].detail == "overseer: backend=REFUSED (cli retired) — provider does not apply"
    assert not any(r.verdict == "FAIL" for r in rows)


def test_dc13_argv_byte_pinned_and_degrades_to_skip(monkeypatch):
    fake_sdk = types.SimpleNamespace(__version__="0.2.999")

    def _importer():
        return fake_sdk

    for exc in (FileNotFoundError("x"), OSError("x"), subprocess.TimeoutExpired(cmd="x", timeout=10)):

        def _raiser(*a, **kw):
            raise exc

        monkeypatch.setattr(subprocess, "run", _raiser)
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/opt/claude")
        row = provider._sdk_row(importer=_importer)
        assert row.verdict == "SKIP"

    class _Result:
        returncode = 1
        stdout = "2.1.999\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())
    row2 = provider._sdk_row(importer=_importer)
    assert row2.verdict == "SKIP"

    recorded = []

    class _OkResult:
        returncode = 0
        stdout = "2.1.999\n"

    def _recording_run(argv, **kw):
        recorded.append(argv)
        assert len(argv) == 2
        assert argv[1] == "--version"
        assert argv[0] == "/opt/claude"
        assert kw.get("timeout") == 10
        return _OkResult()

    monkeypatch.setattr(subprocess, "run", _recording_run)
    row3 = provider._sdk_row(importer=_importer)
    # U4 (S-68) widened this tuple: `fake_sdk` declares no bundled
    # version ("?"), so the operative "2.1.999" differs from it, and a
    # plain difference is INFO now rather than WARN. This test is about
    # the argv and the SKIP legs, not the verdict vocabulary.
    assert row3.verdict in ("PASS", "WARN", "INFO")
    assert recorded


def test_dc14_env_row_per_surface_and_catches_refusal(monkeypatch, capsys, _home):
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    # U-flip flipped worker/worker-repair/miner-reader's default to sdk;
    # pin worker back to cli so its unset model does not refuse (and its
    # "env" row stays SKIP, which is what this leg is about). U8:
    # steward/overseer default to sdk too, unpinned here on purpose --
    # this leg only checks worker/analyst's own verdicts and the row
    # count, so the two new surfaces' own FAIL rows (unset model) are
    # unexamined but harmless.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    rows = provider.preflight(_home)
    env_rows = {r.surface: r for r in rows if r.name == "env"}
    assert len(env_rows) == 6
    assert env_rows["worker"].verdict == "SKIP"
    assert env_rows["analyst"].verdict == "PASS"

    # the catch: refusing config on an sdk surface -> FAIL row, never raises
    _write_provider_yaml(_home, name="bedrock")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    try:
        rows2 = provider.preflight(_home)
    except provider.ProviderRefused:
        pytest.fail("ProviderRefused escaped preflight()")
    env_rows2 = {r.surface: r for r in rows2 if r.name == "env"}
    assert env_rows2["analyst"].verdict == "FAIL"
    assert env_rows2["analyst"].detail.startswith("refused-config: ")

    rc, out = _run(["doctor", "invocation"], capsys)
    assert rc == 1


def test_dc15_preflight_is_the_sole_source(monkeypatch, capsys):
    # verdict=FAIL, deliberately -- a `_cmd_doctor` that computes any
    # verdict of its own (rather than rendering exactly what `preflight`
    # returned) is exactly what this leg exists to catch (`M25`).
    def _monkey_preflight(home):
        return [provider.Row(name="switches", verdict="FAIL", detail="synthetic-row-xyz")]

    monkeypatch.setattr(provider, "preflight", _monkey_preflight)
    rc, out = _run(["doctor", "invocation"], capsys)
    row_lines = [ln for ln in out.splitlines() if ln.startswith("doctor: ") and "handoff" not in ln and ln != "doctor: ---"]
    assert row_lines == ["doctor: FAIL switches — synthetic-row-xyz"]
    assert "doctor: ---" in out
    assert rc == 1


def test_dc16_credentials_warn_not_fail_and_dc3_coupling(monkeypatch, _home, tmp_path):
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID, "miner": BEDROCK_ID_2}},
    )
    # U-flip flipped worker/worker-repair's default to sdk too; pin them
    # back to cli so their unset model does not refuse -- this leg's
    # "not any FAIL" assertion is about credentials, not models/env.
    # U8: steward/overseer join the same pin, same reason.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_STEWARD", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_OVERSEER", "cli")

    # NOTE (code gate, 2026-08-19): the "no credentials seeded" leg below
    # only means that if the HOST this test runs on happens to have no
    # ambient AWS_* env vars and no real `~/.aws/*` -- host-dependent, not
    # sandboxed. Patch `Path.home` to an empty dir and clear every AWS_*
    # var `_credential_mechanisms` reads, so this leg is genuinely
    # mechanism-free rather than incidentally so.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fake-aws-home"))
    for var in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
    ):
        monkeypatch.delenv(var, raising=False)

    # no credentials seeded
    rows = provider.preflight(_home)
    cred_row = next(r for r in rows if r.name == "credentials")
    assert cred_row.verdict == "WARN"
    assert "IMDS" in cred_row.detail
    assert "container" not in cred_row.detail
    assert not any(r.verdict == "FAIL" for r in rows)

    # with a mechanism seeded
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "not-a-real-key-DO-NOT-USE")
    rows2 = provider.preflight(_home)
    cred_row2 = next(r for r in rows2 if r.name == "credentials")
    assert cred_row2.verdict == "PASS"
    assert "env-static" in cred_row2.detail
    assert not any(r.verdict == "FAIL" for r in rows2)


def test_dc17_switches_row_reports_cli_selection_as_refused(monkeypatch, capsys):
    """`SEL6` (U-cleanup §11.1, `T-DOCTOR-SWITCHES`) -- the `switches` row
    (`provider.py:621-623`) prints `backend=sdk (…)` for all four
    surfaces on a clean env (dc2 already covers this half; repeated here
    as the negative control against the same line the positive half
    reads), and reports a `cli` selection as REFUSED, spelled out as
    `backend=REFUSED (cli retired) (...)`, never folded into an accepted
    `backend=cli` or silently absorbed into `backend=sdk`.
    """
    # clean env: every surface sdk (default), never REFUSED.
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        assert f"{surface}: backend=sdk (default)" in line
    assert "REFUSED" not in line
    assert "backend=cli" not in line

    # a single selector pinned to "cli" -- SELECTOR_FOR_SURFACE maps BOTH
    # worker and worker-repair to WORKER, so setting it flips both of
    # their cells to REFUSED; miner-reader/analyst (different selectors)
    # stay sdk (default).
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    for surface in ("worker", "worker-repair"):
        assert f"{surface}: backend=REFUSED (cli retired) (env:SELF_LEARN_BACKEND_WORKER)" in line
    assert "backend=cli" not in line
    for surface in ("miner-reader", "analyst"):
        assert f"{surface}: backend=sdk (default)" in line
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")

    # the coarse rung: SELF_LEARN_BACKEND=cli refuses every surface at once.
    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "switches")
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        assert f"{surface}: backend=REFUSED (cli retired) (env:SELF_LEARN_BACKEND)" in line
    assert "backend=cli" not in line
    assert "backend=sdk" not in line


def test_p2_bare_doctor_is_byte_identical_to_doctor_invocation(capsys):
    """U-papercuts P-2 — bare `self-learn doctor` (no `<verb>`) must behave
    EXACTLY as `self-learn doctor invocation`: same stdout, same stderr,
    same exit code. Before this unit, `doctor_command` defaulted to
    `None` and `_cmd_doctor` printed `usage: self-learn doctor invocation`
    to stderr and returned `EXIT_USAGE` (64) instead of running any
    diagnostic — the first-try papercut this test guards against
    regressing.

    Mutation that turns this red: delete the `doctor_p.set_defaults(
    doctor_command="invocation")` call added to `_build_parser` in
    cli.py (or revert it to the pre-fix state) — bare `doctor`'s stdout
    reverts to empty and its stderr reverts to the old usage line, so
    both equality asserts fail.
    """
    rc_bare = cli_mod.main(["doctor"])
    captured_bare = capsys.readouterr()

    rc_explicit = cli_mod.main(["doctor", "invocation"])
    captured_explicit = capsys.readouterr()

    assert rc_bare == rc_explicit
    assert captured_bare.out == captured_explicit.out
    assert captured_bare.err == captured_explicit.err
    # Not a vacuous pass: prove both sides actually ran the diagnostic
    # (as opposed to both being empty/erroring identically).
    assert captured_bare.out.startswith("doctor: ")
    assert captured_bare.err == ""


def test_p2_doctor_unknown_verb_still_a_usage_error(capsys):
    """`self-learn doctor bogus` must stay an argparse usage error — exit
    2, the "invalid choice" message — unaffected by P-2's bare-form
    default. This is the negative control for P-2: it proves the fix
    only supplies a DEFAULT for the missing case, it does not widen
    `doctor` into accepting an arbitrary verb.

    Mutation that turns this red: a broader fix shape that special-cases
    `doctor_command is None` inside `_cmd_doctor` instead of the
    parser-level default (or one that mishandles the subparsers choice
    validation) could accidentally accept `bogus` too, or change its
    exit code away from argparse's own 2.

    Note: `_main`'s `parser.parse_known_args(argv)` call catches
    argparse's `SystemExit` itself and returns its (int) code (see
    `cli.py::_main`) — `cli_mod.main()` never raises for this case, it
    returns 2, so this asserts on the return value rather than
    `pytest.raises`.

    Gate r1 N-2: `doctor_sub`'s `metavar` changed from `"<verb>"` to
    `"[<verb>]"` (so `doctor -h`'s usage line correctly shows the verb as
    optional, matching the new bare-form default) -- this DOES change
    `bogus`'s stderr bytes (`argument <verb>: invalid choice` becomes
    `argument [<verb>]: invalid choice`; measured via a before/after
    diff). This test's assertions are substring checks
    (`"invalid choice: 'bogus'"`, `"invocation"`), not an exact-byte
    comparison, so both survive unchanged -- no update needed here.
    """
    rc = cli_mod.main(["doctor", "bogus"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'bogus'" in err
    assert "invocation" in err
