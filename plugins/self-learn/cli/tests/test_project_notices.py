"""Project notices (hand-maintenance cures, lane D: M7 and M6 part 3;
decision row S-106).

The user, 2026-10-30: "i reviewed checkpoint 90. i agree with the decisions."
-- which settled design question Q3: one-line project notices at session
start, only in sessions inside the project they name, each ending when done,
when its condition clears, or after 14 days.

Written, not run: the user's 2026-10-30 rule is that tests run once, over the
combined landing. Each test says what it would catch.

Every scenario runs on pytest sandbox ledgers and repos; ids and texts are
synthetic. Absence assertions (nothing shown, nothing written) each have a
positive control asserting the same call does show or write in the neighbouring
case.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cli, execution_evidence, notices, verbs
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from support import commit_all, git, make_env, make_home
from test_failstate_overseer import (
    _ok,
    _phase_a,
    _stage_two_successors,
    _successor,
    _two_parked,
)
from test_overseer_run import _dump, _enabled
from test_pending_hook import NOTICE_HEADER, _base_payload, _run_hook
from test_tracked_target_guard import _head, _lesson, _plain_repo_host, _record


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


T0 = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
WORDS = "The shutdown watchdog predates the daemon it guards; nothing is wrong, but do not rely on it."


def _project(tmp_path: Path, name: str = "proj") -> Path:
    path = tmp_path / name
    (path / "src" / "deep").mkdir(parents=True)
    return path


def _add(home: Path, project: Path, text: str = WORDS, *, now: datetime = T0, **kw):
    return notices.add(
        home, project=project, text=text, source=notices.SOURCE_OVERSEER, now=now, **kw
    )


# --------------------------------------------------------- the store itself


def test_a_notice_is_one_cache_file_and_never_a_ledger_file(tmp_path):
    """The notice lives under the cache, one file per notice; the ledger home
    is not touched (here it does not even exist, so a write there would fail
    the control)."""
    home = tmp_path / "ledger-never-made"
    note = _add(home, _project(tmp_path))
    assert note is not None
    path = notices.notices_dir(home) / f"{note.id}.json"
    assert path.is_file()  # control: the write happened
    assert not home.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["text"] == WORDS and stored["source"] == "overseer" and stored["done_at"] is None
    assert note.id.startswith("ntc-") and len(note.id) == len("ntc-") + 8


def test_a_notice_shows_only_in_a_session_inside_its_project(tmp_path):
    """Containment is by path, not by name prefix: `proj2` shares `proj`'s
    prefix and must not see its notice; a subdirectory and a symlink to the
    project do."""
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    sibling = _project(tmp_path, "proj2")
    link = tmp_path / "link-to-proj"
    link.symlink_to(proj)
    note = _add(home, proj)
    assert note is not None

    for cwd in (proj, proj / "src", proj / "src" / "deep", link):
        assert [n.id for n in notices.visible(home, cwd, now=T0)] == [note.id], cwd
    for cwd in (sibling, tmp_path, proj.parent, Path("/")):
        assert notices.visible(home, cwd, now=T0) == [], cwd


def test_a_notice_ends_fourteen_days_after_it_was_made(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    _add(home, proj)
    assert len(notices.visible(home, proj, now=T0 + timedelta(days=13, hours=23))) == 1
    assert notices.visible(home, proj, now=T0 + timedelta(days=14)) == []
    assert notices.NOTICE_DAYS == 14


def test_the_same_words_are_one_notice_and_the_fourteen_days_do_not_restart(tmp_path):
    """The next weekly run writes the same finding again: it must not extend
    the first notice's life."""
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    first = _add(home, proj, now=T0)
    again = _add(home, proj, now=T0 + timedelta(days=10))
    assert first is not None and again is not None
    assert again.id == first.id and again.created_at == first.created_at
    assert len(notices.all_notices(home)) == 1
    assert notices.visible(home, proj, now=T0 + timedelta(days=14)) == []


def test_done_ends_a_notice_and_the_same_finding_does_not_bring_it_back(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    note = _add(home, proj)
    assert note is not None
    assert len(notices.visible(home, proj, now=T0)) == 1  # control

    done = notices.mark_done(home, note.id, now=T0)
    assert done is not None and done.done_at is not None
    assert notices.visible(home, proj, now=T0) == []
    again = _add(home, proj, now=T0 + timedelta(days=1))
    assert again is not None and again.done_at is not None  # still done
    assert notices.visible(home, proj, now=T0 + timedelta(days=1)) == []
    assert notices.mark_done(home, "ntc-00000000") is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "two\nlines",
        "tab\tin it",
        " leading space",
        "x" * (notices.MAX_TEXT + 1),
        "a leaked " + "ghp_" + "A1b2C3d4" * 5,
    ],
)
def test_words_that_are_not_one_clean_line_make_no_notice(tmp_path, text):
    """One line, printable, at most 200 characters, secret-scanned: a notice
    is printed into a session's context."""
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    assert _add(home, proj, "A fine one-line notice for the control.") is not None  # control
    before = len(notices.all_notices(home))
    assert _add(home, proj, text) is None
    assert len(notices.all_notices(home)) == before


def test_a_notice_file_that_was_hand_edited_into_two_lines_is_not_shown(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    note = _add(home, proj)
    assert note is not None
    assert len(notices.visible(home, proj, now=T0)) == 1  # control
    path = notices.notices_dir(home) / f"{note.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["text"] = "first line\nsecond line"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert notices.visible(home, proj, now=T0) == []


def test_a_junk_file_and_a_bad_working_directory_never_raise(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    _add(home, proj)
    (notices.notices_dir(home) / "ntc-deadbeef.json").write_text("not json", encoding="utf-8")
    (notices.notices_dir(home) / "stray.txt").write_text("x", encoding="utf-8")
    assert len(notices.visible(home, proj, now=T0)) == 1  # the junk costs nothing
    assert notices.visible(home, tmp_path / "does" / "not" / "exist", now=T0) == []


def test_a_notice_is_deleted_thirty_days_after_it_was_made(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    old = _add(home, proj, "An old notice for the control.", now=T0 - timedelta(days=31))
    assert old is not None and (notices.notices_dir(home) / f"{old.id}.json").is_file()
    new = _add(home, proj, "A new notice that triggers the sweep.", now=T0)  # add prunes
    assert new is not None
    assert not (notices.notices_dir(home) / f"{old.id}.json").exists()
    assert (notices.notices_dir(home) / f"{new.id}.json").is_file()


# ----------------------------------------------- the uncommitted-change kind


#: Short repos made by :func:`_tracked_repo` in the running test; the
#: autouse fixture below removes them.
_SHORT_REPOS: list[Path] = []

#: The longest repo path the commit-line tests can rely on. The code notice's
#: words name the repo (``git -C <repo> commit -m ... -- CLAUDE.md``) only
#: while the whole line fits in ``notices.MAX_TEXT`` (200); longer, they fall
#: back by design to "commit that file". pytest's own ``tmp_path`` is not
#: short enough: under xdist with a four-digit basetemp counter
#: (``/tmp/pytest-of-<user>/pytest-1487/popen-gw2/test_..._cle0/repo``) the
#: line measured 201 characters (2026-11-01, integration suite), so six
#: tests failed on the path, not on the code.
_REPO_PATH_BUDGET = 60


@pytest.fixture(autouse=True)
def _remove_short_repos():
    yield
    while _SHORT_REPOS:
        shutil.rmtree(_SHORT_REPOS.pop(), ignore_errors=True)


def _tracked_repo(tmp_path: Path) -> Path:
    """A git repo whose one tracked file is ``CLAUDE.md``. It lives in a
    short temporary directory of its own (removed after the test), not
    under *tmp_path*, so the full commit line always fits (see
    :data:`_REPO_PATH_BUDGET`)."""
    base = Path(tempfile.mkdtemp(prefix="pn-"))
    _SHORT_REPOS.append(base)
    repo = Path(os.path.realpath(base)) / "repo"
    assert len(str(repo)) <= _REPO_PATH_BUDGET, repo  # else the commit line may not fit
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    (repo / "CLAUDE.md").write_text("one\ntwo\n", encoding="utf-8")
    commit_all(repo, "seed")
    return repo


def _remove(home, repo, claude, new, *, now=T0):
    """What a plain host's removal does: the bytes before are kept, the file is
    rewritten, then the notice is made from both."""
    old = claude.read_bytes()
    claude.write_text(new, encoding="utf-8")
    return notices.add_uncommitted(home, project=repo, file=claude, before=old, now=now)


def test_an_uncommitted_notice_clears_when_the_person_commits_the_file(tmp_path):
    """The condition is git's own word: the notice shows while the file has an
    uncommitted change and stops showing once it is committed -- though it is
    neither done nor expired."""
    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    note = _remove(home, repo, claude, "one\n", now=T0)  # a lesson's line taken out
    assert note is not None and note.source == notices.SOURCE_CODE
    assert "CLAUDE.md" in note.text and " commit -m " in note.text
    assert [n.id for n in notices.visible(home, repo, now=T0)] == [note.id]  # control

    commit_all(repo, "the person commits it")
    assert notices.visible(home, repo, now=T0) == []
    stored = [n for n in notices.all_notices(home) if n.id == note.id]
    assert stored and stored[0].done_at is None  # cleared by the condition alone


def test_two_removals_before_a_commit_are_one_notice_and_a_done_one_is_renewed(tmp_path):
    """A second removal while the first notice is live must not print the same
    line twice; once the person has marked it done, a later change is news."""
    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    first = _remove(home, repo, claude, "one\n", now=T0)
    same = _remove(home, repo, claude, "", now=T0 + timedelta(hours=1))  # a second removal, still uncommitted
    assert first is not None and same is not None and same.id == first.id
    assert same.created_at == first.created_at  # the live notice was left alone
    assert same.condition["hash"] != first.condition["hash"]  # ... but follows the file
    assert [n.id for n in notices.visible(home, repo, now=T0)] == [first.id]  # one line, not two

    notices.mark_done(home, first.id, now=T0)
    assert notices.visible(home, repo, now=T0) == []  # control: done is done
    later = _remove(home, repo, claude, "one\ntwo\nthree\n", now=T0 + timedelta(days=1))  # a later change
    assert later is not None and later.id == first.id and later.done_at is None
    assert later.created_at != first.created_at  # fresh days
    assert [n.id for n in notices.visible(home, repo, now=T0 + timedelta(days=1))] == [first.id]


def test_an_uncommitted_notice_for_a_file_outside_every_repo_is_not_made(tmp_path):
    home = tmp_path / "ledger"
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "CLAUDE.md").write_text("x\n", encoding="utf-8")
    assert notices.add_uncommitted(home, project=loose, file=loose / "CLAUDE.md") is None
    assert notices.all_notices(home) == []


# ---------------------------------------------------------- known projects


def test_known_projects_are_registered_hosts_and_project_buckets_that_exist(tmp_path):
    env = make_env(tmp_path)
    bucket = env.ledger / "projects" / "some-project"
    bucket.mkdir(parents=True)
    kept = tmp_path / "bucket-project"
    kept.mkdir()
    (bucket / "meta.yaml").write_text(f"path: {kept}\n", encoding="utf-8")
    gone = env.ledger / "projects" / "gone-project"
    gone.mkdir()
    (gone / "meta.yaml").write_text(f"path: {tmp_path / 'deleted'}\n", encoding="utf-8")

    paths = {row["path"] for row in notices.known_projects(env.ledger)}
    assert os.path.realpath(env.host) in paths  # a registered host
    assert os.path.realpath(kept) in paths  # a project bucket
    assert os.path.realpath(tmp_path / "deleted") not in paths  # no longer on disk


# --------------------------------------------------------------- the CLI


def test_status_fast_carries_notices_only_inside_their_project(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    proj = _project(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    note = _add(home, proj, now=datetime.now(timezone.utc))
    assert note is not None

    monkeypatch.chdir(proj / "src")
    assert cli.main(["status", "--fast"]) == 0
    inside = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in inside["project_notices"]] == [note.id]  # control
    assert inside["project_notices"][0]["line"] == notices.format_line(note)
    assert WORDS in inside["project_notices"][0]["line"]
    assert "project_notices_more" not in inside

    monkeypatch.chdir(tmp_path)
    assert cli.main(["status", "--fast"]) == 0
    outside = json.loads(capsys.readouterr().out)
    assert "project_notices" not in outside


def test_status_fast_shows_three_notices_and_counts_the_rest(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    proj = _project(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    now = datetime.now(timezone.utc)
    for i in range(notices.MAX_SHOWN + 2):
        assert _add(home, proj, f"Notice number {i} for the project.", now=now + timedelta(seconds=i))
    monkeypatch.chdir(proj)
    assert cli.main(["status", "--fast"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["project_notices"]) == notices.MAX_SHOWN
    assert data["project_notices_more"] == 2


def test_notice_list_and_done_through_the_cli(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    proj = _project(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    note = _add(home, proj, now=datetime.now(timezone.utc))
    assert note is not None
    monkeypatch.chdir(proj)

    assert cli.main(["notice", "list", "--json"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == [note.id]  # control
    assert cli.main(["notice", "done", note.id]) == 0
    capsys.readouterr()
    assert cli.main(["notice", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["notice", "list", "--all", "--json"]) == 0
    assert [row["done_at"] is not None for row in json.loads(capsys.readouterr().out)] == [True]
    assert cli.main(["status", "--fast"]) == 0
    assert "project_notices" not in json.loads(capsys.readouterr().out)

    assert cli.main(["notice", "done", "not-an-id"]) == cli.EXIT_USAGE
    assert cli.main(["notice", "done", "ntc-00000000"]) == cli.EXIT_USAGE
    assert not (home / "notices").exists()  # nothing was ever written beside the ledger


def test_notice_done_on_an_unwritable_cache_says_so_instead_of_a_traceback(
    tmp_path, monkeypatch, capsys
):
    home = make_home(tmp_path)
    proj = _project(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    note = _add(home, proj, now=datetime.now(timezone.utc))
    assert note is not None
    monkeypatch.chdir(proj)

    def refuse(*_a, **_k):
        raise OSError("read-only cache")

    real_store = notices._store
    monkeypatch.setattr(notices, "_store", refuse)
    assert cli.main(["notice", "done", note.id]) == 1
    assert "could not write the cache" in capsys.readouterr().err
    monkeypatch.setattr(notices, "_store", real_store)  # control: writable, the same call works
    assert cli.main(["notice", "done", note.id]) == 0


def test_a_code_notice_does_not_say_self_learn_twice():
    """The hook prints `self-learn: <words>`; the words of a code notice used
    to start with `self-learn` too."""
    words = notices.uncommitted_text("CLAUDE.md")
    assert "CLAUDE.md" in words and "self-learn" not in words
    line = notices.format_line(
        notices.Notice(
            id="ntc-00000000", project="/p", text=words, source=notices.SOURCE_CODE,
            created_at="2026-10-31T12:00:00Z",
        )
    )
    assert line.startswith("self-learn: ") and line.count("self-learn") == 2  # prefix and the verb


# ------------------------------------------------------- the git budget


def test_all_the_git_questions_of_one_read_share_one_budget(tmp_path, monkeypatch):
    """The session-start hook gives `status --fast` 4 s and loses every line
    when it runs out; six 1.5 s git questions could take 9 s. Past the budget a
    notice is kept without asking (the same as a git that timed out)."""
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    for i in range(3):
        assert notices.add(
            home, project=proj, text=f"Uncommitted file number {i} needs a person.",
            source=notices.SOURCE_CODE, key=f"f{i}", now=T0,
            condition={"kind": notices.COND_UNCOMMITTED, "repo": str(proj), "file": f"f{i}"},
        )
    asked: list[float] = []

    def fake_git(argv, **kwargs):
        asked.append(kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=" M f\n", stderr="")

    monkeypatch.setattr(notices.subprocess, "run", fake_git)
    assert len(notices.visible(home, proj, now=T0)) == 3
    assert len(asked) == 3 and max(asked) <= notices.GIT_CHECK_TIMEOUT  # control: git was asked

    asked.clear()
    monkeypatch.setattr(notices, "GIT_TOTAL_BUDGET", 0.0)
    assert len(notices.visible(home, proj, now=T0)) == 3  # all kept
    assert asked == []  # and git was not asked at all


def test_the_overseer_is_shown_which_of_its_notices_are_still_up(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    other = _project(tmp_path, "other")
    live = _add(home, proj)
    assert live is not None
    gone = _add(home, proj, "A finding that a person already marked done.")
    assert gone is not None
    notices.mark_done(home, gone.id)
    _add(home, other, "An old one.", now=T0 - timedelta(days=notices.NOTICE_DAYS + 1))
    code = notices.add(
        home, project=proj, text="A code notice is not the overseer's.", source=notices.SOURCE_CODE, now=T0,
    )
    assert code is not None
    assert notices.showing_by_project(home, now=T0) == {os.path.realpath(proj): [WORDS]}


# ------------------------------------------------------------- the hook


def test_the_hook_prints_each_notice_line_and_the_count_of_the_rest(tmp_path):
    payload = _base_payload()
    payload["project_notices"] = [
        {"id": "ntc-00000001", "text": "one", "line": "self-learn: one (done with it: self-learn notice done ntc-00000001)"},
        {"id": "ntc-00000002", "text": "two", "line": "self-learn: two (done with it: self-learn notice done ntc-00000002)"},
    ]
    payload["project_notices_more"] = 4
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    # 2026-11-01: the notices print under one header line first (M9, design
    # r2 §3.9, S-127; 13 §7.5).
    assert result.stdout == (
        f"{NOTICE_HEADER}\n"
        "self-learn: one (done with it: self-learn notice done ntc-00000001)\n"
        "self-learn: two (done with it: self-learn notice done ntc-00000002)\n"
        "self-learn: 4 more notice(s) for this project — self-learn notice list\n"
    )


def test_the_hook_prints_nothing_when_the_field_is_absent_or_malformed(tmp_path):
    (tmp_path / "absent").mkdir()
    (tmp_path / "malformed").mkdir()
    absent = _run_hook(tmp_path / "absent", _base_payload())
    assert absent.returncode == 0 and absent.stdout == "", absent.stderr
    bad = _base_payload()
    bad["project_notices"] = "a string, not a list"
    malformed = _run_hook(tmp_path / "malformed", bad)
    assert malformed.returncode == 0 and malformed.stdout == "", malformed.stderr


# ------------------------------------------- a plain host's removal (M6.3)


def test_a_retirement_that_leaves_a_tracked_file_changed_leaves_a_notice(tmp_path):
    """S-89 leaves the commit to a person; the person is now told, in a session
    in that host, and not in any other directory."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a0000d1")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    git(host, "add", "-f", "CLAUDE.md")
    git(host, "commit", "-q", "-m", "track CLAUDE.md after all")
    head = _head(host)
    assert notices.all_notices(home) == []  # control: nothing before the removal

    result = verbs.retire(home, rid, covered_by="skill-md:canon", no_push=True)

    assert any("left the change uncommitted" in w for w in result.warnings), result.warnings
    assert _head(host) == head  # self-learn never commits in a plain host
    (note,) = notices.visible(home, host)
    assert "CLAUDE.md" in note.text and note.source == notices.SOURCE_CODE
    assert notices.visible(home, tmp_path) == []  # not shown outside the host

    git(host, "add", "CLAUDE.md")
    git(host, "commit", "-q", "-m", "the person commits it")
    assert notices.visible(home, host) == []  # its condition cleared


def test_a_retirement_from_an_untracked_file_leaves_no_notice(tmp_path):
    """The file git ignores holds the lesson and nothing is left for a person:
    no notice. (Positive control: the tracked case above makes one.)"""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a0000d2")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    result = verbs.retire(home, rid, covered_by="skill-md:canon", no_push=True)
    assert _record(home, rid).status == "superseded"  # control: the retirement happened
    assert not [w for w in result.warnings if "left the change uncommitted" in w], result.warnings
    assert notices.all_notices(home) == []


def test_a_reference_retirement_from_a_tracked_shelf_leaves_a_notice(tmp_path):
    """The reference-shelf leg is a second call site (`_retire_reference_host_phase`):
    two lessons on a shelf git tracks, one retired -- only its lines leave the
    shelf, the change is left for a person, and the person gets a notice. Deleting
    that call leaves this test, and only this one, red."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a0000d3")
    keep = _lesson(home, host, "lrn-9a0000d4")
    verbs.route(home, rid, dest="reference", no_push=True)
    verbs.route(home, keep, dest="reference", no_push=True)
    git(host, "add", "-f", "--", "references/LEARNINGS.md")
    git(host, "commit", "-q", "-m", "track the shelf after all")
    head = _head(host)
    assert notices.all_notices(home) == []  # control: nothing before the removal

    result = verbs.retire(home, rid, covered_by="skill-md:canon", no_push=True)

    assert _record(home, rid).status == "superseded"
    assert any("left the change uncommitted" in w for w in result.warnings), result.warnings
    assert _head(host) == head
    (note,) = notices.visible(home, host)
    assert "references/LEARNINGS.md" in note.text and note.source == notices.SOURCE_CODE
    assert notices.visible(home, tmp_path) == []


# ------------------------------------------- the overseer's notices.yaml

KNOWN = {os.path.realpath(formats.EXAMPLE_PROJECT)}


def test_the_formats_example_notices_validate_and_each_broken_twin_is_dropped():
    data = YAML(typ="safe").load(formats.phase_b_examples()["notices.yaml"])
    kept, dropped = overseer_run._validate_notices(data, KNOWN)
    assert dropped == [] and len(kept) == 1  # control
    assert kept[0]["project"] == os.path.realpath(formats.EXAMPLE_PROJECT)

    base = data["notices"][0]
    broken = {
        "a path the ledger does not know": {**base, "project": "/srv/somewhere-else"},
        "a control character": {**base, "text": "line one\x07line two"},
        "too long": {**base, "text": "x" * (notices.MAX_TEXT + 1)},
        "an unknown key": {**base, "severity": "high"},
        "a case that is not a case id": {**base, "case": "the-weekly-one"},
        "no text": {"project": base["project"]},
    }
    for name, entry in broken.items():
        kept, dropped = overseer_run._validate_notices({"notices": [entry]}, KNOWN)
        assert kept == [] and len(dropped) == 1, name
        assert dropped[0].startswith("notice 1: dropped"), (name, dropped)
        assert (entry.get("text") or "\0") not in dropped[0], name  # never the model's text


def test_a_wrapped_block_scalar_is_one_line_and_is_kept():
    """A model that writes `text: |` and wraps it at 80 columns puts a line
    break in the middle of one sentence. The prompt asks for one double-quoted
    line, but a wrapped one must still be a notice (it was dropped whole)."""
    raw = (
        "notices:\n"
        f"  - project: {formats.EXAMPLE_PROJECT}\n"
        "    text: |\n"
        "      The shutdown watchdog predates the daemon it guards;\n"
        "      nothing is wrong, but do not rely on it.\n"
    )
    data = YAML(typ="safe").load(raw)
    assert "\n" in data["notices"][0]["text"].strip()  # control: the value really wraps
    kept, dropped = overseer_run._validate_notices(data, KNOWN)
    assert dropped == [] and len(kept) == 1
    assert kept[0]["text"] == (
        "The shutdown watchdog predates the daemon it guards; nothing is wrong, but do not rely on it."
    )
    assert notices.text_problem(kept[0]["text"]) is None


def test_a_project_path_the_secret_scan_matches_costs_that_notice_not_the_run():
    """The run record is secret-scanned whole and a hit refuses the run, so a
    notice may not carry a path the scan matches. (Control: a clean known path
    with the same words is kept.)"""
    leaky = "/srv/" + "ghp_" + "A1b2C3d4" * 5
    words = "A fine one-line notice."
    kept, dropped = overseer_run._validate_notices(
        {"notices": [{"project": formats.EXAMPLE_PROJECT, "text": words}]}, KNOWN
    )
    assert len(kept) == 1 and dropped == []  # control
    kept, dropped = overseer_run._validate_notices(
        {"notices": [{"project": leaky, "text": words}]}, {os.path.realpath(leaky)}
    )
    assert kept == [] and dropped == ["notice 1: dropped — the secret scan matched the project path"]
    assert leaky not in dropped[0]


def test_a_notices_file_that_is_not_a_notices_list_drops_whole():
    for data in ({"notices": "no"}, {"notices": [], "extra": 1}, ["a list"], None):
        kept, dropped = overseer_run._validate_notices(data, KNOWN)
        assert kept == [] and dropped == ["notices.yaml: dropped — expected only a notices list"]


def test_a_run_keeps_at_most_five_notices_and_one_of_each(tmp_path):
    entries = [
        {"project": formats.EXAMPLE_PROJECT, "text": f"Notice number {i}."}
        for i in range(notices.MAX_PER_RUN + 2)
    ]
    entries.append(dict(entries[0]))  # the same notice twice
    kept, dropped = overseer_run._validate_notices({"notices": entries}, KNOWN)
    assert len(kept) == notices.MAX_PER_RUN  # control: five were kept
    assert len(dropped) == 3
    assert sum("same notice twice" in line for line in dropped) == 1
    assert sum("more than" in line for line in dropped) == 2


def test_read_notices_costs_the_run_nothing_in_any_state(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    assert overseer_run._read_notices(stage, {}, KNOWN) == ([], [])  # no file: no notices
    (stage / "notices.yaml").write_text("notices: [a: b: c\n", encoding="utf-8")
    kept, lines = overseer_run._read_notices(stage, {}, KNOWN)
    assert kept == [] and len(lines) == 1 and lines[0].endswith("every notice dropped")
    (stage / "notices.yaml").write_text("- not a mapping\n", encoding="utf-8")
    kept, lines = overseer_run._read_notices(stage, {}, KNOWN)
    assert kept == [] and lines and lines[0].endswith("every notice dropped")
    kept, lines = overseer_run._read_notices(stage, {"notices.yaml": "github-token"}, KNOWN)
    assert kept == [] and "withheld" in lines[0] and "github-token" in lines[0]


def test_a_secret_in_notices_yaml_is_withheld_and_the_run_goes_on():
    assert "notices.yaml" in overseer_run._WITHHELD_ON_SECRET
    assert overseer_run._WITHHELD_ON_SECRET["notices.yaml"] == "notices: []\n"
    assert "notices.yaml" not in overseer_run.REQUIRED_OUTPUT_FILES


def test_the_phase_b_prompt_and_formats_tell_the_overseer_about_notices(tmp_path):
    prompt = overseer_run._phase_b_prompt(tmp_path, (), ())
    assert "notices.yaml is optional" in prompt and "projects.yaml" in prompt
    flat = " ".join(prompt.split())
    # one double-quoted line, like the two other free-text exceptions (a wrapped
    # block scalar used to be dropped), and the notices still up are named
    assert "ONE line (a double-quoted string, never a block scalar)" in flat
    assert "A notice's text in notices.yaml is held to one line as well" in flat
    assert "`showing` list in projects.yaml" in flat
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root = formats.write(workspace, "B")
    assert (root / "notices.yaml").is_file()
    assert "notices.yaml (optional)" in (root / "README.md").read_text(encoding="utf-8")
    sets = YAML(typ="safe").load((root / "closed-sets.yaml").read_text(encoding="utf-8"))
    assert sets["notices"]["max_per_run"] == notices.MAX_PER_RUN
    assert sets["notices"]["ends_after_days"] == notices.NOTICE_DAYS
    (tmp_path / "ws-a").mkdir()
    phase_a = formats.write(tmp_path / "ws-a", "A")
    assert not (phase_a / "notices.yaml").exists()  # phase A is blind to all of it


def test_writing_a_run_records_notices_is_idempotent(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    manifest = {
        "run_id": "run-0000000000aa",
        "notices": [
            {"project": str(proj), "text": WORDS, "case": "case-0000000b"},
            {"project": str(proj)},  # malformed row: skipped, never raises
        ],
    }
    assert overseer_run._write_project_notices(home, manifest) == 1
    (note,) = notices.all_notices(home)
    assert note.source == notices.SOURCE_OVERSEER and note.run == "run-0000000000aa"
    notices.mark_done(home, note.id)
    assert overseer_run._write_project_notices(home, manifest) == 1  # a resume
    (again,) = notices.all_notices(home)
    assert again.id == note.id and again.done_at is not None  # still done
    assert overseer_run._write_project_notices(home, {"run_id": "x"}) == 0  # an old record


def _notice_run(tmp_path, monkeypatch, entries, *, dry_run=False, before=None, setup=None):
    """One overseer run on a sandbox ledger whose fake phase B writes the
    notices.yaml that ``entries(env, parked_case_id)`` answers (*before* runs
    first, with the env)."""
    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    seen: dict[str, str] = {}
    if before is not None:
        before(env)
    if setup is not None:
        setup(env, parked_a)  # with the id of the case the run will examine

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-s":
            # integration 2026-10-31 (SK4): skill discovery runs in its own
            # workspace, which holds no projects.yaml; nothing to stage here.
            return _ok()
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _stage_two_successors(
                stage, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
            )
            seen["projects"] = (stage / "projects.yaml").read_text(encoding="utf-8")
            _dump(stage / "notices.yaml", {"notices": entries(env, parked_a)})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, dry_run=dry_run, no_push=True)
    return env, home, result, seen


def test_a_run_writes_its_notices_for_known_projects_and_names_what_it_dropped(
    tmp_path, monkeypatch
):
    def entries(env, parked):
        return [
            {"project": str(env.host), "text": WORDS, "case": parked},
            {"project": str(tmp_path / "elsewhere"), "text": "A notice for a path nobody registered."},
        ]

    env, home, result, seen = _notice_run(tmp_path, monkeypatch, entries)

    assert result.status == "applied", result  # a bad notice never costs the run
    assert os.path.realpath(env.host) in seen["projects"]  # phase B was told its projects
    (note,) = notices.all_notices(home)
    assert note.project == os.path.realpath(env.host) and note.text == WORDS
    assert note.source == notices.SOURCE_OVERSEER and note.run == result.run
    assert [n.id for n in notices.visible(home, env.host)] == [note.id]
    assert notices.visible(home, tmp_path) == []
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do", 1)[1]
    assert "notice 2: dropped — project is not one of the projects in projects.yaml" in refused
    assert "A notice for a path nobody registered." not in report  # never the model's words
    manifest = execution_evidence.read_manifest(home, result.run, at="HEAD")
    assert [row["text"] for row in manifest["notices"]] == [WORDS]
    # a notice is cache, not ledger: the run record above is its one ledger
    # copy, and nothing else of the ledger home was made for it
    assert not (home / "notices").exists()


def test_a_dry_run_writes_no_notice(tmp_path, monkeypatch):
    """A dry run writes only inside the cache stage and commits nothing. (The
    real run above is the positive control: the same stage files do write.)"""

    def entries(env, parked):
        return [{"project": str(env.host), "text": WORDS}]

    _env, home, result, seen = _notice_run(tmp_path, monkeypatch, entries, dry_run=True)
    assert result.status == "dry-run"  # the run got as far as the end of a dry run ...
    assert "projects" in seen  # ... and phase B ran and wrote the same notices.yaml
    assert notices.all_notices(home) == []


def test_phase_b_is_shown_the_overseer_notices_still_up_in_each_project(tmp_path, monkeypatch):
    """A reworded finding is a new notice with a fresh 14 days, so phase B is
    told what is still showing and asked not to repeat it. (Control: a run with
    nothing showing has no `showing` key.)"""

    def entries(env, parked):
        return []

    (tmp_path / "plain").mkdir()
    _e, _h, _r, seen_plain = _notice_run(tmp_path / "plain", monkeypatch, entries)
    assert "path:" in seen_plain["projects"] and "showing" not in seen_plain["projects"]

    def up(env):
        assert notices.add(
            env.ledger, project=env.host, text=WORDS, source=notices.SOURCE_OVERSEER,
        )

    (tmp_path / "with").mkdir()
    _e, _h, _r, seen = _notice_run(tmp_path / "with", monkeypatch, entries, before=up)
    data = YAML(typ="safe").load(seen["projects"])
    (row,) = [r for r in data["projects"] if r["path"] == os.path.realpath(_e.host)]
    assert row["showing"] == [WORDS]


# ============================ hand-maintenance round b, lane CU-6 (S-118)
#
# A condition notice outlives 14 days while its condition holds; its words name
# the exact commit; the overseer sees the waiting ones; a notice marked done is
# keyed by its case, so other words do not bring it back.

LATE = T0 + timedelta(days=20)


def _dirty_notice(tmp_path, now=T0):
    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    note = _remove(home, repo, claude, "one\n", now=now)  # a lesson's line taken out
    assert note is not None
    return home, repo, claude, note


def test_a_code_notice_on_a_still_dirty_file_shows_on_day_twenty(tmp_path):
    home, repo, claude, note = _dirty_notice(tmp_path)
    assert [n.id for n in notices.visible(home, repo, now=T0 + timedelta(days=5))] == [note.id]  # control
    assert [n.id for n in notices.visible(home, repo, now=LATE)] == [note.id]
    commit_all(repo, "the agent commits it")
    assert notices.visible(home, repo, now=LATE) == []  # the condition cleared


def test_past_fourteen_days_a_condition_git_cannot_answer_hides_the_notice(tmp_path, monkeypatch):
    home, repo, _claude, note = _dirty_notice(tmp_path)

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(notices.subprocess, "run", timed_out)
    assert [n.id for n in notices.visible(home, repo, now=T0 + timedelta(days=5))] == [note.id]  # young: kept
    assert notices.visible(home, repo, now=LATE) == []  # old: hidden


def test_prune_keeps_a_dirty_condition_notice_and_deletes_a_done_one(tmp_path):
    home, repo, claude, note = _dirty_notice(tmp_path)
    path = notices.notices_dir(home) / f"{note.id}.json"
    day40 = T0 + timedelta(days=40)
    assert notices.prune(home, now=day40) == 0 and path.is_file()
    commit_all(repo, "committed")
    assert notices.prune(home, now=day40) == 1 and not path.exists()  # cleared: goes
    again = _remove(home, repo, claude, "", now=T0)
    assert again is not None
    notices.mark_done(home, again.id, now=T0)
    assert notices.prune(home, now=day40) == 1  # done: goes even though the file is dirty
    assert notices.all_notices(home) == []


def test_a_second_removal_after_fourteen_days_leaves_the_dirty_notice_as_it_is_and_it_shows(tmp_path):
    home, repo, claude, first = _dirty_notice(tmp_path)
    same = notices.add_uncommitted(
        home, project=repo, file=claude, before=claude.read_bytes(), now=LATE)
    assert same is not None and same.created_at == first.created_at  # dirty: left alone
    assert [n.id for n in notices.visible(home, repo, now=LATE)] == [first.id]
    notices.mark_done(home, first.id, now=LATE)
    fresh = _remove(home, repo, claude, "", now=LATE)  # done: renewed
    assert fresh is not None and fresh.done_at is None and fresh.created_at != first.created_at


def test_a_code_notice_names_the_exact_commit_for_its_one_file(tmp_path):
    home, repo, claude, note = _dirty_notice(tmp_path)
    assert f"git -C {os.path.realpath(repo)} commit" in note.text and "-- CLAUDE.md" in note.text
    assert "nothing else changed" in note.text
    assert len(note.text) <= notices.MAX_TEXT and "self-learn" not in note.text
    words = notices.uncommitted_text("dir with space/a b.md", repo="/r", repo_rel="dir with space/a b.md")
    assert "'" in words and "a b.md'" in words  # quoted for a shell
    deep = "d/" * 60 + "x.md"
    assert len(notices.uncommitted_text(deep, repo="/r", repo_rel=deep)) <= notices.MAX_TEXT
    assert len(notices.uncommitted_text(deep, repo="/r", repo_rel=deep, clean=False)) <= notices.MAX_TEXT


def test_the_commit_line_in_the_notice_commits_only_that_file(tmp_path):
    """Run the notice's own command from a subdirectory: it must commit the
    one file and leave another dirty file alone."""
    import shlex

    home, repo, claude, note = _dirty_notice(tmp_path)
    (repo / "other.md").write_text("x\n", encoding="utf-8")
    git(repo, "add", "other.md")
    (repo / "sub").mkdir()
    command = note.text[note.text.index("git -C"):]
    argv = shlex.split(command)
    assert argv[:2] == ["git", "-C"] and argv[3] == "commit"
    subprocess.run(argv, cwd=repo / "sub", check=True, capture_output=True)
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True,
    ).stdout
    assert "CLAUDE.md" not in status and "other.md" in status


def test_the_health_row_lists_a_dirty_notice_and_not_a_committed_one(tmp_path):
    from self_learn.overseer import health

    home, repo, _claude, note = _dirty_notice(tmp_path)
    row = health.uncommitted_host_removals_row(home)
    assert row["kind"] == "uncommitted-host-removals"
    (item,) = row["items"]
    assert item["project"] == os.path.realpath(repo) and item["file"].endswith("CLAUDE.md")
    assert item["since"] == note.created_at
    assert "uncommitted-host-removals" in [r["kind"] for r in health.gather(home)]
    commit_all(repo, "committed")
    assert health.uncommitted_host_removals_row(home)["items"] == []
    notices.mark_done(home, note.id)
    assert health.uncommitted_host_removals_row(home)["items"] == []


def test_a_done_overseer_notice_is_not_made_again_in_other_words_for_the_same_case(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    manifest = {"run_id": "run-0000000000aa", "notices": [
        {"project": str(proj), "text": WORDS, "case": "case-0000000b"}]}
    overseer_run._write_project_notices(home, manifest)
    (note,) = notices.all_notices(home)
    assert note.case == "case-0000000b"
    notices.mark_done(home, note.id)
    reworded = {"run_id": "run-0000000000bb", "notices": [
        {"project": str(proj), "text": "The watchdog is older than its daemon; leave it be.",
         "case": "case-0000000b"}]}
    overseer_run._write_project_notices(home, reworded)
    assert [n.id for n in notices.all_notices(home)] == [note.id]  # nothing new
    other = {"run_id": "run-0000000000cc", "notices": [
        {"project": str(proj), "text": "The watchdog is older than its daemon; leave it be.",
         "case": "case-0000000c"}]}
    overseer_run._write_project_notices(home, other)
    assert len(notices.all_notices(home)) == 2  # control: another case is news


def test_validation_names_a_notice_a_person_already_marked_done(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    overseer_run._write_project_notices(home, {"notices": [
        {"project": str(proj), "text": WORDS, "case": "case-0000000b"}]})
    (note,) = notices.all_notices(home)
    notices.mark_done(home, note.id)
    real = os.path.realpath(proj)
    done = lambda project, text, case: notices.is_done_key(  # noqa: E731
        home, project, notices.overseer_key(text, case))
    data = {"notices": [
        {"project": real, "text": "Said again, in other words.", "case": "case-0000000b"},
        {"project": real, "text": "A different case.", "case": "case-0000000c"},
    ]}
    kept, dropped = overseer_run._validate_notices(data, [real], done)
    assert [row["text"] for row in kept] == ["A different case."]
    assert dropped == ["notice 1: dropped — already marked done"]
    kept_all, none = overseer_run._validate_notices(data, [real])  # control: no check, both kept
    assert len(kept_all) == 2 and none == []


def test_notices_marked_done_show_in_projects_yaml_for_thirty_days(tmp_path):
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    note = _add(home, proj, now=T0)
    assert note is not None
    assert notices.done_by_project(home, now=T0) == {}  # control: not done yet
    notices.mark_done(home, note.id, now=T0)
    assert notices.done_by_project(home, now=T0 + timedelta(days=29)) == {os.path.realpath(proj): [WORDS]}
    assert notices.done_by_project(home, now=T0 + timedelta(days=31)) == {}


def test_phase_b_is_shown_the_done_notices_of_each_project(tmp_path, monkeypatch):
    def entries(env, parked):
        return []

    def done(env):
        note = notices.add(env.ledger, project=env.host, text=WORDS, source=notices.SOURCE_OVERSEER)
        assert note is not None
        notices.mark_done(env.ledger, note.id)

    _e, _h, _r, seen = _notice_run(tmp_path, monkeypatch, entries, before=done)
    data = YAML(typ="safe").load(seen["projects"])
    (row,) = [r for r in data["projects"] if r["path"] == os.path.realpath(_e.host)]
    assert row["done"] == [WORDS] and "showing" not in row


def test_a_run_names_a_notice_already_marked_done_in_refused(tmp_path, monkeypatch):
    """No monkeypatch: a REAL case-keyed notice is marked done for the run's
    case (other words), and the run's own keying finds it. Control: another
    case's notice is written."""

    def entries(env, parked):
        return [{"project": str(env.host), "text": "Said in new words.", "case": parked}]

    def done(env, case):
        note = notices.add(
            env.ledger, project=env.host, text="The first words.", source=notices.SOURCE_OVERSEER,
            key=notices.overseer_key("The first words.", case), case=case,
        )
        assert note is not None
        notices.mark_done(env.ledger, note.id)

    _env, home, result, _seen = _notice_run(tmp_path, monkeypatch, entries, setup=done)
    assert result.status == "applied", result
    assert [n.text for n in notices.all_notices(home)] == ["The first words."]  # nothing new
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "notice 1: dropped — already marked done" in report.split("## Refused / could not do", 1)[1]

    other = tmp_path / "other"
    other.mkdir()

    def done_elsewhere(env, case):
        note = notices.add(
            env.ledger, project=env.host, text="Another case.", source=notices.SOURCE_OVERSEER,
            key=notices.overseer_key("Another case.", "case-00000000"), case="case-00000000",
        )
        assert note is not None
        notices.mark_done(env.ledger, note.id)

    _e, home2, result2, _s = _notice_run(other, monkeypatch, entries, setup=done_elsewhere)
    assert result2.status == "applied", result2
    assert "Said in new words." in [n.text for n in notices.all_notices(home2)]  # control


# ----------------------------------------- gate r1: the condition is the removal


def test_a_file_that_held_edits_before_the_removal_is_not_offered_as_a_whole_file_commit(tmp_path):
    """MAJOR 1(a): the person had an uncommitted line in CLAUDE.md; the removal
    must not tell the next agent that nothing else changed and to commit it."""
    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    _clean = _remove(home, repo, claude, "one\n", now=T0)  # control: a clean file gets the commit line
    assert _clean is not None and "nothing else changed" in _clean.text and "commit -m" in _clean.text
    notices.mark_done(home, _clean.id, now=T0)
    commit_all(repo, "seed again")
    claude.write_text("one\nthe person's own line\n", encoding="utf-8")  # work in progress
    note = _remove(home, repo, claude, "the person's own line\n", now=T0)
    assert note is not None and note.condition["clean"] == "0"
    assert "nothing else changed" not in note.text and "commit -m" not in note.text
    assert "diff" in note.text and "other" in note.text and len(note.text) <= notices.MAX_TEXT


def test_a_removal_committed_and_then_the_file_edited_again_does_not_come_back(tmp_path):
    """MAJOR 1(b): the notice is about the removal, and the removal is
    committed; a later edit is not it, on day 20 or in the health row."""
    from self_learn.overseer import health

    home, repo, claude, note = _dirty_notice(tmp_path)
    assert [n.id for n in notices.visible(home, repo, now=LATE)] == [note.id]  # control: holds
    commit_all(repo, "the agent commits it")
    assert notices.visible(home, repo, now=LATE) == []
    claude.write_text("one\nand then somebody typed this\n", encoding="utf-8")
    assert notices.visible(home, repo, now=LATE) == []
    assert notices.visible(home, repo, now=T0 + timedelta(days=5)) == []  # not even young
    assert health.uncommitted_host_removals_row(home)["items"] == []
    assert notices.prune(home, now=T0 + timedelta(days=40)) == 1


def test_an_edit_after_the_removal_ends_the_notice_in_the_health_row_too(tmp_path):
    from self_learn.overseer import health

    home, repo, claude, note = _dirty_notice(tmp_path)
    assert len(health.uncommitted_host_removals_row(home)["items"]) == 1  # control
    claude.write_text("one\nanother edit\n", encoding="utf-8")
    assert health.uncommitted_host_removals_row(home)["items"] == []
    assert notices.condition_state(note) == "changed"


def test_the_commit_line_works_from_a_linked_worktree_of_the_project(tmp_path):
    """MINOR 2: a session in the project's worktree is shown the line; running
    it there commits the checkout the removal was made in, not the worktree's
    own copy of the file."""
    import shlex

    home, repo, claude, note = _dirty_notice(tmp_path)
    tree = repo / ".claude" / "worktrees" / "w"
    git(repo, "worktree", "add", "-q", str(tree), "-b", "w")
    (shown,) = notices.visible(home, tree, now=T0)  # the worktree session is shown it
    assert shown.id == note.id
    argv = shlex.split(note.text[note.text.index("git -C"):])
    done = subprocess.run(argv, cwd=tree, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--", "CLAUDE.md"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert status.strip() == ""  # the main checkout's file is committed
    assert notices.visible(home, repo, now=T0) == []


def test_a_done_notice_stays_done_for_thirty_days_from_the_day_it_was_marked(tmp_path):
    """MINOR 3: made on day 0, marked done on day 10: still done on day 35."""
    home = tmp_path / "ledger"
    proj = _project(tmp_path)
    note = _add(home, proj, now=T0)
    assert note is not None
    notices.mark_done(home, note.id, now=T0 + timedelta(days=10))
    key = WORDS
    assert notices.prune(home, now=T0 + timedelta(days=35)) == 0
    assert notices.is_done_key(home, proj, key, now=T0 + timedelta(days=35))
    assert notices.prune(home, now=T0 + timedelta(days=41)) == 1  # control: it does go
    assert not notices.is_done_key(home, proj, key, now=T0 + timedelta(days=41))


def test_the_health_row_says_so_when_git_cannot_answer_or_the_notices_cannot_be_read(
    tmp_path, monkeypatch
):
    """MINOR 4: a question that could not be asked is not 'nothing waiting'."""
    from self_learn.overseer import health

    home, repo, _claude, note = _dirty_notice(tmp_path)
    assert health.uncommitted_host_removals_row(home)["state"] == "ok"  # control

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(notices.subprocess, "run", timed_out)
    row = health.uncommitted_host_removals_row(home)
    assert row["items"] == [] and [u["file"].endswith("CLAUDE.md") for u in row["unknown"]] == [True]
    assert row["state"] == "ok" and "unknown" in row["caution"]

    def broken(home_):
        raise RuntimeError("cache unreadable")

    monkeypatch.setattr(notices, "all_notices", broken)
    row = health.uncommitted_host_removals_row(home)
    assert row["state"] == "unavailable" and "cache unreadable" in row["reason"]


# ------------------------------------------------- gate r2: an ended notice is replaced


def test_a_second_removal_after_the_first_was_committed_with_more_gets_a_fresh_notice(tmp_path):
    """Gate r2 MAJOR 1: removal 1 committed together with the person's own
    line (not marked done, day 0..5): removal 2 is a new, uncommitted removal
    and must be shown and listed, with the whole-file commit line."""
    from self_learn.overseer import health

    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    first = _remove(home, repo, claude, "one\n", now=T0)
    assert first is not None  # control
    assert [n.id for n in notices.visible(home, repo, now=T0)] == [first.id]
    claude.write_text("one\nthe person's own line\n", encoding="utf-8")
    commit_all(repo, "removal and more")
    day5 = T0 + timedelta(days=5)
    second = _remove(home, repo, claude, "one\nthe person's own line\nx\n", now=day5)
    assert second is not None and second.condition["hash"] != first.condition["hash"]
    assert "nothing else changed" in second.text
    shown = notices.visible(home, repo, now=day5)
    assert [n.id for n in shown] == [second.id]
    assert shown[0].condition["hash"] == second.condition["hash"]
    assert [i["file"] for i in health.uncommitted_host_removals_row(home)["items"]] == [str(claude)]


def test_a_second_removal_over_edits_in_progress_gets_a_fresh_review_notice(tmp_path):
    from self_learn.overseer import health

    home = tmp_path / "ledger"
    repo = _tracked_repo(tmp_path)
    claude = repo / "CLAUDE.md"
    first = _remove(home, repo, claude, "one\n", now=T0)
    assert first is not None
    claude.write_text("one\nedit in progress\n", encoding="utf-8")  # never committed
    day5 = T0 + timedelta(days=5)
    second = _remove(home, repo, claude, "edit in progress\n", now=day5)
    assert second is not None and second.condition["clean"] == "0"
    assert "nothing else changed" not in second.text and "diff" in second.text
    assert [n.id for n in notices.visible(home, repo, now=day5)] == [second.id]
    items = health.uncommitted_host_removals_row(home)["items"]
    assert [i["file"] for i in items] == [str(claude)] and items[0]["mixed"] is True
