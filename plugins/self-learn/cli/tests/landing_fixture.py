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


def make_repo(tmp_path: Path, *, with_ui: bool = False) -> Path:
    """A clean, pushed origin+master fixture with everything `land` needs
    to run its full non-docs lane (a trivial CLI + optionally UI suite)."""
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

    # a fake armor-pinned file + the pins dict referencing it
    (cli / "tests" / "backends.py").write_text("# backends fixture module\n")
    _write_worker_contract(cli, {"plugins/self-learn/cli/tests/backends.py": _sha256_of(cli / "tests" / "backends.py")})

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
