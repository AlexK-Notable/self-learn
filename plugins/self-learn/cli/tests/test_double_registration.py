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
import re
import shlex
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


def test_the_plain_project_is_gated_by_its_marker_while_the_root_is_git(
    tmp_path, monkeypatch, capsys
):
    """A host is checked as the registration it is asked about: the plain
    project needs its marker (U-hostmode §4.4) even though the same path
    is a git skills root. Red on master: the path-only lookup read the
    root's `git`, found a git repo and passed the project with no marker."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _project_lesson(home, repo, "lrn-8b000012")
    (repo / MARKER_FILENAME).unlink()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()

    assert cli.main(["host", "list"]) == 0
    out = capsys.readouterr().out
    assert f"skills_root: {repo}\n" in out  # control: the git root is sound
    assert f"  - {repo}  [mode=plain]  ⚠ BROKEN — " in out
    assert f"carries no {MARKER_FILENAME} marker" in out
    with pytest.raises(verbs.NeedsPerson, match="carries no .* marker"):
        verbs.route(home, rid, dest="claude-md:local", no_push=True)
    assert _record(home, rid).status == "pending"


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


def test_push_follows_the_git_registration_whichever_is_listed_first(tmp_path):
    """`push` skips a plain registration before it counts the repo as
    seen. Red on master: a plain skills root (listed first) marked the
    repo seen and its git project registration was never pushed."""
    env = _double(tmp_path, root="plain", project="git")
    home, repo = env.ledger, env.host
    bare = _with_remote(tmp_path, repo, "host-remote")
    (repo / "notes.md").write_text("an unpushed commit\n", encoding="utf-8")
    commit_all(repo, "unpushed")
    assert gitops.unpushed_commits(repo)  # control

    pushed = verbs.push_pending(home)

    assert repo.resolve() in [Path(r).resolve() for r, _ in pushed.entries]
    assert git(bare, "rev-parse", "main").stdout.strip() == _head(repo)


# ------------------------------- (b) the skills-root leg: git, committed


def test_b_a_skill_md_route_commits_exactly_that_skill_md_under_the_pause(
    tmp_path, commits_under_pause
):
    """(b) *control*: the skills root's git registration commits exactly
    the SKILL.md it changed, while the autosync pause is held, and pushes
    it."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    bare = _with_remote(tmp_path, repo, "host-remote")
    rid = _skill_lesson(home, "lrn-8b000004")
    assert not sentinel.is_live()  # control: nobody holds the pause before

    result = verbs.route(home, rid, dest="skill-md")

    assert result.mode == "git" and result.host_commit_sha is not None
    rel = env.skill_md.relative_to(repo).as_posix()
    assert _commit_files(repo, result.host_commit_sha) == [rel]
    assert rid in env.skill_md.read_text(encoding="utf-8")
    assert (repo.resolve(), True) in commits_under_pause  # the host commit, paused
    assert not sentinel.is_live()  # released after
    assert result.host_push is not None and result.host_push.ok
    assert git(bare, "rev-parse", "main").stdout.strip() == result.host_commit_sha
    assert _status(repo) == ""
    assert not _ignored(repo, rel)  # git mode writes no ignore line


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


# --------------------------------------------- (d) remove one registration


def test_d_host_remove_skills_root_keeps_the_project_and_project_keeps_the_root(
    tmp_path, monkeypatch, capsys
):
    """(d) Red on master: there was no `--skills-root` / `--project`, and
    one `host remove` dropped both registrations."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))

    assert cli.main(["host", "remove", str(repo), "--skills-root"]) == 0
    after = load_hosts(home)
    assert after.skills_root is None
    assert [Path(p).resolve() for p in after.projects] == [repo.resolve()]
    assert after.project_modes == {str(repo.resolve()): "plain"}  # its mode kept
    subject = git(home, "log", "-1", "--format=%s", last_verb_sha(home)).stdout.strip()
    assert subject == f"self-learn: host remove skills-root {repo.resolve()}"
    assert (repo / MARKER_FILENAME).is_file()  # GATE5: the marker stays

    # the switch the orchestrator runs (O3): the root comes back in git mode
    host_add(home, repo, "skills-root", mode="git")
    assert host_mode(home, repo, registration="skills-root") == "git"
    assert host_mode(home, repo, registration="project") == "plain"

    assert cli.main(["host", "remove", str(repo), "--project"]) == 0
    after = load_hosts(home)
    assert after.skills_root is not None and after.skills_root.resolve() == repo.resolve()
    assert after.skills_root_mode == "git" and after.projects == []

    capsys.readouterr()
    assert cli.main(["host", "remove", str(repo), "--project"]) == 64  # no project entry left
    assert "is not a registered project host" in capsys.readouterr().err
    assert load_hosts(home).skills_root is not None  # nothing changed

    # control: the bare verb still drops every registration of the path
    host_add(home, repo, "project", mode="plain")
    assert cli.main(["host", "remove", str(repo)]) == 0
    after = load_hosts(home)
    assert after.skills_root is None and after.projects == []


def test_d_removing_one_registration_counts_only_that_registration_s_lessons(
    tmp_path, monkeypatch, capsys
):
    """The routed-lesson refusal of `host remove` counts what the named
    registration compiles: skill lessons for the root, project lessons
    for the project. Red on master (no registration to name)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    skill = _skill_lesson(home, "lrn-8b000005")
    verbs.route(home, skill, dest="skill-md", no_push=True)
    one = _project_lesson(home, repo, "lrn-8b000006")
    two = _project_lesson(home, repo, "lrn-8b000007")
    verbs.route(home, one, dest="claude-md:local", no_push=True)
    verbs.route(home, two, dest="claude-md:local", no_push=True)
    assert sorted(hosts.records_targeting(home, repo)) == sorted([skill, one, two])  # control

    with pytest.raises(hosts.HostRemoveRefused) as root_refusal:
        hosts.host_remove(home, repo, registration="skills-root")
    assert "1 routed record(s)" in str(root_refusal.value)
    assert skill in str(root_refusal.value) and one not in str(root_refusal.value)
    with pytest.raises(hosts.HostRemoveRefused) as project_refusal:
        hosts.host_remove(home, repo, registration="project")
    assert "2 routed record(s)" in str(project_refusal.value)
    assert skill not in str(project_refusal.value)

    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()
    assert cli.main(["host", "remove", str(repo), "--project", "--gate-only"]) == 0
    out = capsys.readouterr().out
    assert f"host remove: project {repo.resolve()}" in out
    assert "--gate-only: 2 routed record(s)" in out
    assert load_hosts(home).skills_root is not None


# ------------------------------- (e) the skills root's own claude-md


def test_e_the_skills_root_claude_md_is_refused_by_name_while_double_registered(tmp_path):
    """(e) Red on master: the route went through and committed the shared
    CLAUDE.md in git mode, the plain project's section with it."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _skill_lesson(home, "lrn-8b000008")
    claude_md = (repo / "CLAUDE.md").read_bytes()
    ledger_head, host_head = last_verb_sha(home), _head(repo)

    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, rid, dest="claude-md", no_push=True)

    message = str(caught.value)
    assert f"{repo} is also registered as a project host (plain mode)" in message
    assert "skills root is git mode" in message
    assert "skill-md" in message  # what to do instead
    assert _record(home, rid).status == "pending"
    assert last_verb_sha(home) == ledger_head
    assert (repo / "CLAUDE.md").read_bytes() == claude_md
    assert _head(repo) == host_head and _status(repo) == ""


def test_e_the_refusal_reaches_a_sheet_as_destination_unavailable(tmp_path):
    env = _double(tmp_path)
    home = env.ledger
    rid = _skill_lesson(home, "lrn-8b000009")
    sheet = _sheet(tmp_path, rid, "route", "claude-md")

    preview = batch.dry_run(home, sheet, actor="steward")
    result = batch.run(home, sheet, no_push=True, actor="steward")

    (pitem,), (item,) = preview.items, result.items
    assert (pitem.state, pitem.kind) == ("would-refuse", "destination-unavailable"), pitem.detail
    assert (item.state, item.kind) == ("refused", "destination-unavailable"), item.detail
    assert "also registered as a project host" in (item.detail or "")
    assert _record(home, rid).status == "pending"


@pytest.mark.parametrize(
    ("root", "project"),
    [("git", None), ("git", "git"), ("plain", "plain")],
    ids=["no-project-entry", "same-mode-git", "same-mode-plain"],
)
def test_e_the_skills_root_claude_md_still_resolves_without_two_modes(tmp_path, root, project):
    """*control*: with no project entry, or with both registrations in
    one mode (one coherent posture, `make_env`'s default), the skills
    root's claude-md resolves exactly as on master."""
    env = _double(tmp_path, root=root, project=project)
    home, repo = env.ledger, env.host
    if root == "plain":
        git(repo, "rm", "-q", "--cached", "CLAUDE.md")  # a plain host takes only ignored files
        git(repo, "commit", "-q", "-m", "untrack CLAUDE.md")
    rid = _skill_lesson(home, "lrn-8b00000a")

    result = verbs.route(home, rid, dest="claude-md", no_push=True)

    assert result.mode == root
    assert rid in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    if root == "git":
        assert result.host_commit_sha is not None
        assert _commit_files(repo, result.host_commit_sha) == ["CLAUDE.md"]
    else:
        assert result.host_commit_sha is None


def _lesson_left_on_the_root_claude_md(
    tmp_path: Path, *, agree: str = "git", diverge_to: str = "plain"
):
    """A skill lesson routed to the skills root's own claude-md while the
    two registrations' modes AGREE (both *agree*), then the project
    registration switched to *diverge_to* through the verbs (`host remove
    --project`, `host add --mode`): the double registration in two modes,
    with a lesson already on the destination it now refuses to add to."""
    env = _double(tmp_path, root=agree, project=agree)
    home, repo = env.ledger, env.host
    if agree == "plain":
        git(repo, "rm", "-q", "--cached", "CLAUDE.md")  # a plain host takes only ignored files
        git(repo, "commit", "-q", "-m", "untrack CLAUDE.md")
    rid = _skill_lesson(home, "lrn-8b00000b")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    assert rid in (repo / "CLAUDE.md").read_text(encoding="utf-8")  # control: it landed
    hosts.host_remove(home, repo, registration="project")
    if diverge_to == "plain":
        exclude = _exclude(repo)
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(f"/{MARKER_FILENAME}\n", encoding="utf-8")
    host_add(home, repo, "project", mode=diverge_to)
    assert host_mode(home, repo, registration="skills-root") == agree
    assert host_mode(home, repo, registration="project") == diverge_to
    return env, rid


def test_e_recompile_warns_and_skips_a_lesson_already_on_the_refused_destination(tmp_path):
    """Recompile names the refusal and leaves the shared file alone."""
    env, rid = _lesson_left_on_the_root_claude_md(tmp_path)
    repo = env.host
    claude_md = (repo / "CLAUDE.md").read_bytes()
    host_head = _head(repo)

    result = verbs.recompile(env.ledger, no_push=True)

    assert any(rid in w and "also registered as a project host" in w for w in result.warnings)
    assert (repo / "CLAUDE.md").read_bytes() == claude_md
    assert _head(repo) == host_head


# ---------------------------------- (f) tracked files, by registration


def test_f_a_project_write_into_a_tracked_claude_md_is_refused_and_a_skill_md_commits(
    tmp_path,
):
    """(f) *control* (G1/S-80 on master). An ADDITION into the tracked
    CLAUDE.md through the plain project registration is S-80's
    `destination-unavailable`; taking a lesson OUT of it is `needs-person`;
    the skills root's git registration commits a tracked SKILL.md."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    git(repo, "rm", "-q", "--cached", "CLAUDE.md")
    git(repo, "commit", "-q", "-m", "untrack CLAUDE.md")
    placed = _project_lesson(home, repo, "lrn-8b00000c")
    verbs.route(home, placed, dest="claude-md", no_push=True)
    assert placed in (repo / "CLAUDE.md").read_text(encoding="utf-8")  # control
    git(repo, "add", "-f", "CLAUDE.md")
    git(repo, "commit", "-q", "-m", "track CLAUDE.md after all")
    claude_md = (repo / "CLAUDE.md").read_bytes()

    added = _project_lesson(home, repo, "lrn-8b00000d")
    preview = batch.dry_run(home, _sheet(tmp_path, added, "route", "claude-md"), actor="human")
    (pitem,) = preview.items
    assert (pitem.state, pitem.kind) == ("would-refuse", "destination-unavailable"), pitem.detail
    with pytest.raises(verbs.DestinationUnavailable, match="CLAUDE.md is tracked by git"):
        verbs.route(home, added, dest="claude-md", no_push=True)
    with pytest.raises(verbs.NeedsPerson, match="CLAUDE.md is tracked by git"):
        verbs.graduate(home, placed, no_push=True)
    assert (repo / "CLAUDE.md").read_bytes() == claude_md
    assert _record(home, placed).status == "routed"

    skill = _skill_lesson(home, "lrn-8b00000e")
    rel = env.skill_md.relative_to(repo).as_posix()
    assert git(repo, "ls-files", "--", rel).stdout.strip() == rel  # control: tracked
    result = verbs.route(home, skill, dest="skill-md", no_push=True)
    assert result.mode == "git" and result.host_commit_sha is not None
    assert _commit_files(repo, result.host_commit_sha) == [rel]
    assert _status(repo) == ""


# ------------------------------------ hook scripts and new skills, git mode


def _project_hook_lesson(home: Path, repo: Path, rid: str) -> tuple[str, Record]:
    record = make_behavior(scope="project", record_id=rid)
    create_record(home, record, project_path=repo)
    write_proposal(
        home, rid,
        proposal_dict(scope="project", destination="hook", alternates=["claude-md"],
                      **hook_proposal_fields()),
    )
    stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")
    return rid, record


def test_a_project_hook_script_lands_in_the_git_root_and_is_committed(
    tmp_path, commits_under_pause
):
    """*control*: a project lesson's hook script lands in the skills
    root's `hooks/self-learn/` (S-17 D1) and the root's git registration
    commits exactly that script, under the pause."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid, record = _project_hook_lesson(home, repo, "lrn-8b00000f")

    result = verbs.route(home, rid, dest="hook", no_push=True)

    assert result.target is not None
    rel = result.target.relative_to(repo).as_posix()
    assert rel == f"hooks/self-learn/{script_name(rid, verbs.record_title(record))}"
    assert result.mode == "git" and result.host_commit_sha is not None
    assert _commit_files(repo, result.host_commit_sha) == [rel]
    assert (repo / rel).is_file()
    assert git(repo, "ls-files", "--", rel).stdout.strip() == rel
    assert (repo.resolve(), True) in commits_under_pause
    assert _status(repo) == ""


def test_retiring_a_committed_hook_script_in_the_git_root_deletes_and_commits_it(tmp_path):
    """R1/M12: the script's removal goes through the skills root's git
    registration -- a commit that deletes it, never the plain project's
    "tracked by git" refusal."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid, _record_ = _project_hook_lesson(home, repo, "lrn-8b000014")
    routed = verbs.route(home, rid, dest="hook", no_push=True)
    assert routed.target is not None and routed.target.is_file()  # control
    rel = routed.target.relative_to(repo).as_posix()
    assert git(repo, "ls-files", "--", rel).stdout.strip() == rel  # control: tracked
    head = _head(repo)

    verbs.graduate(home, rid, no_push=True)

    assert _record(home, rid).status == "superseded"
    assert not routed.target.exists()
    assert _head(repo) != head
    assert _commit_files(repo, _head(repo)) == [rel]  # the deletion, committed
    assert git(repo, "ls-files", "--", rel).stdout.strip() == ""
    assert _status(repo) == ""


def test_a_skill_reference_route_and_reroute_go_through_the_git_root(tmp_path):
    """R1/M18: a skill lesson's shelf and its SKILL.md pointer are the
    skills root's files -- committed in git mode, and a reroute off the
    shelf commits the removal."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    rid = _skill_lesson(home, "lrn-8b000015")

    routed = verbs.route(home, rid, dest="reference", no_push=True)

    shelf = env.skill_dir / "references" / "LEARNINGS.md"
    assert routed.mode == "git" and routed.host_commit_sha is not None
    assert rid in shelf.read_text(encoding="utf-8")
    assert set(_commit_files(repo, routed.host_commit_sha)) == {
        shelf.relative_to(repo).as_posix(), env.skill_md.relative_to(repo).as_posix(),
    }
    assert _status(repo) == ""
    head = _head(repo)

    verbs.reroute(home, rid, dest="skill-md", no_push=True)

    assert _head(repo) != head  # committed in git mode
    assert not shelf.exists() or rid not in shelf.read_text(encoding="utf-8")
    assert rid in env.skill_md.read_text(encoding="utf-8")
    assert _record(home, rid).routing["destination"] == "skill-md"
    assert _status(repo) == ""


def test_a_new_skill_route_creates_and_commits_the_skill(tmp_path, commits_under_pause):
    """*control*: `new-skill` through the git root scaffolds the plugin,
    appends the marketplace entry and commits them, under the pause."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    marketplace = repo / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(
        json.dumps({"name": "sandbox", "plugins": [
            {"name": "s-plugin", "source": "./plugins/s-plugin", "description": "seed",
             "version": "1.0.0"},
        ]}, indent=2) + "\n",
        encoding="utf-8",
    )
    commit_all(repo, "marketplace seed")
    rid = _skill_lesson(home, "lrn-8b000010")

    result = verbs.route(home, rid, dest="new-skill:probe-skill", no_push=True)

    skill_md = repo / "plugins" / "probe-skill" / "skills" / "probe-skill" / "SKILL.md"
    assert result.mode == "git" and result.host_commit_sha is not None
    assert rid in skill_md.read_text(encoding="utf-8")
    files = _commit_files(repo, result.host_commit_sha)
    assert "plugins/probe-skill/skills/probe-skill/SKILL.md" in files
    assert ".claude-plugin/marketplace.json" in files
    names = [p["name"] for p in json.loads(marketplace.read_text(encoding="utf-8"))["plugins"]]
    assert names == ["s-plugin", "probe-skill"]
    assert (repo.resolve(), True) in commits_under_pause
    assert _status(repo) == ""


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


# ------------------------------------------------- --selftest's hosts row


def test_the_selftest_hosts_row_shows_a_repo_registered_twice_with_each_mode(
    tmp_path, monkeypatch, capsys
):
    """Red on master (no such row)."""
    env = _double(tmp_path)
    home, repo = env.ledger, env.host
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()

    cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert (
        f"selftest: PASS hosts — 2 registration(s); {repo.resolve()} is registered "
        "twice: skills-root=git, project=plain\n"
    ) in out

    (home / "hosts.yaml").write_text(_registry(repo, root="git", project=None), encoding="utf-8")
    assert selfcheck._check_hosts(home) == (
        selfcheck.Verdict.PASS, "1 registration(s); no repo is registered twice"
    )
    (home / "hosts.yaml").unlink()
    assert selfcheck._check_hosts(home)[0] is selfcheck.Verdict.UNMEASURED
    (home / "hosts.yaml").write_text("projects: 7\n", encoding="utf-8")
    verdict, msg = selfcheck._check_hosts(home)
    assert verdict is selfcheck.Verdict.FAIL and "hosts.yaml unreadable" in msg


def test_the_selftest_hosts_row_fails_on_a_stranded_lesson_and_its_printed_reroute_clears_it(
    tmp_path, monkeypatch, capsys
):
    """F1 (gate GM): the row names the lesson and a command, and the
    command WORKS -- a removal off the refused destination is never
    refused. Red on 6a27412: the reroute raised `destination-unavailable`
    (the refusal fired on the removal of the old placement too)."""
    env, rid = _lesson_left_on_the_root_claude_md(tmp_path)
    home, repo = env.ledger, env.host

    verdict, msg = selfcheck._check_hosts(home)
    assert verdict is selfcheck.Verdict.FAIL
    assert "skills-root=git, project=plain" in msg and rid in msg
    (command,) = re.findall(r"`(self-learn reroute [^`]*)`", msg)
    argv = shlex.split(command.replace("<id>", rid))[1:] + ["--no-push"]
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()

    assert cli.main(argv) == 0, capsys.readouterr().err

    assert rid not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert rid in env.skill_md.read_text(encoding="utf-8")
    assert _record(home, rid).routing["destination"] == "skill-md"
    assert _status(repo) == ""  # the git root committed both files
    verdict, msg = selfcheck._check_hosts(home)
    assert verdict is selfcheck.Verdict.PASS, msg


def test_a_stranded_lesson_can_be_graduated_off_the_refused_destination(tmp_path):
    """F1: retiring a lesson off the root's own claude-md is a removal,
    never refused. Red on 6a27412 (`destination-unavailable`)."""
    env, rid = _lesson_left_on_the_root_claude_md(tmp_path)
    home, repo = env.ledger, env.host
    head = _head(repo)

    verbs.graduate(home, rid, no_push=True)

    assert _record(home, rid).status == "superseded"
    assert rid not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert _head(repo) != head and _status(repo) == ""  # committed in git mode
    assert selfcheck._check_hosts(home)[0] is selfcheck.Verdict.PASS


def test_a_steward_sheet_retiring_a_stranded_lesson_applies(tmp_path):
    """F1: an agent's sheet line that only removes such a lesson is not
    refused `destination-unavailable` (preview and run). Red on 6a27412."""
    env, rid = _lesson_left_on_the_root_claude_md(tmp_path)
    home, repo = env.ledger, env.host
    sheet = _sheet(tmp_path, rid, "graduate")

    preview = batch.dry_run(home, sheet, actor="steward")
    result = batch.run(home, sheet, no_push=True, actor="steward")

    (pitem,), (item,) = preview.items, result.items
    assert pitem.state == "would-apply", (pitem.kind, pitem.detail)
    assert item.state == "applied", (item.kind, item.detail)
    assert rid not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert _status(repo) == ""


def test_the_hosts_row_passes_a_lesson_on_the_root_claude_md_when_the_modes_agree(tmp_path):
    """R1/M19: with one mode both ways the destination is not refused, so
    a lesson on it is not stranded."""
    env = _double(tmp_path, root="git", project="git")
    home, repo = env.ledger, env.host
    rid = _skill_lesson(home, "lrn-8b000013")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    assert rid in (repo / "CLAUDE.md").read_text(encoding="utf-8")  # control

    verdict, msg = selfcheck._check_hosts(home)

    assert verdict is selfcheck.Verdict.PASS, msg
    assert msg.endswith("skills-root=git, project=git")
