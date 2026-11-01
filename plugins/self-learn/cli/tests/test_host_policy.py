"""S-112 (decision 5, interventions L5): host modes follow the policy
the user typed, applied by code, and self-learn registers a project in plain
mode on its own.

- :func:`hosts.apply_policy`: a project registration of the skills root's
  path takes the skills root's mode (one repo, one mode); one ledger commit
  per change, ``By: policy``; nothing else changes; it runs from code even
  where ``host set-mode`` typed in an agent's shell is refused.
- ``serve`` applies it once a day, before the premise sweep.
- The overseer's optional phase B ``hosts.yaml`` registers plain projects
  (never git), refusing a path the checks name; each registration is listed
  under "Decided in the user's stead" with the command that undoes it.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import attribution, cli, execution_evidence, hosts, serve, settings, verbs
from self_learn.hosts import (
    MARKER_FILENAME,
    HostModeAgentRefusal,
    apply_policy,
    host_mode,
    host_set_mode,
    is_project_host,
    load_hosts,
    policy_changes,
    registration_problem,
)
from self_learn.overseer import run as overseer_run
from support import commit_all, git, init_repo, make_env
from test_double_registration import _double, _project_lesson
from test_failstate_overseer import _ok, _phase_a, _stage_two_successors, _successor, _two_parked
from test_overseer_run import _dump, _enabled


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    """A person's terminal by default; a test that models an agent's shell
    sets a marker itself."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _commits(repo: Path, since: str) -> list[str]:
    out = git(repo, "log", "--format=%H", f"{since}..HEAD").stdout.split()
    return out


def _message(repo: Path, rev: str = "HEAD") -> str:
    return git(repo, "log", "-1", "--format=%B", rev).stdout


def _diverged(tmp_path: Path):
    """`make_env`'s repo: the skills root in git mode, its project
    registration switched to plain by a person (claude-skills today)."""
    env = make_env(tmp_path)
    host_set_mode(env.ledger, env.host, "plain", registration="project")
    assert host_mode(env.ledger, env.host, registration="project") == "plain"  # control
    return env


# ------------------------------------------------------------- the policy


def test_the_skills_roots_project_registration_takes_the_skills_roots_mode(tmp_path):
    """Mutation: `policy_mode` answers None (no comparison made) -> nothing
    changes, the mode stays plain."""
    env = _diverged(tmp_path)
    home, repo = env.ledger, env.host
    before = _head(home)

    result = apply_policy(home)

    assert host_mode(home, repo, registration="project") == "git"
    assert host_mode(home, repo, registration="skills-root") == "git"
    assert [c.text() for c in result.changed] == [f"project {repo.resolve()} plain → git"]
    assert result.failed == []
    (sha,) = _commits(home, before)  # exactly one ledger commit
    message = _message(home, sha)
    assert message.splitlines()[0] == (
        f"self-learn: host set-mode project {repo.resolve()} plain → git (policy)"
    )
    assert "one repo, one mode" in message and "stmt-60e41e67" in message
    assert message.rstrip().endswith("By: policy")
    # idempotent: a registry that follows the policy writes nothing
    again = apply_policy(home)
    assert again.changed == [] and again.failed == [] and _head(home) == sha


def test_a_plain_project_that_is_not_the_skills_root_is_left_alone(tmp_path):
    """Mutation: drop the path comparison in `policy_mode` (every project
    takes the skills root's mode) -> the other project turns git."""
    env = _diverged(tmp_path)
    home = env.ledger
    other = tmp_path / "other"
    init_repo(other)
    hosts.host_add(home, other, "project", mode="plain")

    result = apply_policy(home)

    assert host_mode(home, env.host, registration="project") == "git"  # positive control: it ran
    assert host_mode(home, other, registration="project") == "plain"
    assert [c.path for c in result.changed] == [env.host.resolve()]


def test_the_policy_follows_a_plain_skills_root_too(tmp_path):
    """One repo, one mode, in the other direction: the project follows a
    plain skills root to plain (and gets its marker)."""
    env = _double(tmp_path, root="plain", project="git")
    home, repo = env.ledger, env.host
    (repo / MARKER_FILENAME).unlink()

    apply_policy(home)

    assert host_mode(home, repo, registration="project") == "plain"
    assert (repo / MARKER_FILENAME).is_file()


def test_the_policy_runs_from_code_where_an_agents_set_mode_is_refused(tmp_path, monkeypatch, capsys):
    """Mutation: `apply_policy` calls the checked `host_set_mode` -> it is
    refused in this shell and the mode stays plain (named in `failed`)."""
    env = _diverged(tmp_path)
    home, repo = env.ledger, env.host
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("CLAUDECODE", "1")
    assert settings.agent_caller()  # an agent's shell
    head = _head(home)
    # positive control first: the person's command is refused here
    assert cli.main(["host", "set-mode", str(repo), "git", "--project", "--note", "why"]) == 1
    with pytest.raises(HostModeAgentRefusal):
        host_set_mode(home, repo, "git", registration="project")
    assert _head(home) == head and host_mode(home, repo, registration="project") == "plain"
    capsys.readouterr()

    result = apply_policy(home)

    assert result.failed == [], result.failed
    assert host_mode(home, repo, registration="project") == "git"
    message = _message(home)
    assert message.rstrip().endswith("By: policy") and "By: agent" not in message


def test_the_policy_recompiles_the_switched_registrations_lessons(tmp_path):
    """The switch is followed by a recompile of the records routed into the
    registration (the drift row's repair, done by code). Mutation: skip the
    recompile -> the lesson's line stays missing from the host's CLAUDE.md."""
    env = _double(tmp_path, root="git", project="git")
    home, repo = env.ledger, env.host
    rid = _project_lesson(home, repo, "lrn-8c000001")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    claude_md = repo / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    assert rid in text  # control: routed and committed in git mode
    host_set_mode(home, repo, "plain", registration="project")
    # the line went missing while the registration was plain (drift)
    claude_md.write_text(
        "\n".join(line for line in text.splitlines() if rid not in line) + "\n", encoding="utf-8"
    )
    commit_all(repo, "a hand edit dropped the lesson's line")
    assert rid not in claude_md.read_text(encoding="utf-8")

    result = apply_policy(home)

    assert result.failed == [], result.failed
    assert result.recompiled[str(repo.resolve())] == (rid,)
    assert rid in claude_md.read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain").stdout == ""  # committed in git mode


def test_the_policys_commits_are_not_hand_steps(tmp_path):
    """Gate r1 MINOR 1. Mutation: `report._JOB_ACTORS` without `policy`
    (the old fixed set) -> the policy's set-mode and recompile commits are
    counted as hand steps."""
    from self_learn import report

    env = _double(tmp_path, root="git", project="git")
    home = env.ledger
    rid = _project_lesson(home, env.host, "lrn-8c000002")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    host_set_mode(home, env.host, "plain", registration="project")  # a person's step
    claude_md = env.host / "CLAUDE.md"
    claude_md.write_text(
        "\n".join(line for line in claude_md.read_text(encoding="utf-8").splitlines() if rid not in line) + "\n",
        encoding="utf-8",
    )
    commit_all(env.host, "a hand edit dropped the lesson's line")  # so the recompile has work
    before = _head(home)
    result = apply_policy(home)
    assert result.changed and result.recompiled[str(env.host.resolve())] == (rid,)
    policy_commits = _commits(home, before)
    assert policy_commits  # the switch (and any recompile commit)
    for sha in policy_commits:
        assert _message(home, sha).rstrip().endswith("By: policy")

    census = report.hand_steps(home)
    subjects = [step["subject"] for step in census["steps"]]
    # positive control: the person's own set-mode commits are hand steps
    assert any(s.endswith("git → plain") for s in subjects), subjects
    assert not any("(policy)" in s for s in subjects), subjects
    short = {sha[:7] for sha in policy_commits}
    assert not any(step["commit"][:7] in short for step in census["steps"])


def test_the_overseers_report_lists_the_policys_switches_with_their_undo(tmp_path):
    """Gate r1 MINOR 1: the policy's switch is decided in the user's
    stead, so the weekly report lists it with its undo. Mutation: drop the
    subject match from `policy_commits` -> no line; drop its `By: policy`
    reading -> the hand-made `(policy)` commit below is listed too (gate r2
    NIT 2)."""
    env = _diverged(tmp_path)
    home = env.ledger
    assert overseer_run._policy_lines(home, None) == ([], [])  # control: nothing yet
    apply_policy(home)
    lines, notes = overseer_run._policy_lines(home, None)
    real = env.host.resolve()
    assert notes == []
    (line,) = lines
    assert line.startswith(f"[host mode set by the policy] project {real} plain → git (one repo, one mode")
    assert f"undo: `self-learn host remove {real} --project`" in line
    assert f"`self-learn host set-mode {real} plain --skills-root`" in line
    # gate r2 NIT 1: the first undo says what it needs once lessons are routed there
    assert "`self-learn rehome <id> --to <target>`" in line and "`--gate-only`" in line
    # only since the last run
    assert overseer_run._policy_lines(home, "2999-01-01T00:00:00Z") == ([], [])
    # a person's own set-mode is never listed as the policy's
    host_set_mode(home, env.host, "plain", registration="project")
    assert len(overseer_run._policy_lines(home, None)[0]) == 1
    # nor is a commit whose subject reads like the policy's but which does
    # not carry `By: policy` (a hand edit of hosts.yaml committed by a person)
    hosts_yaml = home / "hosts.yaml"
    hosts_yaml.write_text(hosts_yaml.read_text(encoding="utf-8") + "# a hand edit\n", encoding="utf-8")
    git(home, "add", "hosts.yaml")
    git(home, "commit", "-q", "-m",
        f"self-learn: host set-mode project {real} git → plain (policy)\n\nBy: human")
    assert _message(home).splitlines()[0].endswith("(policy)")  # control: the subject matches
    assert len(overseer_run._policy_lines(home, None)[0]) == 1


def test_an_info_exclude_failure_is_a_failed_line(tmp_path):
    """Gate r1 MINOR 2: the switch to git stands when self-learn's
    info/exclude block cannot be edited, and `failed` says so. Mutation:
    drop the `unexclude_error` branch in `apply_policy` -> `failed` empty."""
    from self_learn import gitops

    env = _diverged(tmp_path)
    exclude = env.host / ".git" / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8")
    assert gitops.EXCLUDE_END in text  # control: the plain registration wrote the block
    exclude.write_text(text + gitops.EXCLUDE_END + "\n", encoding="utf-8")  # two ends: malformed

    result = apply_policy(env.ledger)

    assert host_mode(env.ledger, env.host, registration="project") == "git"  # the switch stands
    (line,) = result.failed
    assert line.startswith(f"project {env.host.resolve()} plain → git: changed, but self-learn's info/exclude")
    assert "malformed" in line


def test_policy_changes_names_only_a_registration_the_policy_would_change(tmp_path):
    env = _diverged(tmp_path)
    (change,) = policy_changes(load_hosts(env.ledger))
    assert (change.kind, change.old_mode, change.new_mode) == ("project", "plain", "git")
    apply_policy(env.ledger)
    assert policy_changes(load_hosts(env.ledger)) == []


def test_the_doctor_names_the_change_the_policy_owes(tmp_path):
    """Mutation: drop the policy clause from `_check_hosts` -> not named."""
    from self_learn import selfcheck

    env = _diverged(tmp_path)
    _verdict, msg = selfcheck._check_hosts(env.ledger)
    assert "skills-root=git, project=plain" in msg  # control: the row is the double one
    assert f"sets project {env.host.resolve()} plain → git" in msg
    apply_policy(env.ledger)
    verdict, msg = selfcheck._check_hosts(env.ledger)
    assert verdict is selfcheck.Verdict.PASS and "host policy" not in msg


# ------------------------------------------------------------- serve


def test_serve_applies_the_policy_once_a_day_before_the_premise_sweep(tmp_path, monkeypatch):
    """Mutation: drop the hosts step from `_run_tick` -> the mode stays
    plain after a tick."""
    env = _diverged(tmp_path)
    home, repo = env.ledger, env.host
    cache = tmp_path / "serve-cache"
    order: list[str] = []
    real_policy = hosts.apply_policy

    def policy(h):
        order.append("hosts")
        return real_policy(h)

    monkeypatch.setattr(serve.hosts_mod, "apply_policy", policy)
    monkeypatch.setattr(serve, "_premises_is_due", lambda *a: True)
    monkeypatch.setattr(serve, "_run_premises_job", lambda *a: order.append("premises"))
    for name in ("_mine_is_due", "_steward_is_due", "_overseer_is_due"):
        monkeypatch.setattr(serve, name, lambda *a, **k: False)
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc).timestamp()

    ran = serve._run_tick(home, cache, now=now, pid=os.getpid(), tick_secs=60.0)

    assert [r.name for r in ran][:2] == ["hosts", "premises"] and order == ["hosts", "premises"]
    assert all(r.ok for r in ran), [r.error for r in ran]
    assert host_mode(home, repo, registration="project") == "git"
    assert _message(home).rstrip().endswith("By: policy")
    marker = json.loads((cache / serve.HOSTS_POLICY_FILENAME).read_text(encoding="utf-8"))
    assert marker["attempted_at"].startswith("2026-11-01T12:00")
    # owed again (a person switched it back): not again the same day; a day later
    host_set_mode(home, repo, "plain", registration="project")
    serve._run_tick(home, cache, now=now + 3600, pid=os.getpid(), tick_secs=60.0)
    assert order.count("hosts") == 1
    serve._run_tick(home, cache, now=now + 24 * 3600, pid=os.getpid(), tick_secs=60.0)
    assert order.count("hosts") == 2


def test_the_policy_is_due_only_with_a_change_owed_and_at_most_daily(tmp_path):
    """Mutation: drop the `policy_changes` check from the due check -> due
    with nothing owed (a job every day for nothing)."""
    env = _diverged(tmp_path)
    home = env.ledger
    cache = tmp_path / "c"
    cache.mkdir()
    now = 1_800_000_000.0
    assert serve._hosts_policy_is_due(home, cache, now)  # owed, no marker
    path = cache / serve.HOSTS_POLICY_FILENAME
    path.write_text(json.dumps({"attempted_at": "2027-01-15T08:00:00Z"}), encoding="utf-8")
    stamp = datetime(2027, 1, 15, 8, 0, tzinfo=timezone.utc).timestamp()
    assert not serve._hosts_policy_is_due(home, cache, stamp + 60)
    assert serve._hosts_policy_is_due(home, cache, stamp + 24 * 3600)
    assert serve._hosts_policy_is_due(home, cache, stamp - 60)  # future-dated: due
    path.write_text("{not json", encoding="utf-8")
    assert serve._hosts_policy_is_due(home, cache, now)  # unreadable: due, rewritten
    path.unlink()
    apply_policy(home)
    assert not serve._hosts_policy_is_due(home, cache, now)  # nothing owed: no job
    (home / "hosts.yaml").write_text("projects: 7\n", encoding="utf-8")
    assert not serve._hosts_policy_is_due(home, cache, now)  # unreadable registry: not due


# ------------------------------------------- self-learn's own registration


@pytest.fixture
def inside_home(tmp_path, monkeypatch):
    """The user's home directory is *tmp_path* for these tests."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_registration_problem_names_each_refusal(tmp_path, inside_home):
    """Mutations: drop each check in `registration_problem` -> the matching
    row is answered None."""
    env = make_env(tmp_path)
    ok = tmp_path / "repos" / "proj"
    ok.mkdir(parents=True)
    in_ledger = env.ledger / "projects"
    in_cache = Path(os.environ["XDG_CACHE_HOME"]) / "self-learn" / "x"
    in_cache.mkdir(parents=True)
    outside = Path("/")

    assert registration_problem(env.ledger, str(ok)) is None  # positive control
    assert "not an absolute path" in registration_problem(env.ledger, "repos/proj")
    assert "not an existing directory" in registration_problem(env.ledger, str(tmp_path / "gone"))
    assert "inside the user's home" in registration_problem(env.ledger, str(outside))
    assert "inside the user's home" in registration_problem(env.ledger, str(tmp_path))
    assert "the ledger" in registration_problem(env.ledger, str(in_ledger))
    assert "the ledger" in registration_problem(env.ledger, str(env.ledger))
    assert "cache" in registration_problem(env.ledger, str(in_cache))
    assert "already registered (the skills root)" in registration_problem(env.ledger, str(env.host))
    hosts.host_add(env.ledger, ok, "project", mode="plain")
    assert "already registered (a plain project)" in registration_problem(env.ledger, str(ok))


def test_the_directory_above_the_ledger_or_the_cache_is_refused_by_that_clause(tmp_path, monkeypatch):
    """Gate r1 MINOR 2: with the user's home one level ABOVE *tmp_path*,
    the ledger and the cache sit two levels below it, so the directory
    above each is inside the home and is refused only by its own clause.
    Mutations: drop the ledger clause -> *tmp_path* is answered by the cache
    clause instead (no "the ledger"); drop the cache clause -> the cache's
    parent is answered None."""
    monkeypatch.setenv("HOME", str(tmp_path.parent))
    env = make_env(tmp_path)
    cache_parent = Path(os.environ["XDG_CACHE_HOME"])  # <tmp>/xdg-cache, above <tmp>/xdg-cache/self-learn
    cache_parent.mkdir(parents=True, exist_ok=True)
    elsewhere = tmp_path / "repos" / "proj"
    elsewhere.mkdir(parents=True)
    assert registration_problem(env.ledger, str(elsewhere)) is None  # positive control

    above_ledger = registration_problem(env.ledger, str(env.ledger.parent))
    assert above_ledger is not None and "the ledger, inside it or above it" in above_ledger
    above_cache = registration_problem(env.ledger, str(cache_parent))
    assert above_cache is not None and "self-learn's cache, inside it or above it" in above_cache


def test_a_registration_from_an_agents_shell_is_the_overseers_act(tmp_path, inside_home, monkeypatch):
    """`register_plain_project` is self-learn's own act: it runs whatever
    shell started the run, and the commit says `By: overseer`. Mutation:
    call the checked `host_add` -> refused here."""
    env = make_env(tmp_path)
    proj = tmp_path / "repos" / "proj"
    init_repo(proj)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(HostModeAgentRefusal):
        hosts.host_add(env.ledger, proj, "project", mode="plain")  # control
    with attribution.job("overseer"):
        hosts.register_plain_project(env.ledger, str(proj), note="why")
    assert host_mode(env.ledger, proj, registration="project") == "plain"
    assert (proj / MARKER_FILENAME).is_file()
    assert _message(env.ledger).rstrip().endswith("By: overseer")


def _why(n: int) -> str:
    """A one-line why of exactly *n* characters that reads as words (a run of
    one letter would itself match the secret scan's long-token rule)."""
    text = ("ab " * n)[:n]
    return text[:-1] + "z"


#: A GitHub-token shape the secret scan matches, built at run time so no
#: credential-shaped literal sits in the tracked tree.
_TOKEN_SHAPE = "gh" + "p_" + "A1b2C3d4" * 5


def test_the_runner_keeps_at_most_the_per_run_limit_of_registrations(tmp_path):
    """Gate r1 MINOR 2. Mutation: drop the per-run limit check -> the sixth
    valid entry is kept."""
    limit = hosts.MAX_REGISTRATIONS_PER_RUN
    entries = [
        {"path": f"/srv/p{i}", "case": "case-0000000b", "why": "w"} for i in range(limit + 1)
    ]
    kept, dropped = overseer_run._validate_registrations(
        {"registrations": entries}, {"case-0000000b"},
    )
    assert [row["path"] for row in kept] == [f"/srv/p{i}" for i in range(limit)]
    assert dropped == [
        f"host registration {limit + 1}: dropped — more than {limit} registrations in one run"
    ]


def test_the_runner_refuses_git_mode_and_the_ledger_before_anything_is_written(tmp_path):
    """Mutation: accept `mode: git` in `_validate_registrations` -> kept."""
    kept, dropped = overseer_run._validate_registrations(
        {"registrations": [
            {"path": "/srv/a", "case": "case-0000000b", "why": "w", "mode": "git"},
            {"path": "/srv/b", "case": "case-0000000b", "why": "w", "mode": "plain"},
            {"path": "rel/c", "case": "case-0000000b", "why": "w"},
            {"path": "/srv/d", "case": "case-0000000c", "why": "w"},
            {"path": "/srv/e", "case": "case-0000000b", "why": ""},
            {"path": "/srv/b", "case": "case-0000000b", "why": "w"},
            {"path": "/srv/f", "case": "case-0000000b", "why": _why(overseer_run.REGISTRATION_WHY_MAX + 1)},
            {"path": "/srv/g", "case": "case-0000000b", "why": f"the key is {_TOKEN_SHAPE}"},
        ]},
        {"case-0000000b"},
    )
    assert kept == [{"path": "/srv/b", "case": "case-0000000b", "why": "w"}]
    assert dropped == [
        "host registration 1: dropped — only plain mode: registering a repository "
        "in git mode stays the user's",
        "host registration 3: dropped — path must be absolute",
        "host registration 4: dropped — case is not a case in the ledger",
        "host registration 5: dropped — a registration needs a why",
        "host registration 6: dropped — the same path twice",
        f"host registration 7: dropped — why is longer than {overseer_run.REGISTRATION_WHY_MAX} characters",
        "host registration 8: dropped — the secret scan matched it",
    ]
    # a why exactly at the limit is kept (the boundary of the row above)
    at_limit, none_dropped = overseer_run._validate_registrations(
        {"registrations": [{"path": "/srv/h", "case": "case-0000000b",
                            "why": _why(overseer_run.REGISTRATION_WHY_MAX)}]},
        {"case-0000000b"},
    )
    assert len(at_limit) == 1 and none_dropped == []
    _kept, whole = overseer_run._validate_registrations({"hosts": []}, set())
    assert whole == ["hosts.yaml: dropped — expected only a registrations list"]


def _registration_run(tmp_path, monkeypatch, entries, *, dry_run=False, project=None, before=None):
    """One overseer run whose fake phase B writes hosts.yaml from
    ``entries(env, parked_case_id)``; the user's home is *tmp_path*. A
    *project* gets a lesson first, so the ledger knows it (a bucket) and
    projects.yaml lists it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    env = make_env(tmp_path)
    home = env.ledger
    if project is not None:
        _project_lesson(home, project, "lrn-8c0000aa")
    if before is not None:
        before(env)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    seen: dict[str, str] = {}

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-s":
            return _ok()
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _stage_two_successors(
                stage, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
            )
            seen["projects"] = (stage / "projects.yaml").read_text(encoding="utf-8")
            _dump(stage / "hosts.yaml", {"registrations": entries(env, parked_a)})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, dry_run=dry_run, no_push=True)
    return env, home, result, seen


def test_a_run_registers_a_plain_project_and_lists_it_with_its_undo(tmp_path, monkeypatch):
    """Mutations: drop the `_register_hosts` call -> nothing registered;
    drop the ledger check in `registration_problem` -> the ledger path is
    registered too (or refused by `host add` with another reason)."""
    proj = tmp_path / "repos" / "proj"
    init_repo(proj)
    (tmp_path / "repos" / "plaindir").mkdir()

    def entries(env, parked):
        return [
            {"path": str(proj), "case": parked, "why": "Its build lessons have nowhere to go."},
            {"path": str(env.ledger / "projects"), "case": parked, "why": "A wrong path."},
            {"path": str(tmp_path / "repos" / "plaindir"), "case": parked, "why": "No git at all.",
             "mode": "git"},
        ]

    env, home, result, seen = _registration_run(tmp_path, monkeypatch, entries, project=proj)

    assert result.status == "applied", result  # a refused registration never costs the run
    # phase B is told which known projects are unregistered
    from ruamel.yaml import YAML

    listed = {
        row["path"]: row["registered"]
        for row in YAML(typ="safe").load(seen["projects"])["projects"]
    }
    assert listed[os.path.realpath(proj)] == "no"
    assert listed[os.path.realpath(env.host)] == "git"  # control: the registered one says so
    real = os.path.realpath(proj)
    assert is_project_host(load_hosts(home), proj)
    assert host_mode(home, proj, registration="project") == "plain"
    assert (proj / MARKER_FILENAME).is_file()
    assert git(proj, "status", "--porcelain").stdout == ""  # nothing to commit there
    log = git(home, "log", "--format=%s%x00%B%x01").stdout
    (entry,) = [e for e in log.split("\x01") if f"self-learn: host add project {real}\x00" in e]
    assert entry.rstrip().endswith("By: overseer") and f"Overseer run {result.run}" in entry
    assert f"Undo: self-learn host remove {real} --project" in entry
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    decided = report.split("## Decided in the user's stead", 1)[1].split("\n## ", 1)[0]
    assert f"[host registered] {real} as a plain project" in decided
    assert f"undo: `self-learn host remove {real} --project`" in decided
    refused = report.split("## Refused / could not do", 1)[1]
    ledger_path = os.path.realpath(env.ledger / "projects")
    assert f"host registration 2 ({ledger_path}): refused — " in refused
    assert "the ledger, inside it or above it" in refused
    assert "host registration 3: dropped — only plain mode" in refused
    assert not is_project_host(load_hosts(home), env.ledger / "projects")
    manifest = execution_evidence.read_manifest(home, result.run, at="HEAD")
    assert [row.get("result") for row in manifest["registrations"]] == ["registered", "refused"]


def test_a_run_lists_the_policys_switch_in_the_users_stead(tmp_path, monkeypatch):
    """Gate r1 MINOR 1, end to end. Mutation: drop the record's
    `policy_lines` from the report's decided lines -> not listed."""

    def switch(env):
        host_set_mode(env.ledger, env.host, "plain", registration="project")
        apply_policy(env.ledger)

    env, home, result, _seen = _registration_run(
        tmp_path, monkeypatch, lambda env, parked: [], before=switch,
    )
    assert result.status == "applied", result
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    decided = report.split("## Decided in the user's stead", 1)[1].split("\n## ", 1)[0]
    assert f"[host mode set by the policy] project {env.host.resolve()} plain → git" in decided
    manifest = execution_evidence.read_manifest(home, result.run, at="HEAD")
    assert len(manifest["policy_lines"]) == 1


def test_a_resumed_run_reads_its_own_registration_as_registered(tmp_path, inside_home):
    """A resume after the registration committed and before the record did
    finds the path registered: its own commit says it made it. Control: a
    path registered by someone else is refused as already registered."""
    env = make_env(tmp_path)
    home = env.ledger
    proj = tmp_path / "proj"
    init_repo(proj)
    other = tmp_path / "other"
    init_repo(other)
    run_id = "run-0000000000ab"
    row = {"path": str(proj), "case": "case-0000000b", "why": "w"}
    with attribution.job("overseer"):
        hosts._host_add(home, os.path.realpath(proj), "project", mode="plain",
                        note=overseer_run._registration_note(run_id, row, os.path.realpath(proj)))
    hosts.host_add(home, other, "project", mode="plain")
    manifest = {"run_id": run_id, "registrations": [
        dict(row), {"path": str(other), "case": "case-0000000b", "why": "w"},
    ]}
    notes: list[str] = []

    lines = overseer_run._register_hosts(home, manifest, notes)

    assert lines == [overseer_run._host_line(row)]
    assert [r["result"] for r in manifest["registrations"]] == ["registered", "refused"]
    assert len(notes) == 1 and "already registered (a plain project)" in notes[0]


def test_a_host_a_person_removed_is_never_registered_again(tmp_path, inside_home):
    """Gate r1 MAJOR 1: the printed undo (`host remove … --project`) stands.
    The overseer registers a project, the person removes it, and the same
    entry in a later run is refused with the reason; projects.yaml reads
    `removed`. Positive control: a path never removed still registers in the
    same pass. Mutation: drop the removal check in `registration_problem`
    -> the removed path is registered again."""
    env = make_env(tmp_path)
    home = env.ledger
    proj = tmp_path / "repos" / "proj"
    init_repo(proj)
    fresh = tmp_path / "repos" / "fresh"
    init_repo(fresh)
    real = os.path.realpath(proj)
    first = {"run_id": "run-00000000000a", "registrations": [
        {"path": str(proj), "case": "case-0000000b", "why": "w"},
    ]}
    with attribution.job("overseer"):
        assert overseer_run._register_hosts(home, first, []) == [
            overseer_run._host_line(first["registrations"][0])
        ]
    assert is_project_host(load_hosts(home), proj)
    labels = overseer_run._registered_labels(home, [real])
    assert labels == {real: "plain"}  # control: registered reads its mode
    # the person's undo, exactly as the report prints it
    assert "--project" in overseer_run._host_line(first["registrations"][0])
    hosts.host_remove(home, proj, registration="project")
    assert not is_project_host(load_hosts(home), proj)
    assert overseer_run._registered_labels(home, [real, os.path.realpath(fresh)]) == {
        real: "removed", os.path.realpath(fresh): "no",
    }

    later = {"run_id": "run-00000000000b", "registrations": [
        {"path": str(proj), "case": "case-0000000b", "why": "w"},
        {"path": str(fresh), "case": "case-0000000b", "why": "w"},
    ]}
    notes: list[str] = []
    with attribution.job("overseer"):
        lines = overseer_run._register_hosts(home, later, notes)

    assert not is_project_host(load_hosts(home), proj)
    assert [r["result"] for r in later["registrations"]] == ["refused", "registered"]
    assert is_project_host(load_hosts(home), fresh)  # positive control
    assert lines == [overseer_run._host_line(later["registrations"][1])]
    (note,) = notes
    assert note.startswith(f"host registration 1 ({real}): refused — ")
    assert "taken out of the registry (ledger commit " in note
    assert "never registers it again" in note

    # Gate r2 MINOR 1: the verb's default, bare form `host remove <path>`
    # (no registration word in the subject; most live removals) stands too.
    # Mutation: make the registration word required in `_REMOVE_SUBJECT_RE`
    # -> the bare removal is not read, `fresh` reads `no` and is registered
    # again.
    fresh_real = os.path.realpath(fresh)
    hosts.host_remove(home, fresh)
    assert not is_project_host(load_hosts(home), fresh)
    assert git(home, "log", "-1", "--format=%s").stdout.strip() == (
        f"self-learn: host remove {fresh_real}"
    )  # control: the bare subject form is what this exercises
    assert overseer_run._registered_labels(home, [fresh_real]) == {fresh_real: "removed"}
    third = {"run_id": "run-00000000000c", "registrations": [
        {"path": str(fresh), "case": "case-0000000b", "why": "w"},
    ]}
    notes = []
    with attribution.job("overseer"):
        assert overseer_run._register_hosts(home, third, notes) == []
    assert [r["result"] for r in third["registrations"]] == ["refused"]
    assert not is_project_host(load_hosts(home), fresh)
    (note,) = notes
    assert "taken out of the registry (ledger commit " in note


def test_an_unreadable_ledger_history_refuses_and_reads_unknown(tmp_path, inside_home, monkeypatch):
    """Gate r2 MINOR 2: the fail-closed half of the removal rule. When git
    cannot read the ledger's history of hosts.yaml, `registration_problem`
    refuses (never reads it as "nothing was removed") and projects.yaml's
    `registered` reads `unknown` for an unregistered path, while a
    registered one still reads its mode (positive control). Mutations: the
    except branch in `registration_problem` sets `removed = {}` -> None;
    the except branch in `_registered_labels` sets `removed = {}` -> `no`."""
    from self_learn import gitops

    env = make_env(tmp_path)
    home = env.ledger
    proj = tmp_path / "repos" / "proj"
    init_repo(proj)
    real = os.path.realpath(proj)
    registered = os.path.realpath(env.host)
    assert registration_problem(home, str(proj)) is None  # control: readable history
    assert overseer_run._registered_labels(home, [real]) == {real: "no"}

    real_git = gitops._git  # noqa: SLF001

    def failing_log(repo, *args, **kwargs):
        if args and args[0] == "log" and "hosts.yaml" in args:
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: simulated unreadable history")
        return real_git(repo, *args, **kwargs)

    monkeypatch.setattr(gitops, "_git", failing_log)

    problem = registration_problem(home, str(proj))
    assert problem is not None
    assert "the ledger's record of removed hosts could not be read" in problem
    assert "simulated unreadable history" in problem
    labels = overseer_run._registered_labels(home, [real, registered])
    assert labels == {real: "unknown", registered: "git"}


def test_the_undo_line_says_what_to_do_once_lessons_are_routed_there(tmp_path):
    """Gate r1 MAJOR 1, second half: `host remove` refuses while routed
    records compile into the host, so the printed undo names the repair."""
    line = overseer_run._host_line({"path": str(tmp_path), "case": "case-0000000b", "why": "w"})
    assert f"`self-learn host remove {os.path.realpath(tmp_path)} --project`" in line
    assert "`self-learn rehome <id> --to <target>`" in line and "`--gate-only`" in line
    note = overseer_run._registration_note("run-x", {"case": "case-0000000b", "why": "w"}, "/p")
    assert "Undo: self-learn host remove /p --project (once lessons are routed there" in note


def test_a_dry_run_registers_nothing(tmp_path, monkeypatch):
    """A dry run commits nothing (the applied run above is the positive
    control: the same hosts.yaml registers)."""
    proj = tmp_path / "repos" / "proj"
    init_repo(proj)

    def entries(env, parked):
        return [{"path": str(proj), "case": parked, "why": "Its build lessons have nowhere to go."}]

    _env, home, result, seen = _registration_run(tmp_path, monkeypatch, entries, dry_run=True)
    assert result.status == "dry-run" and "projects" in seen
    assert not is_project_host(load_hosts(home), proj)
    assert not (proj / MARKER_FILENAME).exists()


def test_phase_b_is_told_about_hosts_yaml_and_it_is_withheld_on_a_secret(tmp_path):
    from ruamel.yaml import YAML

    from self_learn.overseer import formats

    flat = " ".join(overseer_run._phase_b_prompt(tmp_path, (), ()).split())
    assert "hosts.yaml is optional" in flat and "never registers git mode" in flat
    assert overseer_run._WITHHELD_ON_SECRET["hosts.yaml"] == "registrations: []\n"
    assert "hosts.yaml" not in overseer_run.REQUIRED_OUTPUT_FILES
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root = formats.write(workspace, "B")
    assert (root / "hosts.yaml").is_file()
    assert "hosts.yaml (optional)" in (root / "README.md").read_text(encoding="utf-8")
    data = YAML(typ="safe").load(formats.phase_b_examples()["hosts.yaml"])
    kept, dropped = overseer_run._validate_registrations(data, {formats.EXAMPLE_CASE})
    assert dropped == [] and len(kept) == 1  # the example passes the runner's own check
