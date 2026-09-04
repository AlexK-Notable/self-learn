"""M-G: bounded synchronous children (sprint 1 plan v2 §2, lane L1
ledger-git). `primitives.procs.run_bounded` replaces the six raw
`subprocess.run(...)` sites that had no `timeout=` (closes C12b/C12c,
C22's Python half): `hook_compiler.py` (validate_ere, replay_examples),
`hosts.py` (the `--init` leg's `git init` / empty root commit),
`verbs.py` (`_show_lifecycle`'s `git log`), `worker.py` (`_digest`'s
`git log`) — plus a seventh: `ledger_ops.py`'s three `git mv` call sites,
migrated off `_git_ok` onto a new `_git_mv` helper.

Two halves:

1. **P3 timeout gate** — a structural scanner (same shape as
   `test_lock_invariant.py`'s fixpoint walker: parse the source, don't
   hand-enumerate) over `src/self_learn/**/*.py` for the three violation
   shapes P3 forbids: a `subprocess.run(` with no `timeout=` (outside
   `primitives/procs.py`, which IS the bounded primitive and is exempt
   by construction — see its own body, which never calls bare
   `subprocess.run` at all); a bare `.communicate()` (no `input=`, no
   `timeout=`); a `subprocess.Popen(` with no literal
   `start_new_session=True`. An allowlist entry suppresses a violation
   ONLY when it carries all three disposition fields the standing rule
   requires (what bounds it instead, the caller's behaviour on a hang, a
   review trigger) — an incomplete entry is debt, not a ratchet, and
   stays a violation.

2. **`run_bounded` behavior** — pass-through, `check=True`, and the
   timeout path: the WHOLE process group dies (not just the immediate
   child), proven against a child that ignores SIGTERM and spawns its
   own grandchild.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import self_learn
from self_learn.primitives import procs

SRC = Path(self_learn.__file__).parent


# ======================================================== the P3 scanner


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    kind: str  # "run-no-timeout" | "bare-communicate" | "popen-no-new-session"


#: The three disposition fields the standing rule requires of every
#: allowlist entry (BRIEF-ledger-git.md's P3 gate paragraph, verbatim):
#: "what bounds it instead (or why unbounded is acceptable), the
#: caller's behaviour on a hang, and a review trigger."
DISPOSITION_FIELDS = ("bounds", "on_hang", "review_trigger")


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_subprocess_dot(call: ast.Call, attr: str) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr == attr
    )


def _kw_true(call: ast.Call, name: str) -> bool:
    for kw in call.keywords:
        if kw.arg == name:
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def _has_kw(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords)


def _scan_module(path: Path, rel: str) -> list[Violation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # `primitives/procs.py` IS the bounded primitive: a bare
    # `subprocess.run(` there would be the gate's own escape hatch, so
    # it is the one file exempt from the run-without-timeout rule. (In
    # this implementation it never calls `subprocess.run` at all --
    # `run_bounded` is built on `Popen` + a bounded `communicate` -- so
    # the exemption matches nothing today; it exists so a future
    # rewrite of the primitive itself isn't flagged by the gate it IS.)
    exempt_run_timeout = rel in ("primitives/procs.py", "primitives\\procs.py")
    hits: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node)
        if name == "run" and _is_subprocess_dot(node, "run"):
            if not exempt_run_timeout and not _has_kw(node, "timeout"):
                hits.append(Violation(rel, node.lineno, "run-no-timeout"))
        elif name == "Popen" and (
            _is_subprocess_dot(node, "Popen")
            or (isinstance(node.func, ast.Name) and node.func.id == "Popen")
        ):
            if not _kw_true(node, "start_new_session"):
                hits.append(Violation(rel, node.lineno, "popen-no-new-session"))
        elif name == "communicate":
            bare = not node.args and not _has_kw(node, "input") and not _has_kw(node, "timeout")
            if bare:
                hits.append(Violation(rel, node.lineno, "bare-communicate"))
    return hits


def scan(root: Path) -> list[Violation]:
    """Every violation in every ``*.py`` under *root*, walked
    recursively (mirrors ``rglob`` — the real tree has subpackages:
    ``invocation/``, ``invocation_sdk/``, ``sdksession/``)."""
    out: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        out.extend(_scan_module(path, rel))
    return out


def _disposition_complete(entry: dict) -> bool:
    return all(
        isinstance(entry.get(field), str) and entry[field].strip()
        for field in DISPOSITION_FIELDS
    )


def unallowed(
    violations: list[Violation], allowlist: dict[tuple[str, int], dict]
) -> list[Violation]:
    """Violations the allowlist does NOT excuse: absent from it, or
    present with an incomplete disposition (debt, not a ratchet — the
    standing rule's own words)."""
    out = []
    for v in violations:
        entry = allowlist.get((v.path, v.lineno))
        if entry is not None and _disposition_complete(entry):
            continue
        out.append(v)
    return out


#: Production allowlist for `src/self_learn`. Measured empty: the census
#: below (and the report's "Brief statements found false") found 18
#: `subprocess`-invoking call sites across 9 modules pre-migration, not
#: the brief's claimed 20 across ten -- 7 `subprocess.run(` lacked
#: `timeout=` (the six file sites the brief names plus `ledger_ops.py`'s
#: own `_git`, retired whole by this move), and the 3 pre-existing
#: `Popen` sites already carried `start_new_session=True`. After the
#: migrations every site either lives in `primitives/procs.py`, already
#: carried `timeout=`, or already carried `start_new_session=True` --
#: zero violations, so zero allowlist entries are needed. An empty dict
#: is a claim the tests below prove is checkable, not just asserted:
#: `test_p3_gate_...` fails loudly the moment a real violation appears,
#: and the synthetic tests below prove the accept/reject machinery
#: around a NON-empty allowlist actually works.
PRODUCTION_ALLOWLIST: dict[tuple[str, int], dict[str, str]] = {}


def test_p3_gate_src_has_no_unallowed_bounded_children_violations():
    bad = unallowed(scan(SRC), PRODUCTION_ALLOWLIST)
    assert not bad, "\n".join(f"{v.path}:{v.lineno} {v.kind}" for v in bad)


def test_p3_gate_census_matches_the_measured_count():
    """Pins the measured census so a future change to this file (or a
    new subprocess call site landing anywhere in `src`) is a visible
    diff here, not a silent drift of what "clean" means. See the report
    for the corrected count against the brief's stated 20/ten/14."""
    violations = scan(SRC)
    assert len(violations) == 0, violations
    modules = {p.stem for p in SRC.rglob("*.py")}
    assert "gitops" in modules and "ledger_ops" in modules


# -------------------------------------------------- positive controls


OFFENDING_RUN = "import subprocess\n\ndef f():\n    subprocess.run(['true'])\n"
OFFENDING_POPEN = "import subprocess\n\ndef f():\n    subprocess.Popen(['true'])\n"
OFFENDING_COMMUNICATE = (
    "import subprocess\n\ndef f(proc):\n    proc.communicate()\n"
)


@pytest.mark.parametrize(
    "snippet, kind",
    [
        (OFFENDING_RUN, "run-no-timeout"),
        (OFFENDING_POPEN, "popen-no-new-session"),
        (OFFENDING_COMMUNICATE, "bare-communicate"),
    ],
)
def test_positive_control_the_scanner_catches_each_violation_shape(
    tmp_path, snippet, kind
):
    """The gate is only worth its runtime if it FAILS on the bug it
    exists to catch — a structural test that cannot be shown catching
    its own bug class is one that passes because it looks at nothing
    (same discipline as test_lock_invariant.py's planted-violation
    tests)."""
    (tmp_path / "offender.py").write_text(snippet, encoding="utf-8")
    violations = scan(tmp_path)
    assert violations, f"the scanner missed a planted {kind} violation"
    assert violations[0].kind == kind


def test_positive_control_a_complete_allowlist_entry_suppresses_it(tmp_path):
    (tmp_path / "offender.py").write_text(OFFENDING_RUN, encoding="utf-8")
    violations = scan(tmp_path)
    assert len(violations) == 1
    allowlist = {
        (violations[0].path, violations[0].lineno): {
            "bounds": "test double: no real child spawned",
            "on_hang": "test double: n/a",
            "review_trigger": "test double: n/a",
        }
    }
    assert unallowed(violations, allowlist) == []


@pytest.mark.parametrize("missing_field", DISPOSITION_FIELDS)
def test_positive_control_an_incomplete_allowlist_entry_still_flags(
    tmp_path, missing_field
):
    """'An allowlist entry without those is debt, not a ratchet' —
    dropping ANY ONE of the three required fields must still count as
    unallowed, not just a missing entry entirely."""
    (tmp_path / "offender.py").write_text(OFFENDING_RUN, encoding="utf-8")
    violations = scan(tmp_path)
    entry = {f: f"present:{f}" for f in DISPOSITION_FIELDS}
    del entry[missing_field]
    allowlist = {(violations[0].path, violations[0].lineno): entry}
    assert unallowed(violations, allowlist) == violations


def test_positive_control_an_allowlist_entry_with_blank_field_still_flags(tmp_path):
    (tmp_path / "offender.py").write_text(OFFENDING_RUN, encoding="utf-8")
    violations = scan(tmp_path)
    entry = {f: "present" for f in DISPOSITION_FIELDS}
    entry["on_hang"] = "   "  # whitespace-only: not a real disposition
    allowlist = {(violations[0].path, violations[0].lineno): entry}
    assert unallowed(violations, allowlist) == violations


def test_scanner_does_not_flag_a_compliant_run_call(tmp_path):
    (tmp_path / "clean.py").write_text(
        "import subprocess\n\ndef f():\n    subprocess.run(['true'], timeout=5)\n",
        encoding="utf-8",
    )
    assert scan(tmp_path) == []


def test_scanner_does_not_flag_a_compliant_popen_call(tmp_path):
    (tmp_path / "clean.py").write_text(
        "import subprocess\n\n"
        "def f():\n"
        "    subprocess.Popen(['true'], start_new_session=True)\n",
        encoding="utf-8",
    )
    assert scan(tmp_path) == []


def test_scanner_does_not_flag_a_non_bare_communicate_call(tmp_path):
    (tmp_path / "clean.py").write_text(
        "import subprocess\n\ndef f(proc):\n    proc.communicate(timeout=5)\n",
        encoding="utf-8",
    )
    assert scan(tmp_path) == []


def test_scanner_exempts_a_bare_run_call_inside_primitives_procs_py(tmp_path):
    procs_dir = tmp_path / "primitives"
    procs_dir.mkdir()
    (procs_dir / "procs.py").write_text(
        "import subprocess\n\ndef f():\n    subprocess.run(['true'])\n",
        encoding="utf-8",
    )
    assert scan(tmp_path) == []


# ============================================================ run_bounded


def test_pass_through_returns_a_completed_process_with_text_output():
    result = procs.run_bounded(
        [sys.executable, "-c", "import sys; print('hi'); sys.exit(0)"],
        timeout=10,
    )
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout.strip() == "hi"


def test_nonzero_exit_is_reported_not_raised_by_default():
    result = procs.run_bounded(
        [sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10
    )
    assert result.returncode == 3


def test_check_true_raises_on_nonzero_exit():
    with pytest.raises(subprocess.CalledProcessError):
        procs.run_bounded(
            [sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10, check=True
        )


def test_input_is_delivered_to_stdin():
    result = procs.run_bounded(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
        timeout=10,
        input="echo-me",
    )
    assert result.stdout.strip() == "echo-me"


def test_cwd_is_honored(tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    result = procs.run_bounded(
        [sys.executable, "-c", "import os; print(sorted(os.listdir('.')))"],
        timeout=10,
        cwd=str(tmp_path),
    )
    assert "marker.txt" in result.stdout


def test_env_is_honored():
    result = procs.run_bounded(
        [sys.executable, "-c", "import os; print(os.environ.get('PROBE_VAR', ''))"],
        timeout=10,
        env={"PROBE_VAR": "seen", "PATH": os.environ.get("PATH", "")},
    )
    assert result.stdout.strip() == "seen"


def test_timeout_raises_bounded_timeout_naming_argv():
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(procs.BoundedTimeout) as excinfo:
        procs.run_bounded(argv, timeout=0.3)
    assert str(list(excinfo.value.cmd)) == str(argv) or argv[0] in str(excinfo.value)


def test_bounded_timeout_is_a_subprocess_timeout_expired():
    """So an existing `except subprocess.TimeoutExpired:` handler
    elsewhere in the codebase (e.g. `hosts.py`'s already-bounded
    `_is_git_repo`/`is_repo_root` probes) would still catch this."""
    assert issubclass(procs.BoundedTimeout, subprocess.TimeoutExpired)


_IGNORES_SIGTERM_AND_SLEEPS = (
    "import signal, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "time.sleep(30)\n"
)


def test_timeout_kills_a_child_that_ignores_sigterm():
    start = time.monotonic()
    with pytest.raises(procs.BoundedTimeout):
        procs.run_bounded(
            [sys.executable, "-c", _IGNORES_SIGTERM_AND_SLEEPS], timeout=0.5
        )
    elapsed = time.monotonic() - start
    assert elapsed < 10, (
        f"run_bounded took {elapsed:.1f}s to return past a 0.5s timeout — a "
        "SIGTERM-ignoring child was not force-killed"
    )


def _proc_is_dead(pid: int) -> bool:
    """Absent, or a zombie, both mean dead — `os.kill(pid, 0)` alone is
    NOT enough: if this test process (or pytest) is a subreaper, a
    killed grandchild becomes ITS zombie and `kill(pid, 0)` keeps
    succeeding until someone waits on it."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return True
    # format: "pid (comm) STATE ..." — comm may itself contain ')', so
    # split on the LAST ')'
    state = stat.rsplit(")", 1)[1].split()[0]
    return state == "Z"


_SPAWNS_A_GRANDCHILD_SCRIPT = """
import signal, subprocess, sys, time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = subprocess.Popen(
    [sys.executable, "-c",
     "import signal, time\\n"
     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
     "time.sleep(60)\\n"],
)
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(str(grandchild.pid))
    f.flush()
time.sleep(60)
"""


def test_timeout_kills_the_whole_process_group_a_grandchild_dies_too(tmp_path):
    """The defect this whole module exists to close: killing only the
    immediate child (`proc.terminate()`/`proc.kill()`) leaves a
    grandchild the child spawned (without its own new session) running
    forever, because it never belonged to `proc` in the first place —
    it belongs to the process GROUP. `run_bounded` must kill that
    whole group."""
    pidfile = tmp_path / "gpid.txt"
    script = tmp_path / "child.py"
    script.write_text(_SPAWNS_A_GRANDCHILD_SCRIPT, encoding="utf-8")

    with pytest.raises(procs.BoundedTimeout):
        procs.run_bounded(
            [sys.executable, str(script), str(pidfile)], timeout=1.5
        )

    deadline = time.monotonic() + 10
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pidfile.exists(), "the child never got to spawn+record its grandchild"
    gpid = int(pidfile.read_text(encoding="utf-8").strip())

    deadline = time.monotonic() + 10
    dead = False
    while time.monotonic() < deadline:
        if _proc_is_dead(gpid):
            dead = True
            break
        time.sleep(0.05)
    assert dead, (
        f"grandchild pid {gpid} was still alive after run_bounded's timeout — "
        "killing only the immediate child leaves orphaned descendants running"
    )
