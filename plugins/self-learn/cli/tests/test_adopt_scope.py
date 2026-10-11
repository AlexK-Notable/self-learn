"""`recompile --adopt <target>` re-records only the named region(s) and
stops (S-83). The user, 2026-10-08 17:49: "`recompile --adopt <target>`
re-records only that target and stops; today it recompiles every host."

Found live 2026-10-08: adopting one hand-edited CLAUDE.md wrote the adopt
entry, then carried on through the whole recompile, re-rendering and
committing every registered host (it committed into an unrelated skills
repo). An adopt run now makes its adopt commit(s) and nothing else: no
render, no reference re-append, no pointer write, no hook re-apply, no
resync batch commit, no host commit and no host push. The ledger commit is
pushed as any single-commit verb's is (`--no-push` skips it). A plain
`recompile` afterwards does the rest.

Every scenario: one ledger, two registered hosts -- a PLAIN project host
holding the region adopted, and the sandbox's GIT host (`make_env`), whose
CLAUDE.md carries drift an ordinary recompile repairs with a host commit.
No model is called.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from self_learn import cli, compiled, gitops, sentinel, verbs
from self_learn.compilers import _LEARNINGS_HEADER, BEGIN_MARKER, POINTER_BEGIN_MARKER
from self_learn.hosts import host_add, host_slug
from self_learn.ledger_ops import create_record
from support import commit_all, git, make_behavior, make_env

PERSONS_NOTE = "A person's own note, kept by hand.\n"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


# ------------------------------------------------------------------ helpers


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _subjects_since(repo: Path, base: str) -> list[str]:
    out = git(repo, "log", "--format=%s", f"{base}..HEAD").stdout
    return [line for line in out.splitlines() if line]


def _route(env, host: Path, rid: str, dest: str) -> None:
    record = make_behavior(scope="project", record_id=rid, instruction=f"Do {rid}.")
    create_record(env.ledger, record, project_path=host)
    verbs.route(env.ledger, rid, dest=dest, no_push=True)


def _plain_host(env, tmp_path: Path) -> Path:
    host = tmp_path / "adopt-plain"
    host.mkdir()
    host_add(env.ledger, host, "project", mode="plain")
    return host


def _drift_the_git_host(env) -> Path:
    """The git host's CLAUDE.md written back to the bytes it held before
    its second lesson, and committed: the `stale` verdict, which never
    refuses -- drift an ordinary recompile repairs by re-rendering and
    committing in the host."""
    target = env.host / "CLAUDE.md"
    _route(env, env.host, "lrn-0ad0a001", "claude-md")
    stale = target.read_text(encoding="utf-8")
    _route(env, env.host, "lrn-0ad0a002", "claude-md")
    assert "lrn-0ad0a002" in target.read_text(encoding="utf-8")
    target.write_text(stale, encoding="utf-8")
    commit_all(env.host, "the git host's CLAUDE.md back to stale bytes")
    return target


def _hand_edit(path: Path, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert marker in text  # the region exists
    path.write_text(text.replace(marker, marker + "\nhand edit"), encoding="utf-8")


def _entry(env, host: Path, target: Path, kind: str):
    slug = host_slug(env.ledger, host, scope_kind="project")
    return compiled.entry_for(
        compiled.load_record(env.ledger, slug),
        compiled.region_key(host, target, kind), region=kind,
    )


def _region_sha(target: Path, kind: str) -> str:
    region = compiled.region_bytes(target.read_text(encoding="utf-8"), kind)
    assert region is not None
    return compiled.sha256_hex(region)


def _assert_only_the_adopt(env, before: dict, adopted: list[tuple[Path, Path, str]]) -> None:
    """The adopt run's whole footprint: the git host untouched (bytes and
    history), and exactly one ledger commit per adopted region, each under
    the pinned subject and nothing else."""
    git_claude = env.host / "CLAUDE.md"
    assert git_claude.read_bytes() == before["git_bytes"]
    assert _head(env.host) == before["git_head"]
    keys = [compiled.region_key(host, target, kind) for host, target, kind in adopted]
    assert _subjects_since(env.ledger, before["ledger_head"]) == [
        f"self-learn: recompile --adopt {key}" for key in reversed(keys)
    ]
    for host, target, kind in adopted:
        entry = _entry(env, host, target, kind)
        assert entry is not None and entry["sha256"] == _region_sha(target, kind)


def _snapshot(env) -> dict:
    # `create_record` leaves a new bucket's meta.yaml uncommitted in the
    # sandbox; commit the setup so every later commit is the run's own.
    if git(env.ledger, "status", "--porcelain").stdout:
        commit_all(env.ledger, "test setup")
    assert git(env.ledger, "status", "--porcelain").stdout == ""  # control: clean ledger
    return {
        "git_bytes": (env.host / "CLAUDE.md").read_bytes(),
        "git_head": _head(env.host),
        "ledger_head": _head(env.ledger),
    }


def _plain_recompile_repairs_the_git_host(env, before: dict) -> None:
    """Positive control: the drift the adopt run left is real, and an
    ordinary recompile still repairs it with a host commit."""
    result = verbs.recompile(env.ledger, no_push=True)
    git_claude = env.host / "CLAUDE.md"
    assert git_claude.read_bytes() != before["git_bytes"]
    assert "lrn-0ad0a002" in git_claude.read_text(encoding="utf-8")
    assert _head(env.host) != before["git_head"]
    assert result.adopt_only is False


# ---------------------------------------------------------- the three kinds


def test_a_managed_adopt_touches_no_other_host_and_makes_one_commit(env, tmp_path):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0b001", "claude-md")
    target = plain / "CLAUDE.md"
    _hand_edit(target, BEGIN_MARKER)
    _drift_the_git_host(env)
    before = _snapshot(env)
    plain_bytes = target.read_bytes()

    result = verbs.recompile(env.ledger, no_push=True, adopt=target)

    assert target.read_bytes() == plain_bytes  # adopted, never rendered over
    assert [e.target for e in result.entries] == [target]
    _assert_only_the_adopt(env, before, [(plain, target, "managed")])
    _plain_recompile_repairs_the_git_host(env, before)
    assert result.adopt_only is True


def test_a_pointer_adopt_touches_no_other_host_and_makes_one_commit(env, tmp_path):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0c001", "reference")
    surface = plain / "CLAUDE.md"
    _hand_edit(surface, POINTER_BEGIN_MARKER)
    _drift_the_git_host(env)
    before = _snapshot(env)
    plain_bytes = surface.read_bytes()

    result = verbs.recompile(env.ledger, no_push=True, adopt=f"{surface}#pointer")

    assert surface.read_bytes() == plain_bytes
    assert [e.target for e in result.entries] == [surface]
    _assert_only_the_adopt(env, before, [(plain, surface, "pointer")])
    _plain_recompile_repairs_the_git_host(env, before)
    assert result.adopt_only is True


def test_a_shelf_adopt_touches_no_other_host_and_makes_one_commit(env, tmp_path):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0d001", "reference")
    shelf = plain / "references" / "LEARNINGS.md"
    shelf.write_text(shelf.read_text(encoding="utf-8") + PERSONS_NOTE, encoding="utf-8")
    _drift_the_git_host(env)
    before = _snapshot(env)
    shelf_bytes = shelf.read_bytes()

    result = verbs.recompile(env.ledger, no_push=True, adopt=shelf)

    assert shelf.read_bytes() == shelf_bytes
    assert [e.target for e in result.entries] == [shelf]
    _assert_only_the_adopt(env, before, [(plain, shelf, "reference")])
    _plain_recompile_repairs_the_git_host(env, before)
    assert result.adopt_only is True


def test_several_named_regions_are_all_adopted_and_nothing_else(env, tmp_path):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0e001", "reference")
    _route(env, plain, "lrn-0ad0e002", "claude-md")
    claude = plain / "CLAUDE.md"
    _hand_edit(claude, POINTER_BEGIN_MARKER)
    _hand_edit(claude, BEGIN_MARKER)
    _drift_the_git_host(env)
    before = _snapshot(env)

    result = verbs.recompile(env.ledger, no_push=True, adopt=[str(claude), f"{claude}#pointer"])

    # the pointer pass runs before the managed pass
    _assert_only_the_adopt(
        env, before, [(plain, claude, "pointer"), (plain, claude, "managed")]
    )
    assert result.adopt_only is True


# ------------------------------------------------------- what is not adopted


def test_an_unmatched_managed_path_warns_and_the_run_still_stops(env, tmp_path):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    _drift_the_git_host(env)
    before = _snapshot(env)
    nowhere = tmp_path / "nowhere" / "CLAUDE.md"

    result = verbs.recompile(env.ledger, no_push=True, adopt=nowhere)

    assert any(
        str(nowhere.resolve()) in w and "no routed managed target at this path" in w
        for w in result.warnings
    ), result.warnings
    assert result.entries == []
    _assert_only_the_adopt(env, before, [])
    _plain_recompile_repairs_the_git_host(env, before)
    assert result.adopt_only is True


# --------------------------------------------------------------- the order


def test_a_shelf_adopted_without_its_live_entry_gets_it_back_on_the_next_recompile(
    env, tmp_path
):
    """Gate SH2b F1's order after S-83: the adopt records the shelf's bytes
    as they stand (a live lesson's entry taken out by hand); the reference
    leg that appends that entry back no longer runs in the same call. The
    next plain `recompile` appends it and re-records the shelf, so the
    record and the disk agree, and a third call has nothing to do."""
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0f001", "reference")
    shelf = plain / "references" / "LEARNINGS.md"
    assert "lrn-0ad0f001" in shelf.read_text(encoding="utf-8")  # control
    shelf.write_text(_LEARNINGS_HEADER + PERSONS_NOTE, encoding="utf-8")
    hand_bytes = shelf.read_bytes()

    verbs.recompile(env.ledger, no_push=True, adopt=shelf)

    assert shelf.read_bytes() == hand_bytes  # nothing appended in the adopt run
    adopted = _entry(env, plain, shelf, "reference")
    assert adopted is not None and adopted["sha256"] == _region_sha(shelf, "reference")

    result = verbs.recompile(env.ledger, no_push=True)

    text = shelf.read_text(encoding="utf-8")
    assert "lrn-0ad0f001" in text and PERSONS_NOTE in text
    assert not result.warnings, result.warnings
    entry = _entry(env, plain, shelf, "reference")
    assert entry is not None and entry["sha256"] == _region_sha(shelf, "reference")
    assert compiled.verdict_for(entry, _region_sha(shelf, "reference")) == "clean"
    head = _head(env.ledger)
    third = verbs.recompile(env.ledger, no_push=True)
    assert not third.warnings, third.warnings
    assert _head(env.ledger) == head
    assert shelf.read_text(encoding="utf-8") == text


# ------------------------------------------------------------------ pushes


def test_an_adopt_run_pushes_the_ledger_and_no_host(env, tmp_path, monkeypatch):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0a101", "claude-md")
    target = plain / "CLAUDE.md"
    _hand_edit(target, BEGIN_MARKER)
    _drift_the_git_host(env)
    pushed: list[Path] = []

    def spy(repo, *, is_ledger=False):
        pushed.append(Path(repo).resolve())
        return gitops.PushResult(ok=True)

    monkeypatch.setattr(gitops, "push_if_remote", spy)

    result = verbs.recompile(env.ledger, adopt=target)

    assert pushed == [env.ledger.resolve()]
    assert result.ledger_push is not None and result.ledger_push.ok

    # control: the same spy sees the git host's push on a plain recompile
    pushed.clear()
    verbs.recompile(env.ledger)
    assert env.host.resolve() in pushed
    assert result.adopt_only is True


def test_an_adopt_run_that_commits_nothing_pushes_nothing(env, tmp_path, monkeypatch):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    _drift_the_git_host(env)
    pushed: list[Path] = []
    monkeypatch.setattr(
        gitops, "push_if_remote",
        lambda repo, *, is_ledger=False: pushed.append(Path(repo)) or gitops.PushResult(ok=True),
    )

    result = verbs.recompile(env.ledger, adopt=tmp_path / "nowhere" / "CLAUDE.md")

    assert pushed == []
    assert result.adopt_only is True and result.ledger_push is None


# -------------------------------------------------------------------- CLI


def test_the_cli_says_only_the_adopt_was_done(env, tmp_path, capsys):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0a201", "claude-md")
    target = plain / "CLAUDE.md"
    _hand_edit(target, BEGIN_MARKER)
    _drift_the_git_host(env)
    capsys.readouterr()

    rc = cli.main(["recompile", "--no-push", "--adopt", str(target)])

    out = capsys.readouterr().out
    assert rc == 0
    assert f"recompile: {target} — adopted" in out
    assert "the rest of the recompile was not run" in out
    assert "`self-learn recompile`" in out
    assert "no managed targets" not in out


def test_the_cli_names_an_adopt_run_that_matched_nothing(env, tmp_path, capsys):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    nowhere = tmp_path / "nowhere" / "CLAUDE.md"

    rc = cli.main(["recompile", "--no-push", "--adopt", str(nowhere)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "no routed managed target at this path" in captured.err
    assert "no managed targets (no routed records)" not in captured.out
    assert "nothing was adopted" in captured.out
    assert "the rest of the recompile was not run" in captured.out


# --------------------------------------------- the automatic adopt proceeds


def test_a_plain_recompile_still_self_adopts_and_proceeds(env, tmp_path, capsys):
    """Out of S-83's scope, and pinned so it stays so: the AUTOMATIC adopt
    of an `unknown provenance` region whose bytes equal what the compiler
    renders (doc 17 `recompile --adopt` section) prints its notice and the
    recompile carries on to every other target. Only an explicit `--adopt`
    stops. The plain host's target sorts first, so the git host's repair
    below proves the run went on past it."""
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0a301", "claude-md")
    target = plain / "CLAUDE.md"
    git_claude = _drift_the_git_host(env)
    assert str(target) < str(git_claude)  # control: the self-adopt comes first
    shutil.rmtree(env.ledger / "compiled")
    commit_all(env.ledger, "no compile records yet (a host from before them)")
    before = _snapshot(env)
    plain_bytes = target.read_bytes()
    capsys.readouterr()

    result = verbs.recompile(env.ledger, no_push=True)

    err = capsys.readouterr().err
    assert f"self-learn: adopting {target}" in err
    assert target.read_bytes() == plain_bytes
    assert not [e for e in result.entries if e.skipped], result.entries
    assert git_claude.read_bytes() != before["git_bytes"]  # the run went on
    assert _head(env.host) != before["git_head"]
    assert result.adopt_only is False


# ------------------------------------------- fold r1: the managed no-op


def _managed_adopt_setup(env, tmp_path) -> Path:
    plain = _plain_host(env, tmp_path)
    _route(env, plain, "lrn-0ad0a401", "claude-md")
    target = plain / "CLAUDE.md"
    _hand_edit(target, BEGIN_MARKER)
    _snapshot(env)  # commits the setup
    return target


@pytest.mark.parametrize("clock", ["same second", "later second"])
def test_adopting_a_managed_region_twice_commits_once(env, tmp_path, monkeypatch, capsys, clock):
    """The managed pass has the pointer and shelf passes' "already accepted
    as it stands" no-op. Without it the second adopt rewrote the entry: in
    the same second the ledger commit had nothing to commit (exit 6,
    HalfWrittenError); in a later second only `at:` moved, a redundant
    `recompile --adopt` commit that an adopt run also pushes."""
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    ticks = iter(["2026-10-09T10:00:00Z", "2026-10-09T10:00:00Z" if clock == "same second"
                  else "2026-10-09T10:00:07Z"])
    monkeypatch.setattr(compiled, "_now_iso", lambda: next(ticks))
    base = _head(env.ledger)

    first = cli.main(["recompile", "--no-push", "--adopt", str(target)])
    assert first == 0
    assert "adopted (its own ledger commit)" in capsys.readouterr().out  # control
    second = cli.main(["recompile", "--no-push", "--adopt", str(target)])

    captured = capsys.readouterr()
    assert second == 0, captured.err
    assert f"recompile: {target} — already accepted as it stands" in captured.out
    assert "already accepted as it stands — nothing to adopt" in captured.err
    assert "nothing was adopted" in captured.out
    key = compiled.region_key(target.parent, target, "managed")
    assert _subjects_since(env.ledger, base) == [f"self-learn: recompile --adopt {key}"]


# ------------------------------------------------ fold r2/r3: the push pins


def _push_spy(monkeypatch, ok: bool = True) -> list[Path]:
    pushed: list[Path] = []

    def spy(repo, *, is_ledger=False):
        pushed.append(Path(repo).resolve())
        return gitops.PushResult(ok=ok, detail="" if ok else "refused")

    monkeypatch.setattr(gitops, "push_if_remote", spy)
    return pushed


def test_an_adopt_run_under_no_push_has_no_ledger_push(env, tmp_path, monkeypatch):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    pushed = _push_spy(monkeypatch)
    base = _head(env.ledger)

    result = verbs.recompile(env.ledger, no_push=True, adopt=target)

    assert len(_subjects_since(env.ledger, base)) == 1  # control: a commit landed
    assert pushed == []
    assert result.ledger_push is None


def test_the_cli_says_an_adopt_under_no_push_was_not_pushed(env, tmp_path, monkeypatch, capsys):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    pushed = _push_spy(monkeypatch)

    rc = cli.main(["recompile", "--no-push", "--adopt", str(target)])

    assert rc == 0
    assert pushed == []
    assert "1 region(s) adopted (ledger not pushed — --no-push)" in capsys.readouterr().out


def test_a_failed_ledger_push_after_an_adopt_is_the_exit_status(
    env, tmp_path, monkeypatch, capsys
):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    pushed = _push_spy(monkeypatch, ok=False)

    rc = cli.main(["recompile", "--adopt", str(target)])

    out = capsys.readouterr().out
    assert "adopted (its own ledger commit)" in out  # control: the adopt landed
    assert pushed == [env.ledger.resolve()]  # control: the push was tried
    assert rc == gitops.EXIT_PUSH_FAILED
    assert "PUSH FAILED" in out


# ------------------------------------------------ fold n1: the sentinel hold


def test_an_adopt_run_releases_the_sentinel_hold(env, tmp_path, monkeypatch):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    assert not sentinel.is_live()  # control: nobody holds it before
    live_during: list[bool] = []
    real_adopt_entry = compiled.adopt_entry

    def spy(*args, **kwargs):
        live_during.append(sentinel.is_live())
        return real_adopt_entry(*args, **kwargs)

    monkeypatch.setattr(compiled, "adopt_entry", spy)

    result = verbs.recompile(env.ledger, no_push=True, adopt=target)

    assert result.adopt_only is True
    assert live_during == [True]  # control: the run held it while adopting
    assert not sentinel.is_live()


def test_an_adopt_run_that_raises_releases_the_sentinel_hold(env, tmp_path, monkeypatch):
    # S-83 (user, 2026-10-08): --adopt re-records only that target and stops.
    target = _managed_adopt_setup(env, tmp_path)
    assert not sentinel.is_live()  # control: nobody holds it before
    live_during: list[bool] = []

    def boom(*args, **kwargs):
        live_during.append(sentinel.is_live())
        raise OSError("adopt entry write failed")

    monkeypatch.setattr(compiled, "adopt_entry", boom)

    with pytest.raises(OSError, match="adopt entry write failed"):
        verbs.recompile(env.ledger, no_push=True, adopt=target)

    assert live_during == [True]  # control: the run held it when it raised
    assert not sentinel.is_live()
