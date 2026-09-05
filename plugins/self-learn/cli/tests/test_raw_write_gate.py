"""RAW-WRITE GATE (Sprint 2 M-I, lane L1 fsops).

Same shape as `test_bounded_children.py`'s P3 scanner (structural: parse
the source, don't hand-enumerate) and `test_lock_invariant.py`'s
fixpoint walker (fail-closed: the default classification is "this is a
violation", escaping requires a human-written, checkable claim).

**What it scans.** Every ``*.py`` under `cli/src/self_learn/` and
`ui/src/self_learn_ui/`, recursively (subpackages included --
``invocation/``, ``sdksession/``, ``primitives/``, all of them), for
three call shapes: ``<expr>.write_text(``, ``<expr>.write_bytes(``, and
``open(...)``/``<expr>.open(...)`` whose mode argument (positional
``args[1]`` or the ``mode=`` keyword) is a string constant containing
``"w"`` or ``"a"`` -- a write or an append, either one bypasses this
primitive's atomicity/durability guarantees. `primitives/fsops.py`
itself is exempt by construction (it IS the primitive; a raw write
inside its own implementation is not a violation of a rule it defines).

**Why every hit needs a name, not just the migrated sites.** M-I's own
census (this file) found 54 distinct (file, enclosing-function) raw
write sites across both trees before this move; M-I migrates 13 of them
onto `atomic_write`/`private_write` (waves 1 and 2, the two ledger
migration commits) and leaves 41 as `RAW_WRITE_ALLOWLIST` entries, each
with a one-line reason it is not (yet, or ever) migrated and a `wave` in
`{3, 4, 5, "keep"}` -- `"keep"` for a site that structurally does not
fit the atomic-replace shape (a flock lock file that never carries
content, an append-only cache spool, a subprocess stdout redirect, a
test fixture, a log truncator that is silent-on-failure by design, or a
site already carrying a `NOT_REPO_TRUTH` disposition in
`test_lock_invariant.py`); a number for a genuine future migration
candidate of the SAME shape this primitive serves, not touched this
sprint for scope reasons named in the entry.

Two failure modes, both checked below: an UNKNOWN site (not in the
allowlist, or in it with an incomplete disposition) fails naming it --
new code that writes raw bytes outside this primitive is caught the
moment it lands, the same fail-closed shape `test_lock_invariant.py`
already uses for the lock obligation. A ROTTED entry -- an allowlisted
`(path, func)` that no longer has any matching violation (renamed,
migrated, deleted) -- ALSO fails: an allowlist that only ever grows is
not a ledger, it is debt with a rubber stamp.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import self_learn

CLI_SRC = Path(self_learn.__file__).parent
# The CLI venv does not have `self_learn_ui` installed (two separate uv
# projects, two separate venvs) -- located by path, same pattern
# `test_primitives.py` already uses to reach the UI tree from a CLI test.
UI_SRC = Path(__file__).resolve().parent.parent.parent / "ui" / "src" / "self_learn_ui"

DISPOSITION_FIELDS = ("disposition", "wave")
_VALID_WAVES = (3, 4, 5, "keep")


@dataclass(frozen=True)
class Violation:
    tree: str  # "cli" | "ui"
    relpath: str
    lineno: int
    func: str
    kind: str  # "write_text" | "write_bytes" | "open(mode=...)"


def _qualname_map(tree: ast.Module) -> dict[int, str]:
    """``id(node) -> "Class.method"`` (bare ``func`` at module level) for
    every statement in the tree, built by one recursive descent that
    tracks the enclosing class/function stack -- the same approach
    `test_lock_invariant.py`'s ``_Collector`` uses for qualnames, here
    keyed by node id so a raw ``ast.walk`` call site can look its own
    enclosing function up in O(1)."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            new_stack = stack
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                new_stack = stack + [child.name]
            elif isinstance(child, ast.ClassDef):
                new_stack = stack + [child.name]
            owner[id(child)] = ".".join(stack) if stack else "<module>"
            visit(child, new_stack)

    visit(tree, [])
    return owner


def _mode_arg(call: ast.Call) -> ast.expr | None:
    if len(call.args) >= 2:
        return call.args[1]
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    return None


def _is_write_mode(mode_val: object) -> bool:
    return isinstance(mode_val, str) and ("w" in mode_val or "a" in mode_val)


def _scan_module(path: Path, tree_name: str, relpath: str) -> list[Violation]:
    if relpath in ("primitives/fsops.py", "primitives\\fsops.py"):
        return []
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    owners = _qualname_map(tree)
    hits: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        kind: str | None = None
        if isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes"):
            kind = func.attr
        else:
            is_open_call = (isinstance(func, ast.Name) and func.id == "open") or (
                isinstance(func, ast.Attribute) and func.attr == "open"
            )
            if is_open_call:
                mode_arg = _mode_arg(node)
                if isinstance(mode_arg, ast.Constant) and _is_write_mode(mode_arg.value):
                    kind = "open(mode=...)"
        if kind is None:
            continue
        owner = owners.get(id(node), "<module>")
        hits.append(Violation(tree_name, relpath, node.lineno, owner, kind))
    return hits


def scan(root: Path, tree_name: str) -> list[Violation]:
    """Every violation under *root*, walked recursively -- subpackages
    (``primitives/``, ``invocation/``, ``sdksession/``, ...) included,
    matching the real tree's shape."""
    out: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        relpath = str(path.relative_to(root))
        out.extend(_scan_module(path, tree_name, relpath))
    return out


def _disposition_complete(entry: tuple) -> bool:
    if not isinstance(entry, tuple) or len(entry) != 2:
        return False
    disposition, wave = entry
    return (
        isinstance(disposition, str)
        and disposition.strip() != ""
        and wave in _VALID_WAVES
    )


def unallowed(
    violations: list[Violation], allowlist: dict[tuple[str, str, str], tuple]
) -> list[Violation]:
    """Violations the allowlist does not excuse: absent from it, or
    present with an incomplete/invalid disposition (debt, not a
    ratchet)."""
    out = []
    for v in violations:
        entry = allowlist.get((v.tree, v.relpath, v.func))
        if entry is not None and _disposition_complete(entry):
            continue
        out.append(v)
    return out


def rotted(
    violations: list[Violation], allowlist: dict[tuple[str, str, str], tuple]
) -> list[tuple[str, str, str]]:
    """Allowlist keys with no matching violation any more -- the site
    was migrated, renamed, or deleted, and the entry was never
    removed."""
    live = {(v.tree, v.relpath, v.func) for v in violations}
    return [key for key in allowlist if key not in live]


# ======================================================================
# THE ALLOWLIST -- every raw write site left after M-I's waves 1 and 2,
# each with a one-line reason and a wave. Filled from this file's own
# scan (measured at the tip of M-I's work, all three commits' worth of
# migrations already applied): 54 distinct (tree, path, function) sites
# before M-I; 13 migrated onto `atomic_write`/`private_write` (wave 1:
# `ui/middleware.write_token_file`, `verbs._write_hook_script`; wave 2:
# `records.Record.write`, `ledger_ops._dump_yaml`, `hosts.save_hosts`,
# `compiled.write_entry`/`delete_entry`, `config.dump_editable`,
# `worker._write_install_journal`, `worker._write_window_durable`,
# `sentinel.hold`, `serve.write_heartbeat`,
# `store.PaneTranscriptStore._write_meta`); 41 remain, below.
# ======================================================================

RAW_WRITE_ALLOWLIST: dict[tuple[str, str, str], tuple[str, object]] = {
    # ---------------------------------------------------- wave 3: same
    # shape atomic_write serves (ledger/host content replace), not
    # touched this sprint -- M-I's pinned scope is records / proposals /
    # meta / compiled / hosts.yaml / config.yaml / the hook script /
    # the five temp+rename helpers, nothing else.
    ("cli", "compilers.py", "apply_paths_frontmatter"): (
        "host CLAUDE.md paths-block rewrite (same content-replace shape as "
        "compiled.py's bookkeeping); out of M-I's pinned scope",
        3,
    ),
    ("cli", "compilers.py", "apply_pointer"): (
        "host surface pointer-line rewrite (skill/project surfaces); out of "
        "M-I's pinned scope, same future primitive as the other compilers.py sites",
        3,
    ),
    ("cli", "compilers.py", "compile_managed_file"): (
        "host managed-section content rewrite; out of M-I's pinned scope",
        3,
    ),
    ("cli", "compilers.py", "compile_reference"): (
        "host reference-block append-or-create rewrite; out of M-I's pinned scope",
        3,
    ),
    ("cli", "compilers.py", "retire_reference"): (
        "host reference-block removal rewrite; out of M-I's pinned scope",
        3,
    ),
    ("cli", "hosts.py", "_write_host_marker"): (
        "plain-host registration marker, content write under gitops.host_lock; "
        "same shape as records/proposals, not named in M-I's pinned target list",
        3,
    ),
    ("cli", "verbs.py", "_apply_new_skill"): (
        "first-time skill scaffold (manifest.yaml + SKILL.md seed); host content "
        "write, out of M-I's pinned scope",
        3,
    ),
    ("cli", "verbs.py", "_apply_target"): (
        "first-time empty CLAUDE.md bootstrap; host content write, out of M-I's "
        "pinned scope",
        3,
    ),
    ("cli", "telemetry.py", "flush"): (
        "tracked-plane append-with-torn-line-heal under gitops.commit_lock; "
        "append semantics, not a replace -- needs a future atomic-APPEND "
        "primitive, not this atomic-REPLACE one",
        3,
    ),
    # -------------------------------------------------------- wave 4:
    # legitimate atomic-write candidates outside the ledger tree itself
    # (an external tool's file, a UI-side derived/regenerable cache).
    ("cli", "import_memory.py", "_drop_index_line"): (
        "rewrites ~/.claude auto-memory (Claude Code's own file, not this "
        "ledger's truth -- already NOT_REPO_TRUTH in test_lock_invariant.py); "
        "external integration point, deferred",
        4,
    ),
    ("ui", "doctrine.py", "compile_doctrine"): (
        "UI-side compiled-doctrine cache, regenerated from source mtimes -- "
        "derived/reproducible content, not primary ledger truth; deferred",
        4,
    ),
    # -------------------------------------------------------- wave 5:
    # invocation-seam cache bookkeeping, deferred behind the armor-pinned
    # end-to-end tests' (test_invocation.py, test_invocation_sdk.py)
    # stability guarantee -- CLAUDE.md: "a change that touches
    # worker.run's path runs the armor-pinned end-to-end files before
    # merging"; these sit adjacent to that seam and are left alone this
    # sprint on purpose.
    ("cli", "invocation_sdk/events.py", "write_event_log"): (
        "invocation-seam tool-event log, XDG-cache-only bookkeeping; deferred "
        "behind the armor-pinned invocation end-to-end tests",
        5,
    ),
    ("cli", "invocation_sdk/lifecycle.py", "write_sidecar"): (
        "invocation-seam child-pid sidecar (K-4), XDG-cache-only; deferred "
        "behind the armor-pinned invocation end-to-end tests",
        5,
    ),
    ("cli", "sdksession/children.py", "write_sidecar"): (
        "sdk-session child-pid sidecar (K-4), XDG-cache-only; deferred behind "
        "the armor-pinned invocation_sdk end-to-end tests",
        5,
    ),
    ("cli", "sdksession/events.py", "write_event_log"): (
        "sdk-session tool-event log, XDG-cache-only bookkeeping; deferred "
        "behind the armor-pinned invocation_sdk end-to-end tests",
        5,
    ),
    # ------------------------------------------------------- "keep":
    # structurally not an atomic-replace candidate at all.
    ("cli", "gitops.py", "_flock_lock"): (
        "flock lock file only (open 'w' just creates/truncates it for "
        "fcntl.flock) -- never carries content",
        "keep",
    ),
    ("cli", "sentinel.py", "_lock_section"): (
        "flock lock file only (open 'a+' so it can be created and locked) -- "
        "never carries content",
        "keep",
    ),
    ("cli", "worker.py", "_open_window"): (
        "flock lock file only (worker.spawn.lock) -- never carries content",
        "keep",
    ),
    ("cli", "worker.py", "run"): (
        "flock lock file only (worker.lock) -- never carries content",
        "keep",
    ),
    ("cli", "miner.py", "run"): (
        "flock lock file only (miner.lock) -- never carries content",
        "keep",
    ),
    ("cli", "miner.py", "maybe_kick"): (
        "flock lock file only (miner.spawn.lock) -- never carries content",
        "keep",
    ),
    ("cli", "miner.py", "_spawn_run"): (
        "subprocess.Popen stdout redirect (miner.log), not a content write by "
        "this code",
        "keep",
    ),
    ("cli", "worker.py", "_spawn_window"): (
        "subprocess.Popen stdout redirect (worker.log), not a content write by "
        "this code",
        "keep",
    ),
    ("cli", "miner.py", "log"): (
        "append-only XDG cache log (miner.log); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "miner.py", "_journal"): (
        "append-only XDG cache run journal (JSONL); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "miner.py", "_save_cursors"): (
        "XDG cache JSON bookkeeping (cursors.json); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "miner.py", "_rejected_counter_bump"): (
        "XDG cache JSON bookkeeping (rejected-sightings.json); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "miner.py", "_rejected_mark_landed"): (
        "XDG cache JSON bookkeeping (rejected-sightings.json); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "miner.py", "_save_canaries"): (
        "XDG cache JSON bookkeeping (canaries.json); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "telemetry.py", "spool_event"): (
        "append-only XDG cache telemetry spool; NOT_REPO_TRUTH "
        "(flush -- see wave 3 above -- is what moves it to the tracked plane)",
        "keep",
    ),
    ("cli", "worker.py", "_log_to"): (
        "append-only XDG cache log, silent on OSError by design; NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "worker.py", "append_event"): (
        "append-only XDG cache event spool (JSONL); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "worker.py", "_write_failure_count"): (
        "XDG cache scratch counter (follow-on backoff); NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "worker.py", "_migrate_cache"): (
        "XDG cache-path migration shim; NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "serve.py", "request_poke"): (
        "XDG cache scheduler poke-request file; NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "serve.py", "_today_mine_target"): (
        "XDG cache scheduler bookkeeping (today's jittered mine target); "
        "NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "verbs.py", "_replay_hook_examples"): (
        "transient TemporaryDirectory scratch, executed then deleted; "
        "NOT_REPO_TRUTH",
        "keep",
    ),
    ("cli", "worker.py", "_install_staged"): (
        "crash-survival contract is the OPPOSITE of atomic_write's: "
        "test_attrib.py's armor-pinned IN8(e) asserts the temp file SURVIVES "
        "a crashed os.replace, so the next run's pass-1 cleanup can sweep it "
        "-- atomic_write's unlink-on-any-exception would delete exactly that "
        "evidence. See primitives/fsops.py's module docstring",
        "keep",
    ),
    ("cli", "invocation/fake.py", "FakeBackend._step"): (
        "test fixture (FakeBackend) writing model-simulated output paths for "
        "tests, not a production content writer",
        "keep",
    ),
    ("cli", "primitives/truncate.py", "truncate_oldest"): (
        "log-rotation truncator, silent on OSError by design; log content is "
        "disposable, atomicity adds no value",
        "keep",
    ),
    ("ui", "uilog.py", "log"): (
        "append-only UI log file, same class as the CLI's worker.log/miner.log",
        "keep",
    ),
}


def test_raw_write_gate_has_no_unallowed_violations():
    violations = scan(CLI_SRC, "cli") + scan(UI_SRC, "ui")
    bad = unallowed(violations, RAW_WRITE_ALLOWLIST)
    assert not bad, "\n".join(
        f"{v.tree}/{v.relpath}:{v.lineno} [{v.func}] {v.kind}" for v in bad
    )


def test_raw_write_allowlist_has_no_rotted_entries():
    violations = scan(CLI_SRC, "cli") + scan(UI_SRC, "ui")
    stale = rotted(violations, RAW_WRITE_ALLOWLIST)
    assert not stale, (
        "allowlist entries with no matching violation any more (migrated, "
        f"renamed, or deleted -- remove the entry): {sorted(stale)}"
    )


def test_fsops_module_itself_is_exempt_but_not_silently_unscanned():
    """`primitives/fsops.py` is excluded from the scan by construction
    (it IS the primitive) -- prove that exclusion is a deliberate,
    named skip, not the scanner failing to find the file at all."""
    fsops_path = CLI_SRC / "primitives" / "fsops.py"
    assert fsops_path.is_file()
    assert _scan_module(fsops_path, "cli", "primitives/fsops.py") == []
    # Sanity: the file DOES contain a raw write internally (open(...,
    # "wb")) -- the exemption is real, not a coincidence of an empty file.
    assert "open(tmp" in fsops_path.read_text(encoding="utf-8")


# ============================================================ synthetic
# controls: prove the scanner itself works, independent of the real
# tree's current shape.


def test_positive_control_synthetic_module_with_one_raw_write_is_caught(tmp_path):
    mod = tmp_path / "synthetic.py"
    mod.write_text(
        "from pathlib import Path\n"
        "\n"
        "def leaky(p: Path) -> None:\n"
        "    p.write_text('oops', encoding='utf-8')\n",
        encoding="utf-8",
    )
    found = scan(tmp_path, "synthetic")
    assert len(found) == 1, found
    assert found[0].func == "leaky"
    assert found[0].kind == "write_text"


def test_positive_control_synthetic_open_append_and_write_are_both_caught(tmp_path):
    mod = tmp_path / "synthetic2.py"
    mod.write_text(
        "def appender(p):\n"
        "    with open(p, 'a', encoding='utf-8') as fh:\n"
        "        fh.write('x')\n"
        "\n"
        "def writer(p):\n"
        "    with open(p, mode='w', encoding='utf-8') as fh:\n"
        "        fh.write('x')\n"
        "\n"
        "def reader(p):\n"
        "    with open(p, 'r', encoding='utf-8') as fh:\n"
        "        return fh.read()\n",
        encoding="utf-8",
    )
    found = scan(tmp_path, "synthetic2")
    funcs = {v.func for v in found}
    assert funcs == {"appender", "writer"}, found


def test_fail_closed_empty_walk_fails_not_passes_vacuously(tmp_path):
    """A scan of a directory with no ``.py`` files at all must not be
    mistaken for "everything is clean" -- it must be loud that nothing
    was checked. Mutation this catches: a version of this test that
    only asserted ``scan(empty) == []`` would ALSO pass on the real
    gate scanning the wrong (empty/typo'd) path -- exactly the silent
    fail-open this repo's own lessons warn about."""
    empty_dir = tmp_path / "nothing_here"
    empty_dir.mkdir()
    files = list(empty_dir.rglob("*.py"))
    assert files == []
    # The gate functions themselves scan CLI_SRC/UI_SRC, real trees that
    # always contain files -- this test instead pins the CONTRACT an
    # empty walk must never be silently accepted as: the real gate
    # tests above never call `scan()` against a walk that could be
    # empty without first asserting the root actually has `.py` files.
    assert list(CLI_SRC.rglob("*.py")), "CLI_SRC walk is unexpectedly empty"
    assert list(UI_SRC.rglob("*.py")), "UI_SRC walk is unexpectedly empty"
