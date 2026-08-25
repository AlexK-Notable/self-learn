"""U-seam acceptance criteria (docs/specs/self-learn/drafts/
u-seam-invocation-seam-spec.md Sec 4): SU/CN/AV/LG/TR/RG/FK/WR/HY -- the
invocation seam's contract, containment-as-data, the registry's
precedence chain, FakeBackend, and the three call-site rewirings.

Fixtures are reused by NAME from test_repair.py / test_route_cli.py,
exactly as test_repair.py itself already does with test_worker.py:
pytest resolves a fixture by the name bound in the requesting module's
namespace, regardless of which module defines the function.

SU2/SU3/SU5/HY5 are INSTRUMENT criteria per the spec's own text
("satisfied by the command's output in the build report, not by a test
function") and have no test function here; SU1 is the whole-suite
pass/fail count, likewise verified by running the suite, not by a single
test. Every other criterion has a named test below.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import analyst, config, invocation, miner, worker
from self_learn.invocation_sdk import SdkBackend
from support import make_behavior, make_env

from test_repair import (  # noqa: F401 -- fixtures resolved by name
    Env,
    claude_shim,
    env,
    seed_pending,
    _defect_script,
    _t4_missing_target,
    _t4_target_fixed,
)

from test_invocation_sdk import (  # noqa: F401 -- fixture resolved by name
    sdk_absent,
)


# analyst_env / analyst_shim are NOT imported from test_route_cli: that
# module's own `env` fixture calls `make_env(tmp_path)` at the BARE
# `tmp_path` root, and so does test_worker's `env` (via test_repair) --
# requesting both in the same test (several CN/AV tests need a worker
# run AND an analyst run) collides on `tmp_path/host-repo` with
# `FileExistsError`. These local fixtures nest under a private
# subdirectory instead, so they compose freely with `env`/`claude_shim`.
class _AnalystEnv:
    def __init__(self, sandbox_root):
        e = make_env(sandbox_root)
        self.home = e.ledger
        self.host = e.host


@pytest.fixture()
def analyst_env(tmp_path, monkeypatch):
    sub = tmp_path / "analyst-sandbox"
    sub.mkdir()
    e = _AnalystEnv(sub)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


_ANALYST_CLAUDE_SHIM = """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$CLAUDE_SHIM_LOG"
pwd -P > "$CLAUDE_SHIM_CWD"
cat "$CLAUDE_SHIM_OUT"
exit "${CLAUDE_SHIM_EXIT-0}"
"""


@pytest.fixture()
def analyst_shim(tmp_path, monkeypatch):
    """U-cleanup-A migration: SDK-backed replacement, same interface
    (`["log"]`, `["out"]`, `["cwd"]`) as the bash PATH shim -- see
    `test_route_cli.py::claude_cli_shim_analyst`'s docstring for the same
    pattern (`FAKE_CLAUDE_FORCE_SCENARIO=analyst_result`,
    `FAKE_CLAUDE_OUT` is the wire-level `CLAUDE_SHIM_OUT`)."""
    log = tmp_path / "analyst-shim-argv.log"
    cwd_log = tmp_path / "analyst-shim-cwd.log"
    out = tmp_path / "analyst-shim-stdout.txt"
    out.write_text("", encoding="utf-8")
    _sdk_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
    monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_CWD_LOG", str(cwd_log))
    prompt_log = tmp_path / "analyst-shim-prompt.log"
    monkeypatch.setenv("FAKE_CLAUDE_PROMPT_LOG", str(prompt_log))
    return {"log": log, "out": out, "cwd": cwd_log, "prompt": prompt_log}


# ===================================================================== #
# Shared fake transports (stand-ins for the real `claude` process)
# ===================================================================== #


class _Proc:
    """Stand-in for a `subprocess.run(...)` CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_returns(returncode=0, stdout="", stderr=""):
    def fake_run(argv, **kwargs):
        return _Proc(returncode, stdout, stderr)

    return fake_run


def _run_raises(exc):
    def fake_run(argv, **kwargs):
        raise exc

    return fake_run


class _FakePopen:
    """Configurable stand-in for `subprocess.Popen` (the miner's
    transport). Used AS the monkeypatched replacement directly:
    `monkeypatch.setattr(subprocess, "Popen", _FakePopen(...))` -- calling
    `subprocess.Popen(argv, **kwargs)` then invokes this instance's
    `__call__`, which records the call and returns itself as `proc`."""

    def __init__(
        self,
        *,
        returncode=0,
        output="",
        raise_on_construct=None,
        raise_on_communicate=None,
        write_file=None,
        write_content="",
        pid=4242,
    ):
        self.returncode = returncode
        self._output = output
        self._raise_on_construct = raise_on_construct
        self._raise_on_communicate = raise_on_communicate
        self._write_file = write_file
        self._write_content = write_content
        self.pid = pid
        self.calls: list[tuple[list[str], dict]] = []
        self.waited = False

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self._raise_on_construct is not None:
            raise self._raise_on_construct
        return self

    def communicate(self, prompt, timeout=None):
        if self._raise_on_communicate is not None:
            raise self._raise_on_communicate
        if self._write_file is not None:
            self._write_file.write_text(self._write_content, encoding="utf-8")
        return (self._output, None)

    def wait(self):
        self.waited = True
        return self.returncode


class _PopenRaises:
    """Stand-in for `subprocess.Popen` that raises at CONSTRUCTION time
    (mirrors `FileNotFoundError`/`OSError` from a missing/unexecutable
    `claude`)."""

    def __init__(self, exc):
        self._exc = exc

    def __call__(self, argv, **kwargs):
        raise self._exc


# ===================================================================== #
# SessionSpec builder
# ===================================================================== #


def _default_containment(surface: str) -> invocation.Containment:
    if surface in ("worker", "worker-repair"):
        return invocation.DEGRADED_WORKER_CONTAINMENT
    if surface == "miner-reader":
        return invocation.containment_for(
            "miner-reader", disallowed_tools="X", spool_dir="/tmp/spool"
        )
    if surface == "analyst":
        return invocation.containment_for("analyst", allowed_tools="Read")
    return invocation.DEGRADED_WORKER_CONTAINMENT


def _spec(
    surface: str,
    *,
    prompt: str = "PROMPT",
    cwd: Path | None = None,
    timeout: float = 30.0,
    containment: invocation.Containment | None = None,
    log=None,
    argv: list[str] | None = None,
    argv_builder=None,
    settings_writer=None,
    label: str = "",
    timeout_display=None,
) -> invocation.SessionSpec:
    if containment is None:
        containment = _default_containment(surface)
    if argv_builder is None:
        fixed_argv = argv if argv is not None else ["claude", "-p", prompt]
        argv_builder = lambda _settings, _a=fixed_argv: _a
    return invocation.SessionSpec(
        surface=surface,
        prompt=prompt,
        cwd=cwd or Path("/tmp"),
        timeout=timeout,
        containment=containment,
        log=log or (lambda _msg: None),
        cli_argv_builder=argv_builder,
        cli_settings_writer=settings_writer,
        label=label,
        timeout_display=timeout_display,
    )


# ===================================================================== #
# Backend-selection helpers
# ===================================================================== #


def _clear_backend_env(monkeypatch):
    for var in (
        "SELF_LEARN_BACKEND",
        "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER",
        "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)


def _write_config(home: Path, mapping: dict) -> None:
    lines = ["invocation:"]
    for k, v in mapping.items():
        lines.append(f'  {k}: "{v}"')
    (home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _clear_config(home: Path) -> None:
    p = home / "config.yaml"
    if p.is_file():
        p.unlink()


# ===================================================================== #
# Real-invocation capture fixtures (CN2/CN8/CN9/CN10/AV1/AV4/LG1's real
# legs all reuse these -- one repair-producing worker run, one direct
# miner._invoke_reader call, one direct analyst.analyze call, each with a
# spy on invocation.write_session/text_session recording the real
# SessionSpec the call site actually built)
# ===================================================================== #


@pytest.fixture()
def repair_run(env, claude_shim, monkeypatch):
    """Drives a REAL `worker.run()` that reaches the repair round (a
    T4-missing-target defect, then the fixed form), capturing the two
    `SessionSpec`s `write_session` actually received, in call order."""
    rid = seed_pending(env)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    captured: list[invocation.SessionSpec] = []
    real_write_session = invocation.write_session

    def spy(spec, **kwargs):
        captured.append(spec)
        return real_write_session(spec, **kwargs)

    # A LOCAL MonkeyPatch, undone before this fixture returns -- not the
    # shared per-test `monkeypatch` fixture, whose patches would otherwise
    # persist for the REST of the test and silently capture calls made by
    # sibling fixtures (miner_capture/analyst_capture) requested alongside
    # this one, ballooning this fixture's own `captured` list.
    mp = pytest.MonkeyPatch()
    mp.setattr(invocation, "write_session", spy)
    try:
        worker.run(env.home)
    finally:
        mp.undo()
    return captured


@pytest.fixture()
def miner_capture(monkeypatch, tmp_path):
    """U-cleanup-A migration: drives a REAL `miner._invoke_reader(home,
    prompt)` through `SdkBackend` against `tests/fixtures/fake_claude.py`
    (the `reader_write` scenario, real transport, `SELF_LEARN_SDK_CLI_PATH`),
    capturing the spec and the real argv the fake observed
    (`FAKE_CLAUDE_ARGV_LOG`) -- the SAME interface (`["spec"]`, `["argv"]`,
    `["out_path"]`, `["home"]`) the bash-shimmed fixture returned."""
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "miner-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "miner-xdg-cache"))
    home = tmp_path / "miner-home"
    home.mkdir()
    spool = miner.spool_dir()
    argv_log = tmp_path / "miner-argv.log"
    _sdk_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "reader_write")
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(spool / miner.OUTPUT_BASENAME))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY", '{"candidates": [], "fires": []}')

    captured: list[invocation.SessionSpec] = []
    real_write_session = invocation.write_session

    def spy(spec, **kwargs):
        captured.append(spec)
        return real_write_session(spec, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(invocation, "write_session", spy)
    try:
        out_path = miner._invoke_reader(home, "MINER PROMPT")
    finally:
        mp.undo()
    argv = argv_log.read_text(encoding="utf-8").split("\0")[:-1] if argv_log.exists() else []
    return {"spec": captured[0], "argv": argv, "out_path": out_path, "home": home}


@pytest.fixture()
def analyst_capture(analyst_env, analyst_shim, monkeypatch):
    """Drives a REAL `analyst.analyze(...)` through `test_route_cli`'s
    PATH-shimmed `claude`, capturing the spec and its argv."""
    analyst_shim["out"].write_text(
        "```yaml\n"
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _skill_gates_yaml_for(analyst_env)
        + "```\n",
        encoding="utf-8",
    )
    captured: list[invocation.SessionSpec] = []
    real_text_session = invocation.text_session

    def spy(spec, **kwargs):
        captured.append(spec)
        return real_text_session(spec, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(invocation, "text_session", spy)
    try:
        proposal = analyst.analyze(analyst_env.home, make_behavior())
    finally:
        mp.undo()
    argv = analyst_shim["log"].read_text(encoding="utf-8").split("\0")[:-1]
    prompt_wire = analyst_shim["prompt"].read_text(encoding="utf-8") if analyst_shim["prompt"].exists() else ""
    return {"spec": captured[0], "argv": argv, "proposal": proposal, "prompt_wire": prompt_wire}


def _skill_gates_yaml_for(env) -> str:
    """A SKILL-outcome decision trace at scope skill:s -- mirrors
    `test_route_cli.py::_skill_gates_yaml` (not imported directly since
    that module does not export it in `__all__`; duplicated in miniature
    here rather than reaching into a private helper across files)."""
    from self_learn.worker import skill_roster

    roster_sha = skill_roster(env.home).sha
    trigger = "About to edit .storage while HA is running."
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: false
    field_shaped:
      answer: "no"
      evidence: "{trigger}"
    separable: {{answer: null}}
    cost_bearing: {{answer: null}}
  t2:
    answer: "no"
    evidence: "{trigger}"
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{roster_sha}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "{trigger}"}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: SKILL
flags: []
recommendation: route
"""


# ===================================================================== #
# SU -- the suite (SU4 is the one real test function; SU1/2/3/5 are
# instrument criteria -- see the module docstring)
# ===================================================================== #


def test_su4_invoke_reader_signature_pinned():
    """SU4/B-5: `_invoke_reader` is still a module-level function whose
    POSITIONAL parameters are exactly `("home", "prompt")` -- the arity
    the three named two-positional shims of B-5 require -- and any
    parameter beyond them is keyword-only with a default."""
    sig = inspect.signature(miner._invoke_reader)
    params = list(sig.parameters.values())
    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert [p.name for p in positional] == ["home", "prompt"]
    for p in params:
        if p.name in ("home", "prompt"):
            continue
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (p.name, p.kind)
        assert p.default is not inspect.Parameter.empty, p.name


# ===================================================================== #
# HY -- hygiene
# ===================================================================== #


def test_hy1_this_file_contains_no_bare_claude_argv_literal():
    """HY1/B-1: no line in THIS file matches the bare single-element
    claude-argv literal shape (`B-1`'s pattern) unless it also calls
    `worker._invoke_claude(` -- keeps
    `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
    green now that this file is inside its glob. Deliberately does not
    spell that shape out literally in this docstring -- doing so would
    make this very detection line match its own source."""
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    src = Path(__file__).read_text(encoding="utf-8")
    hits = []
    for i, line in enumerate(src.splitlines(), start=1):
        if pattern.search(line):
            hits.append((i, line))
    for i, line in hits:
        assert "worker._invoke_claude(" in line, (i, line)


def test_hy2_no_module_in_invocation_imports_the_forbidden_modules():
    """HY2/I-a: no module under `invocation/` imports `worker`, `miner`,
    `analyst`, `verbs`, `teach` or `ledger_ops`. AST scan of the
    package -- catches `import X`, `from X import Y`, and `from . import
    X` / `from .. import X` forms alike."""
    forbidden = {"worker", "miner", "analyst", "verbs", "teach", "ledger_ops"}
    invocation_dir = Path(invocation.__file__).resolve().parent
    violations = []
    for path in sorted(invocation_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    last = alias.name.split(".")[-1]
                    if last in forbidden:
                        violations.append((path.name, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                mod_last = mod.split(".")[-1] if mod else ""
                if mod_last in forbidden:
                    violations.append((path.name, node.lineno, mod))
                for alias in node.names:
                    if alias.name in forbidden:
                        violations.append((path.name, node.lineno, f"{mod}.{alias.name}"))
    assert violations == [], violations


# HY3 -- shas taken from `git show 83d05c6:...worker.py` / `...miner.py`
# (N-d/D-27) -- NEVER from the working tree. See the build report for the
# `git diff 83d05c6..HEAD -- worker.py miner.py` proof that no hunk
# touches these five functions' ranges.
_HY3_SHAS = {
    "write_settings_file": "faa1517655474a708951b6ffc067d3b16a8c0d72d03f88668ac83a850fa3488e",
    "write_repair_settings_file": "077adf3c99453c21640219a2ba8c10866ff1240c51442d3b1559a258ce566448",
    "write_permission_rules": "745ceedd12d0720e0c36c8411b43a5292db6e3399a7f6d02c5473f441d99fc66",
    "stage_permission_rules": "1ad0fba43230779635e8eee20d6580cab170c228ff367fa09d3d1c447812c864",
    "write_reader_settings": "c3d25da3bb14dd0c92dd9d17515162d6fae1f075faab3a34f20d8181176fc722",
}


def test_hy3_witness_b_is_sha_pinned():
    """HY3 -- Witness B (the shipped settings-file writers) is sha256
    pinned, not substring-guarded (M34's defeat of the r1 substring
    form). Any edit to these five functions -- even an innocent
    docstring fix -- reddens this test; that is the deliberate,
    documented cost (Sec 3.11)."""
    checks = [
        (worker.write_settings_file, "write_settings_file"),
        (worker.write_repair_settings_file, "write_repair_settings_file"),
        (worker.write_permission_rules, "write_permission_rules"),
        (worker.stage_permission_rules, "stage_permission_rules"),
        (miner.write_reader_settings, "write_reader_settings"),
    ]
    for fn, name in checks:
        actual = hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()
        assert actual == _HY3_SHAS[name], (
            f"Witness B changed ({name}). If this was deliberate, U-seam "
            "is the wrong unit for it -- see Sec 3.11."
        )


def test_hy4_no_filesystem_writes_in_invocation_except_fakebackend_writes():
    """HY4 -- a NEW guard (B-6: the shipped fail-closed census cannot see
    `invocation/` at all -- root-level `glob`, not `rglob`). No function
    in `invocation/` writes to the filesystem, with `FakeBackend`'s
    `Writes` step the single declared exception."""
    fs_calls = {"open", "write_text", "mkdir", "unlink", "touch"}
    invocation_dir = Path(invocation.__file__).resolve().parent
    violations = []
    for path in sorted(invocation_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name in fs_calls:
                    violations.append((path.name, node.lineno, name))
    allowed = {("fake.py", "mkdir"), ("fake.py", "write_text")}
    unexpected = [v for v in violations if (v[0], v[2]) not in allowed]
    assert unexpected == [], (
        f"filesystem write(s) found in invocation/ outside FakeBackend's "
        f"declared Writes exception: {unexpected}"
    )
    assert len(violations) == 2, violations


def test_hy4_lock_census_is_root_level_only_and_therefore_blind_to_invocation():
    """HY4's companion fact (B-6, measured E8): `test_lock_invariant.py`'s
    `NOT_REPO_TRUTH` census globs root-level only -- `invocation/` is
    invisible to it by construction. This does not modify that file; it
    reads it to keep the fact current."""
    src = (Path(__file__).parent / "test_lock_invariant.py").read_text(encoding="utf-8")
    assert 'SRC.glob("*.py")' in src
    assert 'root.glob("*.py")' in src
    assert "SRC.rglob(" not in src
    assert "root.rglob(" not in src


# ===================================================================== #
# CN -- containment
# ===================================================================== #


def test_cn1_every_rendered_rule_has_the_double_slash():
    """CN1 -- for each of the four containments, every rendered rule
    starts with `Edit(//` (double slash). Guarded by non-emptiness FIRST
    for the three surfaces that have rules -- "every element starts with
    X" is vacuously true of `[]`."""
    home = "/home/x"
    worker_c = invocation.containment_for(
        "worker",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        home=home,
        stage_dir=f"{home}/.cache/self-learn/worker.stage",
        stage_on=True,
        enforce=True,
    )
    repair_c = invocation.containment_for(
        "worker-repair",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        write_exact=(f"{home}/a.yaml",),
        enforce=True,
    )
    miner_c = invocation.containment_for(
        "miner-reader",
        disallowed_tools=miner.READER_DISALLOWED_TOOLS,
        spool_dir=f"{home}/.cache/self-learn/miner/spool",
    )
    analyst_c = invocation.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS)

    for c in (worker_c, repair_c, miner_c):
        rules = invocation.containment_rules(c)
        assert len(rules) >= 1
        for r in rules:
            assert r.startswith("Edit(//"), r

    # the analyst's empty case is CN3's business, not this one's.
    assert invocation.containment_rules(analyst_c) == []


def test_cn2_call_site_containment_matches_the_call_site_table(
    repair_run, miner_capture, analyst_capture
):
    """CN2 (restated in r2 to observe the CALL SITE) -- captures the real
    `SessionSpec` from three real invocations and asserts on what the
    call sites actually sent, per the C-c1 table."""
    spec_worker, spec_repair = repair_run
    assert spec_worker.surface == "worker"
    assert spec_repair.surface == "worker-repair"
    for spec in (spec_worker, spec_repair):
        assert spec.containment.allowed_tools == worker.ALLOWED_TOOLS
        assert spec.containment.disallowed_tools == worker.DISALLOWED_TOOLS
        assert spec.containment.strict_mcp is True

    spec_miner = miner_capture["spec"]
    assert spec_miner.containment.allowed_tools is None
    assert spec_miner.containment.disallowed_tools == miner.READER_DISALLOWED_TOOLS
    # U-sdkr: strict_mcp closed for the reader (Fix-1) -- do not "restore" this to False.
    assert spec_miner.containment.strict_mcp is True

    spec_analyst = analyst_capture["spec"]
    assert spec_analyst.containment.allowed_tools == analyst.ANALYST_ALLOWED_TOOLS
    assert spec_analyst.containment.disallowed_tools is None
    assert spec_analyst.containment.strict_mcp is False


def test_cn3_analyst_containment_is_deliberately_near_empty():
    c = invocation.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS)
    assert c.disallowed_tools is None
    assert c.write_globs == ()
    assert c.write_exact == ()
    assert c.strict_mcp is False
    assert c.default_mode is None
    assert invocation.containment_rules(c) == []


def test_cn4_write_exact_sorts_write_globs_does_not():
    c_repair = invocation.containment_for(
        "worker-repair", write_exact=("/z/c.yaml", "/z/a.yaml", "/z/b.yaml")
    )
    assert invocation.containment_rules(c_repair) == [
        "Edit(//z/a.yaml)",
        "Edit(//z/b.yaml)",
        "Edit(//z/c.yaml)",
    ]

    home = "/home/x"
    c_worker = invocation.containment_for(
        "worker", home=home, stage_on=False, enforce=True
    )
    # write_permission_rules already returns fully-rendered `Edit(...)`
    # rules -- containment_rules must render the SAME final strings from
    # its own raw glob patterns, not double-wrap them.
    expected = worker.write_permission_rules(Path(home))
    assert invocation.containment_rules(c_worker) == expected


def test_cn5_default_mode_omitted_when_none_present_when_default():
    c_off = invocation.containment_for(
        "worker", home="/h", stage_dir="/h/.cache/worker.stage", stage_on=True, enforce=False
    )
    perms_off = invocation.containment_permissions(c_off)
    assert "defaultMode" not in perms_off

    c_on = invocation.containment_for(
        "worker", home="/h", stage_dir="/h/.cache/worker.stage", stage_on=True, enforce=True
    )
    perms_on = invocation.containment_permissions(c_on)
    assert perms_on["defaultMode"] == "default"


# CN6/TW-a -- the static twin-witness registry, exactly as Sec 3.10 names it.
SETTINGS_WITNESS = {
    "worker": worker.write_settings_file,
    "worker-repair": worker.write_repair_settings_file,
    "miner-reader": miner.write_reader_settings,
    "analyst": None,
}


def test_cn6_witnesses_a_and_b_agree_statically():
    home = Path(os.environ["SELF_LEARN_HOME"])

    c_worker = invocation.containment_for(
        "worker",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        home=home,
        stage_dir=worker.stage_dir(),
        stage_on=True,
        enforce=True,
    )
    witness_path = SETTINGS_WITNESS["worker"](home)
    witness_perms = json.loads(witness_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(c_worker) == witness_perms

    # N-f: write_exact supplied REVERSE-SORTED -- both witnesses sort
    # internally, so a pre-sorted input would agree whether or not either
    # sort survives; reverse order makes the leg discriminate.
    exact_paths = [home / "z.yaml", home / "m.yaml", home / "a.yaml"]
    assert exact_paths == sorted(exact_paths, reverse=True)
    c_repair = invocation.containment_for(
        "worker-repair",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        write_exact=tuple(str(p) for p in exact_paths),
        enforce=True,
    )
    witness_repair_path = SETTINGS_WITNESS["worker-repair"](home, exact_paths)
    witness_repair_perms = json.loads(witness_repair_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(c_repair) == witness_repair_perms

    c_miner = invocation.containment_for(
        "miner-reader", disallowed_tools=miner.READER_DISALLOWED_TOOLS, spool_dir=miner.spool_dir()
    )
    witness_miner_path = SETTINGS_WITNESS["miner-reader"]()
    witness_miner_perms = json.loads(witness_miner_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(c_miner) == witness_miner_perms

    assert SETTINGS_WITNESS["analyst"] is None
    c_analyst = invocation.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS)
    assert invocation.containment_rules(c_analyst) == []
    argv = analyst.build_argv("prompt", "doctrine text", "model")
    assert "--settings" not in argv


@pytest.mark.parametrize("enforce_env", [None, "0"])
@pytest.mark.parametrize("stage_env", [None, "0"])
def test_cn7_worker_leg_over_all_four_switch_combinations(stage_env, enforce_env, monkeypatch):
    if stage_env is None:
        monkeypatch.delenv("SELF_LEARN_STAGE", raising=False)
    else:
        monkeypatch.setenv("SELF_LEARN_STAGE", stage_env)
    if enforce_env is None:
        monkeypatch.delenv("SELF_LEARN_ENFORCE_SCOPE", raising=False)
    else:
        monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", enforce_env)

    home = Path(os.environ["SELF_LEARN_HOME"])
    stage_on = worker._stage_enabled()
    enforce = worker._enforce_scope()
    c = invocation.containment_for(
        "worker",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        home=home,
        stage_dir=worker.stage_dir(),
        stage_on=stage_on,
        enforce=enforce,
    )
    witness_path = SETTINGS_WITNESS["worker"](home)
    witness_perms = json.loads(witness_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(c) == witness_perms


@pytest.mark.parametrize("enforce_env", [None, "0"])
def test_cn7_repair_leg_over_both_enforce_values(enforce_env, monkeypatch):
    if enforce_env is None:
        monkeypatch.delenv("SELF_LEARN_ENFORCE_SCOPE", raising=False)
    else:
        monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", enforce_env)

    home = Path(os.environ["SELF_LEARN_HOME"])
    enforce = worker._enforce_scope()
    exact_paths = [home / "z.yaml", home / "m.yaml", home / "a.yaml"]
    c = invocation.containment_for(
        "worker-repair",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        write_exact=tuple(str(p) for p in exact_paths),
        enforce=enforce,
    )
    witness_path = SETTINGS_WITNESS["worker-repair"](home, exact_paths)
    witness_perms = json.loads(witness_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(c) == witness_perms


# U-cleanup-A: `test_cn8_twin_witnesses_agree_at_runtime_on_a_repair_producing_run`
# DELETED here, not migrated -- per spec §3.4's own measurement (the T3
# AST-walk + regex method), CN8 is one of the 5 genuine claude-argv tests
# in test_invocation.py (cn8, cn10, av1, av2, av4). Its subject -- the
# real `--settings <path>` argv element -- does not exist under the sdk
# backend (settings=None under sdk, `A-2`; measured live, the SDK's real
# argv carries no `--settings` flag). The runtime-agreement property CN8
# guarded (containment == the settings file's rendered permissions) is
# now the charter's job end to end, covered by `CH1`-`CH13`
# (`test_invocation_sdk.py`) and `CH10` (`test_worker_contract.py`,
# driven end to end from the real variable, same as CN8 was).


# ---------------------------------------------------- CN9's AST machinery


_FORBIDDEN_TAINT_SOURCES = {
    "write_permission_rules",
    "stage_permission_rules",
    "write_settings_file",
    "write_repair_settings_file",
    "write_reader_settings",
}
_CONTAINMENT_SINKS = {"containment_for", "Containment"}


def _call_func_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _contains_forbidden_call(expr: ast.AST) -> bool:
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _call_func_name(node) in _FORBIDDEN_TAINT_SOURCES:
            return True
    return False


def _one_hop_taint_violations(path: Path) -> list[tuple]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        tainted: set[str] = set()
        for node in ast.walk(func):
            targets = None
            value = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if targets is None or value is None:
                continue
            if _contains_forbidden_call(value):
                for t in targets:
                    if isinstance(t, ast.Name):
                        tainted.add(t.id)
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and _call_func_name(node) in _CONTAINMENT_SINKS:
                for arg_expr in list(node.args) + [kw.value for kw in node.keywords]:
                    if _contains_forbidden_call(arg_expr):
                        violations.append((path.name, node.lineno, "direct-call"))
                    for sub in ast.walk(arg_expr):
                        if isinstance(sub, ast.Name) and sub.id in tainted:
                            violations.append((path.name, node.lineno, f"variable-taint:{sub.id}"))
    return violations


def test_cn9_direction_guard_one_hop_local_taint():
    """CN9 -- the DIRECTION guard (C-c), as a ONE-HOP LOCAL taint check,
    AST-only, over worker.py/miner.py/analyst.py AND this file's own
    CN6/CN7 legs (the collapse is just as fatal in the test meant to
    detect it)."""
    files = [Path(worker.__file__), Path(miner.__file__), Path(analyst.__file__), Path(__file__)]
    all_violations = []
    for f in files:
        all_violations.extend(_one_hop_taint_violations(f))
    assert all_violations == [], all_violations


# U-cleanup-A: `_assert_argv_matches_containment_iff` (the shared helper
# `test_cn10`'s deleted body was its only caller) removed alongside it --
# dead code otherwise.


# U-cleanup-A: `test_cn10_argv_is_the_third_witness_iff_both_directions`
# DELETED here, not migrated -- CN10, per §3.4's measurement (5 genuine
# claude-argv tests: cn8, cn10, av1, av2, av4). Its subject
# (`--allowedTools`/`--disallowedTools`/`--strict-mcp-config` reaching
# the REAL argv, "the argv is a third witness besides the settings file
# and the spec") is moot: measured live, the sdk backend's real argv
# carries `--disallowedTools` but NEVER `--allowedTools`, and permission
# enforcement happens through the `can_use_tool` charter callback, not a
# flag set. `CH1`-`CH13` are the sdk-side charter-enforcement suite this
# property is now covered by.


# ===================================================================== #
# AV -- argv identity
# ===================================================================== #


# U-cleanup-A: `test_av1_argv_equals_surfaces_own_builder_output_recomputed`
# and `test_av2_worker_argv_shape` DELETED here, not migrated -- AV1/AV2,
# per §3.4's measurement. AV1's subject (the captured argv equals
# `worker.build_argv`/`miner.build_reader_argv`/`analyst.build_argv`'s
# own recomputed output) and AV2's (`--strict-mcp-config` trailing,
# prompt absent from argv) are both moot: there is no CLI argv under sdk
# to compare against a builder's output, and `options_kwargs`
# (`invocation_sdk/backend.py`) is what replaces `build_argv` for the
# surviving backend, covered by `OP1`-`OP17`. AV2's "prompt not in argv"
# half survives as `test_bg3_sdk_prompt_delivered_intact`
# (`test_worker_contract.py`) and `T-READER-PROMPT-ON-THE-WIRE`
# (`test_reader_contract.py`, `RO-7`/`CV8`) -- both drive the real wire,
# not a PATH-shimmed argv.


#: U-cleanup-A AG1: `test_av3_settings_writer_called_before_argv_builder`
#: and `test_av4_transport_kwargs_input_presence` are transport-mechanics
#: tests of `CliBackend._run`'s OWN internal call order/kwargs shape --
#: their subject is deleted in U-cleanup-B (§10.1 disposition: "delete in
#: B, unreached in A"). SKIPPED here, not deleted or rewritten: the
#: property (settings-writer-before-argv-builder order; input= kwarg vs
#: argv membership) is intrinsic to the subprocess transport and has no
#: sdk-side analogue -- `options_kwargs` in `invocation_sdk/backend.py`
#: is the sdk equivalent and is covered by `OP1`-`OP17`
#: (`test_invocation_sdk.py`), including `test_op12`/`test_op13`'s own
#: settings-writer-before-argv-builder order assertion.
@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_av3_settings_writer_called_before_argv_builder(monkeypatch):
    """AV3 -- asserted on the miner surface (the one that supplies both)
    with an order-recording pair of closures, driven through the REAL
    `CliBackend` with `subprocess.Popen` mocked out."""
    order = []
    settings_path = Path("/tmp/settings.json")

    def writer():
        order.append("writer")
        return settings_path

    def builder(sp):
        order.append("builder")
        assert sp == settings_path
        return ["claude", "-p", "x"]

    monkeypatch.setattr(subprocess, "Popen", _FakePopen(output=""))
    spec = _spec("miner-reader", argv_builder=builder, settings_writer=writer)
    outcome = invocation.CliBackend().write_session(spec)
    assert order == ["writer", "builder"]
    assert outcome.ok


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_av4_transport_kwargs_input_presence(monkeypatch):
    """AV4 -- the analyst's prompt is in ARGV, not stdin: `input` is
    absent from the transport call's kwargs and the prompt is present in
    argv. The inverse holds for the worker and (via `communicate`) the
    miner."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Proc(0, "RESULT", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec_analyst = _spec(
        "analyst", prompt="THE PROMPT", argv=["claude", "-p", "THE PROMPT", "--model", "x"]
    )
    invocation.CliBackend().text_session(spec_analyst)
    assert "input" not in captured["kwargs"]
    assert "THE PROMPT" in captured["argv"]

    spec_worker = _spec("worker", prompt="THE PROMPT", argv=["claude", "-p"], label="")
    invocation.CliBackend().write_session(spec_worker)
    assert captured["kwargs"].get("input") == "THE PROMPT"
    assert "THE PROMPT" not in captured["argv"]

    captured_popen = {}

    class _CapturePopen:
        def __call__(self, argv, **kwargs):
            captured_popen["argv"] = argv
            self.pid = 1
            self.returncode = 0
            return self

        def communicate(self, prompt, timeout=None):
            captured_popen["prompt"] = prompt
            return ("", None)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _CapturePopen())
    spec_miner = _spec("miner-reader", prompt="THE PROMPT", argv=["claude", "x"])
    invocation.CliBackend().write_session(spec_miner)
    assert captured_popen["prompt"] == "THE PROMPT"
    assert "THE PROMPT" not in captured_popen["argv"]


def test_av4_prompt_membership_on_real_invocations(
    repair_run, miner_capture, analyst_capture, claude_shim
):
    """AV4, U-cleanup-A rebase (armor-reconciled -- see
    `test_u_sdka.py::_ARMOR_21_BY_FILE`). Originally: the analyst's
    `prompt_via_argv=True` transport property put its prompt literally in
    argv, the CLI inverse of worker/repair/miner's stdin delivery.
    Measured live: under the sdk backend NO surface's prompt rides argv
    -- every surface's prompt travels the wire via `ClaudeSDKClient.
    query()` (a real `{"type": "user"}` control-protocol message), so the
    analyst's own distinguishing CLI-argv property is gone. Rebased to
    the sdk-side distinction that DOES survive: the analyst's prompt
    reaches the wire (`analyst_shim`'s `FAKE_CLAUDE_PROMPT_LOG`, captured
    by `analyst_capture["prompt_wire"]`) and is absent from EVERY
    surface's real argv, analyst included -- `AV4`'s "never argv" half
    now holds universally rather than per-surface."""
    assert analyst_capture["spec"].prompt == analyst_capture["prompt_wire"]
    assert analyst_capture["spec"].prompt not in analyst_capture["argv"]
    spec_worker, spec_repair = repair_run
    assert spec_worker.prompt not in claude_shim["argv"](1)
    assert spec_repair.prompt not in claude_shim["argv"](2)
    assert miner_capture["spec"].prompt not in miner_capture["argv"]


# ===================================================================== #
# LG -- log bytes
# ===================================================================== #

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"


def _sdk_env(monkeypatch, *, cli_path: Path | str | None = None) -> None:
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(cli_path if cli_path is not None else FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")


#: U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): the sdk
#: leg of `test_u_sdka.py::_Leg.fail`'s kind table, extracted so LG7/WR1/
#: WR5/WR6 can drive the same four failure shapes without importing a
#: fixture cross-file. Mirrors `_Leg.fail`'s sdk branch exactly (same
#: env vars, same "os-error" nonexec-file trick) -- kept in sync by hand
#: since the two files don't share fixtures.
def _analyst_fail_sdk(monkeypatch, tmp_path, kind: str) -> None:
    _sdk_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    if kind == "exit":
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")
    elif kind == "timeout":
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")
        monkeypatch.setenv("SELF_LEARN_ANALYST_TIMEOUT", "0.5")
    elif kind == "not-found":
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
    elif kind == "os-error":
        bad = tmp_path / "analyst-fail-nonexec"
        bad.write_text("", encoding="utf-8")
        bad.chmod(0o644)
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(bad))
    else:
        raise AssertionError(f"{kind!r}: not a recognised _analyst_fail_sdk kind")


def _run_sdk(
    surface: str,
    monkeypatch,
    *,
    prompt: str = "ok_text",
    timeout: float = 5.0,
    timeout_display=None,
    label: str = "",
    log=None,
    cli_path: Path | str | None = None,
) -> invocation.Outcome:
    """U-cleanup-A LG-group rebase: drives `SdkBackend` (real subprocess,
    `tests/fixtures/fake_claude.py`) directly, the same shape
    `test_invocation_sdk.py::_run` uses. `text_session` for `analyst`,
    `write_session` otherwise (`S-a`). `cli_path` overrides the default
    fake -- e.g. a nonexistent path, for the `not-found` leg."""
    _sdk_env(monkeypatch, cli_path=cli_path)
    spec = _spec(surface, prompt=prompt, timeout=timeout, timeout_display=timeout_display, label=label, log=log)
    method = SdkBackend().text_session if surface == "analyst" else SdkBackend().write_session
    return method(spec)


def test_lg1_twelve_byte_identical_log_lines(monkeypatch):
    """U-cleanup-A RO-6/CV3 host, rebased onto `SdkBackend`
    (§10.1 disposition: "LG* rows... re-base onto the SDK backend in A").
    `rc` is SYNTHETIC under sdk (`test_ou2`) -- always `1` on the `exit`
    leg, never the CLI's real exit code -- so this rebase asserts the
    template SHAPE (`f"...exited 1: "` prefix) rather than the CLI's
    literal `exited 7`. The full byte-pin over every `LOG_TEMPLATES` row
    is `test_templates_byte_pinned_ro6` (`test_invocation_sdk.py`); this
    test keeps exercising the SAME 12 real-transport legs (4 kinds x 3
    surfaces) `LG1` always did, now against the surviving backend."""
    # -- exited: worker / repair / miner (rc synthetic = 1 under sdk)
    for surface, label in (("worker", ""), ("worker-repair", "repair "), ("miner-reader", "")):
        logs = []
        outcome = _run_sdk(surface, monkeypatch, prompt="hard_exit", timeout=5.0, label=label, log=logs.append)
        assert outcome.failure == "exit"
        assert logs and logs[0].startswith(f"run: {label}claude exited 1: "), (surface, logs)

    # -- timed out: real wait stays short (0.3s); timeout_display renders
    # the ORIGINAL CLI-era wall-clock values (1800/600/900) -- exactly
    # what `timeout_display` exists for (`LG3B`/`LG3C`).
    for surface, label, display in (
        ("worker", "", 1800.0), ("worker-repair", "repair ", 600.0), ("miner-reader", "", 900),
    ):
        logs = []
        outcome = _run_sdk(
            surface, monkeypatch, prompt="hang", timeout=0.3, timeout_display=display, label=label, log=logs.append
        )
        assert outcome.failure == "timeout"
        expected = f"run: {label}claude timed out after {display:g}s" if isinstance(display, float) else f"run: {label}claude timed out after {display}s"
        # logs[0] only -- the sdk kill ladder may emit further diagnostic
        # lines after the primary timeout line (`disconnect()` escalation).
        assert logs and logs[0] == expected, (surface, logs, expected)

    # -- not found: worker / repair / miner
    for surface, label in (("worker", ""), ("worker-repair", "repair "), ("miner-reader", "")):
        logs = []
        outcome = _run_sdk(
            surface, monkeypatch, prompt="ok_text", timeout=5.0, label=label, log=logs.append,
            cli_path="/nonexistent/claude-fake",
        )
        assert outcome.failure == "not-found"
        assert logs == [f"run: {label}claude CLI not found on PATH"]

    # -- os_error: worker / repair / miner (ClaudeSDKClient.connect raises)
    import claude_agent_sdk

    async def _os_err(self):
        raise OSError("nope")

    original_connect = claude_agent_sdk.ClaudeSDKClient.connect
    monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", _os_err)
    try:
        for surface, label, template_prefix in (
            ("worker", "", "run: claude invocation failed (nope)"),
            ("worker-repair", "repair ", "run: repair claude invocation failed (nope)"),
            ("miner-reader", "", "run: reader invocation failed (nope)"),
        ):
            logs = []
            outcome = _run_sdk(surface, monkeypatch, prompt="ok_text", timeout=5.0, label=label, log=logs.append)
            assert outcome.failure == "os-error"
            assert logs == [template_prefix]
    finally:
        monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", original_connect)


def test_lg2_repair_label_appears_only_in_repair_lines(monkeypatch):
    logs_batch = []
    _run_sdk("worker", monkeypatch, prompt="hard_exit", timeout=5.0, label="", log=logs_batch.append)
    logs_repair = []
    _run_sdk("worker-repair", monkeypatch, prompt="hard_exit", timeout=5.0, label="repair ", log=logs_repair.append)
    assert not any("repair" in line for line in logs_batch)
    assert logs_repair and all("repair " in line for line in logs_repair)


def test_lg3a_worker_g_format(monkeypatch):
    logs = []
    outcome = _run_sdk(
        "worker", monkeypatch, prompt="hang", timeout=0.3, label="", timeout_display=1800.0, log=logs.append
    )
    assert outcome.failure == "timeout"
    assert logs[0] == "run: claude timed out after 1800s"  # `:g` format drops the trailing .0


def test_lg3b_miner_no_g_format(monkeypatch):
    logs = []
    outcome = _run_sdk(
        "miner-reader", monkeypatch, prompt="hang", timeout=0.3, timeout_display=900.0, log=logs.append
    )
    assert outcome.failure == "timeout"
    assert logs[0] == "run: claude timed out after 900.0s"  # miner's template has no `:g` -- keeps the .0


def test_lg3c_timeout_display_is_actually_read(monkeypatch):
    logs = []
    outcome = _run_sdk(
        "miner-reader", monkeypatch, prompt="hang", timeout=0.3, timeout_display=900, log=logs.append
    )
    assert outcome.failure == "timeout"
    assert logs[0] == "run: claude timed out after 900s"


@pytest.mark.skip(reason="U-cleanup-A NIT-6 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): CliBackend "
    "transport-mechanics test; live sdk analogue is "
    "test_reader_contract.py::test_to1_transport_timeout_is_the_patched_value -- disposition is "
    "skip-to-B (delete alongside CliBackend, U-cleanup-B), not migrate.")
def test_lg4_miner_timeout_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "lg4-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "lg4-xdg"))
    home = tmp_path / "lg4-home"
    home.mkdir()
    out_file = miner.spool_dir() / miner.OUTPUT_BASENAME
    captured = {}

    class _Capture:
        def __init__(self):
            self.pid = 1
            self.returncode = 0

        def __call__(self, argv, **kwargs):
            return self

        def communicate(self, prompt, timeout=None):
            captured["timeout"] = timeout
            out_file.write_text('{"candidates": [], "fires": []}', encoding="utf-8")
            return ("", None)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _Capture())
    monkeypatch.setattr(miner, "INVOKE_TIMEOUT_SECS", 42)
    miner._invoke_reader(home, "PROMPT")
    assert captured["timeout"] == 42


def test_lg5_detail_rendering_per_surface(monkeypatch):
    """U-cleanup-A LG-group rebase. The original's "invert stdout/stderr"
    leg is DROPPED, not migrated: the sdk backend's exit-detail comes from
    the SDK's own `ResultMessage`/`ProcessError` text (`backend.py:
    _extract_text`/`str(exc)`), not a captured child stdout/stderr pair --
    there is no second channel to invert. `detail_cap`/`detail_strip`
    SURVIVE (`_render_exit_detail`, table-driven, identical function on
    both backends) and are driven here via the `error_result` scenario's
    `FAKE_CLAUDE_ERROR_TEXT` knob, which lands in `result_message.errors`
    -> `detail` on the `is_error` ResultMessage leg (`backend.py:337`)."""
    # cap: worker/miner carry 400 chars; analyst carries all 600
    long_detail = "X" * 600
    monkeypatch.setenv("FAKE_CLAUDE_ERROR_TEXT", long_detail)
    logs = []
    _run_sdk("worker", monkeypatch, prompt="error_result", label="", log=logs.append)
    assert logs[0].count("X") == 400

    logs = []
    _run_sdk("miner-reader", monkeypatch, prompt="error_result", log=logs.append)
    assert logs[0].count("X") == 400

    logs = []
    _run_sdk("analyst", monkeypatch, prompt="error_result", log=logs.append)
    assert logs[0].count("X") == 600

    # strip: analyst strips; worker/miner don't
    padded = "  padded text  "
    monkeypatch.setenv("FAKE_CLAUDE_ERROR_TEXT", padded)
    logs = []
    _run_sdk("worker", monkeypatch, prompt="error_result", label="", log=logs.append)
    assert padded in logs[0]

    logs = []
    _run_sdk("analyst", monkeypatch, prompt="error_result", log=logs.append)
    assert padded.strip() in logs[0]
    assert padded not in logs[0]
    monkeypatch.delenv("FAKE_CLAUDE_ERROR_TEXT", raising=False)


def test_lg6_clean_invocation_logs_nothing(monkeypatch):
    for surface in ("worker", "worker-repair"):
        logs = []
        outcome = _run_sdk(surface, monkeypatch, prompt="ok_text", log=logs.append)
        assert outcome.ok
        assert logs == []
    logs = []
    outcome = _run_sdk("analyst", monkeypatch, prompt="ok_text", log=logs.append)
    assert outcome.ok
    assert logs == []
    logs = []
    outcome = _run_sdk("miner-reader", monkeypatch, prompt="ok_text", log=logs.append)
    assert outcome.ok
    assert logs == []


def test_lg7_analyst_invocation_never_grows_worker_or_miner_log(analyst_env, tmp_path, monkeypatch):
    """U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F):
    rebased onto the sdk transport -- the property (analyst logging never
    reaches `worker.log`/`miner.log`, i.e. log-channel isolation across
    surfaces) is backend-independent, so the four `subprocess.run` arms
    become the same four `_analyst_fail_sdk` kinds `test_u_sdka.py::
    _Leg.fail` already uses, plus one real success leg driven through
    `FAKE_CLAUDE_OUT`/`analyst_result` (the sdk analogue of the old
    rc=0-with-YAML-stdout arm)."""
    worker_log_calls = []
    miner_log_calls = []
    monkeypatch.setattr(worker, "log", worker_log_calls.append)
    monkeypatch.setattr(miner, "log", miner_log_calls.append)

    out_path = tmp_path / "lg7-analyst-out.txt"

    def _arm_ok():
        _sdk_env(monkeypatch)
        monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
        out_path.write_text("destination: skill-md\nrationale: x\n", encoding="utf-8")
        monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out_path))

    arms = [
        _arm_ok,
        lambda: _analyst_fail_sdk(monkeypatch, tmp_path, "not-found"),
        lambda: _analyst_fail_sdk(monkeypatch, tmp_path, "timeout"),
        lambda: _analyst_fail_sdk(monkeypatch, tmp_path, "exit"),
    ]
    for arm in arms:
        arm()
        try:
            analyst.analyze(analyst_env.home, make_behavior())
        except analyst.AnalystError:
            pass
        assert worker_log_calls == []
        assert miner_log_calls == []


# ===================================================================== #
# TR -- transport
# ===================================================================== #


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr1_surfaces_reach_the_right_transport(monkeypatch):
    run_calls = []

    def fake_run(argv, **kwargs):
        run_calls.append(argv)
        return _Proc(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    popen = _FakePopen(returncode=0, output="")
    monkeypatch.setattr(subprocess, "Popen", popen)

    invocation.CliBackend().write_session(_spec("worker"))
    invocation.CliBackend().write_session(_spec("worker-repair"))
    invocation.CliBackend().text_session(_spec("analyst"))
    assert len(run_calls) == 3
    assert popen.calls == []

    invocation.CliBackend().write_session(_spec("miner-reader"))
    assert len(run_calls) == 3
    assert len(popen.calls) == 1


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr2_miner_popen_kwargs(monkeypatch):
    captured_kwargs = {}

    class _Capture:
        def __call__(self, argv, **kwargs):
            captured_kwargs.update(kwargs)
            self.pid = 1
            self.returncode = 0
            return self

        def communicate(self, prompt, timeout=None):
            return ("", None)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _Capture())
    invocation.CliBackend().write_session(_spec("miner-reader"))
    assert captured_kwargs["start_new_session"] is True
    assert captured_kwargs["stdin"] is subprocess.PIPE
    assert captured_kwargs["stdout"] is subprocess.PIPE
    assert captured_kwargs["stderr"] is subprocess.STDOUT
    assert captured_kwargs["text"] is True


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr3_miner_timeout_killpg_and_wait(monkeypatch):
    class _TimeoutOnce:
        def __init__(self):
            self.pid = 4242
            self.waited = False

        def __call__(self, argv, **kwargs):
            return self

        def communicate(self, prompt, timeout=None):
            raise subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=timeout)

        def wait(self):
            self.waited = True
            return 0

    popen = _TimeoutOnce()
    monkeypatch.setattr(subprocess, "Popen", popen)
    killpg_calls = []

    def fake_killpg(pid, sig):
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)
    outcome = invocation.CliBackend().write_session(_spec("miner-reader"))
    assert outcome.failure == "timeout"
    assert killpg_calls == [(4242, signal.SIGKILL)]
    assert popen.waited is True

    for exc_cls in (ProcessLookupError, PermissionError):
        popen2 = _TimeoutOnce()
        monkeypatch.setattr(subprocess, "Popen", popen2)

        def fake_killpg_raises(pid, sig, _exc_cls=exc_cls):
            raise _exc_cls()

        monkeypatch.setattr(os, "killpg", fake_killpg_raises)
        outcome2 = invocation.CliBackend().write_session(_spec("miner-reader"))
        assert outcome2.failure == "timeout"
        assert popen2.waited is True


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr4_bare_os_error_is_caught_on_analyst_worker_and_miner(monkeypatch):
    # U-sdka Err-1 (FW-87): the preserved defect (R-1/T-c) is retired --
    # a bare OSError is now converted to an "os-error" Outcome on every
    # surface, the analyst included.
    monkeypatch.setattr(subprocess, "run", _run_raises(OSError("permission denied")))
    outcome_analyst = invocation.CliBackend().text_session(_spec("analyst"))
    assert outcome_analyst.failure == "os-error"

    outcome_worker = invocation.CliBackend().write_session(_spec("worker"))
    assert outcome_worker.failure == "os-error"

    monkeypatch.setattr(subprocess, "Popen", _PopenRaises(OSError("permission denied")))
    outcome_miner = invocation.CliBackend().write_session(_spec("miner-reader"))
    assert outcome_miner.failure == "os-error"


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr5_cwd_passed_for_every_surface(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["run_cwd"] = kwargs.get("cwd")
        return _Proc(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    invocation.CliBackend().write_session(_spec("worker", cwd=tmp_path))
    assert captured["run_cwd"] == str(tmp_path)
    invocation.CliBackend().text_session(_spec("analyst", cwd=tmp_path))
    assert captured["run_cwd"] == str(tmp_path)

    class _CapturePopen:
        def __call__(self, argv, **kwargs):
            captured["popen_cwd"] = kwargs.get("cwd")
            self.pid = 1
            self.returncode = 0
            return self

        def communicate(self, prompt, timeout=None):
            return ("", None)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _CapturePopen())
    invocation.CliBackend().write_session(_spec("miner-reader", cwd=tmp_path))
    assert captured["popen_cwd"] == str(tmp_path)


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr6_argv_positional_timeout_keyword(monkeypatch):
    """F2 (gate NOTE-1): a positive control on EACH transport, exactly
    as TR7's -- without it, a transport that's never reached leaves
    every assertion above un-run and the test passes vacuously (gate
    measured this fail-open under M4b)."""
    called_run = []

    def fake_run(*args, **kwargs):
        called_run.append(1)
        assert len(args) == 1
        assert "timeout" in kwargs
        return _Proc(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    invocation.CliBackend().write_session(_spec("worker"))
    assert called_run == [1]

    called_popen = []

    class _PosPopen:
        def __call__(self, *args, **kwargs):
            called_popen.append(1)
            assert len(args) == 1
            self.pid = 1
            self.returncode = 0
            return self

        def communicate(self, *args, **kwargs):
            assert "timeout" in kwargs
            return ("", None)

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _PosPopen())
    invocation.CliBackend().write_session(_spec("miner-reader"))
    assert called_popen == [1]


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_tr7_transport_reached_through_the_subprocess_module_attribute(monkeypatch):
    """B-3/TR7: `cli.py` reaches the transport as `subprocess.run(...)`
    through the MODULE object -- patching `subprocess.run` AFTER import
    intercepts the call (the same mechanism `test_repair.py::test_e1`
    relies on)."""
    called = []

    def fake_run(*a, **kw):
        called.append(1)
        return _Proc(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    invocation.CliBackend().write_session(_spec("worker"))
    assert called == [1]


# ===================================================================== #
# RG -- registry
# ===================================================================== #


def test_rg1_five_rung_precedence_resolves_in_isolation(tmp_path, monkeypatch, sdk_absent):
    home = tmp_path / "rg1-home"
    home.mkdir()
    for surface in invocation.SURFACES:
        selector = invocation.SELECTOR_FOR_SURFACE[surface]

        # code-gate MAJOR-1: every surface's own default is now "sdk"
        # (the U-flip table), so a "sdk" stimulus at rungs 1-4 would be
        # tautological with the (unset) default -- indistinguishable from
        # the rung never being read at all. Inverted to "cli", asserting
        # `CliBackend`: only an override that genuinely reaches that rung
        # can produce this result, since the default never would.
        _clear_backend_env(monkeypatch)
        _clear_config(home)
        monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "cli")
        assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
        assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "cli"})
        assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
        _clear_config(home)

        _write_config(home, {"backend": "cli"})
        assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
        _clear_config(home)

        # U-sdka `A-c` / U-flip: the default rung is surface-aware, read
        # directly off the table rather than hardcoded here -- U-sdka
        # flipped the analyst alone, U-flip flipped the remaining three
        # (worker/worker-repair/miner-reader), so every surface now takes
        # the BackendUnavailable leg (sdk_absent is active); this branch
        # stays live for whichever surfaces the table still names "cli".
        if invocation.contract.DEFAULT_BACKEND_FOR_SURFACE[surface] == "cli":
            assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
        else:
            with pytest.raises(invocation.BackendUnavailable):
                invocation.backend_for(surface, home=home)


def test_rg2_each_rung_shadows_the_ones_below(tmp_path, monkeypatch, sdk_absent):
    home = tmp_path / "rg2-home"
    home.mkdir()
    surface, selector = "worker", "WORKER"

    _clear_backend_env(monkeypatch)
    _clear_config(home)
    monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    _write_config(home, {f"backend_{surface}": "cli", "backend": "cli"})
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for(surface, home=home)

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    _write_config(home, {f"backend_{surface}": "cli", "backend": "cli"})
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for(surface, home=home)

    _clear_backend_env(monkeypatch)
    _write_config(home, {f"backend_{surface}": "sdk", "backend": "cli"})
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for(surface, home=home)

    # code-gate MAJOR-1: "worker"'s own default is now sdk, so an
    # isolated "sdk" stimulus here (nothing else set) is tautological
    # with the default -- indistinguishable from rung 4 never being
    # read at all. Inverted to "cli", asserting `CliBackend`.
    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend": "cli"})
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)

    # U-flip flipped "worker"'s default to sdk (same table rung the
    # analyst flip, U-sdka, used); `sdk_absent` is active, so the
    # default rung now raises rather than returning `CliBackend`.
    _clear_config(home)
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for(surface, home=home)

    # surface -> selector: WORKER governs worker-repair, MINER does not.
    # code-gate MAJOR-1: worker-repair's own default is now sdk too, so
    # a "sdk" stimulus here would be tautological with the (unset)
    # default. Inverted to "cli", asserting `CliBackend`: only a WORKER
    # selector that genuinely governs worker-repair can produce this.
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    assert isinstance(invocation.backend_for("worker-repair", home=home), invocation.CliBackend)

    # U-flip flipped worker-repair's own default to sdk too, so a
    # MINER-leak stimulus of "sdk" would be tautological with the
    # correct (non-leaked) answer -- both raise BackendUnavailable.
    # Inverted to "cli": a leak would resolve worker-repair to
    # CliBackend (no exception); the correct, non-leaked answer still
    # raises (worker-repair's own sdk default).
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("worker-repair", home=home)


def test_rg3_unknown_value_falls_closed_with_byte_exact_warning(tmp_path, monkeypatch, capsys):
    home = tmp_path / "rg3-home"
    home.mkdir()
    surface, selector = "miner-reader", "MINER"

    _clear_backend_env(monkeypatch)
    _clear_config(home)
    monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "bogus")
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        f"self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND_{selector}"
        ' — using "cli"\n'
    )

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        "self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND" ' — using "cli"\n'
    )

    _clear_backend_env(monkeypatch)
    _write_config(home, {f"backend_{surface}": "bogus"})
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        f'self-learn: config.yaml ignored — invocation.backend_{surface} must be '
        'one of cli, sdk; got \'bogus\' — using "cli"\n'
    )
    _clear_config(home)

    _write_config(home, {"backend": "bogus"})
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        'self-learn: config.yaml ignored — invocation.backend must be '
        'one of cli, sdk; got \'bogus\' — using "cli"\n'
    )
    _clear_config(home)

    # does NOT fall through: bogus at rung 2 with sdk at rung 4 -> cli, not sdk.
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    _write_config(home, {"backend": "sdk"})
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)


def test_rg4_sdk_raises_backend_unavailable_with_install_command(monkeypatch, tmp_path, sdk_absent):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    with pytest.raises(invocation.BackendUnavailable) as exc_info:
        invocation.backend_for("worker", home=tmp_path)
    assert "pip install 'self-learn-cli[sdk]'" in str(exc_info.value)


def test_rg5_write_session_returns_unavailable_without_raising(monkeypatch, tmp_path, sdk_absent):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    logs = []
    spec = _spec("worker", cwd=tmp_path, log=logs.append)
    outcome = invocation.write_session(spec)
    assert outcome.ok is False
    assert outcome.failure == "unavailable"
    assert logs
    assert "CLI not found on PATH" not in logs[0]
    assert "unavailable" in logs[0]


def test_rg5_text_session_returns_unavailable_without_raising(monkeypatch, tmp_path, sdk_absent):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    logs = []
    spec = _spec("analyst", cwd=tmp_path, log=logs.append)
    outcome = invocation.text_session(spec)
    assert outcome.ok is False
    assert outcome.failure == "unavailable"


def test_rg5_analyst_analyze_converts_unavailable_to_analyst_error(monkeypatch, analyst_env, sdk_absent):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    with pytest.raises(analyst.AnalystError) as exc_info:
        analyst.analyze(analyst_env.home, make_behavior())
    assert "invocation backend unavailable" in str(exc_info.value)
    assert "pip install 'self-learn-cli[sdk]'" in str(exc_info.value)


def test_rg5_shimmed_worker_run_completes_under_sdk_selection(env, claude_shim, monkeypatch, sdk_absent):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    seed_pending(env)
    result = worker.run(env.home)
    assert claude_shim["count"]() == 0  # never actually spawned
    assert result is not None


def test_rg5_unknown_surface_returns_outcome_never_keyerror():
    spec = _spec("nope")
    try:
        outcome = invocation.write_session(spec)
    except KeyError:
        pytest.fail("write_session raised KeyError for an unknown surface")
    assert outcome.ok is False
    assert outcome.failure == "unavailable"

    try:
        outcome2 = invocation.text_session(spec)
    except KeyError:
        pytest.fail("text_session raised KeyError for an unknown surface")
    assert outcome2.ok is False
    assert outcome2.failure == "unavailable"


def test_rg6_empty_string_falls_through_silently(tmp_path, monkeypatch, capsys):
    home = tmp_path / "rg6-home"
    home.mkdir()
    _clear_backend_env(monkeypatch)
    _clear_config(home)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "")
    _write_config(home, {"backend_worker": "", "backend": ""})
    backend = invocation.backend_for("worker", home=home)
    # U-flip flipped "worker"'s default to sdk -- falling all the way
    # through to the default rung now resolves a real `SdkBackend`, not
    # `CliBackend`. The invariant under test (every empty value falls
    # through SILENTLY) is the `err == ""` assertion below, not the
    # resolved backend's type.
    from self_learn.invocation_sdk import SdkBackend as _SdkBackend
    assert isinstance(backend, _SdkBackend)
    assert capsys.readouterr().err == ""


def test_rg7_config_invocation_backend_discipline(tmp_path, capsys, monkeypatch):
    home = tmp_path / "rg7-home"
    home.mkdir()

    assert config.invocation_backend(home, "worker") is None
    assert capsys.readouterr().err == ""

    (home / "config.yaml").write_text("", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert capsys.readouterr().err == ""

    (home / "config.yaml").write_text(":::not yaml {{{\n", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert "config.yaml ignored" in capsys.readouterr().err

    (home / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert "config.yaml ignored" in capsys.readouterr().err

    (home / "config.yaml").write_text("one_motion_route:\n  hook: true\n", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert capsys.readouterr().err == ""

    (home / "config.yaml").write_text("invocation: not-a-mapping\n", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert "config.yaml ignored" in capsys.readouterr().err

    (home / "config.yaml").write_text("invocation:\n  backend: 42\n", encoding="utf-8")
    assert config.invocation_backend(home, "worker") is None
    assert "config.yaml ignored" in capsys.readouterr().err

    (home / "config.yaml").write_text(
        "invocation:\n  backend_worker: cli\n  backend: sdk\n", encoding="utf-8"
    )
    assert config.invocation_backend(home, "worker") == ("backend_worker", "cli")
    assert config.invocation_backend(home, "miner-reader") == ("backend", "sdk")
    assert capsys.readouterr().err == ""

    assert "invocation_backend" in config.__all__

    home2 = tmp_path / "rg7-home2"
    home2.mkdir()
    (home2 / "config.yaml").write_text("invocation:\n  backend_worker: bogus\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(config, "_warn", lambda message: calls.append(message))
    _clear_backend_env(monkeypatch)
    invocation.backend_for("worker", home=home2)
    assert calls, "the registry's unknown-value warning must be emitted via config._warn"


def test_rg8_pyproject_sdk_extra_matches_ui_pin():
    cli_pyproject = Path(worker.__file__).resolve().parents[2] / "pyproject.toml"
    ui_pyproject = Path(worker.__file__).resolve().parents[3] / "ui" / "pyproject.toml"
    cli_text = cli_pyproject.read_text(encoding="utf-8")
    ui_text = ui_pyproject.read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in cli_text

    m = re.search(r'"claude-agent-sdk[^"]*"', ui_text)
    assert m is not None, "UI pyproject.toml has no claude-agent-sdk pin to compare against"
    ui_pin = m.group(0).strip('"')
    assert f'sdk = ["{ui_pin}"]' in cli_text


# ===================================================================== #
# FK -- the fake
# ===================================================================== #


def test_fk1_fakebackend_records_specs_prompts_and_argvs():
    backend = invocation.FakeBackend([invocation.Text("hi"), invocation.Exits(rc=3, detail="boom")])
    spec1 = _spec("analyst", prompt="P1", argv=["claude", "-p", "P1"])
    spec2 = _spec("worker", prompt="P2", argv=["claude", "-p", "x", "--settings", "s"])
    backend.text_session(spec1)
    backend.write_session(spec2)
    assert backend.specs == [spec1, spec2]
    assert backend.prompts == ["P1", "P2"]
    assert backend.argvs == [["claude", "-p", "P1"], ["claude", "-p", "x", "--settings", "s"]]


def test_fk2_each_fakestep_matches_sdkbackend_for_the_same_failure(monkeypatch):
    """U-cleanup-A §10.1: "fk2 compares FakeBackend against CliBackend per
    failure kind -> re-base onto FakeBackend vs SdkBackend." Each
    `FakeStep` is scripted to produce the SAME rendered log line as the
    matching real `SdkBackend` failure -- `rc=1` on the exit leg (sdk's
    rc is always synthetic, `test_ou2`), `timeout_display` aligned to the
    real transport's `timeout`, an identical exception message on the
    os-error leg."""
    real_logs = []
    _run_sdk("worker", monkeypatch, prompt="hard_exit", timeout=5.0, label="", log=real_logs.append)
    exit_detail = real_logs[0][len("run: claude exited 1: ") :]
    fake_logs = []
    fake_outcome = invocation.FakeBackend([invocation.Exits(rc=1, detail=exit_detail)]).write_session(
        _spec("worker", log=fake_logs.append, label="")
    )
    assert fake_outcome.failure == "exit"
    assert fake_logs == real_logs, ("exit", fake_logs, real_logs)

    real_logs = []
    real_outcome = _run_sdk(
        "worker", monkeypatch, prompt="hang", timeout=0.3, timeout_display=30.0, label="", log=real_logs.append
    )
    fake_logs = []
    fake_outcome = invocation.FakeBackend([invocation.TimesOut()]).write_session(
        _spec("worker", log=fake_logs.append, label="", timeout=30.0)
    )
    assert real_outcome.failure == fake_outcome.failure == "timeout"
    assert fake_logs == [real_logs[0]], ("timeout", fake_logs, real_logs)

    real_logs = []
    real_outcome = _run_sdk(
        "worker", monkeypatch, prompt="ok_text", timeout=5.0, label="", log=real_logs.append,
        cli_path="/nonexistent/claude-fake",
    )
    fake_logs = []
    fake_outcome = invocation.FakeBackend([invocation.NotFound()]).write_session(
        _spec("worker", log=fake_logs.append, label="")
    )
    assert real_outcome.failure == fake_outcome.failure == "not-found"
    assert fake_logs == real_logs, ("not-found", fake_logs, real_logs)

    import claude_agent_sdk

    async def _os_err(self):
        raise OSError("boom-os")

    original_connect = claude_agent_sdk.ClaudeSDKClient.connect
    monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", _os_err)
    try:
        real_logs = []
        real_outcome = _run_sdk("worker", monkeypatch, prompt="ok_text", timeout=5.0, label="", log=real_logs.append)
    finally:
        monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", original_connect)
    fake_logs = []
    fake_outcome = invocation.FakeBackend([invocation.Fails(exc=OSError("boom-os"))]).write_session(
        _spec("worker", log=fake_logs.append, label="")
    )
    assert real_outcome.failure == fake_outcome.failure == "os-error"
    assert fake_logs == real_logs, ("os-error", fake_logs, real_logs)


def test_fk3_fake_is_not_reachable_from_backend_for(monkeypatch, tmp_path, capsys):
    assert "fake" not in invocation.KNOWN_BACKENDS
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "fake")
    backend = invocation.backend_for("worker", home=tmp_path)
    assert isinstance(backend, invocation.CliBackend)
    assert not isinstance(backend, invocation.FakeBackend)
    assert "unknown invocation backend 'fake'" in capsys.readouterr().err


def test_fk4_writes_step_creates_files(tmp_path):
    target = tmp_path / "sub" / "out.yaml"
    backend = invocation.FakeBackend([invocation.Writes({target: "content\n"})])
    outcome = backend.write_session(_spec("worker"))
    assert outcome.ok
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "content\n"


# ===================================================================== #
# WR -- wiring
# ===================================================================== #


def test_wr1_invoke_claude_signature_and_never_raises(tmp_path, monkeypatch):
    """U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): the
    signature clause is unchanged -- `worker._invoke_claude` is real,
    still-shipped product code (it now calls `invocation.write_session`
    internally, `worker.py:3121-3155`), and its positional/keyword-only
    shape is a property independent of which backend a call resolves to.
    The never-raises legs are rebased onto sdk: `_invoke_claude` always
    returns `None` (no `return` statement at all -- `-> None`, the
    result of `write_session` is discarded), so `is None` was always
    trivially true; the REAL property under test, then and now, is that
    calling it never lets an exception escape regardless of how the
    session fails -- exactly `test_hd4_seam_is_total_on_the_analyst_
    surface`'s (`test_u_sdka.py`) shape, but driven for the WORKER
    surface (no analogous worker-surface seam-is-total test existed
    before this migration)."""
    sig = inspect.signature(worker._invoke_claude)
    params = list(sig.parameters.values())
    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert [p.name for p in positional] == ["argv", "prompt", "timeout", "home"]
    assert sig.parameters["label"].kind == inspect.Parameter.KEYWORD_ONLY

    _sdk_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")

    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
    assert worker._invoke_claude(["claude"], "p", 5.0, tmp_path, label="") is None

    _sdk_env(monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")
    assert worker._invoke_claude(["claude"], "p", 0.3, tmp_path, label="") is None  # timeout: real, short

    bad = tmp_path / "wr1-nonexec"
    bad.write_text("", encoding="utf-8")
    bad.chmod(0o644)
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(bad))
    assert worker._invoke_claude(["claude"], "p", 5.0, tmp_path, label="") is None  # os-error

    _sdk_env(monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")
    assert worker._invoke_claude(["claude"], "p", 5.0, tmp_path, label="") is None  # exit


def test_wr2_miner_early_returns_precede_the_stray_sweep(monkeypatch, tmp_path, sdk_absent):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "wr2-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "wr2-xdg"))
    home = tmp_path / "wr2-home"
    home.mkdir()
    spool = miner.spool_dir()
    stray = spool / "litter.txt"

    scenarios = [
        ("timeout", _FakePopen(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1))),
        ("not-found", _PopenRaises(FileNotFoundError())),
        ("os-error", _PopenRaises(OSError("x"))),
    ]
    for name, popen in scenarios:
        stray.write_text("litter", encoding="utf-8")
        monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)
        monkeypatch.setattr(subprocess, "Popen", popen)
        out = miner._invoke_reader(home, "PROMPT")
        assert out is None, name
        assert stray.exists(), f"{name}: stray sweep ran despite an early return"

    # unavailable leg -- U-flip pins SELF_LEARN_BACKEND_MINER=cli at rung
    # 1 (conftest's suite-wide default); clear it too, or it shadows this
    # rung-2 override and miner-reader never reaches "unavailable".
    stray.write_text("litter", encoding="utf-8")
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    out = miner._invoke_reader(home, "PROMPT")
    assert out is None
    assert stray.exists(), "unavailable: stray sweep ran despite an early return"
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)


@pytest.mark.skip(reason="U-cleanup-A NIT-6 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): CliBackend "
    "transport-mechanics test; live sdk analogue is "
    "test_reader_contract.py::test_sw2_rc_nonzero_does_not_short_circuit -- disposition is "
    "skip-to-B (delete alongside CliBackend, U-cleanup-B), not migrate.")
def test_wr3_miner_rc_nonzero_does_not_short_circuit(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "wr3-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "wr3-xdg"))
    home = tmp_path / "wr3-home"
    home.mkdir()
    spool = miner.spool_dir()
    out_file = spool / miner.OUTPUT_BASENAME
    monkeypatch.setattr(
        subprocess,
        "Popen",
        _FakePopen(
            returncode=1,
            output="stderr text",
            write_file=out_file,
            write_content='{"candidates": [], "fires": []}',
        ),
    )
    out = miner._invoke_reader(home, "PROMPT")
    assert out is not None
    assert out.is_file()


@pytest.mark.skip(reason="U-cleanup-A: CliBackend transport-mechanics test; unreached pending U-cleanup-B deletion (AG1)")
def test_wr4_outcome_stdout_per_surface(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_returns(0, stdout="STDOUT-TEXT", stderr=""))
    assert invocation.CliBackend().write_session(_spec("worker")).stdout == ""
    assert invocation.CliBackend().write_session(_spec("worker-repair")).stdout == ""
    assert invocation.CliBackend().text_session(_spec("analyst")).stdout == "STDOUT-TEXT"

    monkeypatch.setattr(subprocess, "Popen", _FakePopen(returncode=0, output="MERGED-OUT"))
    assert invocation.CliBackend().write_session(_spec("miner-reader")).stdout == "MERGED-OUT"


def test_wr5_analyst_error_carries_cause_for_not_found_and_timeout(analyst_env, tmp_path, monkeypatch):
    """U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F):
    rebased onto sdk -- these were the ONLY live `__cause__` assertions
    for the not-found/timeout legs in the suite; skipping this test
    silently dropped both. Not-found's chained exception has an sdk
    analogue -- `claude_agent_sdk.CLINotFoundError`, NOT `FileNotFoundError`
    (measured: `invocation_sdk/backend.py:465` catches `CLINotFoundError`
    and threads it through as `exc=exc`; `analyst.py:263` re-raises `from
    outcome.exc`). Timeout does NOT have a chained-exception analogue --
    measured: `invocation_sdk/backend.py:460` catches `asyncio.
    TimeoutError` with no `as` binding at all, so nothing is threaded
    through and `outcome.exc` stays its `None` default (`analyst.py:264-
    268` still does `raise ... from outcome.exc`, i.e. `from None`). That
    is a genuine, verified transport difference, not a migration
    shortcut -- asserting `__cause__ is None` here is what the sdk leg
    actually does, not a tautology (a mistakenly-threaded exception would
    fail it)."""
    from claude_agent_sdk import CLINotFoundError

    _analyst_fail_sdk(monkeypatch, tmp_path, "not-found")
    with pytest.raises(analyst.AnalystError) as exc_info:
        analyst.analyze(analyst_env.home, make_behavior())
    assert isinstance(exc_info.value.__cause__, CLINotFoundError)

    _analyst_fail_sdk(monkeypatch, tmp_path, "timeout")
    with pytest.raises(analyst.AnalystError) as exc_info2:
        analyst.analyze(analyst_env.home, make_behavior())
    assert exc_info2.value.__cause__ is None


def test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates(
    analyst_env, tmp_path, monkeypatch
):
    """U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F):
    legs 1-3 and 5 rebased onto the sdk transport via `_analyst_fail_sdk`
    -- the not-found wording is IDENTICAL on both transports (RO-6's own
    byte-pin: `not_found="claude CLI not found on PATH"` for every
    surface), so that assertion is unchanged. The exit leg's `rc` is
    inherently CLI-specific (a real subprocess exit code): sdk sessions
    have no such code and `invocation_sdk/backend.py` synthesizes
    `rc=1` for every `is_error=True` result (`:343-345`) -- `rc=7` has
    no sdk analogue, so the byte-exact literal becomes `exited 1`, with
    the detail text still controlled via `FAKE_CLAUDE_ERROR_TEXT`. Leg 5
    (rendered THROUGH `LOG_TEMPLATES`) now covers BOTH the not-found AND
    the timed-out legs under sdk -- the gate's own measurement (`M-9`
    against the analyst `timed_out` template) found nothing else in the
    suite catches "rendered through the template" for that leg once this
    test stopped reaching it.

    `sdk_absent` is no longer a whole-test fixture parameter: legs 1-3
    and 5 now need `claude_agent_sdk` to import for real, so the old
    "sdk absent for the whole test" shape (harmless when only leg 4
    touched sdk) would break every other leg. The poisoning is now
    scoped to leg 4 alone via a nested `pytest.MonkeyPatch()`, undone
    immediately after."""
    _analyst_fail_sdk(monkeypatch, tmp_path, "not-found")
    with pytest.raises(analyst.AnalystError) as e1:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e1.value) == "claude CLI not found on PATH"

    _analyst_fail_sdk(monkeypatch, tmp_path, "timeout")
    with pytest.raises(analyst.AnalystError) as e2:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e2.value) == "analyst timed out after 0.5s"

    _analyst_fail_sdk(monkeypatch, tmp_path, "exit")
    monkeypatch.setenv("FAKE_CLAUDE_ERROR_TEXT", "ERR TEXT")
    with pytest.raises(analyst.AnalystError) as e3:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e3.value) == "analyst exited 1: ERR TEXT"

    # -- new: unavailable, byte literal per W-i. sdk-absence poisoning
    # scoped to just this leg (see the docstring) -- undone before leg 5
    # needs a real sdk import again.
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    absent_mp = pytest.MonkeyPatch()
    for name in list(sys.modules):
        if name == "self_learn.invocation_sdk" or name.startswith("self_learn.invocation_sdk."):
            absent_mp.delitem(sys.modules, name, raising=False)
    absent_mp.setitem(sys.modules, "claude_agent_sdk", None)
    try:
        with pytest.raises(analyst.AnalystError) as e4:
            analyst.analyze(analyst_env.home, make_behavior())
    finally:
        absent_mp.undo()
    assert str(e4.value) == (
        'invocation backend unavailable (the "sdk" invocation backend is not '
        "built yet — install it with:\n"
        "    pip install 'self-learn-cli[sdk]')"
    )
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)

    # -- every one of them is rendered through LOG_TEMPLATES["analyst"]
    # (not-found AND timed-out, both under sdk).
    _analyst_fail_sdk(monkeypatch, tmp_path, "not-found")
    original = invocation.LOG_TEMPLATES["analyst"]
    mutated = invocation.LogTemplates(
        exited=original.exited,
        timed_out=original.timed_out,
        not_found="MUTATED NOT FOUND TEXT",
        os_error=original.os_error,
        unavailable=original.unavailable,
        detail_cap=original.detail_cap,
        detail_strip=original.detail_strip,
    )
    monkeypatch.setitem(invocation.LOG_TEMPLATES, "analyst", mutated)
    with pytest.raises(analyst.AnalystError) as e5:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e5.value) == "MUTATED NOT FOUND TEXT"
    monkeypatch.setitem(invocation.LOG_TEMPLATES, "analyst", original)

    _analyst_fail_sdk(monkeypatch, tmp_path, "timeout")
    mutated_timeout = invocation.LogTemplates(
        exited=original.exited,
        timed_out="MUTATED TIMED OUT TEXT",
        not_found=original.not_found,
        os_error=original.os_error,
        unavailable=original.unavailable,
        detail_cap=original.detail_cap,
        detail_strip=original.detail_strip,
    )
    monkeypatch.setitem(invocation.LOG_TEMPLATES, "analyst", mutated_timeout)
    with pytest.raises(analyst.AnalystError) as e6:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e6.value) == "MUTATED TIMED OUT TEXT"


def test_wr7_seam_is_only_called_from_the_three_call_sites():
    src_dir = Path(worker.__file__).resolve().parent
    seam_funcs = {"write_session", "text_session"}
    sites: dict[str, list] = {}
    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name in seam_funcs:
                    rel = str(path.relative_to(src_dir))
                    sites.setdefault(rel, []).append((node.lineno, name))
    assert set(sites) == {"worker.py", "miner.py", "analyst.py"}, sites

    # O-a/D-24: the exclusion is EXPLICIT, by name -- every non-model
    # subprocess spawn site named in Sec 7.1's table, deliberately outside
    # the seam.
    excluded_by_name = (
        "worker._spawn_window",
        "worker._digest",
        "worker._notify",
        "worker._notify_with_ids",
        "miner._spawn_run",
        "gitops.py",
        "hosts.py",
        "ledger.py",
        "ledger_ops.py",
        "chezmoi.py",
        "hook_compiler.py",
    )
    assert len(excluded_by_name) == 11

    # F3 (gate NOTE-6): the tuple above only fails if someone EDITS it --
    # it says nothing about whether the names it lists still exist. A
    # rename on either side (the excluded symbol, or this tuple) strands
    # a stale entry that this leg was blind to. Attribute entries are
    # checked against the real module object; file entries (whole-module
    # exclusions with no single function to name) are checked against
    # the actual source tree.
    _excluded_modules = {"worker": worker, "miner": miner}
    for entry in excluded_by_name:
        if entry.endswith(".py"):
            assert (src_dir / entry).is_file(), (
                f"excluded file {entry} does not exist under {src_dir}"
            )
        else:
            mod_name, _, attr = entry.partition(".")
            assert mod_name in _excluded_modules, f"unknown module in {entry!r}"
            assert hasattr(_excluded_modules[mod_name], attr), (
                f"excluded symbol {entry!r} does not exist -- a rename "
                "stranded a stale entry"
            )
