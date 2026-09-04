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
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import self_learn
from self_learn import hook_compiler, hosts, ledger_ops, verbs, worker
from self_learn.primitives import procs
from support import init_repo

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
        if name == "run" and (
            _is_subprocess_dot(node, "run")
            or (isinstance(node.func, ast.Name) and node.func.id == "run")
        ):
            # M-G fold r1 MINOR 3: mirrors the Popen arm below exactly.
            # `subprocess.run(` alone was asymmetric with the Popen check
            # — bypassable by `from subprocess import run; run(...)`, an
            # import style the scanner would silently miss while still
            # catching the same bypass on Popen.
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


#: Production allowlist for `src/self_learn`. Measured empty: the
#: PRE-migration census (report's "Brief statements found false") found
#: 18 `subprocess`-invoking call sites across 9 modules, not the brief's
#: claimed 20 across ten -- 7 `subprocess.run(` lacked `timeout=` (the
#: six file sites the brief names plus `ledger_ops.py`'s own `_git`,
#: retired whole by this move), and the 3 pre-existing `Popen` sites
#: already carried `start_new_session=True`. After the migrations every
#: site either lives in `primitives/procs.py`, already carried
#: `timeout=`, or already carried `start_new_session=True` -- zero
#: violations, so zero allowlist entries are needed. An empty dict is a
#: claim the tests below prove is checkable, not just asserted:
#: `test_p3_gate_...` fails loudly the moment a real violation appears,
#: and the synthetic tests below prove the accept/reject machinery
#: around a NON-empty allowlist actually works.
PRODUCTION_ALLOWLIST: dict[tuple[str, int], dict[str, str]] = {}


def test_p3_gate_src_has_no_unallowed_bounded_children_violations():
    bad = unallowed(scan(SRC), PRODUCTION_ALLOWLIST)
    assert not bad, "\n".join(f"{v.path}:{v.lineno} {v.kind}" for v in bad)


# ---------------------------------------------------------- the census


@dataclass(frozen=True)
class Site:
    """One subprocess-invoking call site, regardless of compliance --
    the census counts ALL of `run`/`Popen`/`.communicate()`, not just
    violations (which is what `test_p3_gate_...` above already pins at
    zero). Two counts answer two different questions: violations answers
    "is anything unbounded"; the census answers "did the SHAPE of
    src's subprocess usage change at all" -- a brand-new, perfectly
    bounded call site changes the second without moving the first, and a
    test that only watches violations cannot see it land."""

    path: str
    lineno: int
    kind: str  # "run" | "Popen" | "communicate"


def _census_module(path: Path, rel: str) -> list[Site]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node)
        if name == "run" and (
            _is_subprocess_dot(node, "run")
            or (isinstance(node.func, ast.Name) and node.func.id == "run")
        ):
            hits.append(Site(rel, node.lineno, "run"))
        elif name == "Popen" and (
            _is_subprocess_dot(node, "Popen")
            or (isinstance(node.func, ast.Name) and node.func.id == "Popen")
        ):
            hits.append(Site(rel, node.lineno, "Popen"))
        elif name == "communicate":
            hits.append(Site(rel, node.lineno, "communicate"))
    return hits


def census(root: Path) -> list[Site]:
    """Every `run`/`Popen`/`.communicate()` call site under *root*,
    compliant or not (mirrors `scan`'s traversal and callee-matching
    exactly, minus the compliance filter)."""
    out: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        out.extend(_census_module(path, str(path.relative_to(root))))
    return out


#: M-G fold r1 MAJOR 1: pins what the gate's own independent AST count
#: measured at HEAD (post-migration) -- 15 sites across 7 modules. This
#: is NOT the same number as the pre-migration 18/9 in
#: `PRODUCTION_ALLOWLIST`'s comment above (that census answers "how much
#: was unbounded before this lane started"; this one answers "how much
#: subprocess-invoking surface does `src` have RIGHT NOW, compliant
#: sites included"). A single new call site anywhere in `src` --
#: bounded or not -- changes this number and reddens the test below,
#: forcing a human to look at it and consciously re-pin; the positive
#: control after it proves the census function actually is that
#: sensitive, not just asserted to be.
#: POSIX form only — `_census_module`'s `rel` (like `_scan_module`'s own
#: `rel`, which is why `exempt_run_timeout` above checks BOTH separator
#: forms) is `str(path.relative_to(root))`, native-separated. The
#: comparison below normalizes a backslash-separated hit back to POSIX
#: first, so this frozenset never needs a second, Windows-only literal.
MEASURED_CENSUS_MODULES = frozenset(
    {
        "gitops.py",
        "hosts.py",
        "ledger.py",
        "miner.py",
        "primitives/procs.py",
        "provider.py",
        "worker.py",
    }
)
MEASURED_CENSUS_SITE_COUNT = 15


def test_p3_gate_census_matches_the_measured_count():
    """Pins the TOTAL subprocess-invoking site count (run + Popen +
    `.communicate()`, compliant sites included) so a future call site --
    even a correctly-bounded one -- is a visible diff here, not a silent
    drift of what "measured" means. `test_p3_gate_...violations` above
    already covers "is anything unbounded" at zero; this covers "did the
    census move at all"."""
    sites = census(SRC)
    assert len(sites) == MEASURED_CENSUS_SITE_COUNT, sites
    modules = {s.path.replace("\\", "/") for s in sites}  # no POSIX-only literal
    assert modules == MEASURED_CENSUS_MODULES, sorted(modules)


def test_positive_control_census_count_changes_when_a_new_site_lands(tmp_path):
    """The census is only worth pinning if adding a site actually moves
    it -- proven directly, independent of `src`'s own current state."""
    (tmp_path / "a.py").write_text(
        "import subprocess\n\ndef f():\n    subprocess.run(['true'], timeout=5)\n",
        encoding="utf-8",
    )
    before = len(census(tmp_path))
    assert before == 1
    (tmp_path / "b.py").write_text(
        "import subprocess\n\ndef g():\n    subprocess.run(['true'], timeout=5)\n",
        encoding="utf-8",
    )
    after = len(census(tmp_path))
    assert after == before + 1, (
        "a brand-new, perfectly-bounded call site did not move the census "
        "count -- the census is blind to exactly what it exists to see"
    )


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


def test_positive_control_catches_run_imported_by_name(tmp_path):
    """M-G fold r1 MINOR 3: `from subprocess import run; run(...)` used to
    be a bypass — the Popen arm already matched a bare `Popen(...)` name
    call, but the run arm required the `subprocess.run(` attribute form
    literally, so this exact import style evaded detection entirely."""
    (tmp_path / "offender.py").write_text(
        "from subprocess import run\n\ndef f():\n    run(['true'])\n",
        encoding="utf-8",
    )
    violations = scan(tmp_path)
    assert violations and violations[0].kind == "run-no-timeout", violations


def test_scanner_does_not_flag_a_bounded_run_imported_by_name(tmp_path):
    (tmp_path / "clean.py").write_text(
        "from subprocess import run\n\ndef f():\n    run(['true'], timeout=5)\n",
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
    """M-G fold r1 NIT 1: exact text, not a disjunctive 'either shape is
    fine' assertion — pins the precise message a human reads on a real
    timeout, and would catch a change to either `argv`'s own value or how
    it gets rendered."""
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(procs.BoundedTimeout) as excinfo:
        procs.run_bounded(argv, timeout=0.3)
    assert excinfo.value.cmd == argv
    assert str(excinfo.value) == f"Command '{argv}' timed out after 0.3 seconds"


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


# ============================================ M-G fold r1 NIT 2 / MINOR 2


def test_validate_ere_rejects_a_genuinely_broken_pattern():
    """M-G fold r1 NIT 2: `validate_ere`'s `>= 2` branch (grep -E itself
    rejects the pattern, as opposed to a plain "no match", exit 1) had no
    test at all before this fold. `[` is an unterminated bracket
    expression — grep -E always rejects it, exit 2, on every grep
    implementation on this host."""
    problem = hook_compiler.validate_ere("[")
    assert problem is not None
    assert problem != ""


def test_validate_ere_accepts_a_usable_pattern():
    assert hook_compiler.validate_ere("abc") is None


#: M-G fold r1 MINOR 2: seven new `except procs.BoundedTimeout:` branches
#: landed with this move and none had a test driving them — this table
#: drives each one and asserts its DOCUMENTED fallback (the behavior
#: named in that site's own comment/docstring in the production code).
#: Every case patches the SAME shared `primitives.procs.run_bounded` --
#: whether a call site imports it at module level (`ledger_ops.py`,
#: M-G fold r1 MINOR 1) or locally inside the function (`hosts.py`,
#: `verbs.py`, `worker.py`, `hook_compiler.py`), `from .primitives import
#: procs` always binds to the ONE cached module object, so patching
#: `procs.run_bounded` here reaches every call site regardless of import
#: style or timing.
def _always_bounded_timeout(argv, *, timeout, **kwargs):
    raise procs.BoundedTimeout(list(argv), timeout)


def _bounded_timeout_only_for(needle: str):
    """Real `run_bounded` for everything except an argv containing
    *needle*, which times out — lets a two-call sequence (git init THEN
    commit) have its FIRST call really succeed and its SECOND time out,
    isolating that one branch."""
    real = procs.run_bounded

    def fake(argv, *, timeout, **kwargs):
        if needle in argv:
            raise procs.BoundedTimeout(list(argv), timeout)
        return real(argv, timeout=timeout, **kwargs)

    return fake


def _case_validate_ere(monkeypatch, tmp_path):
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    result = hook_compiler.validate_ere("a")
    assert result is not None and "did not finish" in result, result


def _case_replay_examples(monkeypatch, tmp_path):
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    script = tmp_path / "guard.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    mismatches = hook_compiler.replay_examples(script, {"allow": [{"tool_input": {}}]})
    assert mismatches and "did not finish" in mismatches[0], mismatches


def _case_hosts_init_git_init_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    target = tmp_path / "host_init_case"
    target.mkdir()
    with pytest.raises(hosts.HostsError) as excinfo:
        hosts._init_for_registration(target)
    assert "did not finish" in str(excinfo.value)


def _case_hosts_init_git_commit_timeout(monkeypatch, tmp_path):
    # git init runs for REAL (needs an actual repo for commit to fail
    # against); only the commit call times out.
    monkeypatch.setattr(procs, "run_bounded", _bounded_timeout_only_for("commit"))
    target = tmp_path / "host_commit_case"
    target.mkdir()
    with pytest.raises(hosts.HostsError) as excinfo:
        hosts._init_for_registration(target)
    assert "did not finish" in str(excinfo.value)


def _case_show_lifecycle(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    result = verbs._show_lifecycle(repo, "lrn-00000001")
    assert result == []


def _case_worker_digest(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    result = worker._digest(repo)
    assert result == "(no rejected-proposal history available)"


def _case_ledger_ops_git_mv(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    monkeypatch.setattr(procs, "run_bounded", _always_bounded_timeout)
    with pytest.raises(ledger_ops.LedgerOpsError) as excinfo:
        ledger_ops._git_mv(repo, repo / "a.txt", repo / "b.txt")
    assert "did not finish" in str(excinfo.value)


_BOUNDED_TIMEOUT_CASES = [
    pytest.param(_case_validate_ere, id="hook_compiler.validate_ere"),
    pytest.param(_case_replay_examples, id="hook_compiler.replay_examples"),
    pytest.param(_case_hosts_init_git_init_timeout, id="hosts._init_for_registration:git-init"),
    pytest.param(_case_hosts_init_git_commit_timeout, id="hosts._init_for_registration:git-commit"),
    pytest.param(_case_show_lifecycle, id="verbs._show_lifecycle"),
    pytest.param(_case_worker_digest, id="worker._digest"),
    pytest.param(_case_ledger_ops_git_mv, id="ledger_ops._git_mv"),
]


@pytest.mark.parametrize("case", _BOUNDED_TIMEOUT_CASES)
def test_bounded_timeout_fallback_at_each_migrated_call_site(case, monkeypatch, tmp_path):
    case(monkeypatch, tmp_path)


# ================================================== M-G fold r1 MAJOR 2


def test_lock_invariant_walker_flags_a_planted_unlocked_git_mv(tmp_path):
    """`test_lock_invariant.py`'s `_git_primitive` was blind to `git mv`
    once `ledger_ops._git_mv` replaced `_git_ok(repo, "mv", ...)` — its
    callee has no constant subcommand argument (the OLD shape
    `_git_ok(repo, "mv", ...)` matched on `args[1] == "mv"`; `_git_mv`'s
    args are `(home, src, dest)`, no string literal anywhere). Fixed
    there with the minimal, gate-authorized edit: recognize the callee
    NAME `_git_mv` directly as `git mv`, nothing else in that file
    touched (another lane widened a different part of the same walker).

    Proven HERE, not by adding to that file's own diff: plant an
    unlocked call to the (module-private, name-only) `_git_mv` primitive
    into a COPY of `ledger_ops.py` — same "plant into a COPY, assert the
    walker flags it" discipline `test_lock_invariant.py`'s OWN
    `test_it_catches_a_planted_violation` uses — and assert the fixpoint
    flags it. A `_git_mv`-named function whose only body is a call to
    something that isn't `ledger_ops._git_mv` would NOT trip this
    (`_git_primitive` matches by literal callee name, not by target
    resolution), so this is a real exercise of the fix, not a tautology."""
    import shutil

    import test_lock_invariant as tli

    sandbox = tmp_path / "src" / "self_learn"
    shutil.copytree(tli.SRC, sandbox)
    planted = (
        "\n\ndef _planted_git_mv_violation(home, src, dest):\n"
        "    _git_mv(home, src, dest)\n"
    )
    (sandbox / "ledger_ops.py").write_text(
        (sandbox / "ledger_ops.py").read_text(encoding="utf-8") + planted,
        encoding="utf-8",
    )
    requires = tli._Analysis(sandbox).requires_lock()
    assert "ledger_ops._planted_git_mv_violation" in requires, (
        "the walker did not flag a planted unlocked _git_mv call — it is "
        "blind to the exact primitive it was just taught to recognize"
    )
