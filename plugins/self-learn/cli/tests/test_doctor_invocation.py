"""U-bedrock — `DC` criteria: `self-learn doctor invocation` (see
`docs/specs/self-learn/drafts/u-bedrock-provider-spec.md` §3.8/§4).

Fixtures never carry a real Bedrock model id or anything credential-
shaped (`D-6`, `SEC-1`) — see `test_provider.py`'s module docstring for
the placeholder table; `MD6` enforces the boundary over both test files.
"""

from __future__ import annotations

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
    single_line_rows = ("switches", "provider", "config", "sdk", "rollout", "region", "credentials", "orphans")
    for row in single_line_rows:
        assert len(_rows_by_name(out, row)) == 1, row
    assert len(_rows_by_name(out, "models")) == 5  # 4 surfaces + small_fast
    assert len(_rows_by_name(out, "env")) == 4
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
    for surface in ("worker", "worker-repair", "miner-reader"):
        assert f"{surface}: backend=cli (default)" in line
    # U-sdka: the analyst's default flipped to sdk (§9 E7).
    assert "analyst: backend=sdk (default)" in line

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
    # wholly-inert -> FAIL. U-sdka: the analyst's default flipped to sdk,
    # so this state must now be CONSTRUCTED by pinning the analyst back to
    # cli -- without the pin all four surfaces are no longer cli, and the
    # rollout is no longer wholly inert (see DR3, test_u_sdka.py).
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    _write_provider_yaml(_home, name="bedrock")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "rollout")
    assert line.startswith("FAIL")

    # mixed -> no FAIL row anywhere, exit 0
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    assert rc == 0
    body_lines = [ln for ln in out.splitlines() if ln.startswith("doctor: ") and "handoff" not in ln]
    assert not any(" FAIL " in ln for ln in body_lines)
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")

    # all-sdk -> PASS
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={
            "region": "us-east-1",
            "models": {"worker": BEDROCK_ID, "miner": BEDROCK_ID, "analyst": BEDROCK_ID},
        },
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    rc, out = _run(["doctor", "invocation"], capsys)
    (line,) = _rows_by_name(out, "rollout")
    assert line.startswith("PASS")
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

    def _host_match():
        return "2.1.999", ""

    monkeypatch.setattr(provider, "_host_cli_version", _host_match)
    row = provider._sdk_row(importer=_match_importer)
    assert row.verdict == "PASS"

    def _host_differ():
        return "2.1.212", ""

    monkeypatch.setattr(provider, "_host_cli_version", _host_differ)
    row2 = provider._sdk_row(importer=_match_importer)
    assert row2.verdict == "WARN"

    def _raises_import_error():
        raise ImportError("no sdk")

    row3 = provider._sdk_row(importer=_raises_import_error)
    assert row3.verdict == "SKIP"

    # the real importer must not raise
    row4 = provider._sdk_row()
    assert row4.verdict in provider.VERDICTS


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
    # (Mod-3/MD4); only `analyst` is flipped to backend=sdk, so it alone
    # sees the FAIL and the three `cli` surfaces see the INFO gating.
    _write_provider_yaml(_home, name="bedrock", bedrock={"region": "us-east-1"})
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
        assert "backend=cli" in cli_row.detail

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
    expected_fields = (
        ["provider"]
        + [f"backend.{s}" for s in ("worker", "worker-repair", "miner-reader", "analyst")]
        + ["region", "profile", "credential-mechanisms"]
        + [f"model.{s}" for s in ("worker", "worker-repair", "miner-reader", "analyst")]
        + ["model.small_fast"]
        + [f"env-keys.{s}" for s in ("worker", "worker-repair", "miner-reader", "analyst")]
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
    # ONE permitted spawn (`_host_cli_version`) uses `run`, but nothing
    # guarded `Popen`, and `Popen` at the top of `preflight` (reached on
    # every default-posture run) survived undetected. Guard both.
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
    assert ok is True
    assert "self-learn doctor invocation" in reason

    _write_provider_yaml(_home, name="bedrock")
    ok2, reason2 = selfcheck._check_invocation(_home)
    assert ok2 is False
    assert "self-learn doctor invocation" in reason2

    # `M27`'s target: a healthy MID-ROLLOUT install (one surface flipped
    # to sdk with a real id, the rest still on cli with correct aliases)
    # must stay green -- `Doc-i`'s gating is what keeps it so.
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    ok3, reason3 = selfcheck._check_invocation(_home)
    assert ok3 is True, reason3
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")
    _write_provider_yaml(_home, name="anthropic")

    # the printed selftest output, end to end (DC11's "PASS invocation" leg)
    import support

    env = support.make_env(tmp_path / "dc11")
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rc = cli_mod.main(["--selftest"])
    out = capsys.readouterr().out
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
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    rows = provider.preflight(_home)
    rollout_rows = {r.surface: r for r in rows if r.name == "rollout"}
    assert len(rollout_rows) == 4
    assert rollout_rows["worker"].detail == "worker: backend=cli — provider does not apply"
    assert rollout_rows["worker-repair"].detail == "worker-repair: backend=cli — provider does not apply"
    assert "backend=sdk provider=bedrock" in rollout_rows["analyst"].detail
    assert "backend=sdk provider=bedrock" in rollout_rows["miner-reader"].detail
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
    assert row3.verdict in ("PASS", "WARN")
    assert recorded


def test_dc14_env_row_per_surface_and_catches_refusal(monkeypatch, capsys, _home):
    _write_provider_yaml(
        _home,
        name="bedrock",
        bedrock={"region": "us-east-1", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    rows = provider.preflight(_home)
    env_rows = {r.surface: r for r in rows if r.name == "env"}
    assert len(env_rows) == 4
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
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")

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
