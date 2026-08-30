"""U-fake §3.9 `Home-1`/`BL-1` — home of ALL 17 of this unit's criterion
tests. r1 homed its criterion tests in the modules they constrain, which
put new node IDs into `GUARDED` modules and falsified the very criteria
those tests existed to satisfy (§3.9's own account). None of the tests
below may move into a `GUARDED` module for the same reason.

`Sets-1` (§3.1), restated here as the literals this module's own tests
read, per `RN-c`/`BL-1`.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
import subprocess
from pathlib import Path

import pytest

from test_worker import sdk_fake_worker, env  # noqa: F401 -- fixtures resolved by name
from test_route_cli import sdk_fake_analyst  # noqa: F401 -- fixture resolved by name

TESTS_DIR = Path(__file__).parent

GUARDED = (
    "test_worker.py",
    "test_repair.py",
    "test_attrib.py",
    "test_route_cli.py",
    "test_composer.py",
)
# U-cleanup-B (§8.3): `shims.py` is deleted along with the rest of the
# CLI transport -- dropped from ADDED (SH3 below scans this set for a
# bare single-element `claude` argv literal; a deleted file has nothing
# to scan).
ADDED = ("test_u_fake.py", "backends.py")
FIXTURE_NAMES = ("sdk_fake_worker", "sdk_fake_analyst")
LEGACY_NAME = "claude_shim"


# ===================================================================== #
# FX -- fixture disambiguation
# ===================================================================== #


def test_fx1_no_claude_shim_def_statement_anywhere():
    """FX1 -- no module defines `def claude_shim` anymore; `Compat-1`'s
    alias (a module-level `Assign`, not a `def`) is legitimate and is
    policed by `FX4` instead. Guarded by a positive control first: "no
    function named X" is vacuously true of an empty or wrong module
    scan."""
    import test_worker
    import test_route_cli

    for module, name in (
        (test_worker, "sdk_fake_worker"),
        (test_route_cli, "sdk_fake_analyst"),
    ):
        fn = getattr(module, name)
        assert hasattr(fn, "_fixture_function_marker"), (module.__name__, name)

    for path in sorted(TESTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name != LEGACY_NAME, f"{path.name}:{node.lineno}"


def test_fx2_worker_fixture_shape(sdk_fake_worker):
    """FX2 -- `sdk_fake_worker`'s returned dict has exactly the
    base key set; `dir`/`log`/`prompt` are `Path`s, `argv`/`call_prompt`/
    `count` are callables. Driven by REQUESTING the fixture, not by
    reading source."""
    d = sdk_fake_worker
    assert set(d.keys()) == {"log", "prompt", "dir", "argv", "call_prompt", "count"}
    for key in ("dir", "log", "prompt"):
        assert isinstance(d[key], Path), key
    for key in ("argv", "call_prompt", "count"):
        assert callable(d[key]), key


def test_fx2_analyst_fixture_shape(sdk_fake_analyst):
    """FX2 -- `sdk_fake_analyst`'s returned dict has exactly the
    base key set, all four values `Path`s. `"prompt"` (U-cleanup-A: the
    sdk-backed replacement's prompt-log capture, `FAKE_CLAUDE_PROMPT_LOG`)
    joined the original three when the fixture was rebased onto
    `SdkBackend` -> `fake_claude.py` -- the bash shim had no equivalent
    (the prompt rode argv, never a logged file of its own)."""
    d = sdk_fake_analyst
    assert set(d.keys()) == {"log", "out", "cwd", "prompt"}
    for key in ("log", "out", "cwd", "prompt"):
        assert isinstance(d[key], Path), key


def test_fx4_compat_alias_is_extinct():
    """FX4, U-cleanup-B RE-BASELINE (§8.3, `R-1`): `Compat-1`'s alias
    (`claude_shim = sdk_fake_worker`, module-level in
    `test_repair.py`) is DELETED, and `test_invocation.py` (its one
    importer) now imports `sdk_fake_worker` directly. Inverted
    from FX4's original "appears exactly once" shape to its natural
    successor: a tripwire against the alias, or an importer of the
    legacy name, ever being reintroduced."""
    alias_sites = []
    importer_sites = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == LEGACY_NAME
                and isinstance(node.value, ast.Name)
                and node.value.id == "sdk_fake_worker"
            ):
                alias_sites.append(path.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == LEGACY_NAME:
                        importer_sites.append(path.name)

    assert alias_sites == [], alias_sites
    assert importer_sites == [], importer_sites


def test_fx5_renamed_fixture_did_not_rename_two_tests():
    """FX5 -- the two node IDs of `RN-c` are present, spelled exactly as
    at base. A blunt `sed` over `test_worker.py` renames these two TEST
    FUNCTIONS as a side effect (they carry the fixture's old name in
    their OWN names) while leaving the collected count and `DS1`
    (inverse-rename-symmetric) both green -- `SU1`'s set leg is the
    other guard that sees it; this is the "asserted by name" one
    (`HM-a`'s cost: it lives here, not in `test_worker.py`)."""
    import test_worker

    for name in (
        "test_claude_shim_path_never_resolves_a_real_self_learn_notify",
        "test_claude_shim_default_notify_send_stub_is_present",
    ):
        fn = getattr(test_worker, name, None)
        assert fn is not None, f"{name} missing from test_worker.py — RN-c renamed it"
        assert inspect.isfunction(fn)


# ===================================================================== #
# SH -- shims.py
# ===================================================================== #


# U-cleanup-B DELETE (§8.3): `test_sh1_emitted_shim_bytes_are_sha_pinned`
# pinned `shims.write_worker_claude_shim`/`write_analyst_claude_shim`'s
# emitted byte shape directly -- both functions, and the module that
# defined them, are deleted along with the rest of the CLI transport.


def test_sh2_fixture_retains_the_three_guarded_literals():
    """SH2 -- `B-2`/`B-3`'s two path literals and the PATH-prepend line
    stay IN the fixture, not in `shims.py`. The two path literals are
    checked on the AST -- an `Assign` whose VALUE expression carries the
    literal, i.e. the CODE computes that path -- never by a raw
    source-text search: `sdk_fake_worker`'s own DOCSTRING also
    mentions both words in prose, so a text search stays green even
    after the computing `Assign` moves to `shims.py` (gate MAJOR 1,
    `M6`; the shipped `test_attrib.py::test_hy1_...`'s B-2 legs share
    this exact defect and are out of this unit's reach -- GUARDED,
    frozen beyond the mechanical rename)."""
    import test_worker

    src = inspect.getsource(test_worker.sdk_fake_worker)
    tree = ast.parse(src)
    func_node = tree.body[0]
    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))

    computed_literals = set()
    for stmt in func_node.body:
        if isinstance(stmt, ast.Assign):
            for sub in ast.walk(stmt.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    computed_literals.add(sub.value)

    assert "claude-invocation-count" in computed_literals, (
        "no Assign in sdk_fake_worker COMPUTES a path containing "
        "'claude-invocation-count' — has the counter assignment moved to shims.py?"
    )
    assert "claude-calls" in computed_literals, (
        "no Assign in sdk_fake_worker COMPUTES a path containing "
        "'claude-calls' — has the calls_dir assignment moved to shims.py?"
    )
    assert (
        'monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))' in src
    )


def test_sh3_new_modules_carry_no_bare_claude_argv():
    """SH3 -- `B-1`'s guard reaches all three NEW files: none may
    contain a bare one-element argv list holding only the word claude
    (the shape a real spawn's argv[0] would take)."""
    # a pattern that does not itself contain that shape as a contiguous
    # substring, so this detection line can never match its own source
    # (mirrors test_repair.py::test_f6's own care about this).
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    for name in ADDED:
        path = TESTS_DIR / name
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not pattern.search(line), (name, i, line)


# U-cleanup-B DELETE (§8.3): `test_sh4_shims_public_surface_is_honest`
# checked `shims.__all__`'s exports directly and AST-scanned `shims.py`'s
# own imports for `self_learn`/`test_*` leakage -- the whole module is
# deleted.


# ===================================================================== #
# BK -- backends.py
# ===================================================================== #


def _minimal_session_spec(tmp_path, prompt="p"):
    from self_learn.invocation import SessionSpec, containment_for

    return SessionSpec(
        surface="analyst",
        prompt=prompt,
        cwd=tmp_path,
        timeout=5.0,
        containment=containment_for("analyst"),
        log=lambda _msg: None,
        doctrine=None,
    )


def test_bk1_install_fake_patches_the_registry_binding(request, monkeypatch, tmp_path):
    """BK1 -- `install_fake` patches
    `self_learn.invocation.registry.backend_for`, asserted BEHAVIORALLY:
    a `text_session` call with no `backend=` keyword reaches the fake.
    PATH is sanitized first (`B-7a`) so a build that patched the
    package-level re-export instead falls through to a `CliBackend` that
    can find no executable -- deterministic, never a real spawn."""
    from backends import install_fake, analyst_text
    from self_learn import invocation

    monkeypatch.setenv("PATH", str(tmp_path))
    fake = install_fake(request, monkeypatch, [analyst_text("k: v\n")])

    outcome = invocation.text_session(_minimal_session_spec(tmp_path))
    assert outcome.ok
    assert len(fake.specs) == 1


def test_bk2_assert_fake_was_used_fires_on_an_unused_fake(request, monkeypatch, tmp_path):
    """BK2 -- `assert_fake_was_used` raises, naming the missed-patch
    fail-open, on a `FakeBackend` that recorded nothing, and does not
    raise on one that recorded a call. A second leg spies on `request`
    to confirm `install_fake` registered the finalizer through it
    (`B-5a`: `MonkeyPatch` has no `addfinalizer`)."""
    from backends import assert_fake_was_used, install_fake, analyst_text
    from self_learn.invocation import FakeBackend
    from self_learn import invocation

    unused = FakeBackend([])
    with pytest.raises(AssertionError, match="backend_for"):
        assert_fake_was_used(unused)

    monkeypatch.setenv("PATH", str(tmp_path))
    used = install_fake(request, monkeypatch, [analyst_text("k: v\n")])
    invocation.text_session(_minimal_session_spec(tmp_path))
    assert_fake_was_used(used)  # must not raise

    class _SpyRequest:
        def __init__(self):
            self.finalizers = []

        def addfinalizer(self, fn):
            self.finalizers.append(fn)

    spy = _SpyRequest()
    install_fake(spy, monkeypatch, [])
    assert len(spy.finalizers) == 1


def test_bk3_backends_public_surface_is_honest():
    """BK3 -- as the now-deleted `SH4`'s first two legs (U-cleanup-B,
    §8.3: `shims.py` and its own honesty check are gone) once checked for
    `shims.py`, for `backends.py`: `__all__` non-empty, every export
    consumed in-suite. The import legs do not apply (`BK-d`: `backends.py`
    DOES import from `self_learn.invocation`, which is required)."""
    import backends

    assert backends.__all__

    other_src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(TESTS_DIR.glob("*.py"))
        if p.name != "backends.py"
    )
    for name in backends.__all__:
        assert re.search(rf"\b{re.escape(name)}\s*\(", other_src), name


#: The three `test_fold5_*` MOVE1 tests specifically -- NOT derived by
#: filtering `REWRITTEN` for `test_composer.py` entries starting with
#: `test_` (U-cleanup-A added two more test-prefixed `test_composer.py`
#: entries, `test_a12b_...`/`test_composer_analyst_fails_ro5`, that are
#: NOT MOVE1 tests and must not be swept in by a name-prefix filter).
MOVE1_TEST_NAMES = (
    "test_fold5_project_scope_one_shot_resolves_real_targets_when_bucket_exists",
    "test_fold5_project_scope_bucket_exists_but_genuinely_has_no_meta",
    "test_fold5_honest_sentinel_when_project_path_truly_not_supplied",
)

#: `MV-c1`'s eight prompt assertions, enumerated from source at
#: `c2669a9` -- three of the eight are negative controls (`not in`) --
#: GROUPED BY LEG (gate NOTE 1): each leg's needles are checked against
#: THAT test's own source span, never the union of all three, closing
#: two gaps the union form had -- a needle satisfied by the WRONG leg
#: (P6), and a mangled positive whose bare string constant survives
#: even though the `assert ... in prompt` wrapping it was dropped or
#: broken (P5). Needle #7 (leg 3's positive) is therefore the
#: CONTIGUOUS text through `in prompt`, not the bare string alone.
PROMPT_ASSERTIONS_BY_LEG = {
    "test_fold5_project_scope_one_shot_resolves_real_targets_when_bucket_exists": (
        'assert f"ALWAYS target      : {host_str}/CLAUDE.md" in prompt',
        'assert f"PATHED rules dir   : {host_str}/.claude/rules" in prompt',
        'assert f"DEMAND target      : {host_str}/references/LEARNINGS.md" in prompt',
        'assert "unresolvable" not in prompt',
    ),
    "test_fold5_project_scope_bucket_exists_but_genuinely_has_no_meta": (
        'assert "(unresolvable — project bucket has no meta.yaml)" in prompt',
        'assert "record not yet persisted" not in prompt',
    ),
    "test_fold5_honest_sentinel_when_project_path_truly_not_supplied": (
        '"(unresolvable — record not yet persisted; project path not supplied)"\n'
        '        in prompt',
        'assert "project bucket has no meta.yaml" not in prompt',
    ),
}

# ===================================================================== #
# T1 -- the three Move-1 conversions (source reads of test_composer.py)
# ===================================================================== #


def test_t1a_move1_tests_keep_all_eight_prompt_assertions():
    """T1a -- each of the three `Move-1` tests, read from source, still
    contains ITS OWN leg's prompt assertions of `MV-c1` verbatim -- each
    needle checked against THAT test's own source span (gate NOTE 1),
    not the union of all three: a needle satisfied by the wrong leg, or
    a stray string no longer wired to an `assert`, is not evidence that
    leg still contains it. "And all three pass" is `SU1`'s leg, not this
    one -- this test reads source and never executes them."""
    import test_composer

    for name, needles in PROMPT_ASSERTIONS_BY_LEG.items():
        src = inspect.getsource(getattr(test_composer, name))
        for needle in needles:
            assert needle in src, (name, needle)


def test_t1b_move1_tests_assert_the_fake_was_reached():
    """T1b -- each of the three contains `assert len(fake.prompts) == 1`,
    so a fall-through to a real backend cannot satisfy them (`M33`, not
    `M9` -- `M9` mutates `backends.py`, which this source read never
    looks at). U-cleanup-B rebase (§8.1): the literal moved from
    `fake.argvs` to `fake.prompts` -- `CliBackend` is deleted and there
    is no argv left to count."""
    import test_composer

    for name in MOVE1_TEST_NAMES:
        src = inspect.getsource(getattr(test_composer, name))
        assert "assert len(fake.prompts) == 1" in src, name


def test_t1c_move1_tests_keep_the_argv_shape_assertions():
    """T1c -- U-cleanup-B RE-BASELINE (§8.1): the argv-shape assertions
    this test originally named (`fake.argvs[0][0] == "claude"`, etc.)
    have no surviving subject -- `analyst.build_argv` is deleted and
    there is no argv anymore. What survives is the property those
    assertions served: each of the three still reads the composed
    prompt from `fake.prompts[0]`, the analyst's own real `SessionSpec.
    prompt` field, not a hand-recomputed value (`MV-c`)."""
    import test_composer

    for name in MOVE1_TEST_NAMES:
        src = inspect.getsource(getattr(test_composer, name))
        assert "prompt = fake.prompts[0]" in src, name


