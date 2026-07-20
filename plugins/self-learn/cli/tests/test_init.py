"""C1 §2 `self-learn init` verb (docs/specs/self-learn/drafts/
c1-portability-defects-spec.md rev 7): the ledger-home bootstrap.

Obligations covered here: O-1 through O-5, O-10, O-12, O-13, O-16. O-6
through O-9 and O-11 (doc/manifest content) live in
test_portability_docs.py. O-14/O-15 are withdrawn (carved to C3) and are
deliberately NOT implemented here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from self_learn import cli, gitops
from self_learn.hosts import is_repo_root
from self_learn.ledger import (
    INIT_COMMIT_SUBJECT,
    _LAYOUT,
    InitError,
    home_state,
    init_home,
)
from support import commit_all, git, init_repo


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _has_head(repo: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _subjects(repo: Path) -> list[str]:
    return git(repo, "log", "--format=%s").stdout.strip().splitlines()


@pytest.fixture(autouse=True)
def git_identity(tmp_path, monkeypatch):
    """Deterministic global git identity for `init`'s `--allow-empty`
    commits (mirrors test_hosting.py's fixture of the same name for the
    ratified `host add --init` precedent)."""
    cfg = tmp_path / "gitconfig-global"
    cfg.write_text(
        "[user]\n\tname = Test\n\temail = test@example.com\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    for var in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
    return cfg


# ---------------------------------------------------------------------- O-1


def test_o1_missing_path_creates_full_layout_and_head(tmp_path):
    target = tmp_path / "brand-new-home"
    result = init_home(target)
    assert result.created_repo is True
    assert result.made_head is True
    assert set(result.added_dirs) == set(_LAYOUT)
    assert is_repo_root(target)
    for name in _LAYOUT:
        assert (target / name).is_dir()
    assert home_state(target) == "ok"
    assert _subjects(target) == [INIT_COMMIT_SUBJECT]


# ---------------------------------------------------------------------- O-2


def test_o2_complete_ledger_reports_already_complete_and_mutates_nothing(tmp_path):
    """Rev 2's version of this obligation mandated the OPPOSITE — a
    refusal — because `home_state` is an any-of predicate (MAJOR A). This
    is the corrected version: nothing missing + HEAD exists → no-op."""
    target = tmp_path / "complete-home"
    init_repo(target)
    for name in _LAYOUT:
        (target / name).mkdir()
    git(target, "commit", "--allow-empty", "-m", "seed")
    before = _head(target)

    result = init_home(target)

    assert result.already_complete is True
    assert result.added_dirs == ()
    assert result.made_head is False
    assert result.created_repo is False
    assert _head(target) == before  # byte-for-byte: no new commit


# ---------------------------------------------------------------------- O-3


def test_o3_empty_non_repo_dir_inits_in_place(tmp_path):
    target = tmp_path / "empty-dir"
    target.mkdir()
    result = init_home(target)
    assert result.created_repo is True
    assert is_repo_root(target)
    for name in _LAYOUT:
        assert (target / name).is_dir()
    assert _subjects(target) == [INIT_COMMIT_SUBJECT]


# ---------------------------------------------------------------------- O-4


def test_o4_non_empty_non_repo_dir_refuses(tmp_path):
    target = tmp_path / "non-empty-dir"
    target.mkdir()
    (target / "foo.txt").write_text("data\n", encoding="utf-8")
    with pytest.raises(InitError, match="non-empty"):
        init_home(target)
    assert not (target / ".git").exists()
    assert (target / "foo.txt").read_text(encoding="utf-8") == "data\n"


def test_o4_regular_file_refuses(tmp_path):
    target = tmp_path / "a-file"
    target.write_text("not a dir\n", encoding="utf-8")
    with pytest.raises(InitError, match="not a directory"):
        init_home(target)
    assert target.is_file()


# ---------------------------------------------------------------------- O-5


def test_o5_no_remote_added_and_a_later_push_skips_cleanly(tmp_path):
    target = tmp_path / "no-remote-home"
    init_home(target)
    assert git(target, "remote").stdout.strip() == ""
    result = gitops.push_if_remote(target)
    assert result.ok is True
    assert result.skipped is True


# --------------------------------------------------------------------- O-10


def test_o10_existing_repo_with_no_head_gets_one(tmp_path):
    target = tmp_path / "no-head-home"
    init_repo(target)  # git init, no commit
    assert not _has_head(target)

    result = init_home(target)

    assert result.made_head is True
    assert _has_head(target)
    assert set(result.added_dirs) == set(_LAYOUT)


def test_o10_partial_layout_completes_without_refusing(tmp_path):
    """The MAJOR-A case: a `--user` capture creates exactly user/ +
    telemetry/, so `home_state` reads `ok` — and must NOT be the gate
    (P-C1.14)."""
    target = tmp_path / "partial-home"
    init_repo(target)
    (target / "user").mkdir()
    (target / "telemetry").mkdir()
    git(target, "commit", "--allow-empty", "-m", "seed")
    assert home_state(target) == "ok"  # the any-of predicate already fires

    result = init_home(target)

    assert result.already_complete is False
    assert set(result.added_dirs) == {"skills", "projects"}
    for name in _LAYOUT:
        assert (target / name).is_dir()


# --------------------------------------------------------------------- O-12


def test_o12_nested_empty_dir_gets_own_repo_parent_stays_tracked_clean(tmp_path):
    parent = tmp_path / "parent-repo"
    init_repo(parent)
    (parent / "README.md").write_text("parent\n", encoding="utf-8")
    commit_all(parent, "parent seed")
    parent_head_before = _head(parent)

    nested = parent / "ledger"
    nested.mkdir()

    result = init_home(nested)

    assert result.created_repo is True
    assert is_repo_root(nested)

    # P-C1.21: assert TRACKED state, never filesystem cleanliness — a
    # legitimate nested ledger DOES put real dirs under the parent's work
    # tree (`?? ledger/` in `git status` is correct, not a failure).
    diff = subprocess.run(
        ["git", "-C", str(parent), "diff-index", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 0, diff.stdout + diff.stderr
    tracked = subprocess.run(
        ["git", "-C", str(parent), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout
    assert "ledger/" not in tracked
    status = subprocess.run(
        ["git", "-C", str(parent), "status", "--porcelain"],
        capture_output=True,
        text=True,
    ).stdout
    assert "?? ledger/" in status  # untracked presence is expected
    assert _head(parent) == parent_head_before


def test_o12_nested_non_empty_dir_refuses(tmp_path):
    parent = tmp_path / "parent-repo-2"
    init_repo(parent)
    (parent / "README.md").write_text("parent\n", encoding="utf-8")
    commit_all(parent, "parent seed")

    nested = parent / "ledger"
    nested.mkdir()
    (nested / "notes.txt").write_text("stuff\n", encoding="utf-8")

    with pytest.raises(InitError, match="non-empty"):
        init_home(nested)

    assert not (nested / ".git").exists()
    diff = subprocess.run(
        ["git", "-C", str(parent), "diff-index", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 0, diff.stdout + diff.stderr


# --------------------------------------------------------------------- O-13


def test_o13_fifo_refuses_cleanly_never_a_raw_mkdir_error(tmp_path):
    target = tmp_path / "a-fifo"
    os.mkfifo(target)
    with pytest.raises(InitError, match="not a directory"):
        init_home(target)
    assert not target.is_dir()


# --------------------------------------------------------------------- O-16


def test_o16_dangling_symlink_refuses(tmp_path):
    """P-C1.24: the step-2 check MUST key on `os.path.lexists`, not
    `exists()` — a dangling symlink is exists()==False, lexists()==True,
    so an exists()-keyed check falls through to step 3 and crashes on a
    raw `mkdir` FileExistsError. This is the test that fails if the pin
    is ignored."""
    missing_target = tmp_path / "nonexistent-target"
    link = tmp_path / "dangling-link"
    link.symlink_to(missing_target)
    assert os.path.lexists(link)
    assert not link.exists()  # confirms the dangling shape empirically

    with pytest.raises(InitError, match="not a directory"):
        init_home(link)

    # never touched — still the same dangling link, not a directory
    assert os.path.lexists(link)
    assert not link.is_dir()


# ------------------------------------------------------------- CLI wiring


def test_cli_init_success_line_names_the_resolved_path(tmp_path, monkeypatch, capsys):
    target = tmp_path / "cli-home"
    monkeypatch.setenv("SELF_LEARN_HOME", str(target))
    rc = cli.main(["init"])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(target) in out
    assert is_repo_root(target)


def test_cli_init_echoes_even_on_refusal(tmp_path, monkeypatch, capsys):
    target = tmp_path / "cli-bad-home"
    target.write_text("not a dir\n", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_HOME", str(target))
    rc = cli.main(["init"])
    assert rc != 0
    out = capsys.readouterr().out
    assert str(target) in out  # P-C1.10: echoed before the refusal


# ------------------------------------------------------- code-gate folds
#
# MAJOR 1 / MAJOR 2 from the C1 blind code gate. The gate found that the
# obligation set (O-1..O-16) did not reach the "raw OSError escapes as a
# traceback" class at all, and could not see step 6's unlocked commit.
# These are the tests that fail when either fold is reverted.


def test_init_refuses_cleanly_when_parent_is_a_regular_file(tmp_path):
    """MAJOR 1: `$SELF_LEARN_HOME=<a-regular-file>/ledger` raised a raw
    NotADirectoryError. Exit 1 is ALSO the refusal code, so a crash was
    indistinguishable from a clean refusal by exit status alone."""
    afile = tmp_path / "afile"
    afile.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(InitError) as exc:
        init_home(afile / "ledger")
    assert "cannot create" in str(exc.value)
    assert not (afile / "ledger").exists()


def test_init_refuses_cleanly_when_parent_is_unwritable(tmp_path):
    """MAJOR 1: an unwritable parent raised a raw PermissionError."""
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        with pytest.raises(InitError) as exc:
            init_home(parent / "ledger")
        assert "cannot create" in str(exc.value)
    finally:
        parent.chmod(0o700)


def test_init_topup_refuses_cleanly_on_readonly_ledger(tmp_path):
    """MAJOR 1, the step-6 leg — P-C1.16 calls this the path a real user
    is most likely to take, and it raised a raw PermissionError."""
    home = tmp_path / "ledger"
    home.mkdir()
    init_repo(home)
    (home / "user").mkdir()
    # The delta code gate caught this test choosing the ONE read-only
    # variant that dodged the bug the MAJOR-2 fold introduced: chmod on
    # the top dir alone leaves .git writable, so commit_lock's raw
    # mkdir+open never fired. chmod -R is the natural "read-only ledger".
    for d in sorted(home.rglob("*"), reverse=True):
        if d.is_dir():
            d.chmod(0o500)
    home.chmod(0o500)
    try:
        with pytest.raises(InitError) as exc:
            init_home(home)
        msg = str(exc.value)
        assert "cannot create" in msg or "cannot take the commit lock" in msg
    finally:
        home.chmod(0o700)
        for d in home.rglob("*"):
            if d.is_dir():
                d.chmod(0o700)


def test_init_refuses_cleanly_on_unreadable_directory(tmp_path):
    """NIT 6: an unreadable dir refused with step 4's message, which names
    foreign files that may not exist. It gets its own words now."""
    home = tmp_path / "ledger"
    home.mkdir()
    home.chmod(0o300)  # write+exec, not readable
    try:
        with pytest.raises(InitError) as exc:
            init_home(home)
        msg = str(exc.value)
        assert "cannot read" in msg
        assert "non-empty" not in msg
    finally:
        home.chmod(0o700)


def test_init_topup_holds_the_commit_lock(tmp_path, monkeypatch):
    """MAJOR 2: step 6 is the only init path that mutates a repo
    self-learn did not just create. `git commit --allow-empty` commits
    whatever is STAGED, so an unlocked step 6 lets a racing producer's
    staged index land under INIT_COMMIT_SUBJECT."""
    home = tmp_path / "ledger"
    home.mkdir()
    init_repo(home)
    (home / "user").mkdir()

    taken: list[Path] = []
    real = gitops.commit_lock

    def _spy(repo, **kw):
        taken.append(Path(repo))
        return real(repo, **kw)

    monkeypatch.setattr(gitops, "commit_lock", _spy)
    result = init_home(home)

    assert taken == [home.resolve()], "step 6 must take the repo's commit_lock"
    assert set(result.added_dirs) == set(_LAYOUT) - {"user"}


def test_init_does_not_create_parent_chain(tmp_path):
    """NIT 9: `mkdir(parents=True)` silently materialized a whole chain
    for a mistyped deep $SELF_LEARN_HOME — the failure P-C1.10 exists to
    make visible. §2.2 step 3 says "create dir", singular."""
    deep = tmp_path / "a" / "b" / "c" / "ledger"
    with pytest.raises(InitError):
        init_home(deep)
    assert not (tmp_path / "a").exists()
