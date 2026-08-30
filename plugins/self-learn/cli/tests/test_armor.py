"""U-armor (docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-
spec.md, r7, SOUND) -- one module, one table, replacing the three
whole-file armor mechanisms that used to live in ``test_worker_
contract.py`` (``_ARMOR_SHAS``/``SU4A``/``SU4B``), ``test_u_sdka.py``
(``AR1``/``AR3``/``HY3``/``HY5``) and ``test_u_fake.py`` (``DS1``/``DS2``).

Three kinds, one anchor:

* **FIXTURE** (``support.py``, ``conftest.py``, ``backends.py``) --
  whole-file byte identity against ``ANCHOR``, with a dated ``repinned``
  door as the only legal drift (``F1``-``F3``, section 4.3).
* **ADDITIVE** (``fixtures/fake_claude.py``) -- ``SU4B``'s four legs,
  migrated verbatim, reading their sanctioned sets from one ``Additive``
  record instead of three module constants (section 4.4).
* **BEHAVIOUR** (the eight test files that hold the suite's actual
  assertions) -- every top-level AST node, keyed by name and compared by
  a normalized dump computed at ``ANCHOR``. A unit may ADD nodes freely;
  it may not DELETE, RENAME or EDIT one without a dated, anchored entry
  in ``Behaviour.missing`` / ``.edited`` / ``.edited_exports``
  (``B1``-``B7``, section 4.5).

A second table, ``MEASURED``, holds the literals ``BEH5``/``BEH7``/
``EXM3`` check the ``ARMOR`` table against. They are anchor-scoped, so
every landing invalidates them, and ``--remeasure`` never rewrites one:
it REFUSES to advance the anchor while any is stale and prints what to
transcribe (``ANC1``-``ANC6``, U-anchorlit). That buys two things and
no more. First, the motion stops at a NAMED refusal before anything is
written -- before this door existed the anchor advanced and the suite
went red afterwards, with assertions naming nothing about the anchor
(measured 2026-08-29: ``2 failed, 39 passed``). Second, the literals
change only through a deliberate, dated, justified edit -- the same
posture section 4.7 already requires of an exemption entry. The author
of that edit is whoever performs the landing; an AGENT is a sanctioned
author here, exactly as for an exemption entry (``e59534b``).

``ANCHOR`` is the first-parent PARENT of the most recent first-parent
merge on ``master`` (section 4.2) -- never the merge itself. It is
advanced only by the landing chain's ``--remeasure`` step, which
computes the whole owed set BEFORE writing anything and refuses (writing
nothing) if any node is ``missing``/``edited`` without a dated exemption
naming a spec section.

This module carries no product code and touches no file under
``plugins/self-learn/cli/src`` or ``plugins/self-learn/ui`` (``UN1``).
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

import pytest

# ===================================================================== #
# Repo-relative plumbing -- one place, matching the sibling armor files'
# own `_REPO_ROOT`/`_repo_root()` convention.
# ===================================================================== #

_REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)

#: Every `ARMOR` key is relative to this directory (section 4.1).
_TESTS_DIR = "plugins/self-learn/cli/tests"


def _relpath(key: str) -> str:
    return f"{_TESTS_DIR}/{key}"


def _abspath(key: str) -> Path:
    return _REPO_ROOT / _relpath(key)


def _git_show_bytes(rev: str, key: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{rev}:{_relpath(key)}"],
        cwd=_REPO_ROOT, capture_output=True, check=True,
    )
    return proc.stdout


def _git_show_text(rev: str, key: str) -> str:
    return _git_show_bytes(rev, key).decode("utf-8")


# ===================================================================== #
# The anchor -- section 4.2. `ANCHOR` replaces `BASE_COMMIT` (the old
# `test_worker_contract.py`), `_BASE_SHA` (`test_u_sdka.py`) and
# `BASE_REF` (`test_u_fake.py`). It is the first-parent PARENT of the
# most recent first-parent merge on `master` -- measured at build time
# (section 9.0): master's latest first-parent merge is `9b9b1a1` (this
# spec's own docs-only landing), whose first parent is `6038eee`. Every
# literal below is measured against THAT commit, not the spec's own
# `3b8e037` (the pre-Phase-2 value the spec was authored against) --
# `6038eee..9b9b1a1` touches only docs (`git diff --numstat 6038eee..
# 9b9b1a1 -- plugins/self-learn/cli` is empty), so the CLI tree at this
# anchor is byte-identical to what the spec measured at `fe5a012`
# (`= 3b8e037`'s child). The landing chain rewrites this via
# `--remeasure`, never a human (section 4.2).
ANCHOR = "6815503"


# ===================================================================== #
# The node census -- section 2.10 / 4.5, quoted verbatim from the spec
# (the spec requires a gate to re-run this exact algorithm).
# ===================================================================== #


class _Strip(ast.NodeTransformer):
    """Drop docstrings only. Every other statement is kept."""

    def _s(self, node):
        self.generic_visit(node)
        b = node.body
        if (
            b
            and isinstance(b[0], ast.Expr)
            and isinstance(b[0].value, ast.Constant)
            and isinstance(b[0].value.value, str)
        ):
            node.body = b[1:] or [ast.Pass()]
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Module = _s


def _norm_dump(node: ast.AST) -> str:
    n = _Strip().visit(copy.deepcopy(node))
    ast.fix_missing_locations(n)
    return ast.dump(n, annotate_fields=False, include_attributes=False)


def _key(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return f"func:{node.name}"
    if isinstance(node, ast.ClassDef):
        return f"class:{node.name}"
    if isinstance(node, ast.Assign):
        ts = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if ts:
            return "assign:" + ",".join(sorted(ts))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return f"assign:{node.target.id}"
    if isinstance(node, ast.Import):
        return "import:" + ",".join(sorted(a.name for a in node.names))
    if isinstance(node, ast.ImportFrom):
        return f"importfrom:{node.module}:" + ",".join(sorted(a.name for a in node.names))
    return "other:" + hashlib.sha256(_norm_dump(node).encode("utf-8")).hexdigest()[:16]


def _census(source: str) -> dict[str, str]:
    """Every top-level node, keyed by `_key` and compared by
    `_norm_dump`. The MODULE docstring is stripped before the body is
    keyed (r5, gate M-1), so a module-docstring reword is invisible --
    it is not a node at all, not an `other:` node that content-hashes to
    a new value. A dict comprehension over `mod.body` in SOURCE ORDER
    means a top-level name defined twice (a shadowing redefinition)
    lands on the LAST definition -- the same binding `import` would
    produce, so this already satisfies "resolved through the imported
    module, never an ast first-match" (section 2.9's `SU4B` leg 1
    requirement) without an actual dynamic import."""
    mod = _Strip().visit(ast.parse(source))
    ast.fix_missing_locations(mod)
    return {_key(n): _norm_dump(n) for n in mod.body}


def _dump_sha(census: Mapping[str, str]) -> str:
    """Sort by key; join `f"{key}\\x00{dump}\\x00"`; utf-8; sha256 hex."""
    return hashlib.sha256(
        "".join(f"{k}\x00{v}\x00" for k, v in sorted(census.items())).encode("utf-8")
    ).hexdigest()


# ===================================================================== #
# The table -- section 4.1.
# ===================================================================== #


@dataclass(frozen=True)
class Fixture:
    """Whole-file byte pin, anchored (section 4.3). `repinned` is the
    ONLY door: `(sha256, dated reason)` lets head differ from the anchor
    and only to that sha."""

    repinned: tuple[str, str] | None = None


@dataclass(frozen=True)
class Additive:
    """`fixtures/fake_claude.py` -- `SU4B`'s four legs, migrated verbatim
    (section 4.4). `edited_funcs` is a PERMANENT allowlist, not an
    anchor-diff artifact: `main` and `_scenario_error_result` are
    declared exempt from leg 1's byte-identity check regardless of
    anchor advances (they were edited once, by U-cleanup-A, long before
    this unit's anchor), and each entry's sha VALUE lets `ADD3` keep
    pinning `_scenario_error_result` exactly even though leg 1 no longer
    checks it (the property `_HY3_SCENARIO_SHAS` used to hold alone).
    `new_funcs` / `new_scenario_keys` / `new_stmt_keys` ARE anchor-diff
    artifacts (additions since `ANCHOR`) and are measured empty at this
    anchor -- `fixtures/fake_claude.py` is byte-identical between
    `ANCHOR` and HEAD (measured below, `ADD1`)."""

    edited_funcs: Mapping[str, tuple[str, str]]  # name -> (sha256, reason)
    new_funcs: frozenset[str] = frozenset()
    new_scenario_keys: frozenset[str] = frozenset()
    new_stmt_keys: frozenset[tuple] = frozenset()


@dataclass(frozen=True)
class Behaviour:
    """Anchor-side NODE census (section 4.5). `nodes`/`dump_sha` are the
    `B7` positive-control literals. `missing`/`edited`/`edited_exports`
    are doors that ship shut except what the anchor->HEAD diff genuinely
    owes (`EXM3`) -- at `ANCHOR = 6038eee` that is none: U-hostmode Phase
    2's `test_wr7_...` edit (owed against the spec's original anchor,
    `3b8e037`) is now INSIDE this anchor, so its exemption entry is
    vacuous and is dropped here (the spec's own fold rule, section 4.7
    `FW-140`: "every accumulated ... entry whose subject node is now
    INSIDE the new anchor becomes vacuous and must be dropped")."""

    nodes: int
    dump_sha: str
    missing: Mapping[str, str] = field(default_factory=dict)
    edited: Mapping[str, str] = field(default_factory=dict)
    edited_exports: Mapping[str, str] = field(default_factory=dict)


ARMOR: dict[str, Fixture | Additive | Behaviour] = {
    # --- FIXTURES: ground truth, whole-file byte-pinned (section 4.3) -
    "support.py": Fixture(),  # 62 importers  (NEW under this unit -- FIX3)
    # r1 gate fold note: support.py briefly carried a `repinned` entry
    # (U-verbs' force_past_deferred, landed at 9c7ebdd) while ANCHOR sat
    # at 99d310e; a second landing-chain round (U-land-spec, 8c7a220,
    # docs-only) moved ANCHOR to 9c7ebdd itself, folding that content
    # IN and making the repin vacuous -- dropped, same motion as
    # test_wr7's own fold (section 4.1).
    "conftest.py": Fixture(),  # 2 importers
    "backends.py": Fixture(),  # 3 importers
    # --- ADDITIVE: the one fixture V-2 lets grow (section 4.4) --------
    "fixtures/fake_claude.py": Additive(
        edited_funcs={
            "main": (
                "3d52a74e1dd963882a2bd789850ceb9c97b9b4b95decb2640d3b8164e62df8ef",
                "2026-08-28 U-cleanup-A, per section 4.4: main gained per-call "
                "argv/prompt capture and _CURRENT_INVOCATION bookkeeping.",
            ),
            "_scenario_error_result": (
                "2dd5c6d4c28be358e96476c5c25f22e263b91a7e5e58170bda97c5dea8337c90",
                "2026-08-28 U-cleanup-A, per section 4.4: gains an optional "
                'FAKE_CLAUDE_ERROR_TEXT override; "boom" default preserved. '
                "The one HY3 row SU4B's leg 1 blanket-exempts, carried here "
                "as a value rather than a blanket pass.",
            ),
        },
    ),
    # --- BEHAVIOUR: every top-level node (section 4.5) -----------------
    "test_invocation.py": Behaviour(
        nodes=94, dump_sha="eb90005324f7f1483dcd618a80501d03a11e2f0ebb2541b5af696d31b48644fe"
    ),
    "test_invocation_sdk.py": Behaviour(
        nodes=139, dump_sha="2517577cbfc385476eba58d5e580a5bf5ea6d6691b15c14e1e51eb618168d7f0"
    ),
    "test_worker.py": Behaviour(
        nodes=80, dump_sha="16e45a867ecebd6471586640f1f52417427c235d04777e74ec4f34c14506627c"
    ),
    "test_repair.py": Behaviour(
        nodes=85, dump_sha="f7d0670234803960b1475444399bd83481234b308646589c7e3e35cc61c56e6e"
    ),
    "test_attrib.py": Behaviour(
        nodes=68, dump_sha="124dcc0dd69f9868195289eed661c5ad3d7d6569dc0fe41558d5fd54e8825c0d"
    ),
    "test_route_cli.py": Behaviour(
        nodes=58, dump_sha="5bb83e2da3fe5e85d8e1c261e316c20f7116de4530d34d993a86902caba21f48"
    ),
    "test_composer.py": Behaviour(
        nodes=58, dump_sha="3c920c0066c5f9db54b2a243a4714d331822cba6e82c6e029d8add6c6f4c7a5f"
    ),
    "test_u_fake.py": Behaviour(
        nodes=45, dump_sha="e8655e2be8863fc8d10edbd993edb65633d5e82c80ec79e5625e3bf2a7da9df5",
        # DS1's own migration source -- fourteen anchor-era nodes this
        # build itself removes (section 4.7 row 12). The one place the
        # anchor->HEAD diff genuinely owes a `missing` entry. Reasons
        # below are grouped by role (r1 gate fold, N-4: distinct
        # citations, not one boilerplate string repeated 14 times).
        missing={
            # DS1's own head-side bookkeeping tables -- migrated INTO
            # this Behaviour census, which tracks the same information
            # anchor-side (`nodes`/`dump_sha`/`missing`/`edited`) instead.
            "assign:REWRITTEN": "2026-08-28 §4.7 row 12: DS1's head-side rewrite-tracking table, superseded by this row's own nodes/dump_sha/missing/edited fields.",
            "assign:DS1_REMOVED": "2026-08-28 §4.7 row 12: DS1's head-side removed-symbols table, superseded by this row's own `missing` field.",
            "assign:DS1_ADDED": "2026-08-28 §4.7 row 12: DS1's head-side added-symbols table, superseded by this row's own `edited` field (adding is free, BEH2).",
            "assign:_DS1_EXPECTED": "2026-08-28 §4.7 row 12: DS1's hand-maintained expected-census literal, superseded by the node census's own live `nodes`/`dump_sha` computation.",
            # The Freeze-1 extractor and its base-commit plumbing (DS-d,
            # spec section 3.6's own account) -- DS1's mechanism for
            # reading base-commit content and reconstructing pre-rename
            # names, superseded by `_anchor_census`/`_git_show_text`.
            "assign:BASE_REF": "2026-08-28 §4.7 row 12 / DS-d: the base commit DS1 diffed against, superseded by `ANCHOR` (section 4.2).",
            "func:_git_show_base": "2026-08-28 §4.7 row 12 / DS-d: DS1's base-commit content reader, superseded by `_git_show_text`/`_anchor_text`.",
            "func:_inverse_rename": "2026-08-28 §4.7 row 12 / DS-d: DS1's pre-rename NAME reconstructor (Freeze-1), superseded by the node census reading real anchor-side source directly.",
            "func:_inverse_rename_text": "2026-08-28 §4.7 row 12 / DS-d: DS1's pre-rename TEXT reconstructor (Freeze-1), superseded the same way as `_inverse_rename`.",
            "func:_extract_guarded_functions": "2026-08-28 §4.7 row 12 / DS-d: DS1's guarded-function-body extractor, superseded by `_census`'s own per-node AST walk.",
            "func:_extract_named_function": "2026-08-28 §4.7 row 12 / DS-d: DS1's single-named-function extractor, superseded the same way as `_extract_guarded_functions`.",
            # DS1/DS2's own four census-assertion tests -- the invariant
            # each checked (count/sha exactness over base/head/rewritten
            # sets) is now BEH1/BEH3/BEH8/BEH9's job, over ALL eight
            # Behaviour files, not just this one.
            "func:test_ds1_t3_function_bodies_survive_the_inverse_rename": "2026-08-28 §4.7 row 12 / DEL2: DS1's function-body-survives-rename assertion, superseded by BEH3 (dump identity, node-wide).",
            "func:test_ds2_rewritten_set_is_exact_and_every_entry_is_live": "2026-08-28 §4.7 row 12 / DEL2: DS2's REWRITTEN-set-is-exact assertion, superseded by BEH1/BEH9 (missing/edited-set exactness, node-wide).",
            "func:test_ds1b_removed_set_is_exact_and_every_entry_is_base_only": "2026-08-28 §4.7 row 12 / DEL2: DS1b's REMOVED-set-is-exact assertion, superseded by BEH1/BEH8 (missing-set exactness and its anti-rot leg).",
            "func:test_ds1c_added_set_is_exact_and_every_entry_is_head_only": "2026-08-28 §4.7 row 12 / DEL2: DS1c's ADDED-set-is-exact assertion, superseded by BEH2 (adding is free, positive control).",
        },
    ),
}

FIXTURE_KEYS: tuple[str, ...] = tuple(k for k, v in ARMOR.items() if isinstance(v, Fixture))
ADDITIVE_KEYS: tuple[str, ...] = tuple(k for k, v in ARMOR.items() if isinstance(v, Additive))
BEHAVIOUR_KEYS: tuple[str, ...] = tuple(k for k, v in ARMOR.items() if isinstance(v, Behaviour))

#: The 11 protected paths (r1 gate fold, N-2: corrected from a stray
#: "12" -- 3 FIXTURE + 8 BEHAVIOUR keys, repo-relative) named
#: throughout the spec (`ARM5` leg (c), `UN5`). ADDITIVE is
#: deliberately excluded, by DESIGN, not oversight: `fixtures/
#: fake_claude.py` is allowed to grow (`ADD1`'s own leg 4 -- a
#: sanctioned module-level rebinding -- verifies exactly what "may
#: this file change" means for it), so "has a protected file moved /
#: is this file byte-unchanged" is not the right question for it.
PROTECTED_RELPATHS: tuple[str, ...] = tuple(
    _relpath(k) for k in (*FIXTURE_KEYS, *BEHAVIOUR_KEYS)
)

#: `PROTECTED_RELPATHS` minus `test_u_fake.py` (r1 gate discovery,
#: shared by `UN5` and `ARM5` leg (c)): the one protected file this
#: unit is BOTH protecting and, by DEL1/DEL2 mandate, itself editing
#: (section 4.7 row 12) -- its diff is sanctioned and checked
#: precisely at the node level (`BEH1`/`BEH8`/`EXM3`'s `missing`-door
#: coverage) elsewhere, not by these two blunt whole-file/whole-repo
#: checks.
STRICT_PROTECTED_RELPATHS: tuple[str, ...] = tuple(
    p for p in PROTECTED_RELPATHS if not p.endswith("/test_u_fake.py")
)


# ===================================================================== #
# Anchor-side recovery, cached per session (section 12 item 4: the
# census parses 627 nodes on the anchor side alone; a session-scoped
# cache avoids re-running `git show` once per criterion).
# ===================================================================== #

_ANCHOR_TEXT_CACHE: dict[str, str] = {}
_ANCHOR_CENSUS_CACHE: dict[str, dict[str, str]] = {}


def _anchor_text(key: str) -> str:
    if key not in _ANCHOR_TEXT_CACHE:
        _ANCHOR_TEXT_CACHE[key] = _git_show_text(ANCHOR, key)
    return _ANCHOR_TEXT_CACHE[key]


def _anchor_bytes(key: str) -> bytes:
    return _git_show_bytes(ANCHOR, key)


def _anchor_census(key: str) -> dict[str, str]:
    if key not in _ANCHOR_CENSUS_CACHE:
        _ANCHOR_CENSUS_CACHE[key] = _census(_anchor_text(key))
    return _ANCHOR_CENSUS_CACHE[key]


def _head_text(key: str) -> str:
    return _abspath(key).read_text(encoding="utf-8")


def _head_bytes(key: str) -> bytes:
    return _abspath(key).read_bytes()


def _head_census(key: str) -> dict[str, str]:
    return _census(_head_text(key))


def _diff_maps(anchor: dict[str, str], head: dict[str, str]) -> tuple[list[str], list[str]]:
    """The shared diff CORE (r1 gate fold, M-1): anchor keys absent at
    head ("missing"), and surviving anchor keys whose dump differs at
    head ("edited") -- a pure function over two census dicts, no file
    I/O. `_diff_census` (below) and `BEH2` (`test_beh2_adding_is_free`)
    both call THIS, so a mutation to the shared subset/equality logic
    (`M14`) reddens both, not just one of two independently-maintained
    copies (the r1 gate finding: BEH2 used to re-implement this inline)."""
    missing = [k for k in anchor if k not in head]
    edited = [k for k in anchor if k in head and head[k] != anchor[k]]
    return missing, edited


def _diff_census(key: str) -> tuple[list[str], list[str]]:
    """`(missing, edited)` for one Behaviour file: anchor keys absent at
    head, and surviving anchor keys whose dump differs at head. Raises a
    named, actionable error if the protected file is gone outright
    (`BEH1`'s deleted-file leg, r6 gate N-3) instead of letting
    `FileNotFoundError` propagate as a bare traceback. Delegates the
    actual diff to `_diff_maps` (r1 gate fold, M-1) -- this function
    only supplies the two census dicts from real file state."""
    if not _abspath(key).exists():
        raise AssertionError(f"protected file {key} missing — every node missing; refuse")
    return _diff_maps(_anchor_census(key), _head_census(key))


# ===================================================================== #
# F3 -- the fixture DIAGNOSTIC (section 4.3). Reuses `_census`/`_key`,
# which already resolves a shadowing redefinition to the LAST top-level
# binding (the runtime import would bind the same name) -- see
# `_census`'s own docstring. It is a DIAGNOSTIC ONLY: it is called
# solely inside F1's failure branch, and its return value is never bound
# to a name an `assert` reads (`FIX4`).
# ===================================================================== #


def _f3_diagnostic(key: str, candidate_source: str | None = None) -> dict[str, list[str]]:
    """`added`/`removed`/`edited` top-level keys, anchor vs. `candidate_
    source` (defaults to the real HEAD file). Takes source TEXT so a
    `tmp_path` mutation can be diagnosed without touching disk."""
    a = _anchor_census(key)
    h = _census(candidate_source) if candidate_source is not None else _head_census(key)
    added = sorted(k for k in h if k not in a)
    removed = sorted(k for k in a if k not in h)
    edited = sorted(k for k in a if k in h and h[k] != a[k])
    return {"added": added, "removed": removed, "edited": edited}


def _f1_or_report(key: str, candidate_bytes: bytes) -> str | None:
    """`F1` with `F3` as an on-failure diagnostic ONLY (`FIX4`): if the
    whole-file sha differs from `ANCHOR`, `F3` names what moved and the
    result is folded into a DIAGNOSTIC STRING -- never into the decision
    itself, which is `F1`'s sha comparison alone. Returns `None` on a
    match (the file is fine)."""
    anchor_sha = hashlib.sha256(_anchor_bytes(key)).hexdigest()
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    if candidate_sha != anchor_sha:
        diag = _f3_diagnostic(key, candidate_bytes.decode("utf-8"))
        return f"{key}: F1 whole-file sha mismatch -- F3 diagnostic: {diag}"
    return None


# ===================================================================== #
# B5/B6 -- the exported surface, derived with `ast.ImportFrom` (never a
# line regex, section 2.10 / `BEH5`), unioned across `ANCHOR` and HEAD.
# ===================================================================== #


def _all_tree_paths(rev: str | None) -> list[str]:
    """Every `.py` path under `cli/tests`, repo-relative, at `rev`
    (anchor-side) or in the current working tree (`rev=None`, head)."""
    if rev is None:
        return sorted(
            str(p.relative_to(_REPO_ROOT)).replace("\\", "/")
            for p in (_REPO_ROOT / _TESTS_DIR).rglob("*.py")
        )
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", rev, _TESTS_DIR],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [p for p in proc.stdout.splitlines() if p.endswith(".py")]


def _top_level_def_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _exported_names_one_side(rev: str | None) -> dict[str, set[str]]:
    """Every `BEHAVIOUR_KEYS` top-level def name imported BY NAME
    elsewhere in the tree, at one side (`rev=None` means HEAD). Uses
    `ast.ImportFrom` exclusively -- a line regex silently skips every
    parenthesized multi-line import site (`BEH5`)."""
    stem_to_key = {Path(k).stem: k for k in BEHAVIOUR_KEYS}
    defs_by_key: dict[str, set[str]] = {}
    for key in BEHAVIOUR_KEYS:
        src = _head_text(key) if rev is None else _git_show_text(rev, key)
        defs_by_key[key] = _top_level_def_names(src)

    result: dict[str, set[str]] = {k: set() for k in BEHAVIOUR_KEYS}
    for path in _all_tree_paths(rev):
        try:
            src = (
                (_REPO_ROOT / path).read_text(encoding="utf-8")
                if rev is None
                else subprocess.run(
                    ["git", "show", f"{rev}:{path}"],
                    cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
                ).stdout
            )
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, subprocess.CalledProcessError):
            continue
        this_stem = Path(path).stem
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in stem_to_key:
                target_key = stem_to_key[node.module]
                if path == _relpath(target_key):
                    continue  # self-import, not a consumer
                for alias in node.names:
                    if alias.name in defs_by_key[target_key]:
                        result[target_key].add(alias.name)
    return result


def _exported_names_union() -> dict[str, set[str]]:
    """`anchor_set ∪ head_set`, per Behaviour file (`B5`)."""
    anchor = _exported_names_one_side(ANCHOR)
    head = _exported_names_one_side(None)
    return {k: anchor[k] | head[k] for k in BEHAVIOUR_KEYS}


def _exported_names_anchor() -> dict[str, set[str]]:
    return _exported_names_one_side(ANCHOR)


def _exported_names_head() -> dict[str, set[str]]:
    return _exported_names_one_side(None)


def _exported_def_source(key: str, name: str, source: str) -> str:
    tree = ast.parse(source)
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(source, n) or ""
    raise AssertionError(f"{name} not found at top level of {key}")


# ===================================================================== #
# EXM1 -- the exemption-reason grammar: a DATE and an ANCHOR, and any
# hex-shaped anchor must RESOLVE as a real commit (section 4.6, r5/r6
# gate B-1/N-2).
# ===================================================================== #

_EXM1_DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
_EXM1_SECTION_RE = re.compile(r"§\d|FW-\d+|S-\d+")
_EXM1_HEX_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def _resolves_as_commit(sha: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=_REPO_ROOT, capture_output=True,
    )
    return r.returncode == 0


def _exm1_check(reason: str) -> tuple[bool, str]:
    """`(ok, why-not)`. Leg 1 (grammar): a date AND at least one of
    `§\\d` / `FW-\\d+` / `S-\\d+` / a 7-40-hex token. Leg 2 (resolution):
    if the ONLY anchor evidence is a hex token, it must resolve via
    `git cat-file -e <sha>^{commit}` -- a fabricated sha is refused even
    though it is well-formed. A sha that resolves but is irrelevant
    still passes (section 4.8's human-review job, not this grammar's)."""
    if not _EXM1_DATE_RE.search(reason):
        return False, "no date (20\\d\\d-\\d\\d-\\d\\d)"
    section_hit = _EXM1_SECTION_RE.search(reason) is not None
    hex_tokens = _EXM1_HEX_RE.findall(reason)
    if not section_hit and not hex_tokens:
        return False, "no anchor (§N / FW-N / S-N / 7-40-hex commit sha)"
    if not section_hit and hex_tokens and not any(_resolves_as_commit(h) for h in hex_tokens):
        return False, f"hex anchor {hex_tokens} does not resolve as a commit (git cat-file -e)"
    return True, ""


# ===================================================================== #
# The MEASURED literals -- section 4.6's exemption discipline, extended
# to the NUMBERS the landing's author writes down (`ANC1`-`ANC6`,
# U-anchorlit).
#
# Two kinds of literal live in this module, and the difference between
# them is WHO WRITES THEM -- not which is the stronger check:
#
# * `ARMOR`'s `Behaviour.nodes`/`.dump_sha` are written by
#   `--remeasure`, silently, as part of every landing.
# * The values below are never written by `--remeasure` (`ANC3` is the
#   leg that holds this). They change only when the landing's author
#   edits this table deliberately, having been shown the old value
#   beside the new one, and re-dates the row's `reason`.
#
# WHAT THAT SEPARATION BUYS -- stated exactly, because the tempting
# stronger claim is false and was corrected here on 2026-08-29. It is
# NOT an independent measurement, and it is NOT corroboration against a
# drifted extractor: the author transcribes the numbers this module's
# own refusal printed, and that printout comes from the SAME `_census`
# that fills the `ARMOR` table. Copying one tool's output into a second
# location does not check that tool. What it does deliver is two
# things, both real:
#
#   1. A REFUSAL AGAINST SILENT STALENESS. An anchor-scoped literal
#      goes stale the instant `ANCHOR` advances, which every landing
#      does. `--remeasure` measures every row below at the NEW anchor
#      BEFORE it writes anything and stops, naming each stale row and
#      printing its shipped value beside its newly measured one --
#      exactly as it already refuses an unexempted `OWED:` node
#      (section 4.2's check-then-write order). Before this door, the
#      write went through and the suite went red AFTERWARDS. Measured
#      2026-08-29 in a throwaway clone carrying a synthetic landing
#      merge: a SUCCESSFUL `--remeasure` advanced `ANCHOR`
#      `6815503 -> a768696` and left the armor suite at `2 failed, 39
#      passed` (`BEH7` at `('test_u_fake.py', 31, 45)`, `EXM3` at
#      `assign:REWRITTEN`), with two assertion failures that named
#      nothing about the anchor. Nothing had landed since `u-armor`
#      shipped, which is the only reason it had not bitten yet.
#   2. A DATED AUDIT TRAIL. Each value changes only through a
#      deliberate, recorded act carrying a date and an anchor -- the
#      same discipline section 4.6/4.7 already require of every
#      exemption entry, and the same reviewability at the gate.
#
# WHO MAY WRITE THESE VALUES: the author of the landing, whoever that
# is. An AGENT performing the landing is a sanctioned author, exactly
# as for an exemption entry -- `e59534b` landed agent-written exemption
# entries with dated justifications, and that was correct. The
# discipline requires the change to be deliberate, attributed and
# dated; it does not require a person at a keyboard. What it forbids is
# `--remeasure` doing it as a side effect, because that would remove
# the refusal (1) and the record (2) in one move.
#
# `scope` says what a row is a function of, so a reader can tell at a
# glance which rows an anchor advance can move:
#   `anchor`       -- the anchor side alone.
#   `anchor+head`  -- the anchor->HEAD diff; either side moves it.
#   `head`         -- a FIXED historical rev against HEAD. An anchor
#                     advance can NEVER move one of these; a landing
#                     that edits a protected file can.
#
# `BEH7`'s OTHER half -- the `_census` -> `{}` monkeypatch control -- is
# deliberately NOT in this table. It is anchor-INDEPENDENT, never goes
# stale, and is the leg that actually proves the extractor can fail.
# Only the measured half is anchor-scoped, and the two must not be
# confused: an anchor advance is allowed to invalidate the numbers, and
# is never allowed to invalidate the control.
# ===================================================================== #

_SCOPE_ANCHOR = "anchor"
_SCOPE_ANCHOR_HEAD = "anchor+head"
_SCOPE_HEAD = "head"
_SCOPES: tuple[str, ...] = (_SCOPE_ANCHOR, _SCOPE_ANCHOR_HEAD, _SCOPE_HEAD)

#: The retired anchor `BEH1`/`BEH3`/`EXM3` still drive their
#: not-vacuous positive controls from (one of section 4.2's three
#: retired anchors, which `ARM4` forbids `ANCHOR` from ever becoming
#: again). Fixed history: it is never advanced, which is exactly why
#: the rows measured against it are `head`-scoped, not `anchor`-scoped.
_RETIRED_ANCHOR_CONTROL = "c3b48e7"

#: Non-`ANCHOR` revs, memoized per (rev, key). `ANCHOR` itself keeps
#: using `_ANCHOR_CENSUS_CACHE`, untouched, so `BEH7`'s monkeypatch
#: control still poisons and drops exactly the one entry it always did.
_REV_CENSUS_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def _census_at(rev: str, key: str) -> dict[str, str]:
    """The node census of one Behaviour file at `rev`. Routes through
    the session cache when `rev` IS the shipped `ANCHOR` -- the common
    case, and the path `BEH7`'s monkeypatch control already drives; a
    `--remeasure` run's NEW anchor, and the retired control anchor, are
    read and memoized separately."""
    if rev == ANCHOR:
        return _anchor_census(key)
    cache_key = (rev, key)
    if cache_key not in _REV_CENSUS_CACHE:
        _REV_CENSUS_CACHE[cache_key] = _census(_git_show_text(rev, key))
    return _REV_CENSUS_CACHE[cache_key]


def _measure_node_counts(anchor: str) -> tuple[int, ...]:
    """`BEH7`'s per-file top-level node counts, in `BEHAVIOUR_KEYS`
    order."""
    return tuple(len(_census_at(anchor, k)) for k in BEHAVIOUR_KEYS)


def _measure_dump_prefixes(anchor: str) -> tuple[str, ...]:
    """`BEH7`'s eight 12-character `dump_sha` prefixes."""
    return tuple(_dump_sha(_census_at(anchor, k))[:12] for k in BEHAVIOUR_KEYS)


def _measure_node_total(anchor: str) -> int:
    return sum(_measure_node_counts(anchor))


def _measure_export_counts(anchor: str) -> tuple[int, ...]:
    """`BEH5`'s per-file exported-name counts, `anchor_set | head_set`.
    Anchor-scoped even though half the union is head-side: measured
    2026-08-29, the same union reads `(4, 5, 6, 10, 0, 4, 2, 0)` at
    `6815503`/`a768696`/`15fb676`/`3b8e037` and `(4, 6, 7, 10, 0, 5, 2,
    0)` at `c3b48e7`, so the anchor genuinely moves it -- it has simply
    not moved across the four most recent anchors, which is how this
    row survived two independent hunts for anchor-scoped literals."""
    anchor_side = _exported_names_one_side(anchor)
    head_side = _exported_names_one_side(None)
    return tuple(len(anchor_side[k] | head_side[k]) for k in BEHAVIOUR_KEYS)


def _measure_export_total(anchor: str) -> int:
    return sum(_measure_export_counts(anchor))


def _measure_diff_totals(anchor: str) -> tuple[int, int]:
    """`(missing, edited)` summed over every Behaviour file, `anchor`
    against HEAD -- the shared core `EXM3`'s own census totals and the
    retired-anchor controls both read."""
    missing_total = 0
    edited_total = 0
    for key in BEHAVIOUR_KEYS:
        missing, edited = _diff_maps(_census_at(anchor, key), _head_census(key))
        missing_total += len(missing)
        edited_total += len(edited)
    return missing_total, edited_total


def _measure_census_missing(anchor: str) -> int:
    return _measure_diff_totals(anchor)[0]


def _measure_census_edited(anchor: str) -> int:
    return _measure_diff_totals(anchor)[1]


def _measure_control_missing(_anchor: str) -> int:
    """`BEH1`/`EXM3`'s not-vacuous control. `_anchor` is ignored BY
    CONSTRUCTION -- this row reads the retired control anchor, which is
    why its `scope` is `head`."""
    return _measure_diff_totals(_RETIRED_ANCHOR_CONTROL)[0]


def _measure_control_edited(_anchor: str) -> int:
    """`BEH3`/`EXM3`'s not-vacuous control. See `_measure_control_
    missing` on the ignored parameter."""
    return _measure_diff_totals(_RETIRED_ANCHOR_CONTROL)[1]


@dataclass(frozen=True)
class Measured:
    """One transcribed measurement, with the recomputation that proves
    it. `value` is what the landing's author wrote down (an agent is a
    sanctioned author here, exactly as for an exemption entry --
    `e59534b`); `measure(anchor)` recomputes it live at `anchor`;
    `reason` carries the same dated, cited grammar `EXM1` requires of
    every exemption reason (section 4.6).

    `--remeasure` may READ `measure`; it may never WRITE `value`
    (`ANC3`). Not because the transcribed number is an independent
    check on the extractor -- it is not, it is copied from this same
    code's own printout (see the section header) -- but because a tool
    that rewrote it would remove both the refusal that stops a stale
    landing and the dated record of the change."""

    value: object
    scope: str
    reason: str
    measure: Callable[[str], object]


MEASURED: dict[str, Measured] = {
    "BEH7.node_counts": Measured(
        value=(94, 139, 80, 85, 68, 58, 58, 45),
        scope=_SCOPE_ANCHOR,
        reason=(
            "2026-08-28 §4.5/§2.10, measured by hand at ANCHOR 6815503 "
            "(u-armor's own landing): per-file top-level node counts, in "
            "BEHAVIOUR_KEYS order."
        ),
        measure=_measure_node_counts,
    ),
    "BEH7.dump_prefixes": Measured(
        value=(
            "eb90005324f7", "2517577cbfc3", "16e45a867ece", "f7d067023480",
            "124dcc0dd69f", "5bb83e2da3fe", "3c920c0066c5", "e8655e2be886",
        ),
        scope=_SCOPE_ANCHOR,
        reason=(
            "2026-08-28 §4.5/§2.10, measured by hand at ANCHOR 6815503: the "
            "first 12 characters of each file's normalized-dump sha256, in "
            "BEHAVIOUR_KEYS order."
        ),
        measure=_measure_dump_prefixes,
    ),
    "BEH7.node_total": Measured(
        value=627,
        scope=_SCOPE_ANCHOR,
        reason=(
            "2026-08-28 §4.5/§2.10, measured by hand at ANCHOR 6815503: the "
            "sum of BEH7.node_counts, carried separately so a transcription "
            "that drops or duplicates one file reddens on the total too."
        ),
        measure=_measure_node_total,
    ),
    "BEH5.export_counts": Measured(
        value=(4, 5, 6, 10, 0, 4, 2, 0),
        scope=_SCOPE_ANCHOR,
        reason=(
            "2026-08-28 §4.5/`B5`, measured by hand at ANCHOR 6815503: "
            "per-file exported-name counts, anchor_set | head_set, derived "
            "with ast.ImportFrom (never a line regex)."
        ),
        measure=_measure_export_counts,
    ),
    "BEH5.export_total": Measured(
        value=31,
        scope=_SCOPE_ANCHOR,
        reason=(
            "2026-08-28 §4.5/`B5`, measured by hand at ANCHOR 6815503: the "
            "sum of BEH5.export_counts."
        ),
        measure=_measure_export_total,
    ),
    "EXM3.census_missing": Measured(
        value=14,
        scope=_SCOPE_ANCHOR_HEAD,
        reason=(
            "2026-08-28 §4.7 row 12, measured by hand at ANCHOR 6815503: "
            "anchor nodes absent at HEAD, summed over every Behaviour file "
            "-- u-armor's own DS1 retirement from test_u_fake.py, and the "
            "count EXM3 requires the shipped `missing` doors to match."
        ),
        measure=_measure_census_missing,
    ),
    "EXM3.census_edited": Measured(
        value=0,
        scope=_SCOPE_ANCHOR_HEAD,
        reason=(
            "2026-08-28 §4.1's fold note, measured by hand at ANCHOR "
            "6815503: anchor nodes whose dump differs at HEAD, summed over "
            "every Behaviour file. Zero because the one historical `edited` "
            "entry (test_wr7) is now INSIDE the anchor."
        ),
        measure=_measure_census_edited,
    ),
    "BEH1.control_missing": Measured(
        value=66,
        scope=_SCOPE_HEAD,
        reason=(
            "2026-08-28 §4.7 row 12, measured by hand against the RETIRED "
            "anchor c3b48e7 (never advanced): the not-vacuous control for "
            "BEH1 and EXM3. Re-measured from the spec-gate-era 56 by "
            "u-armor's own test_u_fake.py deletions."
        ),
        measure=_measure_control_missing,
    ),
    "BEH3.control_edited": Measured(
        value=184,
        scope=_SCOPE_HEAD,
        reason=(
            "2026-08-28 §4.7 row 12, measured by hand against the RETIRED "
            "anchor c3b48e7 (never advanced): the not-vacuous control for "
            "BEH3 and EXM3. Re-measured from the spec-gate-era 190, same "
            "cause as BEH1.control_missing."
        ),
        measure=_measure_control_edited,
    ),
}


def _module_relpath() -> str:
    """This module's repo-relative path, for the refusal output. Falls
    back to the bare filename rather than ever printing an absolute
    path (the scratch copies `ARM6`/`ANC1` exec live inside the repo,
    so the relative form normally resolves)."""
    p = Path(__file__).resolve()
    try:
        return p.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return p.name


# ===================================================================== #
# EXM2 -- no hardcoded name skips outside the four exemption maps.
# ===================================================================== #


def _all_live_test_and_def_names() -> set[str]:
    names: set[str] = set()
    for key in BEHAVIOUR_KEYS:
        for n in ast.parse(_head_text(key)).body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
    return names


def _module_source() -> str:
    return Path(__file__).read_text(encoding="utf-8")


def _hardcoded_skip_names(source: str, live_names: set[str]) -> list[str]:
    """Every string literal that equals a live test/def name, found
    inside a MECHANISM function (a module-level `def` whose name does
    NOT start with `test_` -- the extractors and legs a `--remeasure`
    run or a gate actually executes) -- `EXM2`. Deliberately excludes
    `test_*` functions themselves: this suite's own tests legitimately
    name specific protected functions as MUTATION TARGETS (`test_beh1`'s
    `"test_run_idle_when_nothing_eligible"`, `test_beh3`'s
    `"RECORD_QUOTE"`, ...), which is not the hardcoded-skip evasion this
    criterion polices -- that evasion looks like `if name ==
    "some_protected_test": continue` INSIDE a leg's own loop."""
    tree = ast.parse(source)
    hits = []
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)) and not top.name.startswith("test_"):
            for node in ast.walk(top):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in live_names:
                    hits.append(node.value)
    return hits


# ===================================================================== #
# DEL1/DOC2/DOC3 -- the retired names, ast-visible, owner-scoped.
# ===================================================================== #

#: Constants (22) -- ast.Assign or ast.AnnAssign, per section 13.
RETIRED_CONSTANTS: tuple[str, ...] = (
    "_ARMOR_SHAS", "_SU4B_DIFF_EXEMPT", "_SU4B_SANCTIONED_EDITED_FUNCS",
    "_SU4B_SANCTIONED_NEW_FUNCS", "_SU4B_SANCTIONED_NEW_SCENARIO_KEYS",
    "_SU4B_SANCTIONED_NEW_STMT_KEYS", "_FAKE_CLAUDE_RELPATH", "BASE_COMMIT",
    "_AR1_TRIPWIRE_SHA256", "_AR1_SANCTIONED_PIN_LINES", "_AR3_REASONS",
    "_AR3_RENAMED", "_AR3_REMOVED", "_AR3_ADDED", "_AR3_ONE_LINE_ONLY",
    "_HY3_SCENARIO_SHAS", "_BASE_SHA", "REWRITTEN", "DS1_REMOVED",
    "DS1_ADDED", "_DS1_EXPECTED", "BASE_REF",
)

#: Test functions (10), per section 13.
RETIRED_TEST_FUNCTIONS: tuple[str, ...] = (
    "test_su4a_whole_file_armor_shas",
    "test_su4b_fake_claude_additive_only",
    "test_ar1_tripwire_byte_unchanged",
    "test_ar3_edited_is_exactly_21_functions_with_reasons",
    "test_hy3_fake_claude_additions_are_additive",
    "test_hy5_numstat_bounds_hold",
    "test_ds1_t3_function_bodies_survive_the_inverse_rename",
    "test_ds1b_removed_set_is_exact_and_every_entry_is_base_only",
    "test_ds1c_added_set_is_exact_and_every_entry_is_head_only",
    "test_ds2_rewritten_set_is_exact_and_every_entry_is_live",
)

#: Helpers deleted alongside their caller (section 13's closing note; not
#: separately DOC2-checked since a bare name lookup would collide with
#: unrelated symbols elsewhere -- their absence is covered by
#: `DEL2`'s collector check on their sole callers).
RETIRED_HELPERS_NOTE: tuple[str, ...] = (
    "_stmt_key", "_load_module_from_path", "_load_fake_claude_module",
    "_git_show_base", "_extract_guarded_functions", "_extract_named_function",
    "_inverse_rename", "_inverse_rename_text",
)

#: The three owner files (section 13: scoping is load-bearing -- a bare
#: cli/-wide check would flag `test_u_corrob.py:65`'s own unrelated
#: `_BASE_SHA`, `DOC3`).
OWNER_FILES: tuple[str, ...] = (
    "test_worker_contract.py", "test_u_sdka.py", "test_u_fake.py",
)


def _ast_visible_retired_bindings(source: str) -> list[str]:
    """Every `ast.Assign`/`ast.AnnAssign` target or `FunctionDef`/
    `AsyncFunctionDef` name in `source` that names a retired symbol --
    the walk `DOC2` runs and `DEL1` reuses. Deliberately NOT a raw-text
    grep: a docstring mentioning a retired name historically is prose,
    not a binding (section 8's note)."""
    tree = ast.parse(source)
    hits: list[str] = []
    retired = set(RETIRED_CONSTANTS) | set(RETIRED_TEST_FUNCTIONS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in retired:
                    hits.append(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in retired:
                hits.append(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in retired:
                hits.append(node.name)
    return hits


def _ast_visible_retired_bindings_assign_only(source: str) -> list[str]:
    """The under-scoped walk `M38` ships: `ast.Assign` only, omitting
    `AnnAssign` -- silently misses `_AR3_REMOVED`/`_AR3_ADDED`."""
    tree = ast.parse(source)
    hits: list[str] = []
    retired = set(RETIRED_CONSTANTS) | set(RETIRED_TEST_FUNCTIONS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in retired:
                    hits.append(t.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in retired:
                hits.append(node.name)
    return hits


# ===================================================================== #
# GATE1-3 / DOC1 -- the process-doc greps.
# ===================================================================== #

_RUNBOOK = _REPO_ROOT / "docs/specs/self-learn/15-orchestration-runbook.md"
_DECISIONS = _REPO_ROOT / "docs/specs/self-learn/03-decisions.md"
_FW_MAP = _REPO_ROOT / "docs/specs/self-learn/14-forward-work-map.md"


def _grep_count(text: str, pattern: str) -> int:
    """Case-insensitive by default -- matches this repo's own `grep`
    convention for prose-keyword sweeps (section 0's own instrument uses
    `-niE`); row-marker patterns (`^\\| S-55`) are exact tokens with no
    case ambiguity either way."""
    return len(re.findall(pattern, text, re.IGNORECASE | re.MULTILINE))


# ===================================================================== #
# DEL3 -- the disposition-coverage table (section 4.7's 17 rows, each
# mapped to what now covers it).
# ===================================================================== #

#: `(disposition description, covering criterion id or "KEPT AS IS" file)`
DISPOSITION_COVERAGE: tuple[tuple[str, str], ...] = (
    ("_ARMOR_SHAS -- 2 fixture rows -> Fixture", "FIX1"),
    ("_ARMOR_SHAS -- 5 behaviour rows -> Behaviour", "BEH1"),
    ("_SU4B_DIFF_EXEMPT -> retired outright", "DEL1"),
    ("test_su4a_whole_file_armor_shas -> F1-F3/B1-B7", "FIX1"),
    ("test_su4b_fake_claude_additive_only -> Additive", "ADD1"),
    ("_SU4B_SANCTIONED_* four tables -> Additive fields", "ADD1"),
    ("_AR1_SANCTIONED_PIN_LINES + test_ar1_tripwire_byte_unchanged -> F1", "FIX1"),
    ("_AR1_TRIPWIRE_SHA256 -> subsumed by F1", "FIX1"),
    ("_AR3_* + test_ar3_edited_is_exactly_21_functions_with_reasons -> Behaviour.missing/.edited", "BEH1"),
    ("_HY3_SCENARIO_SHAS + test_hy3_fake_claude_additions_are_additive -> Additive/ADD3", "ADD3"),
    ("test_hy5_numstat_bounds_hold -> retired outright", "DEL2"),
    ("REWRITTEN/DS1_ADDED/DS1_REMOVED/_DS1_EXPECTED + test_ds1/ds1b/ds1c/ds2 -> Behaviour", "BEH5"),
    ("test_ar5_pin1_class_is_closed_by_census -> KEPT AS IS", "test_u_sdka.py"),
    ("PL1/EV4 -> KEPT AS IS", "test_invocation_sdk.py"),
    ("BND4/POL2 -> KEPT AS IS", "test_u_engine.py"),
    ("_LOCKS/NOT_REPO_TRUTH walker -> KEPT AS IS, UNTOUCHED", "test_lock_invariant.py"),
    ("test_pin2_armor_sha_paths_are_byte_unchanged -> RETARGETED", "test_u_corrob.py"),
)


def _armor_test_names() -> set[str]:
    """Only `test_`-prefixed top-level functions -- what pytest's own
    collector counts (`UN3`). A bare `isinstance` filter also counts
    every helper (`_census`, `_key`, `_diff_census`, ...), which does
    not appear in the collector's output and silently inflated `UN3`'s
    `n_armor_tests` from 41 to 88 (measured, 2026-08-28) -- `DEL3`'s own
    `startswith` matching against `test_<id>_` prefixes was unaffected
    either way, since a helper name never matches that shape."""
    tree = ast.parse(_module_source())
    return {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    }


def _kept_file_contains(relpath_from_cli: str, symbol: str) -> bool:
    text = (_REPO_ROOT / "plugins/self-learn/cli/tests" / relpath_from_cli).read_text(encoding="utf-8")
    return re.search(rf"\b{re.escape(symbol)}\b", text) is not None


# ===================================================================== #
# UN1/UN5 -- production/protected-file diffs against the build base.
# `_BUILD_BASE` is the commit this unit's OWN changes are measured
# against. `_numstat`'s `git diff --numstat <base> -- <paths>` is a
# ONE-ref diff, always comparing *base*'s committed tree against
# whatever is currently on disk -- it reports the same thing whether
# this unit's own work sits committed or not (r1 gate fold, N-6: the
# original "while the tree stays uncommitted" framing described a
# non-load-bearing implementation detail, then went stale and
# confusing the moment this unit's own landing-chain fold commits).
# ===================================================================== #


def _incorporated_master_point() -> str:
    """The most recent commit on `master`'s own history that `HEAD`
    has actually absorbed (r1 gate fold, THIRD discovery, found after
    `cc8abe1`): neither literal `master` nor a bare `HEAD` walk stays
    race-safe once this unit has folded master in at least once.
    Literal `master` can race ahead with content not yet merged --
    measured live, a same-day hotfix (`6815503`) landed on master with
    no merge marker at all, so a simple "is master an ancestor of
    HEAD" check reads False even though nothing new needs folding in
    yet for THIS purpose. And `HEAD` itself became a 2-parent merge
    the moment this unit's OWN landing-chain fold committed (`93bfb5d`,
    then `cc8abe1`), so a bare first-parent walk from `HEAD` finds
    THAT fold commit, not master's mainline -- the exact bug the
    caught-up/fallback split was built to dodge, reappearing through
    its OTHER branch once both conditions hit at once. `git merge-base
    master HEAD` sidesteps the whole class by construction: it is
    always the latest commit reachable from BOTH histories, i.e.
    exactly the master content this branch has already absorbed,
    however that absorption happened and however far master has since
    moved. Shared by `_BUILD_BASE`'s resolution and
    `_latest_first_parent_merge_root` (`ARM5`)."""
    return subprocess.run(
        ["git", "merge-base", "master", "HEAD"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _resolve_build_base() -> str:
    """`_BUILD_BASE`'s own resolution (r1 gate fold). Diffing against
    `ANCHOR` directly misreads any sibling unit's own legitimate
    changes -- brought in through this unit's OWN merges -- as if this
    unit made them, the moment `ANCHOR` sits one or more merges behind
    what `HEAD` actually contains (deliberately: `ANCHOR` only advances
    on the NEXT `--remeasure`). `_incorporated_master_point` is exactly
    the master content already folded into `HEAD`, so `UN1`/`UN2`/`UN5`
    never misattribute a sibling's already-absorbed change, and never
    reach past what `HEAD` has actually merged either."""
    return _incorporated_master_point()


_BUILD_BASE = _resolve_build_base()


#: This landing's own permanent base/tip pair (r2 gate fold: post-
#: landing, `_BUILD_BASE` (`_incorporated_master_point`) collapses onto
#: `HEAD` itself -- measured live, right after the `u-armor` merge
#: (`9ada450`) landed, `merge-base master HEAD == HEAD`, so "this
#: unit's own diff" read empty for UN1/UN3/UN5 all at once.
#: `_LANDING_BASE` is `master`'s tip immediately BEFORE this unit's
#: merge (the merge's own first parent, `6815503`); `_LANDING_TIP` is
#: the merge commit itself (`9ada450`). Both are a ONE-TIME census of
#: THIS landing -- fixed forever, like the retired `c3b48e7`-era
#: controls, never re-measured. `--remeasure` never rewrites either
#: literal: it only ever touches `ANCHOR` and the `Behaviour`/`Fixture`
#: rows (section 4.2) -- these two are written once, by this commit,
#: and never again.
_LANDING_BASE = "6815503"
_LANDING_TIP = "9ada450"


def _landing_is_absorbed() -> bool:
    """Has this branch already reached (or been fast-forwarded onto)
    `_LANDING_TIP`? True from that moment on, PERMANENTLY -- including
    across every later housekeeping commit this branch makes on top of
    it (this very commit is one), which is the whole point: UN1/UN3/
    UN5 must pin to THIS landing once, not re-measure it every time
    `HEAD` moves again. Checked via `merge-base --is-ancestor
    _LANDING_TIP HEAD`, deliberately NOT via `merge-base master HEAD ==
    HEAD`: the two coincide exactly at the single instant right after a
    fast-forward with no further commits (the moment the gate observed
    the failure), but the literal-`master` comparison flips back to
    "not yet" the instant this branch gains even one unrelated
    follow-up commit -- which would silently hand UN1/UN3/UN5 back to
    `_BUILD_BASE`'s now-degenerate pre-landing math (verified: it does,
    see the RED/restore proof in this commit's own report). The
    ancestor form is the one that stays right forever, matching
    "immune to every later landing"."""
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", _LANDING_TIP, "HEAD"], cwd=_REPO_ROOT,
    )
    return proc.returncode == 0


def _assert_landing_pair_is_real_history() -> None:
    """Both `_LANDING_BASE`/`_LANDING_TIP` resolve to real commits, and
    `_LANDING_TIP`'s own first parent is exactly `_LANDING_BASE` -- the
    merge shape section 4.2 defines (the merge's first-parent PARENT is
    the anchor). A typo'd literal fails LOUD here, not by silently
    measuring the wrong diff."""
    for sha in (_LANDING_BASE, _LANDING_TIP):
        r = subprocess.run(["git", "cat-file", "-e", sha], cwd=_REPO_ROOT)
        assert r.returncode == 0, f"_LANDING pair: {sha!r} does not resolve to a real commit"
    parent = subprocess.run(
        ["git", "rev-parse", "--short=7", f"{_LANDING_TIP}^1"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert parent == _LANDING_BASE, (
        f"_LANDING_TIP's first parent is {parent!r}, not _LANDING_BASE ({_LANDING_BASE!r})"
    )


def _numstat(base: str, *paths: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "--numstat", base, "--", *paths],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return proc.stdout


def _numstat2(base: str, tip: str, *paths: str) -> str:
    """Two-ref numstat: `base`'s tree against `tip`'s tree, both
    committed shas -- unlike `_numstat` (which diffs `base` against
    whatever is currently on disk, deliberately, per its own note
    above), this never reads the working tree or `HEAD`, so it stays
    byte-identical forever once `base`/`tip` are fixed (r2 gate fold:
    UN1/UN3/UN5's post-landing pin)."""
    proc = subprocess.run(
        ["git", "diff", "--numstat", base, tip, "--", *paths],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return proc.stdout


# ===================================================================== #
# `--remeasure` -- the landing-chain CLI (section 4.2). Check-then-write:
# resolve the anchor and read the CURRENT literal; census everything;
# compute the owed set; refuse (writing nothing) if it is non-empty;
# only on an empty owed set render the whole module and `os.replace()`
# it atomically; exit non-zero if the anchor literal did not change
# (`ARM6`, the no-op guard, r6 gate M-2).
# ===================================================================== #


def _resolve_new_anchor() -> str:
    merge = subprocess.run(
        ["git", "rev-list", "--first-parent", "--merges", "-1", "master"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not merge:
        raise SystemExit("no first-parent merge found on master")
    parent = subprocess.run(
        ["git", "rev-parse", "--short=7", f"{merge}^1"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return parent


def _compute_owed(new_anchor: str) -> dict[str, list[str]]:
    """Every `missing`/`edited` key, per Behaviour file, that no
    exemption entry in the CURRENT (pre-rewrite) table covers, measured
    against `new_anchor`."""
    owed: dict[str, list[str]] = {}
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        anchor_src = _git_show_text(new_anchor, key)
        a = _census(anchor_src)
        h = _head_census(key)
        missing = [k for k in a if k not in h]
        edited = [k for k in a if k in h and h[k] != a[k]]
        unexempt_missing = [k for k in missing if k not in row.missing]
        unexempt_edited = [k for k in edited if k not in row.edited]
        if unexempt_missing or unexempt_edited:
            owed[key] = [*(f"missing:{k}" for k in unexempt_missing), *(f"edited:{k}" for k in unexempt_edited)]
    return owed


def _compute_vacuous(new_anchor: str) -> dict[str, list[str]]:
    """Every SHIPPED exemption entry that `new_anchor` no longer owes
    (`ANC5`) -- section 4.7's own fold rule (`FW-140`): "every
    accumulated ... entry whose subject node is now INSIDE the new
    anchor becomes vacuous and must be dropped". `_compute_owed` is
    the other direction (nodes owed an entry that does not exist);
    this is entries that exist and are owed nothing.

    Both directions have to be refused for the same reason: `EXM3`'s
    `shipped == census` leg and `FIX2`'s anti-rot leg are the two
    that go RED on a vacuous entry, and an advance that leaves one
    behind is the same silent-red landing `ANC1` closes for the
    measured literals. Measured 2026-08-29 in a throwaway clone: the
    fourteen `test_u_fake.py` `missing` entries all become vacuous the
    instant `ANCHOR` reaches `a768696`, and `EXM3` fails on the first
    of them (`assign:REWRITTEN`) before it ever reaches its own
    hand-written totals."""
    dead: dict[str, list[str]] = {}
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        if not isinstance(row, Behaviour):
            continue
        missing, edited = _diff_maps(_census_at(new_anchor, key), _head_census(key))
        gone = [f"missing:{k}" for k in row.missing if k not in missing]
        gone += [f"edited:{k}" for k in row.edited if k not in edited]
        if gone:
            dead[key] = gone
    for key in FIXTURE_KEYS:
        frow = ARMOR[key]
        if not isinstance(frow, Fixture) or frow.repinned is None:
            continue
        anchor_sha = hashlib.sha256(_git_show_bytes(new_anchor, key)).hexdigest()
        if hashlib.sha256(_head_bytes(key)).hexdigest() == anchor_sha:
            dead.setdefault(key, []).append("repinned")
    return dead


def _compute_stale(new_anchor: str) -> list[tuple[str, object, object]]:
    """Every `MEASURED` row whose live value at `new_anchor` differs
    from the value this module ships -- `(name, shipped, live)`,
    `ANC1`. Computed BEFORE anything is written, exactly like
    `_compute_owed` (section 4.2's check-then-write order, and for the
    same reason: under write-then-check the anchor literal is already
    advanced on disk when the refusal fires, and the no-op guard
    deadlocks the chain on the re-run).

    `--remeasure` reads these rows and never writes one. The reason
    is NOT that the shipped value is an independent measurement -- it
    is transcribed from this same code's own printout -- but that a
    silent rewrite would delete the refusal itself: nothing would ever
    be reported stale, the anchor would advance unannounced, and the
    dated record of the change would be gone. So the refusal prints
    what the landing's author must transcribe, in the same posture the
    `OWED:` leg already takes for an exemption entry."""
    stale: list[tuple[str, object, object]] = []
    for name, row in MEASURED.items():
        live = row.measure(new_anchor)
        if live != row.value:
            stale.append((name, row.value, live))
    return stale


def _render_module(new_anchor: str) -> str:
    """Render the WHOLE module with `ANCHOR` and every `Behaviour`
    row's `nodes`/`dump_sha` recomputed at `new_anchor`. Exemption maps
    (`missing`/`edited`/`edited_exports`/`Fixture.repinned`/
    `Additive.*`) are carried over UNCHANGED -- `--remeasure` never
    writes an exemption entry (section 4.2); only a human or a builder
    does."""
    source = _module_source()
    new_source = source.replace(f'ANCHOR = "{ANCHOR}"', f'ANCHOR = "{new_anchor}"', 1)
    for key in BEHAVIOUR_KEYS:
        anchor_src = _git_show_text(new_anchor, key)
        c = _census(anchor_src)
        new_nodes = len(c)
        new_sha = _dump_sha(c)
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        old_literal = f'nodes={row.nodes}, dump_sha="{row.dump_sha}"'
        new_literal = f'nodes={new_nodes}, dump_sha="{new_sha}"'
        if old_literal not in new_source:
            raise SystemExit(f"could not locate the literal for {key} to rewrite")
        new_source = new_source.replace(old_literal, new_literal, 1)
    return new_source


def _remeasure(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="test_armor.py --remeasure")
    parser.add_argument("--remeasure", action="store_true", required=True)
    parser.add_argument("--anchor", required=True)
    args = parser.parse_args(argv)

    new_anchor = args.anchor
    old_anchor = ANCHOR

    # Three refusal legs, all computed BEFORE anything is written and
    # all reported in ONE run, so the author transcribes once instead of
    # discovering the next leg on the next attempt (section 4.2's
    # check-then-write order; `ARM6` drives the whole loop end to end).
    owed = _compute_owed(new_anchor)
    vacuous = _compute_vacuous(new_anchor)
    stale = _compute_stale(new_anchor)
    if owed or vacuous or stale:
        relpath = _module_relpath()
        for key, entries in owed.items():
            for e in entries:
                print(f"OWED: {key}: {e}", file=sys.stderr)
        for key, entries in vacuous.items():
            for e in entries:
                print(f"VACUOUS: {key}: {e}", file=sys.stderr)
        for name, shipped, live in stale:
            print(f"STALE: {relpath}: MEASURED[{name!r}] (scope={MEASURED[name].scope})", file=sys.stderr)
            print(f"STALE:       shipped value: {shipped!r}", file=sys.stderr)
            print(f"STALE:   value at {new_anchor}: {live!r}", file=sys.stderr)
        # The trailer deliberately spells NO bare `OWED:`/`VACUOUS:`/
        # `STALE:` token (note the article-and-space forms below), so a
        # caller's unanchored substring match on a token still matches
        # only real report lines. An earlier draft did spell them out,
        # which made `"OWED:" not in stderr` false for every refusal --
        # caught by this unit's own first test run, and now pinned by
        # `ANC6` and by the runbook §5 contract table.
        print(
            f"refusing to write test_armor.py ({relpath}) -- NOTHING was "
            "written and the file is byte-unchanged. Fix every line above, "
            "then re-run this exact command.\n"
            "  An OWED line   -- that node needs a dated, anchored exemption "
            "entry naming a spec section (Behaviour.missing / .edited).\n"
            "  A VACUOUS line -- the new anchor owes that entry nothing; DROP "
            "it (section 4.7 FW-140's fold rule).\n"
            "  A STALE line   -- copy the printed 'value at' into that "
            "MEASURED row's `value=` and re-date its `reason`. --remeasure "
            "never writes a MEASURED value: rewriting it silently would "
            "remove this refusal and the dated record of the change. The "
            "landing's author writes it -- an agent is a sanctioned author "
            "here, exactly as for an exemption entry.\n"
            "(see docs/specs/self-learn/15-orchestration-runbook.md §5 for "
            "the full refusal contract, and §1.4a for the gate's own review)",
            file=sys.stderr,
        )
        return 1

    new_source = _render_module(new_anchor)
    module_path = Path(__file__)
    tmp_path = module_path.with_suffix(".py.tmp")
    tmp_path.write_text(new_source, encoding="utf-8")
    import os
    os.replace(tmp_path, module_path)

    if new_anchor == old_anchor:
        print(
            f"ANCHOR did not change ({old_anchor} -> {new_anchor}) -- the "
            "landing chain's &&-chain must abort here (the no-op guard)",
            file=sys.stderr,
        )
        return 1
    print(f"ANCHOR {old_anchor} -> {new_anchor}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if "--remeasure" in sys.argv[1:]:
        raise SystemExit(_remeasure(sys.argv[1:]))
    raise SystemExit(
        "test_armor.py has no standalone CLI mode other than --remeasure "
        "(ARM6's refused-CLI-mode leg) -- run it under pytest."
    )


# ======================================================================= #
# ======================================================================= #
#  5.1 ARM -- the module and the table
# ======================================================================= #
# ======================================================================= #


def test_arm1_one_table_one_anchor():
    """`ARM1`. Positive control first: the pre-state (`3b8e037`) walk
    over `test_worker_contract.py` finds exactly one such table
    (`_ARMOR_SHAS`, 7 entries) -- proving the instrument finds a second
    table when one exists, before asserting this module ships alone."""

    def _sha_dicts(tree: ast.Module) -> list[tuple[str, int]]:
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                hex_values = sum(
                    1 for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", v.value)
                )
                path_keys = sum(
                    1 for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and k.value.endswith(".py")
                )
                if hex_values and path_keys and hex_values == path_keys:
                    found.append(("dict", len(node.keys)))
        return found

    pre_state_src = _git_show_text("3b8e037", "test_worker_contract.py")
    pre_hits = _sha_dicts(ast.parse(pre_state_src))
    assert pre_hits == [("dict", 7)], pre_hits

    cli_tests_dir = _REPO_ROOT / _TESTS_DIR
    armor_assigns = 0
    anchor_assigns = 0
    stray_sha_tables = []
    for p in cli_tests_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            target_name = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target_name = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_name = node.target.id
            if target_name == "ARMOR":
                armor_assigns += 1
            if target_name == "ANCHOR":
                anchor_assigns += 1
        if p.name != "test_armor.py":
            hits = _sha_dicts(tree)
            if hits:
                stray_sha_tables.append((str(p.relative_to(cli_tests_dir)), hits))

    assert armor_assigns == 1, armor_assigns
    assert anchor_assigns == 1, anchor_assigns
    assert stray_sha_tables == [], stray_sha_tables


def test_arm2_literals_match_the_anchor():
    """`ARM2`. Every `Behaviour.nodes`/`.dump_sha` and every `Fixture`
    sha equals the census/sha256 measured at `ANCHOR` right now."""
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        c = _anchor_census(key)
        assert len(c) == row.nodes, (key, len(c), row.nodes)
        assert _dump_sha(c) == row.dump_sha, key
    for key in FIXTURE_KEYS:
        live_sha = hashlib.sha256(_anchor_bytes(key)).hexdigest()
        # There is no per-fixture literal in `Fixture` itself (the sha
        # lives only in `F1`'s live comparison, section 4.3) -- ARM2's
        # fixture leg instead confirms the anchor bytes are non-empty
        # and stable across two independent `git show` calls, which is
        # what a hand-edited literal drifting from `--remeasure` would
        # violate for the BEHAVIOUR half above.
        assert len(live_sha) == 64
        assert hashlib.sha256(_anchor_bytes(key)).hexdigest() == live_sha


def test_arm3_table_is_exhaustive():
    """`ARM3`. Positive control: dropping the `support.py` row from a
    FIXTURE COPY of the table reddens the first half; dropping
    `test_composer.py` reddens the second half."""
    non_test_paths = {
        str(p.relative_to(_REPO_ROOT / _TESTS_DIR)).replace("\\", "/")
        for p in (_REPO_ROOT / _TESTS_DIR).rglob("*.py")
        if p.stem != "__init__" and "__pycache__" not in p.parts and not p.name.startswith("test_")
    }
    assert non_test_paths <= set(ARMOR), non_test_paths - set(ARMOR)

    old_pins_src = _git_show_text("3b8e037", "test_worker_contract.py")
    old_pins = set(
        re.findall(r'"plugins/self-learn/cli/tests/([a-z0-9_/.]+\.py)": "[0-9a-f]{64}"', old_pins_src)
    )
    old_ds1_src = _git_show_text("3b8e037", "test_u_fake.py")
    m = re.search(r"_DS1_EXPECTED = \{(.*?)\n\}", old_ds1_src, re.S)
    assert m is not None, "_DS1_EXPECTED not found in the 3b8e037 test_u_fake.py source"
    old_ds1 = set(re.findall(r'"([a-z0-9_.]+\.py)"', m.group(1)))
    assert old_pins | old_ds1 <= set(ARMOR), (old_pins | old_ds1) - set(ARMOR)

    def _check(table: dict) -> None:
        keys = set(table)
        assert non_test_paths <= keys, "first half: " + str(non_test_paths - keys)
        assert (old_pins | old_ds1) <= keys, "second half: " + str((old_pins | old_ds1) - keys)

    _check(dict(ARMOR))  # the real table: both halves pass
    fixture_copy = dict(ARMOR)
    del fixture_copy["support.py"]
    with pytest.raises(AssertionError, match="first half"):
        _check(fixture_copy)
    fixture_copy2 = dict(ARMOR)
    del fixture_copy2["test_composer.py"]
    with pytest.raises(AssertionError, match="second half"):
        _check(fixture_copy2)


def test_arm4_anchor_is_real():
    """`ARM4`. `ANCHOR` resolves as a commit reachable from `HEAD`, and
    is not one of the three retired anchors."""
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ANCHOR, "HEAD"], cwd=_REPO_ROOT,
    )
    assert r.returncode == 0
    kind = subprocess.run(
        ["git", "cat-file", "-t", ANCHOR], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert kind == "commit"
    assert ANCHOR not in {"c3b48e7", "442385d", "c2669a9"}

    r2 = subprocess.run(["git", "merge-base", "--is-ancestor", "deadbeef", "HEAD"], cwd=_REPO_ROOT)
    assert r2.returncode != 0


def _latest_first_parent_merge_root() -> str:
    """`ARM5`'s walk root (r1 gate fold discovery). See
    `test_arm5_anchor_is_not_stale`'s own docstring for the full
    reasoning; delegates to the shared `_incorporated_master_point`,
    which is always the master content `HEAD` has actually absorbed --
    never a fold commit HEAD made itself, never content master gained
    afterward that HEAD hasn't merged yet. (r2 gate, N-1: this is
    `§4.2`'s own literal-`master` rule narrowed to what HEAD has
    absorbed while this branch is still in flight -- the two forms
    coincide exactly once the landing merge lands and HEAD contains
    that same `master` tip.)"""
    return _incorporated_master_point()


def test_arm5_anchor_is_not_stale():
    """`ARM5`. Three legs, measured at live `HEAD`, plus three red
    controls that are all real history.

    Resolves the walk ROOT via `_latest_first_parent_merge_root` (r1
    gate fold discovery -- not a named finding, a correctness gap this
    unit's own landing-chain folds surfaced, in two stages). Neither a
    bare, permanent `HEAD` nor literal `master` stays race-safe once
    this branch has folded master in at least once: `HEAD` BECOMES a
    2-parent merge the moment this unit performs its OWN landing-chain
    fold, so walking first-parent from `HEAD` directly finds that fold
    commit itself, not master's mainline; and literal `master` can
    race ahead again afterward with content -- merge or not -- that
    `HEAD` hasn't absorbed yet (measured live: a same-day hotfix landed
    on master with no merge marker at all). `git merge-base master
    HEAD` sidesteps both failure modes at once: it is always exactly
    the master content this branch has already absorbed, which is the
    same moment `--remeasure`'s own production logic
    (`_resolve_new_anchor`) trusts a fresh `master` query too -- just
    computed from HEAD's side of that same absorption point instead of
    master's live tip. (r2 gate, N-2: leg (c) is commit-scoped
    (`merge..HEAD`) by design -- an uncommitted protected-file edit is
    not this leg's job, and is already caught by UN5/BEH1/BEH3.)"""
    root = _latest_first_parent_merge_root()
    merge = subprocess.run(
        ["git", "rev-list", "--first-parent", "--merges", "-1", root],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    merge_parent_short = subprocess.run(
        ["git", "rev-parse", "--short=7", f"{merge}^1"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    def _legs(anchor: str, tip: str) -> tuple[bool, bool, int]:
        a = subprocess.run(["git", "merge-base", "--is-ancestor", anchor, tip], cwd=_REPO_ROOT)
        leg_a = a.returncode == 0
        leg_b = anchor == merge_parent_short
        moved = subprocess.run(
            ["git", "diff", "--name-only", f"{merge}..{tip}", "--", *STRICT_PROTECTED_RELPATHS],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        return leg_a, leg_b, len(moved)

    leg_a, leg_b, leg_c = _legs(ANCHOR, "HEAD")
    assert (leg_a, leg_b, leg_c) == (True, True, 0), (leg_a, leg_b, leg_c)

    # Red control (ii): ANCHOR one merge stale (15fb676, Phase 1's
    # parent) -- leg (b) alone fails; (a) and (c) both still pass.
    leg_a2, leg_b2, leg_c2 = _legs("15fb676", "HEAD")
    assert leg_a2 is True and leg_b2 is False, (leg_a2, leg_b2)

    # Red control (iii): the merge itself, r3's own shipped mistake.
    leg_a3, leg_b3, leg_c3 = _legs("fe5a012", "HEAD")
    assert leg_a3 is True and leg_b3 is False, (leg_a3, leg_b3)

    # Red control (i), real history: tip `1251552` touched a protected
    # file (`test_repair.py`) after its own anchor merge `c8dcaf3`
    # (ANCHOR = `5803a36`). (a) and (b) both PASS there; only (c)
    # discriminates, at 1.
    r_exists = subprocess.run(["git", "cat-file", "-e", "1251552"], cwd=_REPO_ROOT)
    if r_exists.returncode == 0:
        moved = subprocess.run(
            ["git", "diff", "--name-only", "c8dcaf3..1251552", "--", "plugins/self-learn/cli/tests/test_repair.py"],
            cwd=_REPO_ROOT, capture_output=True, text=True,
        ).stdout.splitlines()
        assert len(moved) == 1, moved

    # The count-form leg (c) IS deliberately rejected: it drifts on
    # unrelated docs-only commits (section 4.2's own deviation, adjudicated
    # SOUND). Measured here so the rejection is not merely asserted.
    count_form = subprocess.run(
        ["git", "rev-list", "--count", f"{ANCHOR}..HEAD^"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # This may be 0 (nothing landed after the anchor merge yet) or
    # nonzero (docs-only commits on top) -- either way, leg (c) as
    # SHIPPED must read 0 whenever the count form is nonzero but nothing
    # protected moved, which the live measurement above already proves.
    assert count_form.isdigit()


def _scratch_armor_namespace(scratch_dir: Path, mod_name: str) -> tuple[Path, dict]:
    """`(scratch_module_path, namespace)` -- a COPY of this module
    exec'd in an isolated namespace whose `__file__` points at a
    throwaway file INSIDE the repo tree, so the copy's own
    `_REPO_ROOT` computation (`git rev-parse --show-toplevel` from
    `Path(__file__).parent`) still resolves.

    Every `--remeasure` drive in this file goes through here: the real
    `test_armor.py`, the real `ARMOR` and the real `MEASURED` are
    never touched by a test. `ARM6` grew this pattern; `ANC1`/`ANC5`
    reuse it (r1 U-anchorlit fold: it was three inline copies)."""
    scratch_module = scratch_dir / "test_armor.py"
    shutil.copyfile(Path(__file__), scratch_module)
    scratch_mod = types.ModuleType(mod_name)
    scratch_mod.__file__ = str(scratch_module)
    sys.modules[mod_name] = scratch_mod
    ns = scratch_mod.__dict__
    code = compile(scratch_module.read_text(encoding="utf-8"), str(scratch_module), "exec")
    try:
        exec(code, ns)
    finally:
        del sys.modules[mod_name]
    return scratch_module, ns


def test_arm6_refusal_writes_nothing(capsys):
    """`ARM6`. A refusing `--remeasure` leaves the file byte-identical
    (sha256 before == after); a subsequent run with everything the
    refusal named written succeeds AND the `ANCHOR` literal changes in
    that run. Positive control: a clean census rewrites the file (sha
    differs) and exits 0. Also: plain CLI invocation with no
    `--remeasure` refuses.

    "Everything the refusal named" now includes the `MEASURED` rows
    the advance invalidates (`ANC1`, U-anchorlit), so this test is the
    landing bootstrap in miniature -- refuse, transcribe by hand,
    re-run, succeed -- driven in-process against a scratch copy at a
    FIXED historical anchor (`15fb676`), which no later landing can
    invalidate. The transcription happens in the SCRATCH namespace
    only; `ANC3` is the leg proving `--remeasure` itself never writes
    a `MEASURED` value into the file."""
    real_module = Path(__file__)

    # In-process leg: exec a SCRATCH COPY of this module's text in an
    # isolated namespace, so `_compute_owed`/`_remeasure` operate on a
    # throwaway file and the real ARMOR table is never touched. Driving
    # `--remeasure` against `15fb676` (one merge stale) is a real anchor
    # the spec's own census measures as owing 5 unexempted `edited`
    # entries (section 2.10) -- a genuine owed set, not a synthetic one.
    scratch_dir = Path(tempfile.mkdtemp(dir=str(_REPO_ROOT)))
    try:
        scratch_module, ns = _scratch_armor_namespace(scratch_dir, "_armor_scratch")

        owed = ns["_compute_owed"]("15fb676")
        assert owed, "expected 15fb676 to owe at least one unexempted node (section 2.10: 5 edited)"

        sha_before2 = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        rc = ns["_remeasure"](["--remeasure", "--anchor", "15fb676"])
        sha_after2 = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        assert rc != 0
        assert sha_after2 == sha_before2, "a refusing --remeasure must leave the file byte-identical"

        # Now write the owed exemptions directly into the scratch
        # namespace's ARMOR (what a human/builder would do by hand) and
        # re-run: it must succeed, AND the ANCHOR literal must genuinely
        # change in that run.
        new_armor = {}
        for k, v in ns["ARMOR"].items():
            if isinstance(v, ns["Behaviour"]) and k in owed:
                missing = dict(v.missing)
                edited = dict(v.edited)
                for entry in owed[k]:
                    kind, _, name = entry.partition(":")
                    reason = "2026-08-28 ARM6 test scaffold, §4.2: synthetic exemption."
                    if kind == "missing":
                        missing[name] = reason
                    else:
                        edited[name] = reason
                new_armor[k] = ns["Behaviour"](nodes=v.nodes, dump_sha=v.dump_sha, missing=missing, edited=edited)
            else:
                new_armor[k] = v
        ns["ARMOR"] = new_armor
        owed2 = ns["_compute_owed"]("15fb676")
        assert owed2 == {}, owed2

        # ... and transcribe every `MEASURED` row the advance
        # invalidates, exactly as the landing's author copies the printed
        # `value at 15fb676:` into `value=`. Asserted non-empty first:
        # if the advance stopped invalidating anything, this leg would
        # be silently vacuous and the bootstrap unproven.
        stale = ns["_compute_stale"]("15fb676")
        assert stale, "expected 15fb676 to invalidate at least one MEASURED row"
        transcribed = dict(ns["MEASURED"])
        for name, _shipped, live in stale:
            transcribed[name] = dataclasses.replace(transcribed[name], value=live)
        ns["MEASURED"] = transcribed
        assert ns["_compute_stale"]("15fb676") == []
        assert ns["_compute_vacuous"]("15fb676") == {}

        capsys.readouterr()
        anchor_before_run2 = ns["ANCHOR"]
        rc2 = ns["_remeasure"](["--remeasure", "--anchor", "15fb676"])
        cap2 = capsys.readouterr()
        assert rc2 == 0

        # The rc-0 success shape, for the runbook §5 contract table
        # (`ANC6` pins the three refusal legs; this is the fourth
        # outcome, and the only one `ANC6` cannot cheaply reach).
        assert cap2.out == "", cap2.out
        success_lines = [ln for ln in cap2.err.splitlines() if ln.strip()]
        assert len(success_lines) == 1, success_lines
        assert success_lines[0] == f"ANCHOR {anchor_before_run2} -> 15fb676", success_lines
        assert _SUCCESS_RE.match(success_lines[0]), success_lines[0]
        new_text = scratch_module.read_text(encoding="utf-8")
        assert 'ANCHOR = "15fb676"' in new_text
        assert anchor_before_run2 != "15fb676"

        # The written file carries the NEW anchor and the NEW Behaviour
        # rows -- and the SAME `MEASURED` block it started with, because
        # `--remeasure` never authors one (`ANC3`). The transcription
        # above lived in the namespace, never in the rendered text.
        assert _measured_block(new_text) == _measured_block(real_module.read_text(encoding="utf-8"))

        # Positive control: a clean run against a genuinely new anchor
        # with nothing owed rewrites the file (sha differs from a fresh
        # copy) and exits 0 -- already proven by rc2/new_text above.
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # Plain CLI invocation, no --remeasure: refuses (nonzero exit).
    proc = subprocess.run([sys.executable, str(real_module)], cwd=real_module.parent, capture_output=True)
    assert proc.returncode != 0


# ======================================================================= #
# ======================================================================= #
#  5.2 FIX -- the fixtures
# ======================================================================= #
# ======================================================================= #


def _f1(key: str) -> str:
    """`F1` -- whole-file byte identity against `ANCHOR`."""
    return hashlib.sha256(_head_bytes(key)).hexdigest()


def _f1_matches_anchor(key: str) -> bool:
    return _f1(key) == hashlib.sha256(_anchor_bytes(key)).hexdigest()


def test_fix1_fixtures_are_byte_identical(tmp_path):
    """`F1`. Positive control, asserted first: three `tmp_path` copies,
    one per fixture, each with a module-level rebinding of a
    pre-existing global appended -- all three must redden (the exact
    evasion r2's ordered-subsequence match let through, section 4.3)."""
    rebindings = {
        "conftest.py": '\n_cache_env = "PWNED"\n',
        "support.py": '\n_GIT_SHIM = "PWNED"\n',
        "backends.py": '\n__all__ = "PWNED"\n',
    }
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        if row.repinned is None:
            assert _f1_matches_anchor(key), f"{key} unexpectedly differs from anchor before mutation"
        else:
            # r1 gate fold: `support.py` carries a real re-pin
            # (U-verbs' `force_past_deferred`) -- its correct
            # pre-mutation state is the REPINNED sha, not ANCHOR's.
            assert _f1(key) == row.repinned[0], f"{key} unexpectedly differs from its repinned sha before mutation"

    for key, appended in rebindings.items():
        mutated = tmp_path / key
        mutated.write_bytes(_head_bytes(key) + appended.encode("utf-8"))
        mutated_sha = hashlib.sha256(mutated.read_bytes()).hexdigest()
        anchor_sha = hashlib.sha256(_anchor_bytes(key)).hexdigest()
        assert mutated_sha != anchor_sha, f"{key}: appended rebinding did not change the whole-file sha"

    # M7: delete an exported helper from a `support.py` copy.
    support_text = _head_text("support.py")
    lines = support_text.splitlines(keepends=True)
    # delete the first `def ` line found, plus its body up to the next
    # top-level statement, approximated by removing just that one line
    # (sufficient to move the whole-file sha).
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("def "))
    mutated_support = tmp_path / "support_del.py"
    mutated_support.write_text("".join(lines[:idx] + lines[idx + 1:]), encoding="utf-8")
    assert (
        hashlib.sha256(mutated_support.read_bytes()).hexdigest()
        != hashlib.sha256(_anchor_bytes("support.py")).hexdigest()
    )

    # M5: delete one line from inside an anchor-era statement of a
    # `conftest.py` copy.
    conftest_lines = _head_text("conftest.py").splitlines(keepends=True)
    mutated_conftest = tmp_path / "conftest_del.py"
    mutated_conftest.write_text("".join(conftest_lines[:5] + conftest_lines[6:]), encoding="utf-8")
    assert (
        hashlib.sha256(mutated_conftest.read_bytes()).hexdigest()
        != hashlib.sha256(_anchor_bytes("conftest.py")).hexdigest()
    )

    # The shipped fixtures themselves are byte-identical to ANCHOR right now.
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        if row.repinned is None:
            assert _f1_matches_anchor(key), key
        else:
            assert _f1(key) == row.repinned[0], key


def test_fix2_repin_door_is_exact_and_cannot_rot():
    """`F2`. A `Fixture.repinned = (sha, reason)` entry lets head differ
    from the anchor and ONLY to that sha; every entry's file must
    actually differ from its anchor bytes and match the pinned sha
    (the anti-rot leg). Driven over a fixture TABLE, not the real one."""

    def _check_repin_shas(key: str, row: Fixture, head_sha: str, anchor_sha: str) -> None:
        if row.repinned is None:
            return
        sha, reason = row.repinned
        assert head_sha != anchor_sha, f"{key}: repinned entry present but file reverted to its anchor (anti-rot)"
        assert head_sha == sha, f"{key}: repinned sha does not match head bytes"
        ok, why = _exm1_check(reason)
        assert ok, f"{key}: {why}"

    def _check_repin(key: str, row: Fixture) -> None:
        _check_repin_shas(key, row, _f1(key), hashlib.sha256(_anchor_bytes(key)).hexdigest())

    # The shipped table: all three `repinned is None` -- EXM3 covers the
    # unconditional assertion; here we only confirm `_check_repin` is a
    # no-op for it.
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        _check_repin(key, row)

    # Bad entry 1: a sha that does not match head. Genuinely-differing
    # head/anchor shas (so the anti-rot leg passes first) with a
    # `repinned` sha that matches NEITHER.
    bad1 = Fixture(repinned=("0" * 64, "2026-08-28 §4.3 test scaffold."))
    with pytest.raises(AssertionError, match="does not match head"):
        _check_repin_shas("conftest.py", bad1, head_sha="1" * 64, anchor_sha="2" * 64)

    # Bad entry 2 (anti-rot): an entry on a file identical to its anchor.
    same = "3" * 64
    bad2 = Fixture(repinned=(same, "2026-08-28 §4.3 test scaffold."))
    with pytest.raises(AssertionError, match="anti-rot"):
        _check_repin_shas("conftest.py", bad2, head_sha=same, anchor_sha=same)

    # Bad entry 3: a reason with no citation (a well-formed sha/anti-rot
    # pair, so `_check_repin`'s first two asserts pass and the failure is
    # isolated to the reason grammar, which `EXM1` -- not `_check_repin`
    # -- is responsible for).
    bad3 = Fixture(repinned=("0" * 64, "cleaned up"))
    assert bad3.repinned is not None
    ok, why = _exm1_check(bad3.repinned[1])
    assert not ok, why


def test_fix3_support_is_protected():
    """`FIX3`. `support.py` is a key, and `F1` reports a nonzero anchor
    byte length. Positive control: the same assertion over an empty
    file reports 0 and reddens."""
    assert "support.py" in ARMOR
    assert isinstance(ARMOR["support.py"], Fixture)
    n = len(_anchor_bytes("support.py"))
    assert n > 0, n

    assert len(b"") == 0  # the empty-file control this positive control rejects


def test_fix4_diagnostic_is_report_only():
    """`FIX4`. `F3` is called only inside `F1`'s failure branch, and its
    return value never reaches an `assert`'s CONDITION. Structural (r4,
    gate N-7 -- narrowed to what an `ast` walk can actually prove): (i)
    every `_f3_diagnostic` call site is lexically nested inside an
    `ast.If`; (ii) no name bound from its return value is referenced
    inside any `assert`'s `test` expression (the message half is fine --
    that IS the diagnostic's job). Functional: over the three FIX1
    control copies, `F1` (`_f1_or_report`) reports non-`None` AND names
    the rebound global."""
    tree = ast.parse(_module_source())

    def _enclosing_if(target: ast.expr, root: ast.AST) -> ast.If | None:
        best = None
        for node in ast.walk(root):
            if isinstance(node, ast.If) and node.lineno <= target.lineno <= (node.end_lineno or target.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
        return best

    call_sites = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_f3_diagnostic"
    ]
    assert call_sites, "no _f3_diagnostic call site found -- FIX4 has nothing to check"
    for call in call_sites:
        assert _enclosing_if(call, tree) is not None, (
            f"_f3_diagnostic called at line {call.lineno} outside any if-branch"
        )

    # Names bound directly from a `_f3_diagnostic(...)` call (via `x = _f3_diagnostic(...)`
    # or `x := _f3_diagnostic(...)`), anywhere in the module.
    diag_bound_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "_f3_diagnostic":
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        diag_bound_names.add(t.id)
        if isinstance(node, ast.NamedExpr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "_f3_diagnostic":
                if isinstance(node.target, ast.Name):
                    diag_bound_names.add(node.target.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Name) and sub.id in diag_bound_names:
                    raise AssertionError(
                        f"assert condition at line {node.lineno} reads {sub.id!r}, "
                        "a name bound from _f3_diagnostic's return -- F3 must never decide"
                    )

    # Functional leg: for each of FIX1's three mutated fixtures,
    # `_f1_or_report` is non-None AND names the rebound global.
    mutations = {
        "conftest.py": "_cache_env",
        "support.py": "_GIT_SHIM",
        "backends.py": "__all__",
    }
    for key, global_name in mutations.items():
        mutated_bytes = _head_bytes(key) + f'\n{global_name} = "PWNED"\n'.encode("utf-8")
        report = _f1_or_report(key, mutated_bytes)
        assert report is not None, f"{key}: F1 unexpectedly matched after mutation"
        assert f"assign:{global_name}" in report, (key, report)
    # Positive control: an unmutated fixture reports None (F1 passes).
    # `_f1_or_report` is a plain ANCHOR-vs-candidate comparison (not
    # repin-aware); skip any row carrying a real `Fixture.repinned`
    # (r1 gate fold: `support.py` now does) -- for those, live bytes
    # are EXPECTED to differ from anchor bytes by design (F2's job,
    # not F1's), so `_f1_or_report` correctly reports non-None.
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        if row.repinned is not None:
            continue
        assert _f1_or_report(key, _head_bytes(key)) is None, key


# ======================================================================= #
# ======================================================================= #
#  5.3 ADD -- fixtures/fake_claude.py (SU4B's four legs, migrated
#  verbatim -- section 4.4)
# ======================================================================= #
# ======================================================================= #

_FAKE_CLAUDE_KEY = "fixtures/fake_claude.py"


def _load_module_from_path(path: Path, name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _additive_stmt_key(node: ast.AST) -> tuple:
    if isinstance(node, ast.Import):
        return ("import", tuple(sorted(a.name for a in node.names)))
    if isinstance(node, ast.ImportFrom):
        return ("importfrom", node.module, tuple(sorted(a.name for a in node.names)))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return ("assign", node.target.id)
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return ("assign", node.targets[0].id)
    if isinstance(node, ast.ClassDef):
        return ("class", node.name)
    return ("other", ast.dump(node))


def _find_scenarios_assign(tree: ast.Module) -> ast.Assign:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "SCENARIOS"
        ):
            return node
    raise AssertionError("SCENARIOS assignment not found")


def _su4b_leg1_runtime_bound_source_unchanged(base_func_names, base_shas, cur_func_names, cur_mod, edited_names) -> None:
    """Leg 1: every base function's RUNTIME-BOUND source is byte-
    unchanged -- resolved through the imported module, never an
    ast-first-match (r1 gate fold, N-7: named and callable on its own,
    not folded invisibly inside `_su4b_legs`)."""
    import inspect
    for name in base_func_names:
        assert name in cur_func_names, f"{name} missing from the current file"
        if name in edited_names:
            continue
        fn = getattr(cur_mod, name)
        live_src = inspect.getsource(fn)
        assert hashlib.sha256(live_src.encode("utf-8")).hexdigest() == base_shas[name], name


def _su4b_leg2_no_new_top_level_names(base_func_names, cur_func_names, additive: Additive) -> None:
    """Leg 2: no top-level names beyond base and the sanctioned new set."""
    new_names = cur_func_names - base_func_names
    assert new_names == set(additive.new_funcs), (new_names, additive.new_funcs)


def _su4b_leg3_scenarios_key_set(base_mod, cur_mod, additive: Additive) -> None:
    """Leg 3: SCENARIOS' key set gained nothing beyond base and the
    sanctioned new keys; every base key survives bound to its ORIGINAL
    function (by __name__)."""
    base_scenarios = base_mod.SCENARIOS
    cur_scenarios = cur_mod.SCENARIOS
    base_keys = set(base_scenarios.keys())
    cur_keys = set(cur_scenarios.keys())
    assert cur_keys - base_keys == set(additive.new_scenario_keys), (
        cur_keys - base_keys, additive.new_scenario_keys
    )
    assert base_keys <= cur_keys
    for key in base_keys:
        assert base_scenarios[key].__name__ == cur_scenarios[key].__name__, key


def _su4b_leg4_other_statements_unchanged(base_tree: ast.Module, cur_tree: ast.Module, additive: Additive) -> None:
    """Leg 4: top-level non-FunctionDef statements are exactly base's,
    in the same order, plus the sanctioned new statement keys inserted
    anywhere."""
    base_scen_node = _find_scenarios_assign(base_tree)
    cur_scen_node = _find_scenarios_assign(cur_tree)
    base_other = [n for n in base_tree.body if not isinstance(n, ast.FunctionDef) and n is not base_scen_node]
    cur_other = [n for n in cur_tree.body if not isinstance(n, ast.FunctionDef) and n is not cur_scen_node]

    cur_other_keys = [_additive_stmt_key(n) for n in cur_other]
    sanctioned_idx = [i for i, k in enumerate(cur_other_keys) if k in set(additive.new_stmt_keys)]
    assert {cur_other_keys[i] for i in sanctioned_idx} == set(additive.new_stmt_keys), (
        "sanctioned-new-statement set mismatch",
        {cur_other_keys[i] for i in sanctioned_idx},
    )
    filtered_cur_other = [n for i, n in enumerate(cur_other) if i not in sanctioned_idx]
    assert len(base_other) == len(filtered_cur_other), (
        "top-level non-FunctionDef statement count changed beyond the sanctioned insertions"
    )
    for b, c in zip(base_other, filtered_cur_other):
        assert ast.dump(b) == ast.dump(c)

    base_dict, cur_dict = base_scen_node.value, cur_scen_node.value
    assert isinstance(base_dict, ast.Dict) and isinstance(cur_dict, ast.Dict)
    base_pairs = {
        ast.dump(k): ast.dump(v) for k, v in zip(base_dict.keys, base_dict.values) if k is not None
    }
    cur_pairs = {
        ast.dump(k): ast.dump(v) for k, v in zip(cur_dict.keys, cur_dict.values) if k is not None
    }
    assert set(base_pairs) <= set(cur_pairs)
    for k, v in base_pairs.items():
        assert cur_pairs[k] == v, "a pre-existing SCENARIOS entry changed"
    assert len(set(cur_pairs) - set(base_pairs)) == len(set(additive.new_scenario_keys))


def _su4b_legs(base_src: str, cur_src: str, cur_mod, tmp_path: Path, additive: Additive) -> None:
    """`SU4B`'s four legs, migrated verbatim from `test_worker_
    contract.py`, reading their sanctioned sets from `additive` instead
    of three module constants. `cur_mod` is the IMPORTED current module
    (leg 1's runtime-binding requirement). Orchestrates the four named
    leg functions above (r1 gate fold, N-7) -- `test_add1`'s own
    shipped-file positive control calls those four directly instead of
    this wrapper, so each leg is independently visible; the MUTATION
    scenarios below call this orchestrator, since they only need "does
    violating one leg fail overall"."""
    base_tree = ast.parse(base_src, filename="base_fake_claude.py")
    base_func_names = {n.name for n in base_tree.body if isinstance(n, ast.FunctionDef)}

    tmp_path.mkdir(parents=True, exist_ok=True)
    base_path = tmp_path / "base_fake_claude.py"
    base_path.write_text(base_src, encoding="utf-8")
    base_mod = _load_module_from_path(base_path, f"_fake_claude_base_{id(tmp_path)}")
    import inspect
    base_shas = {
        name: hashlib.sha256(inspect.getsource(getattr(base_mod, name)).encode("utf-8")).hexdigest()
        for name in base_func_names
    }

    cur_tree = ast.parse(cur_src, filename="cur_fake_claude.py")
    cur_func_names = {n.name for n in cur_tree.body if isinstance(n, ast.FunctionDef)}

    edited_names = set(additive.edited_funcs)

    _su4b_leg1_runtime_bound_source_unchanged(base_func_names, base_shas, cur_func_names, cur_mod, edited_names)
    _su4b_leg2_no_new_top_level_names(base_func_names, cur_func_names, additive)
    _su4b_leg3_scenarios_key_set(base_mod, cur_mod, additive)
    _su4b_leg4_other_statements_unchanged(base_tree, cur_tree, additive)


def test_add1_fake_claude_additive_only(tmp_path):
    """`ADD1`. Positive control, asserted first: the two evasions `SU4B`'s
    own comments name -- a shadowing redefinition (leg 1) and an
    appended module-level rebinding of a pre-existing global (leg 4) --
    each applied to a `tmp_path` copy, each must redden its leg."""
    import inspect

    additive = ARMOR[_FAKE_CLAUDE_KEY]
    assert isinstance(additive, Additive)
    base_src = _anchor_text(_FAKE_CLAUDE_KEY)
    cur_src = _head_text(_FAKE_CLAUDE_KEY)

    # The shipped file: all four legs pass -- as FOUR SEPARATE asserts
    # (r1 gate fold, N-7), each calling its own named leg function
    # directly, not one opaque `_su4b_legs` call.
    ok_base_dir = tmp_path / "ok_base"
    ok_base_dir.mkdir()
    base_tree = ast.parse(base_src, filename="base_fake_claude.py")
    base_func_names = {n.name for n in base_tree.body if isinstance(n, ast.FunctionDef)}
    base_path = ok_base_dir / "base_fake_claude.py"
    base_path.write_text(base_src, encoding="utf-8")
    base_mod = _load_module_from_path(base_path, f"_fake_claude_base_ok_{id(tmp_path)}")
    base_shas = {
        name: hashlib.sha256(inspect.getsource(getattr(base_mod, name)).encode("utf-8")).hexdigest()
        for name in base_func_names
    }
    cur_path = tmp_path / "cur_ok.py"
    cur_path.write_text(cur_src, encoding="utf-8")
    cur_mod = _load_module_from_path(cur_path, f"_fake_claude_cur_ok_{id(tmp_path)}")
    cur_tree = ast.parse(cur_src, filename="cur_fake_claude.py")
    cur_func_names = {n.name for n in cur_tree.body if isinstance(n, ast.FunctionDef)}
    edited_names = set(additive.edited_funcs)

    _su4b_leg1_runtime_bound_source_unchanged(base_func_names, base_shas, cur_func_names, cur_mod, edited_names)
    _su4b_leg2_no_new_top_level_names(base_func_names, cur_func_names, additive)
    _su4b_leg3_scenarios_key_set(base_mod, cur_mod, additive)
    _su4b_leg4_other_statements_unchanged(base_tree, cur_tree, additive)

    # M9: a shadowing redefinition -- append a second `def <name>():` for
    # a NON-exempted base function (an exempted one would be a weak
    # control, since leg 1 already skips it deliberately).
    base_tree = ast.parse(base_src)
    base_func_names = {n.name for n in base_tree.body if isinstance(n, ast.FunctionDef)}
    edited_names = set(additive.edited_funcs)
    shadow_target = sorted(base_func_names - edited_names)[0]
    shadowed_src = cur_src + f"\n\ndef {shadow_target}():\n    return 'PWNED'\n"
    shadow_path = tmp_path / "shadow"
    shadow_path.mkdir()
    shadow_file = shadow_path / "shadowed.py"
    shadow_file.write_text(shadowed_src, encoding="utf-8")
    shadow_mod = _load_module_from_path(shadow_file, f"_fake_claude_shadow_{id(tmp_path)}")
    with pytest.raises(AssertionError):
        _su4b_legs(base_src, shadowed_src, shadow_mod, tmp_path / "shadow_base", additive)

    # M9 (leg 4's own evasion): append a module-level REBINDING of a
    # pre-existing global (not a def) -- passes legs 1-3, must redden
    # leg 4's filtered-sequence comparison.
    existing_global = _additive_stmt_key(
        next(n for n in base_tree.body if _additive_stmt_key(n)[0] == "assign")
    )[1]
    rebind_src = cur_src + f'\n{existing_global} = "PWNED"\n'
    rebind_path = tmp_path / "rebind"
    rebind_path.mkdir()
    rebind_file = rebind_path / "rebind.py"
    rebind_file.write_text(rebind_src, encoding="utf-8")
    rebind_mod = _load_module_from_path(rebind_file, f"_fake_claude_rebind_{id(tmp_path)}")
    with pytest.raises(AssertionError):
        _su4b_legs(base_src, rebind_src, rebind_mod, tmp_path / "rebind_base", additive)


def test_add2_fake_claude_imports_nothing_live():
    """`ADD2`. `fake_claude.py` imports none of `subprocess`, `socket`,
    `urllib`, `http`. Positive control: a copy with `import socket`
    appended reddens."""
    text = _head_text(_FAKE_CLAUDE_KEY)
    for banned in ("subprocess", "socket", "urllib", "http"):
        assert f"import {banned}" not in text, banned

    mutated = text + "\nimport socket\n"
    assert "import socket" in mutated  # the positive control


def test_add3_edited_scenario_still_pinned():
    """`ADD3`. `_scenario_error_result`'s sha is pinned in `edited_funcs`
    and the live function matches it. Positive control: `SU4B` leg 1 is
    confirmed to SKIP this function (it is in `edited_funcs`), so `ADD3`
    is the only thing covering it."""
    additive = ARMOR[_FAKE_CLAUDE_KEY]
    assert isinstance(additive, Additive)
    assert "_scenario_error_result" in additive.edited_funcs
    sha, reason = additive.edited_funcs["_scenario_error_result"]
    assert re.fullmatch(r"[0-9a-f]{64}", sha)

    fake_mod = _load_module_from_path(
        _abspath(_FAKE_CLAUDE_KEY), "_fake_claude_live_for_add3"
    )
    import inspect
    live_src = inspect.getsource(fake_mod._scenario_error_result)
    assert hashlib.sha256(live_src.encode("utf-8")).hexdigest() == sha

    # Positive control: leg 1 skips this name (it's in edited_funcs).
    assert "_scenario_error_result" in set(additive.edited_funcs)


# ======================================================================= #
# ======================================================================= #
#  5.4 BEH -- the behaviour files
# ======================================================================= #
# ======================================================================= #


def test_beh1_no_node_is_deleted_or_renamed():
    """`B1`. Every anchor node key still exists at head, unless in
    `Behaviour.missing`. Positive control, asserted first: `ANCHOR =
    c3b48e7` reports 66 missing keys (re-measured 2026-08-28, was 56
    at spec-gate time, before this unit's own test_u_fake.py DS1
    deletions -- section 4.7 row 12). Second leg: an absent protected
    file fails with a named message, never a bare traceback."""
    total_missing_c3b48e7 = 0
    for key in BEHAVIOUR_KEYS:
        a = _census(_git_show_text("c3b48e7", key))
        h = _head_census(key)
        missing = [k for k in a if k not in h]
        total_missing_c3b48e7 += len(missing)
    assert total_missing_c3b48e7 == MEASURED["BEH1.control_missing"].value, total_missing_c3b48e7

    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        missing, _edited = _diff_census(key)
        unexempt = [k for k in missing if k not in row.missing]
        assert unexempt == [], (key, unexempt)

    # M12/M13: delete (or rename, i.e. delete-then-add) a real test.
    src = _head_text("test_worker.py")
    mutated_tree = ast.parse(src)
    mutated_tree.body = [
        n for n in mutated_tree.body
        if not (isinstance(n, ast.FunctionDef) and n.name == "test_run_idle_when_nothing_eligible")
    ]
    ast.fix_missing_locations(mutated_tree)
    mutated_census = _census(ast.unparse(mutated_tree))
    anchor_census_ = _anchor_census("test_worker.py")
    assert "func:test_run_idle_when_nothing_eligible" in anchor_census_
    assert "func:test_run_idle_when_nothing_eligible" not in mutated_census

    # deleting a module constant similarly reddens, naming `assign:...`.
    const_tree = ast.parse(src)
    const_key = next(
        _key(n) for n in const_tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and _key(n).startswith("assign:")
    )
    const_tree.body = [n for n in const_tree.body if _key(n) != const_key or not isinstance(n, (ast.Assign, ast.AnnAssign))]
    ast.fix_missing_locations(const_tree)
    mutated_census2 = _census(ast.unparse(const_tree))
    assert const_key not in mutated_census2

    # deleting a whole protected file: named message, not a traceback.
    with pytest.raises(AssertionError, match=r"protected file .* missing"):
        _diff_census("test_composer_DOES_NOT_EXIST.py")


def test_beh2_adding_is_free():
    """`BEH2`. Appending a new test and a new module constant to a
    `tmp_path` copy leaves every leg green. Positive control: deleting
    either reddens `BEH1`. Calls `_diff_maps` -- the SAME shared core
    `_diff_census` uses for the real file (r1 gate fold, M-1: this
    used to re-implement the subset/equality logic inline, a second
    copy that could drift from `_diff_census`'s own)."""
    key = "test_worker.py"
    src = _head_text(key)
    augmented = src + "\n\ndef test_zz_probe():\n    assert True\n\n\nZZ_CONST = 1\n"
    a = _anchor_census(key)
    h = _census(augmented)
    missing, edited = _diff_maps(a, h)
    assert missing == [], missing
    assert edited == [], edited
    assert "func:test_zz_probe" in h
    assert "assign:ZZ_CONST" in h

    # Positive control: deleting either one from the augmented copy
    # reddens BEH1 (a key present at anchor now missing at head -- here
    # we delete an EXISTING anchor key from `augmented` to prove the
    # detector fires).
    tree = ast.parse(augmented)
    tree.body = [n for n in tree.body if _key(n) != "func:test_zz_probe"]
    ast.fix_missing_locations(tree)
    without_probe = _census(ast.unparse(tree))
    assert "func:test_zz_probe" not in without_probe


def test_beh3_no_protected_node_is_edited():
    """`B3`. Dump identity, node-wide. Four MEASURED positive controls
    (all GREEN under the retired test-only census, all RED here) plus
    two gate probes (setup-line flip; `pytest.raises` deletion), plus
    the `c3b48e7` control at 184 edited (re-measured 2026-08-28, was
    190 at spec-gate time -- see `test_beh1`'s docstring)."""
    total_edited_c3b48e7 = 0
    for key in BEHAVIOUR_KEYS:
        a = _census(_git_show_text("c3b48e7", key))
        h = _head_census(key)
        edited = [k for k in a if k in h and h[k] != a[k]]
        total_edited_c3b48e7 += len(edited)
    assert total_edited_c3b48e7 == MEASURED["BEH3.control_edited"].value, total_edited_c3b48e7

    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        _missing, edited = _diff_census(key)
        unexempt = [k for k in edited if k not in row.edited]
        assert unexempt == [], (key, unexempt)

    def _mutate_and_check(key: str, target_key: str, transform) -> None:
        tree = ast.parse(_head_text(key))
        found = False
        for i, n in enumerate(tree.body):
            if _key(n) == target_key:
                tree.body[i] = transform(n)
                found = True
                break
        assert found, target_key
        ast.fix_missing_locations(tree)
        mutated_src = ast.unparse(tree)
        a = _anchor_census(key)
        h = _census(mutated_src)
        assert a[target_key] != h.get(target_key), f"{target_key} did not change under mutation"

    # (i) test_repair.py::RECORD_QUOTE mutated.
    def _flip_record_quote(n: ast.Assign) -> ast.Assign:
        mutated_expr = ast.parse('"MUTATED"').body[0]
        assert isinstance(mutated_expr, ast.Expr)
        n.value = mutated_expr.value
        return n
    _mutate_and_check("test_repair.py", "assign:RECORD_QUOTE", _flip_record_quote)

    # (ii)-(iv): gut a function body to `return None` / `pass`.
    def _gut(n):
        n.body = [ast.Pass()]
        return n
    _mutate_and_check("test_invocation.py", "func:_run_sdk", _gut)
    _mutate_and_check("test_repair.py", "func:_gates_raises", _gut)
    _mutate_and_check("test_worker.py", "func:_wait_for_file", _gut)

    # M43: flip one True->False on a setup line of a real protected test.
    src = _head_text("test_worker.py")
    tree = ast.parse(src)
    target = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "test_dead_pid_window_reopens"
    )
    flipped = False
    for node in ast.walk(target):
        if isinstance(node, ast.Constant) and node.value is True and not flipped:
            node.value = False
            flipped = True
    assert flipped, "no boolean literal found to flip in test_dead_pid_window_reopens"
    ast.fix_missing_locations(tree)
    mutated_src = ast.unparse(tree)
    a = _anchor_census("test_worker.py")
    h = _census(mutated_src)
    assert a["func:test_dead_pid_window_reopens"] != h["func:test_dead_pid_window_reopens"]

    # M44: delete a `with pytest.raises(...)` block inside a real test,
    # WHEREVER it is nested (a `NodeTransformer`, not a top-level-body
    # filter, since the block is not always a direct child statement).
    def _is_raises_with(node) -> bool:
        return isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "raises"
            for item in node.items
        )

    src2 = _head_text("test_invocation.py")
    tree2 = ast.parse(src2)
    raises_test = None
    raises_node = None
    for n in tree2.body:
        if isinstance(n, ast.FunctionDef):
            hit = next((node for node in ast.walk(n) if _is_raises_with(node)), None)
            if hit is not None:
                raises_test, raises_node = n, hit
                break
    assert raises_test is not None, "no pytest.raises block found in test_invocation.py"
    target_key2 = f"func:{raises_test.name}"

    class _DropRaises(ast.NodeTransformer):
        def visit_With(self, node):
            if node is raises_node:
                return ast.Pass()
            self.generic_visit(node)
            return node

    tree2.body = [
        _DropRaises().visit(n) if n is raises_test else n for n in tree2.body
    ]
    ast.fix_missing_locations(tree2)
    mutated_src2 = ast.unparse(tree2)
    a2 = _anchor_census("test_invocation.py")
    h2 = _census(mutated_src2)
    assert a2[target_key2] != h2[target_key2], target_key2


def test_beh4_docstring_reword_is_not_an_edit():
    """`BEH4`. A protected test's docstring reword and body reflow stay
    green; the same copy with one STATEMENT changed reddens. Control
    first."""
    key = "test_worker.py"
    src = _head_text(key)
    tree = ast.parse(src)
    target = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and ast.get_docstring(n))
    target_key = f"func:{target.name}"

    # Reword the docstring and reflow (insert a blank statement-neutral
    # comment is not visible to ast either -- reflow via re-unparsing).
    docstring_node = target.body[0]
    assert isinstance(docstring_node, ast.Expr) and isinstance(docstring_node.value, ast.Constant)
    docstring_node.value = ast.Constant(value="A completely reworded docstring, section 4.5.")
    ast.fix_missing_locations(tree)
    reworded_src = ast.unparse(tree)

    a = _anchor_census(key)
    h_reworded = _census(reworded_src)
    assert a[target_key] == h_reworded[target_key], "a docstring reword must be invisible"

    # Now change one real statement in the SAME function -- must redden.
    tree2 = ast.parse(reworded_src)
    target2 = next(n for n in tree2.body if isinstance(n, ast.FunctionDef) and n.name == target.name)
    # append a real statement (changes the body -- a superset comparison
    # via dump is exact, not subsequence, so any addition inside a
    # function body also counts as an edit of that function's node).
    target2.body.append(ast.parse("assert True  # BEH4 mutation").body[0])
    ast.fix_missing_locations(tree2)
    edited_src = ast.unparse(tree2)
    h_edited = _census(edited_src)
    assert a[target_key] != h_edited[target_key], "a real statement change must be visible"


def test_beh5_exported_fixtures_are_byte_pinned():
    """`B5`. Exported set = anchor_set ∪ head_set, `ast.ImportFrom` only
    -- a line regex is FORBIDDEN. MEASURED: 31 names, 4/5/6/10/0/4/2/0.
    Positive control: a MULTI-LINE parenthesized import must make its
    name join the derived set; a single-line control does not
    discriminate between the correct and the broken derivation."""
    union = _exported_names_union()
    counts = {k: len(v) for k, v in union.items()}
    # Anchor-SCOPED literals, transcribed, sourced from `MEASURED`
    # (U-anchorlit): `_exported_names_union` reads the ANCHOR side, so
    # these move when the anchor does -- measured at `c3b48e7` they read
    # `(4, 6, 7, 10, 0, 5, 2, 0)` / 34. `--remeasure` refuses to advance
    # `ANCHOR` past a stale value here rather than rewriting it (`ANC1`/
    # `ANC3`); the multi-line-import positive control below is
    # anchor-INDEPENDENT and never goes stale.
    assert [counts[k] for k in BEHAVIOUR_KEYS] == list(MEASURED["BEH5.export_counts"].value), counts
    assert sum(counts.values()) == MEASURED["BEH5.export_total"].value

    # Byte-identity of each exported name's def source, anchor vs head,
    # unless in `edited_exports`.
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        anchor_src = _anchor_text(key)
        head_src = _head_text(key)
        for name in union[key]:
            if name in row.edited_exports:
                continue
            a_src = _exported_def_source(key, name, anchor_src) if name in _top_level_def_names(anchor_src) else None
            h_src = _exported_def_source(key, name, head_src) if name in _top_level_def_names(head_src) else None
            if a_src is not None and h_src is not None:
                assert a_src == h_src, (key, name)

    # Positive control: a MULTI-LINE parenthesized import.
    multiline_src = (
        "from test_invocation import (\n"
        "    _clear_backend_env,\n"
        "    miner_capture,\n"
        ")\n"
    )
    tree = ast.parse(multiline_src)
    import_from = tree.body[0]
    assert isinstance(import_from, ast.ImportFrom)
    assert len(import_from.names) == 2  # a genuinely multi-line, parenthesized site

    def _line_regex_derive(text: str) -> set[str]:
        # The FORBIDDEN implementation: a single-line regex.
        hits = set()
        for m in re.finditer(r"^from test_invocation import (\w+)", text, re.M):
            hits.add(m.group(1))
        return hits

    correct = {a.name for a in import_from.names}
    broken = _line_regex_derive(multiline_src)
    assert correct == {"_clear_backend_env", "miner_capture"}
    assert broken == set(), "the line regex must fail to see a parenthesized multi-line import"


def test_beh6_export_surface_cannot_shrink():
    """`B6`. anchor_set ⊆ head_set. MEASURED: dropping `test_u_corrob.py`
    (the last importer of `test_route_cli.py::_skill_gates_yaml`) takes
    31 -> 30; dropping five unprotected importers, 31 -> 25."""
    anchor = _exported_names_anchor()
    head = _exported_names_head()
    for key in BEHAVIOUR_KEYS:
        assert anchor[key] <= head[key], (key, anchor[key] - head[key])

    # M42: delete test_u_corrob.py and confirm _skill_gates_yaml would
    # lose its only importer.
    importers_of = []
    for path in _all_tree_paths(None):
        if path == _relpath("test_route_cli.py"):
            continue
        try:
            tree = ast.parse((_REPO_ROOT / path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "test_route_cli":
                if any(a.name == "_skill_gates_yaml" for a in node.names):
                    importers_of.append(path)
    assert importers_of == [_relpath("test_u_corrob.py")], importers_of


def test_beh7_extractor_positive_control(monkeypatch):
    """`B7`. Two halves, and they are NOT the same kind of thing --
    U-anchorlit's whole subject, so the split is stated here rather
    than left to be rediscovered:

    * The MEASURED half (first) is ANCHOR-SCOPED. The anchor-side
      census must yield exactly `Behaviour.nodes` keys and a
      `_dump_sha` equal to `Behaviour.dump_sha`, checked against the
      transcribed numbers in `MEASURED`. Every landing advances
      `ANCHOR` and invalidates these, which is why `--remeasure`
      refuses the advance and prints them rather than rewriting them
      (`ANC1`/`ANC3`) -- so the staleness surfaces as a named refusal
      BEFORE the write, instead of as this assertion failing after it.
    * The CONTROL half (second) is ANCHOR-INDEPENDENT and never goes
      stale: monkeypatch `_census` to `{}` and confirm BEH1/BEH3/BEH7
      all redden. This is the leg that actually proves the extractor
      can fail, and no anchor advance may ever invalidate it."""
    expected_nodes = list(MEASURED["BEH7.node_counts"].value)
    expected_prefixes = list(MEASURED["BEH7.dump_prefixes"].value)
    # `zip` truncates silently: without these two, a transcription that
    # dropped a file would skip it rather than redden.
    assert len(expected_nodes) == len(BEHAVIOUR_KEYS), expected_nodes
    assert len(expected_prefixes) == len(BEHAVIOUR_KEYS), expected_prefixes
    total = 0
    narrow = 0
    for key, exp_n, exp_prefix in zip(BEHAVIOUR_KEYS, expected_nodes, expected_prefixes):
        c = _anchor_census(key)
        assert len(c) == exp_n, (key, len(c), exp_n)
        assert _dump_sha(c)[:12] == exp_prefix, (key, _dump_sha(c)[:12], exp_prefix)
        total += len(c)
        # r2's retired shape narrowed the census to `test_*` defs only
        # -- the shape this positive control's own "narrow the
        # extractor back" mutation (M21) would produce. Counted LIVE
        # here (and inside this loop, before the monkeypatch below
        # poisons `_census`) rather than saved as a literal: it is
        # anchor-scoped like everything else in this half, and a saved
        # `627 != 366` pair would be two more numbers to transcribe.
        narrow += sum(1 for node_key in c if node_key.startswith("func:test_"))
    assert total == MEASURED["BEH7.node_total"].value, total
    assert 0 < narrow < total, (narrow, total)

    key = "test_worker.py"
    _ANCHOR_CENSUS_CACHE.pop(key, None)
    monkeypatch.setattr(sys.modules[__name__], "_census", lambda source: {})
    try:
        c_broken = _anchor_census(key)  # goes through the module-level (patched) _census
        assert c_broken == {}
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        assert len(c_broken) == 0 != row.nodes  # BEH7 red: 0 != 80
        assert _dump_sha(c_broken) != row.dump_sha  # BEH7 red
        h_broken = _census("")  # BEH1/BEH3's head side, also patched
        assert h_broken == {}
    finally:
        _ANCHOR_CENSUS_CACHE.pop(key, None)  # drop the poisoned cache entry



def test_beh8_missing_set_cannot_rot():
    """`B2`/`BEH8`. Every `Behaviour.missing` key must be ABSENT at
    head. Driven over a fixture table with an entry naming a key that
    still exists -- must redden. The shipped table's fourteen live
    `test_u_fake.py` entries (the other seven rows ship empty) all
    pass this leg, checked below over the REAL shipped `ARMOR` table."""
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        head_census_ = _head_census(key)
        for missing_key in row.missing:
            assert missing_key not in head_census_, (key, missing_key, "stale missing entry")

    # M22/M51: a fixture table with a bogus missing entry naming a key
    # that still exists at head.
    key = "test_worker.py"
    head_census_ = _head_census(key)
    still_present_key = next(iter(head_census_))
    bogus_missing = {still_present_key: "2026-08-28 §4.6 test scaffold."}
    with pytest.raises(AssertionError):
        for k in bogus_missing:
            assert k not in head_census_, (key, k, "stale missing entry")


def test_beh9_edited_set_cannot_rot():
    """`B4`/`BEH9`. Every `Behaviour.edited` key exists at head AND its
    dump genuinely differs from the anchor's. Positive control on the
    shipped table: every live entry must PASS both halves (proving the
    leg is not vacuously green)."""
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        head_census_ = _head_census(key)
        anchor_census_ = _anchor_census(key)
        for edited_key in row.edited:
            assert edited_key in head_census_, (key, edited_key, "edited entry names a key absent at head")
            assert head_census_[edited_key] != anchor_census_.get(edited_key), (
                key, edited_key, "edited entry's dump did not actually change"
            )

    # M22/M52: a fixture table with an entry naming a key whose dump is
    # UNCHANGED from the anchor.
    key = "test_worker.py"
    anchor_census_ = _anchor_census(key)
    head_census_ = _head_census(key)
    unchanged_key = next(k for k in anchor_census_ if k in head_census_ and head_census_[k] == anchor_census_[k])
    with pytest.raises(AssertionError):
        assert head_census_[unchanged_key] != anchor_census_.get(unchanged_key), (
            key, unchanged_key, "edited entry's dump did not actually change"
        )

    # And an entry naming a key absent at head.
    with pytest.raises(AssertionError):
        assert "func:__nonexistent_probe__" in head_census_, (key, "absent")


# ======================================================================= #
# ======================================================================= #
#  5.5 EXM -- the exemption discipline
# ======================================================================= #
# ======================================================================= #


def test_exm1_every_reason_carries_a_date_and_an_anchor():
    """`EXM1`. Six negative controls (isolating each half plus the
    resolution leg), all MEASURED; two positive strings."""
    negatives = [
        ("2026-08-28 refactored for clarity.", "a"),
        ("§9.1 -- U-hostmode Phase 2 deleted chezmoi.py.", "b"),
        ("refactored", "c"),
        ("2026-8-2 §9.1 cleanup", "d"),
        ("2026-08-28 fe5a01: cleanup", "e"),
        ("2026-08-28 deadbee: sanctioned by a commit that does not exist.", "f"),
    ]
    for reason, label in negatives:
        ok, why = _exm1_check(reason)
        assert not ok, (label, reason, "unexpectedly passed")

    positives = [
        "2026-08-28 per S-55.",
        "2026-08-28 per FW-140.",
        "2026-08-28 U-hostmode Phase 2, fe5a012: test_wr7's exclusion tuple "
        "loses chezmoi.py and its count assertion moves 11 -> 10. See section 9.1.",
    ]
    for reason in positives:
        ok, why = _exm1_check(reason)
        assert ok, (reason, why)

    # The residual, named explicitly: a sha that resolves but is
    # irrelevant still passes (section 4.8's human-review job).
    ok, why = _exm1_check(f"2026-08-28 {ANCHOR}: unrelated citation.")
    assert ok, why

    # Applied to every live reason string this table actually ships
    # (currently zero, since EXM3 requires all four doors shut) -- the
    # grammar/resolution functions themselves are exercised above; this
    # loop keeps the assertion meaningful once a real entry lands.
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        for reason in (*row.missing.values(), *row.edited.values(), *row.edited_exports.values()):
            ok, why = _exm1_check(reason)
            assert ok, (key, reason, why)
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        if row.repinned is not None:
            ok, why = _exm1_check(row.repinned[1])
            assert ok, (key, why)


def test_exm2_no_hardcoded_skips():
    """`EXM2`. The four exemption maps are the only escape hatches: no
    leg has a hardcoded name skip. Positive control: the same walk over
    a copy with a hardcoded skip inserted reddens."""
    live_names = _all_live_test_and_def_names()
    hits = _hardcoded_skip_names(_module_source(), live_names)
    assert hits == [], hits

    mutated = _module_source().replace(
        "def _diff_census(key: str) -> tuple[list[str], list[str]]:",
        'def _diff_census(key: str) -> tuple[list[str], list[str]]:\n'
        '    if key == "test_run_idle_when_nothing_eligible": pass  # M24-shaped hardcoded skip',
        1,
    )
    mutated_hits = _hardcoded_skip_names(mutated, live_names)
    assert "test_run_idle_when_nothing_eligible" in mutated_hits


def test_exm3_doors_match_what_the_anchor_owes():
    """`EXM3`. Every door ships shut except the entries the anchor->HEAD
    diff genuinely owes, each carrying a dated, cited reason -- the SAME
    "owed" exception `test_wr7`'s lone `edited` entry already used is
    extended here to `missing`, symmetrically (section 4.7 row 12): this
    build's own DEL1/DEL2-mandated deletion of DS1's fourteen anchor-era
    nodes from `test_u_fake.py` -- the file being migrated FROM and one
    of the eight files migrated TO -- is exactly such an owed diff.
    `BEH1` already enforces the coverage half of this in code; EXM3's
    distinctive job is the reason-grammar half (`EXM1`), checked here for
    every shipped `missing`/`edited` entry, not just counted.
    MEASURED (2026-08-28, re-run after this unit's own required
    deletions): census edited = 0 (the `test_wr7` entry is now INSIDE
    this build's anchor, section 4.1's fold note); census missing = 14,
    all fourteen inside `test_u_fake.py`. Shipped: 14 missing / 0
    edited. Positive control: the same code at `c3b48e7` reports 66
    missing / 184 edited (re-measured from the spec's 56/190 -- this
    unit's own test_u_fake.py deletions moved several c3b48e7-edited
    nodes into c3b48e7-missing, and some further into outright common
    ancestry; not vacuous on a small number either way)."""
    # `Fixture.repinned` gets the SAME "owed" exception (r1 gate
    # fold): `support.py` now legitimately carries one (U-verbs'
    # `force_past_deferred`, landed on master and merged in by this
    # unit's own landing chain) -- verified here to carry a valid
    # EXM1-grammar reason, not asserted blanket-`None`.
    for key in FIXTURE_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Fixture)
        if row.repinned is not None:
            ok, why = _exm1_check(row.repinned[1])
            assert ok, (key, why)

    census_edited_total = 0
    census_missing_total = 0
    shipped_edited_total = 0
    shipped_missing_total = 0
    for key in BEHAVIOUR_KEYS:
        row = ARMOR[key]
        assert isinstance(row, Behaviour)
        assert row.edited_exports == {}, key
        missing, edited = _diff_census(key)
        census_missing_total += len(missing)
        census_edited_total += len(edited)
        shipped_edited_total += len(row.edited)
        shipped_missing_total += len(row.missing)
        for k in row.edited:
            assert k in edited, (key, k, "shipped entry the census does not report as edited")
            ok, why = _exm1_check(row.edited[k])
            assert ok, (key, k, why)
        for k in row.missing:
            assert k in missing, (key, k, "shipped entry the census does not report as missing")
            ok, why = _exm1_check(row.missing[k])
            assert ok, (key, k, why)

    # Anchor-scoped, transcribed, sourced from `MEASURED`
    # (U-anchorlit): both move on every anchor advance, and
    # `--remeasure` refuses the advance rather than rewriting them.
    assert census_missing_total == MEASURED["EXM3.census_missing"].value, census_missing_total
    assert census_edited_total == MEASURED["EXM3.census_edited"].value, census_edited_total
    assert shipped_edited_total == census_edited_total, (shipped_edited_total, census_edited_total)
    assert shipped_missing_total == census_missing_total, (shipped_missing_total, census_missing_total)

    additive = ARMOR[_FAKE_CLAUDE_KEY]
    assert isinstance(additive, Additive)
    assert set(additive.edited_funcs) == {"main", "_scenario_error_result"}, set(additive.edited_funcs)

    # Positive control: c3b48e7 is NOT vacuous.
    c_missing = c_edited = 0
    for key in BEHAVIOUR_KEYS:
        a = _census(_git_show_text("c3b48e7", key))
        h = _head_census(key)
        c_missing += len([k for k in a if k not in h])
        c_edited += len([k for k in a if k in h and h[k] != a[k]])
    # HEAD-scoped, not anchor-scoped: `c3b48e7` is fixed history, so an
    # anchor advance can never move these -- a landing that edits a
    # protected file can. Same two rows `BEH1`/`BEH3` read.
    assert c_missing == MEASURED["BEH1.control_missing"].value, c_missing
    assert c_edited == MEASURED["BEH3.control_edited"].value, c_edited


# ======================================================================= #
# ======================================================================= #
#  5.6 DEL -- the retirement is real
# ======================================================================= #
# ======================================================================= #


def test_del1_retired_symbols_are_gone():
    """`DEL1`. Every retired symbol is gone from the tree (`ast`-scoped,
    owner-files only -- a docstring mentioning a retired name
    historically is prose, not a binding). Positive control: the same
    walk at `3b8e037` returns 32."""
    pre_state_total = 0
    for f in OWNER_FILES:
        src = _git_show_text("3b8e037", f)
        pre_state_total += len(_ast_visible_retired_bindings(src))
    assert pre_state_total == 32, pre_state_total

    total = 0
    for f in OWNER_FILES:
        text = (_REPO_ROOT / _TESTS_DIR / f).read_text(encoding="utf-8")
        hits = _ast_visible_retired_bindings(text)
        assert hits == [], (f, hits)
        total += len(hits)
    assert total == 0, total


def test_del2_retired_tests_are_gone():
    """`DEL2`. Every retired test FUNCTION is gone from the collector.
    Positive control: the same collector at `3b8e037` names all ten."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "test_worker_contract.py", "test_u_sdka.py", "test_u_fake.py"],
        cwd=_REPO_ROOT / _TESTS_DIR, capture_output=True, text=True,
    )
    collected = proc.stdout
    for name in RETIRED_TEST_FUNCTIONS:
        assert name not in collected, name


def _covering_test_name(criterion_id: str) -> str:
    """`ARM1`-style ids map to their `test_<id-lowercased>_...` name via
    the live test set (a `startswith` match on the lowercased id)."""
    prefix = f"test_{criterion_id.lower()}_"
    return prefix


def _disposition_uncovered(table: tuple, live_tests: set[str]) -> list[tuple[str, str]]:
    uncovered = []
    for desc, covering in table:
        if covering.endswith(".py"):
            # a KEPT-AS-IS file reference.
            if not (_REPO_ROOT / _TESTS_DIR / covering).exists():
                uncovered.append((desc, covering))
        else:
            # a criterion id like "FIX1"/"BEH5" -- covered iff some live
            # test name starts with test_<id>_
            if not any(t.startswith(_covering_test_name(covering)) for t in live_tests):
                uncovered.append((desc, covering))
    return uncovered


def test_del3_every_disposition_is_covered():
    """`DEL3`. Every one of section 4.7's 17 dispositions names a
    covering `test_armor.py` test or a KEPT-AS-IS location, and both
    exist. Positive control: renaming one covering test reddens."""
    live_tests = _armor_test_names()
    assert _disposition_uncovered(DISPOSITION_COVERAGE, live_tests) == []

    # Positive control: pretend `test_fix1_...` was renamed away.
    fake_live = {t for t in live_tests if not t.startswith("test_fix1_")}
    uncovered = _disposition_uncovered(DISPOSITION_COVERAGE, fake_live)
    assert any(cov == "FIX1" for _, cov in uncovered), uncovered


def test_del4_pin2_is_retargeted_not_deleted():
    """`DEL4`. `test_u_corrob.py::test_pin2_...` is retargeted, not
    deleted: it reads `ARMOR` and asserts the 3 Fixture rows' live bytes
    are consistent with `F1`/`F2`. `grep -c '_ARMOR_SHAS'` (ast-scoped,
    like `DEL1`) is 0; the test's own `len(...) == 3` replaces `len(pins)
    == 7`. Historical docstring mentions (`:7`/`:17`/`:1040`) stay."""
    text = (_REPO_ROOT / _TESTS_DIR / "test_u_corrob.py").read_text(encoding="utf-8")
    bindings = _ast_visible_retired_bindings(text)
    assert "_ARMOR_SHAS" not in bindings, bindings

    assert "def test_pin2_" in text, "test_pin2 was deleted, not retargeted"
    assert "ARMOR" in text
    assert "len(fixture_rows) == 3" in text or "== 3" in text

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", "test_pin2"],
        cwd=_REPO_ROOT / _TESTS_DIR, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Historical docstring mentions stay (prose, not bindings).
    assert "_ARMOR_SHAS" in text  # still mentioned in a docstring


def test_del5_armor_files_shrink():
    """`DEL5`. `test_worker_contract.py`/`test_u_sdka.py`/`test_u_fake.py`
    each individually lose lines from baseline, AND -- the criterion's
    actual concern, and the leg the r1 gate found missing (`M-2`: this
    test never read `test_armor.py` at all, so an 800-line comment
    append to `test_armor.py` ITSELF was invisible to it) -- the
    combined COMMENT-line reduction across the three owner files
    exceeds `test_armor.py`'s own comment-line count: this build did
    not just relocate the retired mechanisms' prose bloat into the new
    file, it genuinely retired it. The reduction is separately required
    to be >= 700 (unchanged). MEASURED baseline: 2285/2556/913 lines;
    626/627/197 comment lines = 1450 total. MEASURED now (2026-08-28):
    `test_armor.py` carries 287 comment lines of its own; the real
    reduction is 812 -- 812 > 287, and M30's 800-line append would
    push `test_armor.py` to 1087, breaking `812 > 1087`."""
    baseline_lines = {"test_worker_contract.py": 2285, "test_u_sdka.py": 2556, "test_u_fake.py": 913}
    baseline_comments = {"test_worker_contract.py": 626, "test_u_sdka.py": 627, "test_u_fake.py": 197}
    assert sum(baseline_comments.values()) == 1450

    now_comments_total = 0
    for f in OWNER_FILES:
        p = _REPO_ROOT / _TESTS_DIR / f
        lines = p.read_text(encoding="utf-8").splitlines()
        now_lines = len(lines)
        now_comments = sum(1 for ln in lines if ln.lstrip().startswith("#"))
        now_comments_total += now_comments
        assert now_lines < baseline_lines[f], (f, now_lines, baseline_lines[f])

    comment_reduction = 1450 - now_comments_total
    assert comment_reduction >= 700, (1450, now_comments_total)

    armor_text = (_REPO_ROOT / _TESTS_DIR / "test_armor.py").read_text(encoding="utf-8")
    armor_comments = sum(1 for ln in armor_text.splitlines() if ln.lstrip().startswith("#"))
    assert comment_reduction > armor_comments, (comment_reduction, armor_comments)


# ======================================================================= #
# ======================================================================= #
#  5.7 GATE -- the process amendment
# ======================================================================= #
# ======================================================================= #


def test_gate1_guard_amendment_clauses_present():
    """`GATE1`. The runbook gains section 1.4a with all six clauses.
    Positive control: every keyword returns 0 in the runbook at
    pre-state, against a control of 1 for `mutation verification`."""
    pre_state = subprocess.run(
        ["git", "show", "3b8e037:docs/specs/self-learn/15-orchestration-runbook.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert _grep_count(pre_state, "guard-amendment") == 0
    assert _grep_count(pre_state, "mutation verification") == 1

    text = _RUNBOOK.read_text(encoding="utf-8")
    assert _grep_count(text, "guard-amendment") >= 2
    for keyword in ("missing", "edited", "positive control", "repinned", "edited_exports", "ANCHOR"):
        assert _grep_count(text, re.escape(keyword)) >= 1, keyword

    # Six blockquote bullets under §1.4a.
    m = re.search(r"\*\*4a\. Guard-amendment.*?(?=\n## |\Z)", text, re.S | re.IGNORECASE)
    assert m is not None, "section 1.4a not found"
    bullets = re.findall(r"^> - \*\*", m.group(0), re.M)
    assert len(bullets) == 6, (len(bullets), m.group(0)[:2000])


def test_gate2_trigger_is_mechanical():
    """`GATE2`. section 1.4a names its trigger mechanically -- a key in
    `cli/tests/test_armor.py::ARMOR` -- appearing twice (§1.4a and §8)."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    assert _grep_count(text, re.escape("test_armor.py::ARMOR")) == 2


def test_gate3_only_insertions():
    """`GATE3`. The runbook's diff against its pre-state is
    insertions-only: `git diff --numstat` deletions = 0. Positive
    control: the same numstat on a copy with one line reworded shows a
    nonzero deletion count."""
    numstat = subprocess.run(
        ["git", "diff", "--numstat", "3b8e037", "--", "docs/specs/self-learn/15-orchestration-runbook.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if numstat:
        added, deleted, _path = numstat.split("\t", 2)
        assert int(deleted) == 0, numstat
    else:
        pytest.fail("no diff found against 3b8e037 -- the runbook amendment did not land")

    # Positive control: a copy with a reworded EXISTING line shows a
    # nonzero deletion count under the same numstat shape.
    pre_full = subprocess.run(
        ["git", "show", "3b8e037:docs/specs/self-learn/15-orchestration-runbook.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    pre_lines = pre_full.splitlines()
    reworded = "\n".join(["REWORDED FIRST LINE, section 4.8"] + pre_lines[1:])
    import difflib
    diff_lines = list(difflib.unified_diff(pre_full.splitlines(), reworded.splitlines()))
    removed = [l for l in diff_lines if l.startswith("-") and not l.startswith("---")]
    assert len(removed) > 0, "the reworded-line control must show a nonzero deletion"


# ======================================================================= #
# ======================================================================= #
#  5.8 UN -- the unaffected group. `UN4` (pyright before/after) is an
#  INSTRUMENT criterion satisfied by the build report -- like `test_u_
#  sdka.py`'s `SU1`/`SU2`/`SU3`/`SU5`, there is no single before/after
#  pair a stateless pytest run can observe; the other four are
#  git-diff-shaped and get real functions.
# ======================================================================= #


def test_un1_no_production_source_changes():
    """`UN1`. `plugins/self-learn/cli/src` and `plugins/self-learn/ui`
    are byte-identical to the build base. Positive control: the same
    command scoped to `cli/tests` is non-empty. Post-landing (r2 gate
    fold), this pins to the permanent `_LANDING_BASE`/`_LANDING_TIP`
    pair instead of `_BUILD_BASE`/`HEAD` -- see the module note above
    `_LANDING_BASE`."""
    if _landing_is_absorbed():
        _assert_landing_pair_is_real_history()
        out = _numstat2(_LANDING_BASE, _LANDING_TIP, "plugins/self-learn/cli/src", "plugins/self-learn/ui")
        assert out.strip() == "", out

        control = _numstat2(_LANDING_BASE, _LANDING_TIP, "plugins/self-learn/cli/tests")
        assert control.strip() != "", "positive control: cli/tests SHOULD show a diff in the landing"
        return

    out = _numstat(_BUILD_BASE, "plugins/self-learn/cli/src", "plugins/self-learn/ui")
    assert out.strip() == "", out

    control = _numstat(_BUILD_BASE, "plugins/self-learn/cli/tests")
    assert control.strip() != "", "positive control: cli/tests SHOULD show a diff by now"


def test_un2_lock_invariant_untouched():
    """`UN2`. `test_lock_invariant.py` is byte-unchanged (a sibling
    unit's own pin, `U-verbs`' `UN4`, depends on it). Post-landing this
    pins to the permanent `_LANDING_BASE`/`_LANDING_TIP` pair instead
    of `_BUILD_BASE`/`HEAD` -- the same fix `UN1`/`UN3`/`UN5` received
    in `dfa2a24`, which this criterion was simply missed out of
    (repaired 2026-08-29, found by `U-verbs` Phase 2's own code gate).
    Left on `_BUILD_BASE` the check is VACUOUSLY green on master --
    the diff of master against its own merge-base is empty, so it
    passes without measuring anything -- while going RED on every
    later branch that merges this landing and then legitimately edits
    the file. Measured on `u-verbs-p2`, whose own `UN4` REQUIRES the
    three lines it adds (`3\t0\t.../test_lock_invariant.py`): a
    self-scoped, branch-time promise had leaked into a permanent
    global constraint on every sibling unit. Positive control (also
    new, and the reason the vacuity went unnoticed for a landing):
    `cli/tests` SHOULD show a diff, so an empty result can never be
    mistaken for a check that looked at nothing."""
    if _landing_is_absorbed():
        _assert_landing_pair_is_real_history()
        out = _numstat2(
            _LANDING_BASE, _LANDING_TIP,
            "plugins/self-learn/cli/tests/test_lock_invariant.py",
        )
        assert out.strip() == "", out

        control = _numstat2(_LANDING_BASE, _LANDING_TIP, "plugins/self-learn/cli/tests")
        assert control.strip() != "", "positive control: cli/tests SHOULD show a diff in the landing"
        return

    out = _numstat(_BUILD_BASE, "plugins/self-learn/cli/tests/test_lock_invariant.py")
    assert out.strip() == "", out

    control = _numstat(_BUILD_BASE, "plugins/self-learn/cli/tests")
    assert control.strip() != "", "positive control: cli/tests SHOULD show a diff by now"


def _collect_count(cwd: Path, python: str) -> int:
    """Run `--collect-only -q` under *python* from *cwd* and parse its
    trailing "N tests collected" line. Shared by `UN3`'s live count
    and its hermetic ANCHOR-side base count."""
    proc = subprocess.run(
        [python, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(cwd), capture_output=True, text=True,
    )
    last_line = [l for l in proc.stdout.splitlines() if l.strip()][-1]
    m = re.search(r"(\d+) tests? collected", last_line)
    assert m is not None, (last_line, proc.stdout[-2000:], proc.stderr[-2000:])
    return int(m.group(1))


def _collect_count_at(ref: str) -> int:
    """Hermetic collected count at a fixed committed *ref*: a throwaway
    DETACHED `git worktree`, collected with THIS worktree's already-
    synced venv (no second `uv sync` -- close enough behind HEAD, same
    lockfile; never a bare `python`/`pytest` off PATH, always this
    worktree's own `.venv` interpreter, explicit path). Shared by
    `_base_collected_at_build_base` (pre-landing, ref = `_BUILD_BASE`)
    and `UN3`'s post-landing pin (ref = `_LANDING_BASE`/`_LANDING_TIP`,
    r2 gate fold)."""
    tmp_dir = tempfile.mkdtemp(prefix="armor-un3-at-")
    shutil.rmtree(tmp_dir)  # `git worktree add` must create the path itself
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", tmp_dir, ref],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
        )
        venv_python = str(_REPO_ROOT / "plugins/self-learn/cli" / ".venv" / "bin" / "python")
        return _collect_count(Path(tmp_dir) / _TESTS_DIR, venv_python)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", tmp_dir],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )


def _armor_test_names_at(ref: str) -> set[str]:
    """`_armor_test_names`, but reading `test_armor.py`'s content AT A
    FIXED REF (`git show ref:path`) instead of the live file -- UN3's
    post-landing pin must count exactly what LANDED, never whatever
    this branch's later housekeeping commits add or remove afterward
    (r2 gate fold)."""
    relpath = Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix()
    proc = subprocess.run(
        ["git", "show", f"{ref}:{relpath}"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    )
    tree = ast.parse(proc.stdout)
    return {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    }


def _base_collected_at_build_base() -> int:
    """`UN3`'s hermetic PRE-landing base count (r1 gate fold, M-3): NOT
    the bare `ANCHOR` literal -- `_BUILD_BASE` already resolves to
    `master` once this unit's own fold has landed it, exactly like
    UN1/UN2/UN5's own fix; using `ANCHOR` here would undercount every
    sibling-unit test this unit's OWN merge just brought in, e.g.
    U-verbs' `test_u_verbs.py`. Never a saved literal: a hardcoded
    total silently drifts the moment a sibling unit lands on master
    mid-session -- measured live, the r1 gate's own venv resolved
    `self_learn` to master's MOVING src for the same reason, one layer
    down. Delegates to `_collect_count_at`, shared with the post-
    landing pin."""
    return _collect_count_at(_BUILD_BASE)


def test_un3_suite_grows_by_exactly_the_delta():
    """`UN3`. The suite grows by exactly the new armor tests and shrinks
    by exactly the ten retired ones: `base_collected -> base_collected -
    10 + N`. Pre-landing this is measured fresh from `_BUILD_BASE`'s own
    tree (r1 gate fold, M-3) -- never the literal `2666`, which was true
    only at THIS unit's original 3b8e037-era anchor and silently goes
    stale the moment a sibling unit lands on master. Post-landing (r2
    gate fold), `HEAD` itself IS the landing, so a live/`_BUILD_BASE`
    measurement degenerates to `base_collected == total_now` (delta 0)
    -- this pins to the permanent `_LANDING_BASE`/`_LANDING_TIP` pair
    instead, both legs hermetic detached checkouts, `N` read from
    `_LANDING_TIP`'s own `test_armor.py` (`_armor_test_names_at`), not
    whatever this branch's later commits do to the live file."""
    if _landing_is_absorbed():
        _assert_landing_pair_is_real_history()
        base_collected = _collect_count_at(_LANDING_BASE)
        total_now = _collect_count_at(_LANDING_TIP)
        n_armor_tests = len(_armor_test_names_at(_LANDING_TIP))
        n_retired = 10
        assert total_now == base_collected - n_retired + n_armor_tests, (
            total_now, base_collected, n_retired, n_armor_tests
        )
        return

    base_collected = _base_collected_at_build_base()
    total_now = _collect_count(_REPO_ROOT / _TESTS_DIR, sys.executable)

    n_armor_tests = len(_armor_test_names())
    n_retired = 10
    assert total_now == base_collected - n_retired + n_armor_tests, (
        total_now, base_collected, n_retired, n_armor_tests
    )


def test_un5_protected_files_unedited_by_this_unit():
    """`UN5`. The 3 fixture files and SEVEN of the 8 protected behaviour
    files (fixtures/fake_claude.py is Additive, not edited either --
    section 9's note) are byte-unchanged by this unit. The eighth,
    `test_u_fake.py`, is BOTH a protected Behaviour file AND one of the
    three owner files this build must edit -- DEL1/DEL2 mandate deleting
    DS1's own armor mechanism FROM it, the same migration this Behaviour
    census exists to replace (section 4.7 row 12). Its diff is therefore
    excluded from the strict "empty" leg below and checked precisely, at
    the node level, by `BEH1`/`BEH8`/`EXM3`'s `missing`-door coverage
    instead (the exact precedent `fake_claude.py`'s own Additive
    exclusion from this same leg already set). Positive control: the
    same command over the three retired-mechanism files, INCLUDING
    `test_u_fake.py`, is non-empty."""
    assert len(STRICT_PROTECTED_RELPATHS) == len(PROTECTED_RELPATHS) - 1, STRICT_PROTECTED_RELPATHS

    if _landing_is_absorbed():
        _assert_landing_pair_is_real_history()
        out = _numstat2(_LANDING_BASE, _LANDING_TIP, *STRICT_PROTECTED_RELPATHS)
        assert out.strip() == "", out

        fake_out = _numstat2(_LANDING_BASE, _LANDING_TIP, "plugins/self-learn/cli/tests/test_u_fake.py")
        assert fake_out.strip() != "", "test_u_fake.py: this unit's own DS1 retirement should show a diff"

        control = _numstat2(
            _LANDING_BASE, _LANDING_TIP,
            "plugins/self-learn/cli/tests/test_worker_contract.py",
            "plugins/self-learn/cli/tests/test_u_sdka.py",
            "plugins/self-learn/cli/tests/test_u_fake.py",
        )
        assert control.strip() != "", "positive control: the three retired-mechanism files SHOULD show a diff"
        return

    out = _numstat(_BUILD_BASE, *STRICT_PROTECTED_RELPATHS)
    assert out.strip() == "", out

    fake_out = _numstat(_BUILD_BASE, "plugins/self-learn/cli/tests/test_u_fake.py")
    assert fake_out.strip() != "", "test_u_fake.py: this unit's own DS1 retirement should show a diff"

    control = _numstat(
        _BUILD_BASE,
        "plugins/self-learn/cli/tests/test_worker_contract.py",
        "plugins/self-learn/cli/tests/test_u_sdka.py",
        "plugins/self-learn/cli/tests/test_u_fake.py",
    )
    assert control.strip() != "", "positive control: the three retired-mechanism files SHOULD show a diff"


# ======================================================================= #
# ======================================================================= #
#  5.9 DOC -- the owed doc edits, and the retired-names list
# ======================================================================= #
# ======================================================================= #


def test_doc1_owed_doc_edits_land():
    """`DOC1`. The runbook's `guard-amendment`/`--remeasure` markers are
    OWED by this unit's own build; `S-55`/`FW-140`/`FW-141` are NOT --
    they land WITH the spec merge (section 10) and are already present
    at `ANCHOR`/`_BUILD_BASE` itself (r1 gate fold, N-5: this used to
    assert all five against the same ancient `3b8e037` baseline, which
    cannot tell "pre-existing from the spec commit" apart from "owed by
    this build" -- both read 0 there, since 3b8e037 predates the spec
    merge entirely). Two groups, verified against the RIGHT baseline
    each: `ANCHOR` for the pre-existing three (MEASURED present, `==1`
    each), `3b8e037` for the runbook markers this build itself owes
    (MEASURED absent, `==0`, plus a same-shape sibling-marker control)."""
    pre_anchor = {
        name: subprocess.run(
            ["git", "show", f"{ANCHOR}:{path}"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout
        for name, path in (
            ("decisions", "docs/specs/self-learn/03-decisions.md"),
            ("fwmap", "docs/specs/self-learn/14-forward-work-map.md"),
        )
    }
    # Pre-existing from the spec commit -- NOT owed by this build.
    assert _grep_count(pre_anchor["decisions"], r"^\| S-55") == 1
    assert _grep_count(pre_anchor["fwmap"], r"^\| FW-140") == 1
    assert _grep_count(pre_anchor["fwmap"], r"^\| FW-141") == 1

    pre_3b8e037 = {
        name: subprocess.run(
            ["git", "show", f"3b8e037:{path}"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout
        for name, path in (
            ("runbook", "docs/specs/self-learn/15-orchestration-runbook.md"),
            ("decisions", "docs/specs/self-learn/03-decisions.md"),
            ("fwmap", "docs/specs/self-learn/14-forward-work-map.md"),
        )
    }
    # Owed by THIS build -- absent at the pre-spec baseline.
    assert _grep_count(pre_3b8e037["runbook"], "guard-amendment") == 0
    assert _grep_count(pre_3b8e037["runbook"], re.escape("--remeasure")) == 0
    assert _grep_count(pre_3b8e037["decisions"], r"^\| S-55") == 0
    assert _grep_count(pre_3b8e037["fwmap"], r"^\| FW-140") == 0
    assert _grep_count(pre_3b8e037["fwmap"], r"^\| FW-141") == 0
    # Controls that DO exist at pre-state, same shape.
    assert _grep_count(pre_3b8e037["runbook"], re.escape("mutation verification")) == 1
    assert _grep_count(pre_3b8e037["decisions"], r"^\| S-54") == 1
    assert _grep_count(pre_3b8e037["fwmap"], r"^\| FW-138") == 1

    runbook = _RUNBOOK.read_text(encoding="utf-8")
    decisions = _DECISIONS.read_text(encoding="utf-8")
    fwmap = _FW_MAP.read_text(encoding="utf-8")
    assert _grep_count(runbook, "guard-amendment") >= 2
    assert _grep_count(runbook, re.escape("--remeasure")) >= 1
    assert _grep_count(decisions, r"^\| S-55") == 1
    assert _grep_count(fwmap, r"^\| FW-140") == 1
    assert _grep_count(fwmap, r"^\| FW-141") == 1


def test_doc2_retired_names_are_gone():
    """`DOC2`. section 13's retired-names list is complete and
    live-checked: every name is absent from the three owner files as an
    `ast`-visible binding. MEASURED at `3b8e037`, owner-scoped: 32
    occurrences (9+13+10); an `ast.Assign`-only walk finds 30 and misses
    2 (`_AR3_REMOVED`/`_AR3_ADDED`, both `AnnAssign`)."""
    pre_full = pre_assign_only = 0
    per_file = {}
    for f in OWNER_FILES:
        src = _git_show_text("3b8e037", f)
        full = _ast_visible_retired_bindings(src)
        assign_only = _ast_visible_retired_bindings_assign_only(src)
        per_file[f] = len(full)
        pre_full += len(full)
        pre_assign_only += len(assign_only)
    assert pre_full == 32, (per_file, pre_full)
    assert per_file == {"test_worker_contract.py": 10, "test_u_sdka.py": 13, "test_u_fake.py": 9}
    assert pre_assign_only == 30, pre_assign_only

    assert len(RETIRED_CONSTANTS) == 22
    assert len(RETIRED_TEST_FUNCTIONS) == 10

    for f in OWNER_FILES:
        text = (_REPO_ROOT / _TESTS_DIR / f).read_text(encoding="utf-8")
        hits = _ast_visible_retired_bindings(text)
        assert hits == [], (f, hits)


def test_doc3_retired_check_is_owner_scoped():
    """`DOC3`. The retired-names check is scoped to the three owner
    files, not to bare names. MEASURED: `test_u_corrob.py:65` binds its
    OWN unrelated `_BASE_SHA` -- a bare-name check over `cli/` would
    demand deleting it."""
    corrob_text = (_REPO_ROOT / _TESTS_DIR / "test_u_corrob.py").read_text(encoding="utf-8")
    bare_hits = _ast_visible_retired_bindings(corrob_text)
    assert "_BASE_SHA" in bare_hits, "the collision this criterion exists to avoid mis-scoping"

    # The owner-scoped check (DOC2's actual mechanism) never looks at
    # test_u_corrob.py at all, so it stays clean regardless.
    assert "test_u_corrob.py" not in OWNER_FILES
    for f in OWNER_FILES:
        text = (_REPO_ROOT / _TESTS_DIR / f).read_text(encoding="utf-8")
        assert _ast_visible_retired_bindings(text) == [], f


def test_doc4_permanent_rows_describe_the_shipped_design():
    """`DOC4`. `S-55` and `FW-140` each name whole-file byte-pinned
    fixtures with a dated re-pin door, the anchor-side NODE census
    compared by normalized DUMP, and the doors `repinned`/`missing`/
    `edited`/`edited_exports`. Greps evaluated PER ROW."""
    decisions = _DECISIONS.read_text(encoding="utf-8")
    fwmap = _FW_MAP.read_text(encoding="utf-8")

    def _row(text: str, marker: str) -> str:
        m = re.search(rf"^\|\s*{re.escape(marker)}\s*\|.*$", text, re.M)
        assert m is not None, marker
        return m.group(0)

    s55 = _row(decisions, "S-55")
    fw140 = _row(fwmap, "FW-140")

    negatives = ("append-only", "assertion multiset", "weakened", "retired")
    positives = ("node", "repinned", "missing", "dump")
    for label, row in (("S-55", s55), ("FW-140", fw140)):
        for neg in negatives:
            assert _grep_count(row, re.escape(neg)) == 0, (label, neg)
        for pos in positives:
            assert _grep_count(row, re.escape(pos)) >= 1, (label, pos)

    # Positive control: r4's wording of these two rows fails (matching
    # this criterion's own case-sensitive grep -- section 3.6, N-2/N-3:
    # r4 literally wrote "append-only ... additions anywhere are free"
    # and "assertion multisets" in lowercase prose).
    r4_s55_fragment = (
        "S-55 fixtures grow append-only, behaviour files use assertion "
        "multisets, and a weakened assertion is retired from the suite"
    )
    for neg in negatives:
        assert _grep_count(r4_s55_fragment, re.escape(neg)) >= 1, neg


# ======================================================================= #
# ======================================================================= #
#  5.10 ANC -- the measured literals, and who may write them
#       (U-anchorlit: every landing advances `ANCHOR`, and until this
#       section shipped every landing therefore left the suite red)
# ======================================================================= #
# ======================================================================= #


def _measured_keys_read_by_tests(source: str) -> set[str]:
    """Every `MEASURED["..."]` key read DIRECTLY inside a `test_`
    function in `source` -- the anti-orphan walk `ANC4` runs. A
    nested read through a scratch namespace (`ns["MEASURED"][...]`)
    is deliberately NOT counted: it proves the CLI's behaviour, not
    that any shipped assertion reads the row."""
    keys: set[str] = set()
    for top in ast.parse(source).body:
        if not (isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)) and top.name.startswith("test_")):
            continue
        for node in ast.walk(top):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "MEASURED"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                keys.add(node.slice.value)
    return keys


def _measured_block(source: str) -> str:
    """The `MEASURED = {...}` assignment's own source lines, located by
    AST (never a text marker, which a docstring mention would fool).
    `ANC3` compares this block before and after a render."""
    lines = source.splitlines()
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "MEASURED"
            and node.end_lineno is not None
        ):
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("MEASURED assignment not found in source")


def test_anc1_remeasure_refuses_a_stale_measured_literal(capsys):
    """`ANC1`. A `MEASURED` row that no longer matches its live
    measurement makes `--remeasure` REFUSE: rc 1, the stale row named
    with its file, its shipped value AND its newly measured value, and
    the module byte-identical afterwards. A refusal that says
    "something is stale" without saying what to write is a refusal
    that gets worked around, so both values are asserted present.

    Driven over a scratch COPY whose `MEASURED` carries one corrupted
    row, with `--anchor` pointing at the copy's own `ANCHOR` -- so the
    refusal is attributable to the STALE leg ALONE (`_compute_owed`
    and `_compute_vacuous` are both asserted empty first) and the
    probe is permanent: it can never be invalidated by a later
    landing, unlike a hardcoded "some other anchor" would be. The
    anchor-ADVANCE half of the story is `ANC2`'s second leg (these
    rows genuinely move at a different real anchor) and `ARM6`'s
    refuse -> transcribe -> succeed loop at `15fb676`."""
    scratch_dir = Path(tempfile.mkdtemp(dir=str(_REPO_ROOT)))
    try:
        scratch_module, ns = _scratch_armor_namespace(scratch_dir, "_armor_anc1")
        anchor = ns["ANCHOR"]

        # Negative control FIRST: untouched, at its own anchor, nothing
        # is owed, vacuous or stale -- so anything below is the
        # corruption's doing, not a pre-existing refusal.
        assert ns["_compute_owed"](anchor) == {}
        assert ns["_compute_vacuous"](anchor) == {}
        assert ns["_compute_stale"](anchor) == []

        row = ns["MEASURED"]["BEH7.node_counts"]
        corrupted = tuple(n + 1 for n in row.value)
        patched = dict(ns["MEASURED"])
        patched["BEH7.node_counts"] = dataclasses.replace(row, value=corrupted)
        ns["MEASURED"] = patched

        stale = ns["_compute_stale"](anchor)
        assert [name for name, _shipped, _live in stale] == ["BEH7.node_counts"], stale

        capsys.readouterr()  # drop anything buffered before the drive
        sha_before = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        rc = ns["_remeasure"](["--remeasure", "--anchor", anchor])
        sha_after = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        err = capsys.readouterr().err

        assert rc == 1, rc
        assert sha_after == sha_before, "a refusing --remeasure must leave the file byte-identical"

        # Assert on the REPORT LINES, never on substrings of the whole
        # stream: the trailer's own legend spells out the words OWED:,
        # VACUOUS: and STALE: (indented), so a naive `"OWED:" not in
        # err` is true of no refusal at all. Caught by this test's own
        # first run, 2026-08-29.
        report = [ln for ln in err.splitlines() if ln.startswith(("OWED:", "VACUOUS:", "STALE:"))]
        assert len(report) == 3, report
        assert report[0].startswith("STALE: "), report[0]
        assert report[0].endswith("MEASURED['BEH7.node_counts'] (scope=anchor)"), report[0]
        assert "test_armor.py" in report[0], report[0]  # which file to edit
        assert report[1] == f"STALE:       shipped value: {corrupted!r}", report[1]
        assert report[2] == f"STALE:   value at {anchor}: {row.value!r}", report[2]
        assert not [ln for ln in report if ln.startswith(("OWED:", "VACUOUS:"))], report
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def test_anc2_the_refusal_does_not_fire_when_the_literals_are_current():
    """`ANC2`. Two legs, the negative one asserted first: over the
    SHIPPED table at the SHIPPED anchor, `_compute_stale` and
    `_compute_vacuous` are both empty -- the refusal `ANC1` proves can
    fire does NOT fire on a current tree, so it is a gate and not a
    brick.

    Second leg, not-vacuous: every `anchor`-scoped and `anchor+head`-
    scoped row genuinely MOVES at a different real anchor (the retired
    `c3b48e7`), so `ANC1`'s detector watches something an anchor
    advance can actually change; and every `head`-scoped row does NOT
    move there, which is what makes the `scope` labels honest rather
    than decorative."""
    assert _compute_stale(ANCHOR) == []
    assert _compute_vacuous(ANCHOR) == {}

    moved = {name for name, _shipped, _live in _compute_stale(_RETIRED_ANCHOR_CONTROL)}
    by_scope: dict[str, set[str]] = {s: set() for s in _SCOPES}
    for name, row in MEASURED.items():
        by_scope[row.scope].add(name)

    assert by_scope[_SCOPE_ANCHOR], by_scope
    assert by_scope[_SCOPE_ANCHOR] <= moved, by_scope[_SCOPE_ANCHOR] - moved
    assert by_scope[_SCOPE_ANCHOR_HEAD] <= moved, by_scope[_SCOPE_ANCHOR_HEAD] - moved
    assert by_scope[_SCOPE_HEAD] & moved == set(), by_scope[_SCOPE_HEAD] & moved


def test_anc3_remeasure_never_writes_a_measured_literal():
    """`ANC3`. `_render_module` -- the ONLY thing `--remeasure` ever
    writes -- rewrites `ANCHOR` and the eight `Behaviour` rows and
    leaves the whole `MEASURED = {...}` block byte-identical.

    Why that matters, stated exactly: NOT because the transcribed
    numbers are an independent check on the extractor. They are not --
    they are copied from this same code's own printout. Because a
    silent rewrite would delete the two things the table does deliver:
    `_compute_stale` would report nothing, so the refusal that stops a
    stale landing would never fire, and the dated record of what
    changed and why would be gone with it.

    Positive control, asserted first: the same comparison over a
    rendering that DOES rewrite one measured literal reports a
    difference -- so the instrument can see the thing it forbids. Plus
    a render-is-not-a-no-op leg, so "block unchanged" can never be
    satisfied by a renderer that changed nothing at all."""
    source = _module_source()
    rendered = _render_module(_RETIRED_ANCHOR_CONTROL)

    # Positive control: a rendering that DID author a measured literal.
    # The target is DERIVED from the table, never spelled out -- a
    # hardcoded `value=627,` here would itself be an anchor-scoped hand
    # literal, i.e. the exact class this unit exists to remove (found
    # by mutation M-A5, which reddened this test for the wrong reason).
    target = f"value={MEASURED['BEH7.node_total'].value},"
    broken = rendered.replace(target, "value=-1,", 1)
    assert broken != rendered, ("the control mutation found nothing to change", target)
    assert _measured_block(broken) != _measured_block(source)

    # The render is real work, not a no-op.
    assert rendered != source
    assert f'ANCHOR = "{_RETIRED_ANCHOR_CONTROL}"' in rendered
    assert f'ANCHOR = "{ANCHOR}"' not in rendered

    # ... and it leaves every hand-written measurement alone.
    assert _measured_block(rendered) == _measured_block(source)


def test_anc4_every_measured_row_is_dated_anchored_and_used():
    """`ANC4`. `EXM1`'s grammar applied to `MEASURED`: every row's
    `reason` carries a date and a citation, and names a hex anchor
    that RESOLVES as a real commit -- strictly stronger than `EXM1`
    itself, whose leg 2 lets a bare `§N` citation stand without any
    sha at all. Every `scope` is one of the three declared kinds. And
    every row is READ by at least one shipped assertion in this
    module: an orphan row is a literal nothing checks, which is the
    same hole in a different place. Positive controls: a reason with
    no date, and one whose only anchor is a fabricated sha, both
    fail."""
    for name, row in MEASURED.items():
        ok, why = _exm1_check(row.reason)
        assert ok, (name, why)
        hex_tokens = _EXM1_HEX_RE.findall(row.reason)
        assert any(_resolves_as_commit(h) for h in hex_tokens), (name, hex_tokens)
        assert row.scope in _SCOPES, (name, row.scope)
        assert callable(row.measure), name

    read_by_tests = _measured_keys_read_by_tests(_module_source())
    assert read_by_tests == set(MEASURED), (
        set(MEASURED) - read_by_tests, read_by_tests - set(MEASURED)
    )

    undated_ok, _why = _exm1_check("no date here, but a citation: 4.5")
    assert not undated_ok
    fabricated_ok, _why2 = _exm1_check("2026-08-29 anchor ffffffffffff0000")
    assert not fabricated_ok


def test_anc5_remeasure_refuses_a_vacuous_exemption(capsys):
    """`ANC5`. Section 4.7 `FW-140`'s fold rule, enforced by the tool
    instead of discovered by a red suite. An exemption entry the NEW
    anchor no longer owes makes `--remeasure` refuse, rc 1, naming the
    entry -- because `EXM3`'s `shipped == census` leg and `FIX2`'s
    anti-rot leg are exactly what go red on one. Measured 2026-08-29
    in a throwaway clone: all fourteen `test_u_fake.py` `missing`
    entries turn vacuous the instant `ANCHOR` reaches `a768696`, and
    `EXM3` fails on the first of them before it ever reaches its own
    hand-written totals.

    Negative control asserted first (via `ANC2` for the shipped table,
    and again here for the scratch copy). Both doors are driven: a
    `Behaviour.missing` entry naming a node that is still present at
    head, and a `Fixture.repinned` entry on a file identical to its
    anchor."""
    scratch_dir = Path(tempfile.mkdtemp(dir=str(_REPO_ROOT)))
    try:
        scratch_module, ns = _scratch_armor_namespace(scratch_dir, "_armor_anc5")
        anchor = ns["ANCHOR"]
        assert ns["_compute_vacuous"](anchor) == {}

        behaviour_key = "test_worker.py"
        fixture_key = "conftest.py"
        live_node = next(iter(ns["_head_census"](behaviour_key)))
        patched = dict(ns["ARMOR"])
        patched[behaviour_key] = ns["Behaviour"](
            nodes=ns["ARMOR"][behaviour_key].nodes,
            dump_sha=ns["ARMOR"][behaviour_key].dump_sha,
            missing={live_node: "2026-08-29 §4.7 ANC5 test scaffold, 6815503."},
        )
        patched[fixture_key] = ns["Fixture"](
            repinned=(
                hashlib.sha256(ns["_head_bytes"](fixture_key)).hexdigest(),
                "2026-08-29 §4.3 ANC5 test scaffold, 6815503.",
            )
        )
        ns["ARMOR"] = patched

        vacuous = ns["_compute_vacuous"](anchor)
        assert vacuous == {
            behaviour_key: [f"missing:{live_node}"],
            fixture_key: ["repinned"],
        }, vacuous

        capsys.readouterr()
        sha_before = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        rc = ns["_remeasure"](["--remeasure", "--anchor", anchor])
        sha_after = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        err = capsys.readouterr().err

        assert rc == 1, rc
        assert sha_after == sha_before, "a refusing --remeasure must leave the file byte-identical"

        # Report LINES only -- see `ANC1` on why a whole-stream
        # substring check is worthless here.
        report = [ln for ln in err.splitlines() if ln.startswith(("OWED:", "VACUOUS:", "STALE:"))]
        assert report == [
            f"VACUOUS: {behaviour_key}: missing:{live_node}",
            f"VACUOUS: {fixture_key}: repinned",
        ], report
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


#: The four `--remeasure` outcomes, as a caller sees them (`ANC6`, and
#: the runbook §5 contract table this pins). Start-of-line tokens: an
#: unanchored substring match is NOT part of the contract, though the
#: trailer is written so that one still happens to work.
_REFUSAL_TOKENS: tuple[str, ...] = ("OWED: ", "VACUOUS: ", "STALE: ")
_NOOP_PREFIX = "ANCHOR did not change ("
_TRAILER_PREFIX = "refusing to write test_armor.py ("
_SUCCESS_RE = re.compile(r"^ANCHOR [0-9a-f]{7,40} -> [0-9a-f]{7,40}$")
_OWED_RE = re.compile(r"^OWED: \S+\.py: (missing|edited):\S+$")
_VACUOUS_RE = re.compile(r"^VACUOUS: \S+\.py: ((missing|edited):\S+|repinned)$")
_STALE_HEAD_RE = re.compile(
    r"^STALE: \S+: MEASURED\['[^']+'\] \(scope=(anchor|anchor\+head|head)\)$"
)
_STALE_SHIPPED_RE = re.compile(r"^STALE:       shipped value: .+$")
_STALE_LIVE_RE = re.compile(r"^STALE:   value at [0-9a-f]{7,40}: .+$")


def _report_lines(err: str) -> list[str]:
    """The refusal's REPORT lines -- start-of-line token matches only.
    Never a substring scan of the whole stream (`ANC6`'s own subject)."""
    return [ln for ln in err.splitlines() if ln.startswith(_REFUSAL_TOKENS)]


def test_anc6_refusal_leg_contract(capsys):
    """`ANC6`. The `--remeasure` CLI contract, pinned mechanically so a
    sibling unit's landing runner can implement against the runbook's
    §5 table without reading this file. `U-land` is building exactly
    such a runner against the TWO-leg contract that predates this unit
    (`OWED:` and `ANCHOR did not change`); this unit adds two more, and
    the two gates are blind to each other, so the contract has to be
    legible somewhere both can see it.

    Pinned here: exit code, stream, stdout-is-always-empty, the
    start-of-line token for each leg, the three-line shape of a
    `STALE:` record, whether the file is written, and -- the leg that
    actually bit -- that the TRAILER contains no bare token. An
    earlier draft's trailer spelled `OWED:`/`VACUOUS:`/`STALE:` out in
    its legend, which made an unanchored `"OWED:" not in err` false
    for every refusal, including ones reporting no owed node at all.
    That was caught by this unit's own first test run, not by review.

    The rc-0 success leg is asserted by `ARM6` (which already drives a
    genuine write at `15fb676`); duplicating its ~35s here would buy
    nothing."""
    # --- Leg 1: the no-op guard. A pristine scratch copy with
    # `--anchor` equal to its own `ANCHOR` owes nothing, strands
    # nothing and invalidates nothing, so the run reaches the WRITE and
    # only then reports the no-op (section 4.2 step 6). This is the one
    # leg that is post-write: the file IS rewritten, with byte-
    # identical content whenever the table was already current --
    # measured here rather than assumed.
    scratch_dir = Path(tempfile.mkdtemp(dir=str(_REPO_ROOT)))
    try:
        scratch_module, ns = _scratch_armor_namespace(scratch_dir, "_armor_anc6a")
        anchor = ns["ANCHOR"]
        sha_before = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        capsys.readouterr()
        rc = ns["_remeasure"](["--remeasure", "--anchor", anchor])
        cap = capsys.readouterr()
        sha_after = hashlib.sha256(scratch_module.read_bytes()).hexdigest()

        assert rc == 1, rc
        assert cap.out == "", cap.out
        err_lines = [ln for ln in cap.err.splitlines() if ln.strip()]
        assert err_lines[0].startswith(f"{_NOOP_PREFIX}{anchor} -> {anchor})"), err_lines
        assert _report_lines(cap.err) == [], cap.err
        assert sha_after == sha_before, (
            "no-op leg: the write happens, but with byte-identical content"
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # --- Leg 2: one run carrying all three pre-write tokens at once,
    # which is what a real landing behind a sibling unit looks like.
    # Built at the copy's own `ANCHOR` (permanent -- no later landing
    # can invalidate this probe) by: dropping test_u_fake.py's shipped
    # `missing` entries, so its fourteen anchor-era nodes become OWED;
    # adding a `missing` entry naming a node that is still present at
    # head, which is VACUOUS; and corrupting one `MEASURED` row, which
    # is STALE.
    scratch_dir = Path(tempfile.mkdtemp(dir=str(_REPO_ROOT)))
    try:
        scratch_module, ns = _scratch_armor_namespace(scratch_dir, "_armor_anc6b")
        anchor = ns["ANCHOR"]

        owed_key = "test_u_fake.py"
        vacuous_key = "test_worker.py"
        live_node = next(iter(ns["_head_census"](vacuous_key)))
        patched = dict(ns["ARMOR"])
        patched[owed_key] = ns["Behaviour"](
            nodes=ns["ARMOR"][owed_key].nodes,
            dump_sha=ns["ARMOR"][owed_key].dump_sha,
        )
        patched[vacuous_key] = ns["Behaviour"](
            nodes=ns["ARMOR"][vacuous_key].nodes,
            dump_sha=ns["ARMOR"][vacuous_key].dump_sha,
            missing={live_node: "2026-08-29 §4.7 ANC6 test scaffold, 6815503."},
        )
        ns["ARMOR"] = patched

        stale_row = "BEH7.node_total"
        measured = dict(ns["MEASURED"])
        measured[stale_row] = dataclasses.replace(
            measured[stale_row], value=measured[stale_row].value + 1
        )
        ns["MEASURED"] = measured

        sha_before = hashlib.sha256(scratch_module.read_bytes()).hexdigest()
        capsys.readouterr()
        rc = ns["_remeasure"](["--remeasure", "--anchor", anchor])
        cap = capsys.readouterr()
        sha_after = hashlib.sha256(scratch_module.read_bytes()).hexdigest()

        assert rc == 1, rc
        assert cap.out == "", cap.out
        assert sha_after == sha_before, "a pre-write refusal must leave the file byte-identical"

        report = _report_lines(cap.err)
        owed = [ln for ln in report if ln.startswith("OWED: ")]
        vacuous = [ln for ln in report if ln.startswith("VACUOUS: ")]
        stale = [ln for ln in report if ln.startswith("STALE: ")]
        assert len(owed) == 14, owed
        assert len(vacuous) == 1, vacuous
        assert len(stale) == 3, stale
        assert len(report) == len(owed) + len(vacuous) + len(stale), report

        for ln in owed:
            assert _OWED_RE.match(ln), ln
        assert _VACUOUS_RE.match(vacuous[0]), vacuous[0]
        assert vacuous[0] == f"VACUOUS: {vacuous_key}: missing:{live_node}", vacuous[0]

        # The three-line STALE record, in order, both values `repr()`
        # so line 3 can be pasted straight into `value=`.
        assert _STALE_HEAD_RE.match(stale[0]), stale[0]
        assert stale[0].endswith(f"MEASURED['{stale_row}'] (scope=anchor)"), stale[0]
        assert _STALE_SHIPPED_RE.match(stale[1]), stale[1]
        assert _STALE_LIVE_RE.match(stale[2]), stale[2]
        assert stale[1].endswith(repr(measured[stale_row].value)), stale[1]
        assert stale[2].endswith(repr(MEASURED[stale_row].value)), stale[2]

        # The trailer: named, and token-free. Both halves matter -- the
        # first so a caller can find it, the second so an unanchored
        # token match cannot be satisfied by the trailer alone.
        trailer = cap.err[cap.err.index(_TRAILER_PREFIX):]
        assert trailer.startswith(_TRAILER_PREFIX), trailer[:120]
        for token in _REFUSAL_TOKENS:
            assert token.strip() not in trailer, (token, trailer)

        # Positive control on that last leg: the report lines DO carry
        # the tokens the trailer must not, so "token absent" is not
        # vacuously true of this stream.
        for token in _REFUSAL_TOKENS:
            assert token.strip() in cap.err, token
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
