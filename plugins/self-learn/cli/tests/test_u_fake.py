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

#: §3.1 `REWRITTEN` -- the top-level functions this unit may rewrite, as
#: a literal so widening it is a visible diff (`DS2`). A function that
#: still exists, renamed or with an edited body, belongs here. A
#: function DELETED outright belongs in `DS1_REMOVED` below instead --
#: `test_ds2` enforces that every `REWRITTEN` entry still resolves in
#: its module, which a deletion can never satisfy.
#: `test_e1_timeouts_read_not_hardcoded` keeps its name (not a rename)
#: but lost its `subprocess.run`-capturing half to the (now also
#: deleted, U-cleanup-B §8.4b/AG1) `test_e1b_cli_timeout_reaches_
#: subprocess_run` -- a body edit on an otherwise-unchanged, still-
#: present function, exactly what `REWRITTEN` is for. `test_attrib.py`'s
#: `_simple_shim` and `test_composer.py`'s `_shim_env` are the same
#: bash-PATH-shim ->
#: sdk-env-vars rewrite as `sdk_fake_worker`/`claude_cli_shim_
#: analyst`, just under their ORIGINAL names (neither is a fixture with
#: dependent callers to keep stable, so no rename was needed).
#: `test_a12b_trace_less_deletion_and_pipeline_not_dead_control` carried
#: an INLINE duplicate of the same bash-shim idiom, migrated the same
#: way. `test_teach_route_analyst_routes_to_shim_destination`'s body
#: dropped its CLI-argv-only assertions (`-p`/`--allowedTools`, CLI-
#: transport-only under sdk) -- ALSO tracked, separately, by `test_u_
#: sdka.py`'s own `_ARMOR_21_BY_FILE`/`_AR3_*` mechanism (two
#: independent armor systems watch this same file; both must agree).
#: U-cleanup-B (§8.1/§8.4a): `worker.write_settings_file` is deleted --
#: the batch round no longer writes a settings file at all. Six
#: `test_attrib.py` tests that used to read that file back now call the
#: new `_batch_permissions`/`_capture_batch_permissions` helpers instead
#: (`DS1_ADDED` below) -- an edited body on an otherwise-unchanged,
#: still-present test, exactly what `REWRITTEN` is for.
#: FW-117 (2026-08-28): `worker.write_repair_settings_file` deleted -- a
#: dead write nothing under the sdk backend ever read (`options_kwargs()`
#: passes `settings=None` unconditionally, `A-2`). `test_repair.py`'s
#: `test_b9_...` drops its now-vacuous "settings file does NOT exist"
#: leg; `test_d5_...` rebased onto a `invocation.write_session` spy
#: capturing the real `SessionSpec.containment` plus a new mutation-
#: detecting assertion, instead of reading a file that no longer exists.
#: `test_attrib.py`'s `test_gr1_...` (already `REWRITTEN` from
#: U-cleanup-B) and `test_gr3_...` (newly added below) both read the
#: repair round's permissions via the new `_repair_permissions` helper
#: (`DS1_ADDED`) instead of calling the deleted function directly --
#: edited bodies on otherwise-unchanged, still-present tests, exactly
#: what `REWRITTEN` is for.
REWRITTEN = (
    ("test_worker.py", "sdk_fake_worker"),
    ("test_worker.py", "notify_shim"),
    ("test_repair.py", "test_e1_timeouts_read_not_hardcoded"),
    ("test_repair.py", "_next_run_scripts"),
    ("test_repair.py", "test_f6_no_test_invokes_a_real_claude"),
    ("test_repair.py", "test_h4_every_new_line_in_obs1_is_produced_and_pinned"),
    ("test_repair.py", "test_b9_kill_switch_disables_composition"),
    ("test_repair.py", "test_d5_the_narrowed_repair_scope_is_real"),
    ("test_attrib.py", "_simple_shim"),
    ("test_attrib.py", "test_hy1_no_test_in_the_suite_invokes_a_real_claude"),
    ("test_attrib.py", "test_gr1_settings_files_enforce_defaultmode"),
    ("test_attrib.py", "test_gr3_repair_invocation_is_exact_path_over_staged_paths"),
    ("test_attrib.py", "test_gr2_batch_invocation_granted_the_stage_and_nothing_else"),
    ("test_attrib.py", "test_gr4_write_permission_rules_preserved_for_the_fallback"),
    ("test_attrib.py", "test_cp8_testworkercontainment_asserts_new_containment_and_h3"),
    ("test_attrib.py", "test_sw1_self_learn_stage_0_reverts_the_namespace_end_to_end"),
    (
        "test_attrib.py",
        "test_sw2_self_learn_enforce_scope_0_reverts_enforcement_and_only_that",
    ),
    ("test_route_cli.py", "sdk_fake_analyst"),
    ("test_route_cli.py", "test_teach_route_analyst_routes_to_shim_destination"),
    # U-corrob DEN3 (2026-08-28): `fake_analyze`'s nested body (inside
    # this still-present, otherwise-unchanged test) gained a
    # `charter_denials=None` parameter, so `_route_now`'s now-
    # unconditional call keeps working against this stand-in --
    # an edited body on an otherwise-unchanged, still-present test,
    # exactly what `REWRITTEN` is for.
    ("test_route_cli.py", "test_teach_route_bare_analyst_threads_project_path_at_project_scope"),
    ("test_composer.py", "_capture_analyst_prompt"),
    ("test_composer.py", "_shim_env"),
    (
        "test_composer.py",
        "test_a12b_trace_less_deletion_and_pipeline_not_dead_control",
    ),
    (
        "test_composer.py",
        "test_fold5_project_scope_one_shot_resolves_real_targets_when_bucket_exists",
    ),
    (
        "test_composer.py",
        "test_fold5_project_scope_bucket_exists_but_genuinely_has_no_meta",
    ),
    (
        "test_composer.py",
        "test_fold5_honest_sentinel_when_project_path_truly_not_supplied",
    ),
)

#: U-cleanup-A: top-level functions genuinely DELETED (not migrated) from
#: a `_DS1_EXPECTED`-guarded module -- same treatment as `REWRITTEN` for
#: `_extract_guarded_functions`'s purposes (excluded from BOTH sides'
#: extraction, so a base-only name parses the same way a licensed
#: rewrite does), but tracked SEPARATELY because `test_ds2` requires
#: every `REWRITTEN` entry to still resolve in its module -- a deletion
#: never can, and folding it into `REWRITTEN` would make that check
#: either vacuous or wrong. Both were CliBackend real-argv tests
#: (`--allowedTools`/`--disallowedTools`/`--settings`/`--strict-mcp-
#: config`) whose subject does not exist under the sdk backend; the
#: citation for each (why deleted, what covers it now) is left in place
#: at the deletion site in its own module, not here.
#: U-ancestry, 2026-08-28: S-52 (SCAN1) supersedes u-marker §3 criterion
#: A — the whole-file canon contract replaces the old `canon_excerpt`
#: marker-window one, and criterion B is re-homed as SCAN8 (see
#: `test_worker_contract.py::_ARMOR_SHAS`'s matching re-pin comment, the
#: OTHER armor mechanism covering this same file). These four base-only
#: names are the tests that contract replaced outright.
DS1_REMOVED = (
    ("test_worker.py", "test_run_argv_pins"),
    ("test_repair.py", "test_f2_both_invocations_share_one_argv_builder"),
    ("test_worker.py", "test_canon_excerpt_finds_the_compiler_written_markers_in_a_fat_target"),
    ("test_worker.py", "test_canon_excerpt_case_variant_of_compiler_marker_does_not_match"),
    ("test_worker.py", "test_canon_excerpt_begin_only_case_variant_does_not_match"),
    ("test_worker.py", "test_canon_excerpt_end_only_case_variant_does_not_match"),
)

#: The mirror image of `DS1_REMOVED`: top-level functions this unit
#: ADDED outright (present in head, no base counterpart) to a
#: `_DS1_EXPECTED`-guarded module. Same exclusion treatment for the same
#: reason -- excluded from BOTH sides' extraction so a head-only name
#: doesn't read as an unaccounted body change against a base that never
#: had it. `test_composer_analyst_fails_ro5` closes a genuine coverage
#: gap (`RO-5`/`CV6`, see its own docstring).
#: `_batch_permissions`/`_capture_batch_permissions` (U-cleanup-B,
#: §8.1/§8.4a) are `test_attrib.py`'s replacement for the deleted
#: `worker.write_settings_file` -- new top-level helpers, no base
#: counterpart, called by the six `REWRITTEN` `test_attrib.py` entries
#: above.
#: `test_e1b_cli_timeout_reaches_subprocess_run` (the CliBackend-only
#: half split out of `test_e1_timeouts_read_not_hardcoded`,
#: skip-decorated, `AG1`) was here U-cleanup-A -- U-cleanup-B deletes
#: the function outright (§8.4b), so it needs no exclusion entry at all
#: any more: absent from both head and base, there is nothing for
#: `_extract_guarded_functions` to find on either side.
#: U-ancestry, 2026-08-28 (see the matching `DS1_REMOVED` comment above):
#: the four head-only tests SCAN1/SCAN8 replace the deleted ones with,
#: plus two new head-only fixture-generation helpers
#: (`_scan8_filler`/`_scan8_fixture_lines`) those tests share.
#: `_repair_permissions` (FW-117, 2026-08-28) is `test_attrib.py`'s
#: replacement for the deleted `worker.write_repair_settings_file` --
#: same shape as `_batch_permissions` above, new top-level helper, no
#: base counterpart, called by the `REWRITTEN` `test_gr1_.../test_gr3_
#: ...` entries above.
DS1_ADDED = (
    ("test_composer.py", "test_composer_analyst_fails_ro5"),
    ("test_attrib.py", "_batch_permissions"),
    ("test_attrib.py", "_capture_batch_permissions"),
    ("test_worker.py", "_scan8_filler"),
    ("test_worker.py", "_scan8_fixture_lines"),
    ("test_worker.py", "test_canon_blocks_whole_file_reaches_the_compiler_written_section"),
    ("test_worker.py", "test_cap_retains_managed_region"),
    ("test_worker.py", "test_cap_retains_managed_region_begin_only_case_variant"),
    ("test_worker.py", "test_cap_retains_managed_region_end_only_case_variant"),
    ("test_attrib.py", "_repair_permissions"),
)

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
# Freeze-1 (§3.6) -- the extractor shared by DS1's count and sha legs
# ===================================================================== #


def _inverse_rename(name: str) -> str:
    """`FZ-b` step 3."""
    if name in ("sdk_fake_worker", "sdk_fake_analyst"):
        return "claude_shim"
    return name


def _inverse_rename_text(text: str) -> str:
    return text.replace("sdk_fake_worker", "claude_shim").replace(
        "sdk_fake_analyst", "claude_shim"
    )


def _extract_guarded_functions(source: str, rewritten_names) -> list:
    """`FZ-b`/`FZ-b1` -- every top-level `FunctionDef`/`AsyncFunctionDef`
    whose INVERSE-RENAMED name is not in the inverse-renamed
    `rewritten_names`, in source order, extracted DECORATOR-INCLUSIVE
    (`B-9`: a bare `ast.get_source_segment` excludes decorators, hiding
    a `@pytest.mark.skip` added above a T3 test, `M21`)."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    line_start = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    excluded = {_inverse_rename(n) for n in rewritten_names}
    segments = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _inverse_rename(node.name) in excluded:
            continue
        start_lineno = min([node.lineno] + [d.lineno for d in node.decorator_list])
        start = line_start[start_lineno - 1]
        end = line_start[node.end_lineno - 1] + node.end_col_offset
        segments.append(source[start:end])
    return segments


def _extract_named_function(source: str, name: str) -> str:
    """Decorator-inclusive segment (`FZ-b` step 2) of the top-level
    function `name` in `source` -- for a SINGLE named `REWRITTEN`
    function whose license is narrower than "excluded wholesale" (gate
    NOTE 3: `notify_shim`'s only licensed change is its parameter
    rename; everything else in its body is unpoliced by
    `_extract_guarded_functions`, which excludes it entirely)."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    line_start = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            start_lineno = min([node.lineno] + [d.lineno for d in node.decorator_list])
            start = line_start[start_lineno - 1]
            end = line_start[node.end_lineno - 1] + node.end_col_offset
            return source[start:end]
    raise LookupError(f"{name} not found as a top-level function")


#: `FZ-d`/`DS3` -- (count, sha256) per `GUARDED` module, generated by
#: running `_extract_guarded_functions` (this exact function) over
#: `git show c2669a9:plugins/self-learn/cli/tests/<module>` -- never
#: over the working tree. The build report carries the transcript;
#: `M18`'s row is why this must be true regenerated-from-git provenance
#: and not merely "these numbers came from somewhere." An extractor
#: that returns nothing (`M17`) cannot silently agree with these --
#: they do not move merely because the extractor broke.
#: U-ancestry, 2026-08-28: `test_worker.py`'s row is regenerated (55, not
#: 59) because `DS1_REMOVED` gained 4 more base-side names (the
#: superseded `canon_excerpt` tests, see the comment above `DS1_REMOVED`)
#: — those 4 functions' bodies drop OUT of this pin's base-only census,
#: same provenance discipline as the original: `_extract_guarded_functions`
#: run over `git show c2669a9:plugins/self-learn/cli/tests/test_worker.py`
#: with the CURRENT (post-registration) `names` tuple, never over the
#: working tree. The other four modules' rows are untouched.
# U-corrob DEN3 (2026-08-28): `test_teach_route_bare_analyst_threads_
# project_path_at_project_scope` moves into `REWRITTEN` above (its
# nested `fake_analyze` gained a `charter_denials=None` parameter so it
# keeps satisfying `_route_now`'s now-unconditional call) -- one fewer
# name in this module's tracked set (39 -> 38), and the remaining 38
# functions' sha is unchanged by this edit (Leg 1's own live-base-vs-
# live-head check confirms it: this row's sha is the base sha, not a
# re-measured head sha, since `REWRITTEN` exempts the touched function
# from the comparison entirely).
_DS1_EXPECTED = {
    "test_worker.py": (55, "39305f65724adfb1634ce91285b483b05aea05c662f2de9ac9bf30fa38daf1f8"),
    "test_repair.py": (62, "21f7bdbb888254603e4136f0bbbe89322465f459fab4dfaa6ca1761dfcf1a81f"),  # FW-117 (2026-08-28): b9/d5 rewritten -- re-pinned
    "test_attrib.py": (39, "8ea49a554c77736225c5b7c451c02fceb7e33291bb325204a5bd124b951a0754"),  # FW-117 (2026-08-28): gr3 rewritten, _repair_permissions added -- re-pinned
    "test_route_cli.py": (38, "45e55f94f60834643efe1bbab1636649acdd3094dd9210dcf64921b2755fdaea"),
    "test_composer.py": (40, "479a3caf84e427a86df6eb17ecefa2ede57a85185df79ff43defe0c9e5f931ec"),
}

#: The base commit these literals -- and the LIVE `git show` comparison
#: `DS1` also runs -- are anchored to (`Meas-1`: this unit's rebase base
#: IS `c2669a9`; a builder rebasing onto a later `U-sdk`/`U-bedrock`
#: must re-measure both, per `SQ-3`).
BASE_REF = "c2669a9"


def _git_show_base(module: str) -> str:
    """Recover `module`'s bytes AT `BASE_REF` (`FZ-d`: never the working
    tree)."""
    result = subprocess.run(
        ["git", "show", f"{BASE_REF}:plugins/self-learn/cli/tests/{module}"],
        cwd=TESTS_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


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


# ===================================================================== #
# DS -- diff scope
# ===================================================================== #


def test_ds1_t3_function_bodies_survive_the_inverse_rename():
    """DS1 -- `Freeze-1` holds for all five `GUARDED` modules, checked
    two independent ways (`FZ-c1`: neither alone is sufficient).

    Leg 1 -- LIVE base vs LIVE head, both through THIS SAME extractor,
    `FZ-c`'s count equality asserted FIRST: this is what an asymmetric,
    non-inverse-renamed filter (`M32`) actually breaks -- it gives
    DIFFERENT counts on base (still `claude_shim`) vs head (already
    renamed) only when both are freshly extracted; comparing head
    against a fixed pin alone cannot see it, because the naive filter's
    HEAD-side count happens to match the correct one anyway.

    Leg 2 -- both sides checked against a per-module hex literal/count
    PINNED at build time from `git show c2669a9:...` (`FZ-d`/`DS3`; the
    build report carries the generation transcript). An extractor that
    returns nothing (`M17`) cannot silently agree with this pin, because
    the pin does not move merely because the extractor broke -- only a
    builder who ALSO regenerates the pin from the working tree (`M18`)
    makes that escape, and that is a provenance defect DS3 -- not this
    test -- exists to catch.

    Leg 3 (gate NOTE 3) -- `notify_shim` is `REWRITTEN`-excluded from
    Legs 1/2 entirely (its parameter took the fixture rename), which
    left its BODY beyond that one licensed rename completely unpoliced.
    Checked separately here with the SAME inverse-rename technique,
    narrowed to just this one function: its head source, inverse-
    renamed, must equal its base source byte-for-byte."""
    for module, (expected_count, expected_sha) in _DS1_EXPECTED.items():
        names = (
            tuple(n for m, n in REWRITTEN if m == module)
            + tuple(n for m, n in DS1_REMOVED if m == module)
            + tuple(n for m, n in DS1_ADDED if m == module)
        )
        head_source = (TESTS_DIR / module).read_text(encoding="utf-8")
        base_source = _git_show_base(module)

        head_segments = _extract_guarded_functions(head_source, names)
        base_segments = _extract_guarded_functions(base_source, names)

        # Leg 1: live base vs live head.
        assert len(head_segments) == len(base_segments), (
            f"{module}: head extracted {len(head_segments)} T3 functions, "
            f"base ({BASE_REF}) extracted {len(base_segments)} — run: "
            f"git diff {BASE_REF}..HEAD -- plugins/self-learn/cli/tests/{module}"
        )
        head_concat = "".join(_inverse_rename_text(s) for s in head_segments)
        base_concat = "".join(_inverse_rename_text(s) for s in base_segments)
        head_sha = hashlib.sha256(head_concat.encode()).hexdigest()
        base_sha = hashlib.sha256(base_concat.encode()).hexdigest()
        assert head_sha == base_sha, (
            f"{module}: T3 function bodies changed beyond the declared "
            f"rename — run: git diff {BASE_REF}..HEAD -- "
            f"plugins/self-learn/cli/tests/{module}"
        )

        # Leg 2: both sides pinned against a build-time literal.
        assert len(head_segments) == expected_count, (
            f"{module}: extracted {len(head_segments)} T3 functions, "
            f"expected {expected_count} (pinned at {BASE_REF}) — run: git "
            f"diff {BASE_REF}..HEAD -- plugins/self-learn/cli/tests/{module}"
        )
        assert head_sha == expected_sha, (
            f"{module}: T3 function bodies' sha does not match the "
            f"literal pinned at {BASE_REF} — run: git diff {BASE_REF}..HEAD "
            f"-- plugins/self-learn/cli/tests/{module}"
        )

    # Leg 3: notify_shim's licensed change is ONLY its parameter rename.
    notify_head_source = (TESTS_DIR / "test_worker.py").read_text(encoding="utf-8")
    notify_base_source = _git_show_base("test_worker.py")
    head_notify = _extract_named_function(notify_head_source, "notify_shim")
    base_notify = _extract_named_function(notify_base_source, "notify_shim")
    assert _inverse_rename_text(head_notify) == base_notify, (
        "notify_shim changed beyond its licensed parameter rename "
        "(claude_shim -> sdk_fake_worker) — run: git diff "
        f"{BASE_REF}..HEAD -- plugins/self-learn/cli/tests/test_worker.py"
    )


def test_ds2_rewritten_set_is_exact_and_every_entry_is_live():
    """DS2 -- `REWRITTEN` contains exactly the functions named in §3.1's
    table (a stale OR an added entry is caught, not just a missing one),
    and every entry names a function that exists in its module."""
    expected = {
        ("test_worker.py", "sdk_fake_worker"),
        ("test_worker.py", "notify_shim"),
        ("test_repair.py", "test_e1_timeouts_read_not_hardcoded"),
        ("test_repair.py", "_next_run_scripts"),
        ("test_repair.py", "test_f6_no_test_invokes_a_real_claude"),
        ("test_repair.py", "test_h4_every_new_line_in_obs1_is_produced_and_pinned"),
        ("test_repair.py", "test_b9_kill_switch_disables_composition"),
        ("test_repair.py", "test_d5_the_narrowed_repair_scope_is_real"),
        ("test_attrib.py", "_simple_shim"),
        ("test_attrib.py", "test_hy1_no_test_in_the_suite_invokes_a_real_claude"),
        ("test_attrib.py", "test_gr1_settings_files_enforce_defaultmode"),
        ("test_attrib.py", "test_gr3_repair_invocation_is_exact_path_over_staged_paths"),
        (
            "test_attrib.py",
            "test_gr2_batch_invocation_granted_the_stage_and_nothing_else",
        ),
        ("test_attrib.py", "test_gr4_write_permission_rules_preserved_for_the_fallback"),
        (
            "test_attrib.py",
            "test_cp8_testworkercontainment_asserts_new_containment_and_h3",
        ),
        ("test_attrib.py", "test_sw1_self_learn_stage_0_reverts_the_namespace_end_to_end"),
        (
            "test_attrib.py",
            "test_sw2_self_learn_enforce_scope_0_reverts_enforcement_and_only_that",
        ),
        ("test_route_cli.py", "sdk_fake_analyst"),
        ("test_route_cli.py", "test_teach_route_analyst_routes_to_shim_destination"),
        # U-corrob DEN3 (2026-08-28):
        (
            "test_route_cli.py",
            "test_teach_route_bare_analyst_threads_project_path_at_project_scope",
        ),
        ("test_composer.py", "_capture_analyst_prompt"),
        ("test_composer.py", "_shim_env"),
        (
            "test_composer.py",
            "test_a12b_trace_less_deletion_and_pipeline_not_dead_control",
        ),
        (
            "test_composer.py",
            "test_fold5_project_scope_one_shot_resolves_real_targets_when_bucket_exists",
        ),
        (
            "test_composer.py",
            "test_fold5_project_scope_bucket_exists_but_genuinely_has_no_meta",
        ),
        (
            "test_composer.py",
            "test_fold5_honest_sentinel_when_project_path_truly_not_supplied",
        ),
    }
    assert len(REWRITTEN) == 26  # merge 2026-08-28: base 22 + master's 1 + U-fw117's 3
    assert set(REWRITTEN) == expected

    for module, name in REWRITTEN:
        source = (TESTS_DIR / module).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names_in_module = {
            n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in names_in_module, (module, name)


def test_ds1b_removed_set_is_exact_and_every_entry_is_base_only():
    """DS1b -- the mirror image of `DS2` for `DS1_REMOVED`: contains
    exactly the two functions this unit deleted outright, and every
    entry names a function that exists in `BASE_REF`'s module but NOT in
    the current one (the reverse of `DS2`'s existence check -- `REWRITTEN`
    entries must still resolve; `DS1_REMOVED` entries must not)."""
    expected = {
        ("test_worker.py", "test_run_argv_pins"),
        ("test_repair.py", "test_f2_both_invocations_share_one_argv_builder"),
        (
            "test_worker.py",
            "test_canon_excerpt_finds_the_compiler_written_markers_in_a_fat_target",
        ),
        ("test_worker.py", "test_canon_excerpt_case_variant_of_compiler_marker_does_not_match"),
        ("test_worker.py", "test_canon_excerpt_begin_only_case_variant_does_not_match"),
        ("test_worker.py", "test_canon_excerpt_end_only_case_variant_does_not_match"),
    }
    assert len(DS1_REMOVED) == 6
    assert set(DS1_REMOVED) == expected

    for module, name in DS1_REMOVED:
        base_tree = ast.parse(_git_show_base(module))
        base_names = {
            n.name for n in base_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in base_names, (module, name, "not present at", BASE_REF)

        head_tree = ast.parse((TESTS_DIR / module).read_text(encoding="utf-8"))
        head_names = {
            n.name for n in head_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name not in head_names, (module, name, "still present in head -- REWRITTEN, not DS1_REMOVED")


def test_ds1c_added_set_is_exact_and_every_entry_is_head_only():
    """DS1c -- the mirror image of `DS1b` for `DS1_ADDED`: contains
    exactly the functions this unit added outright, and every entry
    names a function that exists in the current module but NOT in
    `BASE_REF`'s (the reverse of `DS1b`'s existence check)."""
    expected = {
        ("test_composer.py", "test_composer_analyst_fails_ro5"),
        ("test_attrib.py", "_batch_permissions"),
        ("test_attrib.py", "_capture_batch_permissions"),
        ("test_worker.py", "_scan8_filler"),
        ("test_worker.py", "_scan8_fixture_lines"),
        ("test_worker.py", "test_canon_blocks_whole_file_reaches_the_compiler_written_section"),
        ("test_worker.py", "test_cap_retains_managed_region"),
        ("test_worker.py", "test_cap_retains_managed_region_begin_only_case_variant"),
        ("test_worker.py", "test_cap_retains_managed_region_end_only_case_variant"),
        ("test_attrib.py", "_repair_permissions"),
    }
    assert len(DS1_ADDED) == 10  # merge 2026-08-28: base 3 + master's 6 + U-fw117's 1
    assert set(DS1_ADDED) == expected

    for module, name in DS1_ADDED:
        head_tree = ast.parse((TESTS_DIR / module).read_text(encoding="utf-8"))
        head_names = {
            n.name for n in head_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in head_names, (module, name, "not present in head")

        base_tree = ast.parse(_git_show_base(module))
        base_names = {
            n.name for n in base_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name not in base_names, (module, name, "already present at", BASE_REF, "-- REWRITTEN, not DS1_ADDED")
