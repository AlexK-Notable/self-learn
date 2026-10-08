"""S-82 (GM, 2026-10-08): one repository, two registrations, two modes.

The orchestrator recommended that self-learn commit and push its own
changes in claude-skills again, pausing autosync around each, as it did
until 2026-10-04; the user accepted. So claude-skills, registered once as
the skills root and once as a project host, goes back to ``git`` mode as
the skills root while its project registration stays ``plain``.

Every write follows the mode of the registration it goes through
(``hosts.host_mode(..., registration=...)``), never the path's first
match; ``host remove --skills-root | --project`` drops one registration
and keeps the other; the skills root's own ``claude-md`` is refused while
the same repo is a project in another mode (both legs write one file);
``--selftest`` shows the double registration with each mode.

Marked *control*: passes on master ``e0d1025`` too. G1 (S-80, landed
before this unit) already gave the project legs in ``verbs.py`` their own
registration's mode (``verbs._project_mode``), so the route-level
behaviours (a), (b), (c), (f) and the hook and new-skill routes are
controls here; the rest is red on master. Every scenario runs on pytest
sandbox repos and ledgers; ids are synthetic.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from self_learn import batch, cli, gitops, hosts, report, selfcheck, sentinel, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.hook_compiler import script_name
from self_learn.hosts import MARKER_FILENAME, host_add, host_mode, load_hosts
from self_learn.ledger_ops import create_record, find_record_path, stamp_proposal, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    git,
    hook_proposal_fields,
    last_verb_sha,
    make_behavior,
    make_env,
    proposal_dict,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


# ------------------------------------------------------------------ helpers


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all").stdout


def _ignored(repo: Path, rel: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--", rel],
        capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode == 0


def _exclude(repo: Path) -> Path:
    out = Path(git(repo, "rev-parse", "--git-path", "info/exclude").stdout.strip())
    return out if out.is_absolute() else repo / out


def _commit_files(repo: Path, sha: str) -> list[str]:
    return git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split()


def _registry(repo: Path, *, root: str | None, project: str | None) -> str:
    """hosts.yaml text registering *repo* as the skills root in mode
    *root* and/or as a project host in mode *project* (``None`` = not
    registered that way)."""
    text = ""
    if root == "git":
        text += f"skills_root: {repo}\n"
    elif root == "plain":
        text += f"skills_root:\n  path: {repo}\n  mode: plain\n"
    if project is None:
        text += "projects: []\n"
    else:
        text += f"projects:\n  - path: {repo}\n"
        if project == "plain":
            text += "    mode: plain\n"
    return text


def _double(tmp_path: Path, *, root: str | None = "git", project: str | None = "plain"):
    """`make_env`'s repo registered as the skills root (mode *root*) AND
    a project host (mode *project*) -- claude-skills after the switch by
    default. The plain-host marker is written and hidden by the
    operator's own exclude line, so `git status` starts clean."""
    env = make_env(tmp_path)
    home, repo = env.ledger, env.host
    (home / "hosts.yaml").write_text(_registry(repo, root=root, project=project), encoding="utf-8")
    if _status(home):  # `make_env` already wrote root=git, project=git
        commit_all(home, f"registry: root={root} project={project}")
    if "plain" in (root, project):
        (repo / MARKER_FILENAME).write_text("plain registration\n", encoding="utf-8")
        exclude = _exclude(repo)
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(f"/{MARKER_FILENAME}\n", encoding="utf-8")
    assert _status(repo) == ""
    return env


def _with_remote(tmp_path: Path, repo: Path, name: str) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def _project_lesson(home: Path, repo: Path, rid: str) -> str:
    create_record(home, make_behavior(scope="project", record_id=rid), project_path=repo)
    commit_all(home, f"seed {rid}")
    return rid


def _skill_lesson(home: Path, rid: str) -> str:
    create_record(home, make_behavior(scope="skill:s", record_id=rid))
    commit_all(home, f"seed {rid}")
    return rid


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _sheet(tmp_path: Path, rid: str, verb: str, dest: str | None = None) -> batch.Sheet:
    path = tmp_path / f"sheet-{rid}-{verb}.yaml"
    item = f"  - id: {rid}\n    verb: {verb}\n" + (f"    dest: {dest}\n" if dest else "")
    path.write_text(f"version: 1\nitems:\n{item}", encoding="utf-8")
    return batch.load_sheet(path)


@pytest.fixture
def commits_under_pause(monkeypatch):
    """Every `gitops.commit` call, with whether the autosync pause was
    live at that moment: ``[(repo, live)]``."""
    seen: list[tuple[Path, bool]] = []
    real = gitops.commit

    def spy(repo, *args, **kwargs):
        seen.append((Path(repo).resolve(), sentinel.is_live()))
        return real(repo, *args, **kwargs)

    monkeypatch.setattr(gitops, "commit", spy)
    return seen


# ------------------------------------- (a) the project leg: plain, no commit


def test_a_project_claude_md_local_route_resolves_plain_and_makes_no_commit(tmp_path):
    """(a) *control* (G1's `verbs._project_mode` already gave the project
    legs their own registration's mode on master)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _project_lesson(home, repo, "lrn-8b000001")
    head = _head(repo)

    result = verbs.route(home, rid, dest="claude-md:local", no_push=True)

    assert result.mode == "plain"
    assert result.host_commit_sha is None
    assert rid in (repo / "CLAUDE.local.md").read_text(encoding="utf-8")  # the write landed
    assert _head(repo) == head  # never committed
    assert _ignored(repo, "CLAUDE.local.md") and _status(repo) == ""


def test_host_mode_answers_for_the_registration_named(tmp_path):
    """The resolver itself: one path, two registrations, two answers.
    Red on master (`host_mode` takes no `registration`)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host

    assert host_mode(home, repo, registration="skills-root") == "git"
    assert host_mode(home, repo, registration="project") == "plain"
    assert host_mode(home, repo) == "git"  # the path-only answer: the root first

    # a path registered one way only: the other registration falls back to it
    (home / "hosts.yaml").write_text(_registry(repo, root="plain", project=None), encoding="utf-8")
    assert host_mode(home, repo, registration="project") == "plain"
    assert host_mode(home, tmp_path / "unregistered", registration="project") == "git"
    with pytest.raises(hosts.HostsError, match="registration must be one of"):
        host_mode(home, repo, registration="skills_root")


def _src_host_mode_calls(root: Path) -> list[tuple[str, int, bool]]:
    calls: list[tuple[str, int, bool]] = []
    for py in sorted(root.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None
            )
            if name == "host_mode":
                named = any(k.arg == "registration" for k in node.keywords)
                calls.append((py.name, node.lineno, named))
    return calls


def test_every_host_mode_call_in_src_names_its_registration(tmp_path):
    """No production caller may ask a path alone for a mode: for a repo
    registered twice, that answers the skills root's mode for a project
    write. Red on master (every call passed only a path)."""
    # positive control first: the sweep flags an unnamed call, bare or dotted
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "m.py").write_text(
        "host_mode(home, path)\n"
        "hosts.host_mode(home, path)\n"
        "host_mode(home, path, registration='project')\n",
        encoding="utf-8",
    )
    assert [named for _f, _l, named in _src_host_mode_calls(probe)] == [False, False, True]

    calls = _src_host_mode_calls(Path(hosts.__file__).resolve().parent)
    assert len(calls) >= 15, calls  # control: the sweep sees the real call sites
    assert {name for name, _line, _named in calls} >= {
        "verbs.py", "hosts.py", "cli.py", "report.py", "selfcheck.py",
    }
    assert [(name, line) for name, line, named in calls if not named] == []


def test_the_readers_report_the_project_registration_s_own_mode(tmp_path, monkeypatch, capsys):
    """`host list`, `report`'s project row and `show` name each
    registration's mode. Red on master (all three read the root's)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _project_lesson(home, repo, "lrn-8b000002")
    verbs.route(home, rid, dest="claude-md:local", no_push=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()

    assert cli.main(["host", "list"]) == 0
    out = capsys.readouterr().out
    assert f"skills_root: {repo}\n" in out  # git: no suffix, nothing broken
    assert f"  - {repo}  [mode=plain]\n" in out

    (row,) = report._resolve_project_rows(home)
    assert row["spec"] is not None and row["spec"].mode == "plain"

    canon = verbs.show(home, rid)["canon"]
    assert canon["host"] == str(repo) and canon["mode"] == "plain"


def test_re_adding_the_plain_project_is_idempotent_while_the_root_is_git(tmp_path):
    """MODE6 compares a re-add with the registration it re-adds. Red on
    master: the project re-add read the root's `git` and refused as a mode
    flip."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    ledger_head = _head(home)

    result = host_add(home, repo, "project", mode="plain")

    assert result.marker_restored is False
    assert _head(home) == ledger_head  # nothing to commit
    with pytest.raises(hosts.HostsError, match="already registered as 'plain'"):
        host_add(home, repo, "project", mode="git")  # a real flip still refuses


def test_drift_check_judges_a_hand_edit_in_the_plain_project_s_file(tmp_path):
    """`--selftest`'s drift row reads a plain host's compile record; for
    the project registration of a repo registered twice it must. Red on
    master (the row read the root's `git` and skipped the check)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _project_lesson(home, repo, "lrn-8b000003")
    verbs.route(home, rid, dest="claude-md:local", no_push=True)
    verdict, _msg = selfcheck._check_drift(home)
    assert verdict is selfcheck.Verdict.PASS  # control: clean before the edit

    local = repo / "CLAUDE.local.md"
    text = local.read_text(encoding="utf-8")
    begin, end = text.index(BEGIN_MARKER), text.index(END_MARKER)
    local.write_text(text[:end] + "- a hand-written line\n" + text[end:], encoding="utf-8")
    assert begin < end

    verdict, msg = selfcheck._check_drift(home)
    assert verdict is selfcheck.Verdict.FAIL
    assert "hand-edited outside self-learn (edited)" in msg and rid in msg


# ---------------------------------------------------------- (c) one lock


def test_c_the_two_registrations_share_one_lock(tmp_path):
    """(c) *control* (S-80 landed one lock per repository)."""
    env = _double(tmp_path)
    repo = env.host
    git_lock = gitops.host_lock_path(repo, "git")
    assert git_lock == gitops.host_lock_path(repo, "plain") == gitops.commit_lock_path(repo)
    with gitops.host_lock(repo, "git"):
        assert str(git_lock) in gitops._held_locks
        with gitops.host_lock(repo, "plain"):  # the same file: re-entrant
            assert str(git_lock) in gitops._held_locks


# ----------------------------------------------- moving the repo (rebind)


def test_a_rebind_keeps_each_registration_s_own_mode(tmp_path):
    """A repo registered twice that moves keeps the root `git` and the
    project `plain`. Red on master: the project came out `git` (the
    rebind read the root's mode and dropped the project's)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    _project_lesson(home, repo, "lrn-8b000011")
    moved = tmp_path / "moved-repo"
    repo.rename(moved)

    hosts.host_rebind(home, str(repo), moved)

    after = load_hosts(home)
    assert after.skills_root is not None and after.skills_root.resolve() == moved.resolve()
    assert after.skills_root_mode == "git"
    assert [Path(p).resolve() for p in after.projects] == [moved.resolve()]
    assert after.project_modes == {str(moved.resolve()): "plain"}
