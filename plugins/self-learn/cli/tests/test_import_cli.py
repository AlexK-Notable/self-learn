"""T11: CLI wiring for the T9 importers — `import --backlog <skill>`,
`import --memory DIR`, `prune-memory [--dry-run] DIR`.

Module behavior is T9's suite (test_import_backlog / test_import_memory);
these tests cover the CLI surface: flag parsing, the report .summary()
printout, exit codes, and the memory-dir refusal. The REAL
auto-memory directory is never resolved in tests — every invocation
passes an explicit dir or the SELF_LEARN_MEMORY_DIR env override.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from self_learn import cli
from self_learn.import_memory import import_memory
from self_learn.ledger_ops import resolve_record

from support import make_env

FIXTURES = Path(__file__).parent / "fixtures"
SKILL = "home-assistant"


@pytest.fixture
def env(tmp_path, monkeypatch):
    # project_path for --memory imports defaults to git-toplevel of cwd;
    # pin it to a sandbox repo so nothing real is resolved.
    e = make_env(tmp_path, skills=(SKILL,))
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.delenv("SELF_LEARN_MEMORY_DIR", raising=False)
    monkeypatch.chdir(e.host)
    return e


@pytest.fixture
def home(env):
    return env.ledger


def seed_journal(env) -> None:
    # doc 13 §2: the journal lives in the HOST skill dir, not the ledger.
    refs = env.skill_dir / "references"
    refs.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "gotchas-journal-excerpt.md", refs / "GOTCHAS.journal.md")
    shutil.copy(FIXTURES / "gotchas-canon-excerpt.md", refs / "GOTCHAS.md")


def memory_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "memory"
    shutil.copytree(FIXTURES / "memory", dest)
    return dest


# ---------------------------------------------------------------- backlog


def test_import_backlog_prints_summary_exit_0(env, capsys):
    seed_journal(env)
    rc = cli.main(["import", "--backlog", SKILL])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("import --backlog: 7 created")
    assert out.count("+ lrn-") == 7


def test_import_backlog_rerun_is_idempotent_at_cli_level(env, capsys):
    seed_journal(env)
    assert cli.main(["import", "--backlog", SKILL]) == 0
    capsys.readouterr()
    rc = cli.main(["import", "--backlog", SKILL])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("import --backlog: 0 created")


def test_import_backlog_unknown_skill_is_usage_error(home, capsys):
    rc = cli.main(["import", "--backlog", "no-such-skill"])
    assert rc == 64
    assert capsys.readouterr().err


def test_import_backlog_missing_journal_exits_1(home, capsys):
    rc = cli.main(["import", "--backlog", SKILL])  # bucket ok, no journal
    assert rc == 1
    assert "no journal" in capsys.readouterr().err


# ----------------------------------------------------------------- memory


def test_import_memory_explicit_dir(home, tmp_path, capsys):
    mem = memory_copy(tmp_path)
    rc = cli.main(["import", "--memory", str(mem)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("import --auto-memory: 3 created")


def test_import_memory_env_override_supplies_default(home, tmp_path, capsys, monkeypatch):
    # Bare `--memory`: the default dir comes from SELF_LEARN_MEMORY_DIR when
    # set — the pinned real path is never touched by this test.
    mem = memory_copy(tmp_path)
    monkeypatch.setenv("SELF_LEARN_MEMORY_DIR", str(mem))
    rc = cli.main(["import", "--memory"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("import --auto-memory: 3 created")


def test_default_memory_dir_is_none_without_env(monkeypatch):
    # No built-in default: the only derivable candidate would guess Claude
    # Code's undocumented, many-to-one projects-dir slug scheme, and
    # prune-memory deletes at this path — refusing is the safe answer.
    monkeypatch.delenv("SELF_LEARN_MEMORY_DIR", raising=False)
    assert cli.default_memory_dir() is None


def test_import_memory_bare_without_env_is_usage_error(home, capsys):
    rc = cli.main(["import", "--memory"])
    assert rc == 64
    err = capsys.readouterr().err
    assert "--memory" in err
    assert "SELF_LEARN_MEMORY_DIR" in err


def test_import_memory_missing_dir_exits_1(home, tmp_path, capsys):
    rc = cli.main(["import", "--memory", str(tmp_path / "nope")])
    assert rc == 1
    assert "no memory directory" in capsys.readouterr().err


def test_import_requires_exactly_one_source(home, capsys):
    assert cli.main(["import"]) == 2
    assert cli.main(["import", "--backlog", SKILL, "--memory", "/x"]) == 2


# ------------------------------------------------------------ prune-memory


def test_prune_memory_dry_run_prints_summary(home, tmp_path, capsys):
    mem = memory_copy(tmp_path)
    assert cli.main(["import", "--memory", str(mem)]) == 0
    capsys.readouterr()

    rc = cli.main(["prune-memory", "--dry-run", str(mem)])
    assert rc == 0
    out = capsys.readouterr().out
    # Freshly imported records are pending (in flight) — the sweep refuses
    # them and, being a dry run, edits nothing.
    assert out.startswith("memory prune sweep (dry run):")
    assert "3 in-flight refused" in out
    assert (mem / "MEMORY.md").exists()


def test_prune_memory_live_run_on_untouched_ledger_prunes_nothing(home, tmp_path, capsys):
    mem = memory_copy(tmp_path)
    assert cli.main(["import", "--memory", str(mem)]) == 0
    capsys.readouterr()
    before = sorted(p.name for p in mem.glob("*.md"))

    rc = cli.main(["prune-memory", str(mem)])
    assert rc == 0
    assert capsys.readouterr().out.startswith("memory prune sweep (live):")
    assert sorted(p.name for p in mem.glob("*.md")) == before


def test_prune_memory_bare_without_env_is_usage_error_and_mutates_nothing(
    home, tmp_path, capsys
):
    # Seed a ledger with a TERMINAL auto-memory record whose origin file
    # still exists in a real memory dir, so a wrongly-reached sweep WOULD
    # have something to prune — the guard must stop it before that, not
    # merely happen to leave nothing behind.
    mem = memory_copy(tmp_path)
    report = import_memory(home, mem)
    rid = report.created[0]
    resolve_record(home, rid, "rejected")
    filename = report.origins[rid].split("/", 1)[1].split("#", 1)[0]
    target = mem / filename
    assert target.exists()  # precondition: the sweep would have work to do
    before = (mem / "MEMORY.md").read_bytes()

    rc = cli.main(["prune-memory"])
    assert rc == 64
    assert "SELF_LEARN_MEMORY_DIR" in capsys.readouterr().err
    assert target.exists()
    assert (mem / "MEMORY.md").read_bytes() == before
