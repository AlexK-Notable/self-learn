"""``gitops.stage_and_commit`` — the M-O seam (audit 2026-09-02 sprint-1
plan v2 §2), replacing three copy-pasted try/except blocks:
``hosts._commit_or_half_written``, ``settings._commit_or_half_written``,
and ``verbs._commit_ledger``.

Design pin, inherited from round 3/round 7 (``test_round7_fixes.py``'s own
stated pin): **no mocks**. A commit failure is produced by a REAL ``git``
that really fails (``support.failing_git_shim``), never by monkeypatching
the code under test. "Nothing to commit" is produced by a REAL
byte-identical rewrite — the same shape ``settings.py``'s own comments
describe hitting live (a re-``set`` of an unchanged value used to crash
with a false "WRITE NOT COMMITTED" before ``config_set``'s idempotent
pre-check existed).

One test class per former copy proves the seam reproduces that copy's
exact behaviour: nothing-to-commit raises ``HalfWrittenError``, a commit
failure raises it too with the touched paths in the repair, and the call
works unchanged whether or not the caller already holds
``gitops.commit_lock`` — the function is lock-agnostic, it neither takes
one nor requires the absence of one."""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import gitops, hosts, settings, verbs
from support import commit_all, failing_git_shim, git, init_repo


def _seed(tmp_path: Path, name: str, rel: str = "a/f.txt", content: str = "hello\n") -> tuple[Path, Path]:
    """A fresh repo with one tracked, already-committed file — the state
    every former copy's caller reaches this seam in: something already on
    disk, HEAD not yet moved to include it."""
    repo = tmp_path / name
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    init_repo(repo)
    commit_all(repo, "seed")
    return repo, path


def _rewrite(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ============================================================ positive control


def test_a_real_commit_lands(tmp_path):
    """The brief's positive control: a genuine change, staged and
    committed through the seam, really lands — HEAD moves, the tree is
    clean, and the returned sha IS the new HEAD."""
    repo, path = _seed(tmp_path, "positive")
    _rewrite(path, "changed\n")

    sha = gitops.stage_and_commit(repo, [path], "self-learn: test change")

    assert sha == git(repo, "rev-parse", "HEAD").stdout.strip()
    assert not git(repo, "status", "--porcelain").stdout.strip()
    subject = git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == "self-learn: test change"


# ==================================================== nothing-to-commit union


class TestNothingToCommit:
    """Union of the three copies' behaviour (pinned decision): none of
    them special-cased "nothing to commit" internally — each instead
    guards with its OWN idempotent pre-check before ever reaching a
    commit call. The default (``allow_empty=False``) reproduces that
    byte-for-byte; ``allow_empty=True`` is the other half of the union,
    for a caller with no pre-check of its own."""

    def test_default_reproduces_the_false_half_written_all_three_copies_hit(
        self, tmp_path
    ):
        """Exactly the bug ``settings.py``'s own comments describe: a
        byte-identical rewrite makes ``git commit`` fail "nothing to
        commit", and — with no idempotent guard upstream of this seam —
        that becomes ``HalfWrittenError``, not a silent no-op."""
        repo, path = _seed(tmp_path, "nothing-default")
        _rewrite(path, "hello\n")  # byte-identical to the seeded content

        with pytest.raises(gitops.HalfWrittenError) as excinfo:
            gitops.stage_and_commit(repo, [path], "self-learn: no-op")

        assert str(path) in excinfo.value.repair
        assert not git(repo, "status", "--porcelain").stdout.strip(), (
            "a byte-identical rewrite must not leave the tree dirty — "
            "`git add` on unchanged content stages nothing"
        )

    def test_allow_empty_returns_none_instead_of_a_false_half_written(
        self, tmp_path
    ):
        """The flag half of the union: a future caller with no pre-check
        of its own opts into a real no-op instead of a false alarm."""
        repo, path = _seed(tmp_path, "nothing-allow-empty")
        before = git(repo, "rev-parse", "HEAD").stdout.strip()
        _rewrite(path, "hello\n")  # byte-identical again

        result = gitops.stage_and_commit(
            repo, [path], "self-learn: no-op", allow_empty=True
        )

        assert result is None
        assert git(repo, "rev-parse", "HEAD").stdout.strip() == before

    def test_allow_empty_still_commits_a_real_change(self, tmp_path):
        """The flag must not swallow a REAL diff — only a genuine no-op."""
        repo, path = _seed(tmp_path, "nothing-allow-empty-real-diff")
        _rewrite(path, "changed for real\n")

        sha = gitops.stage_and_commit(
            repo, [path], "self-learn: real change", allow_empty=True
        )

        assert sha is not None
        assert sha == git(repo, "rev-parse", "HEAD").stdout.strip()


# ======================================================= commit failure union


def test_commit_failure_becomes_half_written_with_the_touched_paths(
    tmp_path, monkeypatch
):
    """A REAL git commit failure (not "nothing to commit") — the shape
    round 7 BLOCKER 2 fixed: the write already happened (staged, on
    disk), the commit did not, and the exception must say so with a
    literal repair naming the touched path."""
    repo, path = _seed(tmp_path, "commit-failure")
    _rewrite(path, "changed\n")
    flag = failing_git_shim(tmp_path, monkeypatch)  # sub="commit"
    flag.touch()
    try:
        with pytest.raises(gitops.HalfWrittenError) as excinfo:
            gitops.stage_and_commit(repo, [path], "self-learn: will fail")
    finally:
        flag.unlink()

    assert str(path) in excinfo.value.repair
    assert f"git -C {repo}" in excinfo.value.repair
    # post-mutation by construction: staged, not committed
    assert "f.txt" in git(repo, "status", "--porcelain").stdout


def test_a_failing_stage_becomes_half_written_not_a_bare_giterror(
    tmp_path, monkeypatch
):
    """Fold r1 BLOCKER 1. ``stage`` is exactly as post-mutation as
    ``commit`` — the caller's own write already landed on disk before
    either is ever called — so a failing ``git add`` must convert to
    :class:`gitops.HalfWrittenError` (exit 7, "here is the repair") the
    same way a failing ``git commit`` does, never surface as a bare
    :class:`gitops.GitOpsError` (exit 6, "nothing was written" — false
    here, the worktree write is real)."""
    repo, path = _seed(tmp_path, "stage-failure")
    _rewrite(path, "changed\n")
    flag = failing_git_shim(tmp_path, monkeypatch, sub="add")
    flag.touch()
    try:
        with pytest.raises(gitops.HalfWrittenError) as excinfo:
            gitops.stage_and_commit(repo, [path], "self-learn: add will fail")
    finally:
        flag.unlink()

    assert str(path) in excinfo.value.repair


def test_paths_are_actually_staged_by_the_seam(tmp_path, monkeypatch):
    """Fold r1 MINOR 2. The seam's own ``stage()`` call, observed
    directly rather than inferred from a commit landing: ``git commit --
    <paths>`` reads WORKTREE content and bypasses the index (see
    :func:`gitops.commit`'s own docstring), so a positive-control commit
    landing does not, by itself, prove ``stage()`` ran. Forcing the
    COMMIT to fail (not the add) leaves the index exactly as ``stage()``
    left it — proving the paths were really staged, not just that a
    commit eventually happened to land."""
    repo, path = _seed(tmp_path, "stage-observed")
    _rewrite(path, "changed\n")
    flag = failing_git_shim(tmp_path, monkeypatch)  # sub="commit"
    flag.touch()
    try:
        with pytest.raises(gitops.HalfWrittenError):
            gitops.stage_and_commit(repo, [path], "self-learn: will fail")
    finally:
        flag.unlink()

    assert gitops.staged_diff(repo, [path]).strip(), (
        "the path was never staged — stage_and_commit's own stage() call "
        "did not run (or ran too late to be observed)"
    )


# ============================================================= lock-agnostic


def test_lock_agnostic_works_nested_inside_an_already_held_commit_lock(
    tmp_path
):
    """Every real caller today already holds (or itself opens)
    ``gitops.commit_lock`` around this seam — ``hosts``/``settings`` hold
    it before calling; ``verbs._stage_and_commit`` opens it itself. The
    seam must work identically either way, since it takes no lock of its
    own (measured: it is re-entrant via `commit_lock`'s `_held_locks` set,
    so nesting cannot deadlock, but the seam does not even try — this
    proves calling it under an already-open lock behaves exactly like the
    unlocked positive control above)."""
    repo, path = _seed(tmp_path, "lock-agnostic")
    _rewrite(path, "changed\n")

    with gitops.commit_lock(repo):
        sha = gitops.stage_and_commit(repo, [path], "self-learn: nested")

    assert sha == git(repo, "rev-parse", "HEAD").stdout.strip()
    assert not git(repo, "status", "--porcelain").stdout.strip()


# ================================================== the three delegates' shape


class TestHostsShapeDelegate:
    """``hosts._commit_or_half_written(home, touched, message)`` — no
    body, three real call sites (``host_add``, a rename, ``host_remove``),
    all holding ``gitops.commit_lock(home)`` already."""

    def test_positive_commit_lands(self, tmp_path):
        repo, path = _seed(tmp_path, "hosts-positive")
        _rewrite(path, "changed\n")
        with gitops.commit_lock(repo):
            hosts._commit_or_half_written(repo, [path], "self-learn: host add x")
        assert not git(repo, "status", "--porcelain").stdout.strip()
        assert git(repo, "log", "-1", "--format=%s").stdout.strip() == (
            "self-learn: host add x"
        )

    def test_nothing_to_commit_raises_half_written(self, tmp_path):
        repo, path = _seed(tmp_path, "hosts-nothing")
        _rewrite(path, "hello\n")
        with gitops.commit_lock(repo):
            with pytest.raises(gitops.HalfWrittenError):
                hosts._commit_or_half_written(repo, [path], "self-learn: no-op")

    def test_commit_failure_raises_half_written(self, tmp_path, monkeypatch):
        repo, path = _seed(tmp_path, "hosts-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    hosts._commit_or_half_written(
                        repo, [path], "self-learn: will fail"
                    )
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair

    def test_stage_failure_raises_half_written_not_a_bare_giterror(
        self, tmp_path, monkeypatch
    ):
        """Fold r1 BLOCKER 1, through the real delegate."""
        repo, path = _seed(tmp_path, "hosts-stage-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch, sub="add")
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    hosts._commit_or_half_written(
                        repo, [path], "self-learn: add will fail"
                    )
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair


class TestSettingsShapeDelegate:
    """``settings._commit_or_half_written(home, touched, message, body)``
    — the one copy that also threads a commit BODY (``config set --note``
    / ``config unset --note``), both call sites already holding
    ``gitops.commit_lock(home)``."""

    def test_body_lands_as_the_commit_body(self, tmp_path):
        repo, path = _seed(tmp_path, "settings-body")
        _rewrite(path, "changed\n")
        with gitops.commit_lock(repo):
            settings._commit_or_half_written(
                repo, [path], "self-learn: config set x=1", "a note"
            )
        body = git(repo, "log", "-1", "--format=%b").stdout.strip()
        assert body == "a note"

    def test_nothing_to_commit_raises_half_written_with_a_body_too(self, tmp_path):
        repo, path = _seed(tmp_path, "settings-nothing")
        _rewrite(path, "hello\n")
        with gitops.commit_lock(repo):
            with pytest.raises(gitops.HalfWrittenError):
                settings._commit_or_half_written(
                    repo, [path], "self-learn: no-op", "a note"
                )

    def test_commit_failure_raises_half_written(self, tmp_path, monkeypatch):
        repo, path = _seed(tmp_path, "settings-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    settings._commit_or_half_written(
                        repo, [path], "self-learn: will fail", None
                    )
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair

    def test_stage_failure_raises_half_written_not_a_bare_giterror(
        self, tmp_path, monkeypatch
    ):
        """Fold r1 BLOCKER 1, through the real delegate."""
        repo, path = _seed(tmp_path, "settings-stage-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch, sub="add")
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    settings._commit_or_half_written(
                        repo, [path], "self-learn: add will fail", None
                    )
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair


class TestVerbsShapeDelegate:
    """``verbs._commit_ledger(home, touched, message, note=None)`` — the
    one copy with its own return contract, ``(staged, sha)``, that every
    one of its 14 call-line occurrences (13 external + the one internal
    delegation inside ``verbs._stage_and_commit``) unpacks. All lexically
    inside ``with _ledger_write(home):`` (== ``gitops.commit_lock``)."""

    def test_returns_staged_and_sha_with_note_as_body(self, tmp_path):
        repo, path = _seed(tmp_path, "verbs-positive")
        _rewrite(path, "changed\n")
        with gitops.commit_lock(repo):
            staged, sha = verbs._commit_ledger(
                repo, [path], "self-learn: reject lrn-x", "why"
            )
        assert staged == [path]
        assert sha == git(repo, "rev-parse", "HEAD").stdout.strip()
        assert git(repo, "log", "-1", "--format=%b").stdout.strip() == "why"

    def test_nothing_to_commit_raises_half_written(self, tmp_path):
        repo, path = _seed(tmp_path, "verbs-nothing")
        _rewrite(path, "hello\n")
        with gitops.commit_lock(repo):
            with pytest.raises(gitops.HalfWrittenError):
                verbs._commit_ledger(repo, [path], "self-learn: no-op")

    def test_commit_failure_raises_half_written(self, tmp_path, monkeypatch):
        repo, path = _seed(tmp_path, "verbs-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    verbs._commit_ledger(repo, [path], "self-learn: will fail")
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair

    def test_stage_failure_raises_half_written_not_a_bare_giterror(
        self, tmp_path, monkeypatch
    ):
        """Fold r1 BLOCKER 1, through the real delegate."""
        repo, path = _seed(tmp_path, "verbs-stage-failure")
        _rewrite(path, "changed\n")
        flag = failing_git_shim(tmp_path, monkeypatch, sub="add")
        flag.touch()
        try:
            with gitops.commit_lock(repo):
                with pytest.raises(gitops.HalfWrittenError) as excinfo:
                    verbs._commit_ledger(
                        repo, [path], "self-learn: add will fail"
                    )
        finally:
            flag.unlink()
        assert str(path) in excinfo.value.repair
