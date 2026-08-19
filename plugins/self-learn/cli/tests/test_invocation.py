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
from pathlib import Path

import pytest

from self_learn import analyst, config, invocation, miner, worker
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
    shim_dir = tmp_path / "analyst-shim-bin"
    shim_dir.mkdir()
    shim = shim_dir / "claude"
    shim.write_text(_ANALYST_CLAUDE_SHIM, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "analyst-shim-argv.log"
    cwd_log = tmp_path / "analyst-shim-cwd.log"
    out = tmp_path / "analyst-shim-stdout.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_SHIM_LOG", str(log))
    monkeypatch.setenv("CLAUDE_SHIM_CWD", str(cwd_log))
    monkeypatch.setenv("CLAUDE_SHIM_OUT", str(out))
    return {"log": log, "out": out, "cwd": cwd_log}


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
    """Drives a REAL `miner._invoke_reader(home, prompt)` through a
    PATH-shimmed `claude` that succeeds trivially, capturing the spec and
    the real argv the shim observed."""
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "miner-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "miner-xdg-cache"))
    home = tmp_path / "miner-home"
    home.mkdir()
    shims = tmp_path / "miner-shims"
    shims.mkdir()
    spool = miner.spool_dir()
    argv_log = tmp_path / "miner-argv.log"
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat > /dev/null\n"
        f"printf '%s\\0' \"$@\" > \"{argv_log}\"\n"
        f"echo '{{\"candidates\": [], \"fires\": []}}' > \"{spool}/{miner.OUTPUT_BASENAME}\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")

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
    return {"spec": captured[0], "argv": argv, "proposal": proposal}


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


def test_cn8_twin_witnesses_agree_at_runtime_on_a_repair_producing_run(repair_run, claude_shim):
    """CN8 -- runtime agreement on a REAL repair-producing run, both
    invocations checked independently against THEIR OWN captured
    `--settings` value (not each other's)."""
    assert len(repair_run) == 2
    assert [s.surface for s in repair_run] == ["worker", "worker-repair"]
    for n, spec in enumerate(repair_run, start=1):
        argv = claude_shim["argv"](n)
        settings_path = Path(argv[argv.index("--settings") + 1])
        permissions = json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]
        assert invocation.containment_permissions(spec.containment) == permissions


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


def _assert_argv_matches_containment_iff(containment: invocation.Containment, argv: list[str]):
    if containment.allowed_tools is None:
        assert "--allowedTools" not in argv
    else:
        assert "--allowedTools" in argv
        assert argv[argv.index("--allowedTools") + 1] == containment.allowed_tools
    if containment.disallowed_tools is None:
        assert "--disallowedTools" not in argv
    else:
        assert "--disallowedTools" in argv
        assert argv[argv.index("--disallowedTools") + 1] == containment.disallowed_tools
    if containment.strict_mcp:
        assert "--strict-mcp-config" in argv
    else:
        assert "--strict-mcp-config" not in argv


def test_cn10_argv_is_the_third_witness_iff_both_directions(
    repair_run, miner_capture, analyst_capture, claude_shim
):
    spec_worker, spec_repair = repair_run
    _assert_argv_matches_containment_iff(spec_worker.containment, claude_shim["argv"](1))
    _assert_argv_matches_containment_iff(spec_repair.containment, claude_shim["argv"](2))
    _assert_argv_matches_containment_iff(miner_capture["spec"].containment, miner_capture["argv"])
    _assert_argv_matches_containment_iff(analyst_capture["spec"].containment, analyst_capture["argv"])


# ===================================================================== #
# AV -- argv identity
# ===================================================================== #


def test_av1_argv_equals_surfaces_own_builder_output_recomputed(
    repair_run, miner_capture, analyst_capture, claude_shim
):
    """AV1 -- the PATH shims record `"$@"`, which is argv WITHOUT the
    invoked program's own name (`$0`) -- every builder's own output
    (`worker.build_argv`, etc.) leads with `"claude"`, so the captured
    argv is compared against the builder's output with `"claude"`
    prepended, never reused from a closure."""
    spec_worker, spec_repair = repair_run
    argv_worker = claude_shim["argv"](1)
    argv_repair = claude_shim["argv"](2)

    settings_worker = Path(argv_worker[argv_worker.index("--settings") + 1])
    assert ["claude", *argv_worker] == worker.build_argv(spec_worker.cwd, settings_worker)

    settings_repair = Path(argv_repair[argv_repair.index("--settings") + 1])
    assert ["claude", *argv_repair] == worker.build_argv(spec_repair.cwd, settings_repair)

    argv_miner = miner_capture["argv"]
    settings_miner = Path(argv_miner[argv_miner.index("--settings") + 1])
    assert ["claude", *argv_miner] == miner.build_reader_argv(settings_miner)

    spec_analyst = analyst_capture["spec"]
    doctrine_text = analyst.doctrine_path().read_text(encoding="utf-8")
    assert ["claude", *analyst_capture["argv"]] == analyst.build_argv(
        spec_analyst.prompt, doctrine_text, analyst.DEFAULT_ANALYST_MODEL
    )


def test_av2_worker_argv_shape(repair_run, claude_shim):
    for n in (1, 2):
        argv = claude_shim["argv"](n)
        assert argv[-1] == "--strict-mcp-config"
        assert "--mcp-config" not in argv
        prompt = claude_shim["call_prompt"](n)
        assert prompt not in argv


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
    assert analyst_capture["spec"].prompt in analyst_capture["argv"]
    spec_worker, spec_repair = repair_run
    assert spec_worker.prompt not in claude_shim["argv"](1)
    assert spec_repair.prompt not in claude_shim["argv"](2)
    assert miner_capture["spec"].prompt not in miner_capture["argv"]


# ===================================================================== #
# LG -- log bytes
# ===================================================================== #


def test_lg1_twelve_byte_identical_log_lines(monkeypatch):
    # -- exited: worker / repair / miner
    monkeypatch.setattr(subprocess, "run", _run_returns(7, stdout="boom", stderr=""))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert logs == ["run: claude exited 7: boom"]

    logs = []
    invocation.CliBackend().write_session(_spec("worker-repair", log=logs.append, label="repair "))
    assert logs == ["run: repair claude exited 7: boom"]

    monkeypatch.setattr(subprocess, "Popen", _FakePopen(returncode=7, output="boom"))
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append))
    assert logs == ["run: claude exited 7: boom"]

    # -- timed out: worker (1800.0) / repair (600.0) / miner (900)
    monkeypatch.setattr(
        subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1800.0))
    )
    logs = []
    invocation.CliBackend().write_session(
        _spec("worker", log=logs.append, label="", timeout=1800.0)
    )
    assert logs == ["run: claude timed out after 1800s"]

    monkeypatch.setattr(
        subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=600.0))
    )
    logs = []
    invocation.CliBackend().write_session(
        _spec("worker-repair", log=logs.append, label="repair ", timeout=600.0)
    )
    assert logs == ["run: repair claude timed out after 600s"]

    monkeypatch.setattr(
        subprocess, "Popen", _FakePopen(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=900))
    )
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append, timeout=900))
    assert logs == ["run: claude timed out after 900s"]

    # -- not found: worker / repair / miner
    monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError()))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert logs == ["run: claude CLI not found on PATH"]

    logs = []
    invocation.CliBackend().write_session(_spec("worker-repair", log=logs.append, label="repair "))
    assert logs == ["run: repair claude CLI not found on PATH"]

    monkeypatch.setattr(subprocess, "Popen", _PopenRaises(FileNotFoundError()))
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append))
    assert logs == ["run: claude CLI not found on PATH"]

    # -- os_error: worker / repair / miner
    monkeypatch.setattr(subprocess, "run", _run_raises(OSError("nope")))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert logs == ["run: claude invocation failed (nope)"]

    logs = []
    invocation.CliBackend().write_session(_spec("worker-repair", log=logs.append, label="repair "))
    assert logs == ["run: repair claude invocation failed (nope)"]

    monkeypatch.setattr(subprocess, "Popen", _PopenRaises(OSError("nope")))
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append))
    assert logs == ["run: reader invocation failed (nope)"]


def test_lg2_repair_label_appears_only_in_repair_lines(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="", stderr="x"))
    logs_batch = []
    invocation.CliBackend().write_session(_spec("worker", log=logs_batch.append, label=""))
    logs_repair = []
    invocation.CliBackend().write_session(
        _spec("worker-repair", log=logs_repair.append, label="repair ")
    )
    assert not any("repair" in line for line in logs_batch)
    assert logs_repair and all("repair " in line for line in logs_repair)


def test_lg3a_worker_g_format(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1800.0))
    )
    logs = []
    invocation.CliBackend().write_session(
        _spec("worker", log=logs.append, label="", timeout=1800.0, timeout_display=None)
    )
    assert logs == ["run: claude timed out after 1800s"]


def test_lg3b_miner_no_g_format(monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", _FakePopen(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=900))
    )
    logs = []
    invocation.CliBackend().write_session(
        _spec("miner-reader", log=logs.append, timeout=900, timeout_display=900.0)
    )
    assert logs == ["run: claude timed out after 900.0s"]


def test_lg3c_timeout_display_is_actually_read(monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", _FakePopen(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=900.0))
    )
    logs = []
    invocation.CliBackend().write_session(
        _spec("miner-reader", log=logs.append, timeout=900.0, timeout_display=900)
    )
    assert logs == ["run: claude timed out after 900s"]


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
    # invert stdout/stderr: worker+analyst render stderr when present, else stdout
    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="OUT", stderr="ERR"))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert "ERR" in logs[0] and "OUT" not in logs[0]

    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="OUT", stderr=""))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert "OUT" in logs[0]

    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="OUT", stderr="ERR"))
    logs = []
    invocation.CliBackend().text_session(_spec("analyst", log=logs.append))
    assert "ERR" in logs[0] and "OUT" not in logs[0]

    # cap: worker/miner carry 400 chars; analyst carries all 600
    long_detail = "X" * 600
    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="", stderr=long_detail))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert logs[0].count("X") == 400

    monkeypatch.setattr(subprocess, "Popen", _FakePopen(returncode=1, output=long_detail))
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append))
    assert logs[0].count("X") == 400

    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="", stderr=long_detail))
    logs = []
    invocation.CliBackend().text_session(_spec("analyst", log=logs.append))
    assert logs[0].count("X") == 600

    # strip: analyst strips; worker/miner don't
    padded = "  padded text  "
    monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="", stderr=padded))
    logs = []
    invocation.CliBackend().write_session(_spec("worker", log=logs.append, label=""))
    assert padded in logs[0]

    logs = []
    invocation.CliBackend().text_session(_spec("analyst", log=logs.append))
    assert padded.strip() in logs[0]
    assert padded not in logs[0]


def test_lg6_clean_invocation_logs_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_returns(0, stdout="", stderr=""))
    for surface in ("worker", "worker-repair"):
        logs = []
        invocation.CliBackend().write_session(_spec(surface, log=logs.append))
        assert logs == []
    logs = []
    invocation.CliBackend().text_session(_spec("analyst", log=logs.append))
    assert logs == []
    monkeypatch.setattr(subprocess, "Popen", _FakePopen(returncode=0, output=""))
    logs = []
    invocation.CliBackend().write_session(_spec("miner-reader", log=logs.append))
    assert logs == []


def test_lg7_analyst_invocation_never_grows_worker_or_miner_log(analyst_env, monkeypatch):
    worker_log_calls = []
    miner_log_calls = []
    monkeypatch.setattr(worker, "log", worker_log_calls.append)
    monkeypatch.setattr(miner, "log", miner_log_calls.append)

    arms = [
        lambda: monkeypatch.setattr(
            subprocess, "run", _run_returns(0, stdout="destination: skill-md\nrationale: x\n", stderr="")
        ),
        lambda: monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError())),
        lambda: monkeypatch.setattr(
            subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=120))
        ),
        lambda: monkeypatch.setattr(subprocess, "run", _run_returns(1, stdout="", stderr="x")),
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

        _clear_backend_env(monkeypatch)
        _clear_config(home)
        monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "sdk")
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "sdk"})
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)
        _clear_config(home)

        _write_config(home, {"backend": "sdk"})
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)
        _clear_config(home)

        # U-sdka `A-c`: the default rung is now surface-aware -- the
        # analyst's default is `sdk` (BackendUnavailable, sdk_absent is
        # active), every other surface's default is still `cli`.
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

    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend": "sdk"})
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for(surface, home=home)

    _clear_config(home)
    assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)

    # surface -> selector: WORKER governs worker-repair, MINER does not.
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("worker-repair", home=home)

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    assert isinstance(invocation.backend_for("worker-repair", home=home), invocation.CliBackend)


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
    assert isinstance(backend, invocation.CliBackend)
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


def test_fk2_each_fakestep_matches_clibackend_for_the_same_failure(monkeypatch):
    scenarios = [
        (
            "exit",
            invocation.Exits(rc=7, detail="boom"),
            lambda: monkeypatch.setattr(subprocess, "run", _run_returns(7, stdout="", stderr="boom")),
        ),
        (
            "timeout",
            invocation.TimesOut(),
            lambda: monkeypatch.setattr(
                subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=30.0))
            ),
        ),
        (
            "not-found",
            invocation.NotFound(),
            lambda: monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError())),
        ),
        (
            "os-error",
            invocation.Fails(exc=OSError("boom-os")),
            lambda: monkeypatch.setattr(subprocess, "run", _run_raises(OSError("boom-os"))),
        ),
    ]
    for failure_kind, step, arm in scenarios:
        fake_logs = []
        fake_backend = invocation.FakeBackend([step])
        fake_outcome = fake_backend.write_session(_spec("worker", log=fake_logs.append, label=""))

        real_logs = []
        arm()
        real_outcome = invocation.CliBackend().write_session(_spec("worker", log=real_logs.append, label=""))

        assert fake_outcome.failure == real_outcome.failure == failure_kind
        assert fake_logs == real_logs, (failure_kind, fake_logs, real_logs)


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


def test_wr1_invoke_claude_signature_and_never_raises(monkeypatch):
    sig = inspect.signature(worker._invoke_claude)
    params = list(sig.parameters.values())
    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert [p.name for p in positional] == ["argv", "prompt", "timeout", "home"]
    assert sig.parameters["label"].kind == inspect.Parameter.KEYWORD_ONLY

    for exc in (FileNotFoundError(), subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1), OSError("x")):
        monkeypatch.setattr(subprocess, "run", _run_raises(exc))
        assert worker._invoke_claude(["claude"], "p", 1.0, Path("/tmp"), label="") is None

    monkeypatch.setattr(subprocess, "run", _run_returns(7, stdout="", stderr="x"))
    assert worker._invoke_claude(["claude"], "p", 1.0, Path("/tmp"), label="") is None


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

    # unavailable leg
    stray.write_text("litter", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    out = miner._invoke_reader(home, "PROMPT")
    assert out is None
    assert stray.exists(), "unavailable: stray sweep ran despite an early return"
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)


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


def test_wr4_outcome_stdout_per_surface(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_returns(0, stdout="STDOUT-TEXT", stderr=""))
    assert invocation.CliBackend().write_session(_spec("worker")).stdout == ""
    assert invocation.CliBackend().write_session(_spec("worker-repair")).stdout == ""
    assert invocation.CliBackend().text_session(_spec("analyst")).stdout == "STDOUT-TEXT"

    monkeypatch.setattr(subprocess, "Popen", _FakePopen(returncode=0, output="MERGED-OUT"))
    assert invocation.CliBackend().write_session(_spec("miner-reader")).stdout == "MERGED-OUT"


def test_wr5_analyst_error_carries_cause_for_not_found_and_timeout(analyst_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError()))
    with pytest.raises(analyst.AnalystError) as exc_info:
        analyst.analyze(analyst_env.home, make_behavior())
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    monkeypatch.setattr(
        subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1))
    )
    with pytest.raises(analyst.AnalystError) as exc_info2:
        analyst.analyze(analyst_env.home, make_behavior())
    assert isinstance(exc_info2.value.__cause__, subprocess.TimeoutExpired)


def test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates(
    analyst_env, monkeypatch, sdk_absent
):
    # -- shipped, byte-identical to master
    monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError()))
    with pytest.raises(analyst.AnalystError) as e1:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e1.value) == "claude CLI not found on PATH"

    monkeypatch.setattr(
        subprocess, "run", _run_raises(subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=120))
    )
    with pytest.raises(analyst.AnalystError) as e2:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e2.value) == "analyst timed out after 120s"

    monkeypatch.setattr(subprocess, "run", _run_returns(7, stdout="OUT", stderr="  ERR TEXT  "))
    with pytest.raises(analyst.AnalystError) as e3:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e3.value) == "analyst exited 7: ERR TEXT"

    # -- new: unavailable, byte literal per W-i
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    with pytest.raises(analyst.AnalystError) as e4:
        analyst.analyze(analyst_env.home, make_behavior())
    assert str(e4.value) == (
        'invocation backend unavailable (the "sdk" invocation backend is not '
        "built yet — install it with:\n"
        "    pip install 'self-learn-cli[sdk]')"
    )
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)

    # -- every one of them is rendered through LOG_TEMPLATES["analyst"]
    # U-sdka `Armor-1`/`A-d`: `_clear_backend_env` above deleted conftest's
    # SELF_LEARN_BACKEND_ANALYST=cli pin, and the analyst's DEFAULT rung is
    # now `sdk` (invocation/contract.py `DEFAULT_BACKEND_FOR_SURFACE`).
    # Restore the pin: the `subprocess.run` patch below is meaningless on
    # any backend but the cli one, so this leg is ABOUT that transport.
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError()))
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
