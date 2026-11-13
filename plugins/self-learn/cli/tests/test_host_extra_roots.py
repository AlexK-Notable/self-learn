"""``hosts.extra_roots`` (2026-11-12): the overseer may register a plain project
strictly inside the home directory OR strictly inside a root the user lists
for a directory on another disk. Invented paths under ``tmp_path``; ``HOME``
is ``tmp_path/home``, so everything under ``tmp_path/disk`` is outside it.

Mutations (each makes the named test fail):
- accept ``real == root`` -> ``test_the_root_itself_is_refused``;
- ignore the setting in ``registration_problem`` -> ``test_a_directory_under_a_listed_root_is_accepted``;
- drop the setting's name from the refusal sentence -> ``test_a_directory_under_neither_names_the_setting``;
- let ``/`` or a missing directory count -> ``test_an_unusable_root_is_ignored_and_reported``;
- skip a later check when the directory is under a root -> ``test_the_other_checks_still_refuse_under_a_root``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from self_learn import attribution, hosts, settings
from self_learn.hosts import registration_problem
from self_learn.overseer import run as overseer_run
from support import make_env


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)


def _list_roots(ledger: Path, *roots: object) -> None:
    (ledger / "config.yaml").write_text(
        "hosts:\n  extra_roots: " + os.pathsep.join(str(r) for r in roots) + "\n", encoding="utf-8"
    )


def _outside(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "disk" / "games"
    proj = root / "SomeGame"
    proj.mkdir(parents=True)
    return root, proj


def test_a_directory_under_a_listed_root_is_accepted(tmp_path):
    env = make_env(tmp_path)
    root, proj = _outside(tmp_path)
    assert registration_problem(env.ledger, str(proj)) is not None  # control: refused unlisted
    _list_roots(env.ledger, root)
    assert registration_problem(env.ledger, str(proj)) is None
    deeper = proj / "bin" / "x64"
    deeper.mkdir(parents=True)
    assert registration_problem(env.ledger, str(deeper)) is None  # any depth below the root
    # the real overseer path registers it, plain
    with attribution.job("overseer"):
        result = hosts.register_plain_project(env.ledger, str(proj), note="n")
    assert result.hosts.project_modes[str(proj.resolve())] == "plain"


def test_a_root_given_through_a_symlink_compares_real_paths(tmp_path):
    env = make_env(tmp_path)
    root, proj = _outside(tmp_path)
    link = tmp_path / "link-to-games"
    link.symlink_to(root)
    _list_roots(env.ledger, link)
    assert registration_problem(env.ledger, str(proj)) is None
    assert registration_problem(env.ledger, str(link / "SomeGame")) is None


def test_the_root_itself_is_refused(tmp_path):
    env = make_env(tmp_path)
    root, proj = _outside(tmp_path)
    _list_roots(env.ledger, root)
    assert registration_problem(env.ledger, str(proj)) is None  # control
    refusal = registration_problem(env.ledger, str(root))
    assert refusal is not None and "hosts.extra_roots" in refusal
    assert "home directory" in registration_problem(env.ledger, str(tmp_path / "home"))  # $HOME stays refused


def test_a_directory_under_neither_names_the_setting(tmp_path):
    env = make_env(tmp_path)
    root, _proj = _outside(tmp_path)
    other = tmp_path / "disk" / "other" / "thing"
    other.mkdir(parents=True)
    _list_roots(env.ledger, root)
    refusal = registration_problem(env.ledger, str(other))
    assert refusal is not None
    assert "home directory" in refusal and "hosts.extra_roots" in refusal


def test_an_unusable_root_is_ignored_and_reported(tmp_path):
    env = make_env(tmp_path)
    _root, proj = _outside(tmp_path)
    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")
    _list_roots(env.ledger, "/", tmp_path / "missing", "relative/dir", a_file)
    good, bad = settings.host_extra_roots(env.ledger)
    assert good == []
    assert len(bad) == 4
    assert any("filesystem root" in b for b in bad)
    assert any("not an existing directory" in b and "missing" in b for b in bad)
    assert any("not an absolute path" in b for b in bad)
    # `/` listed: a directory elsewhere is still refused (nothing admitted)
    assert registration_problem(env.ledger, str(proj)) is not None
    assert registration_problem(env.ledger, "/usr") is not None
    rows = [r for r in settings.preflight(env.ledger) if r.name == "hosts.extra_roots" and r.verdict == "WARN"]
    assert len(rows) == 4


def test_a_root_the_user_does_not_own_is_ignored(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    root, proj = _outside(tmp_path)
    _list_roots(env.ledger, root)
    assert registration_problem(env.ledger, str(proj)) is None  # control
    monkeypatch.setattr(os, "getuid", lambda: os.stat(root).st_uid + 1)
    good, bad = settings.host_extra_roots(env.ledger)
    assert good == [] and any("not owned" in b for b in bad)
    assert registration_problem(env.ledger, str(proj)) is not None


def test_the_other_checks_still_refuse_under_a_root(tmp_path):
    env = make_env(tmp_path)
    # the root holds the ledger, the cache and the registered host: all strictly under it
    _list_roots(env.ledger, tmp_path)
    cache = Path(os.environ["XDG_CACHE_HOME"]) / "self-learn" / "x"
    cache.mkdir(parents=True)
    fresh = tmp_path / "disk" / "fresh"
    fresh.mkdir(parents=True)
    assert registration_problem(env.ledger, str(fresh)) is None  # control: the root works
    assert "the ledger" in registration_problem(env.ledger, str(env.ledger / "projects"))
    assert "the ledger" in registration_problem(env.ledger, str(env.ledger))
    assert "cache" in registration_problem(env.ledger, str(cache))
    assert "already registered" in registration_problem(env.ledger, str(env.host))
    assert "not an existing directory" in registration_problem(env.ledger, str(tmp_path / "disk" / "gone"))
    assert "not an absolute path" in registration_problem(env.ledger, "disk/fresh")

    with attribution.job("overseer"):
        hosts.register_plain_project(env.ledger, str(fresh), note="n")
    hosts.host_remove(env.ledger, fresh, registration="project")
    assert "taken out of the registry" in registration_problem(env.ledger, str(fresh))


def test_the_overseer_report_line_for_a_refused_outside_directory_names_the_setting(tmp_path):
    env = make_env(tmp_path)
    _root, proj = _outside(tmp_path)
    manifest = {"run_id": "run-00000000000c", "registrations": [
        {"path": str(proj), "case": "case-0000000c", "why": "w"},
    ]}
    notes: list[str] = []
    with attribution.job("overseer"):
        overseer_run._register_hosts(env.ledger, manifest, notes)
    assert manifest["registrations"][0]["result"] == "refused"
    assert len(notes) == 1 and "hosts.extra_roots" in notes[0]
