"""THE INVARIANT, enforced mechanically (audit 2026-07-16 round 7).

    **No ledger/host mutation may precede its ``commit_lock``.** The lock
    must open BEFORE the first filesystem/git mutation of a repo and stay
    held through that repo's commit.

Round 3 established this correctly for ``verbs.py`` — ``resolve_record``
mutates before ``stage``, so a stage+commit-scoped lock misses the window
— and proved the damage by probe: a racing ``pull --rebase --autostash``
in that window stashes the staged rename, the restore conflicts, and the
victim's pathspec commit lands conflict markers (or half a rename) with
``git status`` clean and **exit 0**.

Round 7 found the same round applying its own correct insight to 2 of the
4 files that needed it — ``hosts.py`` (three verbs, one of them ``git
mv``-ing an entire project bucket before locking), ``verbs.recompile``'s
reference path, and the miner's fold. The lesson is not "patch two more
files". It is that a rule enforced by human diligence is enforced until
the next person is in a hurry.

**Why this test is STRUCTURAL, and what that means concretely.** A test
that hardcodes a list of surfaces cannot fail for the code it does not
know about — it is a memo, and the failure being fixed *is* an incomplete
memo. So nothing here is enumerated by hand:

- the functions are enumerated by parsing ``src/self_learn/`` (every
  ``def``, every module, no list);
- the mutating primitives are the leaves (``Path.write_text`` / ``.rename``
  / ``.unlink`` / ``shutil.move`` / ``os.replace`` / ``Record.write`` /
  ``git mv|rm|add|commit`` / ``gitops.stage`` / ``gitops.commit``), and
  every function that reaches one is derived by fixpoint over the call
  graph;
- the ENTRYPOINTS are derived too: a "root" is any function with no
  in-package caller. Nobody declares them.

The obligation propagates: a function with an unguarded mutation REQUIRES
a lock from its callers; a caller that does not take one inherits the
obligation. A violation is an obligation that reaches a ROOT — a chain
from an entrypoint to a mutation with no lock anywhere on it. That is
exactly the bug, stated as a graph property.

**The one declared list, and why it is safe.** :data:`NOT_REPO_TRUTH`
names functions whose writes are never a repo's truth — they land outside
every git repo (the XDG cache, the sentinel, the model spool, ``~/.claude``
memory files), or they are transient scratch created and deleted without
ever being committed. It is FAIL-CLOSED, and that is the whole difference
from the list this round is fixing: the default classification is "this
mutates a repo", so new code that writes the ledger and forgets the lock
FAILS this test. Escaping requires a human to add an explicit entry saying
where it writes instead — a claim a reviewer can check against the
function. A missing entry costs a false alarm; a missing surface in a
hand-written surface list costs a silent data-loss bug. Only one of those
two failure modes is acceptable, and this is the one.

(The list earns its keep immediately: written fail-closed, it made the
analysis flag ``selfcheck._check_capture`` — a site no review round had
named — and forced the judgement to be recorded rather than assumed.)

Companion runtime test at the bottom: every ``_cmd_*`` in ``cli.py``, by
introspection, driven against a REAL held lock.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from self_learn import cli, gitops
from support import commit_all, git, init_repo, make_env

SRC = Path(gitops.__file__).parent
MODULES = {p.stem for p in SRC.glob("*.py")}
CLI_SRC = str(Path(__file__).resolve().parents[1] / "src")


# ------------------------------------------------------------ the primitives

#: pathlib/shutil/os leaves that put bytes on disk or move them.
_FS_PRIMITIVES = ("write_text", "rename", "unlink")

#: git subcommands that mutate the worktree or the INDEX — the two things
#: a racing ``pull --rebase --autostash`` rewrites. (``pull`` is here for
#: completeness; ``push`` is deliberately absent — it touches neither, and
#: locking it was the round-3 mistake.)
_GIT_MUTATING = ("mv", "rm", "add", "commit", "apply", "checkout", "reset", "pull")

#: Names that open the critical section.
_LOCKS = ("commit_lock", "_ledger_write")

#: Receivers whose ``.write()`` is a byte stream, not ``Record.write``.
_STREAMS = ("buf", "fh", "f", "sys", "stderr", "stdout", "out", "handle", "proc")

#: Functions whose filesystem writes are never a repo's truth, each with
#: WHY. FAIL-CLOSED (see the module docstring): the default is "this
#: mutates a repo", so an entry here is a CLAIM, checkable against the
#: function, that it cannot corrupt a ledger or a host.
#: Every entry must still exist (see
#: :func:`test_the_exemption_list_cannot_rot`), so a rename or a deletion
#: cannot leave a stale exemption quietly widening the hole.
NOT_REPO_TRUTH = {
    # $XDG_CACHE_HOME/self-learn/autosync-pause — global, cross-repo pause
    # contract (doc 13 §4.4). Never in a repo.
    "sentinel.hold": "XDG cache: the autosync-pause sentinel",
    "sentinel.heartbeat": "XDG cache: the autosync-pause sentinel",
    "sentinel.release": "XDG cache: the autosync-pause sentinel",
    "sentinel.SentinelHold.release": "XDG cache: the autosync-pause sentinel",
    # $XDG_CACHE_HOME/self-learn/home-<sha>/… — the per-home worker cache
    # (doc 13 §6, H-4): windows, logs, settings, the run's own bookkeeping.
    "worker.cache_dir": "XDG cache: the per-home cache namespace itself",
    "worker._migrate_cache": "XDG cache: the H-4 cache-path migration shim",
    "worker._open_window": "XDG cache: worker.window",
    "worker._truncate_oldest": "XDG cache: worker.log rotation",
    "worker._log_to": "XDG cache: worker.log",
    "worker.log": "XDG cache: worker.log",
    "worker.write_settings_file": "XDG cache: the worker's Claude settings",
    "worker.append_event": "XDG cache: the worker's event spool",
    "worker._cache_clear": "XDG cache: the worker's flag files",
    # …/miner/ — cursors, journal, the model's spool. The reader is pointed
    # at the spool precisely so the model cannot touch the repo (M-5).
    "miner.miner_dir": "XDG cache: the miner cache dir itself",
    "miner.spool_dir": "XDG cache: the model's spool",
    "miner.log": "XDG cache: miner.log",
    "miner._journal": "XDG cache: the run journal (JSONL)",
    "miner._save_cursors": "XDG cache: cursors.json",
    "miner._advance_cursors": "XDG cache: cursors.json",
    "miner.initialize_cursors": "XDG cache: cursors.json",
    "miner.write_reader_settings": "XDG cache: the reader's Claude settings",
    "miner._invoke_reader": "XDG cache: the model's spool + its transcript",
    "miner._rejected_counter_bump": "XDG cache: the rejected-resurface counter",
    "miner._rejected_mark_landed": "XDG cache: the rejected-resurface counter",
    # FW-34 §3: canaries.json — cache-local like cursors.json/journal.jsonl;
    # `canary plant` never touches the ledger (t-h: no transcript, no repo).
    "miner._save_canaries": "XDG cache: canaries.json",
    "miner.plant_canary": "XDG cache: canaries.json",
    "cli._cmd_canary": "XDG cache: canaries.json (see miner.plant_canary)",
    "telemetry.spool_quiet": "XDG cache: the telemetry spool (flush commits it)",
    # `sentinel hold|release` is the CLI face of the same cache file.
    "cli._cmd_sentinel": "XDG cache: the autosync-pause sentinel",
    # ~/.claude/projects/<slug>/memory/* — Claude Code's auto-memory. Not
    # a repo, and not ours: `import --memory` READS it and prune-memory
    # rewrites it in place, by explicit user command (08 §3).
    "import_memory._drop_index_line": "~/.claude auto-memory (not a repo)",
    "import_memory.prune_memory": "~/.claude auto-memory (not a repo)",
    # The chezmoi user-scope flow writes the chezmoi SOURCE dir and lets
    # chezmoi's own repo commit it (doc 13 §4.3) — a repo we do not own
    # and never commit, so our lock would mean nothing there.
    "chezmoi._run": "the chezmoi source dir — chezmoi commits its own repo",
    "chezmoi.compile_user_scope": "the chezmoi source dir (see chezmoi._run)",
    "chezmoi.preflight_user_scope": "the chezmoi source dir (see chezmoi._run)",
    # INSIDE the ledger home, and still not its truth: --selftest's
    # round-trip probe writes a scratch record into a TemporaryDirectory
    # under the home and deletes it in the same breath. It is never staged,
    # never committed, and untracked files are the half an autostash leaves
    # alone — there is nothing here for a lock to protect. (Surfaced by
    # THIS check, 2026-07-16: no review round had named it. Judged, not
    # assumed — which is what a fail-closed list is for.)
    "selfcheck._check_capture": "transient scratch under the home, never committed",
    # T17 (M3): the guard-replay probe writes the proposal's script bytes
    # into a TemporaryDirectory, executes the analyst's examples against
    # it, and the directory is deleted on exit. Nothing under any repo;
    # the REAL script write (the host phase / recompile) goes through
    # _write_hook_script under the host's commit_lock and is checked by
    # the main analysis like every other host mutation.
    "verbs._replay_hook_examples": "transient scratch: replay copy in a TemporaryDirectory, executed then deleted",
}


# ---------------------------------------------------------------- the parser


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


class _Collector(ast.NodeVisitor):
    """Every ``def`` in one module, qualified ``module.Class.func``."""

    def __init__(self, module: str) -> None:
        self.module, self._stack, self.funcs = module, [], {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def _fn(self, node) -> None:
        self.funcs[".".join([self.module, *self._stack, node.name])] = node
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_FunctionDef = _fn
    visit_AsyncFunctionDef = _fn


def _primitive(call: ast.Call) -> str | None:
    """The mutating primitive this call IS, or None."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in _FS_PRIMITIVES:
        return f"Path.{func.attr}"
    if func.attr == "move" and _dotted(func) == "shutil.move":
        return "shutil.move"
    if func.attr == "replace" and isinstance(func.value, ast.Name):
        if func.value.id == "os":
            return "os.replace"
        return None
    return None


def _record_write(func: ast.Attribute) -> bool:
    """``x.write(...)`` where x is not an obvious byte stream."""
    recv = func.value
    name = recv.id if isinstance(recv, ast.Name) else getattr(recv, "attr", None)
    return name not in _STREAMS


def _git_primitive(call: ast.Call) -> str | None:
    """``_git(repo, "<mutating subcmd>", …)`` — either module's ``_git``."""
    func = call.func
    name = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id if isinstance(func, ast.Name) else None
    )
    if name not in ("_git", "_git_ok"):
        return None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        if call.args[1].value in _GIT_MUTATING:
            return f"git {call.args[1].value}"
    return None


def _is_lock(expr: ast.expr) -> bool:
    """Does this expression subtree open the critical section? (Walks the
    whole subtree so ``lock = commit_lock(r) if r else nullcontext()`` —
    ``verbs._host_phase``'s real shape — counts.)"""
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None
            )
            if name in _LOCKS:
                return True
    return False


class _Analysis:
    """The whole package, parsed once. ``root`` is the source dir — a
    parameter, not a constant, so the planted-violation test can point it
    at a deliberately-broken COPY of the tree."""

    def __init__(self, root: Path | None = None) -> None:
        root = SRC if root is None else root
        self.funcs: dict[str, ast.AST] = {}
        self.aliases: dict[str, dict[str, str]] = {}
        self.imported: dict[str, dict[str, str]] = {}
        for path in sorted(root.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            collector = _Collector(path.stem)
            collector.visit(tree)
            self.funcs.update(collector.funcs)
            # `from . import gitops` → module alias; `from .compilers
            # import compile_reference` → a bare NAME that must still
            # resolve to compilers.compile_reference (teach and verbs call
            # create_record / compile_reference exactly that way, and the
            # planted-violation test proves the analysis would be blind
            # without this).
            alias: dict[str, str] = {}
            imported: dict[str, str] = {}
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or (node.level or 0) < 1:
                    continue
                for name in node.names:
                    if node.module is None and name.name in MODULES:
                        alias[name.asname or name.name] = name.name
                    elif node.module in MODULES:
                        imported[name.asname or name.name] = (
                            f"{node.module}.{name.name}"
                        )
            self.aliases[path.stem] = alias
            self.imported[path.stem] = imported
        self._guarded = {q: self._guarded_lines(n) for q, n in self.funcs.items()}

    # -- guarding

    @staticmethod
    def _guarded_lines(node) -> set[int]:
        """Line numbers lexically inside a lock-opening ``with`` block.

        A ``with`` whose context manager is a NAME gets resolved through
        the assignments in the same function, so the nullcontext-or-lock
        shape is not a blind spot."""
        lock_names = {
            target.id
            for stmt in ast.walk(node)
            if isinstance(stmt, ast.Assign) and _is_lock(stmt.value)
            for target in stmt.targets
            if isinstance(target, ast.Name)
        }
        guarded: set[int] = set()
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.With):
                continue
            opens = any(
                _is_lock(item.context_expr)
                or (
                    isinstance(item.context_expr, ast.Name)
                    and item.context_expr.id in lock_names
                )
                for item in stmt.items
            )
            if not opens:
                continue
            for body_stmt in stmt.body:
                for inner in ast.walk(body_stmt):
                    if hasattr(inner, "lineno"):
                        guarded.add(inner.lineno)
        return guarded

    def _module(self, qual: str) -> str:
        return qual.split(".")[0]

    def _resolve(self, call: ast.Call, qual: str) -> list[str]:
        """The package function(s) a call may reach — resolved precisely
        (same-module ``Name``, or ``<imported module>.<func>``). Method
        calls on arbitrary receivers resolve to nothing: guessing there
        turns ``buf.write`` into ``Record.write`` and the whole analysis
        into noise."""
        module = self._module(qual)
        func = call.func
        if isinstance(func, ast.Name):
            for target in (
                f"{module}.{func.id}",  # same module
                self.imported[module].get(func.id),  # from .x import f
            ):
                if target and target in self.funcs:
                    return [target]
            return []
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                alias = self.aliases[module].get(func.value.id)
                if alias:
                    target = f"{alias}.{func.attr}"
                    return [target] if target in self.funcs else []
            if func.attr == "write" and _record_write(func):
                # `record.write(path)` — the ONE method call resolved on a
                # bare receiver, because Record.write IS a ledger mutation
                # and every resolution verb reaches the ledger through it.
                # Resolving it as a call EDGE (rather than treating it as an
                # opaque primitive) is what gives records.Record.write real
                # callers — otherwise it reads as an entrypoint that mutates
                # with no lock, i.e. a false alarm on the most-called
                # mutator in the package.
                return ["records.Record.write"]
        return []

    def mutations(self, qual: str, requires: set[str]) -> list[tuple[int, str]]:
        """Every repo-mutating call site in *qual*: (lineno, what)."""
        node = self.funcs[qual]
        if qual in NOT_REPO_TRUTH:
            return []
        found: list[tuple[int, str]] = []
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
            what = _primitive(call) or _git_primitive(call)
            if what is None:
                targets = [
                    t
                    for t in self._resolve(call, qual)
                    if t in requires and t != qual
                ]
                if not targets:
                    continue
                what = targets[0]
            found.append((call.lineno, what))
        return found

    def unguarded(self, qual: str, requires: set[str]) -> list[tuple[int, str]]:
        guarded = self._guarded[qual]
        return [m for m in self.mutations(qual, requires) if m[0] not in guarded]

    def requires_lock(self) -> dict[str, tuple[int, str]]:
        """Fixpoint: functions carrying an UNDISCHARGED lock obligation,
        mapped to the first unguarded mutation that creates it."""
        requires: dict[str, tuple[int, str]] = {}
        changed = True
        while changed:
            changed = False
            for qual in self.funcs:
                hits = self.unguarded(qual, set(requires))
                if hits and qual not in requires:
                    requires[qual] = sorted(hits)[0]
                    changed = True
        return requires

    def callers(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {q: set() for q in self.funcs}
        for qual, node in self.funcs.items():
            for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
                for target in self._resolve(call, qual):
                    if target != qual:
                        out[target].add(qual)
        return out


@pytest.fixture(scope="module")
def analysis() -> _Analysis:
    return _Analysis()


# ================================================================ the check


class TestNoMutationPrecedesItsLock:
    def test_no_entrypoint_reaches_a_mutation_without_a_lock(self, analysis):
        """THE test. A "root" is a function no other package function
        calls — an entrypoint, derived, not declared. If a root carries an
        undischarged lock obligation, there is a path from a program
        entrypoint to a repo mutation with no ``commit_lock`` anywhere on
        it. That is the bug, and it is the same bug in ``hosts.host_add``,
        in ``verbs.recompile``'s reference path and in the miner's fold —
        which is the point of asserting the graph property instead of the
        three sites."""
        requires = analysis.requires_lock()
        callers = analysis.callers()
        roots = [q for q in analysis.funcs if not callers[q]]
        violations = []
        for root in sorted(roots):
            if root not in requires:
                continue
            chain, cursor = [], root
            # walk down to the primitive so the failure names the whole path
            for _ in range(20):
                line, what = requires[cursor]
                chain.append(f"{cursor} @L{line} → {what}")
                if what not in requires:
                    break
                cursor = what
            violations.append("\n    ".join(chain))
        assert not violations, (
            "THE INVARIANT IS BROKEN — a mutation is reachable from an "
            "entrypoint with no commit_lock on the path.\n\n"
            "The lock must open BEFORE the first filesystem/git mutation of "
            "a repo and stay held through that repo's commit: a racing "
            "`pull --rebase --autostash` in that window stashes the staged "
            "work, the restore conflicts, and the pathspec commit lands the "
            "wreckage with `git status` clean and exit 0.\n\n"
            "Each chain below runs entrypoint → … → primitive:\n\n  "
            + "\n\n  ".join(violations)
            + "\n\nIf the function writes OUTSIDE every git repo (the XDG "
            "cache, the sentinel, ~/.claude), say so in NOT_REPO_TRUTH "
            "with the root it writes under."
        )

    def test_the_analysis_actually_sees_the_code(self, analysis):
        """A structural check that silently parses nothing passes forever.
        Pin the shape it depends on: the modules are found, the known
        primitives are found, and the known locks are found."""
        assert len(analysis.funcs) > 200, len(analysis.funcs)
        assert {"verbs.route", "hosts.host_rebind", "miner._run_locked"} <= set(
            analysis.funcs
        )
        requires = analysis.requires_lock()
        # the leaves REALLY are classified as needing a lock — if these
        # ever come out clean, the primitive detector has gone blind and
        # every assertion above it is vacuous
        for leaf in ("records.Record.write", "hosts.save_hosts", "gitops.stage"):
            assert leaf in requires, f"{leaf} is not seen as a repo mutation"
        # and the guard detector really sees a lock
        assert "verbs.route" not in requires, (
            "verbs.route reads as unguarded — the lock detector is broken, "
            "which would make the main test vacuous"
        )

    def test_the_exemption_list_cannot_rot(self, analysis):
        """Every NOT_REPO_TRUTH entry must still name a real function.
        A stale entry (renamed/deleted function) is a hole that widens in
        silence — the exemption stops matching what it exempted, but keeps
        looking like a considered decision."""
        stale = sorted(set(NOT_REPO_TRUTH) - set(analysis.funcs))
        assert not stale, (
            f"NOT_REPO_TRUTH names functions that no longer exist: {stale}"
        )

    @pytest.mark.parametrize(
        "module, snippet",
        [
            # the four files round 7 found — each one's real shape
            ("hosts", "    save_hosts(home, hosts)\n    with gitops.commit_lock(home):\n        gitops.commit(home, 'm', paths=[])\n"),
            ("verbs", "    compile_reference(a, b)\n    with gitops.commit_lock(home):\n        gitops.commit(home, 'm', paths=[])\n"),
            ("miner", "    _reconcile_and_land(home, p, r, c, w)\n    with gitops.commit_lock(home):\n        gitops.commit(home, 'm', paths=[])\n"),
            ("teach", "    create_record(home, record)\n    with gitops.commit_lock(home):\n        gitops.commit(home, 'm', paths=[])\n"),
        ],
    )
    def test_it_catches_a_planted_violation(self, module, snippet, tmp_path):
        """The check is only worth its runtime if it FAILS on the bug. A
        violation of the exact shape round 7 found — mutate, THEN lock, then
        commit — is planted into each of the four files, one at a time, in a
        COPY of the source tree, and the analysis must flag every one.

        This is the test that keeps the checker honest: a structural test
        that cannot be shown catching its own bug class is a structural
        test that passes because it looks at nothing."""
        import shutil

        sandbox = tmp_path / "src" / "self_learn"
        shutil.copytree(SRC, sandbox)
        planted = f"\n\ndef _planted_violation(home):\n{snippet}"
        (sandbox / f"{module}.py").write_text(
            (sandbox / f"{module}.py").read_text(encoding="utf-8") + planted,
            encoding="utf-8",
        )
        requires = _Analysis(sandbox).requires_lock()
        assert f"{module}._planted_violation" in requires, (
            f"the planted mutate-then-lock violation in {module}.py was NOT "
            "flagged — the checker is blind to its own bug class"
        )


# ====================================== the runtime half: every _cmd_*, live


def _cmd_functions() -> list[str]:
    """Every dispatch surface in cli.py, BY INTROSPECTION. A hardcoded
    list is exactly the failure this round exists to fix: ``_cmd_host``
    was the surface the last round's list did not have."""
    return sorted(
        name
        for name, obj in vars(cli).items()
        if name.startswith("_cmd_") and inspect.isfunction(obj)
    )


#: cli.py's own map from a `_cmd_*` to the argv(s) that reach it. Derived
#: names, hand-written argv — the ENUMERATION is what must not be hand-
#: written (a missed surface is the bug); the arguments cannot be guessed.
#: :func:`test_every_cmd_surface_is_covered` fails when a new `_cmd_*`
#: appears without an entry here, so the two cannot drift.
#:
#: A surface may carry SEVERAL argvs — `host` earns three: `rebind` is the
#: one that was probed into a traceback plus a staged bucket-wide rename,
#: and a single argv per surface would have driven only `add`. One argv per
#: dispatch function is the same too-coarse granularity that let this class
#: hide in the first place.
_ARGV_FOR = {
    "_cmd_canary": None,  # writes canaries.json (cache-local), not the ledger
    "_cmd_chezmoi_adopt": None,  # A2 §10.5: writes only the dotfiles repo
    # (its OWN git, chezmoi's), never the ledger — no _home_gate either,
    # same reasoning as _cmd_canary/_cmd_prune_memory.
    "_cmd_followup": [["followup", "done", "lrn-eeee0001"]],
    "_cmd_host": [
        ["host", "add", "{host}"],
        ["host", "rebind", "{project_slug}", "{host2}"],
        ["host", "remove", "{host}"],
    ],
    "_cmd_host_inner": None,  # driven through _cmd_host
    "_cmd_import": [["import", "--backlog", "{empty}"]],
    "_cmd_init": [["init"]],
    "_cmd_link": [["link", "contradicts", "lrn-eeee0001", "lrn-eeee0002"]],
    "_cmd_list": [["list"]],
    "_cmd_mine": [["mine", "status"]],
    "_cmd_proposal": [["proposal", "validate", "lrn-eeee0001"]],
    "_cmd_prune_memory": None,  # rewrites ~/.claude memory, not the ledger
    "_cmd_push": [["push"]],
    "_cmd_reconcile": [["reconcile"]],
    "_cmd_recompile": [["recompile"]],
    "_cmd_report": [["report"]],
    "_cmd_sentinel": [["sentinel", "hold"]],
    "_cmd_status": [["status"]],
    "_cmd_status_fast": [["status", "--fast"]],
    "_cmd_telemetry": [["telemetry", "flush"]],
    "_cmd_verb": [["reject", "lrn-eeee0001"]],
    "_cmd_worker": [["worker", "run"]],
}


def _cases() -> list:
    out = []
    for cmd in _cmd_functions():
        for argv in _ARGV_FOR.get(cmd) or [None]:
            out.append(pytest.param(cmd, argv, id=f"{cmd}:{' '.join(argv or ['-'])}"))
    return out


def test_every_cmd_surface_is_covered():
    """The introspected surfaces and the argv table must agree — this is
    what makes the live test below unable to quietly skip a new command."""
    missing = sorted(set(_cmd_functions()) - set(_ARGV_FOR))
    assert not missing, (
        f"new dispatch surface(s) with no argv in _ARGV_FOR: {missing} — "
        "add one (or None with a reason) so they are driven against a held "
        "lock like every other surface"
    )


class TestEveryCommandSurvivesAHeldLock:
    """Drive EVERY ``_cmd_*`` against a real second process holding the
    ledger's commit lock. Three properties, all of which ``host rebind``
    failed when probed (round 7 BLOCKER 1):

    1. a clean non-zero exit (or 0 — a read surface may legitimately not
       care), never a traceback;
    2. no stranded staged/uncommitted state left in the ledger;
    3. and (1) without any surface having been listed by hand.
    """

    @staticmethod
    def _holder(tmp_path, repo, monkeypatch):
        monkeypatch.setattr(gitops, "COMMIT_LOCK_TIMEOUT", 0.3)
        ready, release = tmp_path / "lk-ready", tmp_path / "lk-release"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""
                    import sys, time
                    sys.path.insert(0, {CLI_SRC!r})
                    from pathlib import Path
                    from self_learn import gitops
                    with gitops.commit_lock(Path({str(repo)!r})):
                        Path({str(ready)!r}).touch()
                        deadline = time.monotonic() + 60
                        while (not Path({str(release)!r}).exists()
                               and time.monotonic() < deadline):
                            time.sleep(0.01)
                """),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = __import__("time").monotonic() + 30
        while not ready.exists() and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.005)
        assert ready.exists(), "the lock holder never started"
        return proc, release

    @pytest.mark.parametrize("cmd, argv", _cases())
    def test_a_held_lock_is_a_clean_exit_and_strands_nothing(
        self, cmd, argv, tmp_path, monkeypatch, capsys
    ):
        if argv is None:
            pytest.skip(f"{cmd}: not a ledger-mutating surface")
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("SELF_LEARN_MINER", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("SELF_LEARN_MEMORY_DIR", str(tmp_path / "memory"))
        (tmp_path / "empty").mkdir()
        # a SECOND real repo for `host rebind` to re-point at, plus the
        # project bucket that makes the rebind move a real tracked bucket
        # (the probed shape: a bucket-wide `git mv` before the lock)
        host2 = tmp_path / "host-repo-moved"
        init_repo(host2)
        (host2 / "CLAUDE.md").write_text("# moved\n", encoding="utf-8")
        commit_all(host2, "moved host seed")
        _no_model_on_path(tmp_path, monkeypatch)
        from self_learn.ledger_ops import create_record

        for rid in ("lrn-eeee0001", "lrn-eeee0002"):
            create_record(home, make_behavior_local(rid))
        # a real, TRACKED project bucket for `host rebind` to git-mv
        create_record(
            home,
            _project_record("lrn-eeee0003"),
            project_path=env.host,
        )
        commit_all_local(home)
        clean_before = git(home, "status", "--porcelain").stdout

        argv = [
            a.format(
                host=str(env.host),
                host2=str(host2),
                empty=str(tmp_path / "empty"),
                project_slug=str(env.host),
            )
            for a in argv
        ]
        if cmd == "_cmd_init":
            # Delta code gate: `make_env`'s ledger is already COMPLETE, so
            # `init_home` hit its `already_complete` early return and never
            # reached the lock — the case passed while asserting nothing.
            # (Proven by the reviewer: replacing the `with` body with a
            # raise still passed.) Remove one layout dir so step 6 — the
            # only init path that mutates a pre-existing repo — actually
            # runs under the invariant.
            import shutil

            shutil.rmtree(home / "telemetry", ignore_errors=True)
            # No commit here: an empty layout dir is untracked, so its
            # removal leaves `git status` byte-identical and the earlier
            # `clean_before` snapshot stays valid.

        holder, release = self._holder(tmp_path, home, monkeypatch)
        try:
            code = cli.main(argv)  # must not raise
        finally:
            release.touch()
            holder.wait(timeout=60)
        out = capsys.readouterr()

        assert "Traceback" not in out.err, (
            f"{cmd} ({argv}) died with a stack dump on a merely-held lock:\n"
            f"{out.err}"
        )
        assert isinstance(code, int)
        assert code not in (gitops.EXIT_HALF_WRITTEN,) or "Repair:" in out.err, (
            f"{cmd} reported the half-written state without naming a repair"
        )
        # (2) Nothing STRANDED. "Stranded" is precisely: state that no
        # producer will ever commit — each pathspec-commits only its own
        # paths — so the first non-FF push's `pull --rebase --autostash`
        # destroys it. That is the documented corruption, and `host
        # rebind` walked right through it (probed: exit 1 + traceback,
        # ledger left holding a staged bucket-wide rename and a modified
        # hosts.yaml).
        #
        # The bar is "recoverable", not "byte-identical", and the
        # difference is load-bearing rather than a hedge: `worker run`'s
        # writes are made by the MODEL, in another process, which no lock
        # of ours can hold — its untracked proposal can outlive a refusal
        # no matter what this code does. So the property asserted is the
        # one that actually means "not lost": after the round-7 recovery
        # verb runs, the ledger is back exactly where it started. A staged
        # rename fails this (reconcile refuses to commit half a `git mv`,
        # by design) — which is what keeps this assertion sharp against
        # the very bug it was written for.
        from self_learn import reconcile as reconcile_mod

        dirty = git(home, "status", "--porcelain").stdout
        if dirty != clean_before:
            reconcile_mod.reconcile(home, no_push=True)
        after = git(home, "status", "--porcelain").stdout
        assert after == clean_before, (
            f"{cmd} ({argv}) left STRANDED uncommitted state behind after "
            "failing on a held lock, and `self-learn reconcile` could not "
            "heal it — no other producer will ever commit it, and the "
            "first non-FF push's `pull --rebase --autostash` destroys it. "
            f"This is the documented corruption, through {cmd}'s door.\n"
            f"  before:      {clean_before!r}\n"
            f"  after cmd:   {dirty!r}\n"
            f"  after heal:  {after!r}\n{out.err}"
        )


def _no_model_on_path(tmp_path: Path, monkeypatch) -> None:
    """A `claude` shim that writes nothing and exits 0.

    Without it `worker run` finds the REAL Claude CLI on this machine's
    PATH and drives a live model from the test suite. Tests never touch
    the real anything (conftest holds that line for the home, the cache
    and the transcripts) — the model is the same rule."""
    shims = tmp_path / "no-model"
    shims.mkdir(exist_ok=True)
    shim = shims / "claude"
    shim.write_text("#!/usr/bin/env bash\ncat > /dev/null\nexit 0\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}:{__import__('os').environ['PATH']}")


def _project_record(rid: str):
    from support import make_knowledge

    return make_knowledge(record_id=rid)


def make_behavior_local(rid: str):
    from support import make_behavior

    return make_behavior(record_id=rid)


def commit_all_local(home: Path) -> None:
    from support import commit_all

    commit_all(home, "seed records")
