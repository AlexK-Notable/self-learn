"""landing_fixture.py -- shared throwaway-repo builder for `land`'s
end-to-end tests (test_land_runner.py). NOT collected by pytest itself
(no test_ prefix) -- a plain helper module.

Every fixture repo is built fresh under tmp_path: a bare "origin" plus a
"repo" main checkout, with the minimal file layout `land` requires
(docs/specs/self-learn/{03-decisions,14-forward-work-map}.md, a pinned
test_worker_contract.py, and copies of the shipped landing package's data
files). `land` itself is invoked via its real on-disk path in THIS build
(never copied), with `--root` resolution driven by the fixture's own cwd
(§4.1's root-resolution rule): PROJECT (the venv `land` uses for its
python module calls) is this build's own, real and already `uv sync`'d;
GITROOT/`--root` is always the fixture. `XDG_CACHE_HOME` and
`SELF_LEARN_HOME` are always pointed at tmp_path -- `~/.self-learn` is
never read or written by anything here (UN2).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

THIS_REPO_CLI = Path(__file__).resolve().parent.parent  # plugins/self-learn/cli
LAND = THIS_REPO_CLI / "scripts" / "land"
LANDING_PKG = THIS_REPO_CLI / "src" / "self_learn" / "landing"


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def env_for(tmp_path: Path) -> dict:
    env = dict(os.environ)
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["SELF_LEARN_HOME"] = str(tmp_path / "self-learn-home-unused")
    env.pop("SELF_LEARN_ANALYST_MODEL", None)
    env.pop("SELF_LEARN_ANALYST_TIMEOUT", None)
    # neutralise the OPERATOR's own gitconfig for the `land` subprocess
    # itself (never the fixture-setup git calls, which use os.environ
    # directly) -- PRV3/gate-F-1 requires `land` supply
    # `-c merge.conflictStyle=diff3` on its OWN invocation and never lean
    # on an inherited global default; a dev machine with
    # `merge.conflictStyle=diff3` already set globally would otherwise
    # mask a runner that dropped its own `-c` flag (M10).
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    return env


# ---------------------------------------------------------------------------
# The WORLD_REMEASURE fixture (U-armor's world). `land`'s WLD2 branch shells
# out to the TARGET TREE's own test_armor.py with `--remeasure --anchor
# <sha>`; the stand-in below is contract-identical to the real module's CLI,
# MEASURED against it in an isolated clone (misc/u-land-work/armor_contract_
# probe.sh, misc/u-land-work/armor_owed_probe.sh, 2026-08-29):
#
#   success : --anchor <master's tip, read mid-merge>  -> rc 0, stderr
#             "ANCHOR <old> -> <new>", the module rewritten
#   no-op   : --anchor == the ANCHOR already in the file -> rc 1, stderr
#             "ANCHOR did not change (X -> X) ...", file byte-identical
#   owed    : a watched node edited/deleted since <anchor> with no
#             exemption -> rc 1, one "OWED: <file>: edited:<name>" line per
#             node plus a "refusing to write" line, file byte-identical
#
# It censuses ONE watched file rather than eight, and hashes each top-level
# node's `ast.dump` rather than the real module's normalized dump. `land`
# reads neither: only the exit code and the rewritten bytes it must stage.
_FIXTURE_ARMOR = '''\
"""Fixture stand-in for the shipped cli/tests/test_armor.py."""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ANCHOR = "@@ANCHOR@@"
WATCHED = "plugins/self-learn/cli/tests/test_watched.py"
#: dated, anchored exemption entries -- node names the census may differ on.
EXEMPT: tuple[str, ...] = ()

_REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
)


def _census(source: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.parse(source).body:
        name = getattr(node, "name", None)
        if name is None:
            continue
        out[name] = hashlib.sha256(ast.dump(node).encode()).hexdigest()
    return out


def _at(rev: str) -> dict[str, str]:
    text = subprocess.run(
        ["git", "show", rev + ":" + WATCHED], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    return _census(text)


def _owed(new_anchor: str) -> list[str]:
    a = _at(new_anchor)
    h = _census((_REPO_ROOT / WATCHED).read_text())
    owed = ["missing:" + k for k in a if k not in h]
    owed += ["edited:" + k for k in a if k in h and h[k] != a[k]]
    return [o for o in owed if o.split(":", 1)[1] not in EXEMPT]


def _remeasure(new_anchor: str) -> int:
    old = ANCHOR
    owed = _owed(new_anchor)
    if owed:
        for o in owed:
            print("OWED: " + WATCHED + ": " + o, file=sys.stderr)
        print(
            "refusing to write test_armor.py -- the above nodes are owed a "
            "dated, anchored exemption entry naming a spec section first",
            file=sys.stderr,
        )
        return 1
    me = Path(__file__)
    new = me.read_text().replace(
        'ANCHOR = "' + old + '"', 'ANCHOR = "' + new_anchor + '"', 1
    )
    tmp = me.with_suffix(".py.tmp")
    tmp.write_text(new)
    os.replace(tmp, me)
    if new_anchor == old:
        print(
            "ANCHOR did not change (" + old + " -> " + new_anchor + ") -- the "
            "landing chain's &&-chain must abort here (the no-op guard)",
            file=sys.stderr,
        )
        return 1
    print("ANCHOR " + old + " -> " + new_anchor, file=sys.stderr)
    return 0


def test_fixture_arm5_anchor_is_not_stale():
    """ARM5's shape. RED until this landing's merge commit exists, GREEN
    the moment it does -- which is exactly why `land` must run no armor
    test between `--remeasure` and `git commit`."""
    merge = subprocess.run(
        ["git", "rev-list", "--first-parent", "--merges", "-1", "master"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert merge, "ARM5: no first-parent merge on master yet"
    parent = subprocess.run(
        ["git", "rev-parse", "--short=7", merge + "^1"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert ANCHOR == parent, (ANCHOR, parent)


if __name__ == "__main__":
    _argv = sys.argv[1:]
    if "--remeasure" not in _argv:
        raise SystemExit(
            "test_armor.py has no standalone CLI mode other than --remeasure"
        )
    raise SystemExit(_remeasure(_argv[_argv.index("--anchor") + 1]))
'''

#: The one BEHAVIOUR file the fixture's armor module censuses. A branch that
#: edits `test_watched_one`'s BODY owes an exemption entry; one that only
#: ADDS a node does not (the real module's B1-B7 rule).
_FIXTURE_WATCHED = (
    "def test_watched_one():\n    assert (2 + 2) == 4\n\n\n"
    "def test_watched_two():\n    assert (3 * 3) == 9\n"
)

#: A stand-in for U-scrub's shipped test_personal_literals.py (CHK5). It
#: resolves the tree it judges from its OWN on-disk location, exactly as the
#: real one does -- which is what makes M61 (CHK5 reading the MAIN
#: checkout's copy under --dry-run instead of the dry-run worktree's)
#: observable at all.
_FIXTURE_LITERALS = (
    "import subprocess\n"
    "from pathlib import Path\n\n"
    "ROOT = Path(subprocess.run(\n"
    "    ['git', 'rev-parse', '--show-toplevel'], cwd=Path(__file__).parent,\n"
    "    capture_output=True, text=True, check=True).stdout.strip())\n\n\n"
    "def test_no_personal_literals():\n"
    "    seeded = ROOT / 'seeded_literal.txt'\n"
    "    assert not seeded.exists(), 'personal literal present: ' + str(seeded)\n"
)


def _write_worker_contract(cli: Path, pins: dict[str, str]) -> None:
    lines = ["_ARMOR_SHAS = {"]
    for path, sha in pins.items():
        lines.append(f'    "{path}": "{sha}",')
    lines.append("}")
    lines.append("")
    (cli / "tests" / "test_worker_contract.py").write_text("\n".join(lines))


def _sha256_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_repo(
    tmp_path: Path,
    *,
    with_ui: bool = False,
    armor: str = "shas",
    with_literals: bool = False,
) -> Path:
    """A clean, pushed origin+master fixture with everything `land` needs
    to run its full non-docs lane (a trivial CLI + optionally UI suite).

    ``armor`` selects which of the two worlds `detect_world()` (WLD1/WLD2)
    must find:

    * ``"shas"``      -- the pre-U-armor world: `test_worker_contract.py`
      carries an `_ARMOR_SHAS` dict and no `test_armor.py` exists, so
      `land` takes its CHK2 pin-check branch.
    * ``"remeasure"`` -- U-armor's world, live on master since `9ada450`:
      `test_armor.py` exists and `test_worker_contract.py` carries no
      pins, so `land` takes its WLD2 `--remeasure` branch.

    ``with_literals`` ships a `test_personal_literals.py` that judges the
    tree it is READ FROM (CHK5/M61); without it CHK5 is a no-op.
    """
    if armor not in ("shas", "remeasure"):
        raise ValueError(f"armor must be 'shas' or 'remeasure', not {armor!r}")
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    # the bare repo's default HEAD may be refs/heads/main (git's newer
    # default) regardless of what gets pushed to it -- pin it to master so
    # `git ls-remote --exit-code origin HEAD` (PRE6) resolves.
    subprocess.run(["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/master"], check=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "remote", "add", "origin", str(origin))

    (repo / "docs/specs/self-learn/drafts").mkdir(parents=True)
    (repo / "docs/specs/self-learn/03-decisions.md").write_text(
        "# decisions\n\n| id | statement | rationale |\n|---|---|---|\n"
        "| S-1 | first | r |\n| S-2 | second | r |\n"
    )
    (repo / "docs/specs/self-learn/14-forward-work-map.md").write_text(
        "# forward work\n\n| id | statement | status | note |\n|---|---|---|---|\n"
        "| FW-1 | first | WATCH | n |\n| FW-2 | second | WATCH | n |\n"
    )
    (repo / "docs/specs/self-learn/15-orchestration-runbook.md").write_text("# runbook\n")

    cli = repo / "plugins/self-learn/cli"
    (cli / "scripts" / "measured").mkdir(parents=True)
    (cli / "tests").mkdir(parents=True)
    landing_dst = cli / "src" / "self_learn" / "landing"
    landing_dst.mkdir(parents=True)

    # copy the shipped landing package's DATA files (fragments, etc), not
    # the .py code -- `land` runs the real build's own venv/code (see
    # module docstring), so only the DATA needs to live under --root.
    for fname in ("sanitize_fragments.txt",):
        shutil.copy(LANDING_PKG / fname, landing_dst / fname)
    (landing_dst / "known_failures.txt").write_text("")
    (landing_dst / "doc_reading_set.txt").write_text(
        "plugins/self-learn/cli/tests/test_alpha.py\n"
    )

    # the armor world (WLD1/WLD2)
    (cli / "tests" / "backends.py").write_text("# backends fixture module\n")
    if armor == "shas":
        _write_worker_contract(
            cli,
            {"plugins/self-learn/cli/tests/backends.py": _sha256_of(cli / "tests" / "backends.py")},
        )
    else:
        # No pins anywhere in the file -- detect_world() must read
        # WORLD_REMEASURE, not "armor_shas with zero pins".
        (cli / "tests" / "test_worker_contract.py").write_text(
            '"""_ARMOR_SHAS retired by U-armor; the census lives in '
            'test_armor.py."""\n'
        )
        (cli / "tests" / "test_watched.py").write_text(_FIXTURE_WATCHED)
        # ANCHOR starts at a value that is NOT master's tip, so the runner's
        # own `--anchor $(rev-parse --short=7 HEAD)` is a genuine advance.
        (cli / "tests" / "test_armor.py").write_text(
            _FIXTURE_ARMOR.replace("@@ANCHOR@@", "0000000")
        )

    if with_literals:
        (cli / "tests" / "test_personal_literals.py").write_text(_FIXTURE_LITERALS)

    # a trivial, FAST `scripts/suite` for the full (non-docs) lane, and a
    # matching test the suite can run.
    (cli / "tests" / "test_alpha.py").write_text(
        "def test_docs():\n    assert (1 + 1) == 2\n"
    )
    suite_script = cli / "scripts" / "suite"
    suite_script.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        "ROOT=$(cd \"$(dirname \"$0\")/../../../..\" && pwd)\ncd \"$ROOT\" || exit 2\n"
        "python3 -m pytest plugins/self-learn/cli/tests -q -p no:cacheprovider\n"
        "exit $?\n"
    )
    suite_script.chmod(0o755)

    if with_ui:
        ui = repo / "plugins/self-learn/ui"
        (ui / "tests").mkdir(parents=True)
        (ui / "tests" / "test_beta.py").write_text("def test_ui():\n    assert True\n")

    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "push", "-q", "origin", "master")
    return repo


def make_branch(repo: Path, name: str, *, edits: dict[str, str] | None = None) -> None:
    """Create a branch off current HEAD with the given file edits committed.

    With no edits, the branch is just a pointer at master's tip (no empty
    commit attempted -- `git commit` refuses one)."""
    git(repo, "checkout", "-q", "-b", name)
    if edits:
        for rel, content in edits.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"branch {name}")
    git(repo, "checkout", "-q", "master")


def run_land(repo: Path, tmp_path: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = env_for(tmp_path)
    return subprocess.run(
        [str(LAND), *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
