"""U-corrob — the tool_events/denials consumer (`src/self_learn/corroborate.py`).

Spec: `docs/specs/self-learn/drafts/u-corrob-tool-events-consumer-spec.md`
(r5, 37 criteria, T1). Each test's docstring cites the criterion id it
discharges. `DEN3` (the analyst/`teach.py` leg) IS built (coordinator
ruling, 2026-08-28: "the cap ... is armor BOOKKEEPING, not a design
constraint"): `test_u_sdka.py::test_hy5_numstat_bounds_hold`'s
`analyst.py` row was re-pinned to this unit's measured single-ref
numstat against `442385d`, `(4, 18)` -> `(22, 20)`, dated and justified
in place, the same sanctioned motion `U-papercuts`/`U-servehermetic`/
`U-kl4` used tonight for their own hy5 rows. `_route_now` passes
`charter_denials=` UNCONDITIONALLY (`FW-107`'s exact shape, no
signature inspection) — a second, unrelated armor collision this
forced (`test_route_cli.py`'s `fake_analyze` stand-in, which did not
accept the new kwarg, is itself pinned by `test_u_fake.py`'s `DS1`,
which is in turn whole-file-hashed by `test_worker_contract.py`'s
`_ARMOR_SHAS`) was resolved the SAME sanctioned way, not by bending
production code to a test double: `fake_analyze` was edited to accept
`charter_denials=None`, and both armor layers it collides with were
re-pinned to match, each with a dated justification in place. See
`test_scrub3_no_new_or_edited_test_reads_an_event_log_back`'s docstring
for the full three-file account and `S-53`/`FW-131` for the recorded
history.

Most PIN/UN/SCRUB3/EV4/BND4/POL2 criteria are discharged by EXISTING
pinned tests in `test_worker_contract.py`/`test_invocation_sdk.py`/
`test_u_engine.py`/`test_u_sdka.py` staying green and byte-unedited (this
unit's own §4.1 pin census, re-run and pasted in the build report) —
those are not duplicated here. This file adds NEW tests only where a
criterion needs a NEW discriminator: the corroborator's own logic
(`corroborate.py`), the new worker/miner log lines, and the docs.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

import pytest

from self_learn import analyst, cli, invocation, miner, worker
from self_learn import corroborate
from self_learn.corroborate import RunEvidence
from self_learn.invocation_sdk import SdkOutcome
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.sdksession import toolpaths

from support import make_behavior

from test_worker import Env, sdk_fake_worker, env, seed_pending, shim_writes, _proposal_yaml  # noqa: F401
from test_reader_contract import reader_leg, BACKEND_VAR, FAKE_CLI, _shadow_claude  # noqa: F401
from test_route_cli import TEACH_ARGS, _skill_gates_yaml  # noqa: F401

_REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)
_SRC = Path(worker.__file__).resolve().parent
_BASE_SHA = "104f6db"  # this unit's own base commit (worktree u-corrob)


def _single_ref_diff(relpath: str) -> str:
    return subprocess.run(
        ["git", "diff", _BASE_SHA, "--", relpath],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout


# ===================================================================== #
# COR1 -- module shape and import bound
# ===================================================================== #


def test_cor1_exports_exactly_runevidence():
    """COR1 (code gate r1, N-1, option (a)): `corroborate.py` exports
    exactly `RunEvidence`, `NO_EVIDENCE`, `MISMATCH` -- `__all__`
    corrected to name all three, since `NO_EVIDENCE`/`MISMATCH` are
    genuinely part of the public contract (imported by name from both
    `worker.py` and `miner.py`); `["RunEvidence"]` alone was not the
    truth."""
    assert corroborate.__all__ == ["RunEvidence", "NO_EVIDENCE", "MISMATCH"]


def test_cor1_import_set_is_bounded_to_stdlib_and_the_two_named_modules():
    """COR1: import set is stdlib + `.invocation_sdk.charter` +
    `.sdksession.toolpaths` only -- no `.worker`, `.miner`,
    `.invocation_sdk.events`, or `self_learn_ui`. AST sweep, LIB1's shape."""
    path = _SRC / "corroborate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed_relative = {"invocation_sdk.charter", "sdksession.toolpaths"}
    allowed_absolute = {"__future__", "pathlib", "typing"}
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                violations.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module not in allowed_absolute:
                    violations.append(("stdlib", node.module))
            elif node.level == 1:
                if node.module is None:
                    violations.extend(("relative-bare", a.name) for a in node.names)
                elif node.module not in allowed_relative:
                    violations.append(("relative", node.module))
            else:
                violations.append(("bad-level", node.level, node.module))
    assert violations == [], violations


def test_cor1_M1_mutation_upward_import_is_rejected_by_the_same_walker():
    """`M1`'s shape, run against a scratch copy (never the worktree): an
    `from . import worker` line in `corroborate.py` must be flagged by
    the same AST walker `test_cor1_import_set_is_bounded...` uses --
    proves that test is a real discriminator, not vacuously true."""
    src = (_SRC / "corroborate.py").read_text(encoding="utf-8")
    mutated = src.replace(
        "from .invocation_sdk.charter import W",
        "from .invocation_sdk.charter import W\nfrom . import worker",
        1,
    )
    assert mutated != src
    tree = ast.parse(mutated, filename="corroborate.py")
    allowed_relative = {"invocation_sdk.charter", "sdksession.toolpaths"}
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:
                violations.extend(a.name for a in node.names)
            elif node.module not in allowed_relative:
                violations.append(node.module)
    assert violations == ["worker"], violations


def test_m2_fresh_interpreter_import_does_not_circular_import():
    """Code gate r1 M-2 (real defect, fixed at the root): `uv run python
    -c "import self_learn.corroborate"` used to raise `ImportError:
    cannot import name 'MISMATCH' from partially initialized module`.
    The cycle: `corroborate.py`'s `from .invocation_sdk.charter import
    W` -> `invocation_sdk/__init__.py` -> `backend.py`'s `from .. import
    provider, worker` -> `worker.py`'s own top-level `from .corroborate
    import MISMATCH, NO_EVIDENCE, RunEvidence`, reached while
    `corroborate` is still mid-exec. Every SHIPPED entry path imports
    `worker` (or `miner`) first, so this was invisible to the whole
    suite -- by the time any test imports `corroborate`, `sys.modules`
    is already warm and the cycle never fires again in that process.
    A FRESH interpreter is the only thing that can see it."""
    result = subprocess.run(
        [sys.executable, "-c", "import self_learn.corroborate; print('M2-OK')"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "M2-OK" in result.stdout, (result.stdout, result.stderr)


def test_m2_mutation_constants_below_imports_reintroduces_the_cycle(tmp_path):
    """M-2's own mutation: move `NO_EVIDENCE`/`MISMATCH` back BELOW the
    two relative imports (the shape the gate actually caught) -- the
    fresh-interpreter test above must go RED.

    U-xdist root fix (2026-08-28, scout classification "(f)", a NEW
    worker-unsafety class): the ORIGINAL version of this test wrote the
    mutated source directly into the LIVE, shared `src/self_learn/
    corroborate.py` and restored it in a `finally` block -- safe only
    under strict serial test ordering. Under pytest-xdist a sibling
    worker running any of the 12 OTHER fresh-interpreter-subprocess
    tests in this suite (this build's own report tables all 13, file
    and line) could land on that file during the write -> spawn ->
    restore window and see a spurious circular-import failure that has
    nothing to do with its own test -- reproduced once directly in the
    scout's own sampling.

    Fixed at the root, not papered over with a lock: the mutation is
    built into a PRIVATE copy of the WHOLE `self_learn` package under
    `tmp_path`, never the live tree. A lone-file copy of `corroborate.py`
    would not reproduce the cycle -- it runs through `worker.py` ->
    `invocation_sdk/__init__.py` -> `backend.py` -> back into
    `corroborate.py` -- so the copy has to be the whole package. A
    fresh interpreter given `PYTHONPATH` pointed at the copy's PARENT
    shadows the editable-installed `src/self_learn` for that ONE
    subprocess only (the same shadow-via-`PYTHONPATH` mechanism
    `test_provider.py`/`test_regime_fixes.py` already use elsewhere in
    this suite for the identical reason: a fresh interpreter that
    resolves `self_learn` to a chosen tree, not whatever is editable-
    installed). The mutation criterion still has to discriminate, so it
    is run BOTH ways against the SAME copy: RED with the mutation
    applied, then GREEN once the copy is restored to the unmutated
    bytes (proves the RED result came from the mutation, not from the
    shadow mechanism itself) -- and the LIVE file's sha256 is asserted
    unchanged before either subprocess ever runs and again after both
    finish, since this test no longer writes to it at all."""
    import hashlib
    import os
    import shutil

    live_target = _SRC / "corroborate.py"
    original = live_target.read_text(encoding="utf-8")
    original_sha = hashlib.sha256(original.encode()).hexdigest()

    anchor_block = (
        "# code gate r1 N-1: `__all__` now names all three public symbols --\n"
        "# `NO_EVIDENCE`/`MISMATCH` are genuinely part of the public contract\n"
        "# (imported by name from both `worker.py` and `miner.py`), so\n"
        '# `["RunEvidence"]` alone was not the truth.\n'
        '__all__ = ["RunEvidence", "NO_EVIDENCE", "MISMATCH"]\n'
        "\n"
        "#: The two verdict tags `RunEvidence.verdict` can return, alongside\n"
        '#: `None` ("say nothing"). A caller wires each tag to its own\n'
        "#: surface-specific wording (`{fs} file(s) on disk` on the worker,\n"
        "#: `{fs} artifact(s) in the spool` on the reader) -- this module spells\n"
        "#: neither noun, only the fact that decides between them.\n"
        'NO_EVIDENCE = "no-evidence"\n'
        'MISMATCH = "mismatch"\n'
        "\n"
        "\n"
        "class RunEvidence:"
    )
    assert original.count(anchor_block) == 1, "anchor not found -- has the shape moved?"
    assert original_sha == hashlib.sha256(live_target.read_text(encoding="utf-8").encode()).hexdigest(), (
        "PRE-CONDITION: the live file must be unread-back-unchanged before either subprocess runs"
    )

    import_pair = (
        "from .invocation_sdk.charter import W\n"
        "from .sdksession.toolpaths import extract_target_path\n"
    )
    # Splice the two relative imports back in BEFORE the constants and
    # the class (the pre-gate-fix, broken ordering), and drop the
    # existing post-class copy so the mutated file carries exactly one
    # copy of each import line.
    mutated = original.replace(anchor_block, import_pair + "\n" + anchor_block, 1)
    assert mutated.count(import_pair) == 2, "expected the pre- and post-class copies"
    idx = mutated.rindex(import_pair)
    mutated = mutated[:idx] + mutated[idx + len(import_pair):]
    assert mutated != original

    # A PRIVATE copy of the WHOLE package, never the live tree -- see
    # this test's own docstring for why a lone-file copy is not enough.
    shadow_root = tmp_path / "shadow_src"
    shadow_pkg = shadow_root / "self_learn"
    shutil.copytree(_SRC, shadow_pkg, ignore=shutil.ignore_patterns("__pycache__"))
    shadow_corrob = shadow_pkg / "corroborate.py"
    assert shadow_corrob.read_text(encoding="utf-8") == original

    child_env = dict(os.environ, PYTHONPATH=str(shadow_root))

    # RED: the mutation, applied to the SHADOW copy only.
    shadow_corrob.write_text(mutated, encoding="utf-8")
    result_red = subprocess.run(
        [sys.executable, "-c", "import self_learn.corroborate; print('M2-OK')"],
        capture_output=True, text=True, timeout=30, env=child_env,
    )
    assert result_red.returncode != 0, (
        "M-2 mutation stayed GREEN -- the circular import did not reproduce\n"
        f"{result_red.stdout}\n{result_red.stderr}"
    )
    assert "circular import" in result_red.stderr or "partially initialized" in result_red.stderr, (
        result_red.stderr
    )

    # GREEN control: the SAME shadow copy, restored to the unmutated
    # bytes -- must import clean, proving the RED result above is the
    # mutation's own doing, not an artifact of the shadow mechanism.
    shadow_corrob.write_text(original, encoding="utf-8")
    result_green = subprocess.run(
        [sys.executable, "-c", "import self_learn.corroborate; print('M2-OK')"],
        capture_output=True, text=True, timeout=30, env=child_env,
    )
    assert result_green.returncode == 0, (result_green.stdout, result_green.stderr)
    assert "M2-OK" in result_green.stdout, (result_green.stdout, result_green.stderr)

    # The live, shared file was never written to by this test at all --
    # asserted directly, not merely inferred from "no exception raised".
    live_bytes_after = live_target.read_text(encoding="utf-8")
    assert live_bytes_after == original, "the LIVE corroborate.py changed even though this test never writes to it"
    assert hashlib.sha256(live_bytes_after.encode()).hexdigest() == original_sha, (
        "the LIVE corroborate.py's sha256 changed even though this test never writes to it"
    )


# ===================================================================== #
# COR2 -- pairing, accepted/unresolved classification, distinct paths
# ===================================================================== #


def _tool_use(uid: str, name: str, target: str | None) -> dict:
    inp = {} if target is None else {"file_path": target}
    return {"kind": "tool_use", "type": "assistant", "id": uid, "name": name, "input": inp}


def _tool_result(uid: str, *, is_error: bool, content: str = "ok") -> dict:
    return {"kind": "tool_result", "type": "user", "tool_use_id": uid, "is_error": is_error, "content": content}


def _outcome(*, failure: str | None = None, tool_events=None, denials: tuple = ()) -> SdkOutcome:
    if tool_events is None:
        return SdkOutcome(
            ok=failure is None, rc=0, stdout="", detail="", failure=failure, denials=denials,
        )
    return SdkOutcome(
        ok=failure is None, rc=0, stdout="", detail="", failure=failure, denials=denials,
        tool_events=tuple(tool_events),
    )


def test_cor2_four_case_table_paired_ok_paired_error_unpaired_non_write(tmp_path):
    """COR2: paired+ok -> accepted (counted); paired+error -> not accepted
    (counted nowhere); unpaired -> `unresolved` increments, not inside/
    outside; a non-write-family tool (e.g. `Read`) is ignored entirely
    regardless of pairing."""
    root = tmp_path / "root"
    root.mkdir()
    ok_target = str(root / "ok.yaml")
    err_target = str(root / "err.yaml")
    events = [
        _tool_use("u-ok", "Write", ok_target), _tool_result("u-ok", is_error=False),
        _tool_use("u-err", "Write", err_target), _tool_result("u-err", is_error=True),
        _tool_use("u-unpaired", "Edit", str(root / "unpaired.yaml")),  # no matching result
        _tool_use("u-read", "Read", str(root / "read.yaml")), _tool_result("u-read", is_error=False),
    ]
    ev = RunEvidence(root, flat=True)
    ev.observe(_outcome(tool_events=events))
    assert ev.inside == {str(root / "ok.yaml")}
    assert ev.outside == set()
    assert ev.unresolved == 1


def test_cor2_two_accepted_events_one_path_counts_as_one_distinct_path(tmp_path):
    """COR2/M3: a `Write` then `Edit` on ONE staged file is two accepted
    events but ONE distinct path -- `len(.inside) == 1`, never 2."""
    root = tmp_path / "stage"
    root.mkdir()
    target = str(root / "same.yaml")
    events = [
        _tool_use("u1", "Write", target), _tool_result("u1", is_error=False),
        _tool_use("u2", "Edit", target), _tool_result("u2", is_error=False),
    ]
    ev = RunEvidence(root, flat=True)
    ev.observe(_outcome(tool_events=events))
    assert ev.inside == {target}
    assert len(ev.inside) == 1


# ===================================================================== #
# COR3 -- write family and path key are imported, never re-spelled
# ===================================================================== #


def test_cor3_write_family_and_path_key_come_from_imports_not_literals():
    """COR3: `corroborate.py` re-spells neither `charter.W` nor
    `TARGET_PATH_KEYS`. AST constant sweep for the tool-name literals;
    text sweep for `file_path`; each with ITS OWN positive control
    (`charter.py` for tool names, `toolpaths.py` for `file_path` --
    `N-2`'s split, since `charter.py` never spells `file_path` itself,
    it imports the keys)."""
    corrob_src = (_SRC / "corroborate.py").read_text(encoding="utf-8")
    charter_src = (_SRC / "invocation_sdk" / "charter.py").read_text(encoding="utf-8")
    toolpaths_src = (_SRC / "sdksession" / "toolpaths.py").read_text(encoding="utf-8")

    tree = ast.parse(corrob_src, filename="corroborate.py")
    string_constants = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for tool_name in charter_mod.W:
        assert tool_name not in string_constants, tool_name
    assert "file_path" not in corrob_src
    assert "path" not in string_constants
    assert "notebook_path" not in string_constants

    # positive controls -- these tests would be vacuous if the source
    # files never spelled the literals at all.
    assert charter_src.count('"Write"') >= 1
    assert charter_src.count("file_path") == 0  # imports the keys, never spells them
    assert toolpaths_src.count("file_path") == 1


def test_cor3_imports_charter_W_and_toolpaths_extract_target_path():
    assert corroborate.W is charter_mod.W
    assert corroborate.extract_target_path is toolpaths.extract_target_path


# ===================================================================== #
# N-2 -- observe() robustness: relative targets resolve against `root`,
# not the process's CWD; malformed events/input are skipped, never
# raised (code gate r1 fold)
# ===================================================================== #


def test_n2_relative_target_path_resolves_against_root_not_cwd(tmp_path, monkeypatch):
    """code gate r1 N-2: spec §6.2 promises a RELATIVE target path
    resolves against `root`, not the process's current working
    directory -- `Path.resolve()` on a relative path resolves against
    `os.getcwd()` on its own. Proven here by chdir-ing to a THIRD
    directory (neither `root` nor a descendant of it) before observing
    a relative target: the accepted write must still land under
    `root`, not under the CWD."""
    root = tmp_path / "stage"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    ev = RunEvidence(root, flat=True)
    events = [
        _tool_use("u1", "Write", "phantom.yaml"),  # RELATIVE, no directory component
        _tool_result("u1", is_error=False),
    ]
    ev.observe(_outcome(tool_events=events))
    assert ev.inside == {str(root / "phantom.yaml")}
    assert ev.outside == set()


def test_n2_malformed_events_are_skipped_never_raised(tmp_path):
    """code gate r1 N-2: `observe` is documented "Never raises" -- that
    promise held only for the documented `events_present=False` case
    before this fix. A non-dict event (a stray string) and a `tool_use`
    whose `input` is a non-dict (a string, not a mapping) must both be
    SKIPPED, never raise -- and a well-formed accepted write elsewhere
    in the SAME event list must still be counted normally, proving the
    malformed entries are skipped rather than aborting the whole
    observation."""
    root = tmp_path / "root"
    root.mkdir()
    ev = RunEvidence(root, flat=True)
    good_target = str(root / "good.yaml")
    events = [
        "not-a-dict-at-all",
        {"kind": "tool_use", "type": "assistant", "id": "u-bad", "name": "Write", "input": "not-a-mapping"},
        _tool_result("u-bad", is_error=False),
        _tool_use("u-good", "Write", good_target),
        _tool_result("u-good", is_error=False),
    ]
    ev.observe(_outcome(tool_events=events))  # must not raise
    assert ev.inside == {good_target}


# ===================================================================== #
# COR6 -- the seen/failure/events_present guard
# ===================================================================== #


def test_cor6_bare_outcome_no_tool_events_attribute_emits_nothing(tmp_path):
    """COR6: an outcome with NO `tool_events` attribute at all (a bare
    `Outcome`) -- `events_present` is False, `observe` does not raise,
    and `verdict`/`outside_paths` say nothing regardless of `fs_count`."""
    root = tmp_path / "root"
    root.mkdir()
    bare = types.SimpleNamespace(failure=None)  # no tool_events attribute
    ev = RunEvidence(root, flat=True)
    ev.observe(bare)
    assert ev.events_present is False
    assert ev.had_events is False
    assert ev.verdict(fs_count=3) is None
    assert ev.outside_paths() == frozenset()


def test_cor6_failed_outcome_emits_nothing_even_with_events(tmp_path):
    """COR6/M8: `outcome.failure` set -> nothing at all, even if
    `tool_events` carries real accepted writes. M8 removes this guard;
    the assertion below is what would break."""
    root = tmp_path / "root"
    root.mkdir()
    target = str(root / "x.yaml")
    events = [_tool_use("u1", "Write", target), _tool_result("u1", is_error=False)]
    ev = RunEvidence(root, flat=True)
    ev.observe(_outcome(failure="timeout", tool_events=events))
    assert ev.verdict(fs_count=0) is None
    assert ev.outside_paths() == frozenset()
    # observe() still recorded the data -- the GUARD is on emission, not
    # on ingestion (so a later re-check against a different fs_count
    # cannot resurrect a stale conclusion).
    assert ev.inside == {target}


def test_cor6_M35_collapsing_events_present_into_had_events_breaks_this_case(tmp_path):
    """B-1r2/M35: a single `had_events`-only flag cannot pass BOTH
    `COR6` (bare Outcome -> nothing) and `COR8` (empty tuple -> the
    no-evidence line) -- demonstrated directly: both inputs collapse to
    `had_events=False` under one flag, so a one-flag implementation MUST
    treat them identically, which is wrong for at least one of them."""
    root = tmp_path / "root"
    root.mkdir()
    bare = types.SimpleNamespace(failure=None)
    empty = _outcome(tool_events=())
    ev_bare = RunEvidence(root, flat=True)
    ev_bare.observe(bare)
    ev_empty = RunEvidence(root, flat=True)
    ev_empty.observe(empty)
    # the real (two-flag) implementation tells them apart
    assert ev_bare.events_present != ev_empty.events_present
    assert ev_bare.verdict(0) != ev_empty.verdict(0)
    # a one-flag implementation could not: both have had_events=False
    assert ev_bare.had_events == ev_empty.had_events == False


# ===================================================================== #
# COR8 -- events_present True, had_events False -> NO-EVIDENCE only
# ===================================================================== #


def test_cor8_empty_tool_events_yields_no_evidence_not_mismatch(tmp_path):
    """COR8: the `sdk_fake_worker`-adjacent `test_fw107_...:275` shape --
    a monkeypatched `SdkOutcome(tool_events=())`. `events_present` True,
    `had_events` False -> exactly the NO-EVIDENCE tag, never MISMATCH,
    regardless of `fs_count`."""
    root = tmp_path / "root"
    root.mkdir()
    ev = RunEvidence(root, flat=True)
    ev.observe(_outcome(tool_events=()))
    assert ev.events_present is True
    assert ev.had_events is False
    assert ev.verdict(fs_count=5) == corroborate.NO_EVIDENCE
    assert ev.outside_paths() == frozenset()


def test_cor8_via_invoke_claude_direct_call(tmp_path, monkeypatch):
    """COR8, via the real wiring: `worker._invoke_claude(..., evidence=...)`
    populates a real `RunEvidence` from a monkeypatched zero-event
    `SdkOutcome`, exactly the `test_fw107_sdk_result_denials_are_not_
    charter_denials:275` call shape with `evidence=` added."""
    fake_outcome = SdkOutcome(ok=True, rc=0, stdout="", detail="", failure=None, tool_events=())
    monkeypatch.setattr(invocation, "write_session", lambda spec, **kw: fake_outcome)
    home = tmp_path / "cor8-home"
    home.mkdir()
    ev = RunEvidence(home / "stage", flat=True)
    worker._invoke_claude(
        "prompt", 5.0, home, label="",
        containment=invocation.DEGRADED_WORKER_CONTAINMENT,
        evidence=ev,
    )
    assert ev.seen is True
    assert ev.verdict(fs_count=0) == corroborate.NO_EVIDENCE


# ===================================================================== #
# COR4/COR5/COR12/COR13/UN4 -- through the real worker.run() pipeline
# ===================================================================== #


def _run_worker_with_synthetic_outcome(env, monkeypatch, rid, *, tool_events, failure=None):
    """Seeds one pending record and drives the REAL `worker.run()` with
    `invocation.write_session` replaced by a synthetic outcome -- nothing
    physically lands in the stage (`staged_paths()` stays empty), so the
    repair round is never reached (0 refusals) regardless of what
    `tool_events` claims. Isolates the corroborator's reaction to
    PURELY REPORTED events against a REAL, empty filesystem census."""
    fake_outcome = SdkOutcome(
        ok=failure is None, rc=0, stdout="", detail="", failure=failure,
        tool_events=tuple(tool_events),
    )
    monkeypatch.setattr(invocation, "write_session", lambda spec, **kw: fake_outcome)
    result = worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    return result, log_text


def _drive_cor4_disagreeing_fixture(env, monkeypatch):
    """Shared driver for `COR4`'s disagreement fixture -- the model
    REPORTS 2 accepted inside writes but the real stage holds 0 files
    (nothing physically landed). Returns `(result, log_text)`; used by
    both the MISMATCH-text test and the UN4 status-independence test."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    events = [
        _tool_use("u1", "Write", str(stage / "a.yaml")), _tool_result("u1", is_error=False),
        _tool_use("u2", "Write", str(stage / "b.yaml")), _tool_result("u2", is_error=False),
    ]
    return _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)


def test_cor4_mismatch_line_fires_when_reported_count_disagrees_with_disk(env, monkeypatch):
    """COR4/M5/M6, byte-pinned text (§6.3): the model REPORTS 2 accepted
    inside writes but the real stage holds 0 files (nothing physically
    landed) -- MISMATCH fires with the exact wording."""
    _result, log_text = _drive_cor4_disagreeing_fixture(env, monkeypatch)
    assert (
        "run: corroboration MISMATCH — stage has 0 file(s), model reported "
        "2 accepted write(s) (filesystem is authority)"
    ) in log_text


def test_cor4_agreeing_run_emits_nothing(env, sdk_fake_worker, monkeypatch):
    """COR4/M6 (the agreement anchor, A-1's shape at a smaller, test-speed
    N -- the corpus's real anchor was N=8 distinct agreeing paths): TWO
    real writes via the REAL fake-CLI shim, both landing in the stage,
    both announced -- `len(inside) == len(staged1)` -> no MISMATCH line.
    M6 (dropping the `!=` guard so MISMATCH is unconditional) would
    redden this."""
    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    script = f"{shim_writes(env, ra)}\n{shim_writes(env, rb)}"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: stage — 2 file(s) written by the model" in log_text
    assert "corroboration MISMATCH" not in log_text
    assert "corroboration — no tool events" not in log_text
    assert "OUTSIDE the stage" not in log_text


def test_cor5_outside_line_independent_of_mismatch_both_fire(env, monkeypatch):
    """COR5/M7, and UN4 in the same fixture (spec's "offsetting" case):
    one reported accepted write INSIDE (phantom -- nothing real lands)
    and one reported accepted write OUTSIDE the stage. `len(inside)=1 !=
    staged1=0` -> MISMATCH; `outside` non-empty -> the OUTSIDE line,
    independently. Both fire on the SAME run."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    outside_target = str(env.home / "outside-write.yaml")
    events = [
        _tool_use("u-in", "Write", str(stage / "phantom.yaml")), _tool_result("u-in", is_error=False),
        _tool_use("u-out", "Write", outside_target), _tool_result("u-out", is_error=False),
    ]
    result_mismatch, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)
    assert (
        "run: corroboration MISMATCH — stage has 0 file(s), model reported "
        "1 accepted write(s) (filesystem is authority)"
    ) in log_text
    assert (
        f"run: 1 accepted write(s) reported OUTSIDE the stage (filesystem is "
        f"authority; see the event log in {worker.cache_dir()})"
    ) in log_text

    # UN4: the mismatch/outside lines never change RunResult. Compare
    # against a CLEAN run (same shape: 0 real staged files, 1 pending
    # record) whose synthetic outcome reports NOTHING -- the only
    # variable between the two runs is the corroboration input.
    rid2 = seed_pending(env, "lrn-0000cccc", created_at="2026-07-03T00:00:00Z")
    result_clean, _ = _run_worker_with_synthetic_outcome(env, monkeypatch, rid2, tool_events=())
    for field in (
        "status", "proposed", "merge_proposed", "invalid_deleted",
        "valid_landed", "committed", "commit_sha", "repair_attempted",
    ):
        assert getattr(result_mismatch, field) == getattr(result_clean, field), field


def test_cor5_outside_only_fires_without_a_mismatch(env, monkeypatch):
    """COR5/M7: the OUTSIDE line fires independently of MISMATCH in
    BOTH directions -- this is the direction the "offsetting" fixture
    above cannot show (there, MISMATCH is also true). Here, `inside`
    stays empty (no inside write reported) so `len(inside)=0 ==
    staged1=0` -> no MISMATCH, while the one reported OUTSIDE write
    still fires its own line. M7 (gating OUTSIDE behind MISMATCH) would
    silently drop it here."""
    rid = seed_pending(env)
    outside_target = str(env.home / "outside-only.yaml")
    events = [
        _tool_use("u-out", "Write", outside_target), _tool_result("u-out", is_error=False),
    ]
    _, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)
    assert "corroboration MISMATCH" not in log_text
    assert (
        f"run: 1 accepted write(s) reported OUTSIDE the stage (filesystem is "
        f"authority; see the event log in {worker.cache_dir()})"
    ) in log_text


def test_un4_M29_a_mismatch_never_sets_status_failed_by_itself(env, monkeypatch):
    """UN4/M29: the mismatch line is a LOG LINE, never a status change --
    `result.status` in the mismatching fixture above is driven entirely
    by "0 valid proposals", the same as it would be with zero reported
    events. Restated explicitly here as its own criterion-named test."""
    result, _ = _drive_cor4_disagreeing_fixture(env, monkeypatch)
    assert result.status == "failed"  # driven by 0 valid proposals, not by corroboration
    assert result.proposed == []


def test_un4_M29_mismatch_never_flips_a_landing_run_to_failed(env, monkeypatch):
    """UN4/M29, the REAL discriminator: the fixture above never lands
    anything, so its `status == "failed"` would hold with or without
    M29's mutation live -- it cannot tell the two apart. THIS fixture
    makes ONE valid proposal physically land (status would be "ok" on
    unmutated code) while the reported events MISMATCH the real census
    (0 accepted-inside writes reported against 1 real staged file, via
    an errored tool_result on the only event so nothing is `accepted`).
    If M29's mutation (folding the corroboration verdict into
    `result.status`) were live, this run's "ok" would flip to "failed"
    -- which this test would catch and the fixture above cannot."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    proposal_path = stage / f"{rid}.yaml"
    proposal_text = _proposal_yaml(env)
    events = [
        _tool_use("u1", "Write", str(proposal_path)),
        _tool_result("u1", is_error=True),  # errored -- never "accepted"
    ]
    outcome = _outcome(tool_events=events)

    def fake_write_session(spec, **kw):
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(proposal_text, encoding="utf-8")
        return outcome

    monkeypatch.setattr(invocation, "write_session", fake_write_session)
    result = worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        "run: corroboration MISMATCH — stage has 1 file(s), model reported "
        "0 accepted write(s) (filesystem is authority)"
    ) in log_text
    assert result.status == "ok"  # landing succeeds DESPITE the MISMATCH
    assert result.proposed == [rid]


def test_cor12_every_new_corroboration_line_begins_with_run_prefix(env, monkeypatch):
    """COR12/M39: every line this unit emits into `worker.log` begins
    with `run: ` -- captured across the disagreeing fixture (MISMATCH +
    OUTSIDE) and the no-evidence fixture."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    outside_target = str(env.home / "outside2.yaml")
    events = [
        _tool_use("u-in", "Write", str(stage / "phantom2.yaml")), _tool_result("u-in", is_error=False),
        _tool_use("u-out", "Write", outside_target), _tool_result("u-out", is_error=False),
    ]
    _, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)
    new_lines = [ln for ln in log_text.splitlines() if "corroboration" in ln or "OUTSIDE the stage" in ln]
    assert new_lines, "no new corroboration lines captured"
    for ln in new_lines:
        # the file format is "<ISO timestamp> <message>" (`_log_to`) --
        # the MESSAGE itself (everything after the one timestamp token
        # and its separating space) must begin with "run: ".
        _timestamp, _, rest = ln.partition(" ")
        assert rest.startswith("run: "), ln

    rid2 = seed_pending(env, "lrn-0000dddd", created_at="2026-07-04T00:00:00Z")
    _, log_text2 = _run_worker_with_synthetic_outcome(env, monkeypatch, rid2, tool_events=())
    new_lines2 = [ln for ln in log_text2.splitlines() if "no tool events recorded" in ln]
    assert new_lines2
    for ln in new_lines2:
        assert "run: corroboration — no tool events recorded" in ln


def test_cor12_M39_mutation_missing_run_prefix_would_be_caught():
    """M39's positive control: the SAME prefix assertion applied to a
    deliberately-unprefixed string fails, proving the check discriminates."""
    bad_line = "corroboration: no tool events recorded (0 file(s) on disk)"
    assert not bad_line.startswith("run: ")


def test_cor4_worker_no_evidence_line_byte_pinned(env, monkeypatch):
    """COR8 byte-pinned text on the worker surface: an empty `tool_events`
    tuple yields the exact NO-EVIDENCE line, worded for the stage."""
    rid = seed_pending(env)
    _, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=())
    assert "run: corroboration — no tool events recorded (0 file(s) on disk)" in log_text
    assert "MISMATCH" not in log_text
    assert "OUTSIDE the stage" not in log_text


# ===================================================================== #
# COR13 -- the parent-of-stage rule (flat=True)
# ===================================================================== #


def test_cor13_nested_but_inside_stage_write_counts_in_neither_bucket(env, sdk_fake_worker, monkeypatch):
    """COR13/M41: the `test_worker.py:1221` shape -- a flat proposal, a
    NESTED `sub/sneaky.yaml`, and a flat `notes.txt`. Post-§6.6-fix, all
    THREE write ops are announced as accepted, but `staged_paths()`
    (flat) sees only TWO. The corroborator must emit NOTHING -- the
    nested write lands in neither `inside` nor `outside`."""
    rid = seed_pending(env)
    sub = worker.stage_dir() / "sub"
    junk = worker.stage_dir() / "notes.txt"
    script = (
        f"{shim_writes(env, rid)}\n"
        f"mkdir -p {sub} && printf 'x: 1\\n' > {sub}/sneaky.yaml\n"
        f"printf 'scratch\\n' > {junk}"
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result = worker.run(env.home)
    assert result.status == "ok"
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    # positive control: the census really did stay flat at 2 (ST-b)
    assert "run: stage — 2 file(s) written by the model" in log_text
    # the criterion: no false MISMATCH from the 3-announced-vs-2-flat gap
    assert "corroboration MISMATCH" not in log_text
    assert "OUTSIDE the stage" not in log_text


def test_cor13_M41_mutation_would_fire_a_false_mismatch(env):
    """M41's shape, demonstrated directly against `RunEvidence`: dropping
    the parent-of-stage rule (using the miner's `flat=False` predicate on
    the worker's stage) makes the nested write count as `inside`, so
    `len(inside)=3` disagrees with the real flat census of 2."""
    stage = worker.stage_dir()
    stage.mkdir(parents=True, exist_ok=True)
    events = [
        _tool_use("u1", "Write", str(stage / "flat1.yaml")), _tool_result("u1", is_error=False),
        _tool_use("u2", "Write", str(stage / "sub" / "sneaky.yaml")), _tool_result("u2", is_error=False),
        _tool_use("u3", "Write", str(stage / "notes.txt")), _tool_result("u3", is_error=False),
    ]
    ev_flat = RunEvidence(stage, flat=True)
    ev_flat.observe(_outcome(tool_events=events))
    assert len(ev_flat.inside) == 2  # correct: the nested write counts nowhere

    ev_recursive = RunEvidence(stage, flat=False)  # M41's mutant predicate
    ev_recursive.observe(_outcome(tool_events=events))
    assert len(ev_recursive.inside) == 3  # would MISMATCH against the real flat census of 2


# ===================================================================== #
# COR7/COR9/COR10/DEN1/DEN2 -- the miner-reader
# ===================================================================== #


def _miner_log_text() -> str:
    """`miner.log` is opened in append mode ONLY when `log()` is
    actually called -- a fully-silent run (agreeing corroboration, no
    denials, no strays) never creates the file at all. Absence reads as
    empty, not as an error."""
    path = miner.miner_dir() / "miner.log"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _invoke_reader_with_outcome(monkeypatch, home: Path, outcome) -> None:
    monkeypatch.setattr(invocation, "write_session", lambda spec, **kw: outcome)
    miner._invoke_reader(home, "PROMPT")


def test_cor7_reader_census_is_after_minus_before(reader_leg, monkeypatch):
    """COR7, byte-pinned text (§6.4): the model reports one accepted
    write INSIDE the spool that never physically lands (phantom) -- the
    real `after - before` census is 0, disagreeing with the reported 1."""
    spool = miner.spool_dir()
    events = [
        _tool_use("u1", "Write", str(spool / "phantom.json")),
        _tool_result("u1", is_error=False),
    ]
    outcome = _outcome(tool_events=events)
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert (
        "run: corroboration MISMATCH — spool has 0 artifact(s), model "
        "reported 1 accepted write(s) (filesystem is authority)"
    ) in log_text


def test_cor7_agreeing_real_write_emits_nothing(reader_leg):
    """COR7 agreement anchor: a REAL single write via `.drive()` (the
    `reader_write` scenario) lands exactly one artifact and announces
    exactly one accepted write -- census 1 == inside 1 -> silent."""
    run = reader_leg.drive()
    assert run.out_path is not None
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text
    assert "no tool events recorded" not in log_text


def test_cor5_reader_outside_only_fires_without_a_mismatch(reader_leg, monkeypatch):
    """Code gate r1 M-1: the reader's own OUTSIDE-line block
    (`miner.py`, right after the MISMATCH `elif`) had NO test at all --
    deleting it left the full suite green. Mirrors `test_cor5_outside_
    only_fires_without_a_mismatch` (the worker's twin) on the
    `reader_leg` fixture: ONE reported accepted write OUTSIDE
    `spool_dir()`, nothing reported inside, nothing physically lands
    (`before`/`after` both empty) -- `len(inside)=0 == fs_count=0` -> no
    MISMATCH, while the one reported OUTSIDE write still fires its own
    line. Mutation: delete the 6-line OUTSIDE block -> this test goes
    RED (silently drops the line) while every other reader test stays
    green."""
    outside_target = str(reader_leg.home / "outside-only.yaml")
    events = [
        _tool_use("u-out", "Write", outside_target), _tool_result("u-out", is_error=False),
    ]
    outcome = _outcome(tool_events=events)
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text
    assert (
        f"run: 1 accepted write(s) reported OUTSIDE the "
        f"spool (filesystem is authority; see the event log in {worker.cache_dir()})"
    ) in log_text


def test_cor7_M9_two_real_spool_writes_need_the_recursive_census(reader_leg, monkeypatch):
    """COR7/M9: the model writes TWO real files into the spool this
    session (the artifact plus a second accepted file), both announced.
    Correct (`after - before`) census = 2 = `len(inside)` -> silent. An
    `out_path`-alone census (M9's mutant) would see only 1, firing a
    false MISMATCH -- this is the fixture that discriminates it (a
    single-write agreement anchor like `test_cor7_agreeing_real_write_
    emits_nothing` cannot: `out_path`-alone and `after-before` agree at
    N=1)."""
    spool = miner.spool_dir()
    out_path = spool / miner.OUTPUT_BASENAME
    second = spool / "second-accepted.json"
    events = [
        _tool_use("u1", "Write", str(out_path)), _tool_result("u1", is_error=False),
        _tool_use("u2", "Write", str(second)), _tool_result("u2", is_error=False),
    ]
    outcome = _outcome(tool_events=events)

    def fake_write_session(spec, **kw):
        out_path.write_text('{"candidates": [], "fires": []}', encoding="utf-8")
        second.write_text("{}", encoding="utf-8")
        return outcome

    monkeypatch.setattr(invocation, "write_session", fake_write_session)
    miner._invoke_reader(reader_leg.home, "PROMPT")
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text


def test_cor8_reader_zero_events_yields_no_evidence_line(reader_leg, monkeypatch):
    """COR8 on the miner-reader surface, byte-pinned text: an empty
    `tool_events` tuple yields the NO-EVIDENCE line worded for the spool,
    never a MISMATCH."""
    outcome = _outcome(tool_events=())
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert "run: corroboration — no tool events recorded (0 artifact(s) in the spool)" in log_text
    assert "MISMATCH" not in log_text


def test_cor9a_planted_strays_before_the_run_never_count(reader_leg):
    """COR9(a)/M36: the `test_sw3` shape -- two strays planted in the
    spool BEFORE the run, a reader that writes exactly one real file
    (`mine-output.json`). Correct: `after - before = 1 == len(inside)`
    -> silent. M36 (a flat pre-sweep census) would report 3 vs 1."""
    spool = miner.spool_dir()
    (spool / "cor9-litter-1.txt").write_text("a", encoding="utf-8")
    (spool / "cor9-litter-2.txt").write_text("b", encoding="utf-8")
    run = reader_leg.drive()
    assert run.out_path is not None
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text


def test_cor9b_stale_output_from_an_earlier_run_never_counts(reader_leg):
    """COR9(b)/M40: a stale `mine-output.json` left by an EARLIER run is
    removed by THIS run's `:751` unlink before `before` is snapshotted,
    so it is absent from `before`; the fresh write appears in `after`;
    census = 1 = `len(inside)` -> silent. M40 (snapshotting `before`
    BEFORE the unlink) would have the stale file cancel the fresh write:
    0 vs 1."""
    run1 = reader_leg.drive()
    assert run1.out_path is not None
    assert run1.out_path.is_file()  # stale artifact now sits in the spool
    run2 = reader_leg.drive()
    assert run2.out_path is not None
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text


def test_cor10_nested_accepted_write_counts_on_the_recursive_census(reader_leg, monkeypatch):
    """COR10/M37: a nested write (`spool/sub/x.json`, permitted by the
    reader's `write_globs=(f"{spool_dir}/**",)`) is counted on BOTH
    sides -- physically written AND reported -- so it agrees rather than
    mismatching. Drives the REAL write via the shim script directly
    (bypassing `.drive()`'s single-target convenience) plus a matching
    reported event. The physical write happens INSIDE the monkeypatched
    `write_session` call -- i.e. between the `before` and `after`
    snapshots `_invoke_reader` takes -- mirroring when a real session
    would produce it; writing it before the call would land it in
    `before` too and the census would see no NEW file at all."""
    spool = miner.spool_dir()
    nested = spool / "sub" / "x.json"
    events = [
        _tool_use("u1", "Write", str(nested)),
        _tool_result("u1", is_error=False),
    ]
    outcome = _outcome(tool_events=events)

    def fake_write_session(spec, **kw):
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("{}", encoding="utf-8")
        return outcome

    monkeypatch.setattr(invocation, "write_session", fake_write_session)
    miner._invoke_reader(reader_leg.home, "PROMPT")
    log_text = _miner_log_text()
    assert "corroboration MISMATCH" not in log_text


def test_den1_miner_denial_line_sorted_distinct_tools(reader_leg, monkeypatch):
    """DEN1: the denial line fires iff the charter-sourced denial count
    is nonzero; `{tools}` is the sorted DISTINCT set of denied tool
    names."""
    denials = (
        {"source": "charter", "tool": "Bash"},
        {"source": "charter", "tool": "Bash"},
        {"source": "charter", "tool": "Edit"},
    )
    outcome = _outcome(tool_events=(), denials=denials)
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert (
        f"run: 3 charter denial(s) this run (Bash, Edit) — see the event "
        f"log in {worker.cache_dir()}"
    ) in log_text


def test_den2_sdk_result_denials_never_count(reader_leg, monkeypatch):
    """DEN2/M12: `source == "sdk-result"` denials count toward NO line,
    on the miner-reader same as the worker (`FW-107`'s `N-3` filter,
    extended). The `test_fw107_sdk_result_denials_are_not_charter_
    denials` shape, replicated for the reader's new line."""
    denials = ({"source": "sdk-result", "value": {"tool_name": "Bash"}},)
    outcome = _outcome(tool_events=(), denials=denials)
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert "charter denial(s)" not in log_text


# ===================================================================== #
# DEN3 -- the analyst/teach.py leg (ruled BUILD IT, 2026-08-28,
# superseding the earlier NOT-BUILT disposition recorded above in this
# file's own module docstring -- see `S-53`/`FW-131`/17 sec5.4 for the
# coordinator's ruling text and this build's report for the numstat
# collision it resolved).
# ===================================================================== #


def test_den3_analyst_analyze_extends_charter_denials_on_success(env, monkeypatch):
    """DEN3 (analyst.py side): `analyze()`'s new keyword-only
    `charter_denials` accumulator is extended with this call's
    charter-sourced denials on the SUCCESS path (return, not raise) --
    `FW-107`'s exact shape, driven directly against a monkeypatched
    `invocation.text_session` (mirrors `COR8`'s `test_cor8_via_invoke_
    claude_direct_call` technique, one level up the call stack)."""
    denials = (
        {"source": "charter", "tool": "Bash"},
        {"source": "charter", "tool": "Bash"},
        {"source": "charter", "tool": "Edit"},
    )
    stdout = (
        "```yaml\n"
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        + _skill_gates_yaml(env)
        + "```\n"
    )
    fake_outcome = SdkOutcome(
        ok=True, rc=0, stdout=stdout, detail="", failure=None, denials=denials,
    )
    monkeypatch.setattr(invocation, "text_session", lambda spec, **kw: fake_outcome)
    charter_denials: list = []
    proposal = analyst.analyze(env.home, make_behavior(), charter_denials=charter_denials)
    assert proposal["destination"] == "skill-md"
    assert charter_denials == list(denials)


def test_den3_analyst_analyze_extends_charter_denials_before_raising(tmp_path, monkeypatch):
    """DEN3 (analyst.py side), the FAILURE branch: the extend happens
    BEFORE any of `analyze()`'s ten `AnstError` legs, so a caller sees
    this run's denials whether `analyze` returns OR raises -- the whole
    point of `teach --route` printing the line on both branches of its
    `try`. Driven with a FAILING outcome (`failure="exit"`) so `analyze`
    never reaches the parse/validate step at all."""
    denials = ({"source": "charter", "tool": "Bash"},)
    fake_outcome = SdkOutcome(
        ok=False, rc=1, stdout="", detail="denied", failure="exit", denials=denials,
    )
    monkeypatch.setattr(invocation, "text_session", lambda spec, **kw: fake_outcome)
    home = tmp_path / "den3-fail-home"
    home.mkdir()
    charter_denials: list = []
    with pytest.raises(analyst.AnalystError):
        analyst.analyze(home, make_behavior(), charter_denials=charter_denials)
    assert charter_denials == list(denials)


def test_den2_analyst_sdk_result_denials_never_count(env, monkeypatch):
    """DEN2, replicated on the analyst surface (`FW-107`'s `N-3` filter,
    extended a second time -- `DEN2`'s own criterion text: "on any
    surface"). `source == "sdk-result"` never lands in `charter_
    denials`, whether `analyze` returns or raises."""
    denials = ({"source": "sdk-result", "value": {"tool_name": "Bash"}},)
    fake_outcome = SdkOutcome(
        ok=False, rc=1, stdout="", detail="denied", failure="exit", denials=denials,
    )
    monkeypatch.setattr(invocation, "text_session", lambda spec, **kw: fake_outcome)
    home = env.home
    charter_denials: list = []
    with pytest.raises(analyst.AnalystError):
        analyst.analyze(home, make_behavior(), charter_denials=charter_denials)
    assert charter_denials == []


def test_den3_teach_route_prints_denial_line_on_the_success_branch(env, monkeypatch, capsys):
    """DEN3 (teach.py side), the SUCCESS branch: `_route_now` extends
    its own `charter_denials` accumulator and prints the line BEFORE
    the "analyst: destination ..." line, for a run that goes on to
    land successfully. Drives `_route_now` through the real CLI, with
    `analyst.analyze` replaced by a fake that mimics a real charter-
    denied-but-still-landed run -- this fake is a NEW function LOCAL to
    this test, not `test_route_cli.py`'s own pinned `fake_analyze`
    (that one's own DS1/`_ARMOR_SHAS` re-pin is `SCRUB3`'s subject, not
    this test's)."""
    def fake_analyze(home, record, *, project_path=None, charter_denials=None):
        if charter_denials is not None:
            charter_denials.extend(
                [
                    {"source": "charter", "tool": "Bash"},
                    {"source": "charter", "tool": "Bash"},
                    {"source": "charter", "tool": "Edit"},
                ]
            )
        return {"destination": "skill-md", "rationale": "r"}

    monkeypatch.setattr(analyst, "analyze", fake_analyze)
    rc = cli.main(TEACH_ARGS + ["--route"])
    captured = capsys.readouterr()
    out = captured.out
    assert rc == 0
    assert "analyst: 3 charter denial(s) this run (Bash, Edit)" in out
    # ordering: the denial line precedes the destination line (both
    # print calls sit before `route_direct` in `_route_now`'s body).
    assert out.index("charter denial(s)") < out.index("analyst: destination")


def test_den3_teach_route_prints_denial_line_on_the_failure_branch(env, monkeypatch, capsys):
    """DEN3 (teach.py side), the FAILURE branch -- the one this unit
    exists for: before this build, a denied-and-failed analyst run
    printed NOTHING about the denial at all, only the generic "analysis
    failed" fallback message. `_route_now`'s `except AnstError` leg now
    prints the SAME denial line before falling back to
    `_capture_to_pending`."""
    def fake_analyze(home, record, *, project_path=None, charter_denials=None):
        if charter_denials is not None:
            charter_denials.append({"source": "charter", "tool": "Bash"})
        raise analyst.AnalystError("simulated analyst failure")

    monkeypatch.setattr(analyst, "analyze", fake_analyze)
    rc = cli.main(TEACH_ARGS + ["--route"])
    captured = capsys.readouterr()
    assert rc == 4  # EXIT_ANALYST -- captured to pending
    assert "analyst: 1 charter denial(s) this run (Bash)" in captured.out
    assert "analysis failed" in captured.err


def test_den3_M13_positional_charter_denials_breaks_every_existing_caller():
    """DEN3/M13: `analyze`'s new parameter is keyword-only WITH a
    default -- every existing call site (which supplies neither
    `project_path` nor `charter_denials` at all, in most of this
    corpus's ~30 direct callers) keeps calling successfully. The
    predicted mutation makes it a REQUIRED POSITIONAL parameter
    instead, which breaks literally every one of those call sites with
    a `TypeError` before the call even reaches the function body --
    checked here via `inspect.signature` directly against the shipped
    function, the same shape check `test_wr1_invoke_claude_signature_
    and_never_raises` uses for `_invoke_claude`'s own `charter_denials`
    parameter (`PIN4`)."""
    import inspect

    sig = inspect.signature(analyst.analyze)
    param = sig.parameters["charter_denials"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, param.kind
    assert param.default is None


def test_den3_M14_mutation_print_only_on_success_branch_would_hide_failure_denials():
    """DEN3/M14: apply the predicted mutation to `teach.py` LIVE --
    delete the `except AnstError` branch's denial-print block, leaving
    the line on the success branch only -- confirm `test_den3_teach_
    route_prints_denial_line_on_the_failure_branch` goes RED, then
    restore via inverse edit and sha256-verify the file is back to its
    pre-mutation bytes."""
    import hashlib
    import subprocess as sp

    target = _SRC / "teach.py"
    original = target.read_text(encoding="utf-8")
    original_sha = hashlib.sha256(original.encode()).hexdigest()

    old = (
        '        except analyst.AnalystError as exc:\n'
        '            if charter_denials:\n'
        '                tools = sorted({tool for d in charter_denials if (tool := d.get("tool"))})\n'
        '                print(\n'
        '                    f"analyst: {len(charter_denials)} charter denial(s) this run "\n'
        '                    f"({\', \'.join(tools)})"\n'
        '                )\n'
        '            return _capture_to_pending(\n'
    )
    assert original.count(old) == 1, "M14 anchor not found in teach.py -- has the shape moved?"
    new = (
        '        except analyst.AnalystError as exc:\n'
        '            return _capture_to_pending(\n'
    )
    mutated = original.replace(old, new, 1)
    assert mutated != original
    target.write_text(mutated, encoding="utf-8")
    try:
        proc = sp.run(
            [
                "uv", "run", "pytest",
                "tests/test_u_corrob.py::test_den3_teach_route_prints_denial_line_on_the_failure_branch",
                "-q",
            ],
            cwd=_REPO_ROOT / "plugins/self-learn/cli",
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode != 0, (
            "M14 mutation stayed GREEN -- the failure-branch print is not "
            f"discriminated\n{proc.stdout[-2000:]}"
        )
    finally:
        target.write_text(original, encoding="utf-8")
        assert hashlib.sha256(target.read_text(encoding="utf-8").encode()).hexdigest() == original_sha, (
            "RESTORE FAILED -- teach.py is not byte-identical to its pre-mutation content"
        )


# ===================================================================== #
# COR11 -- fake_claude.py's one-pair-per-write-op fixture fix
# ===================================================================== #


def test_cor11_shim_multiwrite_still_reports_only_partial_but_now_paired(env, sdk_fake_worker, monkeypatch):
    """COR11/M38: `test_run_partial_success`'s exact shape (`test_worker.
    py:531`) -- a two-write shim (one valid, one invalid) -- emits NO
    corroboration line post-fix (both writes are announced, matching the
    2 staged files)."""
    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    good = shim_writes(env, ra)
    bad = f"printf 'destination: bogus\\n' > {worker.stage_dir()}/{rb}.yaml"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", f"{good}\n{bad}")
    result = worker.run(env.home)
    assert result.status == "ok"
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: stage — 2 file(s) written by the model" in log_text
    assert "corroboration MISMATCH" not in log_text


def test_cor11_scenario_emits_one_pair_per_write_op_directly(env, sdk_fake_worker, monkeypatch):
    """COR11: `_scenario_shim_script` emits one `tool_use`/`tool_result`
    pair PER WRITE OP, each with a distinct `tool_use` id, naming both
    targets, and still performs every write unconditionally (`R2-N3`
    preserved). Drives the REAL two-write shim through `worker.run()`
    and reads the REAL event log file it wrote (test-only -- reading a
    written event log back is what `EV4-a` forbids the PRODUCT from
    doing; a test inspecting the fixture's own output is not that)."""
    from test_worker_contract import _latest_worker_events

    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    script = f"{shim_writes(env, ra)}\n{shim_writes(env, rb)}"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    worker.run(env.home)

    events = _latest_worker_events()
    uses = [e for e in events if e.get("kind") == "tool_use"]
    results = [e for e in events if e.get("kind") == "tool_result"]
    write_uses = [u for u in uses if u.get("name") == "Write"]
    assert len(write_uses) == 2, write_uses
    ids = {u["id"] for u in write_uses}
    assert len(ids) == 2  # distinct tool_use ids
    targets = {u["input"]["file_path"] for u in write_uses}
    expected = {str(worker.stage_dir() / f"{ra}.yaml"), str(worker.stage_dir() / f"{rb}.yaml")}
    assert targets == expected
    non_error_results = [r for r in results if r.get("tool_use_id") in ids and not r.get("is_error")]
    assert len(non_error_results) == 2


# ===================================================================== #
# SCRUB1/SCRUB2/SCRUB4
# ===================================================================== #


def test_scrub1_no_emitted_line_carries_tool_input_or_result_content(env, monkeypatch):
    """SCRUB1: drive the OUTSIDE-line path with an event whose `input`
    carries the canary in BOTH the path and a non-path key, and whose
    paired result's `content` also carries it -- the canary must appear
    in NO emitted line (only `len(outside)` and `cache_dir()` are
    printed, never the path or the content). Positive control: the SAME
    canary placed in a DENIED TOOL NAME does appear in the DEN line
    (policy vocabulary, deliberately allowed)."""
    rid = seed_pending(env)
    canary = "ZZCANARYZZ"
    outside_target = str(env.home / f"outside-{canary}.yaml")
    events = [
        {
            "kind": "tool_use", "type": "assistant", "id": "u-canary", "name": "Write",
            "input": {"file_path": outside_target, "junk_key": canary},
        },
        {
            "kind": "tool_result", "type": "user", "tool_use_id": "u-canary",
            "is_error": False, "content": f"result-body-{canary}",
        },
    ]
    _, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)
    new_lines = [
        ln for ln in log_text.splitlines()
        if "corroboration" in ln or "OUTSIDE the stage" in ln
    ]
    assert new_lines
    for ln in new_lines:
        assert canary not in ln


def test_scrub1_positive_control_tool_name_appears_in_den_line(reader_leg, monkeypatch):
    """SCRUB1's positive control, isolated: a denied tool NAME containing
    the canary DOES appear in the DEN line, proving the SCRUB1 test above
    is a real discriminator (something CAN carry the canary; the
    corroboration lines specifically do not)."""
    canary = "ZZCANARYZZ"
    denials = ({"source": "charter", "tool": canary},)
    outcome = _outcome(tool_events=(), denials=denials)
    _invoke_reader_with_outcome(monkeypatch, reader_leg.home, outcome)
    log_text = _miner_log_text()
    assert canary in log_text
    # and the no-evidence line (also present, since tool_events=()) does
    # NOT carry it.
    no_evidence_lines = [ln for ln in log_text.splitlines() if "no tool events recorded" in ln]
    assert no_evidence_lines
    for ln in no_evidence_lines:
        assert canary not in ln


def test_scrub2_no_emitted_line_carries_a_path_other_than_cache_dir(env, monkeypatch):
    """SCRUB2: a regex over every captured corroboration line for `/`
    runs, allowing only the resolved `cache_dir()` string."""
    rid = seed_pending(env)
    stage = worker.stage_dir()
    outside_target = str(env.home / "some" / "nested" / "outside-path.yaml")
    events = [
        _tool_use("u-in", "Write", str(stage / "phantom3.yaml")), _tool_result("u-in", is_error=False),
        _tool_use("u-out", "Write", outside_target), _tool_result("u-out", is_error=False),
    ]
    _, log_text = _run_worker_with_synthetic_outcome(env, monkeypatch, rid, tool_events=events)
    new_lines = [
        ln for ln in log_text.splitlines()
        if "corroboration" in ln or "OUTSIDE the stage" in ln
    ]
    assert new_lines
    cache_dir_str = str(worker.cache_dir())
    for ln in new_lines:
        stripped = ln.replace(cache_dir_str, "")
        assert "/" not in stripped, ln


def test_scrub4_corroborate_has_no_file_reading_or_event_log_literals():
    """SCRUB4: `corroborate.py` contains no `read_text`, `open(`,
    `.glob(`, `.jsonl`, or `tool-events`. Positive control against
    `invocation_sdk/events.py`, which has three of the five."""
    corrob_src = (_SRC / "corroborate.py").read_text(encoding="utf-8")
    for literal in ("read_text", "open(", ".glob(", ".jsonl", "tool-events"):
        assert literal not in corrob_src, literal

    events_src = (_SRC / "invocation_sdk" / "events.py").read_text(encoding="utf-8")
    hits = sum(1 for literal in ("read_text", "open(", ".glob(", ".jsonl", "tool-events") if literal in events_src)
    assert hits >= 3, hits


# ===================================================================== #
# PIN -- U-corrob's own re-verification of the §4.1 pin census
# ===================================================================== #


def test_pin1_worker_tool_events_literal_exactly_once_pinned_fragment():
    """PIN1: `worker.py` still contains the literal `tool-events`
    EXACTLY ONCE, still `_EV4_FW107_PINNED_FRAGMENT`."""
    worker_src = (_SRC / "worker.py").read_text(encoding="utf-8")
    assert worker_src.count("tool-events") == 1
    assert 'f"worker*.tool-events.*.jsonl in {cache_dir()}"' in worker_src


def test_pin1_miner_and_corroborate_never_spell_tool_events():
    miner_src = (_SRC / "miner.py").read_text(encoding="utf-8")
    corrob_src = (_SRC / "corroborate.py").read_text(encoding="utf-8")
    assert "tool-events" not in miner_src
    assert "tool-events" not in corrob_src


def test_pin2_armor_sha_paths_are_byte_unchanged():
    """PIN2 (post-U-armor form, 2026-08-28): `test_worker_contract.py`'s
    `_ARMOR_SHAS` whole-file-pin mechanism is RETIRED -- U-armor's
    `test_armor.py::ARMOR`/ARM1..ARM6 replace it (spec
    `u-armor-narrow-whole-file-pins-spec.md` §4.7). The durable claim
    this test corroborates -- "every whole-file-pinned fixture is byte-
    unchanged from what it is pinned to" -- now lives in `test_armor.py`
    as `Fixture` rows (`support.py`, `conftest.py`, `backends.py`), each
    proven byte-identical (to its anchor, or to its `Fixture.repinned`
    sha under the anti-rot leg) with full mutation coverage by
    `test_fix1_fixtures_are_byte_identical`/
    `test_fix2_repin_door_is_exact_and_cannot_rot`. This test is an
    INDEPENDENT corroboration of the same live state, not a duplicate of
    that machinery: it parses `ARMOR`'s three `Fixture()` entries
    straight from `test_armor.py` source (still no cross-module import)
    and re-checks each against the SAME anchor commit `test_armor.py`
    itself uses (`ANCHOR`, also parsed from source), consistent with
    what F1/F2 require for a `repinned is None` row -- byte-identical to
    the anchor's own bytes."""
    import hashlib
    import re as _re

    armor_src = (_REPO_ROOT / "plugins/self-learn/cli/tests/test_armor.py").read_text()

    anchor_match = _re.search(r'^ANCHOR = "([0-9a-f]+)"', armor_src, _re.MULTILINE)
    assert anchor_match, "ANCHOR literal not found in test_armor.py"
    anchor = anchor_match.group(1)

    block = armor_src[armor_src.index("ARMOR: dict") :]
    block = block[: block.index("\n}\n") + 3]
    fixture_rows = _re.findall(r'"([A-Za-z_0-9./]+)":\s*Fixture\(', block)
    assert len(fixture_rows) == 3, sorted(fixture_rows)

    for rel in fixture_rows:
        full_rel = f"plugins/self-learn/cli/tests/{rel}"
        live = hashlib.sha256((_REPO_ROOT / full_rel).read_bytes()).hexdigest()
        anchor_bytes = subprocess.run(
            ["git", "show", f"{anchor}:{full_rel}"],
            cwd=_REPO_ROOT, capture_output=True, check=True,
        ).stdout
        anchor_sha = hashlib.sha256(anchor_bytes).hexdigest()

        # A `Fixture.repinned = (sha, reason)` entry (F2's re-pin door)
        # lets live bytes differ from anchor and ONLY to that pinned
        # sha -- parsed from the SAME per-row source span, still no
        # cross-module import. Root fix (U-xdist, 2026-08-28): the row's
        # span is found by a BALANCED-PAREN scan from the matching
        # `Fixture(` open paren, not a naive "next '),\n'" search -- the
        # naive form silently ran PAST a same-line `Fixture(),  # ...`
        # row that has no `),\n` of its own (a trailing comment sits
        # before the newline) and INTO the NEXT row's multi-line
        # `repinned=(...)` tuple, misattributing that sha to the wrong
        # file entirely (measured: exactly this shape, once conftest.py
        # gained a multi-line `repinned` entry and support.py -- the row
        # immediately before it, itself `repinned`-free -- was the one
        # whose naive scan ran past its own comment and into conftest's
        # tuple). String-literal-aware (U-xdist code gate r1 fold,
        # 2026-08-29): a bare paren-depth count over the RAW text is
        # fooled by a paren inside a reason STRING (e.g. this same
        # unit's own conftest.py reason mentions "(pytest_sessionfinish/
        # pytest_testnodedown, appended at the file's end)") the instant
        # one such string is left UNBALANCED -- so the scan below tracks
        # whether it is inside a quoted string and skips paren counting
        # there entirely, the same way a real Python tokenizer would.
        call_start = block.index(f'"{rel}": Fixture(')
        paren_start = call_start + len(f'"{rel}": Fixture')
        depth = 0
        row_end = None
        in_string = None  # None, or the quote char ("'" / '"') we are inside
        i = paren_start
        while i < len(block):
            ch = block[i]
            if in_string:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_string:
                    in_string = None
            elif ch in ("'", '"'):
                in_string = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    row_end = i + 1
                    break
            i += 1
        assert row_end is not None, f"{rel}: could not find the matching close paren"
        row_text = block[call_start:row_end]
        repin_match = _re.search(r'repinned=\(\s*"([0-9a-f]{64})"', row_text)
        if repin_match:
            assert live == repin_match.group(1), (rel, "repinned sha mismatch")
        else:
            assert live == anchor_sha, rel


def test_pin5_charter_py_byte_unchanged():
    """PIN5 (post-landing form, 2026-08-28): `charter.py`'s deny
    messages and `W` are consumed, never edited, by this unit --
    `charter.py` references none of the corroborator's names, and `W` is
    still the set `corroborate` imports (COR3 pins the import direction).
    The unit-time single-ref diff against this unit's base cannot
    survive other units landing; the property is asserted directly."""
    from self_learn.invocation_sdk import charter as charter_mod

    src = (_REPO_ROOT / "plugins/self-learn/cli/src/self_learn/invocation_sdk/charter.py").read_text()
    assert not [n for n in ("corroborate", "RunEvidence", "NO_EVIDENCE", "MISMATCH") if n in src]
    assert isinstance(charter_mod.W, (set, frozenset, tuple, list)) and charter_mod.W, charter_mod.W


def test_pin6_invocation_sdk_still_exactly_six_modules():
    """PIN6: `invocation_sdk/` still contains exactly the six modules."""
    pkg_dir = _SRC / "invocation_sdk"
    names = {p.name for p in pkg_dir.glob("*.py")}
    assert names == {
        "__init__.py", "backend.py", "charter.py", "lifecycle.py", "events.py", "provider_env.py",
    }


def test_scrub3_no_new_or_edited_test_reads_an_event_log_back():
    """SCRUB3 (post-landing form, 2026-08-28): no test this unit added
    reads an event log back -- FW-106's scan/scrub obligation attaches at
    the surfacing boundary, and this unit surfaces nothing. The unit-time
    form diffed the read-only armor files against this unit's own base
    commit and enumerated the three sanctioned armor motions line by
    line; on master those files are re-pinned by other units too, so the
    base-anchored diff is not a durable instrument. The armor files'
    integrity is `PIN2`'s job (and `test_su4a`/DS1/hy5's); THIS test pins
    the read-back property on the unit's own test module.

    Positive control: the pattern matches a deliberately constructed
    reader line, so an empty result is a real negative."""
    import re as _re

    reader = _re.compile(r"tool-events[^\n]*\.(read_text|read_bytes|open\(|glob\()|\.tool-events\.[^\n]*jsonl[^\n]*(read|open|load)")
    control = "path = cache_dir() / 'worker.tool-events.x.jsonl'; data = path.read_text()"
    assert reader.search(control), "positive control did not match"
    own = (_REPO_ROOT / "plugins/self-learn/cli/tests/test_u_corrob.py").read_text()
    hits = [ln for ln in own.splitlines() if reader.search(ln) and "positive control" not in ln and "control = " not in ln]
    assert hits == [], hits


# ===================================================================== #
# UN2 -- the lock-invariant walker sees corroborate.py's ROOT-level glob
# ===================================================================== #


def test_un2_corroborate_module_introduces_no_new_mutation_exemption():
    """UN2: `RunEvidence.observe` performs no filesystem mutation at all
    (pure in-memory) -- `test_lock_invariant.py`'s exemption map needs no
    new entry for it. Confirmed by literal sweep: none of the mutating
    primitives that module's docstring names appear in `corroborate.py`."""
    corrob_src = (_SRC / "corroborate.py").read_text(encoding="utf-8")
    for primitive in (
        "write_text", ".rename(", ".unlink(", "shutil.move", "os.replace",
        "Record.write", "gitops.stage", "gitops.commit", "mkdir",
    ):
        assert primitive not in corrob_src, primitive


def test_un5_serve_py_byte_unchanged():
    """UN5/M30 (post-landing form, 2026-08-28): `serve` is unaffected by
    the corroborator -- `serve.py` references none of this unit's names.
    The unit-time form was a single-ref diff against this unit's base
    commit; U-servehermetic legitimately changed `serve.py` (the unit-dir
    resolver) before this unit merged, so that diff is non-empty on
    master by construction. Positive control: `worker.py` DOES reference
    the names."""
    names = ("corroborate", "RunEvidence", "NO_EVIDENCE", "MISMATCH", "tool-events")
    serve_src = (_REPO_ROOT / "plugins/self-learn/cli/src/self_learn/serve.py").read_text()
    worker_src = (_REPO_ROOT / "plugins/self-learn/cli/src/self_learn/worker.py").read_text()
    assert not [n for n in names if n in serve_src], [n for n in names if n in serve_src]
    assert any(n in worker_src for n in names[:2]), "positive control: worker.py must reference the corroborator"


# ===================================================================== #
# DOC1-4
# ===================================================================== #


def test_doc1_s53_row_landed_after_s50():
    text = (_REPO_ROOT / "docs" / "specs" / "self-learn" / "03-decisions.md").read_text(encoding="utf-8")
    assert "\n| S-53 |" in text
    s50_idx = text.index("| S-50 |")
    s53_idx = text.index("| S-53 |")
    assert s50_idx < s53_idx
    # positive control: absent at base
    base = subprocess.run(
        ["git", "show", f"{_BASE_SHA}:docs/specs/self-learn/03-decisions.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "| S-53 |" not in base


def test_doc2_s44_amended_in_place_not_rewritten():
    text = (_REPO_ROOT / "docs" / "specs" / "self-learn" / "03-decisions.md").read_text(encoding="utf-8")
    assert "Amended 2026-08-27 (`U-corrob`, `S-53`)" in text
    # still amended IN the S-44 row, not a separate row
    s44_start = text.index("| S-44 |")
    s45_start = text.index("| S-45 |") if "| S-45 |" in text else len(text)
    assert "Amended 2026-08-27 (`U-corrob`, `S-53`)" in text[s44_start:s45_start] or (
        "| S-44 |" in text and text.index("Amended 2026-08-27 (`U-corrob`, `S-53`)") > s44_start
    )


def test_doc3_fw_rows_and_dated_entry_landed():
    """DOC3, placement-aware (code gate r1, M-3): the four rows must sit
    INSIDE the FW table's contiguous `|`-prefixed block -- a row placed
    below the table (with prose or a blank line breaking the run of `|`
    lines) renders as a paragraph, not a table row, which
    `"\\n| FW-128 |" in text`-style substring checks cannot tell apart
    from a real row. Located structurally: the table's own header
    delimiter (`|---|---|---|---|`) through the last consecutive
    `|`-prefixed line after it -- every FW id must appear as a row
    inside that span, and nowhere outside it."""
    text = (_REPO_ROOT / "docs" / "specs" / "self-learn" / "14-forward-work-map.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    delim_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "|---|---|---|---|")
    end_idx = delim_idx + 1
    while end_idx < len(lines) and lines[end_idx].startswith("|"):
        end_idx += 1
    table_block = lines[delim_idx:end_idx]
    for fw_id in ("FW-128", "FW-129", "FW-130", "FW-131"):
        assert any(ln.startswith(f"| {fw_id} |") for ln in table_block), (
            fw_id, "not inside the contiguous table block -- renders as a paragraph, not a row"
        )
    assert "FW-128, FW-129, FW-130, FW-131 added by `U-corrob`" in text
    base = subprocess.run(
        ["git", "show", f"{_BASE_SHA}:docs/specs/self-learn/14-forward-work-map.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    for fw_id in ("FW-128", "FW-129", "FW-130", "FW-131"):
        assert f"| {fw_id} |" not in base, fw_id


def test_doc4_runbook_paragraph_landed():
    text = (_REPO_ROOT / "docs" / "specs" / "self-learn" / "17-invocation-runbook.md").read_text(encoding="utf-8")
    assert "**Amended 2026-08-27 (`U-corrob`).**" in text
    assert "run: corroboration MISMATCH" in text
    base = subprocess.run(
        ["git", "show", f"{_BASE_SHA}:docs/specs/self-learn/17-invocation-runbook.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "**Amended 2026-08-27 (`U-corrob`).**" not in base
