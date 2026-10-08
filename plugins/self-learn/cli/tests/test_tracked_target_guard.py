"""G1 (2026-10-07): self-learn writes a file in a plain host only after git
ignores it (D-DEPLOY §1.1).

The user, 2026-10-07, asked whether self-learn should refuse to write into a
file the repo's git tracks: "yes, build it please. just keep in mind that
just because we use claude.local.md doesn't mean it's automatically git
ignored or something. it'll still show up as untracked changes if we don't
add it to git ignores."

So, for a ``plain``-mode registration, every writer (the steward, the
overseer, a person's ``route`` / ``teach --route``, ``recompile``, and the
removal legs of the retiring verbs):

- refuses a file git tracks (index or ``HEAD``), and a file the repo's own
  ignore rules would still re-admit with its ignore line in place;
- otherwise writes the file's anchored line into a self-learn block of the
  repo's private ``info/exclude`` (shared by every worktree) under the host
  lock, just before the file itself;
- judges the file at its REAL path, and passes a file outside every repo.

A ``git``-mode registration is untouched. Every scenario runs on pytest
sandbox repos and ledgers with fake model sessions; ids are synthetic.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from self_learn import batch, cases, cli, gitops, steward, verbs
from self_learn.hosts import MARKER_FILENAME, host_add
from self_learn.invocation.contract import Outcome
from self_learn.ledger_ops import create_record, find_record_path, stamp_proposal, write_proposal
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from support import (
    CLAUDE_MD_SEED,
    commit_all,
    git,
    hook_proposal_fields,
    init_repo,
    last_verb_sha,
    make_behavior,
    make_env,
    proposal_dict,
)
from test_failstate_overseer import _ok, _phase_a, _phase_b_common
from test_overseer_run import _dump, _enabled
from test_steward import _dump_yaml, _enable_steward, _stage_dir
from test_steward_refusals import (
    _REPAIR_HEADER,
    _case,
    _dispositions,
    _notifications,
    _seed,
    _with_always_loaded,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


#: What the operator put in a repo's info/exclude by hand before any of this
#: (D-DEPLOY §3.7): lines OUTSIDE any self-learn block, never touched.
OPERATOR_LINES = "# hand-written, outside any block\n/.self-learn-host\n"

_LEDGER_REPAIR = "The ledger would refuse these lines of your sheets as written:"


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
    """The repo's private ignore file, asked of git itself (the test does
    not lean on the code under test to find it)."""
    out = Path(git(repo, "rev-parse", "--git-path", "info/exclude").stdout.strip())
    return out if out.is_absolute() else repo / out


def _block(repo: Path) -> list[str] | None:
    """The lines of the self-learn block in *repo*'s info/exclude, or None
    when there is no block."""
    path = _exclude(repo)
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    begins = [i for i, line in enumerate(lines) if line.startswith("# self-learn:begin")]
    if not begins:
        return None
    end = lines.index("# self-learn:end")
    return lines[begins[0] + 1 : end]


def _write_operator_lines(repo: Path) -> None:
    path = _exclude(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(OPERATOR_LINES, encoding="utf-8")


def _plain_repo_host(
    home: Path, tmp_path: Path, name: str = "plain-host", *, track_claude_md: bool = True
) -> Path:
    """A git repository registered as a PLAIN project host -- every live
    host's shape: a repo self-learn must stay out of. Its CLAUDE.md is
    tracked unless *track_claude_md* is False. The operator's own
    info/exclude line hides the plain-host marker, so `git status` starts
    clean."""
    host = tmp_path / name
    init_repo(host)
    (host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")
    commit_all(host, "host seed")
    if not track_claude_md:
        git(host, "rm", "-q", "--cached", "CLAUDE.md")
        git(host, "commit", "-q", "-m", "untrack CLAUDE.md")
    _write_operator_lines(host)
    host_add(home, host, "project", mode="plain")
    return host


def _lesson(home: Path, host: Path, rid: str) -> str:
    create_record(home, make_behavior(scope="project", record_id=rid), project_path=host)
    commit_all(home, f"seed {rid}")
    return rid


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _sheet(tmp_path: Path, items: list[dict], name: str = "sheet") -> batch.Sheet:
    path = tmp_path / f"{name}.yaml"
    _dump_yaml(path, {"version": 1, "items": items})
    return batch.load_sheet(path)


# ------------------------------------------- a tracked target, every actor


@pytest.mark.parametrize("actor", ["steward", "overseer", "human"])
def test_a_tracked_target_is_refused_for_every_actor_and_nothing_is_written(
    tmp_path, actor
):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _lesson(home, host, "lrn-9a000001")
    claude_md = (host / "CLAUDE.md").read_bytes()
    ledger_head, host_head = last_verb_sha(home), _head(host)
    sheet = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "claude-md"}])

    preview = batch.dry_run(home, sheet, actor=actor)
    result = batch.run(home, sheet, no_push=True, actor=actor)

    (pitem,), (item,) = preview.items, result.items
    assert (pitem.state, pitem.kind) == ("would-refuse", "destination-unavailable"), pitem.detail
    assert (item.state, item.kind) == ("refused", "destination-unavailable"), item.detail
    assert "CLAUDE.md is tracked by git" in (item.detail or "")
    assert "nothing was written" in (item.detail or "")
    assert item.detail == pitem.detail  # the preview runs the verb's own check
    # nothing written: ledger, host file, host index, host ignore file
    assert _record(home, rid).status == "pending"
    assert last_verb_sha(home) == ledger_head  # a telemetry flush may ride on top
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _head(host) == host_head and _status(host) == ""
    assert _exclude(host).read_text(encoding="utf-8") == OPERATOR_LINES


def test_a_person_s_route_into_a_tracked_file_is_a_clear_message_with_nothing_written(
    tmp_path, monkeypatch, capsys
):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _lesson(home, host, "lrn-9a000002")
    claude_md = (host / "CLAUDE.md").read_bytes()
    ledger_head = last_verb_sha(home)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    capsys.readouterr()

    rc = cli.main(["route", rid, "--dest", "claude-md", "--no-push"])

    err = capsys.readouterr().err
    assert rc == 1, err
    assert f"{host / 'CLAUDE.md'} is tracked by git in {host}" in err
    assert "nothing was written" in err
    assert "claude-md:local" in err  # what to do instead
    assert "Traceback" not in err
    assert _record(home, rid).status == "pending"
    assert last_verb_sha(home) == ledger_head  # a telemetry flush may ride on top
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _status(host) == ""


# ------------------------------------------------- an untracked target


def test_an_untracked_target_gets_its_ignore_line_first_and_is_ignored_afterwards(tmp_path):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    first = _lesson(home, host, "lrn-9a000003")
    second = _lesson(home, host, "lrn-9a000004")
    host_head = _head(host)
    assert not _ignored(host, "CLAUDE.local.md")  # control: nothing ignores it yet

    verbs.route(home, first, dest="claude-md:local", no_push=True)

    local = host / "CLAUDE.local.md"
    assert first in local.read_text(encoding="utf-8")
    assert _ignored(host, "CLAUDE.local.md")  # the positive control, before the absence
    assert "CLAUDE.local.md" not in _status(host)
    assert _status(host) == ""
    text = _exclude(host).read_text(encoding="utf-8")
    assert text.startswith(OPERATOR_LINES)  # the operator's lines, byte for byte
    assert _block(host) == ["/CLAUDE.local.md"]
    assert _head(host) == host_head  # a plain host is never committed to

    # A second write into the same file adds no second line.
    verbs.route(home, second, dest="claude-md:local", no_push=True)
    assert second in local.read_text(encoding="utf-8")
    assert _block(host) == ["/CLAUDE.local.md"]
    assert _exclude(host).read_text(encoding="utf-8").count("/CLAUDE.local.md") == 1


def test_a_target_the_repos_own_gitignore_re_admits_is_refused(tmp_path):
    """D-DEPLOY §0.5: a FILE-level negation in the repo's .gitignore beats
    the exclude line (the .gitignore ranks higher) -- refused, nothing
    written. A FOLDER-level negation does not beat a file line -- that
    write goes ahead and is ignored."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    (host / ".gitignore").write_text("!CLAUDE.local.md\n", encoding="utf-8")
    commit_all(host, "re-admit CLAUDE.local.md")
    rid = _lesson(home, host, "lrn-9a000005")

    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, rid, dest="claude-md:local", no_push=True)

    message = str(caught.value)
    assert "would still not be ignored by git" in message
    assert "'/CLAUDE.local.md'" in message and "re-admit" in message
    assert not (host / "CLAUDE.local.md").exists()
    assert _exclude(host).read_text(encoding="utf-8") == OPERATOR_LINES
    assert _record(home, rid).status == "pending"

    folder = _plain_repo_host(home, tmp_path, "folder-negation-host")
    (folder / ".gitignore").write_text(".claude/\n!/.claude/rules/\n", encoding="utf-8")
    commit_all(folder, "re-admit the rules folder")
    other = _lesson(home, folder, "lrn-9a000006")
    verbs.route(
        home, other, dest="claude-md:rules:guard-topic", rules_paths=["CLAUDE.md"],
        no_push=True,
    )
    assert other in (folder / ".claude" / "rules" / "guard-topic.md").read_text(encoding="utf-8")
    assert _ignored(folder, ".claude/rules/guard-topic.md")
    assert _status(folder) == ""
    assert _block(folder) == ["/.claude/rules/guard-topic.md"]


# ------------------------------------------------------------ worktrees


def test_a_worktree_of_the_host_shares_the_exclude_file_and_the_lock(tmp_path):
    home = make_env(tmp_path).ledger
    main = tmp_path / "main-checkout"
    init_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    commit_all(main, "seed")
    _write_operator_lines(main)
    linked = tmp_path / "linked-worktree"
    git(main, "worktree", "add", "-q", "-b", "side", str(linked))
    host_add(home, linked, "project", mode="plain")
    rid = _lesson(home, linked, "lrn-9a000007")

    # one file for both checkouts
    assert _exclude(linked) == _exclude(main) == main / ".git" / "info" / "exclude"

    verbs.route(home, rid, dest="claude-md:local", no_push=True)

    assert rid in (linked / "CLAUDE.local.md").read_text(encoding="utf-8")
    assert _block(main) == ["/CLAUDE.local.md"]
    assert _ignored(linked, "CLAUDE.local.md")
    assert _status(linked) == ""
    assert _ignored(main, "CLAUDE.local.md")  # the main checkout reads the same line
    # one lock for both checkouts, and for either mode of registration
    assert gitops.host_lock_path(linked, "plain") == gitops.commit_lock_path(main)
    assert gitops.host_lock_path(main, "plain") == gitops.host_lock_path(main, "git")


def test_one_repo_registered_twice_holds_one_lock_and_a_repoless_host_keeps_the_cache_lock(
    tmp_path,
):
    """`gitops.host_lock_path` used to give one repo two lock files when it
    was registered in two modes (claude-skills: the skills root and a
    project host), so two writers into it shared no lock."""
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "x").write_text("x\n", encoding="utf-8")
    commit_all(repo, "seed")
    assert gitops.host_lock_path(repo, "plain") == gitops.host_lock_path(repo, "git")
    held = str(gitops.host_lock_path(repo, "git"))
    with gitops.host_lock(repo, "git"):
        assert held in gitops._held_locks
        with gitops.host_lock(repo, "plain"):  # the same file: a pass-through
            assert held in gitops._held_locks
    # control: a plain host outside every repo still locks in the cache
    loose = tmp_path / "loose"
    loose.mkdir()
    cache = Path(os.environ["XDG_CACHE_HOME"]) / "self-learn"
    assert gitops.host_lock_path(loose, "plain").parent == cache


# ------------------------------------------------------- the real path


def test_a_symlinked_target_is_judged_at_its_real_path(tmp_path):
    """The host itself is in no repo (the `~/.claude` shape); its
    CLAUDE.local.md is a symlink into another repo. Tracked there:
    refused. Untracked there: the ignore line goes into THAT repo."""
    home = make_env(tmp_path).ledger
    other = tmp_path / "other-repo"
    init_repo(other)
    (other / "notes").mkdir()
    (other / "notes" / "shared.md").write_text("shared notes\n", encoding="utf-8")
    commit_all(other, "seed")
    _write_operator_lines(other)
    host = tmp_path / "linked-host"
    host.mkdir()
    host_add(home, host, "project", mode="plain")
    link = host / "CLAUDE.local.md"
    link.symlink_to(other / "notes" / "shared.md")
    rid = _lesson(home, host, "lrn-9a000008")

    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, rid, dest="claude-md:local", no_push=True)
    message = str(caught.value)
    assert f"(really {other / 'notes' / 'shared.md'})" in message
    assert f"is tracked by git in {other}" in message
    assert (other / "notes" / "shared.md").read_text(encoding="utf-8") == "shared notes\n"
    assert _block(other) is None

    (other / "notes" / "mine.md").write_text("mine\n", encoding="utf-8")
    link.unlink()
    link.symlink_to(other / "notes" / "mine.md")
    assert not _ignored(other, "notes/mine.md")  # control
    verbs.route(home, rid, dest="claude-md:local", no_push=True)
    assert rid in (other / "notes" / "mine.md").read_text(encoding="utf-8")
    assert _block(other) == ["/notes/mine.md"]
    assert _ignored(other, "notes/mine.md")
    assert "notes/mine.md" not in _status(other)
    assert not (host / ".git").exists()


# ------------------------------------------------- outside every repo


def test_a_target_outside_every_repo_passes_with_no_line_written(tmp_path):
    home = make_env(tmp_path).ledger
    loose = tmp_path / "loose-host"
    loose.mkdir()
    host_add(home, loose, "project", mode="plain")
    free = _lesson(home, loose, "lrn-9a000009")
    tracked_host = _plain_repo_host(home, tmp_path)
    held = _lesson(home, tracked_host, "lrn-9a00000a")

    verbs.route(home, free, dest="claude-md", no_push=True)
    with pytest.raises(verbs.DestinationUnavailable):
        verbs.route(home, held, dest="claude-md", no_push=True)

    assert free in (loose / "CLAUDE.md").read_text(encoding="utf-8")
    outside = subprocess.run(
        ["git", "-C", str(loose), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    assert outside.returncode != 0  # control: the host really is in no repo
    assert {p.name for p in loose.iterdir()} == {"CLAUDE.md", MARKER_FILENAME}
    assert _record(home, held).status == "pending"


# ------------------------------------------ the registration, not the path


def test_one_repo_registered_twice_follows_the_registration_each_write_goes_through(
    tmp_path,
):
    """claude-skills' shape: one repo is the skills root (here `git`) AND a
    project host (here `plain`). A skill-root write follows git rules,
    unaffected by the guard; a project-scope write into the same repo
    follows plain rules."""
    env = make_env(tmp_path)
    home, repo = env.ledger, env.host
    (home / "hosts.yaml").write_text(
        f"skills_root: {repo}\nprojects:\n  - path: {repo}\n    mode: plain\n",
        encoding="utf-8",
    )
    commit_all(home, "the project registration is plain")
    (repo / MARKER_FILENAME).write_text("plain project host\n", encoding="utf-8")
    _write_operator_lines(repo)

    skill = "lrn-9a00000b"
    create_record(home, make_behavior(scope="skill:s", record_id=skill))
    commit_all(home, f"seed {skill}")
    git_mode = verbs.route(home, skill, dest="skill-md", no_push=True)
    assert git_mode.mode == "git" and git_mode.host_commit_sha is not None
    assert skill in env.skill_md.read_text(encoding="utf-8")
    assert _status(repo) == ""  # committed, nothing left over
    assert _block(repo) is None  # git mode writes no ignore line

    tracked = _lesson(home, repo, "lrn-9a00000c")
    with pytest.raises(verbs.DestinationUnavailable):
        verbs.route(home, tracked, dest="claude-md", no_push=True)

    local = _lesson(home, repo, "lrn-9a00000d")
    head = _head(repo)
    plain_mode = verbs.route(home, local, dest="claude-md:local", no_push=True)
    assert plain_mode.mode == "plain" and plain_mode.host_commit_sha is None
    assert _head(repo) == head  # never committed
    assert _ignored(repo, "CLAUDE.local.md")
    assert _status(repo) == ""
    assert _block(repo) == ["/CLAUDE.local.md"]


def test_a_plain_skills_root_takes_a_new_hook_script_ignored_and_refuses_a_tracked_skill_md(
    tmp_path,
):
    """D-DEPLOY §0.4 hazard 2: a new warning-hook script landing in the
    (plain, autosynced) skills repo was published within seconds. Now its
    ignore line goes in first. The public SKILL.md, tracked there, is
    refused."""
    env = make_env(tmp_path)
    home, repo = env.ledger, env.host
    (home / "hosts.yaml").write_text(
        f"skills_root:\n  path: {repo}\n  mode: plain\nprojects: []\n", encoding="utf-8"
    )
    commit_all(home, "the skills root is plain")
    (repo / MARKER_FILENAME).write_text("plain skills root\n", encoding="utf-8")
    _write_operator_lines(repo)
    skill_md = env.skill_md.read_bytes()

    lesson = "lrn-9a00000e"
    create_record(home, make_behavior(scope="skill:s", record_id=lesson))
    commit_all(home, f"seed {lesson}")
    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, lesson, dest="skill-md", no_push=True)
    assert "SKILL.md is tracked by git" in str(caught.value)
    assert env.skill_md.read_bytes() == skill_md

    hook = "lrn-9a00000f"
    create_record(home, make_behavior(scope="skill:s", record_id=hook))
    write_proposal(
        home, hook,
        proposal_dict(scope="skill:s", destination="hook", alternates=["skill-md"],
                      **hook_proposal_fields()),
    )
    stamp_proposal(home, hook)
    commit_all(home, f"seed {hook}")
    head = _head(repo)
    result = verbs.route(home, hook, dest="hook", no_push=True)
    script = result.target
    assert script is not None and script.is_file()
    rel = script.relative_to(repo).as_posix()
    assert _ignored(repo, rel)  # the positive control, before the absence
    assert _status(repo) == ""
    assert _block(repo) == [f"/{rel}"]
    assert _head(repo) == head

    # Recompile's hook leg: the script and its line both lost, both back.
    script.unlink()
    _write_operator_lines(repo)
    verbs.recompile(home, no_push=True)
    assert script.is_file()
    assert _block(repo) == [f"/{rel}"]
    assert _ignored(repo, rel) and _status(repo) == ""

    # The removal leg: once its owner tracks the script, retiring the hook
    # would delete a tracked file -- refused, the script stays.
    git(repo, "add", "-f", "--", rel)
    git(repo, "commit", "-q", "-m", "track the guard script")
    with pytest.raises(verbs.NeedsPerson) as removal:
        verbs.graduate(home, hook, no_push=True)
    assert f"{rel} is tracked by git" in str(removal.value)
    assert script.is_file()
    assert _record(home, hook).status == "routed"
    assert _status(repo) == ""


def _plain_skills_root(tmp_path: Path):
    """`make_env`'s host re-registered as a PLAIN skills root only."""
    env = make_env(tmp_path)
    home, repo = env.ledger, env.host
    (home / "hosts.yaml").write_text(
        f"skills_root:\n  path: {repo}\n  mode: plain\nprojects: []\n", encoding="utf-8"
    )
    commit_all(home, "the skills root is plain")
    (repo / MARKER_FILENAME).write_text("plain skills root\n", encoding="utf-8")
    _write_operator_lines(repo)
    return home, repo


def _hook_lesson(home: Path, rid: str) -> str:
    create_record(home, make_behavior(scope="skill:s", record_id=rid))
    write_proposal(
        home, rid,
        proposal_dict(scope="skill:s", destination="hook", alternates=["skill-md"],
                      **hook_proposal_fields()),
    )
    stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")
    return rid


def test_a_hook_script_the_skills_repo_re_admits_is_refused_before_anything_is_written(
    tmp_path,
):
    home, repo = _plain_skills_root(tmp_path)
    (repo / ".gitignore").write_text("!/plugins/*/hooks/*.sh\n", encoding="utf-8")
    commit_all(repo, "re-admit hook scripts")
    rid = _hook_lesson(home, "lrn-9a000017")
    ledger_head = last_verb_sha(home)

    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, rid, dest="hook", no_push=True)

    assert "would still not be ignored by git" in str(caught.value)
    assert not list(repo.glob("plugins/*/hooks/*.sh"))
    assert _record(home, rid).status == "pending"
    assert last_verb_sha(home) == ledger_head  # a telemetry flush may ride on top
    assert _block(repo) is None


def test_recompile_never_deletes_a_retired_hook_script_its_owner_tracks(tmp_path):
    """A retired hook's script is back on disk (an interrupted removal, or
    a restore) and its owner tracks it: recompile's removal repair leaves
    it alone and says the removal is still owed."""
    home, repo = _plain_skills_root(tmp_path)
    rid = _hook_lesson(home, "lrn-9a000018")
    script = verbs.route(home, rid, dest="hook", no_push=True).target
    assert script is not None
    text = script.read_text(encoding="utf-8")
    verbs.graduate(home, rid, no_push=True)
    assert not script.exists()  # control: the untracked script was removed
    script.write_text(text, encoding="utf-8")
    rel = script.relative_to(repo).as_posix()
    git(repo, "add", "-f", "--", rel)
    git(repo, "commit", "-q", "-m", "keep the guard script")

    result = verbs.recompile(home, no_push=True)

    assert script.read_text(encoding="utf-8") == text
    (entry,) = [e for e in result.entries if e.target == script]
    assert entry.skipped == "hook removal not done — still owed"
    assert any(f"{rel} is tracked by git" in w for w in result.warnings), result.warnings
    assert _status(repo) == ""


def test_a_reference_retirement_puts_the_shelf_s_line_back_first(tmp_path):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a000019")
    verbs.route(home, rid, dest="reference", no_push=True)
    assert _block(host) == ["/CLAUDE.md", "/references/LEARNINGS.md"]
    _write_operator_lines(host)  # the block is lost
    assert not _ignored(host, "references/LEARNINGS.md")  # control

    verbs.graduate(home, rid, no_push=True)

    shelf = host / "references" / "LEARNINGS.md"
    assert rid not in shelf.read_text(encoding="utf-8")
    assert _block(host) == ["/references/LEARNINGS.md"]
    assert _ignored(host, "references/LEARNINGS.md")


def test_a_renamed_away_path_still_counts_as_tracked_until_the_rename_is_committed(
    tmp_path,
):
    """`git mv CLAUDE.md` leaves the old name in HEAD only (gone from the
    index and the disk). Writing a fresh CLAUDE.md there would change what
    git shows next to the staged rename: refused."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    git(host, "mv", "CLAUDE.md", "NOTES.md")
    rid = _lesson(home, host, "lrn-9a000014")
    status = _status(host)

    with pytest.raises(verbs.DestinationUnavailable) as caught:
        verbs.route(home, rid, dest="claude-md", no_push=True)

    assert "CLAUDE.md is tracked by git" in str(caught.value)
    assert not (host / "CLAUDE.md").exists()
    assert _status(host) == status
    assert _record(home, rid).status == "pending"


def test_the_write_itself_checks_again_when_the_file_was_tracked_after_the_pre_flight(
    tmp_path, monkeypatch
):
    """The pre-flight passed (stood in for here: the file was tracked after
    it ran); the host phase checks once more under the host lock and writes
    nothing into the tracked file. The ledger's own commit stands -- canon
    is stale, never lost (H-2), and the warning says so."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _lesson(home, host, "lrn-9a000015")
    claude_md = (host / "CLAUDE.md").read_bytes()
    # `raising=False`: on a tree without the guard this stand-in changes
    # nothing, and the route writes into the tracked file -- the failure
    # this test exists to show.
    monkeypatch.setattr(
        verbs, "_refuse_unsafe_plain_write", lambda spec, removal=False: None, raising=False
    )

    result = verbs.route(home, rid, dest="claude-md", no_push=True)

    assert _record(home, rid).status == "routed"  # the ledger commit landed
    assert any("HOST PHASE FAILED" in w and "is tracked by git" in w for w in result.warnings)
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _exclude(host).read_text(encoding="utf-8") == OPERATOR_LINES
    assert _status(host) == ""


def test_recompile_repairs_a_plain_hosts_shelf_without_committing_it(tmp_path):
    """A plain host's shelf, lost from disk, is re-appended by recompile:
    ignored first, never committed (the reference leg used to stage and
    commit in every mode)."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a000016")
    verbs.route(home, rid, dest="reference", no_push=True)
    shelf = host / "references" / "LEARNINGS.md"
    assert rid in shelf.read_text(encoding="utf-8")  # control
    shelf.unlink()
    head = _head(host)

    result = verbs.recompile(home, no_push=True)

    assert rid in shelf.read_text(encoding="utf-8")
    assert [e for e in result.entries if e.target == shelf] == [
        verbs.RecompileEntry(target=shelf, changed=True)
    ]
    assert _head(host) == head  # never committed
    assert _ignored(host, "references/LEARNINGS.md")
    assert _status(host) == ""
    assert _block(host) == ["/CLAUDE.md", "/references/LEARNINGS.md"]


# ------------------------------------------------------------ removals


def test_a_retirement_out_of_a_tracked_file_is_refused_for_a_person(tmp_path):
    """The lesson was written while CLAUDE.md was untracked; then its
    owner started tracking it. Taking the lesson out would change a
    tracked file: refused (`needs-person` -- no choice of destination
    moves lines that already sit there), nothing written."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a000010")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    assert rid in (host / "CLAUDE.md").read_text(encoding="utf-8")  # control
    git(host, "add", "-f", "CLAUDE.md")
    git(host, "commit", "-q", "-m", "track CLAUDE.md after all")
    claude_md = (host / "CLAUDE.md").read_bytes()
    ledger_head = last_verb_sha(home)
    sheet = _sheet(tmp_path, [{"id": rid, "verb": "graduate"}])

    preview = batch.dry_run(home, sheet, actor="human")
    result = batch.run(home, sheet, no_push=True, actor="human")

    (pitem,), (item,) = preview.items, result.items
    assert (pitem.state, pitem.kind) == ("would-refuse", "needs-person"), pitem.detail
    assert (item.state, item.kind) == ("refused", "needs-person"), item.detail
    assert "CLAUDE.md is tracked by git" in (item.detail or "")
    assert _record(home, rid).status == "routed"
    assert last_verb_sha(home) == ledger_head  # a telemetry flush may ride on top
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _status(host) == ""


def test_recompile_restores_a_lost_ignore_line_and_leaves_a_tracked_target_alone(tmp_path):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path, track_claude_md=False)
    rid = _lesson(home, host, "lrn-9a000011")
    verbs.route(home, rid, dest="claude-md", no_push=True)
    assert _block(host) == ["/CLAUDE.md"]
    _write_operator_lines(host)  # the block is lost
    assert not _ignored(host, "CLAUDE.md")  # control

    first = verbs.recompile(home, no_push=True)

    assert _block(host) == ["/CLAUDE.md"]
    assert _ignored(host, "CLAUDE.md")
    assert not [e for e in first.entries if e.skipped], first.entries

    git(host, "add", "-f", "CLAUDE.md")
    git(host, "commit", "-q", "-m", "track CLAUDE.md")
    (host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")  # lesson gone
    git(host, "commit", "-q", "-am", "drop the section by hand")
    before = (host / "CLAUDE.md").read_bytes()

    second = verbs.recompile(home, no_push=True)

    (skipped,) = [e for e in second.entries if e.skipped]
    assert skipped.target == host / "CLAUDE.md"
    assert "is tracked by git" in (skipped.skipped or "")
    assert (host / "CLAUDE.md").read_bytes() == before
    assert _status(host) == ""


# ------------------------------------------------------- the two runners


def test_the_overseer_run_reports_the_refusal(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _lesson(home, host, "lrn-9a000012")
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "project", "question": "where does this go?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")
    claude_md = (host / "CLAUDE.md").read_bytes()
    _enabled(monkeypatch)
    items = [{"id": rid, "verb": "route", "dest": "claude-md"}]
    successor = _with_always_loaded({
        "kind": "resolution", "trigger": "weekly", "outcome": "route",
        "records": [rid], "scope": "project", "question": "where does this go?",
        "supersedes": parked,
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "route", "because": "it applies here", "confidence": "settled"},
    }, items)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-tracked.yaml", successor)
            _dump(spec.cwd / "sheet-tracked.yaml", {"version": 1, "items": items})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True)

    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.partition("## Refused / could not do")[2].split("\n## ", 1)[0]
    assert refused.strip(), report  # positive control: the section rendered
    assert "CLAUDE.md is tracked by git" in refused, refused
    assert "[destination-unavailable]" in refused, refused
    assert _record(home, rid).status == "pending"
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _status(host) == ""


def test_the_steward_s_repair_turn_sees_the_refusal_and_its_fix_applies(
    tmp_path, monkeypatch
):
    """The steward routes a project lesson into the host's tracked
    CLAUDE.md. The ledger's preview refuses that line
    (`destination-unavailable`), so the one repair turn hears it the same
    night and moves the lesson to CLAUDE.local.md, which applies."""
    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _seed(
        home, "lrn-9a000013", scope="project",
        record=make_behavior(record_id="lrn-9a000013", scope="project"),
        project_path=host,
    )
    _enable_steward(home)
    _notifications(monkeypatch)
    claude_md = (host / "CLAUDE.md").read_bytes()
    host_head = _head(host)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        dest = "claude-md:local" if _REPAIR_HEADER in spec.prompt else "claude-md"
        items = [{"id": rid, "verb": "route", "dest": dest}]
        stage = _stage_dir(spec)
        _dump_yaml(
            stage / "cases" / f"{rid}.yaml",
            _with_always_loaded(_case([rid], "route", "route", scope="project"), items),
        )
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID", "items": items})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 2, "one decision session, then the repair turn"
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert _LEDGER_REPAIR in repair
    assert f"(route {rid})" in repair
    assert "CLAUDE.md is tracked by git" in repair
    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    routing = _record(home, rid).routing or {}
    assert (routing.get("destination"), routing.get("variant")) == ("claude-md", "local")
    assert rid in (host / "CLAUDE.local.md").read_text(encoding="utf-8")
    assert _ignored(host, "CLAUDE.local.md")
    assert _status(host) == ""
    assert (host / "CLAUDE.md").read_bytes() == claude_md
    assert _head(host) == host_head
